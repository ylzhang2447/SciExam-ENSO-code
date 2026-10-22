"""Command line interface: ``sciexam <command>``."""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import dataset as DS


def _data_root(a):
    return DS.open_verified(a.data_dir)


def cmd_download(a):
    t0 = time.time()
    root = DS.download(local=a.local, root=a.data_dir, revision=a.revision)
    n = len(DS.read_manifest(root))
    print("dataset ready at %s (%d files, sha256 verified, %.1f s)" % (root, n, time.time() - t0))


def cmd_build_image(a):
    from .grader import sandbox
    dt = sandbox.build_image(a.image)
    print("built %s in %.0f s" % (a.image, dt))


SCORE_KEYS = ("statistics", "physics", "predictivity", "composite")
RETRY_STATUSES = (None, "timeout", "grader_error", "internal_error")
GRADE_TOL = 5e-5        # absolute: half a unit of the fourth decimal that the records are compared at


def _compare(r, rec):
    """'match' (equal at 4 decimals), 'within tolerance' (|diff| < GRADE_TOL, so the value differs
    from the record only in the rounding of the fourth decimal), 'MISMATCH', 'no record' or 'FAILED'.
    The records are never changed."""
    if r.get("status") != "scored":
        return "FAILED", None
    if rec is None or rec.get("composite") is None:
        return "no record", None
    pairs = [(r[k], rec[k]) for k in SCORE_KEYS if rec.get(k) is not None]
    diff = max(abs(g - w) for g, w in pairs)
    if all(round(g, 4) == round(w, 4) for g, w in pairs):
        return "match", diff
    if diff < GRADE_TOL:
        return "within tolerance", diff
    return "MISMATCH", diff


def _result_row(label, r, rec):
    verdict, diff = _compare(r, rec)
    if verdict == "FAILED":
        return "%-34s %-6s %s" % (label, "", "FAILED: %s %s" % (r.get("status"), str(r.get("error", r.get("hard_gate", "")))[:200]))
    cells = " ".join("%8.4f" % r[k] for k in SCORE_KEYS)
    if verdict == "no record":
        return "%-34s %5.0f %s %8s  (no record)" % (label, r["calendar_offset"], cells, "")
    return "%-34s %5.0f %s %8.4f  %s (max |diff| %.1e)" % (
        label, r["calendar_offset"], cells, rec["composite"], verdict, diff)


def _check_offset(s):
    if abs(s - round(s)) > 1e-12:
        raise SystemExit("error: the calendar offset must be a whole number of months, got %r" % s)


def _jobs_for_split(root, split):
    runs = DS.read_table(root, "runs.csv")
    jobs = []
    if split == "final":
        for r in runs:
            if r["group"] not in ("main", "reference"):
                continue
            rec = {k: r["final_" + k] for k in SCORE_KEYS}
            jobs.append(dict(label=r["display_name"], run_id=r["run_id"], arm=r["arm"],
                             key=r["run_id"].replace("/", "__"), dir=root / r["model_dir"],
                             s=float(r["calendar_offset"]), record=rec))
    elif split == "checkpoints":
        base = {}
        for r in runs:
            if r["group"] == "main":
                base[r["run_id"]] = root / "models" / "checkpoints" / Path(r["model_dir"]).name
            elif r["group"] == "fable_condition":
                base[r["run_id"]] = root / "models" / "fable_conditions" / r["run_id"].split("/", 1)[1]
        for c in DS.read_table(root, "checkpoints.csv"):
            if not c["graded"] or c["run_id"] not in base:
                continue
            d = base[c["run_id"]] / c["round"]
            if not (d / "model.py").exists():
                continue          # checkpoint recorded but its files are not released
            short = c["run_id"].split("/", 1)[1]
            label = "%s %s" % (short, c["round"])
            jobs.append(dict(label=label, run_id=c["run_id"], arm=c["arm"], round=c["round"],
                             key="%s__%s" % (c["run_id"].replace("/", "__"), c["round"]), dir=d,
                             s=float(c["calendar_offset"]), record={k: c[k] for k in SCORE_KEYS},
                             is_best=c["is_best"], is_final=c["is_final"]))
    else:
        raise SystemExit("unknown split %r" % split)
    for j in jobs:
        _check_offset(j["s"])
    return jobs


def _pool(jobs, n, slow_max, is_slow, fn, on_done):
    """Run ``fn`` over ``jobs`` on ``n`` threads, with at most ``slow_max`` slow jobs at once."""
    import threading
    cv = threading.Condition()
    slow = [j for j in jobs if is_slow(j)]
    fast = [j for j in jobs if not is_slow(j)]
    running = [0]

    def take():
        with cv:
            while True:
                if slow and running[0] < slow_max:
                    running[0] += 1
                    return slow.pop(0), True
                if fast:
                    return fast.pop(0), False
                if not slow:
                    return None, False
                cv.wait()

    def worker():
        while True:
            j, sl = take()
            if j is None:
                return
            try:
                r = fn(j)
            except Exception as e:  # keep the pool alive, the job is retried on the next run
                r = dict(status="internal_error", error=repr(e), calendar_offset=j["s"])
            finally:
                if sl:
                    with cv:
                        running[0] -= 1
                        cv.notify_all()
            on_done(j, r)


    th = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, n))]
    for t in th:
        t.start()
    for t in th:
        t.join()


def _best_reselection(jobs, results, runs):
    """Re-select best and final per run from the regraded composites (runs whose every
    graded checkpoint is released)."""
    by_run = {}
    for j in jobs:
        by_run.setdefault(j["run_id"], []).append(j)
    out = []
    for r in runs:
        rid = r["run_id"]
        if rid not in by_run:
            continue
        js = by_run[rid]
        complete = len(js) == r["n_checkpoints_graded"]
        scored = [(results[j["key"]]["composite"], j["round"]) for j in js
                  if results.get(j["key"], {}).get("status") == "scored"]
        if not complete or len(scored) != len(js):
            out.append(dict(run_id=rid, best_round=None, record_best_round=r["best_round"],
                            note="only %d of %d checkpoints released or scored" % (len(scored), r["n_checkpoints_graded"])))
            continue
        # the earliest checkpoint wins a tie (consecutive snapshots are often byte identical)
        best = max(scored, key=lambda x: (x[0], -int(x[1].split("_")[-1])))
        out.append(dict(run_id=rid, best_round=best[1], best_composite=best[0],
                        record_best_round=r["best_round"], agrees=best[1] == r["best_round"]))
    return out


def cmd_grade(a):
    from .grader import sandbox
    root = _data_root(a)
    jobs = _jobs_for_split(root, a.split)
    arms = a.arm or a.only
    if arms:
        keep = set(arms.split(","))
        jobs = [j for j in jobs if j["arm"] in keep or j["run_id"].split("/")[-1] in keep]
    slow_keys = set(x for x in os.environ.get("SCIEXAM_SLOW", "gpt6astra").split(",") if x)
    is_slow = lambda j: j["arm"] in slow_keys  # noqa: E731
    jobs.sort(key=lambda j: 0 if is_slow(j) else 1)   # slow first so that they do not form the tail
    out_dir = Path(a.out or "sciexam_results/%s" % a.split)
    out_dir.mkdir(parents=True, exist_ok=True)
    results, todo = {}, []
    for j in jobs:
        f = out_dir / (j["key"] + ".json")
        if f.exists():
            try:
                r = json.loads(f.read_text())
            except ValueError:
                r = {}
            if r.get("status") not in RETRY_STATUSES:
                results[j["key"]] = r
                continue
        todo.append(j)
    sandbox.ensure_image(a.image)
    print("grading %d submissions (%d already in %s), %d in parallel (at most %d of %s), image %s" % (
        len(todo), len(results), out_dir, a.jobs, a.slow_max, ",".join(sorted(slow_keys)), a.image), flush=True)
    t0 = time.time()
    done = [0]

    def one(j):
        return sandbox.run(j["dir"], root / "grader_obs", s=j["s"], image=a.image,
                           timeout_s=a.timeout, fallback_scales=root / "task" / "nondim_scales.json")

    def on_done(j, r):
        (out_dir / (j["key"] + ".json")).write_text(json.dumps(r, indent=1))
        results[j["key"]] = r
        done[0] += 1
        verdict, _ = _compare(r, j["record"])
        print("  [%d/%d %5.0f min] %-34s %-8s %6.0f s  composite %s  %s" % (
            done[0], len(todo), (time.time() - t0) / 60, j["label"], r.get("status"),
            r.get("wall_seconds", 0),
            "%.4f" % r["composite"] if r.get("composite") is not None else "-", verdict), flush=True)

    _pool(todo, a.jobs, a.slow_max, is_slow, one, on_done)
    wall = time.time() - t0
    print("\n%-34s %5s %8s %8s %8s %8s %8s" % ("submission", "s", "stat", "phys", "pred", "composite", "record"))
    counts = {}
    rows = []
    for j in jobs:
        r = results.get(j["key"], {"status": None})
        verdict, diff = _compare(r, j["record"])
        counts[verdict] = counts.get(verdict, 0) + 1
        rows.append(dict(key=j["key"], run_id=j["run_id"], round=j.get("round"), verdict=verdict,
                         max_abs_diff=diff, **{k: r.get(k) for k in SCORE_KEYS},
                         **{"record_" + k: j["record"].get(k) for k in SCORE_KEYS}))
        if a.split == "final" or verdict != "match":
            print(_result_row(j["label"], r, j["record"]))
    summary = dict(split=a.split, n=len(jobs), counts=counts, wall_seconds_this_invocation=round(wall, 1),
                   graded_this_invocation=len(todo), jobs=a.jobs, rows=rows)
    if a.split == "checkpoints":
        sel = _best_reselection(jobs, results, DS.read_table(root, "runs.csv"))
        summary["best_reselection"] = sel
        print("\nbest checkpoint re-selected from the regraded composites:")
        for s in sel:
            if s.get("best_round"):
                print("  %-44s %s %.4f  record %s  %s" % (s["run_id"], s["best_round"], s["best_composite"],
                                                        s["record_best_round"], "agrees" if s["agrees"] else "DIFFERS"))
            else:
                print("  %-44s record %s  (%s)" % (s["run_id"], s["record_best_round"], s["note"]))
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    n_ok = counts.get("match", 0) + counts.get("within tolerance", 0)
    print("\n%d of %d agree with the released records at 4 decimals or within %.0e (%s). Wall time of this invocation %.0f s. Results in %s" % (
        n_ok, len(jobs), GRADE_TOL, ", ".join("%s %d" % kv for kv in sorted(counts.items())), wall, out_dir))
    return 0 if n_ok == len(jobs) else 1


def cmd_grade_sample(a):
    from .grader import obs as O
    from .grader import sandbox
    from .grader.score import grade as grade_fn, LocalModel
    root = _data_root(a)
    sub = Path(a.model_dir).resolve()
    if a.offset is not None:
        s = a.offset
    elif (sub / "meta.json").exists() and "calendar_offset" in json.loads((sub / "meta.json").read_text()):
        s = float(json.loads((sub / "meta.json").read_text())["calendar_offset"])
    else:
        s = 0.0
        print("note: no calendar offset given and no meta.json, using offset 0", file=sys.stderr)
    _check_offset(s)
    if a.in_process:
        print("warning: --in-process runs model.py in this Python process without a sandbox", file=sys.stderr)
        from .grader.worker import load_submission
        cwd = os.getcwd()
        model = load_submission(str(sub))
        os.chdir(cwd)
        r = grade_fn(LocalModel(model), O.load(root / "grader_obs"), s=s,
                     log=lambda m: print("  " + m, file=sys.stderr))
        from .grader.scorer import _clean
        r = _clean(r)
    else:
        sandbox.ensure_image(a.image)
        r = sandbox.run(sub, root / "grader_obs", s=s, image=a.image,
                        timeout_s=a.timeout, fallback_scales=root / "task" / "nondim_scales.json")
    summary = {k: r.get(k) for k in ("status", "calendar_offset", "hard_gate", "statistics",
                                     "groups", "physics", "predictivity", "composite", "error")}
    print(json.dumps({k: v for k, v in summary.items() if v is not None}, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=1))
    return 0 if r.get("status") == "scored" else 1


def cmd_grade_run(a):
    """Grade every checkpoint of a run written by ``sciexam run-agent`` and report the final and
    best checkpoints the way the paper does."""
    from .grader import sandbox
    root = _data_root(a)
    run_dir = Path(a.run_dir).resolve()
    snaps = next((d for d in (run_dir / "results" / "snapshots", run_dir / "snapshots") if d.is_dir()), run_dir)
    rounds = sorted((d for d in snaps.glob("round_*") if (d / "model.py").exists()),
                    key=lambda d: int(d.name.split("_")[-1]))
    if not rounds:
        raise SystemExit("error: no checkpoints (round_NN folders with model.py) in %s" % snaps)
    s = float(a.offset)
    _check_offset(s)
    out_dir = Path(a.out or snaps.parent / "grades")
    out_dir.mkdir(parents=True, exist_ok=True)
    results, todo = {}, []
    for d in rounds:
        f = out_dir / (d.name + ".json")
        if f.exists():
            try:
                r = json.loads(f.read_text())
            except ValueError:
                r = {}
            if r.get("status") not in RETRY_STATUSES and r.get("calendar_offset") == s:
                results[d.name] = r
                continue
        todo.append(d)
    sandbox.ensure_image(a.image)
    print("grading %d checkpoints of %s at calendar offset %+.0f (%d already in %s), %d in parallel" % (
        len(todo), run_dir.name, s, len(results), out_dir, a.jobs), flush=True)
    t0 = time.time()

    def one(d):
        return sandbox.run(d, root / "grader_obs", s=s, image=a.image, timeout_s=a.timeout,
                           fallback_scales=root / "task" / "nondim_scales.json")

    def on_done(d, r):
        (out_dir / (d.name + ".json")).write_text(json.dumps(r, indent=1))
        results[d.name] = r
        print("  %-10s %-8s %6.0f s  composite %s" % (
            d.name, r.get("status"), r.get("wall_seconds", 0),
            "%.4f" % r["composite"] if r.get("composite") is not None else "-"), flush=True)

    _pool(todo, a.jobs, 0, lambda d: False, one, on_done)
    rows = []
    print("\n%-10s %8s %8s %8s %8s" % ("checkpoint", "stat", "phys", "pred", "composite"))
    for d in rounds:
        r = results.get(d.name, {})
        if r.get("status") == "scored":
            print("%-10s %s" % (d.name, " ".join("%8.4f" % r[k] for k in SCORE_KEYS)))
        else:
            print("%-10s FAILED: %s %s" % (d.name, r.get("status"), str(r.get("error", r.get("hard_gate", "")))[:120]))
        rows.append(dict(round=d.name, status=r.get("status"), **{k: r.get(k) for k in SCORE_KEYS}))
    final = rows[-1]
    scored = [x for x in rows if x["status"] == "scored"]
    # the earliest checkpoint wins a tie, as in the paper (consecutive snapshots can be identical)
    best = max(scored, key=lambda x: (x["composite"], -int(x["round"].split("_")[-1]))) if scored else None
    board = sorted([(r["final_composite"], r["display_name"]) for r in DS.read_table(root, "runs.csv")
                    if r["group"] in ("main", "reference")], reverse=True)
    summary = dict(run_dir=str(run_dir), calendar_offset=s, n_checkpoints=len(rows), final=final, best=best,
                   rows=rows, wall_seconds_this_invocation=round(time.time() - t0, 1))
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    print()
    if final["status"] == "scored":
        rank = 1 + sum(c > final["composite"] for c, _ in board)
        print("final checkpoint %s: composite %.4f (statistics %.4f, physics %.4f, predictivity %.4f), "
              "rank %d of %d next to the released final models and the reference model" % (
                  final["round"], final["composite"], final["statistics"], final["physics"],
                  final["predictivity"], rank, len(board) + 1))
    else:
        print("final checkpoint %s did not score (%s): the run scores 0 under the hard gate" % (final["round"], final["status"]))
    if best:
        print("best checkpoint %s: composite %.4f" % (best["round"], best["composite"]))
    print("results in %s" % out_dir)
    return 0 if final["status"] == "scored" else 1


COMMAND_PACKAGES = ("ablation", "figures", "prepare", "agent", "submission")


def main(argv=None):
    from .grader.sandbox import IMAGE
    ap = argparse.ArgumentParser(prog="sciexam", description="SciExam-ENSO benchmark tools")
    ap.add_argument("--data-dir", default=None, help="dataset directory (default: $SCIEXAM_DATA or ~/.cache/sciexam/dataset)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("download", help="fetch the dataset and verify every sha256")
    p.add_argument("--local", help="copy from this local dataset directory")
    p.add_argument("--revision", help="remote revision (default: the pinned one)")
    p.set_defaults(fn=cmd_download)

    p = sub.add_parser("grade", help="regrade a split of the released models in the Docker sandbox")
    p.add_argument("--split", default="final", choices=("final", "checkpoints"),
                   help="final: the final model of each ranked run and the reference model. "
                        "checkpoints: every released checkpoint (resumable, see --out)")
    p.add_argument("--jobs", type=int, default=4, help="submissions graded in parallel (each uses 4 CPUs)")
    p.add_argument("--slow-max", type=int, default=2, help="at most this many slow submissions at once ($SCIEXAM_SLOW, default gpt6astra)")
    p.add_argument("--arm", help="comma-separated arm keys (e.g. gpt55,kimi)")
    p.add_argument("--only", help=argparse.SUPPRESS)
    p.add_argument("--timeout", type=int, default=3600)
    p.add_argument("--image", default=IMAGE)
    p.add_argument("--out", help="result folder (default sciexam_results/<split>). Results already there are reused, so "
                                 "an interrupted run continues where it stopped")
    p.set_defaults(fn=cmd_grade)

    p = sub.add_parser("grade-sample", help="grade one submission directory (model.py + params.json)")
    p.add_argument("model_dir")
    p.add_argument("--offset", type=float, help="calendar offset s (the model's step receives t + s), a whole number of months")
    p.add_argument("--in-process", action="store_true", help="no Docker (runs untrusted code in this process)")
    p.add_argument("--timeout", type=int, default=3600)
    p.add_argument("--image", default=IMAGE)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_grade_sample)

    p = sub.add_parser("grade-run", help="grade every checkpoint of a run from run-agent and report its final and best scores")
    p.add_argument("run_dir", help="the run folder written by run-agent (or any folder holding snapshots/round_NN)")
    p.add_argument("--offset", type=float, default=0.0,
                   help="calendar offset s in months: the model's step receives t + s. Use the agent's stated "
                        "convention: 0 if its model reads month c at t = c (1 = January), -1 if t = 0 is January")
    p.add_argument("--jobs", type=int, default=4, help="checkpoints graded in parallel (two containers each)")
    p.add_argument("--out", help="output folder (default: grades/ next to the snapshots)")
    p.add_argument("--image", default=IMAGE)
    p.add_argument("--timeout", type=int, default=3600, help="per-checkpoint limit in seconds")
    p.set_defaults(fn=cmd_grade_run)

    p = sub.add_parser("build-image", help="build the grading image from environment/Dockerfile")
    p.add_argument("--image", default=IMAGE)
    p.set_defaults(fn=cmd_build_image)

    # commands that live in their own subpackages: each has commands.register(subparsers)
    import importlib
    for name in COMMAND_PACKAGES:
        try:
            mod = importlib.import_module("sciexam.%s.commands" % name)
        except ModuleNotFoundError as e:
            if e.name != "sciexam.%s" % name and e.name != "sciexam.%s.commands" % name:
                raise
            continue
        mod.register(sub)

    a = ap.parse_args(argv)
    try:
        return a.fn(a) or 0
    except RuntimeError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
