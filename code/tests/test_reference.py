"""End-to-end check of the grader: the reference model must reproduce its released scores.

Needs the dataset (``sciexam download``) and takes about a minute, so it is skipped when the
dataset is not present.
"""
import os
import sys
from pathlib import Path

import pytest

from sciexam import dataset as DS


def _root():
    try:
        root = Path(os.environ.get("SCIEXAM_DATA") or DS.default_root())
    except Exception:
        return None
    return root if (root / "runs.csv").exists() else None


@pytest.mark.skipif(_root() is None, reason="dataset not downloaded")
def test_reference_model_reproduces_its_record():
    pytest.importorskip("numba")          # the reference model is compiled with numba
    sys.dont_write_bytecode = True        # leave no cache files in the dataset
    from sciexam.grader import obs as O
    from sciexam.grader.score import LocalModel, grade
    from sciexam.grader.worker import load_submission

    root = _root()
    ref = [r for r in DS.read_table(root, "runs.csv") if r["group"] == "reference"][0]
    cwd = os.getcwd()
    try:
        model = load_submission(str(root / ref["model_dir"]))
    finally:
        os.chdir(cwd)
    r = grade(LocalModel(model), O.load(root / "grader_obs"), s=float(ref["calendar_offset"]))
    for k in ("statistics", "physics", "predictivity", "composite"):
        assert abs(r[k] - ref["final_" + k]) < 5e-5, (k, r[k], ref["final_" + k])
