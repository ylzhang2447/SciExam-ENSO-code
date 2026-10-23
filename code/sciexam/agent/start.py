"""`sciexam start`: check what a run needs, help with what is missing, then set up the run.

It shows a checklist and, for the first item that is not ready, either offers to do it (after
saying what it will do) or says exactly what to do and checks again:

    item                   done by sciexam start             done by you
    Docker installed       -                                 install Docker Desktop (admin password)
    Docker running         opens Docker Desktop (macOS)      start the Docker service (Linux)
    Docker CPUs, memory    -                                 Docker Desktop: Settings > Resources
    dataset                copies it from the code checkout  -
    raw data               downloads and rebuilds it (NOAA)  -
    reference paper        checks and copies your PDF        download it from the publisher
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

    def local_dataset(self):
        from .docker_env import repo_root
        code = repo_root()
        d = code.parent / "dataset" if code else None
        return d if d and (d / "MANIFEST.sha256").exists() else None

    def copy_dataset(self, src):
        from .. import dataset as DS
        DS.download(local=src)

    def prepare(self, out):
        return subprocess.run([sys.executable, "-m", "sciexam", "prepare-data", "--out", str(out),
                               "--keep-raw"]).returncode

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
        out.append(("reference paper", paper.exists(), str(paper) if paper.exists() else "not added yet"))
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
                                             lambda: self.sys.copy_dataset(src)))
            return (["The dataset comes with the code checkout (its dataset/ folder), and none was "
                     "found next to this install.", "Reinstall with install.sh, or run "
                     "sciexam download --local /path/to/dataset, then choose check again."], None)
        if title == "raw data":
            return (["The agents receive four observation files (sea surface temperature, ocean "
                     "temperature and currents, wind), rebuilt from NOAA's public servers."],
                    ("download them now (about 330 MB, a few minutes) into %s" % H.prepared(),
                     lambda: self.sys.prepare(H.prepared())))
        if title == "reference paper":
            from ..prepare import paper as P
            return (["The agents read one paper, which we may not redistribute:",
                     "  " + P.CITATION, "  " + P.DOI_URL,
                     "Download the PDF from the publisher (your library may give access), then "
                     "choose add it and drag the file into this window."],
                    ("add the PDF you downloaded", self._add_paper))
        if title == "disk":
            return (["Free some disk space where the runs are kept (%s), then choose check again."
                     % H.runs().resolve()], None)
        return ([], None)

    def _open_docker(self):
        if not self.sys.open_docker():
            self.ui.note("could not open Docker Desktop: open it from Applications")
            return
        self.ui.note("waiting for Docker to start...")
        for _ in range(24):
            if self.sys.host() is not None:
                return
            self.sys.sleep(5)
        self.ui.note("Docker has not answered yet. Wait until its whale icon stops moving.")

    def _add_paper(self):
        src = dropped_path(self.ui.text("Drag the PDF here (or type its path), then press Enter", ""))
        lines = []
        rc = self.sys.install_paper(src, False, lines.append)
        for ln in lines:
            self.ui.note(ln)
        if rc == 1 and self.ui.confirm("Use this PDF anyway (the same article, another rendering)?"):
            rc = self.sys.install_paper(src, True, self.ui.note)

    # ---- the flow ---------------------------------------------------------------------------
    def show(self, rows):
        self.ui.heading("Your setup")
        for title, ok, detail in rows:
            self.ui.note("%s %-24s %s" % ("✓" if ok else "✗", title, detail))

    def checklist(self):
        """Loop until every item is ready. Returns False when the user leaves."""
        while True:
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
            opts = ([("do it", action[0])] if action else []) + [
                ("check", "check again"), ("leave", "leave for now (nothing is lost)")]
            self.ui.at_start = True
            try:
                i = self.ui.select("What now", opts, 0)
            except Back:
                continue
            choice = opts[i][0]
            if choice == "leave":
                return False
            if choice == "do it":
                action[1]()

    def credentials(self):
        """Show which model families have credentials and add one if asked. Never prints a value."""
        while True:
            vals = C.read_env_file(self.env_file)
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
            self.ui.note("saved to %s (readable only by you)" % self.env_file)

    def run(self):
        self.ui.banner("Get ready for a run. Each step says what it will do before doing it.")
        if H.home():
            self.ui.note("Everything is kept in %s" % H.home())
        if not self.checklist():
            raise Abort("left the checklist, run sciexam start again any time")
        if not self.credentials():
            raise Abort("left before the run setup, run sciexam start again any time")
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
