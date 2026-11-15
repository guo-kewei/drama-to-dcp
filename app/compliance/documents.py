"""备案材料文档生成（python-docx）：备案报告 / 主创人员登记表 /
完成台本 / DCP 技术自检报告。

输出 .docx 到 <输出根>/备案/<项目ID>/materials/。
"""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt

from ..pipeline.verify import find_cpl
from .models import FilmProject


def _doc(title: str) -> Document:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "SimSun"
    style.font.size = Pt(12)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    h = doc.add_heading(title, level=1)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    return doc


def _kv(doc: Document, pairs: list[tuple[str, str]]) -> None:
    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for k, v in pairs:
        row = table.add_row().cells
        row[0].text = k
        row[1].text = v or "（待填写）"


def _materials_dir(root: Path, proj: FilmProject) -> Path:
    d = proj.dir(root) / "materials"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ts(sec: float) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ----------------------------------------------------------------------
def build_filing_report(root: Path, proj: FilmProject) -> Path:
    """电影剧本（梗概）备案报告（docx）。"""
    doc = _doc("电影剧本（梗概）备案报告")
    doc.add_paragraph("（本文档由短剧转电影平台自动生成，供备案申请参考；"
                      "正式提交以国家电影局电子政务平台导出的申请表为准。）")
    _kv(doc, [
        ("影片名称（中文）", proj.title_cn),
        ("英文译名", proj.title_en),
        ("影片类型", proj.genre),
        ("片长（分钟）", str(proj.duration_min) if proj.duration_min else ""),
        ("画幅规格", proj.aspect),
        ("素材来源", proj.source),
        ("出品单位（法人）", proj.production_company),
        ("著作权归属", proj.copyright_owner),
        ("编剧", proj.screenwriter),
        ("导演", proj.director),
        ("制片人", proj.producer),
        ("主要演员", proj.cast),
    ])
    doc.add_heading("剧情梗概", level=2)
    doc.add_paragraph(proj.synopsis or "（待填写）")
    doc.add_paragraph(f"（梗概字数：{proj.synopsis_len()}，备案要求约 1000 字）")
    out = _materials_dir(root, proj) / "备案报告.docx"
    doc.save(str(out))
    return out


# ----------------------------------------------------------------------
def build_crew_form(root: Path, proj: FilmProject) -> Path:
    """主创人员登记表（docx）。"""
    doc = _doc("主创人员登记表")
    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    for i, h in enumerate(("职务", "姓名", "身份证号", "代表作", "备注")):
        table.rows[0].cells[i].text = h
    roles = [("编剧", proj.screenwriter), ("导演", proj.director),
             ("制片人", proj.producer)]
    for name in [c.strip() for c in proj.cast.replace(",", "，").split("，")
                 if c.strip()]:
        roles.append(("演员", name))
    for role, name in roles:
        if not name:
            continue
        row = table.add_row().cells
        row[0].text = role
        row[1].text = name
        row[2].text = ""
        row[3].text = ""
        row[4].text = ""
    out = _materials_dir(root, proj) / "主创人员登记表.docx"
    doc.save(str(out))
    return out


# ----------------------------------------------------------------------
def build_transcript_doc(root: Path, proj: FilmProject,
                         segments: list[tuple[float, float, str]]) -> Path:
    """完成台本（docx）：转录对白 + 时间码（场次信息需人工补充）。"""
    doc = _doc(f"完成台本 — {proj.title_cn or '未命名'}")
    doc.add_paragraph("说明：本台本由平台自动转录生成（时间码 HH:MM:SS），"
                      "对白识别可能存在误差，请与成片核对；场次/镜头描述需人工补充。")
    for start, _end, text in segments:
        doc.add_paragraph(f"[{_ts(start)}] {text.strip()}")
    out = _materials_dir(root, proj) / "完成台本.docx"
    doc.save(str(out))
    return out


# ----------------------------------------------------------------------
def inspect_dcp(dcp_dir: Path) -> dict:
    """解析 DCP 关键技术参数（供技术报告与 UI 展示）。"""
    info: dict = {}
    cpl = find_cpl(dcp_dir)
    if cpl:
        root_xml = ET.parse(str(cpl)).getroot()

        def texts(tag):
            return [(el.text or "").strip() for el in root_xml.iter()
                    if el.tag.split("}")[-1] == tag]
        info["CPL 名称"] = (texts("ContentTitleText") or ["—"])[0]
        creator = (texts("Creator") or [""])[0]
        if creator:
            info["溯源（Creator）"] = creator
        info["画幅（SAR）"] = (texts("ScreenAspectRatio") or ["—"])[0]
        info["帧率"] = (texts("FrameRate") or ["—"])[0]
        dur = texts("Duration")
        if dur:
            info["时长（秒）"] = f"{int(dur[0]) / 24:.1f}"
    j2c = [p for p in dcp_dir.iterdir()
           if p.suffix.lower() == ".mxf" and p.name.lower().startswith("j2c")]
    pcm = [p for p in dcp_dir.iterdir()
           if p.suffix.lower() == ".mxf" and p.name.lower().startswith("pcm")]
    if j2c:
        info["视频素材（j2c）"] = f"{len(j2c)} 个 / " \
            f"{sum(p.stat().st_size for p in j2c) / 2**30:.1f} GiB"
    if pcm:
        info["音频素材（pcm）"] = f"{len(pcm)} 个 / " \
            f"{sum(p.stat().st_size for p in pcm) / 2**30:.1f} GiB"
    info["ISDCF 命名"] = dcp_dir.name
    info["文件总数"] = str(sum(1 for _ in dcp_dir.iterdir()))
    return info


def build_qc_report(root: Path, proj: FilmProject,
                    dcp_dir: Path) -> tuple[Path, dict]:
    """DCP 技术自检报告（docx）。"""
    info = inspect_dcp(dcp_dir)
    doc = _doc(f"DCP 技术自检报告 — {proj.title_cn or '未命名'}")
    doc.add_paragraph("本报告由短剧转电影平台对 DCP 包自动检测生成，"
                      "对照 SMPTE DCP（GY/T 266 系列）规范自检，"
                      "不替代电影主管部门的技术审查。")
    _kv(doc, list(info.items()))
    doc.add_heading("自检清单", level=2)
    for c in [
        "ASSETMAP / VOLINDEX / PKL / CPL 结构完整",
        "视频 MXF（JPEG 2000）与音频 MXF（PCM）齐备",
        "帧率 24fps（DCI 通用标准）",
        "画幅与目标容器一致（Flat 1998×1080 / Scope 2048×858）",
        "ISDCF 命名规范（大写字母/数字/下划线）",
        "响度已按 EBU R128 预归一（影院终混建议人工复核 Leq(m)）",
        "未加密（如发行需要 KDM，须另配密钥体系）",
    ]:
        doc.add_paragraph(c, style="List Bullet")
    doc.add_paragraph("送审提示：终审母版须加龙标片头；如加密须提供有效期"
                      "不少于 90 天的 KDM；具体以国家电影局最新《电影片送审须知》为准。")
    out = _materials_dir(root, proj) / "DCP技术自检报告.docx"
    doc.save(str(out))
    return out, info
