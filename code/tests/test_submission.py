"""`sciexam package-run` and `sciexam verify-submission` on simulated run folders.

The released dataset holds the checkpoints of the paper's runs, not their full run folders, so each
test builds a run folder the way `sciexam run-agent` writes one: the last three Kimi K3 checkpoints
as snapshots, and run_meta.json, summary.json, trajectory.jsonl, the egress log and the seal
written from the arm configuration. Needs the dataset (``sciexam download``).
"""
import json
import os
import shutil
from pathlib import Path

import pytest

from sciexam import dataset as DS
from sciexam.agent import config as C
from sciexam.agent import custom as X
from sciexam.agent import effort as E
from sciexam.agent import ledger as LG
from sciexam.agent import prompts as P
from sciexam.agent import resources as R
from sciexam.agent import task as T
from sciexam.agent import seal as SEAL
from sciexam.submission import package as PK
from sciexam.submission import verify as V

AGENTS = Path(__file__).resolve().parents[1] / "agents"


def _root():
    try:
        root = Path(os.environ.get("SCIEXAM_DATA") or DS.default_root())
    except Exception:
        return None
    return root if (root / "models" / "checkpoints" / "kimi-k3").is_dir() else None


pytestmark = pytest.mark.skipif(_root() is None, reason="dataset not downloaded")


FORMAL_HOST = {"cpus": 16, "memory_gb": 30.81, "docker": "29.7", "os": "Ubuntu", "arch": "x86_64"}


def task_rows(paper="formal", data="formal"):
    """run_meta task_files as run-agent records them, for the formal inputs or a variant."""
    from sciexam.agent.provenance import TASK_FILES_SHA256
    rows = []
    for rel, sha in TASK_FILES_SHA256.items():
        got = sha
        if rel.endswith(".pdf") and paper == "other":
            got = "1" * 64
        if rel.startswith("data/") and data == "rebuilt" and "ersst" in rel:
            got = "2" * 64
        rows.append({"path": rel, "sha256": got, "formal_sha256": sha, "same_as_formal": got == sha})
    return rows


def make_run(tmp, arm=None, budget=None, smoke=False, n=3, egress_extra=None, host=FORMAL_HOST,
             at_once=3, samples=None, disk=40.0, paper="formal", data="formal"):
    arm = arm or C.load_arm(AGENTS / "kimi.yaml")
    res = tmp / "run" / "results"
    ckpts = sorted((_root() / "models" / "checkpoints" / "kimi-k3").glob("round_*"))[-n:]
    for k, d in enumerate(ckpts, 1):
        dest = res / "snapshots" / ("round_%02d" % k)
        dest.mkdir(parents=True)
        for f in PK.MODEL_FILES:
            if (d / f).exists():
                shutil.copyfile(d / f, dest / f)
    b = budget or float(arm["budget"]["eligible_seconds"])
    meta = {"arm": arm["arm"], "scaffold": arm["scaffold"], "route": arm["route"],
            "reasoning": arm["reasoning"], "context": arm["context"], "lifecycle": arm["lifecycle"],
            "budget_s": b, "smoke": smoke, "network_allowlist": C.allowlist(arm),
            "prompt_sha256": P.prompt_digests(), "custom": arm.get("custom"),
            "submission": {"system_name": LG.system_name(arm, b), "contact": "tester@example.org",
                           "runs_attempted": 2},
            "resources": dict(R.record(host, at_once, tmp), disk_free_gb_at_start=disk),
            "task_files": task_rows(paper, data)}
    (res / "run_meta.json").write_text(json.dumps(meta))
    k = int(b // R.SAMPLE_S) if samples is None else samples
    rows = [{"t": t, "cpu": "%.1f%%" % (20 + t % 50), "memory_pct": "3.0%", "disk_free_gb": disk}
            for t in range(k)] + [{"t": k, "event": "end", "oom_kills": 0, "disk_free_gb": disk}]
    (res / R.SAMPLE_FILE).write_text("".join(json.dumps(r) + "\n" for r in rows))
    (res / "summary.json").write_text(json.dumps({"status": "complete",
                                                  "clock": {"eligible_elapsed_s": b + 0.2}}))
    chain, events = SEAL.GENESIS, []
    for k in range(1, n + 1):
        chain = SEAL.link(chain, "round_%02d" % k, SEAL.folder_digest(res / "snapshots" / ("round_%02d" % k)))
        events.append({"event": "snapshot", "round": k - 1, "chain": chain})
    (res / "trajectory.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    (res / "proxy").mkdir()
    allow = C.allowlist(arm)
    lines = ([{"event": "start", "allowed": allow}]
             + [{"event": "allow", "target": "%s:443" % h} for h in allow]
             + [{"event": "deny", "target": "example.com:443"}] + (egress_extra or []))
    (res / "proxy" / "egress.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    # the workspace holds sign-in files and must never be packaged
    (tmp / "run" / "workspace" / ".codex").mkdir(parents=True)
    (tmp / "run" / "workspace" / ".codex" / "auth.json").write_text('{"refresh_token": "%s"}' % ("r" * 40))
    SEAL.write(res, chain)                     # as run-agent does once the run has ended
    return tmp / "run"


def reseal(run):
    """Seal again, as a harness that had recorded the edited files itself would have."""
    res = run / "results"
    rounds = sorted((d for d in (res / "snapshots").glob("round_*")), key=lambda d: d.name)
    SEAL.write(res, SEAL.chain_of(rounds))


def pack(tmp, run, **kw):
    args = dict(system_name="Test system", contact="tester@example.org", offset=0, runs_attempted=1,
                env_file=None)
    args.update(kw)
    return PK.package(run, tmp / "sub", **args)


def statuses(rep):
    return {c["check"]: c["status"] for c in rep["checks"]}


def test_package_contents_and_no_workspace(tmp_path):
    md = pack(tmp_path, make_run(tmp_path))
    sub = tmp_path / "sub"
    assert md["final_round"] == "round_03" and md["n_checkpoints"] == 3
    assert md["comparable_with_paper"] is True
    assert (sub / "final" / "model.py").read_bytes() == (sub / "checkpoints" / "round_03" / "model.py").read_bytes()
    assert not list(sub.rglob("auth.json"))
    assert (sub / "MANIFEST.sha256").exists() and (sub / "agent.yaml").exists()


def test_paper_settings_are_consistent(tmp_path):
    pack(tmp_path, make_run(tmp_path))
    rep = V.verify(tmp_path / "sub", _root(), grade=False)
    assert rep["verdict"] == "consistent", rep["checks"]


def test_regrade_reproduces_the_released_score(tmp_path):
    pack(tmp_path, make_run(tmp_path))
    rep = V.verify(tmp_path / "sub", _root(), grade=True, in_process=True)
    assert statuses(rep)["regrade"] == "pass"
    assert abs(rep["scores"]["composite"] - 0.4792) < 5e-4      # Kimi K3, final model


def test_edited_file_fails_the_manifest(tmp_path):
    pack(tmp_path, make_run(tmp_path))
    p = tmp_path / "sub" / "final" / "params.json"
    p.write_text(p.read_text() + " ")
    rep = V.verify(tmp_path / "sub", _root(), grade=False)
    assert statuses(rep)["manifest"] == "fail" and rep["verdict"] == "inconsistent"


def test_declared_changes(tmp_path):
    arm = X.apply(E.apply(C.load_arm(AGENTS / "kimi.yaml"), "low"), "no-pypi")
    pack(tmp_path, make_run(tmp_path, arm=arm, budget=7200.0))
    rep = V.verify(tmp_path / "sub", _root(), grade=False)
    st = statuses(rep)
    assert st["budget"] == st["network"] == st["reasoning effort"] == "declared"
    assert rep["verdict"] == "consistent, declared changes", rep["checks"]
    assert json.loads((tmp_path / "sub" / "metadata.json").read_text())["comparable_with_paper"] is False


def test_changed_prompts_and_smoke_runs_are_inconsistent(tmp_path):
    run = make_run(tmp_path, smoke=True)
    meta = json.loads((run / "results" / "run_meta.json").read_text())
    meta["prompt_sha256"]["RESUME_PROMPT"] = "0" * 64
    (run / "results" / "run_meta.json").write_text(json.dumps(meta))
    reseal(run)
    pack(tmp_path, run)
    st = statuses(V.verify(tmp_path / "sub", _root(), grade=False))
    assert st["prompts"] == "fail" and st["lifecycle"] == "fail"


def test_connection_outside_the_allowlist_fails(tmp_path):
    pack(tmp_path, make_run(tmp_path, egress_extra=[{"event": "allow", "target": "evil.example.org:443"}]))
    assert statuses(V.verify(tmp_path / "sub", _root(), grade=False))["egress log"] == "fail"


def test_new_model_on_a_released_protocol(tmp_path):
    cfg = (AGENTS / "dsflash.yaml").read_text()          # the template add-model uses
    cfg = cfg.replace("arm: dsflash", "arm: newmodel").replace(
        "model_id: deepseek/deepseek-v4.1-flash", "model_id: example/new-model")
    (tmp_path / "newmodel.yaml").write_text(cfg)
    arm = C.load_arm(tmp_path / "newmodel.yaml")
    pack(tmp_path, make_run(tmp_path, arm=arm), agent_config=tmp_path / "newmodel.yaml")
    rep = V.verify(tmp_path / "sub", _root(), grade=False)
    assert rep["verdict"] == "consistent", rep["checks"]
    detail = [c for c in rep["checks"] if c["check"] == "arm configuration"][0]["detail"]
    assert "a new model on the protocol of" in detail
    # the same config with a shorter budget changes the protocol itself
    (tmp_path / "newmodel.yaml").write_text(cfg.replace("eligible_seconds: 21600", "eligible_seconds: 3600"))
    shutil.rmtree(tmp_path / "sub")
    pack(tmp_path, tmp_path / "run", agent_config=tmp_path / "newmodel.yaml")
    assert statuses(V.verify(tmp_path / "sub", _root(), grade=False))["arm configuration"] == "fail"


def test_secrets_stop_packaging(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-" + "a" * 40)
    with open(run / "results" / "trajectory.jsonl", "a") as f:
        f.write(json.dumps({"event": "debug", "env": "sk-or-v1-" + "a" * 40}) + "\n")
    reseal(run)
    with pytest.raises(PK.PackageError, match="possible secrets"):
        PK.package(run, tmp_path / "sub", "x", "y", 0, 1, env_file=".env")
    assert not (tmp_path / "sub").exists()


def test_the_run_carries_its_name_contact_and_count(tmp_path):
    md = PK.package(make_run(tmp_path), tmp_path / "sub", env_file=None)
    assert md["system_name"] == "Kimi K3" and md["contact"] == "tester@example.org"
    assert md["runs_attempted"] == 2 and md["calendar_offset"] is None


def test_a_folder_edited_after_its_run_is_refused(tmp_path):
    run = make_run(tmp_path)
    p = run / "results" / "snapshots" / "round_03" / "params.json"
    p.write_text(p.read_text() + " ")
    with pytest.raises(PK.PackageError, match="changed after its run"):
        pack(tmp_path, run)
    shutil.rmtree(tmp_path / "run")
    run = make_run(tmp_path)
    shutil.copytree(run / "results" / "snapshots" / "round_03", run / "results" / "snapshots" / "round_04")
    with pytest.raises(PK.PackageError, match="added after the run"):
        pack(tmp_path, run)


def test_rewriting_the_manifest_does_not_hide_an_edit(tmp_path):
    pack(tmp_path, make_run(tmp_path))
    p = tmp_path / "sub" / "final" / "params.json"
    for q in (p, tmp_path / "sub" / "checkpoints" / "round_03" / "params.json"):
        q.write_text(q.read_text() + " ")
    PK.write_manifest(tmp_path / "sub")
    st = statuses(V.verify(tmp_path / "sub", _root(), grade=False))
    assert st["manifest"] == "pass" and st["seal"] == "fail"


def test_without_an_offset_both_conventions_are_graded(tmp_path):
    PK.package(make_run(tmp_path), tmp_path / "sub", env_file=None)
    rep = V.verify(tmp_path / "sub", _root(), grade=True, in_process=True)
    st = statuses(rep)
    assert st["regrade, offset +0"] == st["regrade, offset -1"] == "pass"
    assert abs(rep["scores"]["+0"]["composite"] - 0.4792) < 5e-4


def test_ledger_counts_runs_of_the_same_system(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIEXAM_LEDGER", str(tmp_path / "runs.jsonl"))
    kimi = C.load_arm(AGENTS / "kimi.yaml")
    assert LG.record_start(kimi, 21600, "a", tmp_path) == 1
    assert LG.record_start(kimi, 21600, "b", tmp_path) == 2
    assert LG.record_start(E.apply(kimi, "low"), 21600, "c", tmp_path) == 1   # another system
    assert LG.record_start(kimi, 7200, "d", tmp_path) == 1
    assert LG.system_name(E.apply(kimi, "low"), 7200) == "Kimi K3 (effort low, 2 h)"


def test_a_declared_context_window_is_ranked_apart(tmp_path, monkeypatch):
    from sciexam.agent import newmodel as NM
    monkeypatch.setenv("SCIEXAM_AGENTS", str(tmp_path / "agents"))
    path = NM.make("local", "llama-4", api_base="http://localhost:8000/v1", context_tokens=32768)
    md = pack(tmp_path, make_run(tmp_path, arm=C.load_arm(path)), agent_config=path)
    assert md["comparable_with_paper"] is False
    rep = V.verify(tmp_path / "sub", _root(), grade=False)
    assert statuses(rep)["arm configuration"] == "declared"
    assert rep["verdict"] == "consistent, declared changes", rep["checks"]


def test_compute_is_checked_against_the_spec(tmp_path):
    from sciexam.submission import verify as V
    for name, kw, status in [
            ("ok", {}, "pass"),
            ("small", {"host": dict(FORMAL_HOST, cpus=8)}, "fail"),     # 8 CPUs cannot hold 3 agents
            ("alone", {"host": dict(FORMAL_HOST, cpus=8, memory_gb=15.6), "at_once": 1}, "pass")]:
        d = tmp_path / name
        d.mkdir()
        pack(d, make_run(d, **kw))
        rep = V.Report()
        V.check_resources(d / "sub", rep)
        assert statuses({"checks": rep.checks})["compute"] == status, (name, rep.checks)
    for name, kw in [("gaps", {"samples": 10}), ("full", {"disk": 0.4})]:
        d = tmp_path / name
        d.mkdir()
        pack(d, make_run(d, **kw))
        rep = V.Report()
        V.check_resources(d / "sub", rep)
        assert statuses({"checks": rep.checks})["compute samples"] == "fail", name


def test_the_paper_and_the_data_given_to_the_agent_are_checked(tmp_path):
    from sciexam.submission import verify as V
    for name, kw, status, comparable in [
            ("formal", {}, "pass", True),
            ("other", {"paper": "other"}, "declared", False),
            ("rebuilt", {"data": "rebuilt"}, "declared", False)]:
        d = tmp_path / name
        d.mkdir()
        md = pack(d, make_run(d, **kw))
        assert md["comparable_with_paper"] is comparable, name
        rep = V.Report()
        V.check_task_files(d / "sub", rep)
        assert statuses({"checks": rep.checks})["task files"] == status, (name, rep.checks)
    assert md["task_data"]["kind"] == "rebuilt"
