"""The interactive setup of `sciexam run-agent`, driven with scripted answers (numbered prompts)."""
from pathlib import Path

import pytest

from sciexam.agent import config as C
from sciexam.agent import custom as X
from sciexam.agent.tui import Abort, Plain
from sciexam.agent.wizard import Wizard

AGENTS = Path(__file__).resolve().parents[1] / "agents"


@pytest.fixture(autouse=True)
def no_credentials(tmp_path, monkeypatch):
    """Run in an empty folder (no .env) with no credential in the environment."""
    monkeypatch.chdir(tmp_path)
    for name in ("OPENROUTER_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CODEX_AUTH_JSON", "ANTIGRAVITY_HOME"):
        monkeypatch.delenv(name, raising=False)


def drive(answers):
    it = iter(answers)
    lines = []
    ui = Plain(ask=lambda q: next(it), out=lines.append)
    return Wizard(AGENTS, ui=ui).run(), "\n".join(lines)


def test_defaults_give_a_dry_run_of_the_first_arm():
    argv, text = drive(["", "", "", "", ""])
    assert argv == ["--agent", "deepseek", "--dry-run"]
    assert "Credentials" in text and "MISSING" in text


def test_two_arms_with_a_changed_effort_and_parallel():
    argv, text = drive(["1", "kimi,gpt56", "", "1", "", "2", ""])
    assert argv == ["--agent", "kimi,gpt56", "--effort", "gpt56=low", "--parallel", "2", "--dry-run"]
    assert "changed from medium" in text


def test_going_back_and_custom_settings():
    argv, text = drive(["1", "kimi", "b",              # back from the effort step to the agents
                        "gpt56", "", "2",              # gpt56 at its paper level, custom settings
                        "2", "3", "b", "b",            # 2 h, extra hosts, then back twice to the hours
                        "3", "3", "data.example.org",  # 3 h, extra hosts, one host
                        ""])
    assert argv == ["--agent", "gpt56", "--dry-run", "--hours", "3", "--allow-host", "data.example.org"]
    assert "not comparable" in text


def test_back_from_the_summary_changes_the_settings():
    # custom: 6 h and no PyPI, then back from the summary and choose the paper's settings
    argv, text = drive(["1", "kimi", "", "2", "6", "2", "2", "1", "1"])
    assert "--network" not in argv and "model endpoint only" in text
    assert argv == ["--agent", "kimi", "--dry-run"]


def test_live_run_asks_for_data_and_never_starts_by_default(tmp_path):
    data = tmp_path / "raw"
    data.mkdir()
    pdf = tmp_path / "jin1997.pdf"
    pdf.write_bytes(b"%PDF")
    with pytest.raises(Abort):
        drive(["3", "kimi", "", "", str(data), str(pdf), "3"])
    argv, text = drive(["3", "kimi", "", "", str(data), str(pdf), "1"])
    assert argv == ["--agent", "kimi", "--task-data", str(data), "--paper", str(pdf)]
    assert "billed" in text


def test_bad_answers_are_asked_again():
    argv, _ = drive(["9", "1", "nope", "kimi", "7", "2", "", ""])
    assert argv == ["--agent", "kimi", "--effort", "kimi=medium", "--dry-run"]


def test_q_quits():
    with pytest.raises(Abort):
        drive(["q"])


def test_network_overrides():
    kimi = C.load_arm(AGENTS / "kimi.yaml")
    assert "pypi.org" in C.allowlist(kimi)
    tight = X.apply(kimi, "no-pypi")
    assert "pypi.org" not in C.allowlist(tight) and tight["custom"]["comparable_with_paper"] is False
    extra = X.apply(kimi, None, ["data.example.org"])
    assert "data.example.org" in C.allowlist(extra) and "pypi.org" in C.allowlist(extra)
    assert X.apply(kimi, "paper", None) is kimi
    with pytest.raises(X.CustomError):
        X.apply(kimi, None, ["not a host"])
    with pytest.raises(X.CustomError):
        X.apply(C.load_arm(AGENTS / "fable51_web_literature_only.yaml"), "no-pypi")


def test_a_smoke_setup_is_remembered_and_becomes_the_full_run(tmp_path):
    data = tmp_path / "raw"
    data.mkdir()
    pdf = tmp_path / "jin1997.pdf"
    pdf.write_bytes(b"%PDF")
    # first start: smoke for kimi and gpt56, gpt56 at low, two at a time
    argv, _ = drive(["2", "kimi,gpt56", "", "1", "", "2", str(data), str(pdf), "1"])
    assert argv[:7] == ["--agent", "kimi,gpt56", "--effort", "gpt56=low", "--parallel", "2", "--smoke"]
    # next start: "full run" goes straight to the summary with every answer kept
    argv, text = drive(["2", "1"])
    assert argv == ["--agent", "kimi,gpt56", "--effort", "gpt56=low", "--parallel", "2",
                    "--task-data", str(data), "--paper", str(pdf)]
    assert "repeat the last setup: smoke, kimi, gpt56" in text
    # "last" repeats it as it was, and "new" asks everything again
    argv, _ = drive(["1", "1"])
    assert "--smoke" not in argv and argv[:2] == ["--agent", "kimi,gpt56"]   # the last start was the full run
    argv, _ = drive(["2", "", "", "", "", ""])          # after a full run the choices are last and new
    assert argv == ["--agent", "deepseek", "--dry-run"]


def test_back_from_a_remembered_summary_reaches_the_earlier_steps():
    drive(["1", "kimi", "", "", ""])                          # saves a dry run of kimi
    argv, _ = drive(["1", "2", "b", "b", "gpt56", "", "", ""])
    # summary -> back -> settings -> back -> effort -> back -> agents: choose gpt56 instead
    assert argv == ["--agent", "gpt56", "--dry-run"]
