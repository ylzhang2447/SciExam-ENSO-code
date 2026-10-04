"""Locate, fetch and verify the dataset.

The dataset is a directory laid out like a Hugging Face dataset repository (``runs.csv``,
``checkpoints.csv``, ``models/``, ``grader_obs/``, ``task/``, ``ablation/``, ``scores/``)
with a ``MANIFEST.sha256`` that lists the sha256 of every other file. Every command checks
the manifest before it uses the data.
"""
import csv
import hashlib
import os
import shutil
from pathlib import Path

MANIFEST = "MANIFEST.sha256"
# Pinned remote copy. Filled in when the dataset is published.
HF_REPO_ID = None
HF_REVISION = None


def default_root():
    return Path(os.environ.get("SCIEXAM_DATA", Path.home() / ".cache" / "sciexam" / "dataset"))


def sha256_file(path, bufsize=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(bufsize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def read_manifest(root):
    entries = {}
    with open(Path(root) / MANIFEST) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            digest, rel = line.split("  ", 1)
            entries[rel] = digest
    return entries


def write_manifest(root):
    """Write MANIFEST.sha256 for every file under ``root`` (used when building the dataset)."""
    root = Path(root)
    lines = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != MANIFEST:
            lines.append("%s  %s" % (sha256_file(p), p.relative_to(root).as_posix()))
    (root / MANIFEST).write_text("\n".join(lines) + "\n")
    return len(lines)


def verify(root):
    """Return a list of problems (empty when every file matches the manifest)."""
    root = Path(root)
    if not (root / MANIFEST).exists():
        return ["%s has no %s" % (root, MANIFEST)]
    want = read_manifest(root)
    problems = []
    for rel, digest in want.items():
        p = root / rel
        if not p.is_file():
            problems.append("missing: " + rel)
        elif sha256_file(p) != digest:
            problems.append("sha256 mismatch: " + rel)
    for p in root.rglob("*"):
        if p.is_file() and p.name != MANIFEST and p.relative_to(root).as_posix() not in want:
            problems.append("not in manifest: " + p.relative_to(root).as_posix())
    return problems


def download(local=None, root=None, revision=None):
    """Copy a local dataset directory (or fetch the pinned remote revision) into ``root``."""
    root = Path(root or default_root())
    if local:
        src = Path(local).resolve()
        problems = verify(src)
        if problems:
            raise RuntimeError("source dataset failed verification:\n  " + "\n  ".join(problems[:20]))
        if root.exists():
            shutil.rmtree(root)
        root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, root)
    else:
        if HF_REPO_ID is None:
            raise RuntimeError("no published dataset revision is pinned in this version; use --local PATH")
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=HF_REPO_ID, repo_type="dataset",
                          revision=revision or HF_REVISION, local_dir=str(root))
    problems = verify(root)
    if problems:
        raise RuntimeError("dataset failed verification:\n  " + "\n  ".join(problems[:20]))
    return root


def open_verified(root=None):
    root = Path(root or default_root())
    if not root.exists():
        raise RuntimeError("no dataset at %s. Run: sciexam download --local <path>" % root)
    problems = verify(root)
    if problems:
        raise RuntimeError("dataset at %s failed verification:\n  %s" % (root, "\n  ".join(problems[:20])))
    return root


def _convert(v):
    if v == "":
        return None
    if v in ("true", "false"):
        return v == "true"
    try:
        if any(c in v for c in ".eE") or v.lstrip("-").isdigit():
            return float(v) if not v.lstrip("-").isdigit() else int(v)
    except ValueError:
        pass
    return v


def read_table(root, rel):
    with open(Path(root) / rel, newline="") as fh:
        return [{k: _convert(v) for k, v in row.items()} for row in csv.DictReader(fh)]
