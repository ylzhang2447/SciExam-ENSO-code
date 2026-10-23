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
    monkeypatch.setenv("SCIEXAM_PROFILE", str(tmp_path / "profile.json"))
    monkeypatch.setenv("SCIEXAM_LEDGER", str(tmp_path / "runs.jsonl"))
    monkeypatch.setenv("SCIEXAM_AGENTS", str(tmp_path / "agents"))
    for name in ("OPENROUTER_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CODEX_AUTH_JSON", "ANTIGRAVITY_HOME"):
        monkeypatch.delenv(name, raising=False)


OK = lambda s: [("dataset", True, "here"), ("Docker", True, "engine 27"),
                ("task data and paper", True, "every file in place")]


@pytest.fixture
def files(tmp_path):
    data = tmp_path / "raw"
    data.mkdir()
    pdf = tmp_path / "jin1997.pdf"
    pdf.write_bytes(b"%PDF")
    answers = [str(data), str(pdf), "me@example.org"]
    flags = ["--task-data", str(data), "--paper", str(pdf), "--contact", "me@example.org"]
    return answers, flags


def drive(answers, checks=OK, check_openrouter=True):
    it = iter(answers)
    lines = []
    ui = Plain(ask=lambda q: next(it), out=lines.append)
    w = Wizard(AGENTS, ui=ui, checks=checks, check_openrouter=check_openrouter)
    return w.run(), "\n".join(lines)


def test_defaults_give_the_full_run_of_the_first_arm(files):
    data, flags = files
    argv, text = drive(["", ""] + data + ["1"])
    assert argv == ["--agent", "deepseek"] + flags
    assert "MISSING" in text and "Checks" in text
    argv, _ = drive(["1", "2"])                  # the last setup again, as a smoke run this time
    assert argv == ["--agent", "deepseek", "--smoke"] + flags


def test_the_checks_run_before_start_and_never_start_by_default(files):
    data, flags = files
    bad = lambda s: [("Docker", False, "not running: start Docker Desktop")]
    with pytest.raises(Abort):
        drive(["", "kimi"] + data + ["4"], checks=bad)
    with pytest.raises(StopIteration):          # the default answer is back, not start
        drive(["", "kimi"] + data + [""], checks=bad)
    argv, text = drive(["", "kimi"] + data + ["1"], checks=bad)
    assert argv == ["--agent", "kimi"] + flags
    assert "PROBLEM" in text and "Fix these first" in text and "Docker" in text and "billed" in text


def test_two_arms_with_a_changed_effort_and_parallel(files):
    data, flags = files
    argv, text = drive(["2", "kimi,gpt56", "", "1", "", "", "2"] + data + ["1"])
    assert argv == ["--agent", "kimi,gpt56", "--effort", "gpt56=low", "--parallel", "2"] + flags
    assert "changed from medium" in text


def test_going_back_and_custom_settings(files):
    data, flags = files
    argv, text = drive(["2", "kimi", "b",              # customize, kimi, back from its effort
                        "gpt56", "",                   # gpt56 at its leaderboard level
                        "2", "3", "b", "b",            # 2 h, extra hosts, then back twice to the hours
                        "3", "3", "data.example.org",  # 3 h, extra hosts, one host
                        ] + data + ["1"])
    assert argv == ["--agent", "gpt56", "--hours", "3", "--allow-host", "data.example.org"] + flags
    assert "not comparable" in text


def test_back_from_the_summary_changes_the_settings(files):
    # customize: 6 h and no PyPI, then back from the summary to the first question, choose the default
    data, flags = files
    argv, text = drive(["2", "kimi", "", "6", "2"] + data +
                       ["3", "b", "b", "b", "b", "1", "", "", "", "", "1"])
    # summary -> data -> run time -> effort -> agents -> settings
    assert "--network" not in argv and "model endpoint only" in text
    assert argv == ["--agent", "kimi"] + flags


def test_bad_answers_are_asked_again(files):
    data, flags = files
    argv, _ = drive(["9", "2", "nope", "kimi", "7", "2", "", ""] + data + ["1"])
    assert argv == ["--agent", "kimi", "--effort", "kimi=medium"] + flags


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


def test_a_smoke_setup_is_remembered_and_becomes_the_full_run(files):
    data, flags = files
    # first start: a smoke run of kimi and gpt56, gpt56 at low, two at a time
    argv, _ = drive(["2", "kimi,gpt56", "", "1", "", "", "2"] + data + ["2"])
    assert argv == ["--agent", "kimi,gpt56", "--effort", "gpt56=low", "--parallel", "2", "--smoke"] + flags
    # next start: the last setup goes straight to the summary, where full starts the full run
    argv, text = drive(["1", "1"])
    assert argv == ["--agent", "kimi,gpt56", "--effort", "gpt56=low", "--parallel", "2"] + flags
    assert "repeat the last setup (smoke): kimi, gpt56, customized settings" in text
    # "new" asks everything again but keeps the data paths and the contact
    argv, _ = drive(["2", "", "", "", "", "", "1"])
    assert argv == ["--agent", "deepseek"] + flags


def test_back_from_a_remembered_summary_reaches_the_earlier_steps(files):
    data, flags = files
    drive(["", "kimi"] + data + ["1"])                        # saves a full run of kimi
    argv, _ = drive(["1", "3", "b", "gpt56", "", "", "", "1"])
    # summary -> back -> data -> back -> agents: choose gpt56 instead
    assert argv == ["--agent", "gpt56"] + flags


def test_adding_a_model_from_the_agent_list(files):
    data, flags = files
    argv, text = drive(["", "add", "1", "qwen/qwen3-coder", ""] + data + ["1"], check_openrouter=False)
    assert argv == ["--agent", "openrouter-qwen-qwen3-coder"] + flags
    assert "added qwen/qwen3-coder (openrouter)" in text
    # the next start lists it with the leaderboard's arms
    argv, _ = drive(["2", "", "openrouter-qwen-qwen3-coder", "", "", "", "1"])
    assert argv == ["--agent", "openrouter-qwen-qwen3-coder"] + flags


def test_adding_a_local_model_asks_its_context_window(files):
    data, flags = files
    argv, text = drive(["", "add", "5", "llama-4", "", "32768", ""] + data + ["1"],
                       check_openrouter=False)
    assert argv == ["--agent", "local-llama-4"] + flags
    assert "ranked apart from the official leaderboard" in text


def test_default_settings_skip_every_option_and_clear_old_changes(files):
    # customize with gpt56 at low and one at a time, then back to the first question, choose default
    data, flags = files
    argv, text = drive(["2", "kimi,gpt56", "", "1", "", "", "1"] + data +
                       ["3", "b", "b", "b", "b", "b", "1", "", "", "", "", "1"])
    assert argv == ["--agent", "kimi,gpt56", "--parallel", "2"] + flags
    assert "Reasoning effort" in text and "not comparable" not in text.split("Summary")[-1]


def test_default_settings_run_up_to_three_at_a_time(files):
    data, flags = files
    argv, _ = drive(["", "kimi,gpt56,deepseek,glm52"] + data + ["1"])
    assert argv == ["--agent", "kimi,gpt56,deepseek,glm52", "--parallel", "3"] + flags


def test_the_real_checks_name_what_is_missing(tmp_path, monkeypatch):
    from sciexam.agent import wizard as W
    monkeypatch.setenv("PATH", str(tmp_path))                 # no docker on the PATH
    out = {w: (ok, d) for w, ok, d in W.setup_checks({"task_data": None, "paper": None})}
    assert out["Docker"] == (False, "not installed: https://docs.docker.com/get-docker/")


def test_menus_never_wrap_or_overflow_a_small_terminal(monkeypatch):
    import io
    import os
    import re
    from sciexam.agent import tui
    monkeypatch.setattr(tui.shutil, "get_terminal_size", lambda fallback=None: os.terminal_size((40, 12)))
    k = tui.Keys()
    k.w = io.StringIO()
    lines = ["    ( ) %-32s a long description of agent number %d" % ("arm%d" % n, n) for n in range(30)]
    for first, focus in ((True, 0), (False, 15), (False, 29)):
        k.w = io.StringIO()
        k._draw(lines, first, focus=focus, footer="  1 selected")
        rows = [re.sub(r"\033\[[0-9;?]*[A-Za-z]", "", r).lstrip("\r") for r in k.w.getvalue().split("\n")[:-1]]
        assert len(rows) == 9 and all(len(r) <= 39 for r in rows)        # 12 rows, 40 columns
        assert any("arm%d " % focus in r for r in rows)                  # the cursor's line is shown
    assert "more" in rows[0] and rows[-1] == "  1 selected"
    assert tui.clip("abc", 10) == "abc" and tui.clip("abcdefghijkl", 5) == "abcd…" + tui.RESET


def test_a_resized_terminal_gets_a_clean_redraw(monkeypatch):
    import io
    import os
    from sciexam.agent import tui
    size = [os.terminal_size((100, 24))]
    monkeypatch.setattr(tui.shutil, "get_terminal_size", lambda fallback=None: size[0])
    k = tui.Keys()
    k.w = io.StringIO()
    k.banner("Set up a run.")
    k.heading("Mode")
    k.note("a note of this step")
    k._draw(["  > smoke  x", "    full   y"], True, header="Mode")
    k._draw(["    smoke  x", "  > full   y"], False, header="Mode")
    assert "\033[2J" not in k.w.getvalue() and "\033[3A" in k.w.getvalue()    # same size: in place
    size[0] = os.terminal_size((60, 24))
    k.w = io.StringIO()
    k._draw(["  > smoke  x", "    full   y"], False, header="Mode")
    out = k.w.getvalue()
    assert out.startswith("\033[H\033[2J") and "\033[3A" not in out and "Mode" in out
    assert "SciExam for ENSO" in out and "Set up a run." in out and "a note of this step" in out


def test_back_on_the_first_question_does_nothing(files):
    data, flags = files
    argv, text = drive(["b", "", "kimi"] + data + ["1"])
    assert argv == ["--agent", "kimi"] + flags
    assert text.splitlines().count("Settings") == 1 and "this is the first question" in text
