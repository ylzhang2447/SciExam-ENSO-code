"""Interactive setup of `sciexam run-agent`.

`sciexam run-agent` without --agent, on a terminal, shows the logo and asks for the run one step
at a time: the mode, the agents, the reasoning effort of each, the settings (the paper's, or
custom run time and network), how many agents run at once, and the task data and paper for a
live run. It then checks the credentials (set or missing, never their values), shows a summary
and the equivalent command line, and starts only when asked to. Every step can go back to the
one before it. The prompts come from `tui`: arrow-key menus on a terminal, numbered choices
elsewhere.
"""
import shlex
import sys
from pathlib import Path

from . import config as C
from . import custom as X
from . import effort as E
from .tui import Abort, Back, Plain, backend

MODES = [
    ("dry-run", "check the setup only. Starts nothing, free"),
    ("smoke", "15-minute check of containers, credentials and network. Uses your account"),
    ("full", "the benchmark run, 6 h per agent by default. Uses your account"),
]
NETWORK_CHOICES = [
    ("paper", "the model endpoint and PyPI, as in the paper"),
    ("no-pypi", "the model endpoint only, no package installs"),
    ("extra", "the paper's setting plus hosts you name"),
]


class Wizard:
    def __init__(self, agents_dir, ui=None):
        self.agents_dir = Path(agents_dir)
        self.ui = ui or backend()
        self.s = {}

    # ---- data -------------------------------------------------------------------------------
    def arms(self):
        rows = [(p, C.load_arm(p)) for p in sorted(self.agents_dir.glob("*.yaml"))]
        rows.sort(key=lambda r: (bool(r[1].get("condition")), r[0].stem))
        return rows

    # ---- steps: each reads and writes self.s, and raises Back to return to the previous one --
    def step_mode(self):
        self.ui.heading("Mode")
        self.s["mode"] = MODES[self.ui.select("How do you want to run", MODES,
                                              [m[0] for m in MODES].index(self.s.get("mode", "dry-run")))][0]

    def step_agents(self):
        self.ui.heading("Agents")
        rows = self.rows
        opts = []
        for p, arm in rows:
            tag = "condition run" if arm.get("condition") else arm["route"]["kind"]
            opts.append((arm["arm"], "%-20s %-12s %s" % (arm.get("display_name") or "",
                                                          arm["scaffold"]["name"], tag)))
        default = self.s.get("picked_idx", [0])
        idx = self.ui.multiselect("Which agents", opts, default,
                                  names=[a["arm"] for _, a in rows])
        self.s["picked_idx"] = idx
        self.s["picked"] = [rows[i] for i in idx]

    def step_effort(self):
        self.ui.heading("Reasoning effort")
        self.ui.note("The paper's level is preselected. Another level is recorded as not "
                     "comparable with the paper.")
        levels = dict(self.s.get("levels", {}))
        picked = self.s["picked"]
        k = 0
        while k < len(picked):
            arm = picked[k][1]
            paper = arm["reasoning"]["effort"]
            opts = E.options(arm)
            choices = [(lv, "paper" if lv == paper else "") for lv in opts]
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

    def step_settings(self):
        self.ui.heading("Settings")
        cur = 1 if self.s.get("custom") else 0
        i = self.ui.select("Run settings", [("paper", "the paper's run time and network"),
                                            ("custom", "change the run time or the network")], cur)
        self.s["custom"] = i == 1
        if not self.s["custom"]:
            self.s.update(hours=None, network="paper", hosts=[])
            return
        self._custom()

    def _custom(self):
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
                        h = self.ui.text("Run time per agent in hours (paper: 6)",
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
        self.ui.heading("Parallel runs")
        opts = [(str(k), "agent at a time" if k == 1 else "agents at a time") for k in range(1, n + 1)]
        self.s["parallel"] = self.ui.select("How many run at the same time", opts,
                                            self.s.get("parallel", 1) - 1) + 1

    def step_data(self):
        if self.s["mode"] == "dry-run":
            self.s.update(task_data=None, paper=None)
            raise Skip()
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
                else:
                    self.s["paper"] = self.ui.text(
                        "Path to the Jin (1997) PDF (sciexam fetch-paper explains how to get it)",
                        self.s.get("paper") or "",
                        lambda v: None if v and Path(v).is_file() else "no such file: %s" % (v or "(empty)"))
                    return
            except Back:
                if sub == 0:
                    raise
                sub -= 1

    def step_review(self):
        s = self.s
        self.ui.heading("Credentials")
        env_values = C.read_env_file(self.env_file)
        missing = []
        for name, what in sorted({c for _, a in s["picked"] for c in C.required_credentials(a)}):
            ok = bool(C.credential(name, env_values))
            self.ui.note("%-26s %-8s %s" % (name, "set" if ok else "MISSING", what))
            if not ok:
                missing.append(name)

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
            self.ui.note("Changed settings are recorded as not comparable with the paper.")
        self.ui.note("")
        self.ui.note("The same run from the command line:")
        self.ui.note("  " + " ".join(shlex.quote(x) for x in argv))
        if s["mode"] != "dry-run":
            self.ui.note("")
            self.ui.note("This run uses your model account and is billed or counted against it.")
            if missing:
                self.ui.note("Credentials are missing (%s), so it would stop at the start."
                             % ", ".join(missing))
        live = s["mode"] != "dry-run"
        i = self.ui.select("Ready", [("start", "start the run now"),
                                     ("back", "go back and change something"),
                                     ("quit", "leave without starting")], 1 if live else 0)
        if i == 1:
            raise Back()
        if i == 2:
            raise Abort("not started")
        return argv[2:]

    # ---- driver -----------------------------------------------------------------------------
    def run(self, env_file=".env"):
        self.env_file = env_file
        self.rows = self.arms()
        self.ui.banner("Set up a run. Nothing starts until you choose start at the end.")
        steps = [self.step_mode, self.step_agents, self.step_effort, self.step_settings,
                 self.step_parallel, self.step_data, self.step_review]
        history, k = [], 0
        while True:
            try:
                out = steps[k]()
            except Skip:
                k += 1
                continue
            except Back:
                if not history:
                    continue
                k = history.pop()
                continue
            if k == len(steps) - 1:
                return out
            history.append(k)
            k += 1

    def command(self):
        s = self.s
        argv = ["sciexam", "run-agent", "--agent", ",".join(a["arm"] for _, a in s["picked"])]
        if s["levels"]:
            argv += ["--effort", ",".join("%s=%s" % kv for kv in s["levels"].items())]
        if len(s["picked"]) > 1 and s["parallel"] > 1:
            argv += ["--parallel", str(s["parallel"])]
        if s["mode"] == "dry-run":
            argv.append("--dry-run")
        elif s["mode"] == "smoke":
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
        if self.env_file != ".env":
            argv += ["--env-file", self.env_file]
        return argv


class Skip(Exception):
    """A step that does not apply to this run."""


def interactive_argv(agents_dir, env_file=".env"):
    """Run the setup on this terminal and return the run-agent arguments, or None."""
    try:
        return Wizard(agents_dir).run(env_file=env_file)
    except (Abort, KeyboardInterrupt) as e:
        print("\nnothing started (%s)" % (e or "interrupted"), file=sys.stderr)
        return None
