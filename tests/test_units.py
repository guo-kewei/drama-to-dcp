"""单元测试：画幅匹配、滤镜链、上混引擎、DCP 名称、CPL 校验。

运行: python -m pytest tests/ -v  （或 python tests/test_units.py）
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.task import (CONTAINERS, container_size, recommend_container,
                           sanitize_dcp_name)
from app.engines import get_upmix_engine, list_upmix_engines
from app.engines.rule import RuleUpmixEngine
from app.pipeline.normalize import video_filter


class TestAspect(unittest.TestCase):
    def test_recommend(self):
        self.assertEqual(recommend_container(1920, 1080), "flat")   # 1.78
        self.assertEqual(recommend_container(2560, 1080), "scope")  # 2.37
        self.assertEqual(recommend_container(2048, 858), "scope")   # 2.39
        self.assertEqual(recommend_container(3840, 1600), "scope")  # 2.4
        self.assertEqual(recommend_container(1998, 1080), "flat")   # 1.85
        self.assertEqual(recommend_container(1000, 0), "flat")      # 防御

    def test_container_size(self):
        self.assertEqual(container_size("flat", "2k"), (1998, 1080))
        self.assertEqual(container_size("scope", "2k"), (2048, 858))
        self.assertEqual(container_size("full", "2k"), (2048, 1080))
        self.assertEqual(container_size("flat", "4k"), (3996, 2160))
        self.assertEqual(container_size("scope", "4k"), (4096, 1716))

    def test_containers_ratio(self):
        self.assertEqual(CONTAINERS["flat"]["ratio"], 185)
        self.assertEqual(CONTAINERS["scope"]["ratio"], 239)


class TestFilters(unittest.TestCase):
    def test_fill(self):
        f = video_filter(1998, 1080, "fill")
        self.assertIn("force_original_aspect_ratio=increase", f)
        self.assertIn("crop=1998:1080", f)
        self.assertIn("fps=24", f)

    def test_fit(self):
        f = video_filter(2048, 858, "fit")
        self.assertIn("force_original_aspect_ratio=decrease", f)
        self.assertIn("pad=2048:858", f)


class TestUpmixEngines(unittest.TestCase):
    def test_registry(self):
        ids = {e["id"] for e in list_upmix_engines()}
        self.assertIn("rule", ids)
        self.assertIn("ai", ids)

    def test_rule_51_filter(self):
        f = RuleUpmixEngine().build_filter("5.1")
        self.assertIn("pan=6c", f)
        self.assertEqual(f.count("|"), 6)          # pan=6c| + 6 定义间 5 个
        # C = 0.5L+0.5R 对白中置
        self.assertIn("c2=0.5*c0+0.5*c1", f)
        # 声道顺序: c4/c5 为环绕
        self.assertIn("c4=0.35*c0", f)

    def test_rule_71_filter(self):
        f = RuleUpmixEngine().build_filter("7.1")
        self.assertIn("pan=8c", f)
        self.assertIn("c6=0.25*c0", f)   # BsL
        self.assertIn("c7=0.25*c1", f)   # BsR

    def test_ai_not_configured(self):
        eng = get_upmix_engine("ai")
        with self.assertRaises(RuntimeError):
            eng.process(Path("a.wav"), Path("b.wav"), "5.1", None, {})

    def test_unknown_engine(self):
        with self.assertRaises(KeyError):
            get_upmix_engine("nope")


class TestDCPName(unittest.TestCase):
    def test_sanitize(self):
        self.assertEqual(sanitize_dcp_name("My Movie 2026"), "MY_MOVIE_2026")
        self.assertEqual(sanitize_dcp_name("穿越时空的爱恋"), "UNTITLED")
        self.assertEqual(sanitize_dcp_name("  霸总--归来 EP1 "), "EP1")
        self.assertEqual(sanitize_dcp_name("abc"), "ABC")
        # 全部非法字符时取 fallback
        self.assertEqual(sanitize_dcp_name("===###"), "UNTITLED")


class TestCPLVerify(unittest.TestCase):
    """用一段最小 SMPTE CPL 样例验证 verify 逻辑（不依赖真实 DCP）。"""
    CPL_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<CompositionPlaylist xmlns="http://www.smpte-ra.org/schemas/429/2008/CPL">
 <Id>urn:uuid:6a2b7cf1-5e20-4f83-85a5-3b6e2f0a1b2c</Id>
 <ContentTitleText>TEST_FTR_S_2K_SMPTE</ContentTitleText>
 <ReelList><Reel><AssetList>
  <MainPicture>
   <Id>urn:uuid:7b3c8df2-6f31-4a94-96b6-4c7f3a1b2c3d</Id>
   <ScreenAspectRatio>1998 1080</ScreenAspectRatio>
   <FrameRate>24 1</FrameRate>
   <Duration>1440</Duration>
  </MainPicture>
  <MainSound>
   <Id>urn:uuid:8c4d9ef3-7a42-5ba5-a7c7-5d8a4b2c3d4e</Id>
   <Channels>6</Channels>
  </MainSound>
 </AssetList></Reel></ReelList>
</CompositionPlaylist>"""

    def test_verify_ok(self):
        import tempfile
        from app.core.task import TaskConfig, TaskState
        from app.pipeline.verify import verify_dcp
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "ASSETMAP.xml").write_text("<AssetMap/>")
            (d / "VOLINDEX").write_text("1")
            (d / "PKL_xxx.xml").write_text("<PKL/>")
            (d / "j2c.mxf").write_bytes(b"v" * 100)
            (d / "aud.mxf").write_bytes(b"a" * 100)
            (d / "CPL_test.xml").write_text(self.CPL_SAMPLE, encoding="utf-8")
            st = TaskState.new(TaskConfig(source_dir=str(d)))
            st.resolved_container = "flat"
            st.config.audio_layout = "5.1"
            st.expected_total = 60.0     # 1440/24=60s
            ok, problems, info = verify_dcp(d, st)
            self.assertTrue(ok, problems)
            self.assertEqual(info["screen_aspect_ratio"], "1998 1080")
            self.assertEqual(info["audio_channels"], "6")

    def test_verify_bad_aspect(self):
        import tempfile
        from app.core.task import TaskConfig, TaskState
        from app.pipeline.verify import verify_dcp
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "ASSETMAP.xml").write_text("x")
            (d / "VOLINDEX").write_text("1")
            (d / "PKL_x.xml").write_text("x")
            (d / "a.mxf").write_bytes(b"x" * 10)
            (d / "b.mxf").write_bytes(b"x" * 10)
            (d / "CPL_t.xml").write_text(self.CPL_SAMPLE, encoding="utf-8")
            st = TaskState.new(TaskConfig(source_dir=str(d)))
            st.resolved_container = "scope"          # 期望 2048 858，实际 1998 1080
            st.config.audio_layout = "5.1"
            st.expected_total = 60.0
            ok, problems, _ = verify_dcp(d, st)
            self.assertFalse(ok)
            self.assertTrue(any("画幅" in p for p in problems))

    def test_verify_4k_expectation(self):
        """4K 任务的 CPL 预期应为容器×2（回归 P0-1）。"""
        import tempfile
        from app.core.task import TaskConfig, TaskState
        from app.pipeline.verify import _expected_sar
        st = TaskState.new(TaskConfig(source_dir="x", resolution="4k"))
        st.resolved_container = "flat"
        self.assertEqual(_expected_sar(st), "3996 2160")
        st.resolved_container = "scope"
        self.assertEqual(_expected_sar(st), "4096 1716")
        st.config.resolution = "2k"
        self.assertEqual(_expected_sar(st), "2048 858")

    def test_verify_stereo_wants_6ch(self):
        """stereo 目标也产 6ch DCP（仅填 L/R），CPL 声道预期=6（回归 P2-20）。"""
        import tempfile
        from app.core.task import TaskConfig, TaskState
        from app.pipeline.verify import verify_dcp
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "ASSETMAP.xml").write_text("x")
            (d / "VOLINDEX").write_text("1")
            (d / "PKL_x.xml").write_text("x")
            (d / "j2c_a.mxf").write_bytes(b"x" * 10)
            (d / "pcm_b.mxf").write_bytes(b"x" * 10)
            (d / "cpl_t.xml").write_text(
                self.CPL_SAMPLE.replace("<Channels>6</Channels>",
                                        "<Channels>6</Channels>"),
                encoding="utf-8")
            st = TaskState.new(TaskConfig(source_dir=str(d),
                                          audio_layout="stereo"))
            st.resolved_container = "flat"
            st.expected_total = 60.0
            ok, problems, info = verify_dcp(d, st)
            self.assertTrue(ok, problems)     # stereo + CPL 6ch 应通过
            self.assertEqual(info["audio_channels"], "6")

    def test_taskstate_forward_compat(self):
        """旧版 state.json 缺新字段/多未知字段均可加载（回归 P3-30）。"""
        import json
        import tempfile
        from app.core.task import TaskConfig, TaskState
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "state.json"
            p.write_text(json.dumps({
                "task_id": "T1",
                "config": {"source_dir": "x", "future_field": 1},
                "episodes": [{"index": 1, "path": "a", "new_field": 2}],
                "stage": "failed",
                "unknown_top": True,
            }, ensure_ascii=False), encoding="utf-8")
            st = TaskState.load(p)
            self.assertEqual(st.task_id, "T1")
            self.assertEqual(st.config.source_dir, "x")
            self.assertEqual(st.config.output_root, "")   # 缺省字段取默认
            self.assertEqual(st.episodes[0].path, "a")


class TestCancellationWiring(unittest.TestCase):
    """取消异常体系（回归 P1-6 的接线基础）。"""

    def test_tool_cancelled_importable(self):
        from app.tools import ToolCancelled
        from app.tools.dcpomatic import ToolCancelled as T2
        from app.tools.ffmpeg import ToolCancelled as T1
        self.assertIs(T1, ToolCancelled)
        self.assertIs(T2, ToolCancelled)


class TestISDCFPreview(unittest.TestCase):
    """ISDCF 预览与 DCP-o-matic 实际命名对齐（真实素材实测修正）。"""

    def test_aspect_codes(self):
        from app.core.naming import ASPECT_CODE, isdcf_preview
        self.assertEqual(ASPECT_CODE["flat"], "F")    # 实测 WanwanS1_..._F_...
        self.assertEqual(ASPECT_CODE["scope"], "S")   # 实测 TestScope71_..._S_...
        p = isdcf_preview("MYDRAMA", "FTR", "flat", "2k", "5.1",
                          "SMPTE", date="20261114")
        self.assertEqual(
            p, "MYDRAMA_FTR-1_F_XX-XX_51_2K_20261114_SMPTE_OV")

    def test_71_and_stereo_codes(self):
        from app.core.naming import isdcf_preview
        self.assertIn("_71_", isdcf_preview("X", "FTR", "scope", "4k", "7.1",
                                            "SMPTE", date="20260101"))
        self.assertIn("_20_", isdcf_preview("X", "FTR", "flat", "2k", "stereo",
                                            "SMPTE", date="20260101"))


class TestChannelMapPatch(unittest.TestCase):
    """7.1 声道直连补丁（真实素材发现的 HI/VI 误映射修正）。"""

    FILM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Film>
 <Playlist>
  <Content><Type>FFmpeg</Type><Path>C:/x/master_audio.wav</Path>
   <AudioStream>
    <Mapping>
     <InputChannels>8</InputChannels><OutputChannels>16</OutputChannels>
     <Gain input="0" output="0">1</Gain>
     <Gain input="6" output="8">1</Gain>
     <Gain input="7" output="9">1</Gain>
    </Mapping>
   </AudioStream>
  </Content>
  <Content><Type>FFmpeg</Type><Path>C:/x/master_video.mp4</Path></Content>
 </Playlist>
</Film>"""

    def test_patch(self):
        import tempfile
        import xml.etree.ElementTree as ET
        from app.pipeline.dcp import _patch_channel_map
        with tempfile.TemporaryDirectory() as td:
            film = Path(td)
            (film / "metadata.xml").write_text(self.FILM_XML, encoding="utf-8")
            _patch_channel_map(film, 8)
            root = ET.parse(str(film / "metadata.xml")).getroot()
            gains = {(int(g.get("input")), int(g.get("output"))): g.text
                     for g in root.iter("Gain")}
            # 逐声道直连：i==i 为 1
            self.assertEqual(gains[(0, 0)], "1")
            self.assertEqual(gains[(6, 6)], "1")   # BsL
            self.assertEqual(gains[(7, 7)], "1")   # BsR
            # HI/VI 误映射被清除
            self.assertEqual(gains[(6, 8)], "0")
            self.assertEqual(gains[(7, 9)], "0")
            self.assertEqual(
                root.find(".//InputChannels").text, "8")


if __name__ == "__main__":
    unittest.main(verbosity=2)
