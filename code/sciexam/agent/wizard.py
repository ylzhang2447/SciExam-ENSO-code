"""Interactive setup of `sciexam run-agent`.

`sciexam run-agent` without --agent, on a terminal, shows the logo and asks for the run one step
at a time: the mode (a smoke run or the full run), the agents, the settings (the official
leaderboard's, or customized effort, run time, network and parallel runs), and the task data and
paper. Before it offers to start it checks what a run needs (the dataset, Docker, the task data
and paper, the credentials: set or missing, never their values), shows a summary and the
equivalent command line, and starts only when asked to. Every step can go back to the
one before it. The prompts come from `tui`: arrow-key menus on a terminal, numbered choices
elsewhere.
"""
import json
import shlex
import subprocess
import sys
from pathlib import Path

from . import config as C
from . import custom as X
from . import effort as E
from . import newmodel as NM
from .tui import Abort, Back, Plain, backend

MODES = [
    ("smoke", "15-minute check of containers, credentials and network. Uses your account"),
    ("full", "the benchmark run, 6 h per agent by default. Uses your account"),
]
# The last setup that was started, so the next run can repeat it, or turn a smoke run into the
# full run without answering every question again. Kept next to the run folders.
SETUP_FILE = Path("sciexam_runs") / "last_setup.json"
SAVED_KEYS = ("mode", "levels", "custom", "hours", "network", "net_choice", "hosts", "parallel",
              "task_data", "paper", "contact")

# the leaderboard runs were made two or three agents at a time
DEFAULT_PARALLEL = 3

NETWORK_CHOICES = [
    ("paper", "the model endpoint and PyPI, as on the official leaderboard"),
    ("no-pypi", "the model endpoint only, no package installs"),
    ("extra", "the leaderboard's setting plus hosts you name"),
]


class Wizard:
    def __init__(self, agents_dir=None, ui=None, check_openrouter=True, checks=None):
        self.agents_dir = Path(agents_dir) if agents_dir else None
        self.ui = ui or backend()
        self.check_openrouter = check_openrouter
        self.checks = checks or setup_checks
        self.s = {}

    # ---- data -------------------------------------------------------------------------------
    def arms(self):
        """The paper's ranked arms, then the models added with add-model, then the condition runs."""
        paths = list(self.agents_dir.glob("*.yaml")) if self.agents_dir else []
        paths += [p for p in NM.all_configs() if p.parent != self.agents_dir]
        rows = [(p, C.load_arm(p)) for p in paths]
        rows.sort(key=lambda r: (bool(r[1].get("condition")), r[0].parent != NM.RELEASED_DIR,
                                 r[0].stem))
        return rows

    # ---- steps: each reads and writes self.s, and raises Back to return to the previous one --
    def step_mode(self):
        self.ui.heading("Mode")
        self.s["mode"] = MODES[self.ui.select("How do you want to run", MODES,
                                              [m[0] for m in MODES].index(self.s.get("mode", "smoke")))][0]

    def step_agents(self):
        self.ui.heading("Agents")
        rows = self.rows
        opts = []
        for p, arm in rows:
            tag = ("condition run" if arm.get("condition") else
                   "added" if p.parent != NM.RELEASED_DIR else arm["route"]["kind"])
            opts.append((arm["arm"], "%-20s %-12s %s" % (arm.get("display_name") or "",
                                                          arm["scaffold"]["name"], tag)))
        opts.append(("+ add a model", "a model the paper did not run, on a paper system's protocol"))
        default = self.s.get("picked_idx", [0])
        idx = self.ui.multiselect("Which agents", opts, default,
                                  names=[a["arm"] for _, a in rows] + ["add"])
        add = len(rows) in idx
        idx = [i for i in idx if i < len(rows)]
        if add:
            chosen = [rows[i][0] for i in idx]
            try:
                path = self.add_model()
            except Back:
                raise _Again()               # back from adding a model: the agent list again
            self.rows = rows = self.arms()
            where = {p: k for k, (p, _) in enumerate(rows)}
            idx = [where[p] for p in chosen] + [where[path]]
        if not idx:
            self.ui.note("choose at least one agent")
            raise _Again()
        self.s["picked_idx"] = idx
        self.s["picked"] = [rows[i] for i in idx]

    def add_model(self):
        """Ask for a new model and write its configuration. Returns the path."""
        routes = list(NM.TEMPLATES)
        sub, st = 0, {}
        while True:
            try:
                if sub == 0:
                    self.ui.heading("Add a model")
                    i = self.ui.select("How is the model reached", [(r, NM.ROUTE_LABELS[r]) for r in routes],
                                       routes.index(st.get("route", "openrouter")))
                    st["route"] = routes[i]
                    sub = 1
                elif sub == 1:
                    def check(v):
                        v = v.strip()
                        if not v or " " in v:
                            return "the model id, for example qwen/qwen3-coder"
                        if st["route"] == "openrouter" and self.check_openrouter:
                            info = NM.openrouter_info(v)
                            if info and not info["exists"]:
                                return "OpenRouter lists no model %r (see openrouter.ai/models)" % v
                            st["context"] = (info or {}).get("context_length")
                        return None
                    hint = {"openrouter": "e.g. qwen/qwen3-coder", "claude": "e.g. claude-opus-5-5",
                            "codex": "e.g. gpt-6", "antigravity": "e.g. gemini-3.9-pro-medium",
                            "local": "the name your server gives the model"}[st["route"]]
                    st["model"] = self.ui.text("Model id (%s)" % hint, st.get("model", ""), check).strip()
                    sub = 2 if st["route"] == "local" else 3
                elif sub == 2:
                    def check_url(v):
                        try:
                            NM.gateway_api_base(v)
                        except NM.ModelError as e:
                            return str(e)
                        return None
                    st["api_base"] = self.ui.text("Endpoint (OpenAI-compatible, e.g. http://localhost:8000/v1)",
                                                  st.get("api_base", "http://localhost:8000/v1"), check_url)
                    sub = 4
                elif sub == 4:
                    def check_ctx(v):
                        return None if v.isdigit() and int(v) >= 16000 else "a number of tokens, at least 16000"
                    st["context"] = int(self.ui.text("Context window the model is served with, in tokens",
                                                     str(st.get("context") or 131072), check_ctx))
                    sub = 3
                else:
                    st["name"] = self.ui.text("Display name on the leaderboard", st.get("name") or st["model"])
                    try:
                        path = NM.make(st["route"], st["model"], name=st["name"], api_base=st.get("api_base"),
                                       context_tokens=st.get("context"))
                    except NM.ModelError as e:
                        self.ui.note(str(e))
                        sub = 1
                        continue
                    self.ui.note("added %s (%s), configuration in %s" % (st["name"], st["route"], path))
                    if st.get("context") and st["context"] < NM.PAPER_CONTEXT:
                        self.ui.note("its context window, %d tokens, is smaller than the leaderboard's 200,000: "
                                     "the run is ranked apart from the official leaderboard" % st["context"])
                    return path
            except Back:
                if sub == 0:
                    raise
                sub = {1: 0, 2: 1, 4: 2, 3: 4 if st.get("route") == "local" else 1}[sub]

    def step_effort(self):
        if not self.s.get("custom"):
            raise Skip()
        self.ui.heading("Reasoning effort")
        self.ui.note("The official leaderboard's level is preselected. Another level is recorded "
                     "as not comparable with the official leaderboard.")
        levels = dict(self.s.get("levels", {}))
        picked = self.s["picked"]
        k = 0
        while k < len(picked):
            arm = picked[k][1]
            paper = arm["reasoning"]["effort"]
            opts = E.options(arm)
            choices = [(lv, "leaderboard" if lv == paper else "") for lv in opts]
            cur = levels.get(arm["arm"], paper)
            try:
                i = self.ui.select("%s  (%s)" % (arm["arm"], E.mechanism(arm)), choices,
                                   opts.index(cur))
            except Back:
                if k == 0:
                    raise
                k -= 1
                continue
            if opts[i] == paper:
                levels.pop(arm["arm"], None)
            else:
                levels[arm["arm"]] = opts[i]
            k += 1
        self.s["levels"] = levels

    def step_start(self):
        saved = self.saved
        if not saved:
            raise Skip()
        self.ui.heading("Start from")
        desc = "%s, %s, %s" % (saved["mode"], ", ".join(saved["agents"]),
                               "custom settings" if saved.get("custom") else "default settings")
        opts = [("last", "repeat the last setup: " + desc)]
        if saved["mode"] != "full":
            opts.append(("full run", "the last setup as the full benchmark run"))
        opts.append(("new", "answer every question again"))
        i = self.ui.select("Use the last setup", opts, 0)
        choice = opts[i][0]
        # the data paths and the contact belong to this machine, not to the run: kept as defaults
        self.s = {k: saved[k] for k in ("task_data", "paper", "contact") if saved.get(k)}
        if choice != "new":
            self.s = {k: saved[k] for k in SAVED_KEYS if k in saved}
            names = [a["arm"] for _, a in self.rows]
            idx = [names.index(k) for k in saved["agents"]]      # in the order they were chosen
            self.s["picked_idx"] = idx
            self.s["picked"] = [self.rows[n] for n in idx]
            if choice == "full run":
                self.s["mode"] = "full"
            self.jump = True

    def step_settings(self):
        self.ui.heading("Settings")
        if self.s["mode"] == "smoke":
            self.ui.note("A smoke run checks the network you will use for the full run, so it takes "
                         "these settings too. Its run time is fixed at 15 minutes.")
        cur = 1 if self.s.get("custom") else 0
        i = self.ui.select("Run settings", [
            ("default", "as on the official leaderboard: its reasoning effort, run time (6 h) and "
                        "network, up to %d agents at a time" % DEFAULT_PARALLEL),
            ("customize", "choose the effort, run time, network and how many agents run at once")], cur)
        self.s["custom"] = i == 1
        if not self.s["custom"]:
            self.s.update(levels={}, hours=None, network="paper", net_choice="paper", hosts=[],
                          parallel=min(len(self.s["picked"]), DEFAULT_PARALLEL))

    def step_runtime(self):
        if not self.s.get("custom"):
            raise Skip()
        self.ui.heading("Run time and network")
        sub = 0
        while True:
            try:
                if sub == 0:
                    if self.s["mode"] == "smoke":
                        self.ui.note("A smoke run lasts 15 minutes, so its run time is fixed.")
                        self.s["hours"] = None
                    else:
                        def check(v):
                            try:
                                return None if 0 < float(v) <= 48 else "a number of hours from 0 to 48"
                            except ValueError:
                                return "a number of hours, for example 2 or 0.5"
                        h = self.ui.text("Run time per agent in hours (leaderboard: 6)",
                                         str(self.s.get("hours") or 6), check)
                        self.s["hours"] = None if float(h) == 6 else float(h)
                    sub = 1
                elif sub == 1:
                    cur = [n for n, _ in NETWORK_CHOICES].index(self.s.get("net_choice", "paper"))
                    i = self.ui.select("Network of the agent container", NETWORK_CHOICES, cur)
                    self.s["net_choice"] = NETWORK_CHOICES[i][0]
                    self.s["network"] = "no-pypi" if i == 1 else "paper"
                    if i != 2:
                        self.s["hosts"] = []
                        return
                    sub = 2
                else:
                    def check(v):
                        try:
                            return None if X.hosts_from([v]) else "name at least one host"
                        except X.CustomError as e:
                            return str(e)
                    v = self.ui.text("Extra hosts, comma separated", ",".join(self.s.get("hosts", [])), check)
                    self.s["hosts"] = X.hosts_from([v])
                    return
            except Back:
                if sub == 0 or (sub == 1 and self.s["mode"] == "smoke"):
                    raise
                sub -= 1

    def step_parallel(self):
        n = len(self.s["picked"])
        if n < 2:
            self.s["parallel"] = 1
            raise Skip()
        if not self.s.get("custom"):
            raise Skip()
        self.ui.heading("Parallel runs")
        opts = [(str(k), "agent at a time" if k == 1 else "agents at a time") for k in range(1, n + 1)]
        cur = self.s.get("parallel") or min(n, DEFAULT_PARALLEL)
        self.s["parallel"] = self.ui.select("How many run at the same time", opts, min(cur, n) - 1) + 1

    def step_data(self):
        self.ui.heading("Task data and reference paper")
        sub = 0
        while True:
            try:
                if sub == 0:
                    self.s["task_data"] = self.ui.text(
                        "Folder with the four raw data files (sciexam prepare-data --keep-raw writes OUT/raw)",
                        self.s.get("task_data") or "prepared/raw",
                        lambda v: None if Path(v).is_dir() else "no such folder: %s" % v)
                    sub = 1
                elif sub == 1:
                    self.s["paper"] = self.ui.text(
                        "Path to the Jin (1997) PDF (sciexam fetch-paper explains how to get it)",
                        self.s.get("paper") or "",
                        lambda v: None if v and Path(v).is_file() else "no such file: %s" % (v or "(empty)"))
                    sub = 2
                else:
                    # written into the run now, so its submission never has to ask
                    from .ledger import load_profile
                    self.s["contact"] = self.ui.text(
                        "Contact for the leaderboard (email or GitHub handle, kept for later runs)",
                        self.s.get("contact") or load_profile().get("contact") or "",
                        lambda v: None if v.strip() else "a contact is needed to submit the run")
                    return
            except Back:
                if sub == 0:
                    raise
                sub -= 1

    def step_review(self):
        s = self.s
        # what --dry-run checks, done here every time, so a run never starts on a broken setup
        self.ui.heading("Checks")
        problems = []
        for what, ok, detail in self.checks(s):
            self.ui.note("%-26s %-8s %s" % (what, "ok" if ok else "PROBLEM", detail))
            if not ok:
                problems.append(what)
        env_values = C.read_env_file(self.env_file)
        for name, what in sorted({c for _, a in s["picked"] for c in C.required_credentials(a)}):
            ok = bool(C.credential(name, env_values))
            self.ui.note("%-26s %-8s %s" % (name, "set" if ok else "MISSING", what))
            if not ok:
                problems.append(name)

        argv = self.command()
        self.ui.heading("Summary")
        self.ui.note("mode      %s" % s["mode"])
        for _, arm in s["picked"]:
            lv = s["levels"].get(arm["arm"], arm["reasoning"]["effort"])
            ch = "  (changed from %s)" % arm["reasoning"]["effort"] if arm["arm"] in s["levels"] else ""
            self.ui.note("agent     %-28s effort %s%s" % (arm["arm"], lv, ch))
        if len(s["picked"]) > 1:
            self.ui.note("parallel  %d at a time" % s["parallel"])
        if s.get("hours"):
            self.ui.note("run time  %g h per agent  (changed from 6)" % s["hours"])
        if s.get("network", "paper") != "paper":
            self.ui.note("network   model endpoint only  (changed)")
        if s.get("hosts"):
            self.ui.note("extra     %s  (changed)" % ", ".join(s["hosts"]))
        if s["levels"] or s.get("hours") or s.get("network", "paper") != "paper" or s.get("hosts"):
            self.ui.note("Changed settings are recorded as not comparable with the official leaderboard.")
        self.ui.note("")
        self.ui.note("The same run from the command line:")
        self.ui.note("  " + " ".join(shlex.quote(x) for x in argv))
        self.ui.note("")
        self.ui.note("This run uses your model account and is billed or counted against it.")
        if problems:
            self.ui.note("Fix these first, the run would stop at the start: %s" % ", ".join(problems))
        i = self.ui.select("Ready", [("start", "start the run now"),
                                     ("back", "go back and change something"),
                                     ("quit", "leave without starting")], 1)
        if i == 1:
            raise Back()
        if i == 2:
            raise Abort("not started")
        return argv[2:]

    # ---- driver -----------------------------------------------------------------------------
    def run(self, env_file=".env", setup_file=SETUP_FILE):
        self.env_file = env_file
        self.rows = self.arms()
        self.saved = load_setup(setup_file, [a["arm"] for _, a in self.rows])
        self.jump = False
        self.ui.banner("Set up a run. Nothing starts until you choose start at the end.")
        steps = [self.step_start, self.step_mode, self.step_agents, self.step_settings,
                 self.step_effort, self.step_runtime, self.step_parallel, self.step_data,
                 self.step_review]
        history, k = [], 0
        while True:
            try:
                out = steps[k]()
            except Skip:
                k += 1
                continue
            except _Again:
                continue
            except Back:
                if not history:
                    continue
                k = history.pop()
                continue
            if k == len(steps) - 1:
                save_setup(setup_file, self.s)
                return out
            history.append(k)
            if self.jump:
                # a saved setup: go straight to the summary (or to the data step when a live run
                # still needs its data), with every earlier step one Back away
                self.jump = False
                history += [1, 2, 3]
                if self.s.get("custom"):
                    history += [4, 5] + ([6] if len(self.s["picked"]) > 1 else [])
                if not (self.s.get("task_data") and self.s.get("paper") and self.s.get("contact")):
                    k = 7
                else:
                    history.append(7)
                    k = 8
                continue
            k += 1

    def command(self):
        s = self.s
        argv = ["sciexam", "run-agent", "--agent", ",".join(a["arm"] for _, a in s["picked"])]
        if s["levels"]:
            argv += ["--effort", ",".join("%s=%s" % kv for kv in s["levels"].items())]
        if len(s["picked"]) > 1 and s["parallel"] > 1:
            argv += ["--parallel", str(s["parallel"])]
        if s["mode"] == "smoke":
            argv.append("--smoke")
        if s.get("hours") and s["mode"] != "smoke":
            argv += ["--hours", "%g" % s["hours"]]
        if s.get("network", "paper") != "paper":
            argv += ["--network", s["network"]]
        for h in s.get("hosts") or []:
            argv += ["--allow-host", h]
        if s.get("task_data"):
            argv += ["--task-data", s["task_data"]]
        if s.get("paper"):
            argv += ["--paper", s["paper"]]
        if s.get("contact"):
            argv += ["--contact", s["contact"]]
        if self.env_file != ".env":
            argv += ["--env-file", self.env_file]
        return argv


def load_setup(path, known_arms):
    """The saved setup, or None when there is none or it names an arm that no longer exists."""
    try:
        d = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not d.get("agents") or d.get("mode") not in [m[0] for m in MODES]:
        return None
    if any(a not in known_arms for a in d["agents"]):
        return None
    return d


def save_setup(path, s):
    d = {k: s[k] for k in SAVED_KEYS if k in s}
    d["agents"] = [a["arm"] for _, a in s["picked"]]
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(d, indent=1) + "\n")
    except OSError:
        pass


def setup_checks(s):
    """(what, ok, detail) for what a run needs besides the credentials: the checks of --dry-run."""
    from .. import dataset as DS
    from . import task as T
    out = []
    root = Path(DS.default_root())
    have = (root / "task").is_dir()
    out.append(("dataset", have, str(root) if have else "missing: run sciexam download"))
    try:
        r = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                           capture_output=True, text=True, timeout=20)
        ok = r.returncode == 0
        out.append(("Docker", ok, "engine %s" % r.stdout.strip() if ok else
                    "not running: start Docker Desktop (or the Docker service)"))
    except FileNotFoundError:
        out.append(("Docker", False, "not installed: https://docs.docker.com/get-docker/"))
    except subprocess.TimeoutExpired:
        out.append(("Docker", False, "did not answer in 20 s: is Docker starting?"))
    if have:
        probs = T.plan(root / "task", s.get("task_data"), s.get("paper"))[2]
        out.append(("task data and paper", not probs, "; ".join(probs) or "every file in place"))
    return out


class Skip(Exception):
    """A step that does not apply to this run."""


class _Again(Exception):
    """Ask the same step again."""


def interactive_argv(env_file=".env"):
    """Run the setup on this terminal and return the run-agent arguments, or None."""
    try:
        return Wizard(NM.RELEASED_DIR).run(env_file=env_file)
    except (Abort, KeyboardInterrupt) as e:
        print("\nnothing started (%s)" % (e or "interrupted"), file=sys.stderr)
        return None
