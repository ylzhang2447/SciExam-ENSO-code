"""The compute each agent gets: fixed by a cap on its container, checked before a run, recorded
during it.

The formal runs shared one host of 16 vCPUs and 30 GB among at most three agents at a time, with
no cap on the agent container. Each agent's share of that host, about 5 CPUs and 10 GB, is the
spec here, and it is enforced as a cap so that running several agents at once on any machine
gives each the same compute:

    cap          every agent container runs with --cpus 5 --memory 10g (no swap beyond it)
    capacity     before a run Docker's CPUs and memory must hold one cap per agent running at
                 once, and the disk of the run folders must have room for their results
    record       run_meta.json records the spec, the host and how many agents ran at once, and
                 resources.jsonl samples the agent container (CPU, memory, processes) and the free
                 disk every minute, ending with the kernel's count of out-of-memory kills in it.
                 Both lie in the results folder, so the seal covers them.

The disk figures are planning figures: a formal run left about 0.6 GB of results, and the one
formal run lost to a resource was stopped by a full disk.
"""
import json
import math
import shutil
import subprocess
import threading
import time
from pathlib import Path

AGENT_CPUS = 5
AGENT_MEMORY_GB = 10
MEMORY_SLACK = 1.05        # Docker reports a little less than the memory it was given
DISK_BASE_GB = 5
DISK_PER_AGENT_GB = 2
SAMPLE_S = 60
SAMPLE_FILE = "resources.jsonl"


def spec():
    return {"cpus": AGENT_CPUS, "memory_gb": AGENT_MEMORY_GB,
            "basis": "the share of each of up to 3 agents on the formal 16 vCPU / 30 GB host"}


def docker_flags():
    mem = "%dg" % AGENT_MEMORY_GB
    return ["--cpus", str(AGENT_CPUS), "--memory", mem, "--memory-swap", mem]


def host():
    """Docker's CPUs and memory, or None when Docker does not answer."""
    try:
        r = subprocess.run(["docker", "info", "--format", "{{json .}}"], capture_output=True,
                           text=True, timeout=20)
        d = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if not d or not d.get("NCPU"):
        return None
    return {"cpus": int(d["NCPU"]), "memory_gb": round(d.get("MemTotal", 0) / 2 ** 30, 2),
            "docker": d.get("ServerVersion"), "os": d.get("OperatingSystem"),
            "arch": d.get("Architecture")}


def fit(h):
    """How many agents the host holds at once, each with its full cap."""
    if not h:
        return 0
    return max(0, min(h["cpus"] // AGENT_CPUS,
                      int(math.floor(h["memory_gb"] * MEMORY_SLACK / AGENT_MEMORY_GB))))


def disk_free_gb(path):
    p = Path(path).resolve()
    while not p.exists():
        p = p.parent
    return round(shutil.disk_usage(p).free / 2 ** 30, 1)


def disk_needed_gb(agents):
    return DISK_BASE_GB + DISK_PER_AGENT_GB * agents


def problems(h, agents, run_dir):
    """What keeps ``agents`` runs at once from starting on this machine (empty when nothing)."""
    out = []
    if h is None:
        return ["Docker does not answer: start Docker Desktop (or the Docker service)"]
    if fit(h) < agents:
        out.append("Docker has %d CPUs and %.1f GB of memory, and each agent needs %d CPUs and %d GB, "
                   "so it holds %d agent(s) at once, not %d. Run fewer at once, or give Docker more "
                   "(Docker Desktop: Settings > Resources)"
                   % (h["cpus"], h["memory_gb"], AGENT_CPUS, AGENT_MEMORY_GB, fit(h), agents))
    free, need = disk_free_gb(run_dir), disk_needed_gb(agents)
    if free < need:
        out.append("%.1f GB free on the disk of %s, %d GB needed for %d agent(s)"
                   % (free, run_dir, need, agents))
    return out


def record(h, agents, run_dir):
    return {"spec": spec(), "host": h, "agents_at_once": agents,
            "disk_free_gb_at_start": disk_free_gb(run_dir)}


def _oom_kills(container):
    """The kernel's count of out-of-memory kills in the container (cgroup v2, else v1), or None."""
    for path, key in (("/sys/fs/cgroup/memory.events", "oom_kill"),
                      ("/sys/fs/cgroup/memory/memory.oom_control", "oom_kill")):
        try:
            r = subprocess.run(["docker", "exec", container, "cat", path], capture_output=True,
                               text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[0] == key:
                    return int(parts[1])
    return None


class Sampler:
    """Appends one line per minute to results/resources.jsonl while the agent works."""

    def __init__(self, container, res_dir, interval=SAMPLE_S):
        self.container, self.path, self.interval = container, Path(res_dir) / SAMPLE_FILE, interval
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._t.start()
        return self

    def _write(self, rec):
        with open(self.path, "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    def sample(self):
        rec = {"t": int(time.time()), "disk_free_gb": disk_free_gb(self.path.parent)}
        try:
            r = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}",
                                self.container], capture_output=True, text=True, timeout=30)
            s = json.loads(r.stdout.strip().splitlines()[0]) if r.returncode == 0 else {}
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            s = {}
        rec.update(cpu=s.get("CPUPerc"), memory=s.get("MemUsage"), memory_pct=s.get("MemPerc"),
                   pids=s.get("PIDs"))
        self._write(rec)

    def _loop(self):
        while not self._stop.wait(self.interval):
            self.sample()

    def stop(self):
        """Stop sampling and write the closing line: the out-of-memory kills in the container."""
        self._stop.set()
        self._t.join(timeout=60)
        self._write({"t": int(time.time()), "event": "end", "oom_kills": _oom_kills(self.container),
                     "disk_free_gb": disk_free_gb(self.path.parent)})


def summarize(lines):
    """Peak CPU and memory, the lowest free disk and the out-of-memory kills of resources.jsonl."""
    def pct(v):
        try:
            return float(str(v).rstrip("%"))
        except ValueError:
            return None
    cpu, mem, disk, oom, n = [], [], [], None, 0
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("event") == "end":
            oom = r.get("oom_kills")
        else:
            n += 1
            for v, acc in ((pct(r.get("cpu")), cpu), (pct(r.get("memory_pct")), mem)):
                if v is not None:
                    acc.append(v)
        if r.get("disk_free_gb") is not None:
            disk.append(r["disk_free_gb"])
    return {"samples": n, "peak_cpu_pct": max(cpu) if cpu else None,
            "peak_memory_pct": max(mem) if mem else None,
            "min_disk_free_gb": min(disk) if disk else None, "oom_kills": oom}
