"""阶段六：DCP 自动质检——结构完整性 + CPL 参数校验。"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ..core.task import TaskState, container_size
from .provenance import get_creator


def _expected_sar(state: TaskState) -> str:
    """按任务实际容器+分辨率计算 CPL ScreenAspectRatio 期望值 "W H"。"""
    w, h = container_size(state.resolved_container, state.config.resolution)
    return f"{w} {h}"


def find_cpl(dcp_dir: Path) -> Path | None:
    for p in dcp_dir.iterdir():
        if p.is_file() and p.name.lower().startswith("cpl_") \
                and p.suffix.lower() == ".xml":
            return p
    return None


def verify_dcp(dcp_dir: Path, state: TaskState) -> tuple[bool, list[str], dict]:
    """返回 (通过与否, 问题列表, CPL 摘要)。"""
    problems: list[str] = []
    info: dict = {}

    # ---- 1. 结构完整性
    files = {p.name.upper(): p for p in dcp_dir.iterdir() if p.is_file()}
    if not any(k.startswith("ASSETMAP") for k in files):
        problems.append("缺少 ASSETMAP")
    if not any(k.startswith("VOLINDEX") for k in files):
        problems.append("缺少 VOLINDEX")
    if not any(k.startswith("PKL_") for k in files):
        problems.append("缺少 PKL")
    mxfs = [p for p in dcp_dir.iterdir() if p.suffix.lower() == ".mxf"]
    video_mxf = [p for p in mxfs if p.name.lower().startswith("j2c")]
    audio_mxf = [p for p in mxfs if not p.name.lower().startswith("j2c")]
    if not video_mxf:
        problems.append("缺少视频 MXF（j2c）")
    if not audio_mxf:
        problems.append("缺少音频 MXF")
    if any(p.stat().st_size == 0 for p in mxfs):
        problems.append("存在空 MXF 文件")

    # ---- 2. CPL 参数
    cpl = find_cpl(dcp_dir)
    if not cpl:
        problems.append("缺少 CPL")
        return (not problems, problems, info)

    try:
        root = ET.parse(str(cpl)).getroot()
    except ET.ParseError as e:
        problems.append(f"CPL XML 解析失败: {e}")
        return (False, problems, info)

    def texts(tag: str) -> list[str]:
        return [(el.text or "").strip() for el in root.iter()
                if el.tag.split("}")[-1] == tag]

    sar = texts("ScreenAspectRatio")
    want_sar = _expected_sar(state)
    if sar:
        info["screen_aspect_ratio"] = sar[0]
        if sar[0] != want_sar:
            problems.append(f"CPL 画幅 {sar[0]} 与预期容器 {want_sar} 不符")
    else:
        problems.append("CPL 缺少 ScreenAspectRatio")

    fr = texts("FrameRate")
    if fr:
        info["frame_rate"] = fr[0]
        num = fr[0].split()[0]
        if not num.startswith("24"):
            problems.append(f"CPL 帧率 {fr[0]} 非 24fps")
    else:
        problems.append("CPL 缺少 FrameRate")

    # SMPTE CPL 通常无 <Channels>（声道数在音频 MXF 内），有则记录校验
    # 声道预期与 dcp.py 封装策略对齐：stereo 也产 6ch（仅填 L/R，服务器兼容性最好）
    ch = texts("Channels")
    if ch:
        info["audio_channels"] = ch[0]
        want = "8" if state.config.audio_layout == "7.1" else "6"
        if ch[0] != want:
            problems.append(f"CPL 声道数 {ch[0]}，预期 {want}")

    creator = texts("Creator")
    if creator:
        info["creator"] = creator[0]          # 溯源标记（本平台产物）

    dur = texts("Duration")
    if dur and state.expected_total > 0:
        frames = int(dur[0])
        seconds = frames / 24.0
        info["duration_sec"] = round(seconds, 2)
        if abs(seconds - state.expected_total) > 2.0:
            problems.append(
                f"时长偏差过大: CPL {seconds:.1f}s vs 预期 "
                f"{state.expected_total:.1f}s")

    entry = texts("EntryPoint")
    if entry:
        info["entry_point_sec"] = round(int(entry[0]) / 24.0, 2)

    return (not problems, problems, info)
