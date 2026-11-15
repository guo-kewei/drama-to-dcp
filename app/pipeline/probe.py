"""阶段一：扫描源文件夹，ffprobe 逐集探测。"""
from __future__ import annotations

import re
from pathlib import Path

from ..core.task import Episode, recommend_container
from ..tools.ffmpeg import FFmpeg

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".ts", ".flv"}


def natural_key(name: str) -> list:
    """自然排序键：ep2 < ep10。"""
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", name)]


def list_videos(folder: Path) -> list[Path]:
    files = [p for p in folder.iterdir()
             if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    return sorted(files, key=lambda p: natural_key(p.name))


def probe_episode(ff: FFmpeg, idx: int, path: Path) -> Episode:
    info = ff.probe(path)
    v = next((s for s in info.get("streams", [])
              if s.get("codec_type") == "video"), None)
    a = next((s for s in info.get("streams", [])
              if s.get("codec_type") == "audio"), None)
    if v is None:
        raise RuntimeError(f"无视频流: {path.name}")

    def frac(x) -> float:
        try:
            num, den = x.split("/")
            return float(num) / float(den) if float(den) else 0.0
        except Exception:
            return 0.0

    dur = float(info.get("format", {}).get("duration") or 0)
    if not dur and v.get("duration"):
        dur = float(v["duration"])
    fps = frac(v.get("avg_frame_rate") or "0/1") or frac(v.get("r_frame_rate") or "0/1")
    return Episode(
        index=idx, path=str(path),
        width=int(v.get("width") or 0), height=int(v.get("height") or 0),
        fps=fps,
        duration=dur,
        audio_channels=int(a.get("channels") or 0) if a else 0,
        audio_layout=(a.get("channel_layout") or "") if a else "",
        vcodec=v.get("codec_name") or "",
        acodec=(a.get("codec_name") or "") if a else "",
    )


def scan_folder(ff: FFmpeg, folder: Path,
                on_episode=None) -> tuple[list[Episode], dict]:
    """返回 (episodes, summary)。on_episode(idx, total, name) 进度回调。"""
    videos = list_videos(folder)
    if not videos:
        raise RuntimeError(f"文件夹中没有视频文件: {folder}")
    episodes: list[Episode] = []
    errors: list[str] = []
    for i, p in enumerate(videos, 1):
        if on_episode:
            on_episode(i, len(videos), p.name)
        try:
            episodes.append(probe_episode(ff, i, p))
        except Exception as e:      # 坏集占位，策略后定
            errors.append(str(e))
            episodes.append(Episode(index=i, path=str(p), error=str(e)))
    widths = {e.width for e in episodes if e.width}
    heights = {e.height for e in episodes if e.height}
    rec = (recommend_container(max(widths), max(heights))
           if widths and heights else "flat")
    summary = dict(
        total=len(episodes),
        ok=sum(1 for e in episodes if not e.error),
        bad=len(errors),
        total_duration=sum(e.duration for e in episodes if not e.error),
        width=max(widths) if widths else 0,
        height=max(heights) if heights else 0,
        mixed_resolution=len(widths) > 1 or len(heights) > 1,
        fps_set=sorted({round(e.fps, 2) for e in episodes if e.fps}),
        audio_ch_set=sorted({e.audio_channels for e in episodes if e.audio_channels}),
        recommended_container=rec,
        errors=errors,
    )
    return episodes, summary
