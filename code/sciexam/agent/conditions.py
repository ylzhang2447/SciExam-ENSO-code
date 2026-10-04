"""The Claude Fable 5.1 condition runs: how each derives its task tree from the main inputs.

An arm config with a ``condition:`` block (agents/fable51_<condition>.yaml) reruns the
offline Claude Fable 5.1 arm with one condition changed. The block names four things, and
``load_arm`` checks that nothing else differs from the baseline arm:

task_tree        how the workspace files are derived from the dataset task text and the raw
                 data (TASK_TREES below)
network          ``allowlist`` (the egress proxy of every arm) or ``research`` (the web
                 research proxy of sciexam/agent/research, with TLS interception)
research_policy  the research policy (``literature_and_data`` or ``literature_only``)
undenied_tools   tools removed from the baseline arm's --disallowedTools list

Task trees:

years_anonymised         calendar years replaced by relative labels, product names removed,
                         data files renamed and rewritten with a shifted epoch
                         (sciexam/agent/anonymise.py). Phase 1 is graded through the label map.
web_literature_and_data  instruction.md: the sandbox rule is scoped to the local file system
                         and a web research section is appended, the version that allows
                         data sources
web_literature_only      the same sandbox rule and the web research section of the version
                         that tells the agent data sources are refused
"""
import difflib
import hashlib
import shutil
import tempfile
from pathlib import Path

from . import anonymise as A
from .provenance import CONDITION_FILES_SHA256, CONDITION_TREE_SHA256, DATA_FILES, PAPER_FILE
from .task import TASK_TEXT_FILES
from ..dataset import sha256_file

ASSETS = Path(__file__).parent / "assets" / "conditions"
TASK_TREES = ("years_anonymised", "web_literature_and_data", "web_literature_only")
NETWORKS = ("allowlist", "research")

# The sandbox rule of instruction.md that both web conditions replace.
SANDBOX_RULE = (
    "- **Stay inside this sandbox directory.** Everything you need is here. Do not read,\n"
    "  search for, or use any files elsewhere on the machine, in particular any grader,\n"
    "  scoring code, reference model, reference implementation, or observation/truth file\n"
    "  outside this sandbox. Build the model only from the provided task files, the reference\n"
    "  paper, and your own processed data. Accessing hidden grading or reference material\n")
INSTRUCTION_END = "  invalidates the run.\n"


class ConditionError(RuntimeError):
    pass


def web_instruction(task_dir, tree):
    """instruction.md of a web condition: the sandbox rule replaced by
    assets/conditions/web_sandbox_rule.md and assets/conditions/<tree>.md appended."""
    s = (Path(task_dir) / "instruction.md").read_text(encoding="utf-8")
    if s.count(SANDBOX_RULE) != 1 or not s.endswith(INSTRUCTION_END):
        raise ConditionError("instruction.md does not have the expected sandbox rule and ending")
    rule = (ASSETS / "web_sandbox_rule.md").read_text(encoding="utf-8")
    section = (ASSETS / (tree + ".md")).read_text(encoding="utf-8")
    return s.replace(SANDBOX_RULE, rule, 1) + section


def edited_texts(tree, task_dir):
    """{relative path: new text} for the task text files the condition changes."""
    if tree == "years_anonymised":
        return A.edit_texts(task_dir)
    if tree in ("web_literature_and_data", "web_literature_only"):
        return {"instruction.md": web_instruction(task_dir, tree)}
    raise ConditionError("unknown task tree %r" % tree)


def task_texts(tree, task_dir):
    """The task text files as the condition's workspace has them, {relative path: text}."""
    edited = edited_texts(tree, task_dir)
    return {rel: edited.get(rel) or (Path(task_dir) / rel).read_text(encoding="utf-8")
            for rel in TASK_TEXT_FILES}


def text_diff(tree, task_dir):
    """Unified diff of every changed task text file against the dataset task text."""
    out = []
    for rel, new in sorted(edited_texts(tree, task_dir).items()):
        old = (Path(task_dir) / rel).read_text(encoding="utf-8")
        out += difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                    "dataset/task/" + rel, "workspace/" + rel, n=1)
    return "".join(out)


def data_names(tree):
    """Raw data file -> name in the workspace data/ folder."""
    if tree == "years_anonymised":
        return dict(A.RENAME)
    return {n: n for n in DATA_FILES}


def formal_sha256(tree, rel):
    """sha256 of this workspace file in the condition's formal run, if recorded."""
    return CONDITION_FILES_SHA256.get(tree, {}).get(rel)


def build(tree, task_dir, data_dir, paper, out_dir):
    """Write the condition's task files into ``out_dir`` and plan the workspace.

    Returns (rows, problems, manifest). ``rows`` have the shape of task.plan rows (path,
    source, sha256, formal_sha256, same_as_formal). Missing raw data or paper are listed in
    ``problems``; the text files are always built.
    """
    task_dir, out_dir = Path(task_dir), Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    problems, manifest = [], {"task_tree": tree}
    names = data_names(tree)
    have_data = bool(data_dir) and all((Path(data_dir) / n).exists() for n in names)
    for n in names:
        if not (data_dir and (Path(data_dir) / n).exists()):
            problems.append("raw data file missing: %s (sciexam prepare-data --keep-raw, then "
                            "--task-data OUT/raw)" % n)
    if tree == "years_anonymised" and have_data:
        manifest["anonymisation"] = A.build(task_dir, data_dir, out_dir, TASK_TEXT_FILES)
    else:
        edited = edited_texts(tree, task_dir)
        for rel in TASK_TEXT_FILES:
            dst = out_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if rel in edited:
                dst.write_text(edited[rel], encoding="utf-8")
            else:
                shutil.copyfile(task_dir / rel, dst)
    if tree == "years_anonymised":
        manifest["text_leaks"] = A.instruction_leaks(out_dir, TASK_TEXT_FILES)
        if manifest["text_leaks"]:
            raise ConditionError("observation years or product names left in the task text: %s"
                                 % manifest["text_leaks"])
    items = [(rel, out_dir / rel) for rel in TASK_TEXT_FILES]
    if have_data:
        # The anonymised files are the ones just written; the web trees use the raw files.
        items += [("data/" + d, out_dir / "data" / d if tree == "years_anonymised"
                   else Path(data_dir) / s_) for s_, d in names.items()]
    if paper and Path(paper).exists():
        items.append(("papers/" + PAPER_FILE, Path(paper)))
    else:
        problems.append("reference paper missing: papers/%s (see task/papers/CITATION.md, "
                        "then --paper PATH)" % PAPER_FILE)
    rows = []
    for rel, src in items:
        sha = sha256_file(src)
        f = formal_sha256(tree, rel)
        rows.append(dict(path=rel, source=str(src), sha256=sha, formal_sha256=f,
                         same_as_formal=(sha == f)))
    manifest["planned_data"] = {"data/" + d: s for s, d in names.items()}
    return rows, problems, manifest


def tree_sha256(rows):
    """The task tree hash of the formal harness: sha256 of the sorted 'path sha256' lines."""
    return hashlib.sha256("\n".join("%s %s" % (r["path"], r["sha256"])
                                    for r in sorted(rows, key=lambda r: r["path"]))
                          .encode()).hexdigest()


def formal_tree_sha256(tree):
    return CONDITION_TREE_SHA256.get(tree)


def dry_build(tree, task_dir, data_dir, paper):
    """``build`` into a temporary folder that is removed afterwards (for --dry-run)."""
    tmp = Path(tempfile.mkdtemp(prefix="sciexam-condition-"))
    try:
        rows, problems, manifest = build(tree, task_dir, data_dir, paper, tmp / "tree")
        for r in rows:
            if r["source"].startswith(str(tmp)):
                r["source"] = "(built) " + r["path"]
        return rows, problems, manifest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def summary(arm):
    """The condition block of an arm config, as recorded in run_meta."""
    c = arm.get("condition")
    if not c:
        return None
    return {k: c.get(k) for k in ("name", "description", "baseline_arm", "task_tree", "network",
                                  "research_policy", "undenied_tools")}
