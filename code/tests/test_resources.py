"""The compute spec of an agent: the container cap, the capacity check and the samples."""
import json
from pathlib import Path

from sciexam.agent import config as C
from sciexam.agent import docker_env as D
from sciexam.agent import resources as R

AGENTS = Path(__file__).resolve().parents[1] / "agents"
FORMAL = {"cpus": 16, "memory_gb": 30.81}


def test_the_formal_host_holds_three_agents():
    assert R.fit(FORMAL) == 3
    assert R.fit({"cpus": 8, "memory_gb": 15.6}) == 1          # a common laptop: one at a time
    assert R.fit({"cpus": 12, "memory_gb": 9.7}) == 1          # Docker Desktop set to 10 GB
    assert R.fit({"cpus": 4, "memory_gb": 64}) == 0 and R.fit(None) == 0


def test_problems_name_what_is_short(tmp_path):
    assert R.problems(FORMAL, 3, tmp_path) == [] or "GB free" in R.problems(FORMAL, 3, tmp_path)[0]
    probs = R.problems({"cpus": 8, "memory_gb": 15.6}, 2, tmp_path)
    assert any("holds 1 agent(s) at once, not 2" in p for p in probs)
    assert "Docker does not answer" in R.problems(None, 1, tmp_path)[0]


def test_every_agent_container_is_capped(tmp_path):
    arm = C.load_arm(AGENTS / "kimi.yaml")
    n = D.Names("sx", "k1")
    paths = {"workspace": str(tmp_path / "ws"), "ctr_workspace": "/work", "proxy_log_dir": str(tmp_path),
             "gateway_config": str(tmp_path / "g.yaml"), "allowlist": str(tmp_path / "a.txt")}
    try:
        cmds = D.up_commands(arm, "sx", n, paths, tmp_path / "proxy.py")
    except KeyError as e:                       # paths this test does not need to model
        raise AssertionError("up_commands needs path %s" % e)
    agent = [argv for label, argv, _ in cmds if label.startswith("start agent")][0]
    i = agent.index("--cpus")
    assert agent[i:i + 6] == ["--cpus", "5", "--memory", "10g", "--memory-swap", "10g"]


def test_summary_of_the_samples():
    lines = [json.dumps({"t": 0, "cpu": "12.5%", "memory_pct": "4.0%", "disk_free_gb": 20.0}),
             json.dumps({"t": 60, "cpu": "480.0%", "memory_pct": "61.2%", "disk_free_gb": 18.5}),
             json.dumps({"t": 61, "event": "end", "oom_kills": 0, "disk_free_gb": 18.4})]
    s = R.summarize(lines)
    assert s == {"samples": 2, "peak_cpu_pct": 480.0, "peak_memory_pct": 61.2,
                 "min_disk_free_gb": 18.4, "oom_kills": 0}
