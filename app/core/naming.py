"""DCP 命名：ISDCF DCNC（数字影院命名规范）辅助。

规范要点（isdcf.com DCNC）：
  最终 DCP 名称形如
    TITLE_FTR-1_C-185_XX-XX_51_2K_20261114_SMPTE_OV
       │    │     │     │   │  │  │     │      │   └ Original Version
       │    │     │     │   │  │  │     │      └ 标准
       │    │     │     │   │  │  │     └ 打包日期
       │    │     │     │   │  │  └ 分辨率
       │    │     │     │   │  └ 声道配置
       │    │     │     │   └ 字幕语言
       │    │     │     └ 音频主语言
       │    │     └ 投影画幅代码
       │    └ 内容类型+版本
       └ 片名（建议大写字母/数字/下划线）
  片名段只允许 A-Z 0-9 下划线；空格/特殊字符会被放映系统拒绝。
  参数后缀由 DCP-o-matic 打包时按 ISDCF 规范自动生成（日期取打包日）。
"""
from __future__ import annotations

import re
import time

#: 画幅 → DCNC 投影画幅代码
#: 画幅 → DCNC 投影画幅代码（与 DCP-o-matic 实际生成一致：Flat→F、Scope→S）
ASPECT_CODE = {"flat": "F", "scope": "S", "full": "C"}
#: 声道布局 → DCNC 声道配置代码
AUDIO_CODE = {"stereo": "20", "5.1": "51", "7.1": "71"}


def sanitize_dcp_name(name: str, fallback: str = "UNTITLED") -> str:
    """片名段清洗：仅保留大写字母/数字/下划线。"""
    s = re.sub(r"[^A-Za-z0-9]+", "_", name or "").strip("_").upper()
    return (s or fallback)[:50]


def suggest_dcp_name(title: str) -> str:
    """由显示名（可为中文）建议 DCP 片名段：
    含 ASCII → 直接清洗；纯中文 → 拼音（>14 字符用首字母缩写）；
    拼音库不可用时回落 UNTITLED。"""
    if not title or not title.strip():
        return "UNTITLED"
    if re.search(r"[A-Za-z0-9]", title):
        return sanitize_dcp_name(title)
    try:
        from pypinyin import Style, pinyin
        full = "".join(x[0] for x in pinyin(title, style=Style.NORMAL)).upper()
        if len(full) <= 14:
            return sanitize_dcp_name(full)
        initials = "".join(x[0][0] for x in pinyin(title, style=Style.FIRST_LETTER)).upper()
        return sanitize_dcp_name(initials or full)
    except ImportError:
        return "UNTITLED"


def isdcf_preview(name: str, content_type: str, container: str,
                  resolution: str, audio_layout: str,
                  standard: str = "SMPTE", date: str | None = None) -> str:
    """按 ISDCF DCNC 规范拼接最终 DCP 名称（预览用）。

    与 DCP-o-matic 实际生成一致（日期/大小写以打包结果为准）。
    """
    proj = ASPECT_CODE.get(container, "F")
    aud = AUDIO_CODE.get(audio_layout, "51")
    res = {"2k": "2K", "4k": "4K"}.get(resolution, "2K")
    std = "SMPTE" if (standard or "SMPTE").upper().startswith("S") else "IOP"
    date = date or time.strftime("%Y%m%d")
    ver = "-1" if content_type == "FTR" else ""
    return (f"{sanitize_dcp_name(name)}_{content_type}{ver}_{proj}_XX-XX_"
            f"{aud}_{res}_{date}_{std}_OV")
