"""The files an agent receives, assembled from the dataset and the user's own downloads."""
import shutil
from pathlib import Path

from .provenance import DATA_FILES, NOT_GIVEN_TO_AGENTS, PAPER_FILE, TASK_FILES_SHA256
from ..dataset import sha256_file

# Copied from dataset/task/ into the workspace root, as the formal harness did.
TASK_TEXT_FILES = ("instruction.md", "data_processing.md", "interface.md",
                   "nondim_scales.json", "blacklist.txt", "papers/README.md")


def plan(task_dir, data_dir=None, paper=None):
    """List what goes into the workspace: (relative path, source, sha256, formal sha256)."""
    task_dir = Path(task_dir)
    items, problems = [], []
    for rel in TASK_TEXT_FILES:
        src = task_dir / rel
        if not src.exists():
            problems.append("dataset task file missing: %s" % rel)
            continue
        items.append((rel, src))
    for name in DATA_FILES:
        src = Path(data_dir) / name if data_dir else None
        if src is None or not src.exists():
            problems.append("raw data file missing: data/%s (rebuild with "
                            "sciexam prepare-data --keep-raw, which writes them to OUT/raw, then pass --task-data OUT/raw)" % name)
            continue
        items.append(("data/" + name, src))
    if paper and Path(paper).exists():
        items.append(("papers/" + PAPER_FILE, Path(paper)))
    else:
        problems.append("reference paper missing: papers/%s (obtain Jin 1997 from its "
                        "publisher, see task/papers/CITATION.md, then pass --paper PATH)"
                        % PAPER_FILE)
    rows = []
    for rel, src in items:
        sha = sha256_file(src)
        rows.append(dict(path=rel, source=str(src), sha256=sha,
                         formal_sha256=TASK_FILES_SHA256.get(rel),
                         same_as_formal=(sha == TASK_FILES_SHA256.get(rel))))
    excluded = []
    for p in sorted(task_dir.rglob("*")):
        if p.is_file():
            rel = p.relative_to(task_dir).as_posix()
            if rel not in TASK_TEXT_FILES:
                excluded.append(rel)
    return rows, excluded, problems


def reference_paper(rows):
    """Which paper the agent read: the formal PDF or another rendering of it."""
    p = {r["path"]: r for r in rows}.get("papers/" + PAPER_FILE)
    if not p:
        return {"kind": "none"}
    return {"kind": "formal_pdf" if p["same_as_formal"] else "other_pdf", "sha256": p["sha256"]}


def task_data(rows):
    """Whether the four observation files are those of the formal runs or rebuilt ones."""
    data = [r for r in rows if r["path"].startswith("data/")]
    ok = bool(data) and all(r["same_as_formal"] for r in data)
    return {"kind": "formal" if ok else "rebuilt",
            "differs": sorted(r["path"] for r in data if not r["same_as_formal"])}


def inputs_note(paper, data):
    """What a run's inputs change from the formal runs, for its leaderboard name."""
    notes = []
    if paper.get("kind") == "other_pdf":
        notes.append("other PDF")
    if data.get("kind") == "rebuilt":
        notes.append("rebuilt data")
    return notes


def install(rows, workspace):
    """Copy the planned files into the workspace (after it was cleared)."""
    ws = Path(workspace)
    for r in rows:
        dst = ws / r["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(r["source"], dst)


def excluded_reason(rel):
    for p in NOT_GIVEN_TO_AGENTS:
        if rel == p or (p.endswith("/") and rel.startswith(p)):
            return "never in an agent workspace"
    return "not part of the agent task"
