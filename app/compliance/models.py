"""影片备案项目模型与持久化。"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


# 备案流程节点（顺序即流程）
PROCESS_STAGES = [
    ("materials", "立项材料准备"),
    ("filing", "剧本备案提交"),
    ("publicity", "备案公示"),
    ("production", "成片制作/后期"),
    ("provincial", "省级初审"),
    ("national", "国家终审（内容）"),
    ("technical", "技术审查"),
    ("license", "领取龙标"),
    ("release", "发行/入库"),
]


@dataclass
class StageRecord:
    key: str                 # PROCESS_STAGES 的 key
    date: str = ""           # YYYY-MM-DD
    note: str = ""


@dataclass
class FilmProject:
    title_cn: str = ""                    # 中文片名
    title_en: str = ""                    # 英文译名
    genre: str = ""                       # 类型（故事/动画/纪录/戏曲…）
    source: str = ""                      # 素材来源（如：XX短剧 1-80 集）
    duration_min: int = 0                 # 片长（分钟）
    aspect: str = ""                      # 画幅（如 Flat 1.85 / 1998×1080）
    production_company: str = ""          # 出品单位（须为法人）
    copyright_owner: str = ""             # 著作权归属
    director: str = ""
    screenwriter: str = ""
    producer: str = ""
    cast: str = ""                        # 主要演员（逗号分隔）
    synopsis: str = ""                    # 剧情梗概（目标 ~1000 字）
    dcp_dir: str = ""                     # 关联的 DCP 成品目录（技术报告用）
    master_media: str = ""                # 成片母版（完成台本转录用）
    # 元信息
    id: str = field(default_factory=lambda: time.strftime("%Y%m%d_") + uuid.uuid4().hex[:6])
    created_at: float = field(default_factory=time.time)
    stage_log: list[StageRecord] = field(default_factory=list)

    # ------------------------------------------------------------------
    def synopsis_len(self) -> int:
        return len("".join(self.synopsis.split()))

    # ------------------------------------------------------------------ 持久化
    def dir(self, root: Path) -> Path:
        return root / "备案" / self.id

    def path(self, root: Path) -> Path:
        return self.dir(root) / "project.json"

    def save(self, root: Path) -> None:
        d = self.dir(root)
        d.mkdir(parents=True, exist_ok=True)
        (d / "materials").mkdir(exist_ok=True)
        self.path(root).write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8")

    @classmethod
    def load(cls, p: Path) -> "FilmProject":
        data = json.loads(p.read_text(encoding="utf-8"))
        log = [StageRecord(**s) for s in data.pop("stage_log", [])]
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(stage_log=log, **known)

    @classmethod
    def list_all(cls, root: Path) -> list["FilmProject"]:
        base = root / "备案"
        if not base.is_dir():
            return []
        out = []
        for p in sorted(base.glob("*/project.json")):
            try:
                out.append(cls.load(p))
            except Exception:
                continue
        return sorted(out, key=lambda x: x.created_at, reverse=True)
