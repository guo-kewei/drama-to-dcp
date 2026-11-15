"""AI 上混引擎（预留接口）。

未来接入开源 AI 上混模型（生成 5.1/7.1/更高格式沉浸声）时：
1. 若模型提供命令行：在设置中配置命令模板即可启用，无需改代码。
   模板占位符：{input} {output} {layout} {channels}
   例: python ai_upmix.py --in {input} --out {output} --layout {layout}
2. 若为 Python 包：新建 engines/ai_impl.py 实现本类 process 并替换注册。

v1 状态：未配置命令模板时调用即抛出未启用提示；UI 中置灰。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from .base import UpmixEngine, register_upmix, LAYOUT_CHANNELS, ProgressFn


@register_upmix
class AIUpmixEngine(UpmixEngine):
    id = "ai"
    label = "AI 上混（预留，未来生成 5.1/7.1/沉浸声）"
    layouts = ("5.1", "7.1")   # 未来可扩展（DCP 上限 16 声道）

    CFG_KEY_CMD = "ai_upmix_cmd"       # 设置中的命令模板键

    def available(self, cfg: dict) -> tuple[bool, str]:
        if not (cfg or {}).get(self.CFG_KEY_CMD, "").strip():
            return False, ("AI 上混引擎 v1 尚未开放配置入口（设置中的 AI 区暂为预留），"
                           "请使用默认的规则上混引擎（--engine rule）")
        return True, ""

    def process(self, src_wav: Path, dst_wav: Path, layout: str,
                tools, cfg: dict, on_progress: Optional[ProgressFn] = None) -> None:
        template = (cfg or {}).get(self.CFG_KEY_CMD, "").strip()
        if not template:
            raise RuntimeError(
                "AI 上混引擎尚未启用：请在「设置 → AI 引擎」中配置上混命令模板。")
        channels = LAYOUT_CHANNELS.get(layout)
        if not channels:
            raise ValueError(f"AI 上混引擎不支持布局: {layout}")
        cmd = (template
               .replace("{input}", str(src_wav))
               .replace("{output}", str(dst_wav))
               .replace("{layout}", layout)
               .replace("{channels}", str(channels)))
        import shlex
        parts = [t.strip('"') for t in shlex.split(cmd, posix=False)]
        r = subprocess.run(parts, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0 or not dst_wav.is_file():
            raise RuntimeError(
                f"AI 上混命令失败(exit={r.returncode}):\n{r.stderr[-800:]}")
        if on_progress:
            on_progress(1.0)
