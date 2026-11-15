"""任务模型与状态持久化（支持断点恢复）。"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

# 画幅容器定义：name → (2K宽, 2K高, container_ratio, content_ratio, 说明)
CONTAINERS = {
    "flat":  dict(w=1998, h=1080, ratio=185, label="Flat 1.85:1"),
    "scope": dict(w=2048, h=858,  ratio=239, label="Scope 2.39:1"),
    "full":  dict(w=2048, h=1080, ratio=190, label="Full 1.90:1（需放映端预设）"),
}


def container_size(name: str, resolution: str) -> tuple[int, int]:
    c = CONTAINERS[name]
    if resolution == "4k":
        return c["w"] * 2, c["h"] * 2
    return c["w"], c["h"]


def recommend_container(width: int, height: int) -> str:
    """按源画幅推荐容器：≥2.15:1 → scope，其余 → flat。"""
    if height == 0:
        return "flat"
    return "scope" if (width / height) >= 2.15 else "flat"


def sanitize_dcp_name(name: str, fallback: str = "UNTITLED") -> str:
    """DCP 名称仅允许大写字母/数字/下划线。"""
    import re
    s = re.sub(r"[^A-Za-z0-9]+", "_", name or "").strip("_").upper()
    return (s or fallback)[:50]


class Stage(str, Enum):
    pending = "待处理"
    scanning = "扫描探测"
    normalizing = "归一化"
    concatenating = "拼接"
    packaging = "DCP封装"
    verifying = "质检"
    done = "完成"
    failed = "失败"
    cancelled = "已取消"


def stage_label(key: str) -> str:
    """阶段键（英文）→ 中文标签；未识别原样返回。"""
    try:
        return Stage[key].value
    except KeyError:
        try:
            return Stage(key).value
        except ValueError:
            return key


@dataclass
class Episode:
    index: int
    path: str
    width: int = 0
    height: int = 0
    fps: float = 0.0
    duration: float = 0.0
    audio_channels: int = 0
    audio_layout: str = ""
    vcodec: str = ""
    acodec: str = ""
    # 处理状态
    normalized: bool = False      # norm/ep_xxx.mp4 + .wav 已生成
    skipped: bool = False         # 坏集被跳过
    error: str = ""


@dataclass
class TaskConfig:
    source_dir: str
    container: str = "auto"       # auto/flat/scope/full（分析后固化为实际值）
    resolution: str = "2k"        # 2k/4k
    fit_mode: str = "fill"        # fill=轻微裁切填满 / fit=完整保留加黑边
    audio_layout: str = "5.1"     # stereo/5.1/7.1
    upmix_engine: str = "rule"    # rule/ai
    dcp_name: str = ""            # 规范化后的名称（大写/数字/下划线）
    title: str = ""               # 显示名（可为中文）
    content_type: str = "FTR"     # FTR 长片 / TLR 预告
    gap: float = 0.5              # 集间黑场秒
    bad_episode_policy: str = "skip"
    output_root: str = ""         # 任务级输出根覆盖（空=用全局设置推导）


@dataclass
class TaskState:
    task_id: str
    config: TaskConfig
    stage: str = "pending"
    # 分析结果
    resolved_container: str = ""
    expected_total: float = 0.0     # 预期成片总时长（秒，含间隙）
    episodes: list[Episode] = field(default_factory=list)
    # 运行信息
    progress: float = 0.0
    error: str = ""
    created_at: float = field(default_factory=lambda: time.time())
    finished_at: float = 0.0
    dcp_output_dir: str = ""

    # ------------------------------------------------------------------
    def state_path(self, workspace: Path) -> Path:
        return workspace / self.task_id / "state.json"

    def save(self, workspace: Path) -> None:
        p = self.state_path(workspace)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2),
                     encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "TaskState":
        data = json.loads(path.read_text(encoding="utf-8"))
        # 前向兼容：忽略未知字段（新版增加字段后旧/新 state.json 互读不崩）
        cfg_raw = data.pop("config", {})
        known_cfg = {f: cfg_raw[f] for f in TaskConfig.__dataclass_fields__
                     if f in cfg_raw}
        eps = [Episode(**{f: e[f] for f in Episode.__dataclass_fields__ if f in e})
               for e in data.pop("episodes", [])]
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(config=TaskConfig(**known_cfg), episodes=eps, **known)

    @staticmethod
    def new(cfg: TaskConfig) -> "TaskState":
        return TaskState(task_id=time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6],
                         config=cfg)
