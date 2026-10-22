"""The seal of a run: what makes a results folder edited after its run refuse to package.

While the run goes, every checkpoint is hashed the moment it is written, and its hash is chained
to the one before it: chain_k = sha256(chain_{k-1} | round | checkpoint hash). The chain value is
logged with each snapshot event in trajectory.jsonl. When the run has ended and its containers are
down, so that no log can still grow, SEAL.json records the sha256 of every file in the results
folder and the last chain value.

`sciexam package-run` and `sciexam verify-submission` recompute both. A file changed, added or
removed after the run, or a checkpoint changed, added, removed or reordered, breaks them.

What a seal does not do: the harness is open source and runs on the submitter's machine, so a
seal can be recomputed by someone who sets out to. It stops edits after the run, accidental or
not, and makes any other change a deliberate rewrite of the harness.
"""
import hashlib
import json
import time
from pathlib import Path

GENESIS = "0" * 64
SEAL_FILE = "SEAL.json"
FORMAT = 1


def bundle_digest(files):
    """sha256 of a checkpoint given as {name: bytes}, independent of file order."""
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode() + b"\0" + hashlib.sha256(files[name]).hexdigest().encode() + b"\n")
    return h.hexdigest()


def folder_digest(folder):
    folder = Path(folder)
    return bundle_digest({p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()})


def link(prev, round_name, digest):
    return hashlib.sha256(("%s|%s|%s" % (prev, round_name, digest)).encode()).hexdigest()


def chain_of(folders):
    """The chain over checkpoint folders given in round order."""
    c = GENESIS
    for f in folders:
        c = link(c, Path(f).name, folder_digest(f))
    return c


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _files(results):
    results = Path(results)
    out = {}
    for p in sorted(results.rglob("*")):
        rel = p.relative_to(results).as_posix()
        if p.is_file() and rel != SEAL_FILE and ".tmp-" not in rel and ".superseded-" not in rel:
            out[rel] = _sha(p)
    return out


def write(results, chain):
    seal = {"format": FORMAT, "sealed_epoch": int(time.time()), "chain": chain,
            "files": _files(results)}
    (Path(results) / SEAL_FILE).write_text(json.dumps(seal, indent=1, sort_keys=True) + "\n")
    return seal


def check(results, rounds):
    """Problems with the seal of a results folder, empty when it is intact. ``rounds`` are the
    checkpoint folders in round order."""
    results = Path(results)
    try:
        seal = json.loads((results / SEAL_FILE).read_text())
    except (OSError, ValueError):
        return ["the run is not sealed (no SEAL.json): it did not finish, or an older harness wrote it"]
    probs = []
    now = _files(results)
    changed = sorted(k for k in seal.get("files", {}) if now.get(k) != seal["files"][k])
    added = sorted(set(now) - set(seal.get("files", {})))
    if changed:
        probs.append("changed or removed after the run: %s" % ", ".join(changed[:10]))
    if added:
        probs.append("added after the run: %s" % ", ".join(added[:10]))
    chain = chain_of(rounds)
    if chain != seal.get("chain"):
        probs.append("the checkpoints do not reproduce the chain sealed at the end of the run")
    logged = None
    traj = results / "trajectory.jsonl"
    if traj.exists():
        for line in traj.read_text().splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("event") == "snapshot" and ev.get("chain"):
                logged = ev["chain"]
    if logged != seal.get("chain"):
        probs.append("the chain logged with the last snapshot differs from the sealed one")
    return probs


def check_submission(sub):
    """Problems between a submission folder (sciexam package-run) and the seal it carries in
    logs/SEAL.json: each packaged checkpoint and log must have the hash the run sealed, every
    sealed checkpoint file must be there, and the checkpoints must reproduce the sealed chain."""
    sub = Path(sub)
    try:
        seal = json.loads((sub / "logs" / SEAL_FILE).read_text())
    except (OSError, ValueError):
        return ["logs/SEAL.json is missing: the run was not sealed"]
    sealed = seal.get("files", {})
    probs = []
    for p in sorted(sub.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(sub).as_posix()
        if rel.startswith("checkpoints/"):
            key = "snapshots/" + rel[len("checkpoints/"):]
        elif rel.startswith("logs/") and rel != "logs/" + SEAL_FILE:
            key = rel[len("logs/"):]
        else:
            continue
        if sealed.get(key) != _sha(p):
            probs.append("%s does not match the seal" % rel)
    for key in sealed:
        if key.startswith("snapshots/") and not (sub / ("checkpoints/" + key[len("snapshots/"):])).exists():
            probs.append("sealed checkpoint file %s is not in the submission" % key)
    rounds = sorted((d for d in (sub / "checkpoints").glob("round_*") if d.is_dir()),
                    key=lambda d: int(d.name.split("_")[1]))
    if chain_of(rounds) != seal.get("chain"):
        probs.append("the checkpoints do not reproduce the sealed chain")
    return probs[:12]
