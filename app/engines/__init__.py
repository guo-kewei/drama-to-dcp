"""可插拔引擎层：音频上混（规则/AI）与视频增强（超分预留）。

新引擎接入方式：
    @register_upmix
    class MyEngine(UpmixEngine): ...
之后任务参数 audio.engine 使用其 id 即可，流水线其余环节按声道数自动适配。
"""
from .base import (LAYOUT_CHANNELS, UpmixEngine, get_upmix_engine,
                   list_upmix_engines, register_upmix)
from . import rule, ai          # noqa: F401  触发注册
from .enhance import (Enhancer, ExternalCmdEnhancer, NullEnhancer,
                      get_enhancer)

__all__ = [
    "LAYOUT_CHANNELS", "UpmixEngine", "register_upmix", "get_upmix_engine",
    "list_upmix_engines", "Enhancer", "NullEnhancer", "ExternalCmdEnhancer",
    "get_enhancer",
]
