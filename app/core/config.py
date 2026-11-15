"""平台配置（JSON 持久化，位于项目根 config.json）。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"


@dataclass
class Settings:
    # 外部工具
    ffmpeg_dir: str = ""                # 留空=自动检测
    dcpomatic_dir: str = ""             # 留空=自动检测
    # 输出
    output_root: str = ""               # 留空=源文件夹同级
    # 流水线
    concurrency: int = 1                # 并行任务数
    standard: str = "SMPTE"             # SMPTE / Interop
    bad_episode_policy: str = "skip"    # skip=跳过坏集 / abort=中止
    default_gap: float = 0.5            # 集间黑场秒数
    j2k_bitrate_mbps: int = 150         # J2K 码率；超长片崩溃时可降到 100
    dcp_encode_threads: int = 0         # 0=自动；长片随机崩溃可限 2-4
    # 新任务默认参数
    default_container: str = "auto"     # auto/flat/scope/full
    default_resolution: str = "2k"      # 2k/4k
    default_audio_layout: str = "5.1"   # stereo/5.1/7.1
    default_upmix_engine: str = "rule"  # rule/ai
    # 预留引擎配置（AI 上混 / 超分命令模板，v1 未启用）
    engine_cfg: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    def output_root_path(self, source_dir: Path | None = None) -> Path:
        if self.output_root:
            return Path(self.output_root)
        if source_dir is not None:
            return source_dir.parent / "DCP输出"
        return PROJECT_ROOT / "output"

    def workspace_dir(self, source_dir: Path) -> Path:
        return self.output_root_path(source_dir) / "工作区"

    def dcp_dir(self, source_dir: Path) -> Path:
        return self.output_root_path(source_dir) / "DCP"

    def quarantine_dir(self, source_dir: Path) -> Path:
        return self.output_root_path(source_dir) / "隔离区"

    def reports_dir(self, source_dir: Path) -> Path:
        return self.output_root_path(source_dir) / "reports"


def load_settings() -> Settings:
    if CONFIG_PATH.is_file():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            known = {f: data[f] for f in Settings.__dataclass_fields__ if f in data}
            return Settings(**known)
        except Exception as e:
            # 配置损坏时不静默吞掉：打印告警并回退默认，用户至少能察觉
            print(f"⚠ 配置文件损坏，已回退默认设置（{CONFIG_PATH}: {e}）")
    return Settings()


def save_settings(s: Settings) -> None:
    CONFIG_PATH.write_text(
        json.dumps(asdict(s), ensure_ascii=False, indent=2), encoding="utf-8")
