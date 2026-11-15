"""阶段四：拼接——视频流复制拼接 + 音频拼接（含集间黑场/静音过渡）。"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from ..core.task import TaskState, container_size
from ..engines import LAYOUT_CHANNELS
from ..tools.ffmpeg import FFmpeg

ProgressFn = Callable[[float], None]


def _make_gap_video(ff: FFmpeg, dst: Path, cw: int, ch: int,
                    seconds: float) -> None:
    ff.run(["-f", "lavfi", "-i", f"color=c=black:s={cw}x{ch}:r=24",
            "-t", f"{seconds:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
            "-pix_fmt", "yuv420p", str(dst)])


def _make_gap_audio(ff: FFmpeg, dst: Path, channels: int, seconds: float) -> None:
    if channels <= 2:
        ff.run(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-t", f"{seconds:.3f}", "-c:a", "pcm_s24le", str(dst)])
    else:
        pan = "pan=" + f"{channels}c|" + "|".join(f"c{i}=0*c0" for i in range(channels))
        ff.run(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-af", pan, "-t", f"{seconds:.3f}",
                "-c:a", "pcm_s24le", str(dst)])


def _esc(p: Path) -> str:
    return str(p).replace("'", "'\\''")


def _concat_copy(ff: FFmpeg, files: list[Path], list_file: Path,
                 dst: Path, rf64: bool = False,
                 cancel_flag=None) -> None:
    """concat demuxer + 流复制拼接。

    条目路径一律绝对化（resolve），避免 list 文件相对目录解析出双重拼接。
    rf64=True 用于 WAV 输出（>4GB 自动 RF64）。
    """
    entries = []
    for f in files:
        abs_f = f.resolve()
        entries.append(f"file '{_esc(abs_f)}'")
    list_file.write_text("\n".join(entries), encoding="utf-8")
    args = ["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy"]
    if rf64:
        args += ["-rf64", "auto"]
    args.append(str(dst))
    ff.run(args, cancel_flag=cancel_flag)


def concat_master(ff: FFmpeg, state: TaskState, workdir: Path,
                  on_progress: Optional[ProgressFn] = None,
                  cancel_flag=None) -> tuple[Path, Path]:
    """拼接全部已归一化的集 → (master_video.mp4, master_audio.wav)。

    视频/音频均用 concat demuxer 流复制：同参数中间件无损拼接，
    音频输出 RF64 WAV 防 4GB 溢出，命令行只有 list 文件一个输入，
    集数不限。
    """
    norm = workdir / "norm"
    eps = [e for e in state.episodes if e.normalized and not e.skipped]
    if not eps:
        raise RuntimeError("没有可拼接的集")

    cw, ch = container_size(state.resolved_container, state.config.resolution)
    channels = LAYOUT_CHANNELS[state.config.audio_layout]
    gap = state.config.gap

    v_files: list[Path] = []
    a_files: list[Path] = []
    if gap > 0:
        gv = workdir / "gap_video.mp4"
        ga = workdir / f"gap_audio_{channels}ch.wav"
        if not gv.is_file():
            _make_gap_video(ff, gv, cw, ch, gap)
        if not ga.is_file():
            _make_gap_audio(ff, ga, channels, gap)
        for i, e in enumerate(eps):
            v_files.append(norm / f"ep_{e.index:03d}.mp4")
            a_files.append(norm / f"ep_{e.index:03d}.wav")
            if i < len(eps) - 1:
                v_files.append(gv)
                a_files.append(ga)
    else:
        v_files = [norm / f"ep_{e.index:03d}.mp4" for e in eps]
        a_files = [norm / f"ep_{e.index:03d}.wav" for e in eps]

    # ---- 视频：同参数流复制拼接
    master_v = workdir / "master_video.mp4"
    _concat_copy(ff, v_files, workdir / "concat_video.txt", master_v,
                 cancel_flag=cancel_flag)
    if on_progress:
        on_progress(0.5)       # 视频半 / 音频半（流复制很快，粗粒度即可）

    # ---- 音频：concat demuxer 流复制 → RF64 WAV（同为 pcm_s24le/48k/Nch）
    master_a = workdir / "master_audio.wav"
    _concat_copy(ff, a_files, workdir / "concat_audio.txt", master_a,
                 rf64=True, cancel_flag=cancel_flag)
    if on_progress:
        on_progress(1.0)
    return master_v, master_a
