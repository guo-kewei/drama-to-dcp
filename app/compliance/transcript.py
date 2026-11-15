"""完成台本转录：funasr（中文优先）→ faster_whisper 兜底。

输入成片视频/音频 → 输出 [(start, end, text), ...]。
首次使用会自动下载模型（funasr 走 ModelScope 国内源；
faster-whisper 走 hf-mirror 镜像）。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable, Optional

from ..core.config import PROJECT_ROOT
from ..tools.ffmpeg import FFmpeg

ProgressFn = Callable[[str], None]


def _make_16k_mono(ff: FFmpeg, media: Path, out: Path) -> None:
    ff.run(["-i", str(media), "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", str(out)])


def _has_audio(ff: FFmpeg, media: Path) -> bool:
    info = ff.probe(media)
    return any(s.get("codec_type") == "audio"
               for s in info.get("streams", []))


def _audio_source(ff: FFmpeg, media: Path, log) -> Path:
    """选转录音源：媒体自带音轨；否则回退同目录约定的 wav
    （本平台母版为 master_video.mp4 + master_audio.wav 分离式）。"""
    if _has_audio(ff, media):
        return media
    for cand in (media.with_suffix(".wav"),
                 media.parent / "master_audio.wav"):
        if cand.is_file() and _has_audio(ff, cand):
            log(f"媒体无音轨，使用 {cand.name}")
            return cand
    raise RuntimeError(f"媒体无音轨，且未找到配套 WAV: {media}")


def transcribe(media: Path, engine: str = "auto",
               on_progress: Optional[ProgressFn] = None,
               language: str = "zh") -> list[tuple[float, float, str]]:
    """转录媒体文件 → [(start_sec, end_sec, text)]。"""
    log = on_progress or (lambda m: None)
    ff = FFmpeg.discover(None, PROJECT_ROOT)
    source = _audio_source(ff, media, log)

    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "in16k.wav"
        log("提取音轨并重采样 16kHz…")
        _make_16k_mono(ff, source, wav)

        if engine in ("auto", "funasr"):
            try:
                return _funasr(wav, log)
            except ImportError:
                if engine == "funasr":
                    raise
                log("funasr 不可用，改用 faster-whisper…")
        try:
            return _whisper(wav, log, language)
        except ImportError:
            raise RuntimeError(
                "转录引擎未随 exe 打包（体积原因）。请在 Python 源码环境运行："
                "pip install funasr 后使用，或参考 README「备案工作台」章节。")


# ----------------------------------------------------------------------
_PUNC_SPLIT = "，。！？!?；;…"          # 句边界标点


def _segments_from_timestamps(text: str, timestamp) -> list[tuple[float, float, str]]:
    """paraformer 逐字时间戳与非标点字符一一对齐（标点为后加），
    按句边界标点聚合成句子段落。"""
    if not timestamp:
        return [(0.0, 0.0, text)] if text else []
    segs = []
    buf: list[str] = []
    ti = 0                      # timestamp 游标（仅非标点字符消费）
    start_ms = timestamp[0][0]
    last_ms = timestamp[0][1]
    for ch in text:
        if ch not in _PUNC_SPLIT:
            if ti < len(timestamp):
                last_ms = timestamp[ti][1]
                if not buf:
                    start_ms = timestamp[ti][0]
                ti += 1
            buf.append(ch)
            continue
        buf.append(ch)
        if len("".join(buf).strip()) >= 2:
            segs.append((start_ms / 1000, last_ms / 1000,
                         "".join(buf).strip()))
            buf = []
    tail = "".join(buf).strip()
    if tail:
        segs.append((start_ms / 1000, last_ms / 1000, tail))
    return segs


def _funasr(wav: Path, log) -> list[tuple[float, float, str]]:
    from funasr import AutoModel
    log("加载 funasr paraformer-zh 模型（首次使用会下载，约 1GB）…")
    model = AutoModel(
        model="paraformer-zh",
        vad_model="fsmn-vad",
        punc_model="ct-punc",
        disable_update=True,
    )
    log("开始识别（CPU 并行，速度约为片长 1/20）…")
    res = model.generate(input=str(wav), batch_size_s=300)
    segs: list[tuple[float, float, str]] = []
    for item in res:
        sents = item.get("sentence_info") or []
        if sents:      # 部分版本直接给句级信息
            for s in sents:
                t = s.get("text") if isinstance(s.get("text"), str) else \
                    "".join(x.get("text", "") for x in s.get("text", [])
                            if isinstance(x, dict))
                segs.append((s["start"] / 1000, s["end"] / 1000, t))
            continue
        text = item.get("text", "")
        ts = item.get("timestamp")
        segs.extend(_segments_from_timestamps(text, ts))
    return [(s, e, t) for s, e, t in segs if t.strip()]


# ----------------------------------------------------------------------
def _whisper(wav: Path, log, language: str) -> list[tuple[float, float, str]]:
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    from faster_whisper import WhisperModel
    log("加载 faster-whisper small 模型（首次使用经 hf-mirror 下载）…")
    model = WhisperModel("small", device="cpu", compute_type="int8")
    log("开始识别…")
    segments, _info = model.transcribe(str(wav), language=language,
                                       vad_filter=True)
    out = []
    for seg in segments:
        out.append((seg.start, seg.end, seg.text))
    return out
