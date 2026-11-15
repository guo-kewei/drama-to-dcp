"""内容红线预检：对照《电影产业促进法》第16条禁止内容与
《微短剧发展管理办法》红线方向的敏感词启发式扫描。

⚠ 免责声明：关键词预检只是降低退回率的辅助手段，
不能替代国家电影局/广电总局的人工内容审查；词表需持续维护。
词表可在 config/redline_keywords.json 中自行增删。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..core.config import PROJECT_ROOT

DEFAULT_KEYWORDS: dict[str, list[str]] = {
    "危害国家安全/主权": ["颠覆国家", "分裂国家", "恐怖组织", "极端主义"],
    "泄露国家秘密": ["军事机密", "国家秘密", "间谍"],
    "民族/宗教歧视": ["民族歧视", "宗教歧视", "亵渎"],
    "煽动仇恨/暴力": ["煽动仇恨", "种族屠杀", "报复社会"],
    "淫秽色情": ["性爱场面", "色情", "裸露镜头"],
    "赌博/毒品": ["赌场教学", "吸毒方法", "制毒"],
    "教唆犯罪": ["作案手法", "杀人教程", "诈骗教程"],
    "侮辱诽谤": ["侮辱英烈", "诽谤"],
    "历史虚无/歪曲历史": ["否定侵略历史", "历史虚无"],
    "危害未成年人": ["诱导未成年人犯罪", "校园暴力细节"],
    "其他（微短剧管理办法红线）": ["诱导沉迷", "低俗炒作"],
}

_KEYWORDS_PATH = PROJECT_ROOT / "config" / "redline_keywords.json"


def _load_keywords() -> dict[str, list[str]]:
    if _KEYWORDS_PATH.is_file():
        try:
            return json.loads(_KEYWORDS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return DEFAULT_KEYWORDS


def scan(text: str) -> list[dict]:
    """扫描文本，返回 [{category, keyword, count, samples[上下文]}]。"""
    hits = []
    if not text:
        return hits
    for cat, words in _load_keywords().items():
        cat_hits = []
        for w in words:
            for m in re.finditer(re.escape(w), text):
                ctx = text[max(0, m.start() - 20):m.end() + 20]
                cat_hits.append((w, ctx.replace("\n", " ")))
        if cat_hits:
            words_hit = sorted({w for w, _ in cat_hits})
            hits.append(dict(
                category=cat,
                keywords=words_hit,
                count=len(cat_hits),
                samples=[c for _, c in cat_hits[:5]],
            ))
    return sorted(hits, key=lambda h: -h["count"])
