"""DCP 溯源标记：向 CPL 注入 <Issuer>/<Creator>（Drama2DCP vX.Y），
并同步更新 PKL 中的 SHA-1 哈希与 ASSETMAP 的分块长度。

依据 SMPTE ST 429-7/8：CPL 可选元素 Issuer/Creator 位于 ReelList 之后；
修改 CPL 后必须重算其哈希（PKL 中该资产的 <Hash>/<Size>）与
ASSETMAP 的 <Length>，否则放映服务器完整性校验失败。
"""
from __future__ import annotations

import base64
import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def add_creator_marker(dcp_dir: Path, creator: str) -> dict:
    """给 DCP 打溯源标记。幂等：Creator 已是本平台标识则跳过。

    DCP-o-matic 打包时会写入自己的 Creator（如 "DCP-o-matic 2.18.51 xxx"）；
    本函数将其替换为平台标识（附带 DCP-o-matic 版本），CPL 无 Creator 时插入。
    """
    cpl = _find(dcp_dir, "cpl_")
    pkl = _find(dcp_dir, "pkl_")
    assetmap = next((p for p in dcp_dir.iterdir()
                     if p.name.upper().startswith("ASSETMAP") and p.suffix == ".xml"),
                    None)
    if not (cpl and pkl and assetmap):
        return dict(done=False, reason="缺少 CPL/PKL/ASSETMAP")

    cpl_text = cpl.read_text(encoding="utf-8")
    m = re.search(r"<Creator>([^<]*)</Creator>", cpl_text)
    if m:
        old = m.group(1)
        if old.startswith("Drama2DCP"):
            return dict(done=False, reason="已是平台标识，跳过")
        # 替换为「平台标识（保留原工具版本）」
        dom_ver = _dom_ver(old)
        new_creator = f"{creator} ({dom_ver})" if dom_ver else creator
        new_text = cpl_text.replace(f"<Creator>{old}</Creator>",
                                    f"<Creator>{new_creator}</Creator>", 1)
    else:
        # 无 Creator：按 SMPTE 顺序在 ReelList 后插入
        marker = f"<Issuer>{creator}</Issuer><Creator>{creator}</Creator>"
        if "</ReelList>" in cpl_text:
            new_text = cpl_text.replace("</ReelList>",
                                        "</ReelList>" + marker, 1)
        else:
            new_text = cpl_text.replace("</CompositionPlaylist>",
                                        marker + "</CompositionPlaylist>", 1)
        new_creator = creator
    cpl.write_text(new_text, encoding="utf-8")

    data = cpl.read_bytes()
    size = len(data)
    digest = base64.b64encode(hashlib.sha1(data).digest()).decode()

    # PKL：通过 ASSETMAP 的 Path→Id 交叉引用精确定位 CPL 资产，同步哈希/长度
    _patch_pkl(pkl, cpl, assetmap, digest, size)
    # ASSETMAP：同步分块长度
    _patch_assetmap(assetmap, cpl, size)
    return dict(done=True, creator=new_creator, cpl=str(cpl.name),
                size=size, hash=digest)


def _dom_ver(old_creator: str) -> str:
    """从 DCP-o-matic 的 Creator 文本中提取 "DCP-o-matic x.y.z" 版本。"""
    m = re.search(r"DCP-o-matic [\d.]+", old_creator)
    return m.group(0) if m else ""


def _find(dcp_dir: Path, prefix: str) -> Path | None:
    return next((p for p in dcp_dir.iterdir()
                 if p.is_file() and p.name.lower().startswith(prefix)
                 and p.suffix == ".xml"), None)


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _patch_pkl(pkl: Path, cpl: Path, assetmap: Path,
               digest: str, size: int) -> None:
    """定位 PKL 中的 CPL 资产并同步 Hash/Size。

    定位策略（按优先级）：
    1. ASSETMAP 交叉引用：Path==cpl 文件名的 Asset Id → PKL 同 Id 资产（最可靠）
    2. OriginalFilename / AnnotationText 含 cpl 文件名
    3. Type 含 "CPL"（如 text/xml;cd="CPL"）
    """
    cpl_asset_ids: set[str] = set()
    am_root = ET.parse(str(assetmap)).getroot()
    for asset in am_root.iter():
        if _local(asset.tag) != "Asset":
            continue
        path_el = next((c for c in asset.iter() if _local(c.tag) == "Path"), None)
        if path_el is not None and Path(path_el.text or "").name == cpl.name:
            id_el = next((c for c in asset if _local(c.tag) == "Id"), None)
            if id_el is not None and id_el.text:
                cpl_asset_ids.add(id_el.text.strip())

    tree = ET.parse(str(pkl))
    root = tree.getroot()
    patched = False
    for asset in root.iter():
        if _local(asset.tag) != "Asset":
            continue
        id_text = next((c.text for c in asset if _local(c.tag) == "Id"), "") or ""
        ofn = next((c.text for c in asset if _local(c.tag) == "OriginalFilename"), "") or ""
        ann = next((c.text for c in asset if _local(c.tag) == "AnnotationText"), "") or ""
        typ = next((c.text for c in asset if _local(c.tag) == "Type"), "") or ""
        hit = (id_text.strip() in cpl_asset_ids if cpl_asset_ids else False) \
            or cpl.name in ofn or cpl.name in ann or "CPL" in typ.upper()
        if not hit:
            continue
        for c in asset:
            t = _local(c.tag)
            if t == "Hash":
                c.text = digest
            elif t == "Size":
                c.text = str(size)
        patched = True
        break
    if not patched:
        raise RuntimeError("PKL 中未定位到 CPL 资产")
    tree.write(str(pkl), encoding="UTF-8", xml_declaration=True)


def _patch_assetmap(assetmap: Path, cpl: Path, size: int) -> None:
    tree = ET.parse(str(assetmap))
    root = tree.getroot()
    for chunk in root.iter():
        if _local(chunk.tag) != "Chunk":
            continue
        path_el = next((c for c in chunk if _local(c.tag) == "Path"), None)
        if path_el is None or Path(path_el.text or "").name != cpl.name:
            continue
        for c in chunk:
            if _local(c.tag) == "Length":
                c.text = str(size)
        break
    tree.write(str(assetmap), encoding="UTF-8", xml_declaration=True)


def get_creator(dcp_dir: Path) -> str:
    """读取 DCP 的 Creator（供质检/报告展示）。"""
    cpl = _find(dcp_dir, "cpl_")
    if not cpl:
        return ""
    m = re.search(r"<Creator>([^<]*)</Creator>", cpl.read_text(encoding="utf-8"))
    return m.group(1) if m else ""
