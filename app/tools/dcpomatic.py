"""DCP-o-matic 命令行工具（dcpomatic2_create / dcpomatic2_cli）定位与封装。"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Optional, Sequence

from . import ToolCancelled

LogFn = Callable[[str], None]


class ToolNotFoundError(RuntimeError):
    pass


class DCPoMatic:
    """封装 dcpomatic2_create（建工程）与 dcpomatic2_cli（编码出 DCP）。"""

    #: Windows 默认安装目录
    _DEFAULT_DIRS = [
        r"C:\Program Files\DCP-o-matic 2\bin",
        r"C:\Program Files (x86)\DCP-o-matic 2\bin",
        r"C:\Program Files\DCP-o-matic\bin",
    ]

    def __init__(self, bin_dir: Path):
        self.bin_dir = bin_dir
        self.create_exe = bin_dir / "dcpomatic2_create.exe"
        self.cli_exe = bin_dir / "dcpomatic2_cli.exe"
        for exe in (self.create_exe, self.cli_exe):
            if not exe.is_file():
                # 非 Windows 后备
                alt = exe.with_name(exe.stem)
                if alt.is_file():
                    continue
                raise ToolNotFoundError(f"缺少工具: {exe}")

    @classmethod
    def discover(cls, override_dir: Optional[str] = None,
                 project_root: Optional[Path] = None) -> "DCPoMatic":
        cands: list[Path] = []
        if override_dir:
            cands.append(Path(override_dir))
        if project_root:
            cands.append(project_root / "tools" / "dcpomatic2" / "bin")
        cands += [Path(d) for d in cls._DEFAULT_DIRS]
        from shutil import which
        w = which("dcpomatic2_cli")
        if w:
            cands.append(Path(w).parent)
        for d in cands:
            if (d / "dcpomatic2_create.exe").is_file() or \
               (d / "dcpomatic2_create").is_file():
                return cls(d)
        raise ToolNotFoundError(
            "未找到 DCP-o-matic。请从 https://dcpomatic.com/download 安装"
            "（免费开源），或在设置中手动指定其 bin 目录。")

    # ------------------------------------------------------------------
    def _exe(self, exe: Path) -> str:
        return str(exe if exe.is_file() else exe.with_name(exe.stem))

    def _run(self, exe: Path, args: Sequence[str], log: Optional[LogFn] = None,
             cancel_flag: Optional[Callable[[], bool]] = None,
             on_progress: Optional[Callable[[float], None]] = None) -> str:
        full = [self._exe(exe), *(str(a) for a in args)]
        proc = subprocess.Popen(
            full, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        tail: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            tail.append(line)
            if len(tail) > 80:
                tail.pop(0)
            if log:
                log(line)
            # 解析编码进度行（如 "Encoding: 29%" / "Encoding picture ... (29%)"）
            if on_progress and "%" in line and "ncod" in line.lower():
                m = re.search(r"(\d{1,3})\s*%", line)
                if m:
                    on_progress(min(0.999, int(m.group(1)) / 100.0))
            if cancel_flag and cancel_flag():
                proc.terminate()
                proc.wait(timeout=10)
                raise ToolCancelled("已取消")
        proc.wait()
        if proc.returncode != 0:
            hint = ""
            if proc.returncode in (0xC0000005, 3221225477):
                hint = ("\n[提示] DCP-o-matic 编码器发生访问冲突崩溃(0xC0000005)。"
                        "常见于超长片/高码率下的暗场加噪路径："
                        "建议将 J2K 码率调低（设置 j2k_bitrate_mbps，如 100）后重试。")
            raise RuntimeError(
                f"{exe.name} 失败(exit={proc.returncode}):" + hint
                + "\n" + "\n".join(tail[-25:]))
        return "\n".join(tail)

    # ------------------------------------------------------------------
    def create_film(self, film_dir: Path, *, name: str,
                    container_ratio: int,
                    twok: bool, standard: str = "SMPTE",
                    content_type: str = "FTR", no_encrypt: bool = True,
                    audio_channels: Optional[int] = None,
                    video_bit_rate: Optional[int] = None,
                    video_file: Path | None = None,
                    audio_file: Path | None = None,
                    log: Optional[LogFn] = None) -> str:
        """dcpomatic2_create 建立工程（不编码）。

        name 应传完整 ISDCF 名称（create 时附加 --no-use-isdcf-name，
        禁止 DCP-o-matic 自行拼接——它对 8 声道会默认标成 51-HI-VI）。
        """
        args = ["-o", str(film_dir),
                "--container-ratio", str(container_ratio),
                "--standard", standard,
                "-n", name,
                "--no-use-isdcf-name",
                "-c", content_type]
        if video_bit_rate:
            args += ["--video-bit-rate", str(video_bit_rate)]
        args += ["--twok"] if twok else ["--fourk"]
        args += ["-f", "24"]
        if no_encrypt:
            args.append("--no-encrypt")
        if audio_channels:
            args += ["-a", str(audio_channels)]
        if video_file is not None:
            args.append(str(video_file))
        if audio_file is not None:
            args.append(str(audio_file))
        return self._run(self.create_exe, args, log=log)

    def encode_film(self, film_dir: Path, log: Optional[LogFn] = None,
                    on_progress: Optional[Callable[[float], None]] = None,
                    cancel_flag: Optional[Callable[[], bool]] = None,
                    threads: int = 0) -> str:
        """dcpomatic2_cli 执行编码，产出 DCP。返回完整输出文本。

        threads>0 时以 -t 限制编码线程（长片随机崩溃时的降并发手段）。
        """
        args = [str(film_dir)]
        if threads and threads > 0:
            args = ["-t", str(threads), *args]
        out = self._run(self.cli_exe, args, log=log,
                        cancel_flag=cancel_flag, on_progress=on_progress)
        if on_progress:
            on_progress(1.0)
        return out

    @staticmethod
    def find_dcp_dir(film_dir: Path) -> Path:
        """在工程目录下定位 DCP 输出目录（含 ASSETMAP 的目录）。"""
        for p in sorted(film_dir.rglob("*")):
            if p.is_dir() and any(
                    f.name.upper().startswith("ASSETMAP")
                    for f in p.iterdir() if f.is_file()):
                return p
        raise RuntimeError(f"工程目录中未找到 DCP 输出: {film_dir}")
