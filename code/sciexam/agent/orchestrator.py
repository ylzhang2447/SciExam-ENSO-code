"""The run lifecycle of the formal harness.

Phase 1   data processing, checked by the hidden data gate, up to `phase1_max_attempts`
          turns of at most `phase1_turn_cap_s` each.
Phase 2A  the agent writes its own checks under diagnostics/ (at most `phase2a_cap_s`).
          Checks that do not run get up to `diagnostics_repair_rounds` repair turns, then
          diagnostics/ is made read-only (root owned, mode 555).
Phase 2B  one continuous agent session with the Stop hook armed, resumed whenever the
          agent exits, until the eligible budget is spent. A separate thread snapshots the
          submission every `snapshot_every_s` of eligible time when its content changed.

The budget is ELIGIBLE time: wall time minus pauses credited for a provider-stated
allocation reset or a provider service condition (bounded per event and in total, see the
lifecycle block of the arm config). A pause freezes the clock while it happens, and no
agent runs while the clock is frozen.
"""
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from . import data_gate
from . import prompts as P
from .scaffolds import TurnResult

BUNDLE_FILES = ("model.py", "params.json", "model_card.md")
TASK_INPUTS = ("nondim_scales.json",)
BUNDLE_REREADS = 3


def _iso(epoch):
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


class Run:
    """State shared by the orchestrator and the scaffold adapters."""

    def __init__(self, arm, ws, ctr_ws, results, ctr, proxy_env, credentials, obs_file,
                 smoke=False, gate=None):
        self.arm = arm
        self.ws = Path(ws)
        self.ctr_ws = ctr_ws
        self.results = Path(results)
        self.snapshots = self.results / "snapshots"
        self.ctr = ctr
        self.uid = arm["lifecycle"]["agent_uid"]
        self.proxy_env = proxy_env
        self._credentials = credentials
        self.obs_file = obs_file
        self.smoke = smoke
        # Phase 1 gate: data_gate.grade, or the label-translating gate of the year-anonymised
        # condition (anonymise.gate), called as gate(submission_dir, obs_file).
        self.gate = gate or data_gate.grade
        self.L = arm["lifecycle"]
        self._log_lock = threading.Lock()
        self._snap_lock = threading.RLock()

    def credential(self, name):
        return self._credentials.get(name, "")

    def secret_values(self, names):
        return {k: self._credentials.get(k, "") for k in names}

    def log(self, event):
        event["t"] = round(time.time(), 1)
        with self._log_lock:
            with open(self.ws / "trajectory.jsonl", "a") as f:
                f.write(json.dumps(event) + "\n")

    # ---- workspace -----------------------------------------------------------------

    def install_stop_hook(self, enabled):
        """Claude Code consults the Stop hook before exiting. It is off in Phase 1 and 2A,
        whose ending signal is the agent stopping, and on in Phase 2B."""
        home = self.ctr_ws + "/.home/.claude"
        sub = self.ctr_ws + "/submission"
        hook = home + "/stop-hook.sh"
        if enabled:
            self.ctr.put(hook, P.STOP_HOOK, mode="755", owner=self.uid)
            self.ctr.put(home + "/hook-env.sh", P.stop_hook_env(sub), owner=self.uid)
        self.ctr.put(home + "/settings.json", P.stop_hook_settings(sub, hook, enabled),
                     owner=self.uid)
        self.ctr.root(["chown", self.uid, self.ctr_ws + "/.home", home])

    def check_diagnostics_run(self):
        bad = []
        d = self.ws / "diagnostics"
        for f in sorted(d.glob("*.py")):
            try:
                r = subprocess.run(self.ctr.exec_argv(["python3", "diagnostics/" + f.name],
                                                      env=self.proxy_env, workdir=self.ctr_ws),
                                   timeout=self.L["diagnostics_check_timeout_s"],
                                   capture_output=True)
                if r.returncode != 0 or not (r.stdout or b"").strip():
                    err = (r.stderr or b"").decode(errors="replace").strip().splitlines()
                    bad.append({"script": f.name,
                                "error": (err[-1] if err else "no output")[:200]})
            except subprocess.TimeoutExpired:
                bad.append({"script": f.name, "error": "timed out after %ds"
                            % self.L["diagnostics_check_timeout_s"]})
            except Exception as e:
                bad.append({"script": f.name, "error": "%s: %s" % (type(e).__name__, e)})
        return bad

    def freeze_diagnostics(self):
        d = self.ctr_ws + "/diagnostics"
        n = len(list((self.ws / "diagnostics").glob("*.py")))
        ok = True
        for cmd in (["mkdir", "-p", d], ["chown", "-R", "root:root", d], ["chmod", "-R", "555", d]):
            r = self.ctr.root(cmd)
            if r.returncode != 0:
                ok = False
                self.log({"event": "freeze_failed", "cmd": " ".join(cmd), "rc": r.returncode})
        r = self.ctr.root(["stat", "-c", "%u %a", d])
        try:
            uid, mode = r.stdout.decode().split()
            enforced = uid == "0" and not (int(mode, 8) & 0o222)
        except ValueError:
            mode, enforced = "?", False
        if not ok:
            self.log({"event": "freeze_unenforced"})
        self.log({"event": "diagnostics_frozen", "scripts": n, "mode": "0o" + mode,
                  "enforced": bool(enforced)})
        return n

    def audit_diagnostics(self, frozen_at):
        import re
        wd = self.ws
        d = wd / "diagnostics"
        kept = {}
        for f in sorted(d.glob("*.py")):
            try:
                kept[f.name] = f.read_text(errors="replace")
            except OSError:
                pass
        after = []
        for f in wd.rglob("*.py"):
            if d in f.parents or ".home" in f.parts or "papers" in f.parts:
                continue
            if "__pycache__" in f.parts or f.parent.name == "submission":
                continue
            try:
                if f.stat().st_mtime <= frozen_at:
                    continue
                txt = f.read_text(errors="replace")
            except OSError:
                continue
            loads_model = "ENSOModel" in txt or "params.json" in txt
            reads_obs = ("indices.csv" in txt or "processed/" in txt or "obs_" in txt
                         or "observed" in txt.lower())
            if loads_model and reads_obs:
                after.append(str(f.relative_to(wd)))

        def covers(pat):
            rx = re.compile(pat, re.I)
            return sum(1 for t in kept.values() if rx.search(t))
        rep = {"frozen_scripts": len(kept),
               "lines": sum(len(t.splitlines()) for t in kept.values()),
               "reads_submission": covers(r"params\.json|ENSOModel"),
               "covers_statistics": covers(r"acf|autocorr|seasonal|skew|kde|variance|std"),
               "covers_forecast": covers(r"forecast|persistence|lead|skill|rmse"),
               "covers_coupling": covers(r"enkf|enks|kalman|assimilat|reconstruct|nash"),
               "covers_coupling_lag": covers(r"lag[_ ]?corr|cross[_ ]?corr|lead|lag=|phase.*corr"),
               "holds_out_data": covers(r"held|holdout|train_df|set.aside"),
               "written_after_freeze": after[:20], "n_written_after_freeze": len(after)}
        (self.results / "diagnostics_audit.json").write_text(json.dumps(rep, indent=2))
        return rep

    # ---- snapshots -----------------------------------------------------------------

    def _read_bundle(self):
        sub = self.ws / "submission"
        prev, files, sha = None, {}, None
        for _ in range(BUNDLE_REREADS):
            files, h = {}, hashlib.sha256()
            for name in BUNDLE_FILES:
                f = sub / name
                try:
                    if f.exists():
                        b = f.read_bytes()
                        files[name] = b
                        h.update(name.encode())
                        h.update(b)
                except OSError:
                    return None, None, False
            sha = h.hexdigest()
            if prev == sha:
                return files, sha, True
            prev = sha
        return files, sha, False

    def _publish(self, dest, files, extras):
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=dest.name + ".tmp-", dir=str(dest.parent)))
        try:
            for name, b in list(files.items()) + list(extras.items()):
                with open(tmp / name, "wb") as f:
                    f.write(b)
                    f.flush()
                    os.fsync(f.fileno())
            if dest.exists():
                old = Path(str(dest) + ".superseded-%d" % int(time.time() * 1000))
                os.rename(str(dest), str(old))
                os.rename(str(tmp), str(dest))
                shutil.rmtree(old, ignore_errors=True)
            else:
                os.rename(str(tmp), str(dest))
            tmp = None
        finally:
            if tmp is not None:
                shutil.rmtree(str(tmp), ignore_errors=True)

    def snapshot_once(self, seen, curve, start, elapsed_fn):
        """Copy the submission if its content is new. Returns the round index or None."""
        with self._snap_lock:
            files, sha, stable = self._read_bundle()
            if not files:
                return None
            if not stable:
                self.log({"event": "snapshot_failed", "reason": "bundle_unstable",
                          "retryable": True})
                return None
            if sha in seen:
                return None
            idx = len(seen) + 1
            extras = {}
            for name in TASK_INPUTS:
                src = self.ws / name
                if src.exists():
                    extras[name] = src.read_bytes()
            try:
                self._publish(self.snapshots / ("round_%02d" % idx), files, extras)
            except Exception as e:
                self.log({"event": "snapshot_failed", "round": idx - 1,
                          "error": "%s: %s" % (type(e).__name__, e), "retryable": True})
                return None
            seen.add(sha)
            wall_min = round((time.time() - start) / 60.0, 1)
            elapsed_min = round(elapsed_fn() / 60.0, 1)
            curve.append({"round": idx - 1, "elapsed_min": elapsed_min,
                          "wall_elapsed_min": wall_min, "clock": "eligible", "final": None})
            self.log({"event": "snapshot", "round": idx - 1, "elapsed_min": elapsed_min,
                      "wall_elapsed_min": wall_min, "clock": "eligible", "sha": sha[:12]})
            return idx


def orchestrate(run, agent, budget_s):
    """Drive one agent through the phases. Returns a summary dict."""
    L = run.L
    raw_turn = agent.turn

    def agent_fn(prompt, timeout, resume=False, append=False):
        # Every prompt of every arm carries the persistent-memory policy, appended once.
        return raw_turn(P.with_memory_policy(prompt), timeout, resume=resume, append=append)

    run.install_stop_hook(False)
    start = time.time()
    clock = {"paused_s": 0.0, "pause_since": None, "agent_running": False}
    pause = {"quota_pause_s": 0.0, "provider_service_pause_s": 0.0, "quota_pause_events": 0,
             "provider_service_pause_events": 0, "uncredited_wait_s": 0.0, "log": []}
    wall_ceiling_s = budget_s * L["max_wall_multiple"]

    def eligible():
        paused = clock["paused_s"]
        if clock.get("pause_since"):
            paused += time.time() - clock["pause_since"]
        return (time.time() - start) - paused

    def remaining():
        return budget_s - eligible()

    def elapsed_pair():
        return {"elapsed_min": round(eligible() / 60.0, 1),
                "wall_elapsed_min": round((time.time() - start) / 60.0, 1), "clock": "eligible"}

    def paused_sleep(seconds, credit_bound, reason, meta):
        assert not clock["agent_running"], "no agent may run while eligible time is paused"
        t0 = time.time()
        clock["pause_since"] = t0
        try:
            end_t = t0 + max(0.0, seconds)
            while time.time() < end_t:
                if (time.time() - start) >= wall_ceiling_s:
                    break
                time.sleep(min(5.0, max(0.0, end_t - time.time())))
            waited = time.time() - t0
            cap_room = max(0.0, budget_s * L["pause_total_credit_cap_multiple"]
                           - clock["paused_s"])
            credited = max(0.0, min(waited, credit_bound, cap_room))
        finally:
            clock["pause_since"] = None
        clock["paused_s"] += credited
        pause["uncredited_wait_s"] += round(waited - credited, 3)
        rec = dict(event="eligible_pause", reason=reason, waited_s=round(waited, 1),
                   credited_pause_s=round(credited, 1),
                   uncredited_counted_s=round(waited - credited, 1),
                   credit_bound_s=round(credit_bound, 1), credit_cap_room_s=round(cap_room, 1),
                   start=_iso(t0), end=_iso(time.time()),
                   eligible_elapsed_s=round(eligible(), 1),
                   wall_elapsed_s=round(time.time() - start, 1), **meta)
        pause["log"].append(rec)
        run.log(rec)
        return waited, credited

    run.log({"event": "start", "budget_s": budget_s, "feedback": False, "smoke": run.smoke})

    # ---- Phase 1 ----
    passed, fb = False, None
    for att in range(L["phase1_max_attempts"]):
        if remaining() <= 0:
            break
        agent_fn(P.phase1_prompt(fb), min(remaining(), L["phase1_turn_cap_s"]))
        result = run.gate(run.ws / "submission", run.obs_file)
        passed, fb = P.phase1_feedback(result)
        run.log({"event": "phase1_check", "attempt": att, "passed": passed, "feedback": fb,
                 "remaining_s": round(remaining(), 1)})
        if passed:
            break
    if not passed and run.smoke:
        run.log({"event": "SMOKE_phase1_bypassed", "real_passed": passed,
                 "note": "smoke run: phase 1 not required, not a graded result"})
        passed = True
    if not passed:
        run.log({"event": "end", "status": "phase1_failed"})
        return {"status": "phase1_failed", "learning_curve": []}
    if remaining() <= 0:
        run.log({"event": "end", "status": "budget_exhausted_before_phase2"})
        return {"status": "budget_exhausted", "learning_curve": []}

    # ---- Phase 2A ----
    run.install_stop_hook(False)
    t2a = time.time()
    agent_fn(P.phase2a_prompt(remaining() / 60.0), min(remaining(), L["phase2a_cap_s"]))
    for _ in range(L["diagnostics_repair_rounds"]):
        bad = run.check_diagnostics_run()
        run.log({"event": "diagnostics_check", "failed": bad,
                 "elapsed_min": round((time.time() - t2a) / 60.0, 1)})
        if not bad or remaining() <= 0 or (time.time() - t2a) >= L["phase2a_cap_s"]:
            break
        agent_fn(P.diagnostics_repair_prompt(bad),
                 min(remaining(), L["phase2a_cap_s"] - (time.time() - t2a)),
                 resume=True, append=True)
    n_diag = run.freeze_diagnostics()
    frozen_at = time.time()
    run.log({"event": "phase2a_done", "minutes": round((time.time() - t2a) / 60.0, 1),
             "diagnostics": n_diag, "hit_cap": (time.time() - t2a) >= L["phase2a_cap_s"] - 5})
    if remaining() <= 0:
        run.log({"event": "end", "status": "budget_exhausted_in_phase2a"})
        return {"status": "budget_exhausted", "learning_curve": []}

    # ---- Phase 2B ----
    run.install_stop_hook(True)
    curve, seen = [], set()
    stop_snap = threading.Event()

    def snapshot_loop():
        next_at = L["snapshot_every_s"]
        while not stop_snap.wait(min(5.0, L["snapshot_every_s"])):
            if eligible() < next_at:
                continue
            next_at = eligible() + L["snapshot_every_s"]
            try:
                run.snapshot_once(seen, curve, start, eligible)
            except Exception as e:
                run.log({"event": "snapshot_error", "error": repr(e)[:200]})
    snap = threading.Thread(target=snapshot_loop, daemon=True)
    snap.start()

    resumes, turns, status = 0, [], "complete"
    first, stall = True, 0
    last_progress_t, no_improve_s = time.time(), 0.0
    plateau_logged, hard_fail, productive_fatal = False, 0, 0
    qw = {"quota_wait_events": 0, "quota_wait_seconds_total": 0.0, "quota_resume_attempts": 0,
          "quota_resume_successes": 0, "quota_resume_failures": 0}
    pending_quota_resume = False
    while remaining() > 0:
        prompt = (P.phase2_prompt(remaining() / 60.0) if first
                  else P.resume_prompt(no_improve_s, L["stall_escalate_s"]))
        before = len(curve)
        clock["agent_running"] = True
        try:
            res = agent_fn(prompt, remaining(), resume=not first, append=not first)
        finally:
            clock["agent_running"] = False
        first = False
        run.snapshot_once(seen, curve, start, eligible)
        if len(curve) == before:
            stall += 1
        else:
            stall = 0
            last_progress_t = time.time()
            plateau_logged = False
        no_improve_s = time.time() - last_progress_t
        res = res or TurnResult()
        turns.append(res.to_dict())
        run.log(dict(event="turn", resumes=resumes, stall=stall,
                     time_since_last_unique_snapshot_s=round(no_improve_s, 1),
                     remaining_s=round(remaining(), 1), **res.to_dict()))
        if res.timed_out:
            status = "complete"
            break
        if (run.ws / "BUDGET_EXCEEDED").exists():
            status = "budget_cap"
            run.log({"event": "budget_cap", "note": "runaway cap reached"})
            break
        qinfo = res.quota_wait
        if qinfo is not None and qinfo.get("bounded") is False:
            run.log({"event": "allocation_exhausted_unbounded", "reason": qinfo.get("reason"),
                     "matched_phrase": qinfo.get("matched_phrase"),
                     "note": "no provider-stated reset, no pause credited",
                     "eligible_elapsed_s": round(eligible(), 1)})
            qinfo = None
        if qinfo and L["pause_on_quota"] and qw["quota_wait_events"] < L["quota_wait_max_events"]:
            if pending_quota_resume:
                qw["quota_resume_failures"] += 1
            target = max(float(qinfo["reset_delay_s"]) + L["quota_wait_recovery_margin_s"],
                         L["quota_wait_min_s"])
            qw["quota_wait_events"] += 1
            run.log({"event": "quota_wait", "quota_reset_source": qinfo.get("reset_source"),
                     "quota_reset_raw": qinfo.get("reset_raw"), "planned_wait_s": round(target, 1),
                     "remaining_s_before_wait": round(remaining(), 1)})
            waited, credited = paused_sleep(target, float(qinfo["reset_delay_s"]), "quota",
                                            {"quota_reset_source": qinfo.get("reset_source")})
            pause["quota_pause_s"] += credited
            pause["quota_pause_events"] += 1
            qw["quota_wait_seconds_total"] += waited
            if (time.time() - start) >= wall_ceiling_s:
                status = "provider_infrastructure_failed"
                run.log({"event": "provider_infrastructure_failed",
                         "reason": "wall-time ceiling exceeded while paused"})
                break
            if remaining() <= 0:
                status = "complete"
                run.log(dict(event="quota_wait_deadline_reached", **elapsed_pair()))
                break
            qw["quota_resume_attempts"] += 1
            pending_quota_resume = True
            resumes += 1
            run.log({"event": "resume", "attempt": resumes, "after": "quota_wait"})
            continue
        if pending_quota_resume:
            pending_quota_resume = False
            qw["quota_resume_successes"] += 1
        if res.elapsed_s < L["min_runtime_for_resume_s"]:
            status = "agent_failed_fast"
            break
        if res.exit_code not in (0, None):
            tinfo = res.transient
            if (res.productive or 0) > 0:
                hard_fail = 0
                productive_fatal += 1
                run.log(dict(event="productive_fatal", consecutive=productive_fatal,
                             productive_calls=res.productive, exit_code=res.exit_code,
                             transient=bool(tinfo), limit=L["productive_fatal_limit"],
                             **elapsed_pair()))
                if productive_fatal >= L["productive_fatal_limit"]:
                    status = "agent_failed_repeated_productive_fatal"
                    break
            else:
                hard_fail += 1
                if hard_fail >= L["hard_fail_limit"]:
                    status = "agent_failed_hard"
                    run.log(dict(event="agent_failed_hard", consecutive=hard_fail,
                                 exit_code=res.exit_code, **elapsed_pair()))
                    break
            if tinfo:
                spacing = float(tinfo["retry_spacing_s"])
                stated = tinfo.get("spacing_source") in ("retry_after", "stated_interval")
                bound = min(spacing if stated else L["provider_service_pause_granularity_s"],
                            L["pause_max_per_provider_event_s"])
                run.log({"event": "transient_service_wait",
                         "matched_phrase": tinfo.get("matched_phrase"),
                         "planned_spacing_s": round(spacing, 1),
                         "pause_credit_bound_s": round(bound, 1)})
                waited, credited = paused_sleep(
                    spacing, bound if L["pause_on_provider_service"] else 0.0,
                    "provider_service", {"matched_phrase": tinfo.get("matched_phrase")})
                pause["provider_service_pause_s"] += credited
                pause["provider_service_pause_events"] += 1
                if (time.time() - start) >= wall_ceiling_s:
                    status = "provider_infrastructure_failed"
                    break
        else:
            hard_fail = 0
            productive_fatal = 0
        if no_improve_s >= 3 * L["stall_escalate_s"] and not plateau_logged:
            plateau_logged = True
            run.log(dict(event="plateau",
                         time_since_last_unique_snapshot_s=round(no_improve_s, 1),
                         stall_rounds=stall, remaining_min=round(remaining() / 60.0, 1),
                         **elapsed_pair()))
        resumes += 1
        run.log({"event": "resume", "attempt": resumes})

    stop_snap.set()
    snap.join(timeout=10)
    run.snapshot_once(seen, curve, start, eligible)
    try:
        da = run.audit_diagnostics(frozen_at)
        run.log(dict(event="diagnostics_audit",
                     **{k: v for k, v in da.items() if k != "written_after_freeze"}))
    except Exception as e:
        run.log({"event": "diagnostics_audit", "error": "%s: %s" % (type(e).__name__, e)})
    summary = dict(qw)
    summary.update(
        wall_elapsed_s=round(time.time() - start, 1), eligible_elapsed_s=round(eligible(), 1),
        quota_pause_s=round(pause["quota_pause_s"], 1),
        provider_service_pause_s=round(pause["provider_service_pause_s"], 1),
        quota_pause_events=pause["quota_pause_events"],
        provider_service_pause_events=pause["provider_service_pause_events"],
        uncredited_wait_counted_s=round(pause["uncredited_wait_s"], 1),
        pause_detail=pause["log"],
        active_agent_seconds=round(sum(t.get("elapsed_s", 0.0) for t in turns), 1))
    run.log(dict(event="quota_summary", **summary))
    run.log({"event": "end", "status": status, "rounds": len(curve), "resumes": resumes,
             "turns": turns, "learning_curve": curve})
    return {"status": status, "learning_curve": curve, "resumes": resumes, "clock": summary}
