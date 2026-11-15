"""视频增强（AI 超分）引擎——v1 预留接口。

流水线归一化阶段之前调用。v1 默认 NullEnhancer（直通）。
未来集成 video2x / Real-ESRGAN / Intel XeSS 等时，
实现 Enhancer.process 或配置 ExternalCmdEnhancer 的命令模板。
"""
from __future__ import annotations

import abc
import shlex
import subprocess
from pathlib import Path
from typing import ClassVar, Optional


class Enhancer(abc.ABC):
    id: ClassVar[str] = ""
    label: ClassVar[str] = ""

    @abc.abstractmethod
    def process(self, src: Path, dst: Path, cfg: dict) -> Path:
        """增强 src 视频到 dst。返回 dst。失败抛异常。"""
        raise NotImplementedError


class NullEnhancer(Enhancer):
    id = "none"
    label = "不增强（默认）"

    def process(self, src: Path, dst: Path, cfg: dict) -> Path:
        return src


class ExternalCmdEnhancer(Enhancer):
    """外部命令模板超分引擎（预留，未配置则直通）。"""
    id = "external"
    label = "外部超分命令（预留）"
    CFG_KEY_CMD = "enhance_cmd"   # 模板占位符 {input} {output}

    def process(self, src: Path, dst: Path, cfg: dict) -> Path:
        template = (cfg or {}).get(self.CFG_KEY_CMD, "").strip()
        if not template:
            return src
        cmd = template.replace("{input}", str(src)).replace("{output}", str(dst))
        r = subprocess.run(shlex.split(cmd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0 or not dst.is_file():
            raise RuntimeError(f"超分命令失败:\n{r.stderr[-800:]}")
        return dst


def get_enhancer(cfg: dict) -> Enhancer:
    """按配置选择增强引擎：配置了命令模板则用外部命令，否则直通。"""
    if (cfg or {}).get(ExternalCmdEnhancer.CFG_KEY_CMD, "").strip():
        return ExternalCmdEnhancer()
    return NullEnhancer()
