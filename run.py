#!/usr/bin/env python3
"""短剧转电影自动化平台启动入口。

    python run.py            # 图形界面
    python run.py <子命令>   # 命令行模式：doctor / probe / convert / resume
"""
import sys


def _alert(msg: str) -> None:
    """pythonw（无控制台）下也可见的报错弹窗。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "短剧转电影平台·启动失败", 0x10)
    except Exception:
        print(msg)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in {"doctor", "probe", "convert",
                                             "resume", "--version", "-h",
                                             "--help"}:
        from app.cli import main as cli_main
        return cli_main(sys.argv[1:])
    # 默认启动 GUI
    try:
        from app.main import main as gui_main
    except ImportError:
        _alert("图形界面依赖未安装。\n\n请先执行：\n"
               "    pip install PySide6\n\n"
               "或使用命令行模式：python run.py --help")
        return 1
    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
