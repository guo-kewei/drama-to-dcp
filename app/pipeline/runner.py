"""流水线编排器：串联五阶段，支持进度回调、取消、断点恢复、报告。"""
from __future__ import annotations

import html
import os
import shutil
import time
from pathlib import Path
from typing import Callable, Optional

from ..core.config import PROJECT_ROOT, Settings
from ..core.task import (TaskState, recommend_container, sanitize_dcp_name,
                         stage_label)
from ..engines import get_enhancer, get_upmix_engine
from ..tools import ToolCancelled
from ..tools.dcpomatic import DCPoMatic
from ..tools.ffmpeg import FFmpeg
from . import concat as concat_mod
from . import dcp as dcp_mod
from . import normalize as norm_mod
from . import probe as probe_mod
from . import verify as verify_mod


class Cancelled(RuntimeError):
    pass


def _pid_alive(pid: int) -> bool:
    """Windows 下探测进程是否存活（用于工作区锁的陈旧检测）。"""
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    k32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        if k32.GetExitCodeProcess(h, ctypes.byref(code)):
            return code.value == STILL_ACTIVE
        return False
    finally:
        k32.CloseHandle(h)


class RunnerCallbacks:
    """UI/CLI 订阅的回调集合（全部可选）。"""

    def __init__(self,
                 on_stage=None,          # (stage_key, label) -> None
                 on_progress=None,       # (0~1 总进度) -> None
                 on_message=None,        # (str) -> None
                 on_log=None):           # (str) -> None
        self.on_stage = on_stage or (lambda *a: None)
        self.on_progress = on_progress or (lambda *a: None)
        self.on_message = on_message or (lambda *a: None)
        self.on_log = on_log or (lambda *a: None)


# 各阶段在总进度中的区间
_STAGE_SPAN = {
    "scanning": (0.00, 0.05),
    "normalizing": (0.05, 0.75),
    "concatenating": (0.75, 0.85),
    "packaging": (0.85, 0.97),
    "verifying": (0.97, 1.00),
}


class PipelineRunner:
    def __init__(self, settings: Settings, state: TaskState,
                 cbs: Optional[RunnerCallbacks] = None,
                 cancel_flag: Optional[Callable[[], bool]] = None):
        self.s = settings
        self.state = state
        self.cbs = cbs or RunnerCallbacks()
        self._cancel = cancel_flag or (lambda: False)
        # 工具
        self.ff = FFmpeg.discover(settings.ffmpeg_dir or None, PROJECT_ROOT)
        self.dom = DCPoMatic.discover(settings.dcpomatic_dir or None, PROJECT_ROOT)
        # 目录（任务级 output_root 优先）
        src = Path(state.config.source_dir)
        root = (Path(state.config.output_root)
                if state.config.output_root else settings.output_root_path(src))
        self.out_root = root
        self.ws_root = root / "工作区"
        self.workdir = self.ws_root / state.task_id
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.workdir / "task.lock"
        self._acquire_lock()

    # ------------------------------------------------------------------ 锁
    #: 锁文件超过该时长视为陈旧（进程崩溃残留 / PID 被复用），可安全接管
    LOCK_STALE_SECONDS = 6 * 3600

    def _acquire_lock(self):
        if self._lock_path.is_file():
            try:
                old = int(self._lock_path.read_text().strip() or 0)
            except ValueError:
                old = 0
            try:
                age = time.time() - self._lock_path.stat().st_mtime
            except OSError:
                age = 0.0
            # 同 PID 允许复入（同进程内 GUI 重试）；存活进程且锁未陈旧则拒绝
            if old and old != os.getpid() and _pid_alive(old) \
                    and age < self.LOCK_STALE_SECONDS:
                raise RuntimeError(
                    f"任务 {self.state.task_id} 正在被其他进程(PID {old})处理，"
                    f"请等待其完成或关闭该进程后重试")
            if old:
                self.cbs.on_log(f"⚠ 检测到{'陈旧' if age >= self.LOCK_STALE_SECONDS else '已退出进程的'}"
                                f"锁(PID {old}, {age/3600:.1f}h)，已接管任务")
        self._lock_path.write_text(str(os.getpid()), encoding="utf-8")

    def _release_lock(self):
        try:
            self._lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    # ------------------------------------------------------------------ 基础
    def _check_cancel(self):
        if self._cancel():
            raise Cancelled()

    def _stage(self, key: str):
        self.state.stage = key
        self._stage_key = key
        self.cbs.on_stage(key, stage_label(key))
        self.cbs.on_message(stage_label(key) + "…")

    def _prog(self, frac_in_stage: float):
        lo, hi = _STAGE_SPAN.get(self._stage_key, (0, 1))
        total = lo + max(0.0, min(1.0, frac_in_stage)) * (hi - lo)
        self.state.progress = total
        self.cbs.on_progress(total)

    def _log(self, line: str):
        self.cbs.on_log(line)

    # ------------------------------------------------------------------
    def run(self) -> TaskState:
        st = self.state
        try:
            try:
                self._validate()
                self._run_scan()
                self._run_normalize()
                self._run_concat()
                self._run_dcp()
                self._run_verify()
                st.stage = "done"
                st.progress = 1.0
                st.finished_at = time.time()
                self.cbs.on_message("✅ 完成")
            except (Cancelled, ToolCancelled):
                st.stage = "cancelled"
                st.error = "用户取消"
                self.cbs.on_message("已取消")
            except Exception as e:
                st.stage = "failed"
                st.error = str(e)
                st.finished_at = time.time()
                self._log(f"❌ 失败: {e}")
                self.cbs.on_message(f"失败: {e}")
            # 即使保存/报告环节出错也要释放锁
            try:
                self._save()
                self._write_report()
            except Exception as e:
                self._log(f"⚠ 状态保存/报告生成异常: {e}")
        finally:
            self._release_lock()
        return st

    # ------------------------------------------------------------------
    def _validate(self):
        """启动前 fail-fast 校验：引擎可用性等配置错误立即报错，
        而不是逐集失败伪装成坏素材。"""
        st = self.state
        layout = st.config.audio_layout
        if layout != "stereo":
            engine = get_upmix_engine(st.config.upmix_engine)
            ok, why = engine.available(self.s.engine_cfg)
            if not ok:
                raise RuntimeError(why)

    # ------------------------------------------------------------------
    def _save(self):
        self.state.save(self.ws_root)

    def _run_scan(self):
        st = self.state
        self._check_cancel()
        self._stage("scanning")

        resume = st.episodes and any(e.width for e in st.episodes)
        if not resume:
            eps, summary = probe_mod.scan_folder(
                self.ff, Path(st.config.source_dir),
                on_episode=lambda i, n, name:
                    self._prog(i / n) or self.cbs.on_message(
                        f"探测 {i}/{n}: {name}"))
            st.episodes = eps
            self._log(f"扫描完成: {summary}")
            # 解析画幅选择
            cont = st.config.container
            if cont == "auto":
                cont = summary["recommended_container"]
            st.resolved_container = cont
            if not st.config.title:
                st.config.title = Path(st.config.source_dir).name
            if not st.config.dcp_name:
                st.config.dcp_name = sanitize_dcp_name(st.config.title)
            self._recompute_expected()
        else:
            if not st.resolved_container:
                good = [e for e in st.episodes if e.width]
                st.resolved_container = (
                    st.config.container if st.config.container != "auto"
                    else recommend_container(
                        max(e.width for e in good),
                        max(e.height for e in good)))
            self._prog(1.0)
        self._log(f"集数={len(st.episodes)} 容器={st.resolved_container} "
                  f"预计总时长={st.expected_total:.0f}s")

    def _recompute_expected(self):
        """按当前实际参与拼接的集（归一化成功且未跳过）重算预期成片时长。
        跳集发生后调用，避免质检用错预期值误隔离成品。"""
        st = self.state
        part = [e for e in st.episodes if e.normalized and not e.skipped
                and not e.error]
        if not part:
            # 尚未开始归一化时按探测正常的集预估
            part = [e for e in st.episodes if not e.error]
        st.expected_total = (sum(e.duration for e in part)
                             + max(len(part) - 1, 0) * st.config.gap)

    # ------------------------------------------------------------------
    def _run_normalize(self):
        st = self.state
        self._stage("normalizing")
        enhancer = get_enhancer(self.s.engine_cfg)
        good_eps = [e for e in st.episodes if not e.error]
        all_dur = sum(e.duration for e in good_eps) or 1.0
        done_dur = 0.0
        for ep in st.episodes:
            self._check_cancel()
            if ep.error:
                if self.s.bad_episode_policy == "abort":
                    raise RuntimeError(f"第{ep.index}集损坏，策略=中止: {ep.error}")
                ep.skipped = True
                self._log(f"⚠ 跳过坏集 {Path(ep.path).name}: {ep.error}")
                continue
            if ep.normalized:
                done_dur += ep.duration
                continue
            self.cbs.on_message(f"归一化 第{ep.index}集: {Path(ep.path).name}")

            def ep_prog_cb(p, _d=ep.duration, _acc=done_dur):
                self._prog(min(0.999, (_acc + p * _d) / all_dur))

            try:
                # 超分挂载点（未配置时直通，零成本）
                src_for_norm = Path(ep.path)
                if enhancer.id != "none":
                    tmp = self.workdir / "norm" / f"ep_{ep.index:03d}_enhanced.mp4"
                    self._log(f"超分引擎处理 第{ep.index}集 …")
                    src_for_norm = enhancer.process(Path(ep.path), tmp,
                                                    self.s.engine_cfg)
                norm_mod.normalize_episode(
                    self.ff, st, ep, self.workdir,
                    cfg_engine=self.s.engine_cfg,
                    on_progress=ep_prog_cb, log=self._log,
                    cancel_flag=self._cancel,
                    src_override=src_for_norm if enhancer.id != "none" else None)
                ep.normalized = True
            except ToolCancelled:
                raise
            except Exception as e:
                if self.s.bad_episode_policy == "abort":
                    raise RuntimeError(
                        f"第{ep.index}集归一化失败(策略=中止): {e}") from e
                ep.skipped = True
                ep.error = str(e)
                self._log(f"⚠ 跳过失败集 {Path(ep.path).name}: {e}")
            done_dur += ep.duration
            self._save()
        # 跳集后重算预期时长，并明确告知用户
        skipped = [e for e in st.episodes if e.skipped]
        self._recompute_expected()
        if skipped:
            self._log(f"⚠ 共 {len(skipped)} 集被跳过，成片时长相应缩短为 "
                      f"{st.expected_total:.0f}s；质检按缩短后的时长校验")
            self.cbs.on_message(f"⚠ {len(skipped)} 集被跳过，成片时长缩短")
        part = [e for e in st.episodes if e.normalized and not e.skipped]
        if not part:
            raise RuntimeError(
                "没有一集能成功归一化——素材可能全部损坏，或处理配置有误"
                "（详见日志）")
        self._prog(1.0)

    # ------------------------------------------------------------------
    def _run_concat(self):
        st = self.state
        self._stage("concatenating")
        self._check_cancel()
        for e in st.episodes:
            if e.normalized and not e.skipped and e.audio_channels >= 6 \
                    and st.config.audio_layout != "stereo":
                self._log("ℹ 多声道源直通（不经上混引擎、不做响度归一），"
                          "与立体声源混合时可能存在响度差异")
                break
        master_v, master_a = concat_mod.concat_master(
            self.ff, st, self.workdir, on_progress=self._prog,
            cancel_flag=self._cancel)
        self.master_v, self.master_a = master_v, master_a

        # 实测成片时长：源元数据可能虚报（如下载不完整的截断文件），
        # 偏差大时以实测值为质检基准，避免"好片被误隔离"
        try:
            actual = float(self.ff.probe(master_v)
                           .get("format", {}).get("duration") or 0)
        except Exception:
            actual = 0.0
        if actual > 0 and abs(actual - st.expected_total) > 2.0:
            self._log(f"⚠ 实测成片时长 {actual:.1f}s 与按源元数据预计的 "
                      f"{st.expected_total:.1f}s 偏差较大（源时长元数据不准"
                      f"或素材截断）。质检将按实测时长 {actual:.1f}s 校验")
            self.cbs.on_message(f"⚠ 实测时长 {actual:.1f}s 与预计 "
                                f"{st.expected_total:.1f}s 不符，已按实测校验")
            st.expected_total = actual

    # ------------------------------------------------------------------
    def _run_dcp(self):
        st = self.state
        self._stage("packaging")
        self._check_cancel()
        film_dir = self.workdir / "film"
        out_dir = self.out_root / "DCP"
        last = 0.0

        def pack_prog(p):
            nonlocal last
            if p - last > 0.05 or p >= 1.0:
                last = p
                self._prog(p)

        dcp = dcp_mod.build_dcp(
            self.dom, st, self.master_v, self.master_a,
            film_dir, out_dir,
            standard=self.s.standard,
            video_bit_rate=self.s.j2k_bitrate_mbps,
            encode_threads=self.s.dcp_encode_threads,
            log=self._log,
            on_progress=pack_prog, cancel_flag=self._cancel)
        st.dcp_output_dir = str(dcp)
        self._save()
        self._prog(1.0)

    # ------------------------------------------------------------------
    def _run_verify(self):
        st = self.state
        self._stage("verifying")
        self._check_cancel()
        dcp_dir = Path(st.dcp_output_dir)
        ok, problems, info = verify_mod.verify_dcp(dcp_dir, st)
        st.verify = dict(ok=ok, problems=problems, info=info)  # type: ignore[attr-defined]
        self._prog(0.5)
        if not ok:
            # 移入隔离区
            q = self.out_root / "隔离区"
            q.mkdir(parents=True, exist_ok=True)
            target = q / (dcp_dir.name + time.strftime("_%H%M%S"))
            shutil.move(str(dcp_dir), str(target))
            st.quarantined_dir = str(target)                    # type: ignore[attr-defined]
            raise RuntimeError("质检未通过: " + "; ".join(problems)
                               + f"（已移入隔离区 {target}）")
        self._log(f"质检通过: {info}")
        self._prog(1.0)

    # ------------------------------------------------------------------
    def _write_report(self):
        st = self.state
        try:
            rep_dir = self.out_root / "reports"
            rep_dir.mkdir(parents=True, exist_ok=True)
            skipped = [e for e in st.episodes if e.skipped]
            rows = "".join(
                f"<tr><td>{e.index}</td><td>{html.escape(Path(e.path).name)}</td>"
                f"<td>{e.width}×{e.height}</td><td>{e.duration:.1f}s</td>"
                f"<td>{'✅' if e.normalized else ('⏭跳过' if e.skipped else '—')}</td>"
                f"<td>{html.escape((e.error or '').replace(chr(10), ' ')[:120])}</td></tr>"
                for e in st.episodes)
            verify = getattr(st, "verify", None)
            quarantined = getattr(st, "quarantined_dir", "")
            verify_html = (
                "<h2>质检</h2><p class='ok'>✅ 通过</p>"
                if verify and verify["ok"] else
                f"<h2>质检</h2><p class='bad'>❌ {'; '.join(verify['problems']) if verify else html.escape(st.error or '')}</p>"
                + (f"<p>隔离位置：<code>{html.escape(quarantined)}</code></p>"
                   if quarantined else ""))
            info_html = "".join(
                f"<li>{k}: {html.escape(str(v))}</li>"
                for k, v in (verify or {}).get("info", {}).items())
            title = html.escape(st.config.title)
            skip_note = (f"<p class='warn'>⚠ {len(skipped)} 集被跳过，"
                         f"成片时长相应缩短</p>" if skipped else "")
            body = f"""<!doctype html><meta charset="utf-8">
<style>
body{{font-family:"Microsoft YaHei",sans-serif;margin:24px;color:#1f2937}}
h1{{font-size:22px}} h2{{font-size:17px;margin-top:20px}}
table{{border-collapse:collapse;font-size:13px}}
th,td{{border:1px solid #d1d5db;padding:4px 8px;text-align:left}}
th{{background:#f3f4f6}} code{{background:#f3f4f6;padding:1px 4px}}
.ok{{color:#16a34a;font-weight:bold}} .bad{{color:#dc2626;font-weight:bold}}
.warn{{color:#d97706}}
</style>
<h1>转制报告 — {title}</h1>
<p>任务 {st.task_id} | 状态 {stage_label(st.stage)} |
   容器 {st.resolved_container} {st.config.resolution} |
   音频 {st.config.audio_layout}({st.config.upmix_engine}) |
   DCP 名称 {html.escape(st.config.dcp_name)}</p>
<p>成片时长 {st.expected_total:.0f}s | 完成时间
   {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
{skip_note}
{verify_html}<ul>{info_html}</ul>
<h2>分集（共 {len(st.episodes)} 集，成功 {len(st.episodes)-len(skipped)}，跳过 {len(skipped)}）</h2>
<table><tr><th>#</th><th>文件</th><th>分辨率</th><th>时长</th><th>状态</th><th>错误</th></tr>
{rows}</table>
"""
            (rep_dir / f"{st.task_id}.html").write_text(body, encoding="utf-8")
        except Exception as e:      # 报告失败不影响任务状态
            self._log(f"报告生成失败: {e}")
