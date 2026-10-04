"""``sciexam ablation``: regrade the released simplified models and check them and the vote.

Every simplified model in ``ablation/`` is graded in the sandbox under its agent's calendar
offset and compared with its record in ``ablation/candidates.csv`` within an absolute tolerance
of 5e-4 on each score (a competing reduction, which has no row there, is compared through its
relative change in ``scores/structural_vote.csv`` within 0.2 percentage points). The screen and the
vote (see ``rules.py``) are then applied to the regraded simplified models against the recorded
originals, and every cell and the tally are compared with ``scores/structural_vote.csv``. With
``--regrade-originals`` the final models are regraded and compared with the recorded originals as
well. Each result is printed as match (equal at 4 decimals), within tolerance or mismatch. The
regraded tables are written to the output folder only. The dataset is never modified.

``--refit ARM/CANDIDATE`` instead reruns the teacher simulation and the least-squares refit of one
simplified model from the original model (see ``refit/``) in a container without network, and
compares the refit parameters with the released ones.
"""
import csv
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .. import dataset as DS
from . import rules as R

SCORE_KEYS = ("statistics", "physics", "predictivity", "composite")
CAND_COLS = ["arm", "display_name", "candidate", "role", "family", "calendar_offset",
             "original_statistics", "original_physics", "original_predictivity", "original_composite",
             "statistics", "physics", "predictivity", "composite", "relative_change_percent", "model_dir"]
VOTE_COLS = ["arm", "display_name", "vote", "lm_candidate", "lm_qualifies", "lm_relative_change_percent",
             "na_candidate", "na_qualifies", "na_relative_change_percent"]
ROLE_ORDER = {"vote representative": 0, "also qualifies": 1, "automatic endpoint": 2, "competing reduction": 3}


def register(sub):
    from ..grader.sandbox import IMAGE
    p = sub.add_parser("ablation", help="rescore the simplified models of the ablation and rebuild the structural vote")
    p.add_argument("--jobs", type=int, default=2, help="submissions graded in parallel (each uses 4 CPUs)")
    p.add_argument("--slow-max", type=int, default=2, help="at most this many slow submissions at once")
    p.add_argument("--regrade-originals", action="store_true",
                   help="also regrade the twelve final models instead of reading their scores from runs.csv")
    p.add_argument("--arm", help="grade only these arms (comma-separated) and stop before the tables")
    p.add_argument("--refit", metavar="ARM/CANDIDATE",
                   help="rerun the teacher simulation and refit of one simplified model and compare its parameters")
    p.add_argument("--refit-rtol", type=float, default=1e-6, help="relative tolerance of the refit comparison")
    p.add_argument("--timeout", type=int, default=3600)
    p.add_argument("--image", default=IMAGE)
    p.add_argument("--out", help="result folder (default sciexam_results/ablation). Results already there are reused")
    p.set_defaults(fn=run)


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return repr(v) if isinstance(v, float) else str(v)


def _write_csv(path, rows, cols):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: _fmt(r.get(c)) for c in cols})


def _candidates(root):
    out = []
    for meta in sorted((root / "ablation").glob("*/*/meta.json")):
        m = json.loads(meta.read_text())
        m["dir"] = meta.parent
        m["model_dir"] = meta.parent.relative_to(root).as_posix()
        out.append(m)
    return out


def _finals(root):
    runs = [r for r in DS.read_table(root, "runs.csv") if r["group"] == "main"]
    return {r["arm"]: r for r in runs}


def _grade_all(root, a, jobs, out_dir):
    from ..cli import RETRY_STATUSES, _pool
    from ..grader import sandbox
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
    if todo:
        sandbox.ensure_image(a.image)
    print("grading %d submissions (%d already in %s), %d in parallel" % (len(todo), len(results), out_dir, a.jobs), flush=True)
    t0 = time.time()
    slow = set(x for x in os.environ.get("SCIEXAM_SLOW", "gpt6astra").split(",") if x)

    def one(j):
        return sandbox.run(j["dir"], root / "grader_obs", s=j["s"], image=a.image, timeout_s=a.timeout,
                           fallback_scales=j["scales"])

    def done(j, r):
        (out_dir / (j["key"] + ".json")).write_text(json.dumps(r, indent=1))
        results[j["key"]] = r
        print("  %-48s %-8s %6.0f s  composite %s" % (
            j["key"], r.get("status"), r.get("wall_seconds", 0),
            "%.4f" % r["composite"] if r.get("composite") is not None else "-"), flush=True)

    _pool(todo, a.jobs, a.slow_max, lambda j: j["arm"] in slow, one, done)
    return results, time.time() - t0


ABL_TOL = 5e-4          # absolute, scores of simplified models and their originals
PCT_TOL = 0.2           # percentage points, relative changes in the vote table


def _status(pairs, tol):
    """'match' (equal at 4 decimals), 'within tolerance' (max |diff| <= tol) or 'MISMATCH'."""
    pairs = [(g, w) for g, w in pairs if w is not None]
    if not pairs:
        return "no record", None
    diff = max(abs(g - w) for g, w in pairs)
    if all(round(g, 4) == round(w, 4) for g, w in pairs):
        return "match", diff
    return ("within tolerance" if diff <= tol else "MISMATCH"), diff


def run(a):
    root = DS.open_verified(a.data_dir)
    if a.refit:
        return run_refit(root, a)
    out_dir = Path(a.out or "sciexam_results/ablation")
    out_dir.mkdir(parents=True, exist_ok=True)
    finals = _finals(root)
    cands = _candidates(root)
    task_scales = root / "task" / "nondim_scales.json"
    rec_rows = {(r["arm"], r["candidate"]): r for r in DS.read_table(root, "ablation/candidates.csv")}
    rec_vote = {r["arm"]: r for r in DS.read_table(root, "scores/structural_vote.csv")}
    rec_orig = {}
    for r in rec_rows.values():
        rec_orig.setdefault(r["arm"], {k: r["original_" + k] for k in SCORE_KEYS})

    def scales_for(arm):
        fin = root / finals[arm]["model_dir"] / "nondim_scales.json"
        return fin if fin.exists() else task_scales

    jobs = [dict(key="%s__%s" % (c["arm"], c["candidate"]), arm=c["arm"], dir=c["dir"],
                 s=float(c["calendar_offset"]), scales=scales_for(c["arm"])) for c in cands]
    if a.regrade_originals:
        arms = sorted({c["arm"] for c in cands})
        jobs += [dict(key="%s__original" % arm, arm=arm, dir=root / finals[arm]["model_dir"],
                      s=float(finals[arm]["calendar_offset"]), scales=task_scales) for arm in arms]
    if a.arm:
        keep = set(a.arm.split(","))
        jobs = [j for j in jobs if j["arm"] in keep]
    results, wall = _grade_all(root, a, jobs, out_dir)
    if a.arm:
        return 0 if all(results[j["key"]].get("status") == "scored" for j in jobs) else 1
    failed = [k for k, r in results.items() if r.get("status") != "scored"]
    if failed:
        print("not scored: %s" % ", ".join(failed))
        return 1

    # every comparison is against the released records: the recorded original of each agent
    # (ablation/candidates.csv) and the recorded simplified models
    arm_order = [r["arm"] for r in DS.read_table(root, "runs.csv") if r["group"] == "main"]
    rows, verdicts = [], []
    print("\nsimplified models (tolerance %.0e absolute on each score):" % ABL_TOL)
    print("%-20s %-30s %9s %9s %9s  %s" % ("agent", "simplified model", "regraded", "record", "max|diff|", "status"))
    for c in sorted(cands, key=lambda c: (arm_order.index(c["arm"]), ROLE_ORDER.get(c["role"], 9), c["candidate"])):
        r = results["%s__%s" % (c["arm"], c["candidate"])]
        sc = {k: r[k] for k in SCORE_KEYS}
        o = rec_orig[c["arm"]]
        rec = rec_rows.get((c["arm"], c["candidate"]))
        row = dict(arm=c["arm"], display_name=c["display_name"], candidate=c["candidate"], role=c["role"],
                   family=c["family"], calendar_offset=float(c["calendar_offset"]),
                   **{"original_" + k: o[k] for k in SCORE_KEYS}, **sc,
                   relative_change_percent=R.relative_change_percent(sc, o), model_dir=c["model_dir"])
        rows.append(row)
        if rec is not None:
            st, d = _status([(sc[k], rec[k]) for k in SCORE_KEYS], ABL_TOL)
            recv = "%.4f" % rec["composite"]
        else:            # a competing reduction: its record is the relative change in the vote table
            v = rec_vote.get(c["arm"], {})
            want = v.get(R.SHORT[c["family"]] + "_relative_change_percent")
            st, d = _status([(row["relative_change_percent"], want)], PCT_TOL)
            recv = "%+.2f%%" % want if want is not None else "-"
        verdicts.append(st)
        print("%-20s %-30s %9.4f %9s %9s  %s" % (c["display_name"], c["candidate"], sc["composite"], recv,
                                               "%.1e" % d if d is not None else "-", st))
    if a.regrade_originals:
        print("\noriginal models against the recorded originals:")
        for arm in sorted(rec_orig, key=arm_order.index):
            r = results["%s__original" % arm]
            st, d = _status([(r[k], rec_orig[arm][k]) for k in SCORE_KEYS], ABL_TOL)
            verdicts.append(st)
            print("  %-20s %9.4f %9.4f %9.1e  %s" % (finals[arm]["display_name"], r["composite"],
                                                     rec_orig[arm]["composite"], d, st))

    # the vote, rebuilt from the regraded simplified models and the recorded originals
    vote_arms = [arm for arm in arm_order if arm in rec_vote]
    vote = [R.vote_row(arm, finals[arm]["display_name"], rec_orig[arm], [r for r in rows if r["arm"] == arm])
            for arm in vote_arms]
    tally = R.tally(vote)
    print("\nstructural vote (screen %d%% composite, %d%% each component, relative changes within %.1f points):" % (
        round(100 * R.SCREEN_COMPOSITE), round(100 * R.SCREEN_COMPONENT), PCT_TOL))
    for v in vote:
        w = rec_vote[v["arm"]]
        same = all((v[k] or None) == (w[k] or None) or (v[k] is False and w[k] is False)
                   for k in ("vote", "lm_candidate", "lm_qualifies", "na_candidate", "na_qualifies"))
        pct = [(v[k], w[k]) for k in ("lm_relative_change_percent", "na_relative_change_percent")
               if v[k] is not None and w[k] is not None]
        st, _ = _status(pct, PCT_TOL) if pct else ("match", None)
        st = st if same else "MISMATCH"
        verdicts.append(st)
        print("  %-20s %-22s record %-22s %s" % (v["display_name"], v["vote"], w["vote"], st))
    rec_tally = R.tally(list(rec_vote.values()))
    print("  tally: %s  (record: %s)" % (", ".join("%s %d" % kv for kv in tally.items()),
                                         ", ".join("%s %d" % kv for kv in rec_tally.items())))
    verdicts.append("match" if tally == rec_tally else "MISMATCH")

    _write_csv(out_dir / "regraded_candidates.csv", rows, CAND_COLS)
    _write_csv(out_dir / "regraded_structural_vote.csv", vote, VOTE_COLS)
    counts = {k: verdicts.count(k) for k in sorted(set(verdicts))}
    json.dump(dict(tally=tally, record_tally=rec_tally, counts=counts, tolerance=ABL_TOL,
                   percent_tolerance=PCT_TOL, wall_seconds_this_invocation=round(wall, 1)),
              open(out_dir / "summary.json", "w"), indent=1)
    bad = counts.get("MISMATCH", 0)
    print("\n%d checks: %s. %s. Wall time of this invocation %.0f s. Regraded tables in %s (the dataset is not modified)" % (
        len(verdicts), ", ".join("%s %d" % kv for kv in counts.items()),
        "Every result agrees with the released records within the stated tolerance" if bad == 0
        else "%d results do not agree with the released records" % bad, wall, out_dir))
    return 0 if bad == 0 else 1


def run_refit(root, a):
    from ..grader import sandbox
    from .refit.registry import REFITS
    arm, _, cand = a.refit.partition("/")
    if (arm, cand) not in REFITS:
        raise SystemExit("no refit is registered for %s. Available: %s" % (
            a.refit, ", ".join("%s/%s" % k for k in REFITS)))
    finals = _finals(root)
    released = [c for c in _candidates(root) if c["arm"] == arm and c["candidate"] == cand][0]
    out_dir = Path(a.out or "sciexam_results/refit_%s_%s" % (arm, cand)).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(out_dir, 0o777)
    sandbox.ensure_image(a.image)
    tmp = Path(tempfile.mkdtemp(prefix="sciexam-refit-")).resolve()
    os.chmod(tmp, 0o755)
    name = sandbox.PREFIX + "refit-" + os.urandom(4).hex()
    t0 = time.time()
    try:
        sandbox.stage(root / finals[arm]["model_dir"], tmp / "orig")
        argv = sandbox._common(name, 4, "8g") + [
            "-v", "%s:/orig:ro" % (tmp / "orig"), "-v", "%s:/out" % out_dir, a.image,
            "python3", "-m", "sciexam.ablation.refit.run", "--original", "/orig", "--arm", arm,
            "--candidate", cand, "--out", "/out"]
        print("teacher simulation and refit of %s/%s in a container without network ..." % (arm, cand), flush=True)
        p = subprocess.run([x for x in argv if x != "-i"], timeout=a.timeout)
    finally:
        subprocess.run(sandbox.docker() + ["rm", "-f", name], capture_output=True)
        if (tmp / "orig").exists():
            os.chmod(tmp / "orig", 0o755)
        shutil.rmtree(tmp, ignore_errors=True)
    wall = time.time() - t0
    if p.returncode != 0 or not (out_dir / "params.json").exists():
        print("refit failed (exit %d)" % p.returncode)
        return 1
    new = json.loads((out_dir / "params.json").read_text())
    old = json.loads((released["dir"] / "params.json").read_text())
    fit = json.loads((out_dir / "fit.json").read_text())
    refit_keys = sorted({c["term"] for c in fit["coefficients"]} & set(old))
    worst_rel, worst_key, other_diff = 0.0, None, []
    for k in sorted(set(old) | set(new)):
        a_, b_ = new.get(k), old.get(k)
        if k in refit_keys:
            den = max(abs(b_), 1e-12)
            rel = abs(a_ - b_) / den if b_ != 0 else abs(a_)
            if rel > worst_rel:
                worst_rel, worst_key = rel, k
        elif a_ != b_:
            other_diff.append(k)
    ok = worst_rel <= a.refit_rtol and not other_diff and fit["stable_300yr"]
    print("refit of %s/%s: %d refit coefficients, largest relative difference from the released parameters %.2e (%s)" % (
        arm, cand, len(refit_keys), worst_rel, worst_key))
    print("parameters copied unchanged: %s" % ("all identical" if not other_diff else "DIFFER: " + ", ".join(other_diff)))
    print("teacher simulation %.0f s, fit %.0f s, total wall time %.0f s, 300-year run finite: %s" % (
        fit["seconds"]["simulation"], fit["seconds"]["fit"], wall, fit["stable_300yr"]))
    print("%s (relative tolerance %.0e). Refit parameters in %s" % (
        "reproduces the released parameters" if ok else "DOES NOT reproduce the released parameters", a.refit_rtol, out_dir))
    return 0 if ok else 1
