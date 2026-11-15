"""审查回归：取消接线（P1-6）——3 秒后取消，应在命令执行中数秒内停下。"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.core.config import load_settings
from app.core.task import TaskConfig, TaskState
from app.pipeline.runner import PipelineRunner

s = load_settings()
cfg = TaskConfig(
    source_dir=str(pathlib.Path("tests/media/测试A_16x9").resolve()),
    dcp_name="RG_CANCEL", gap=0,
    output_root=str(pathlib.Path("tests/tmp_review/rg_cancel").resolve()))
st = TaskState.new(cfg)
flip_at = time.time() + 3
cancel = lambda: time.time() > flip_at
r = PipelineRunner(s, st, cancel_flag=cancel)
t0 = time.time()
result = r.run()
dt = time.time() - t0
print(f"结果: {result.stage} | 用时: {dt:.1f}s | 错误: {result.error[:40]}")
assert result.stage == "cancelled", result.stage
assert dt < 25, f"取消响应过慢: {dt:.1f}s"
print("取消在命令执行中即时生效 ✅")
