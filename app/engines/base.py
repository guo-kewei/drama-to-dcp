"""上混引擎抽象接口与注册机制。"""
from __future__ import annotations

import abc
from pathlib import Path
from typing import Callable, ClassVar, Optional

# 声道布局 → 声道数
LAYOUT_CHANNELS = {"stereo": 2, "5.1": 6, "7.1": 8}

ProgressFn = Callable[[float], None]


class UpmixEngine(abc.ABC):
    """音频上混引擎统一接口。

    约定：输入为 48000Hz / 24bit 的立体声 WAV；
    输出为按 DCP SMPTE 声道顺序排列的 N 声道 WAV：
      5.1 → L R C LFE Ls Rs
      7.1 → L R C LFE Ls Rs BsL BsR
    （多声道源直通/重排不经过引擎，由流水线预处理完成。）
    """

    id: ClassVar[str] = ""
    label: ClassVar[str] = ""
    #: 支持的目标布局
    layouts: ClassVar[tuple[str, ...]] = ("5.1", "7.1")

    @abc.abstractmethod
    def process(self, src_wav: Path, dst_wav: Path, layout: str,
                tools: "object", cfg: dict,
                on_progress: Optional[ProgressFn] = None) -> None:
        """将立体声 src_wav 上混为 layout 布局的 dst_wav。

        tools: app.tools.ffmpeg.FFmpeg 实例（引擎可调用其 ffmpeg）。
        cfg:   引擎配置（来自设置，如 AI 命令模板、模型路径等）。
        抛出异常即表示失败。
        """
        raise NotImplementedError

    def available(self, cfg: dict) -> tuple[bool, str]:
        """启动前预检：引擎当前配置下是否可用（如 AI 引擎未配命令则否）。"""
        return True, ""


_REGISTRY: dict[str, type[UpmixEngine]] = {}


def register_upmix(cls: type[UpmixEngine]) -> type[UpmixEngine]:
    assert cls.id, f"{cls.__name__} 缺少 id"
    _REGISTRY[cls.id] = cls
    return cls


def get_upmix_engine(engine_id: str) -> UpmixEngine:
    try:
        return _REGISTRY[engine_id]()
    except KeyError:
        known = "/".join(_REGISTRY)
        raise KeyError(f"未知上混引擎: {engine_id}（可用: {known}）")


def list_upmix_engines() -> list[dict]:
    return [{"id": c.id, "label": c.label, "layouts": list(c.layouts)}
            for c in _REGISTRY.values()]
