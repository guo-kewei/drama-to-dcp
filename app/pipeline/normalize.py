"""阶段三：逐集归一化——视频画幅/帧率统一 + 音频响度归一化 + 上混引擎。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

from ..core.task import Episode, TaskState, container_size
from ..engines import LAYOUT_CHANNELS, get_upmix_engine
from ..tools.ffmpeg import FFmpeg

ProgressFn = Callable[[float], None]


# ---------------------------------------------------------------- 视频滤镜链
def video_filter(cw: int, ch: int, fit_mode: str) -> str:
    """生成画幅转换滤镜链。fill=缩放覆盖+中心裁切；fit=缩放适应+黑边。"""
    if fit_mode == "fit":
        return (f"fps=24,"
                f"scale={cw}:{ch}:force_original_aspect_ratio=decrease:"
                f"flags=lanczos,"
                f"pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:black,setsar=1")
    return (f"fps=24,"
            f"scale={cw}:{ch}:force_original_aspect_ratio=increase:"
            f"flags=lanczos,"
            f"crop={cw}:{ch},setsar=1")


def normalize_video_args(src: Path, dst: Path, cw: int, ch: int,
                         fit_mode: str) -> list[str]:
    return ["-i", str(src), "-an",
            "-vf", video_filter(cw, ch, fit_mode),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
            "-pix_fmt", "yuv420p", str(dst)]


# ---------------------------------------------------------------- 音频链
def _loudnorm_analyse(ff: FFmpeg, src: Path, pre: str, cancel_flag=None) -> dict:
    """loudnorm 第一遍：测量响度参数。pre 为前置滤镜（如单声道转立体声）。"""
    chain = pre + ("loudnorm=I=-23:TP=-2.0:LRA=7:print_format=json"
                   if not pre else
                   ",loudnorm=I=-23:TP=-2.0:LRA=7:print_format=json")
    r = ff.run(["-i", str(src), "-map", "0:a:0", "-vn", "-af", chain,
                "-f", "null", "-"], cancel_flag=cancel_flag)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r, re.S)
    if not m:
        raise RuntimeError("loudnorm 分析失败：未能解析测量结果")
    return json.loads(m.group(0))


def _loudnorm_apply_params(m: dict) -> str:
    return (f"loudnorm=I=-23:TP=-2.0:LRA=7"
            f":measured_I={m.get('input_i')}"
            f":measured_LRA={m.get('input_lra')}"
            f":measured_TP={m.get('input_tp')}"
            f":measured_thresh={m.get('input_thresh')}"
            f":offset={m.get('target_offset')}"
            f":linear=true:print_format=summary")


def normalize_audio_stereo(ff: FFmpeg, src: Path, dst_stereo_wav: Path,
                           src_channels: int,
                           on_progress: Optional[ProgressFn] = None,
                           cancel_flag=None) -> None:
    """任意源 → 响度归一化的 48k/24bit 立体声 WAV（上混引擎的标准输入）。"""
    pre = ""
    if src_channels == 1:
        pre = "pan=stereo|c0=c0|c1=c0,"      # 单声道→立体声
    elif src_channels > 2:
        # >2 声道（如 5.1/6ch）先下混立体声（保留对白）
        pre = "pan=stereo|c0=FL+0.707*FC+0.707*BL|c1=FR+0.707*FC+0.707*BR,"
    m = _loudnorm_analyse(ff, src, pre.rstrip(","), cancel_flag)
    ff.run(["-i", str(src), "-map", "0:a:0", "-vn",
            "-af", pre + _loudnorm_apply_params(m),
            "-ar", "48000", "-c:a", "pcm_s24le", str(dst_stereo_wav)],
           on_progress=on_progress,
           total_seconds=_dur_of(ff, src), cancel_flag=cancel_flag)


def extract_multichannel(ff: FFmpeg, src: Path, dst_wav: Path,
                         layout: str, cancel_flag=None) -> None:
    """多声道源(≥6ch)直通/重排为 DCP 顺序 Nch WAV（不经引擎、不响度归一）。"""
    n = LAYOUT_CHANNELS[layout]
    src_n = _audio_channels(ff, src)
    if src_n >= n:
        # 按位直取前 n 声道（5.1 源顺序 FL FR FC LFE BL BR 与 DCP 一致）
        pan = "pan=" + f"{n}c|" + "|".join(f"c{i}=c{i}" for i in range(n))
    else:
        raise RuntimeError(f"源声道不足({src_n}ch)无法直通到 {layout}")
    ff.run(["-i", str(src), "-map", "0:a:0", "-vn", "-af", pan,
            "-ar", "48000", "-c:a", "pcm_s24le", str(dst_wav)],
           cancel_flag=cancel_flag)


# ---------------------------------------------------------------- 阶段入口
def normalize_episode(ff: FFmpeg, state: TaskState, ep: Episode,
                      workdir: Path, cfg_engine: dict,
                      on_progress: Optional[ProgressFn] = None,
                      log=None,
                      cancel_flag=None,
                      src_override: Optional[Path] = None) -> tuple[Path, Path]:
    """归一化单集 → (norm/ep_xxx.mp4, norm/ep_xxx.wav)。

    src_override：超分等前置引擎处理后的替代源（默认用 ep.path 原片）。
    """
    norm = workdir / "norm"
    norm.mkdir(parents=True, exist_ok=True)
    src = Path(src_override) if src_override else Path(ep.path)
    v_dst = norm / f"ep_{ep.index:03d}.mp4"
    a_dst = norm / f"ep_{ep.index:03d}.wav"
    st_dst = norm / f"ep_{ep.index:03d}_st.wav"

    cw, ch = container_size(state.resolved_container, state.config.resolution)
    # ---- 视频
    ff.run(normalize_video_args(src, v_dst, cw, ch, state.config.fit_mode),
           on_progress=(lambda p: on_progress(p * 0.6)) if on_progress else None,
           total_seconds=ep.duration, cancel_flag=cancel_flag)

    # ---- 音频（无音轨的集生成目标布局的静音，任何布局均兜底）
    layout = state.config.audio_layout
    channels = LAYOUT_CHANNELS[layout]
    if ep.audio_channels == 0:
        _silent_wav(ff, a_dst, ep.duration, channels)
    elif layout == "stereo":
        normalize_audio_stereo(ff, src, a_dst, ep.audio_channels,
                               on_progress=(lambda p: on_progress(0.6 + p * 0.4)) if on_progress else None,
                               cancel_flag=cancel_flag)
    elif ep.audio_channels >= 6:
        # 多声道源直通（不经上混引擎、不做响度归一）
        extract_multichannel(ff, src, a_dst, layout, cancel_flag=cancel_flag)
    else:
        # 立体声归一化 → 上混引擎
        normalize_audio_stereo(ff, src, st_dst, ep.audio_channels,
                               on_progress=(lambda p: on_progress(0.6 + p * 0.2)) if on_progress else None,
                               cancel_flag=cancel_flag)
        engine = get_upmix_engine(state.config.upmix_engine)
        if layout not in engine.layouts:
            raise RuntimeError(f"上混引擎 {engine.id} 不支持布局 {layout}")
        engine.process(st_dst, a_dst, layout, ff, cfg_engine,
                       on_progress=(lambda p: on_progress(0.8 + p * 0.2)) if on_progress else None)
        st_dst.unlink(missing_ok=True)
    return v_dst, a_dst


# ---------------------------------------------------------------- 辅助
def _dur_of(ff: FFmpeg, src: Path) -> float:
    try:
        info = ff.probe(src)
        return float(info.get("format", {}).get("duration") or 0)
    except Exception:
        return 0.0


def _audio_channels(ff: FFmpeg, src: Path) -> int:
    info = ff.probe(src)
    a = next((s for s in info.get("streams", [])
              if s.get("codec_type") == "audio"), None)
    return int(a.get("channels") or 0) if a else 0


def _silent_wav(ff: FFmpeg, dst: Path, seconds: float, channels: int) -> None:
    if channels <= 2:
        ff.run(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-t", f"{seconds:.3f}", "-c:a", "pcm_s24le", str(dst)])
    else:
        pan = "pan=" + f"{channels}c|" + "|".join(f"c{i}=0*c0" for i in range(channels))
        ff.run(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-af", pan, "-t", f"{seconds:.3f}",
                "-c:a", "pcm_s24le", str(dst)])
