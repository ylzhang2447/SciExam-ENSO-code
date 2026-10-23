"""What a run carries for its submission, decided when it starts rather than asked afterwards.

    system name     the arm's display name, with the changed settings named after it
    contact         asked once, kept in the profile and written into every later run
    runs attempted  every full run is entered in a ledger when it starts, so the number of runs
                    made with the same system (arm, model, effort, budget, custom settings) is
                    counted, not remembered

The ledger and the profile live next to the dataset cache (~/.cache/sciexam), or where
SCIEXAM_LEDGER and SCIEXAM_PROFILE point.
"""
import json
import os
import time
from pathlib import Path


def _home():
    from .. import home
    return home.state()


def ledger_path():
    return Path(os.environ.get("SCIEXAM_LEDGER") or _home() / "runs.jsonl")


def profile_path():
    return Path(os.environ.get("SCIEXAM_PROFILE") or _home() / "profile.json")


def load_profile():
    try:
        d = json.loads(profile_path().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_contact(contact):
    if not contact:
        return
    p = profile_path()
    d = load_profile()
    if d.get("contact") == contact:
        return
    d["contact"] = contact
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, indent=1) + "\n")
    except OSError:
        pass


def signature(arm, budget_s):
    """What makes two runs the same system."""
    return {"arm": arm["arm"], "model_id": arm["route"]["model_id"],
            "effort": arm["reasoning"]["effort"], "budget_s": float(budget_s),
            "context": arm["context"]["working_context_tokens"],
            "custom": {k: v for k, v in (arm.get("custom") or {}).items() if k != "comparable_with_paper"}}


def system_name(arm, budget_s):
    """The leaderboard name: the display name, and what differs from the paper's run."""
    name = arm.get("display_name") or arm["arm"]
    notes = []
    r = arm["reasoning"]
    if r.get("comparable_with_paper") is False:
        notes.append("effort %s" % r["effort"])
    if float(budget_s) != float(arm["budget"]["eligible_seconds"]):
        notes.append("%g h" % (float(budget_s) / 3600.0))
    ctx = (arm.get("declared") or {}).get("context_tokens")
    if ctx:
        notes.append("%dk context" % (ctx // 1000))
    c = arm.get("custom") or {}
    if c.get("network"):
        notes.append("no PyPI")
    if c.get("extra_allowed_hosts"):
        notes.append("extra hosts")
    return name + (" (%s)" % ", ".join(notes) if notes else "")


def record_start(arm, budget_s, run_key, workdir):
    """Enter a full run in the ledger and return how many runs of this system it now holds."""
    sig = signature(arm, budget_s)
    entry = {"run_key": run_key, "workdir": str(workdir), "started_epoch": int(time.time()),
             "signature": sig}
    p = ledger_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError:
        return None
    return count(sig)


def count(sig):
    n = 0
    try:
        lines = ledger_path().read_text().splitlines()
    except OSError:
        return 0
    for line in lines:
        try:
            if json.loads(line).get("signature") == sig:
                n += 1
        except ValueError:
            continue
    return n
