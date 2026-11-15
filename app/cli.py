"""M1 命令行入口（无 GUI 跑通流水线；M2 起 GUI 为主入口）。

用法：
    python run.py doctor                          # 环境自检
    python run.py probe <短剧文件夹>               # 仅扫描探测
    python run.py convert <短剧文件夹> [选项]       # 全流程转制 DCP
    python run.py resume <短剧文件夹> [任务ID]      # 断点恢复
选项：
    --container auto|flat|scope|full   画幅（默认 auto 自动匹配）
    --res 2k|4k                        分辨率（默认 2k）
    --fit fill|fit                     fill=裁切填满(默认) fit=保留黑边
    --audio stereo|5.1|7.1             声道布局（默认 5.1）
    --engine rule|ai                   上混引擎（默认 rule）
    --name NAME                        DCP 名称（默认由文件夹名生成）
    --ctype FTR|TLR                    内容类型（默认 FTR）
    --gap SECONDS                      集间黑场秒（默认 0.5，≥0）
    --policy skip|abort                坏集策略（默认 skip）
    --standard SMPTE|Interop           DCP 标准（默认 SMPTE）
    --out DIR                          输出根目录
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import __version__
from .core.config import PROJECT_ROOT, Settings, load_settings
from .core.task import TaskConfig, TaskState, stage_label
from .pipeline.runner import PipelineRunner, RunnerCallbacks


def _bar(frac: float, width: int = 30) -> str:
    filled = int(frac * width)
    return "[" + "█" * filled + "·" * (width - filled) + f"] {frac*100:5.1f}%"


def _one_line(s: str, n: int = 60) -> str:
    return (s or "").replace("\r", " ").replace("\n", " ")[:n]


def cmd_doctor(args) -> int:
    from .tools.ffmpeg import FFmpeg
    from .tools.dcpomatic import DCPoMatic
    s = load_settings()
    print(f"平台版本 {__version__}  项目根: {PROJECT_ROOT}")
    ok = True
    try:
        ff = FFmpeg.discover(s.ffmpeg_dir or None, PROJECT_ROOT)
        print(f"✅ FFmpeg     {ff.ffmpeg}")
        print(f"             版本 {ff.version()}")
    except Exception as e:
        ok = False
        print(f"❌ FFmpeg     {e}")
    try:
        dom = DCPoMatic.discover(s.dcpomatic_dir or None, PROJECT_ROOT)
        print(f"✅ DCP-o-matic {dom.bin_dir}")
    except Exception as e:
        ok = False
        print(f"❌ DCP-o-matic {e}")
    try:
        import PySide6  # noqa: F401
        import PySide6.QtWidgets  # noqa: F401
        print("✅ PySide6    已安装（图形界面可用）")
    except Exception:
        print("⚠  PySide6    未安装（仅命令行可用；GUI 需要：pip install PySide6）")
    print("环境就绪" if ok else "环境不全：请按上方提示安装/配置后重试")
    return 0 if ok else 1


def cmd_probe(args) -> int:
    from .pipeline.probe import scan_folder
    from .tools.ffmpeg import FFmpeg
    try:
        s = load_settings()
        ff = FFmpeg.discover(s.ffmpeg_dir or None, PROJECT_ROOT)
        folder = Path(args.folder)
        if not folder.is_dir():
            print(f"❌ 文件夹不存在: {folder}")
            return 1
        eps, summary = scan_folder(ff, folder)
    except Exception as e:
        print(f"❌ {_one_line(str(e), 200)}")
        return 1
    for e in eps:
        mark = "✅" if not e.error else f"❌ {_one_line(e.error)}"
        print(f"  {e.index:3d}. {Path(e.path).name:40s} "
              f"{e.width}×{e.height} {e.fps:g}fps {e.duration:6.1f}s "
              f"audio={e.audio_channels}ch  {mark}")
    print(f"\n汇总: {summary['ok']}集正常/{summary['bad']}集异常 "
          f"总时长 {summary['total_duration']/60:.1f} 分钟 "
          f"推荐容器 {summary['recommended_container']}")
    return 0


def cmd_convert(args) -> int:
    s = load_settings()
    if args.out:
        s.output_root = ""
    if args.policy:
        s.bad_episode_policy = args.policy
    if args.standard:
        s.standard = args.standard
    cfg = TaskConfig(
        source_dir=str(Path(args.folder).resolve()),
        container=args.container, resolution=args.res, fit_mode=args.fit,
        audio_layout=args.audio, upmix_engine=args.engine,
        dcp_name=args.name or "", content_type=args.ctype, gap=args.gap,
        bad_episode_policy=s.bad_episode_policy,
        output_root=str(Path(args.out).resolve()) if args.out else "")
    state = TaskState.new(cfg)
    return _run_with_progress(s, state)


def cmd_resume(args) -> int:
    """从工作区 state.json 断点续跑（已归一化的集不会重做）。"""
    from .core.task import TaskState
    s = load_settings()
    src = Path(args.source).resolve()
    # 优先按候选任务自身的 output_root 定位（--out 转换的任务也能恢复）
    candidates: list[Path] = []
    roots = []
    if args.out:
        roots.append(Path(args.out).resolve() / "工作区")
    roots.append(s.workspace_dir(src))
    seen = set()
    for root in roots:
        if root in seen or not root.is_dir():
            continue
        seen.add(root)
        for sp in root.glob("*/state.json"):
            try:
                if TaskState.load(sp).config.source_dir == str(src):
                    candidates.append(sp)
            except Exception:
                continue
    if args.task_id:
        wanted = [sp for sp in candidates if sp.parent.name == args.task_id]
        if not wanted:
            print(f"❌ 未找到任务 {args.task_id}（源: {src}）")
            return 1
        sp = wanted[0]
    else:
        if not candidates:
            print(f"工作区无该源的任务: {src}")
            return 1
        sp = sorted(candidates)[-1]
    state = TaskState.load(sp)
    if state.stage == "done":
        print(f"任务 {state.task_id} 已完成，无需恢复（DCP: "
              f"{state.dcp_output_dir}）")
        return 0
    print(f"恢复任务 {state.task_id}（阶段 {stage_label(state.stage)}，"
          f"已完成归一化 {sum(1 for e in state.episodes if e.normalized)} 集）")
    state.stage = "pending"
    state.error = ""
    return _run_with_progress(s, state, quiet_progress=True)


def _run_with_progress(s: Settings, state: TaskState,
                       quiet_progress: bool = False) -> int:
    last = [0.0, time.time()]

    def on_progress(f):
        if quiet_progress:
            return
        now = time.time()
        if f - last[0] > 0.01 or now - last[1] > 2:
            last[0], last[1] = f, now
            print(f"\r{_bar(f)} ", end="", flush=True)

    cbs = RunnerCallbacks(
        on_stage=lambda k, lbl: print(f"\n▶ [{k}] {lbl}"),
        on_progress=on_progress,
        on_message=lambda m: print(f"\nℹ {m}"),
        on_log=lambda l: print(f"   {_one_line(l, 160)}") if l.strip() else None)
    try:
        runner = PipelineRunner(s, state, cbs)
    except Exception as e:      # 锁冲突/工具缺失等启动期错误
        state.stage = "failed"
        state.error = str(e)
        print(f"❌ 无法启动任务: {_one_line(str(e), 300)}")
        return 1
    t0 = time.time()
    result = runner.run()
    dt = time.time() - t0
    print()
    if result.stage == "done":
        print(f"✅ 转制成功，用时 {dt/60:.1f} 分钟")
        print(f"   DCP 输出: {result.dcp_output_dir}")
        return 0
    print(f"❌ {stage_label(result.stage)}: {_one_line(result.error, 300)}")
    return 1


def _gap(s: str) -> float:
    v = float(s)
    if v < 0:
        raise argparse.ArgumentTypeError("集间黑场秒数不能为负")
    if v > 60:
        raise argparse.ArgumentTypeError("集间黑场秒数过大（≤60）")
    return v


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="短剧转电影自动化平台",
        description="批量将宽屏短剧自动转制为影院 DCP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="环境自检（工具检测）")

    sp = sub.add_parser("probe", help="扫描探测短剧文件夹")
    sp.add_argument("folder")

    sc = sub.add_parser("convert", help="全流程转制 DCP")
    sc.add_argument("folder")
    sc.add_argument("--container", default="auto",
                    choices=["auto", "flat", "scope", "full"])
    sc.add_argument("--res", default="2k", choices=["2k", "4k"])
    sc.add_argument("--fit", default="fill", choices=["fill", "fit"])
    sc.add_argument("--audio", default="5.1", choices=["stereo", "5.1", "7.1"])
    sc.add_argument("--engine", default="rule", choices=["rule", "ai"])
    sc.add_argument("--name", default="")
    sc.add_argument("--ctype", default="FTR", choices=["FTR", "TLR"])
    sc.add_argument("--gap", type=_gap, default=0.5)
    sc.add_argument("--policy", default="", choices=["", "skip", "abort"])
    sc.add_argument("--standard", default="", choices=["", "SMPTE", "Interop"])
    sc.add_argument("--out", default="")

    sr = sub.add_parser("resume", help="断点恢复未完成任务")
    sr.add_argument("source", help="短剧源文件夹（用于定位工作区）")
    sr.add_argument("task_id", nargs="?", default="",
                    help="任务ID（缺省取最新）")
    sr.add_argument("--out", default="",
                    help="输出根目录（--out 转换的任务需指定）")

    args = p.parse_args(argv)
    return {"doctor": cmd_doctor, "probe": cmd_probe,
            "convert": cmd_convert, "resume": cmd_resume}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
