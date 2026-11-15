"""外部开源工具（FFmpeg / DCP-o-matic）的检测与调用封装。"""


class ToolCancelled(RuntimeError):
    """外部工具执行期间被用户取消。"""
