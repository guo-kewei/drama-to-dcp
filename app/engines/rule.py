"""规则上混引擎（v1 默认）：FFmpeg pan 滤镜，对白锚定中置。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .base import UpmixEngine, register_upmix, ProgressFn


@register_upmix
class RuleUpmixEngine(UpmixEngine):
    id = "rule"
    label = "规则上混（对白中置）"
    layouts = ("5.1", "7.1")

    # 各声道增益（相对原始 L/R）
    GAIN_CENTER = 0.5      # C = 0.5L + 0.5R
    GAIN_LFE = 0.10        # LFE 低电平
    GAIN_SIDE = 0.35       # Ls/Rs 侧环绕
    GAIN_BACK = 0.25       # BsL/BsR 后环绕（仅 7.1）

    def build_filter(self, layout: str) -> str:
        g = self
        if layout == "5.1":
            # 输出顺序 L R C LFE Ls Rs（SMPTE/DCP 顺序）
            return (
                f"pan=6c|c0=c0|c1=c1"
                f"|c2={g.GAIN_CENTER}*c0+{g.GAIN_CENTER}*c1"
                f"|c3={g.GAIN_LFE}*c0+{g.GAIN_LFE}*c1"
                f"|c4={g.GAIN_SIDE}*c0|c5={g.GAIN_SIDE}*c1")
        if layout == "7.1":
            # 输出顺序 L R C LFE Ls Rs BsL BsR
            return (
                f"pan=8c|c0=c0|c1=c1"
                f"|c2={g.GAIN_CENTER}*c0+{g.GAIN_CENTER}*c1"
                f"|c3={g.GAIN_LFE}*c0+{g.GAIN_LFE}*c1"
                f"|c4={g.GAIN_SIDE}*c0|c5={g.GAIN_SIDE}*c1"
                f"|c6={g.GAIN_BACK}*c0|c7={g.GAIN_BACK}*c1")
        raise ValueError(f"规则上混不支持布局: {layout}")

    def process(self, src_wav: Path, dst_wav: Path, layout: str,
                tools, cfg: dict, on_progress: Optional[ProgressFn] = None) -> None:
        af = self.build_filter(layout)
        tools.run(
            ["-i", str(src_wav), "-af", af,
             "-c:a", "pcm_s24le", "-ar", "48000", str(dst_wav)],
            on_progress=on_progress,
            total_seconds=_wav_seconds(src_wav))
        # 清理 ffmpeg 生成可能的 layout 标记差异：pan=Nc 输出为无布局 N 声道，
        # 正是 DCP-o-matic 按序映射所需。


def _wav_seconds(p: Path) -> float:
    """从文件大小粗估 WAV 时长（pcm_s24le 48k）：用于进度分母。"""
    import wave
    try:
        with wave.open(str(p), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 48000)
    except Exception:
        return 0.0
