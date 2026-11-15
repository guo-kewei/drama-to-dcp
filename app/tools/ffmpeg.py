"""FFmpeg / ffprobe 定位与调用封装。

查找顺序：
1. 配置文件指定的 ffmpeg 目录（settings.ffmpeg_dir）
2. 项目内便携版 tools/ffmpeg*/bin
3. 系统 PATH
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Optional, Sequence

from . import ToolCancelled

# 输出按行回调
LogFn = Callable[[str], None]


class ToolNotFoundError(RuntimeError):
    pass


class FFmpeg:
    def __init__(self, ffmpeg_exe: str | Path, ffprobe_exe: str | Path):
        self.ffmpeg = Path(ffmpeg_exe)
        self.ffprobe = Path(ffprobe_exe)

    # ------------------------------------------------------------------ 定位
    @classmethod
    def discover(cls, override_dir: Optional[str] = None,
                 project_root: Optional[Path] = None) -> "FFmpeg":
        cands: list[Path] = []
        if override_dir:
            cands.append(Path(override_dir))
        if project_root:
            tools = project_root / "tools"
            if tools.is_dir():
                # tools/ffmpeg-x.x/bin 或 tools/ffmpeg/bin
                for p in sorted(tools.glob("ffmpeg*")):
                    cands.append(p / "bin")
                    cands.append(p)
        for d in cands:
            if (d / "ffmpeg.exe").is_file() and (d / "ffprobe.exe").is_file():
                return cls(d / "ffmpeg.exe", d / "ffprobe.exe")
            if (d / "ffmpeg").is_file() and (d / "ffprobe").is_file():
                return cls(d / "ffmpeg", d / "ffprobe")
        # PATH
        from shutil import which
        f = which("ffmpeg")
        p = which("ffprobe")
        if f and p:
            return cls(f, p)
        raise ToolNotFoundError(
            "未找到 FFmpeg。请将便携版解压到项目 tools/ 目录，"
            "或安装后加入 PATH，或在设置中手动指定路径。")

    # ------------------------------------------------------------------ 基础
    def _run(self, args: Sequence[str], timeout: Optional[float] = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(self.ffmpeg), *[str(a) for a in args]],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout)

    def version(self) -> str:
        r = subprocess.run([str(self.ffmpeg), "-version"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        m = re.search(r"ffmpeg version (\S+)", r.stdout)
        return m.group(1) if m else "unknown"

    # ------------------------------------------------------------------ 探测
    def probe(self, media: Path | str) -> dict:
        """ffprobe JSON 结果（format + streams）。失败抛 RuntimeError。"""
        r = subprocess.run(
            [str(self.ffprobe), "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(media)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError(f"ffprobe 失败: {media}\n{r.stderr.strip()[:500]}")
        return json.loads(r.stdout)

    # ------------------------------------------------------------------ 执行
    def run(self, args: Sequence[str], log: Optional[LogFn] = None,
            on_progress: Optional[Callable[[float], None]] = None,
            total_seconds: Optional[float] = None,
            cancel_flag: Optional[Callable[[], bool]] = None) -> str:
        """运行 ffmpeg。提供 on_progress 时附加 -progress pipe 解析进度(0~1)。"""
        full = [str(self.ffmpeg), "-hide_banner", "-y", *(str(a) for a in args)]
        if on_progress is not None:
            full += ["-progress", "pipe:1", "-nostats"]
        return self._exec(full, log, on_progress, total_seconds, cancel_flag)

    def _exec(self, full: list[str], log: Optional[LogFn],
              on_progress: Optional[Callable[[float], None]],
              total_seconds: Optional[float],
              cancel_flag: Optional[Callable[[], bool]]) -> str:
        proc = subprocess.Popen(full, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace",
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        tail: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line.startswith("out_time_ms="):
                try:
                    us = int(line.split("=", 1)[1])
                except ValueError:
                    continue
                if total_seconds and total_seconds > 0 and on_progress:
                    on_progress(min(0.999, us / 1e6 / total_seconds))
                continue
            if line.startswith(("progress=", "frame=", "fps=", "bitrate=",
                                "total_size=", "out_time_us=", "out_time=",
                                "speed=", "dup_frames=", "drop_frames=")):
                continue
            tail.append(line)
            if len(tail) > 60:
                tail.pop(0)
            if log:
                log(line)
            if cancel_flag and cancel_flag():
                proc.terminate()
                proc.wait(timeout=10)
                raise ToolCancelled("已取消")
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg 失败(exit={proc.returncode}):\n" + "\n".join(tail[-25:]))
        if on_progress:
            on_progress(1.0)
        return "\n".join(tail)


ProgressFn = Callable[[float], None]
