"""阶段五：DCP 封装（dcpomatic2_create 建工程 + dcpomatic2_cli 编码）。"""
from __future__ import annotations

import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Optional

from ..core.naming import isdcf_preview
from ..core.task import CONTAINERS, TaskState
from ..engines import LAYOUT_CHANNELS
from ..tools.dcpomatic import DCPoMatic
from . import provenance

ProgressFn = Callable[[float], None]


def _patch_channel_map(film_dir: Path, wav_channels: int, log=None) -> None:
    """把音频内容的声道映射改写为「逐声道直连」（input i → output i）。

    背景：dcpomatic2_create 对 8ch WAV 的自动猜测会把第 7/8 声道接到
    HI/VI（助听/视障）而非 BsL/BsR（7.1 后环绕），导致 ISDCF 名称变成
    51-HI-VI、后环绕声进了错误轨道。显式直连后：
      6ch → L R C Lfe Ls Rs（5.1）；8ch → …BsL BsR（7.1），与我们的
    WAV 声道顺序（SMPTE/DCP 顺序）完全一致。
    """
    meta = film_dir / "metadata.xml"
    if not meta.is_file():
        return
    tree = ET.parse(str(meta))
    root = tree.getroot()
    patched = False
    for content in root.iter("Content"):
        path_el = content.find("Path")
        if path_el is None or not (path_el.text or "").lower().endswith(".wav"):
            continue
        for stream in content.iter("AudioStream"):
            mapping = stream.find("Mapping")
            if mapping is None:
                continue
            ic = mapping.find("InputChannels")
            if ic is not None:
                ic.text = str(wav_channels)
            oc = mapping.find("OutputChannels")
            n_out = 16
            if oc is not None and (oc.text or "").strip().isdigit():
                n_out = int(oc.text)
            # 重建完整增益矩阵：input i → output i 直连，其余归零
            for gain in list(mapping.findall("Gain")):
                mapping.remove(gain)
            for i in range(wav_channels):
                for o in range(n_out):
                    g = ET.SubElement(mapping, "Gain",
                                      {"input": str(i), "output": str(o)})
                    g.text = "1" if i == o else "0"
            patched = True
    if patched:
        tree.write(str(meta), encoding="UTF-8", xml_declaration=True)
        if log:
            log(f"声道映射已直连: {wav_channels}ch → DCP 前 {wav_channels} 声道")


def build_dcp(dom: DCPoMatic, state: TaskState,
              master_video: Path, master_audio: Path,
              film_dir: Path, out_dir: Path, *,
              standard: str = "SMPTE",
              video_bit_rate: Optional[int] = None,
              encode_threads: int = 0,
              log=None,
              on_progress: Optional[ProgressFn] = None,
              cancel_flag=None) -> Path:
    """生成 DCP 并移动到 out_dir/<DCP名称>。返回 DCP 目录。"""
    cfg = state.config
    cont = CONTAINERS[state.resolved_container]
    layout_ch = LAYOUT_CHANNELS.get(cfg.audio_layout, 6)

    # 立体声目标：保持 6 声道 DCP（立体声只填 L/R，其余静音），
    # 服务器兼容性最好；5.1 → 默认 6ch；7.1 → 显式 8ch。
    audio_channels = 8 if layout_ch == 8 else None

    # 完整 ISDCF 名称（与界面预览同一函数生成，打包即所见）
    film_name = isdcf_preview(cfg.dcp_name, cfg.content_type,
                              state.resolved_container, cfg.resolution,
                              cfg.audio_layout, standard)
    dom.create_film(
        film_dir,
        name=film_name,
        container_ratio=cont["ratio"],
        twok=(cfg.resolution == "2k"),
        standard=standard,
        content_type=cfg.content_type,
        no_encrypt=True,
        audio_channels=audio_channels,
        video_bit_rate=video_bit_rate,
        video_file=master_video,
        audio_file=master_audio,
        log=log)

    # 声道逐路直连（修正 create 对 8ch 的 HI/VI 猜测，保证 7.1 落在 BsL/BsR）
    _patch_channel_map(film_dir, layout_ch, log=log)

    dom.encode_film(film_dir, log=log, on_progress=on_progress,
                    cancel_flag=cancel_flag, threads=encode_threads)

    dcp = dom.find_dcp_dir(film_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / cfg.dcp_name
    # 目标已存在时不删除（避免同名任务互相覆盖），追加时间戳
    if target.exists():
        target = out_dir / f"{cfg.dcp_name}_{time.strftime('%H%M%S')}"
    shutil.move(str(dcp), str(target))

    # 溯源标记：CPL 注入 Creator（同步修正 PKL 哈希与 ASSETMAP 长度）
    from .. import __version__
    try:
        mark = provenance.add_creator_marker(target, f"Drama2DCP v{__version__}")
        if log:
            log(f"溯源标记: {mark}")
    except Exception as e:
        if log:
            log(f"⚠ 溯源标记失败（不影响 DCP 有效性）: {e}")
    return target
