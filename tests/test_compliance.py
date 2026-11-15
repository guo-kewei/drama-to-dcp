"""合规工作台单元测试：项目模型 / 红线扫描 / 文档生成 / DCP 参数解析。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.compliance.models import FilmProject, PROCESS_STAGES, StageRecord
from app.compliance.redline import scan


class TestModels(unittest.TestCase):
    def test_save_load_roundtrip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = FilmProject(title_cn="测试片", title_en="TEST FILM",
                            synopsis="情节" * 10, duration_min=90)
            p.stage_log.append(StageRecord(key="filing", date="2026-11-15",
                                           note="已提交"))
            p.save(root)
            loaded = FilmProject.list_all(root)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].title_cn, "测试片")
            self.assertEqual(loaded[0].synopsis_len(), 20)
            self.assertEqual(loaded[0].stage_log[0].key, "filing")

    def test_forward_compat(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "备案" / "X1"
            root.mkdir(parents=True)
            (root / "project.json").write_text(json.dumps({
                "title_cn": "旧项目", "unknown_field": 1}), encoding="utf-8")
            p = FilmProject.load(root / "project.json")
            self.assertEqual(p.title_cn, "旧项目")
            self.assertEqual(p.director, "")

    def test_stages_ordered(self):
        keys = [k for k, _ in PROCESS_STAGES]
        self.assertEqual(keys[0], "materials")
        self.assertEqual(keys[-1], "release")


class TestTimestampAlign(unittest.TestCase):
    """funasr 逐字时间戳 → 句段落（标点不占时间戳位）。"""

    def test_align_and_split(self):
        from app.compliance.transcript import _segments_from_timestamps
        # 4 个非标点字 + 1 标点 + 3 字 + 标点
        text = "你好世界。继续说！"
        ts = [[100, 200], [200, 300], [300, 400], [400, 500],
              [600, 700], [700, 800], [800, 900]]
        segs = _segments_from_timestamps(text, ts)
        self.assertEqual(len(segs), 2)
        self.assertAlmostEqual(segs[0][0], 0.1)
        self.assertAlmostEqual(segs[0][1], 0.5)
        self.assertEqual(segs[0][2], "你好世界。")
        self.assertAlmostEqual(segs[1][0], 0.6)
        self.assertEqual(segs[1][2], "继续说！")

    def test_no_timestamp_fallback(self):
        from app.compliance.transcript import _segments_from_timestamps
        self.assertEqual(_segments_from_timestamps("整段文本", None),
                         [(0.0, 0.0, "整段文本")])


class TestRedline(unittest.TestCase):
    def test_scan_hits_and_misses(self):
        text = ("主角在赌场教学后参与吸毒方法演示，还有恐怖组织袭击情节。"
                "普通剧情对白不应命中。")
        hits = scan(text)
        cats = {h["category"] for h in hits}
        self.assertIn("赌博/毒品", cats)
        self.assertIn("危害国家安全/主权", cats)   # 恐怖组织
        self.assertTrue(all(h["count"] >= 1 for h in hits))
        samples = [s for h in hits for s in h["samples"]]
        self.assertTrue(any("赌场教学" in s for s in samples))

    def test_scan_empty(self):
        self.assertEqual(scan(""), [])


class TestDocuments(unittest.TestCase):
    def test_docx_generation(self):
        import tempfile
        from app.compliance import documents
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = FilmProject(title_cn="文档测试", title_en="DOC TEST",
                            synopsis="梗概" * 100, director="张三",
                            screenwriter="李四", producer="王五",
                            cast="赵六，钱七")
            out1 = documents.build_filing_report(root, p)
            out2 = documents.build_crew_form(root, p)
            out3 = documents.build_transcript_doc(
                root, p, [(0.0, 2.5, "你好世界"), (65.0, 70.0, "对白二")])
            for f in (out1, out2, out3):
                self.assertTrue(f.is_file() and f.stat().st_size > 4000, f)

    def test_qc_report_on_real_dcp_structure(self):
        """用最小 DCP 目录结构验证 inspect_dcp/build_qc_report。"""
        import tempfile
        from app.compliance import documents
        CPL = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<CompositionPlaylist xmlns="http://www.smpte-ra.org/schemas/429/2008/CPL">'
               '<ContentTitleText>TEST_FTR-1_F_XX-XX_51_2K_20261115_SMPTE_OV</ContentTitleText>'
               '<ReelList><Reel><AssetList>'
               '<MainPicture><ScreenAspectRatio>1998 1080</ScreenAspectRatio>'
               '<FrameRate>24 1</FrameRate><Duration>2160</Duration></MainPicture>'
               '<MainSound><Channels>6</Channels></MainSound>'
               '</AssetList></Reel></ReelList></CompositionPlaylist>')
        with tempfile.TemporaryDirectory() as td:
            dcp = Path(td) / "TEST_FTR-1_F_XX-XX_51_2K_20261115_SMPTE_OV"
            dcp.mkdir()
            (dcp / "ASSETMAP.xml").write_text("<AssetMap/>")
            (dcp / "VOLINDEX").write_text("1")
            (dcp / "cpl_x.xml").write_text(CPL, encoding="utf-8")
            (dcp / "j2c_a.mxf").write_bytes(b"v" * 10000)
            (dcp / "pcm_b.mxf").write_bytes(b"a" * 10000)
            info = documents.inspect_dcp(dcp)
            self.assertEqual(info["画幅（SAR）"], "1998 1080")
            self.assertEqual(info["帧率"], "24 1")
            self.assertIn("90.0", info["时长（秒）"])
            root = Path(td)
            p = FilmProject(title_cn="技审测试")
            out, _ = documents.build_qc_report(root, p, dcp)
            self.assertTrue(out.is_file() and out.stat().st_size > 4000)




class TestProvenance(unittest.TestCase):
    """CPL 溯源标记 + PKL/ASSETMAP 同步修正。"""

    def _mk(self, tmp: Path) -> Path:
        d = tmp / "TEST_FTR-1_F_XX-XX_51_2K_20261115_SMPTE_OV"
        d.mkdir()
        cpl = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<CompositionPlaylist xmlns="http://www.smpte-ra.org/schemas/429/2008/CPL">'
               '<Id>urn:uuid:1</Id><ContentTitleText>T</ContentTitleText>'
               '<ReelList><Reel><AssetList>'
               '<MainPicture><ScreenAspectRatio>1998 1080</ScreenAspectRatio>'
               '<Duration>24</Duration></MainPicture>'
               '</AssetList></Reel></ReelList></CompositionPlaylist>')
        (d / "cpl_a.xml").write_text(cpl, encoding="utf-8")
        (d / "pkl_a.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?><PackingList>'
            '<Asset><Id>urn:uuid:1</Id><Hash>OLD==</Hash><Size>9</Size>'
            '<Type>text/xml</Type>'
            '<OriginalFilename>cpl_a.xml</OriginalFilename></Asset>'
            '<Asset><Id>urn:uuid:2</Id><Hash>OTHER==</Hash><Size>5</Size>'
            '<Type>application/mxf</Type>'
            '<OriginalFilename>j2c_b.mxf</OriginalFilename></Asset>'
            '</PackingList>', encoding="utf-8")
        (d / "ASSETMAP.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?><AssetMap>'
            '<Asset><Id>urn:uuid:1</Id><Chunk><Path>cpl_a.xml</Path>'
            '<Length>9</Length></Chunk></Asset>'
            '</AssetMap>', encoding="utf-8")
        return d

    def test_marker_and_sync(self):
        import base64
        import hashlib
        import tempfile
        from app.pipeline.provenance import add_creator_marker, get_creator
        with tempfile.TemporaryDirectory() as td:
            d = self._mk(Path(td))
            r = add_creator_marker(d, "Drama2DCP v0.1.0")
            self.assertTrue(r["done"])
            self.assertEqual(get_creator(d), "Drama2DCP v0.1.0")
            data = (d / "cpl_a.xml").read_bytes()
            want = base64.b64encode(hashlib.sha1(data).digest()).decode()
            self.assertEqual(r["hash"], want)
            self.assertEqual(r["size"], len(data))
            pkl = (d / "pkl_a.xml").read_text(encoding="utf-8")
            self.assertIn(want, pkl)
            self.assertNotIn("OLD==", pkl)
            self.assertIn("OTHER==", pkl)          # 其他资产的哈希不被误改
            amap = (d / "ASSETMAP.xml").read_text(encoding="utf-8")
            self.assertIn(f"<Length>{len(data)}</Length>", amap)
            r2 = add_creator_marker(d, "Drama2DCP v0.1.0")
            self.assertFalse(r2["done"])           # 幂等


if __name__ == "__main__":
    unittest.main(verbosity=2)
