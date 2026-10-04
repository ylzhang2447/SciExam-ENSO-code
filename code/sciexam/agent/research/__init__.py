"""The web research proxy of the web-access conditions.

policy.py       the decision rules, pure functions (tested offline)
addon.py        the mitmproxy addon that applies them to live traffic
guard.py        refuses all traffic unless addon.py is loaded and live
policies/       one policy per condition (literature_and_data, literature_only)
fingerprints/   hashed fingerprints of the works the task blacklist names
benchmark_self.json   the benchmark's own public pages, supplied by the user

``stage`` writes the per-run configuration folder that the proxy container mounts.
"""
import hashlib
import json
from pathlib import Path

from . import policy as R

HERE = Path(__file__).parent
POLICIES = ("literature_and_data", "literature_only")
PROXY_PORT = 8080
CA_IN_AGENT = "/usr/local/share/ca-certificates/sciexam-research-ca.crt"


def policy_path(name):
    if name not in POLICIES:
        raise ValueError("unknown research policy %r (known: %s)" % (name, ", ".join(POLICIES)))
    return HERE / "policies" / (name + ".json")


def load(name, benchmark_self=None):
    """(effective policy, works, content fingerprints) of one condition."""
    pol = R.load_json(policy_path(name))
    selfcfg = R.load_json(benchmark_self or (HERE / "benchmark_self.json"))
    return (R.effective_policy(pol, selfcfg), R.load_json(HERE / "fingerprints" / "works.json"),
            R.load_json(HERE / "fingerprints" / "content.json"))


def stage(name, task_texts, out_dir, benchmark_self=None):
    """Write policy.json, works.json, content.json and shingles.json for one run into
    ``out_dir``. ``task_texts`` are the task files of the arm's workspace (text). Returns
    {file: sha256}."""
    pol, works, content = load(name, benchmark_self)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    docs = {"policy.json": pol, "works.json": works, "content.json": content,
            "shingles.json": R.workspace_shingles(task_texts)}
    digests = {}
    for fn, doc in docs.items():
        b = (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode()
        (out / fn).write_bytes(b)
        digests[fn] = hashlib.sha256(b).hexdigest()
    return digests


ENFORCED_FILES = ("addon.py", "policy.py", "guard.py")


def expected_epoch(config_dir):
    """The enforcement epoch the addon will compute for this configuration folder (sha256 over
    the sorted map of file name -> sha256 of the configuration files and the three proxy
    scripts). The guard refuses all traffic if the addon reports another one."""
    from .policy import sha256_text
    parts = {name: Path(config_dir) / name for name in
             ("policy.json", "works.json", "content.json", "shingles.json")}
    parts.update({name: HERE / name for name in ENFORCED_FILES})
    digests = {}
    for name, path in parts.items():
        try:
            digests[name] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        except OSError:
            digests[name] = "MISSING"
    return sha256_text(json.dumps(digests, sort_keys=True))
