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

    def fetch_data(self, raw_dir, log, progress=None):
        self.calls.append("fetch")
        for done in (60e6, 120e6, 180e6):
            progress(done, 180e6)
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

    def open(self, target):
        self.calls.append(("open", str(target)))
        return True

    def sha256(self, path):
        from sciexam.prepare import paper as P
        return P.SHA256 if b"formal" in Path(path).read_bytes() else "0" * 64

    def downloads(self):
        d = H.home().parent / "Downloads"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def sleep(self, s):
        if getattr(self, "arrives", None):         # the browser finishes the download
            self.arrives[0].write_bytes(self.arrives[1])
            self.arrives = None

    def now(self):
        return 1e9


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
        "2", str(pdf).replace(" ", "\\ "),    # paper: already downloaded elsewhere, dragged in
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
    assert "] 100%  180 of 180 MB" in text                # the download's progress bar
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
        def fetch_data(self, raw_dir, log, progress=None):
            log("the download did not finish: no network")
            return False
    lines = []
    it = iter(["1", "1", "1", "", "3"])          # open Docker, copy, download (fails), Enter, leave
    with pytest.raises(Abort):
        S.Start(ui=Plain(ask=lambda q: next(it), out=lines.append), system=Offline()).run()
    text = "\n".join(lines)
    assert "Last step: Docker Desktop started" in text and "Last step: dataset copied" in text
    assert "did not finish: no network" in text and text.count("Next: raw data") == 2


def ready_but_the_paper():
    m = Machine()
    m.running = True
    m.copy_dataset(None)
    m.fetch_data(H.prepared() / "raw", print, lambda d, t: None)
    m.calls = []
    return m


def test_a_pdf_saved_in_the_paper_folder_is_found_and_checked():
    m = ready_but_the_paper()
    folder = H.papers_parent() / "papers"
    lines = []
    it = iter(["3"])                              # check again
    def answer(q):
        a = next(it, None)
        if a is None:                            # the user has saved the PDF meanwhile: check again
            (folder / "jas-1997-download.pdf").write_bytes(b"%PDF formal")
            raise Abort("checked")               # stop before the accounts step
        return a
    with pytest.raises(Abort):
        S.Start(ui=Plain(ask=answer, out=lines.append), system=m).run()
    from sciexam.prepare import paper as P
    assert m.calls == []
    st = S.Start(ui=Plain(ask=lambda q: (_ for _ in ()).throw(Abort("x")), out=lines.append), system=m)
    st.adopt_saved_paper()
    assert (folder / PAPER_FILE).exists() and not (folder / "jas-1997-download.pdf").exists()
    assert "the PDF of the formal runs" in st.last


def test_another_rendering_can_be_used_when_asked():
    m = ready_but_the_paper()
    folder = H.papers_parent() / "papers"
    folder.mkdir(parents=True)
    (folder / "jin.pdf").write_bytes(b"%PDF re-rendered")
    lines = []
    it = iter(["1"])                              # use jin.pdf anyway
    with pytest.raises(StopIteration):           # then the accounts step asks: the paper is done
        S.Start(ui=Plain(ask=lambda q: next(it), out=lines.append), system=m).run()
    text = "\n".join(lines)
    assert "found jin.pdf, not the PDF of the formal runs" in text
    assert (folder / PAPER_FILE).exists() and "Model accounts" in text


def test_the_pdf_is_picked_up_from_downloads():
    m = ready_but_the_paper()
    dl = m.downloads()
    (dl / "other.pdf").write_bytes(b"%PDF unrelated")
    (dl / "1520-0469(1997)054.pdf").write_bytes(b"%PDF formal")
    lines = []
    it = iter(["3"])                              # check again, after downloading in the browser
    with pytest.raises(StopIteration):           # the accounts step is next
        S.Start(ui=Plain(ask=lambda q: next(it), out=lines.append), system=m).run()
    assert (H.papers_parent() / "papers" / PAPER_FILE).read_bytes() == b"%PDF formal"
    assert (dl / "1520-0469(1997)054.pdf").exists()           # the download is left where it is
    assert "found 1520-0469(1997)054.pdf in" in "\n".join(lines)


def test_one_click_the_download_is_picked_up_by_itself():
    m = ready_but_the_paper()
    dl = m.downloads()
    (dl / "old.pdf").write_bytes(b"%PDF formal")             # there before: not taken
    import os
    os.utime(dl / "old.pdf", (1, 1))
    m.arrives = (dl / "1520-0469(1997)054.pdf", b"%PDF formal")
    lines = []
    it = iter(["1"])                              # download: the page opens, the user clicks
    st = S.Start(ui=Plain(ask=lambda q: next(it), out=lines.append), system=m)
    m.sha256 = lambda p: "0" * 64                 # nothing in Downloads matches before the click
    with pytest.raises(StopIteration):           # paper done, the accounts step asks next
        st.run()
    from sciexam.prepare import paper as P
    assert ("open", P.DOI_URL) in m.calls
    assert ("paper", dl / "1520-0469(1997)054.pdf") in m.calls
    assert "Last step: downloaded 1520-0469(1997)054.pdf" in "\n".join(lines)
