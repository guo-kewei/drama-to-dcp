"""审查回归：工作区锁（P2-13）——被其他存活进程占用时拒绝启动。"""
import os
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.core.config import load_settings
from app.core.task import TaskConfig, TaskState
from app.pipeline.runner import PipelineRunner

# 起一个 30 秒的存活进程
p = subprocess.Popen(
    ["ping", "-n", "30", "127.0.0.1"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NO_WINDOW)
try:
    time.sleep(0.5)
    assert p.poll() is None

    s = load_settings()
    cfg = TaskConfig(
        source_dir=str(pathlib.Path("tests/media/测试B_scope").resolve()),
        dcp_name="RG_LOCK", gap=0,
        output_root=str(pathlib.Path("tests/tmp_review/rg_lock").resolve()))
    st = TaskState.new(cfg)
    st.resolved_container = "flat"

    runner = PipelineRunner(s, st)          # 先正常拿锁
    lock = runner.workdir / "task.lock"
    assert lock.is_file()
    runner._release_lock()

    # 伪造：锁指向另一个存活进程
    lock.write_text(str(p.pid), encoding="utf-8")
    try:
        PipelineRunner(s, st)
        raise AssertionError("应当拒绝启动但成功了")
    except RuntimeError as e:
        assert "其他进程" in str(e), e
        print(f"锁生效 ✅ ({e})")
finally:
    p.kill()
    lock.unlink(missing_ok=True)
print("工作区锁测试通过 ✅")
