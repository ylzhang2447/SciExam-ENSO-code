"""`sciexam package-run`: turn a run folder of `sciexam run-agent` into a leaderboard submission.

A submission folder holds

    metadata.json       who submits, the system, the calendar offset, how many runs were made
    agent.yaml          the arm configuration the run used
    final/              the final checkpoint (the one the leaderboard ranks)
    checkpoints/        every checkpoint, round_NN/
    logs/               run_meta.json, summary.json, trajectory.jsonl, diagnostics_audit.json,
                        agent_output.txt and proxy/egress.jsonl from the run's results folder
    MANIFEST.sha256     sha256 of every other file

Only these files are copied. The agent workspace is never copied: it holds the user's sign-in
files (for example the Codex auth.json). Every copied text file is scanned for the user's
credential values and for common secret patterns, and packaging stops if one is found.
"""
import datetime
import hashlib
import json
import re
import shutil
from pathlib import Path

import sciexam

from ..agent import config as C

FORMAT = 1
MODEL_FILES = ("model.py", "params.json", "model_card.md", "nondim_scales.json")
LOG_FILES = ("run_meta.json", "summary.json", "trajectory.jsonl", "diagnostics_audit.json",
             "agent_output.txt", "proxy/egress.jsonl")
REQUIRED_LOGS = ("run_meta.json", "summary.json", "trajectory.jsonl")
AGENTS_DIR = Path(__file__).resolve().parents[2] / "agents"
SECRET_PATTERNS = [
    re.compile(r"sk-(or-v1-|ant-)?[A-Za-z0-9_-]{20,}"),       # OpenRouter, Anthropic, OpenAI keys
    re.compile(r"\b(gh[opsu]_[A-Za-z0-9]{30,})"),              # GitHub tokens
    re.compile(r'"(refresh_token|access_token|id_token)"\s*:\s*"[^"]{20,}"'),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
CREDENTIAL_NAMES = ("OPENROUTER_API_KEY", "LITELLM_MASTER_KEY", "CLAUDE_CODE_OAUTH_TOKEN")


class PackageError(RuntimeError):
    pass


def _results(run_dir):
    run_dir = Path(run_dir)
    for d in (run_dir / "results", run_dir):
        if (d / "snapshots").is_dir():
            return d
    raise PackageError("%s has no results/snapshots folder (is it a run folder of sciexam run-agent?)"
                       % run_dir)


def _rounds(snapshots):
    out = []
    for d in snapshots.iterdir():
        m = re.fullmatch(r"round_(\d+)", d.name)
        if m and d.is_dir() and (d / "model.py").exists():
            out.append((int(m.group(1)), d))
    return [d for _, d in sorted(out)]


def _secret_values(env_file):
    vals = []
    file_vals = C.read_env_file(env_file) if env_file else {}
    for name in CREDENTIAL_NAMES:
        v = C.credential(name, file_vals)
        if v and len(v) >= 8:
            vals.append(v)
    return vals


def scan(path, values):
    """Names of the secret checks a file fails (never the secret itself)."""
    try:
        text = Path(path).read_text(errors="ignore")
    except OSError:
        return []
    hits = ["a credential value from your environment or env file" for v in values if v in text]
    hits += ["a pattern like %s" % p.pattern[:24] for p in SECRET_PATTERNS if p.search(text)]
    return hits


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(out):
    out = Path(out)
    rows = []
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "MANIFEST.sha256":
            rows.append("%s  %s" % (sha256(p), p.relative_to(out).as_posix()))
    (out / "MANIFEST.sha256").write_text("\n".join(rows) + "\n")
    return len(rows)


def package(run_dir, out, system_name, contact, offset, runs_attempted, agent_config=None,
            env_file=".env", notes=""):
    """Write the submission folder ``out`` and return its metadata."""
    res = _results(run_dir)
    out = Path(out)
    if out.exists():
        raise PackageError("%s exists, choose a new --out" % out)
    for f in REQUIRED_LOGS:
        if not (res / f).exists():
            raise PackageError("%s is missing from %s: package a finished run of sciexam run-agent"
                               % (f, res))
    if float(offset) != int(float(offset)):
        raise PackageError("the calendar offset must be a whole number of months")
    if int(runs_attempted) < 1:
        raise PackageError("--runs-attempted is the number of runs you made with this system, at least 1")
    rounds = _rounds(res / "snapshots")
    if not rounds:
        raise PackageError("no checkpoints in %s" % (res / "snapshots"))
    meta = json.loads((res / "run_meta.json").read_text())
    summary = json.loads((res / "summary.json").read_text())
    cfg = Path(agent_config) if agent_config else AGENTS_DIR / ("%s.yaml" % meta["arm"])
    if not cfg.exists():
        raise PackageError("no arm configuration %s: pass --agent with the yaml the run used" % cfg)

    out.mkdir(parents=True)
    try:
        for d in rounds:
            for dest in ([out / "checkpoints" / d.name] + ([out / "final"] if d == rounds[-1] else [])):
                dest.mkdir(parents=True, exist_ok=True)
                for f in MODEL_FILES:
                    if (d / f).exists():
                        shutil.copyfile(d / f, dest / f)
        for f in LOG_FILES:
            if (res / f).exists():
                (out / "logs" / f).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(res / f, out / "logs" / f)
        shutil.copyfile(cfg, out / "agent.yaml")

        values = _secret_values(env_file)
        leaks = {}
        for p in out.rglob("*"):
            if p.is_file():
                hits = scan(p, values)
                if hits:
                    leaks[p.relative_to(out).as_posix()] = hits
        if leaks:
            raise PackageError("possible secrets found, nothing was packaged:\n" + "\n".join(
                "  %s: %s" % (k, "; ".join(v)) for k, v in sorted(leaks.items())))

        clock = summary.get("clock") or {}
        md = {
            "format": FORMAT,
            "system_name": system_name,
            "contact": contact,
            "notes": notes,
            "arm": meta.get("arm"),
            "model_id": (meta.get("route") or {}).get("model_id"),
            "scaffold": "%s %s" % ((meta.get("scaffold") or {}).get("name"),
                                   (meta.get("scaffold") or {}).get("version")),
            "route": (meta.get("route") or {}).get("kind"),
            "reasoning_effort": (meta.get("reasoning") or {}).get("effort"),
            "comparable_with_paper": _comparable(meta, C.load_arm(cfg)),
            "custom": meta.get("custom"),
            "budget_s": meta.get("budget_s"),
            "smoke": meta.get("smoke"),
            "calendar_offset": float(offset),
            "runs_attempted": int(runs_attempted),
            "n_checkpoints": len(rounds),
            "final_round": rounds[-1].name,
            "run_status": summary.get("status"),
            "eligible_elapsed_s": clock.get("eligible_elapsed_s"),
            "sciexam_version": sciexam.__version__,
            "packaged_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        (out / "metadata.json").write_text(json.dumps(md, indent=1) + "\n")
        md["files"] = write_manifest(out)
        return md
    except BaseException:
        shutil.rmtree(out, ignore_errors=True)
        raise


def _comparable(meta, arm):
    if meta.get("budget_s") != float(arm["budget"]["eligible_seconds"]):
        return False
    r = meta.get("reasoning") or {}
    if r.get("comparable_with_paper") is False:
        return False
    if (meta.get("custom") or {}).get("comparable_with_paper") is False:
        return False
    if meta.get("smoke"):
        return False
    return True
