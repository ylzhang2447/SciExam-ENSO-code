"""`sciexam verify-submission`: check a submission folder against the benchmark's rules and regrade
its final model.

Each check ends as

    pass       as the protocol requires
    declared   differs from the paper's protocol, and the run itself recorded the difference
               (reasoning effort, run time, network). The run is valid but ranked apart.
    fail       the submission is inconsistent: a file changed after packaging, the prompts or the
               lifecycle differ from this harness, a difference the run did not record, an
               unfinished run, or a regrade that does not reproduce the claimed score.

and the verdict is ``consistent`` (every check passes), ``consistent, declared changes`` (some
checks declared, none failed) or ``inconsistent`` (any check failed).

What the verdict means. The run records are written on the submitter's own machine, so these checks
establish that a submission is internally consistent and that its final model reproduces its
score. They catch configuration mistakes, unfinished or smoke runs, undeclared changes and edits
made after packaging. They cannot prove that the records were not fabricated before packaging, so a
consistent submission is listed as self-reported. Only a run on infrastructure the maintainers
control can be listed as verified.

An arm the paper did not run (a new model) is compared with the released arm of the same scaffold
and route: only the model, its names and the scaffold version may differ.
"""
import json
from pathlib import Path

from ..agent import config as C
from ..agent import prompts as P
from ..agent import seal as SEAL
from . import package as PK

# The protocol of an arm: a new model may change its model, names and scaffold version, not these.
PROTOCOL_KEYS = ("scaffold.name", "route.kind", "budget.eligible_seconds", "lifecycle",
                 "tools.disallowed", "network.agent_allow_hosts", "context.working_context_tokens",
                 "resource_gate")
SCORE_TOL = 5e-5


def _get(d, dotted):
    cur = d
    for k in dotted.split("."):
        cur = cur.get(k) if isinstance(cur, dict) else None
    return cur


class Report:
    def __init__(self):
        self.checks = []

    def add(self, name, status, detail=""):
        self.checks.append({"check": name, "status": status, "detail": detail})

    @property
    def verdict(self):
        st = {c["status"] for c in self.checks}
        if "fail" in st:
            return "inconsistent"
        return "consistent, declared changes" if "declared" in st else "consistent"


def check_manifest(sub, rep):
    man = sub / "MANIFEST.sha256"
    if not man.exists():
        rep.add("manifest", "fail", "MANIFEST.sha256 is missing")
        return
    listed = {}
    for line in man.read_text().splitlines():
        if line.strip():
            h, name = line.split("  ", 1)
            listed[name] = h
    present = {p.relative_to(sub).as_posix() for p in sub.rglob("*")
               if p.is_file() and p.name != "MANIFEST.sha256"}
    bad = [n for n, h in listed.items() if n not in present or PK.sha256(sub / n) != h]
    extra = sorted(present - set(listed))
    if bad or extra:
        rep.add("manifest", "fail", "changed or missing: %s; not listed: %s"
                % (", ".join(sorted(bad)) or "none", ", ".join(extra) or "none"))
    else:
        rep.add("manifest", "pass", "%d files, every sha256 matches" % len(listed))


def released_template(arm):
    """The released arm this configuration must follow: the same key if the paper ran it, else
    the paper's latest run on its route (see agent/newmodel.py), which `add-model` copies."""
    from ..agent import newmodel as NM
    same = PK.AGENTS_DIR / ("%s.yaml" % arm["arm"])
    if same.exists():
        return C.load_arm(same)
    try:
        return C.load_arm(PK.AGENTS_DIR / ("%s.yaml" % NM.template_for(arm)))
    except (KeyError, OSError, C.ConfigError):
        return None


def check_config(sub, rep):
    try:
        arm = C.load_arm(sub / "agent.yaml")
    except Exception as e:
        rep.add("arm configuration", "fail", "agent.yaml does not load: %s" % e)
        return None
    if arm.get("condition"):
        rep.add("arm configuration", "fail", "condition runs are not leaderboard submissions")
        return arm
    t = released_template(arm)
    if t is None:
        rep.add("arm configuration", "fail", "no released arm with scaffold %s and route %s"
                % (arm["scaffold"]["name"], arm["route"]["kind"]))
        return arm
    diff = [k for k in PROTOCOL_KEYS if _get(arm, k) != _get(t, k)]
    if diff:
        rep.add("arm configuration", "fail", "differs from the released arm %s in %s"
                % (t["arm"], ", ".join(diff)))
    else:
        new = "" if t["arm"] == arm["arm"] else " (a new model on the protocol of %s)" % t["arm"]
        rep.add("arm configuration", "pass", "protocol of the released arm %s%s" % (t["arm"], new))
    return arm


def check_run(sub, arm, rep):
    logs = sub / "logs"
    try:
        meta = json.loads((logs / "run_meta.json").read_text())
        summary = json.loads((logs / "summary.json").read_text())
    except (OSError, ValueError) as e:
        rep.add("run records", "fail", "run_meta.json or summary.json unreadable: %s" % e)
        return
    if arm is None:
        return
    if meta.get("arm") != arm["arm"]:
        rep.add("run records", "fail", "run_meta names arm %r, agent.yaml %r" % (meta.get("arm"), arm["arm"]))

    want = P.prompt_digests()
    got = meta.get("prompt_sha256") or {}
    diff = sorted(k for k in want if got.get(k) != want[k])
    rep.add("prompts", "fail" if diff else "pass",
            "differ from this harness: %s" % ", ".join(diff) if diff else
            "every agent-facing text matches this harness (%d digests)" % len(want))

    sc, r = meta.get("scaffold") or {}, meta.get("route") or {}
    bad = [k for k, a, b in (("scaffold version", sc.get("version"), arm["scaffold"]["version"]),
                             ("scaffold sha256", sc.get("binary_sha256"), arm["scaffold"]["binary_sha256"]),
                             ("model id", r.get("model_id"), arm["route"]["model_id"])) if a != b]
    rep.add("scaffold and model", "fail" if bad else "pass",
            "run differs from agent.yaml in %s" % ", ".join(bad) if bad else
            "%s %s, %s" % (sc.get("name"), sc.get("version"), r.get("model_id")))

    if meta.get("smoke"):
        rep.add("lifecycle", "fail", "a smoke run is a plumbing check, not a submission")
    elif meta.get("lifecycle") != arm["lifecycle"]:
        keys = sorted(k for k in arm["lifecycle"] if (meta.get("lifecycle") or {}).get(k) != arm["lifecycle"][k])
        rep.add("lifecycle", "fail", "differs from the harness in %s" % ", ".join(keys))
    else:
        rep.add("lifecycle", "pass", "the formal lifecycle constants")

    budget = float(arm["budget"]["eligible_seconds"])
    b = meta.get("budget_s")
    if b == budget:
        rep.add("budget", "pass", "%.0f s of eligible time" % budget)
    elif b is not None:
        rep.add("budget", "declared", "%.0f s instead of %.0f s (--hours)" % (b, budget))
    else:
        rep.add("budget", "fail", "run_meta records no budget")

    paper = C.allowlist(arm)
    custom = meta.get("custom") or {}
    allow = meta.get("network_allowlist")
    if allow == paper:
        rep.add("network", "pass", "the paper's allowlist: %s" % ", ".join(paper))
    elif custom.get("network") or custom.get("extra_allowed_hosts"):
        rep.add("network", "declared", "custom: %s" % ", ".join(
            "%s %s" % (k, v) for k, v in custom.items() if k != "comparable_with_paper"))
    else:
        rep.add("network", "fail", "allowlist %s differs from the paper's %s and was not declared"
                % (allow, paper))

    re_ = meta.get("reasoning") or {}
    if re_.get("effort") == arm["reasoning"]["effort"] and re_.get("comparable_with_paper", True):
        rep.add("reasoning effort", "pass", re_.get("effort"))
    elif re_.get("comparable_with_paper") is False:
        rep.add("reasoning effort", "declared", "%s instead of %s"
                % (re_.get("effort"), re_.get("paper_effort")))
    else:
        rep.add("reasoning effort", "fail", "%s, but agent.yaml says %s and no change was recorded"
                % (re_.get("effort"), arm["reasoning"]["effort"]))

    clock = summary.get("clock") or {}
    el = clock.get("eligible_elapsed_s")
    if summary.get("status") != "complete":
        rep.add("run completion", "fail", "run status %r" % summary.get("status"))
    elif el is None or b is None or el < 0.999 * b:
        rep.add("run completion", "fail", "eligible time %s s is short of the budget %s s" % (el, b))
    else:
        rep.add("run completion", "pass", "complete after %.0f s of eligible time" % el)


def check_checkpoints(sub, rep):
    rounds = sorted(p.name for p in (sub / "checkpoints").glob("round_*") if p.is_dir())
    snaps = []
    traj = sub / "logs" / "trajectory.jsonl"
    for line in traj.read_text().splitlines() if traj.exists() else []:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("event") == "snapshot":
            snaps.append(ev)
    final_same = all(PK.sha256(sub / "final" / f) == PK.sha256(sub / "checkpoints" / rounds[-1] / f)
                     for f in ("model.py", "params.json")) if rounds and (sub / "final").is_dir() else False
    if not rounds:
        rep.add("checkpoints", "fail", "no checkpoints")
    elif len(snaps) != len(rounds):
        rep.add("checkpoints", "fail", "%d checkpoint folders, %d snapshot events in trajectory.jsonl"
                % (len(rounds), len(snaps)))
    elif not final_same:
        rep.add("checkpoints", "fail", "final/ is not the last checkpoint %s" % rounds[-1])
    else:
        rep.add("checkpoints", "pass", "%d checkpoints, final = %s" % (len(rounds), rounds[-1]))


def check_egress(sub, rep):
    log = sub / "logs" / "proxy" / "egress.jsonl"
    if not log.exists():
        rep.add("egress log", "fail", "logs/proxy/egress.jsonl is missing")
        return
    allowed, outside, denied, start = 0, [], 0, None
    for line in log.read_text().splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("event") == "start":
            start = sorted(ev.get("allowed") or [])
        elif ev.get("event") == "allow":
            allowed += 1
            host = str(ev.get("target", "")).rsplit(":", 1)[0]
            if start is not None and host not in start:
                outside.append(host)
        elif ev.get("event") == "deny":
            denied += 1
    if outside:
        rep.add("egress log", "fail", "connections outside the allowlist: %s" % ", ".join(sorted(set(outside))))
    else:
        rep.add("egress log", "pass", "%d connections through the allowlist, %d refused" % (allowed, denied))


def regrade(sub, md, data_root, rep, image=None, timeout=3600, in_process=False):
    """Regrade the final model. Without a stated calendar offset it is graded at 0 and -1, the two
    conventions the task leaves open, and the maintainers judge which the model uses."""
    stated = md.get("calendar_offset")
    if stated is None:
        out = {}
        for s in (0.0, -1.0):
            sc = _regrade_one(sub, md, data_root, rep, s, image, timeout, in_process)
            out["%+.0f" % s] = sc
        return out
    return _regrade_one(sub, md, data_root, rep, float(stated), image, timeout, in_process)


def _regrade_one(sub, md, data_root, rep, s, image, timeout, in_process):
    from ..grader import obs as O
    name = "regrade" if md.get("calendar_offset") is not None else "regrade, offset %+.0f" % s
    if in_process:
        import os
        from ..grader.score import LocalModel, grade as grade_fn
        from ..grader.scorer import _clean
        from ..grader.worker import load_submission
        cwd = os.getcwd()
        model = load_submission(str(sub / "final"))
        os.chdir(cwd)
        r = _clean(grade_fn(LocalModel(model), O.load(Path(data_root) / "grader_obs"), s=s))
    else:
        from ..grader import sandbox
        img = image or sandbox.IMAGE
        sandbox.ensure_image(img)
        r = sandbox.run(sub / "final", Path(data_root) / "grader_obs", s=s, image=img, timeout_s=timeout,
                        fallback_scales=Path(data_root) / "task" / "nondim_scales.json")
    scores = {k: r.get(k) for k in ("statistics", "physics", "predictivity", "composite")}
    if r.get("status") != "scored" or scores["composite"] is None:
        rep.add(name, "fail", "the final model did not score: %s" % (r.get("error") or r.get("status")))
        return scores
    claimed = md.get("claimed_scores") or {}
    off = {k: (claimed[k], scores[k]) for k in claimed if k in scores
           and abs(float(claimed[k]) - float(scores[k])) > SCORE_TOL}
    if off:
        rep.add(name, "fail", "claimed %s, regraded %s" % (
            {k: v[0] for k, v in off.items()}, {k: round(v[1], 4) for k, v in off.items()}))
    else:
        rep.add(name, "pass", "composite %.4f (statistics %.4f, physics %.4f, prediction %.4f) at "
                "calendar offset %+.0f" % (scores["composite"], scores["statistics"], scores["physics"],
                                          scores["predictivity"], s))
    return scores


def verify(sub, data_root, grade=True, image=None, timeout=3600, in_process=False):
    sub = Path(sub)
    rep = Report()
    check_manifest(sub, rep)
    try:
        md = json.loads((sub / "metadata.json").read_text())
    except (OSError, ValueError):
        md = {}
    missing = [k for k in ("format", "system_name", "contact", "runs_attempted") if not md.get(k)]
    rep.add("metadata", "fail" if missing or md.get("format") != PK.FORMAT else "pass",
            "missing %s" % ", ".join(missing) if missing else "%s, %d run(s) attempted"
            % (md.get("system_name"), md.get("runs_attempted", 0)))
    broken = SEAL.check_submission(sub)
    rep.add("seal", "fail" if broken else "pass", "; ".join(broken) if broken else
            "every checkpoint and log matches the seal written when the run ended")
    arm = check_config(sub, rep)
    check_run(sub, arm, rep)
    check_checkpoints(sub, rep)
    check_egress(sub, rep)
    scores = None
    if grade:
        scores = regrade(sub, md, data_root, rep, image=image, timeout=timeout, in_process=in_process)
    return {"submission": str(sub), "system_name": md.get("system_name"), "verdict": rep.verdict,
            "scores": scores, "checks": rep.checks}
