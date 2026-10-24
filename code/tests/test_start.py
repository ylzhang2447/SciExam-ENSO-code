"""`sciexam start` on a simulated machine: the checklist, the fixes it offers, the accounts."""
import os
import stat
from pathlib import Path

import pytest

from sciexam import home as H
from sciexam.agent import start as S
from sciexam.agent.provenance import DATA_FILES, PAPER_FILE
from sciexam.agent.tui import Abort, Plain

FORMAL = {"cpus": 16, "memory_gb": 30.81, "docker": "29.7"}
OK = lambda s: [("dataset", True, "here")]


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCIEXAM_HOME", str(tmp_path / "home"))
    for name in ("SCIEXAM_DATA", "SCIEXAM_LEDGER", "SCIEXAM_PROFILE", "SCIEXAM_AGENTS",
                 "OPENROUTER_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CODEX_AUTH_JSON", "ANTIGRAVITY_HOME"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "home"


class Machine(S.System):
    """Docker installed but stopped; no dataset, raw data or paper yet."""
    platform = "darwin"

    def __init__(self, docker=True):
        self.docker, self.running, self.calls = docker, False, []

    def docker_path(self):
        return "/usr/local/bin/docker" if self.docker else None

    def host(self):
        return FORMAL if self.running else None

    def open_docker(self):
        self.calls.append("open")
        self.running = True
        return True

    def local_dataset(self):
        return Path("/checkout/dataset")

    def copy_dataset(self, src):
        self.calls.append("copy")
        root = H.dataset()
        (root / "task").mkdir(parents=True)
        (root / "MANIFEST.sha256").write_text("")

    def fetch_data(self, raw_dir, log):
        self.calls.append("fetch")
        Path(raw_dir).mkdir(parents=True)
        for f in DATA_FILES:
            (Path(raw_dir) / f).write_bytes(b"nc")
        return True

    def install_paper(self, src, accept_different, log):
        self.calls.append(("paper", src))
        dest = H.papers_parent() / "papers" / PAPER_FILE
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(Path(src).read_bytes())
        log("copied to %s" % dest)
        return 0

    def disk_free(self, path):
        return 100.0

    def sleep(self, s):
        pass


def drive(answers, machine):
    it = iter(answers)
    lines = []
    ui = Plain(ask=lambda q: next(it), out=lines.append)
    st = S.Start(ui=ui, system=machine, wizard_opts={"checks": OK, "host": lambda: FORMAL})
    return st.run(), "\n".join(lines)


def test_from_nothing_to_a_run(tmp_path, home):
    pdf = tmp_path / "my downloads" / "jin 1997.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-1.4")
    m = Machine()
    argv, text = drive([
        "1",                                   # Docker running: open it
        "1",                                   # dataset: copy it
        "1",                                   # raw data: download it
        "1", str(pdf).replace(" ", "\\ "),    # paper: add it, dragged into the terminal
        "", "sk-or-v1-test-key-1234567890",    # accounts: OpenRouter, the key (not shown)
        "",                                    # go on to the run setup
        "", "kimi", "", "", "me@example.org", "1"], m)
    raw, paper = H.prepared() / "raw", H.papers_parent() / "papers" / PAPER_FILE
    assert argv == ["--agent", "kimi", "--task-data", str(raw), "--paper", str(paper),
                    "--contact", "me@example.org"]
    assert m.calls == ["open", "copy", "fetch", ("paper", str(pdf))]
    env = home / ".env"
    assert "OPENROUTER_API_KEY=sk-or-v1-test-key-1234567890" in env.read_text()
    assert stat.S_IMODE(os.stat(env).st_mode) == 0o600
    assert "sk-or-v1-test" not in text                    # the key is never printed
    assert "Everything is kept in %s" % home in text
    for p in (H.dataset(), raw, paper, env):              # nothing outside the chosen folder
        assert home in Path(p).parents


def test_what_only_you_can_do_is_explained_and_checked_again():
    lines = []
    it = iter(["1", "2"])                        # check again (still missing), then leave
    with pytest.raises(Abort):
        S.Start(ui=Plain(ask=lambda q: next(it), out=lines.append), system=Machine(docker=False)).run()
    text = "\n".join(lines)
    assert "docker-desktop" in text and "administrator password" in text
    assert text.count("Next: Docker installed") == 2


def test_paths_dragged_into_a_terminal():
    assert S.dropped_path("/Users/me/My\\ Files/jin\\ \\(1997\\).pdf ") == "/Users/me/My Files/jin (1997).pdf"
    assert S.dropped_path("'/tmp/a b.pdf'") == "/tmp/a b.pdf"


def test_write_env_keeps_other_lines(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# mine\nCLAUDE_CODE_OAUTH_TOKEN=abc\nOPENROUTER_API_KEY=old\n")
    S.write_env(f, "OPENROUTER_API_KEY", "new")
    assert f.read_text() == "# mine\nCLAUDE_CODE_OAUTH_TOKEN=abc\nOPENROUTER_API_KEY=new\n"
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600


def test_a_failed_step_waits_and_the_next_page_says_what_happened():
    class Offline(Machine):
        def fetch_data(self, raw_dir, log):
            log("the download did not finish: no network")
            return False
    lines = []
    it = iter(["1", "1", "1", "", "3"])          # open Docker, copy, download (fails), Enter, leave
    with pytest.raises(Abort):
        S.Start(ui=Plain(ask=lambda q: next(it), out=lines.append), system=Offline()).run()
    text = "\n".join(lines)
    assert "Last step: Docker Desktop started" in text and "Last step: dataset copied" in text
    assert "did not finish: no network" in text and text.count("Next: raw data") == 2
