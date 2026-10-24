"""`sciexam start`: check what a run needs, help with what is missing, then set up the run.

It shows a checklist and, for the first item that is not ready, either offers to do it (after
saying what it will do) or says exactly what to do and checks again:

    item                   done by sciexam start             done by you
    Docker installed       -                                 install Docker Desktop (admin password)
    Docker running         opens Docker Desktop (macOS)      start the Docker service (Linux)
    Docker CPUs, memory    -                                 Docker Desktop: Settings > Resources
    dataset                copies it from the code checkout  -
    raw data               downloads the formal runs' files  -
    reference paper        opens the publisher's page and    download it from the publisher
                           the folder to save it in, checks
                           the PDF found there
    disk                   -                                 free some space
    credentials            writes what you enter to .env     sign in to the model provider

Everything it writes goes to the folder of the install (see sciexam/home.py): nothing outside
it is changed. When every item is ready it opens the interactive setup of `run-agent`.
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .. import home as H
from . import config as C
from . import resources as R
from .provenance import DATA_FILES, PAPER_FILE
from .tui import Abort, Back, backend

PROVIDERS = [
    # (key, credential, what it runs, how to get it)
    ("openrouter", "OPENROUTER_API_KEY", "DeepSeek, GLM, Kimi, MiniMax, Qwen and models you add",
     "an API key from https://openrouter.ai/keys"),
    ("claude", "CLAUDE_CODE_OAUTH_TOKEN", "Claude Opus 5 and Fable 5.1",
     "the token that `claude setup-token` prints (a Claude subscription)"),
    ("codex", "CODEX_AUTH_JSON", "GPT-5.5, GPT-5.6 and GPT-6 Astra",
     "the auth.json that `codex login` writes, usually ~/.codex/auth.json"),
    ("antigravity", "ANTIGRAVITY_HOME", "Gemini 3.8 Flash",
     "the .gemini folder the Antigravity CLI writes after the Google sign-in"),
]
DEFAULT_PATHS = {"CODEX_AUTH_JSON": "~/.codex/auth.json", "ANTIGRAVITY_HOME": "~/.gemini"}


class System:
    """What `start` asks of the machine. The tests replace it."""
    platform = sys.platform

    def docker_path(self):
        return shutil.which("docker")

    def host(self):
        return R.host()

    def open_docker(self):
        return subprocess.run(["open", "-a", "Docker"], capture_output=True).returncode == 0

    def open(self, target):
        """Open a web page or a folder with the desktop's own program."""
        cmd = "open" if self.platform == "darwin" else "xdg-open"
        try:
            return subprocess.run([cmd, str(target)], capture_output=True).returncode == 0
        except OSError:
            return False

    def sha256(self, path):
        from ..prepare import paper as P
        return P.sha256(path)

    def downloads(self):
        """The browser's download folder, where a PDF lands by default."""
        return Path.home() / "Downloads"

    def now(self):
        return time.time()

    def local_dataset(self):
        from .docker_env import repo_root
        code = repo_root()
        d = code.parent / "dataset" if code else None
        return d if d and (d / "MANIFEST.sha256").exists() else None

    def copy_dataset(self, src):
        from .. import dataset as DS
        DS.download(local=src)

    def fetch_data(self, raw_dir, log, progress=None):
        from ..prepare import taskdata as TD
        return TD.fetch(raw_dir, log=log, progress=progress)

    def install_paper(self, src, accept_different, log):
        from ..prepare import paper as P
        from .docker_env import repo_root
        from .. import dataset as DS
        return P.install(src, H.papers_parent(), forbidden=[DS.default_root(), repo_root()],
                         accept_different=accept_different, log=log)

    def disk_free(self, path):
        return R.disk_free_gb(path)

    def sleep(self, s):
        time.sleep(s)


def dropped_path(text):
    """A path typed or dragged into the terminal: quotes and backslash escapes removed."""
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "'\"":
        t = t[1:-1]
    return os.path.expanduser(t.replace("\\ ", " ").replace("\\(", "(").replace("\\)", ")"))


def write_env(path, name, value):
    """Set ``name`` in the credential file (created readable only by you), keeping its other lines."""
    p = Path(path)
    lines = p.read_text().splitlines() if p.exists() else [
        "# Credentials for sciexam run-agent, written by sciexam start. Never share this file."]
    lines = [ln for ln in lines if not ln.strip().startswith(name + "=")] + ["%s=%s" % (name, value)]
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(str(p), 0o600)


class Start:
    def __init__(self, ui=None, system=None, env_file=None, wizard_opts=None):
        self.ui = ui or backend()
        self.sys = system or System()
        self.env_file = env_file or H.env_file()
        self.wizard_opts = wizard_opts or {}
        self.last = None          # what the last step did, shown on the next page

    # ---- the checklist: (title, ok, detail), then what to do about it ------------------------
    def items(self):
        from .. import dataset as DS
        out = []
        docker = self.sys.docker_path()
        out.append(("Docker installed", bool(docker), docker or "not found"))
        h = self.sys.host() if docker else None
        out.append(("Docker running", h is not None, "engine %s" % h["docker"] if h else "not answering"))
        n = R.fit(h)
        out.append(("Docker CPUs and memory", n >= 1, "%d CPUs, %.1f GB: %d agent(s) at once" % (
            h["cpus"], h["memory_gb"], n) if h else "unknown until Docker runs"))
        root = DS.default_root()
        have = (root / "MANIFEST.sha256").exists() and (root / "task").is_dir()
        out.append(("dataset", have, str(root) if have else "not yet in %s" % root))
        raw = H.prepared() / "raw"
        missing = [f for f in DATA_FILES if not (raw / f).exists()]
        out.append(("raw data", not missing, str(raw) if not missing else
                    "%d of %d files missing in %s" % (len(missing), len(DATA_FILES), raw)))
        paper = H.papers_parent() / "papers" / PAPER_FILE
        other = self._paper_candidate()
        out.append(("reference paper", paper.exists(), str(paper) if paper.exists() else
                    "found %s, not the PDF of the formal runs" % other.name if other else
                    "not added yet"))
        free, need = self.sys.disk_free(H.runs()), R.disk_needed_gb(1)
        out.append(("disk", free >= need, "%.1f GB free, %d GB needed" % (free, need)))
        return out

    def help_for(self, title):
        """(lines saying what to do, (label, action) when start can do it, or None)."""
        mac = self.sys.platform == "darwin"
        if title == "Docker installed":
            return (["Docker runs the agent, its network proxy and the grader in containers.",
                     "Install Docker Desktop from https://www.docker.com/products/docker-desktop/"
                     if mac or self.sys.platform.startswith("win") else
                     "Install Docker Engine: https://docs.docker.com/engine/install/",
                     "It asks for your administrator password, so only you can install it.",
                     "Open it once when it is installed, then choose check again."], None)
        if title == "Docker running":
            if mac:
                return (["Docker Desktop is installed but not running."],
                        ("open Docker Desktop now and wait for it (up to 2 minutes)", self._open_docker))
            return (["Start the Docker service, for example: sudo systemctl start docker",
                     "then choose check again."], None)
        if title == "Docker CPUs and memory":
            return (["Each agent gets %d CPUs and %d GB, the share each agent had in the formal runs."
                     % (R.AGENT_CPUS, R.AGENT_MEMORY_GB),
                     "Docker Desktop: click the gear (Settings) > Resources, set CPUs to at least %d "
                     "and Memory to at least %d GB, then Apply & restart." % (R.AGENT_CPUS,
                                                                            R.AGENT_MEMORY_GB + 1),
                     "Docker reports a little less memory than you set, hence the extra GB.",
                     "Wait until Docker has restarted, then choose check again."], None)
        if title == "dataset":
            src = self.sys.local_dataset()
            if src:
                return (["The released dataset (task files, grader observations, checkpoints) comes "
                         "with the code."], ("copy it from %s and check every file (seconds)" % src,
                                             lambda: self._copy_dataset(src)))
            return (["The dataset comes with the code checkout (its dataset/ folder), and none was "
                     "found next to this install.", "Reinstall with install.sh, or run "
                     "sciexam download --local /path/to/dataset, then choose check again."], None)
        if title == "raw data":
            from ..prepare import taskdata as TD
            return (["The agents receive four NOAA observation files (sea surface temperature, "
                     "ocean temperature and currents, wind): the very files of the formal runs, "
                     "checked by sha256.",
                     "To rebuild them from NOAA's servers instead: sciexam prepare-data --keep-raw "
                     "(106 downloads, may differ from the formal files)."],
                    ("download them now (one file, %d MB) into %s" % (TD.ARCHIVE_MB, H.prepared() / "raw"),
                     self._fetch_data))
        if title == "reference paper":
            from ..prepare import paper as P
            folder = H.papers_parent() / "papers"
            folder.mkdir(parents=True, exist_ok=True)
            other = self._paper_candidate()
            if other:
                return (["%s is in the paper folder, but its sha256 is not that of the PDF the "
                         "agents read." % other.name,
                         "The publisher may have re-rendered the same article. It can be used, and "
                         "the run's records will show the difference."],
                        [("use it", "use %s anyway" % other.name, lambda: self._adopt(other)),
                         ("open page", "download it again from the publisher's page",
                          lambda: self._open(P.DOI_URL))])
            return (["The agents read one paper. It is free to read, but its publisher keeps the "
                     "copyright (so we may not ship it) and its site admits browsers only, so it is "
                     "the one file you download yourself:",
                     "  " + P.CITATION,
                     "Choose download: the page opens in your browser, you click Download PDF "
                     "(free, no account needed), and the file is picked up from your Downloads "
                     "folder by itself."],
                    [("download", "open the page; click Download PDF there, nothing else to do",
                      self._download_paper),
                     ("add", "it is already downloaded somewhere: drag it in", self._add_paper)])
        if title == "disk":
            return (["Free some disk space where the runs are kept (%s), then choose check again."
                     % H.runs().resolve()], None)
        return ([], None)

    def _copy_dataset(self, src):
        self.ui.note("copying the dataset and checking the sha256 of every file...")
        t0 = time.time()
        try:
            self.sys.copy_dataset(src)
        except Exception as e:            # a damaged or partial checkout
            self.ui.note("the copy failed: %s" % e)
            return False
        self.last = "dataset copied and checked in %.0f s" % (time.time() - t0)
        return True

    def _fetch_data(self):
        t0 = time.time()
        if not self.sys.fetch_data(H.prepared() / "raw", self.ui.note, self.ui.progress):
            self.ui.note("Choose do it to try again (check your internet connection).")
            return False
        self.last = "raw data downloaded and checked in %.0f s" % (time.time() - t0)
        return True

    def _open_docker(self):
        if not self.sys.open_docker():
            self.ui.note("could not open Docker Desktop: open it from Applications")
            return False
        self.ui.note("waiting for Docker to start...")
        for _ in range(24):
            if self.sys.host() is not None:
                self.last = "Docker Desktop started"
                return True
            self.sys.sleep(5)
        self.ui.note("Docker has not answered yet. Wait until its whale icon stops moving, then "
                     "choose check again.")
        return False

    def _open(self, target):
        if not self.sys.open(target):
            self.ui.note("could not open %s: open it yourself" % target)
            return False
        return True

    @staticmethod
    def _pdfs(folder):
        try:
            return [p for p in folder.iterdir() if p.suffix.lower() == ".pdf" and p.is_file()]
        except OSError:
            return []

    def _download_paper(self, wait_s=600, poll_s=2):
        """Open the paper's page, then wait for a new PDF in the Downloads folder (one whose size
        has stopped changing) and check it and put it in place."""
        from ..prepare import paper as P
        dl, t0 = self.sys.downloads(), self.sys.now()
        old = {p: p.stat().st_mtime for p in self._pdfs(dl)}
        if not self._open(P.DOI_URL):
            return False
        self.ui.note("waiting for the PDF in %s: click Download PDF on the page "
                     "(Ctrl-C stops waiting)" % dl)
        sizes = {}
        try:
            for _ in range(int(wait_s / poll_s)):
                for p in self._pdfs(dl):
                    if p in old and p.stat().st_mtime <= old[p]:
                        continue                         # there before the page was opened
                    size = p.stat().st_size
                    if size and sizes.get(p) == size:    # finished: same size twice
                        return self._take_paper(p)
                    sizes[p] = size
                self.sys.sleep(poll_s)
        except KeyboardInterrupt:
            self.ui.note("stopped waiting")
            return None
        self.ui.note("no PDF arrived in %d minutes" % (wait_s // 60))
        return False

    def _take_paper(self, pdf):
        lines = []
        rc = self.sys.install_paper(pdf, False, lines.append)
        if rc == 1:
            for ln in lines:
                self.ui.note(ln)
            if not self.ui.confirm("Use this PDF anyway (the same article, another rendering)?"):
                return False
            rc = self.sys.install_paper(pdf, True, lambda m: None)
        if rc == 0:
            self.last = "downloaded %s and put it in place" % pdf.name
        return rc == 0

    def _paper_candidate(self):
        """A PDF saved in the paper folder under another name, newest first, or None."""
        folder = H.papers_parent() / "papers"
        if (folder / PAPER_FILE).exists() or not folder.is_dir():
            return None
        pdfs = sorted((p for p in folder.iterdir() if p.suffix.lower() == ".pdf" and p.is_file()),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        return pdfs[0] if pdfs else None

    def _adopt(self, pdf):
        pdf.replace(pdf.parent / PAPER_FILE)
        self.last = "reference paper %s in place" % pdf.name
        return True

    def adopt_saved_paper(self):
        """The PDF of the formal runs (by its sha256) is put in place by itself when it is in the
        paper folder (moved) or among the PDFs in the Downloads folder (copied)."""
        from ..prepare import paper as P
        folder = H.papers_parent() / "papers"
        if (folder / PAPER_FILE).exists():
            return
        pdf = self._paper_candidate()
        if pdf and self.sys.sha256(pdf) == P.SHA256:
            self._adopt(pdf)
            self.last = "found %s in the paper folder: the PDF of the formal runs" % pdf.name
            return
        dl = self.sys.downloads()
        try:
            pdfs = [p for p in dl.iterdir() if p.suffix.lower() == ".pdf" and p.is_file()
                    and p.stat().st_size < 50 * 2 ** 20]
        except OSError:
            return
        for p in sorted(pdfs, key=lambda p: p.stat().st_mtime, reverse=True):
            if self.sys.sha256(p) == P.SHA256:
                folder.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, folder / PAPER_FILE)
                self.last = "found %s in %s: the PDF of the formal runs, copied" % (p.name, dl)
                return

    def _add_paper(self):
        src = dropped_path(self.ui.text("Drag the PDF here (or type its path), then press Enter", ""))
        lines = []
        rc = self.sys.install_paper(src, False, lines.append)
        for ln in lines:
            self.ui.note(ln)
        if rc == 1 and self.ui.confirm("Use this PDF anyway (the same article, another rendering)?"):
            rc = self.sys.install_paper(src, True, self.ui.note)
        if rc == 0:
            self.last = "reference paper added"
        return rc == 0

    # ---- the flow ---------------------------------------------------------------------------
    def show(self, rows):
        self.ui.page()
        if H.home():
            self.ui.note("Everything is kept in %s" % H.home())
        self.ui.heading("Your setup")
        for title, ok, detail in rows:
            self.ui.note("%s %-24s %s" % ("✓" if ok else "✗", title, detail))
        if self.last:
            self.ui.note("")
            self.ui.note("Last step: " + self.last)
            self.last = None

    def checklist(self):
        """Loop until every item is ready. Returns False when the user leaves."""
        while True:
            self.adopt_saved_paper()
            rows = self.items()
            self.show(rows)
            bad = [r for r in rows if not r[1]]
            if not bad:
                return True
            title = bad[0][0]
            lines, action = self.help_for(title)
            self.ui.heading("Next: " + title)
            for ln in lines:
                self.ui.note(ln)
            actions = ([] if not action else [("do it", action[0], action[1])]
                       if isinstance(action, tuple) else action)
            opts = [(k, label) for k, label, _ in actions]
            if "check" not in dict(opts):
                opts.append(("check", "check again"))
            opts.append(("leave", "leave for now (nothing is lost)"))
            self.ui.at_start = True
            try:
                i = self.ui.select("What now", opts, 0)
            except Back:
                continue
            choice = opts[i][0]
            if choice == "leave":
                return False
            fn = next((f for k, _, f in actions if k == choice), None)
            if fn and fn() is False:
                # keep what went wrong on the screen until it has been read
                self.ui.text("Press Enter to go back to the checklist", "")

    def credentials(self):
        """Show which model families have credentials and add one if asked. Never prints a value."""
        while True:
            vals = C.read_env_file(self.env_file)
            self.ui.page()
            if self.last:
                self.ui.note("Last step: " + self.last)
                self.last = None
            self.ui.heading("Model accounts")
            have = 0
            for key, name, runs, _ in PROVIDERS:
                ok = bool(C.credential(name, vals))
                have += ok
                self.ui.note("%s %-12s %s" % ("✓" if ok else "✗", key, runs))
            if not have:
                self.ui.note("Add the account of the models you want to run. Each run is billed to, "
                             "or counted against, it.")
            opts = [("continue", "go on to the run setup")] + [
                (key, "add %s: %s" % (key, how)) for key, _, _, how in PROVIDERS] + [
                ("leave", "leave for now")]
            self.ui.at_start = True
            try:
                i = self.ui.select("Accounts", opts, 0 if have else 1)
            except Back:
                continue
            choice = opts[i][0]
            if choice == "continue":
                return True
            if choice == "leave":
                return False
            key, name, _, how = next(p for p in PROVIDERS if p[0] == choice)
            if name in DEFAULT_PATHS:
                d = os.path.expanduser(DEFAULT_PATHS[name])
                v = dropped_path(self.ui.text("Path to %s" % how, d if os.path.exists(d) else ""))
                if not os.path.exists(v):
                    self.ui.note("nothing at %s: sign in with the provider's CLI first" % v)
                    continue
            else:
                v = self.ui.secret("Paste it here (it is not shown), then press Enter").strip()
                if not v:
                    continue
            write_env(self.env_file, name, v)
            self.last = "%s saved to %s (readable only by you)" % (key, self.env_file)

    def run(self):
        self.ui.banner("Get ready for a run. Each step says what it will do before doing it.")
        if not self.checklist():
            raise Abort("left the checklist, run sciexam start again any time")
        if not self.credentials():
            raise Abort("left before the run setup, run sciexam start again any time")
        self.ui.page()
        self.ui.heading("Ready")
        self.ui.note("Everything a run needs is in place. Next: choose the models and how to run.")
        from .wizard import Wizard
        from . import newmodel as NM
        return Wizard(NM.RELEASED_DIR, ui=self.ui, **self.wizard_opts).run(env_file=self.env_file,
                                                                           banner=False)


def cmd_start(a):
    try:
        argv = Start(env_file=a.env_file).run()
    except (Abort, KeyboardInterrupt) as e:
        print("\nnothing started (%s)" % (e or "interrupted"), file=sys.stderr)
        return 1
    from ..cli import main
    return main(["run-agent"] + argv)
