"""UI 视觉自查截图：三页 + 任务卡片多状态。输出 tests/tmp_review/shots/ui_v2_*.png"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

app = QApplication([])
from app.ui.theme import apply
apply(app)

from app.ui.main_window import MainWindow
from app.ui.queue_page import TaskCard
from app.core.task import Episode, TaskConfig, TaskState

OUT = pathlib.Path(__file__).resolve().parent / "shots"
OUT.mkdir(exist_ok=True)

w = MainWindow()
w.resize(1160, 840)
w.show()

# ---- 新建转换页（注入扫描结果 + 名称/预览）
page = w.page_new
page.set_folder(r"E:\AI\短剧转电影自动化平台\tests\media\测试A_16x9")
page.ed_title.setText("穿越时空的爱恋")
from app.core.naming import suggest_dcp_name
page.ed_dcp_name.setText(suggest_dcp_name("穿越时空的爱恋"))
page._scan_gen += 1
gen = page._scan_gen
page._scan_done(gen, [
    dict(index=1, path="第01集.mp4", width=1920, height=1080, fps=30.0,
         duration=8.0, audio_channels=2, audio_layout="stereo",
         vcodec="h264", acodec="aac", normalized=False, skipped=False, error=""),
    dict(index=2, path="第02集.mp4", width=1920, height=1080, fps=30.0,
         duration=7.0, audio_channels=2, audio_layout="stereo",
         vcodec="h264", acodec="aac", normalized=False, skipped=False, error=""),
    dict(index=3, path="第03集.mp4", width=0, height=0, fps=0, duration=0,
         audio_channels=0, audio_layout="", vcodec="", acodec="",
         normalized=False, skipped=False, error="ffprobe 失败: " + "损坏数据" * 20),
], dict(total=3, ok=2, bad=1, total_duration=15.0, width=1920, height=1080,
        mixed_resolution=False, fps_set=[30.0], audio_ch_set=[2],
        recommended_container="flat", errors=[]))
app.processEvents()
w.grab().save(str(OUT / "ui_v2_new.png"))

# ---- 任务队列页（4 张不同状态卡片，不启动线程）
w.stack.setCurrentIndex(1)

def card(title, dcp, stage_key, cont, prog=0.0, err="", out=""):
    cfg = TaskConfig(source_dir=r"E:\drama\某剧100集", title=title,
                     dcp_name=dcp)
    st = TaskState.new(cfg)
    st.stage = stage_key          # 非 pending，add_task 不会自动启动
    st.resolved_container = cont
    st.progress = prog
    st.error = err
    st.dcp_output_dir = out
    c = TaskCard(w.settings, st)
    w.queue_lay.addWidget(c)
    return c

c1 = card("霸总的逆袭", "BZDDNX_2026", "normalizing", "flat", 0.42)
c1.lb_msg.setText("归一化 第42集: 第042集.mp4")
card("龙王的赘婿人生", "LWDZSR", "packaging", "scope", 0.91)
card("闪婚老公是大佬", "SHLGSDL", "done", "flat",
     out=r"E:\输出\DCP\SHLGSDL")
c4 = card("离婚后我成了女王", "LHHCNW", "failed", "flat",
          err="质检未通过: 时长偏差过大（已移入隔离区）")
c4.lb_msg.setText("❌ 质检未通过: 时长偏差过大（已移入隔离区）")
app.processEvents()
w.grab().save(str(OUT / "ui_v2_queue.png"))

# ---- 设置页
w.stack.setCurrentIndex(2)
app.processEvents()
w.grab().save(str(OUT / "ui_v2_settings.png"))

print("截图完成:", [p.name for p in OUT.glob("ui_v2_*.png")])
