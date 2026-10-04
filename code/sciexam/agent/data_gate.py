"""Phase 1 gate: element-wise match of the agent's processed indices with the reference.

Runs on the host, never in the agent container. The reference is grader_obs/indices_truth.nc
of the dataset (the same file the formal gate read). Only the training period 1980-01 to
2014-12 is compared. Every training month must be present and within the tolerance of its
index. The agent is told only which indices are off and the month of the largest
discrepancy (see prompts.phase1_feedback), never a tolerance, a value or a difference.
"""
from pathlib import Path

TRAIN_START = "1980-01"
CUTOFF = "2014-12"

# Absolute tolerance per index, in the dimensional units of the index (a few percent of
# each field's standard deviation).
TOL = {
    "TC": 0.02,     # degrees C
    "TE": 0.02,     # degrees C
    "hW": 0.40,     # m
    "u": 0.006,     # m/s
    "tau": 0.05,    # m/s
}


def _truth(obs_file):
    import pandas as pd
    import xarray as xr
    d = xr.open_dataset(obs_file)
    truth = {}
    for v in TOL:
        s = d[v].to_series().dropna()
        s.index = pd.to_datetime(s.index).to_period("M")
        truth[v] = s[(s.index >= TRAIN_START) & (s.index <= CUTOFF)]
    d.close()
    return truth


def _submission(sub):
    import pandas as pd
    csv = Path(sub) / "processed" / "indices.csv"
    if not csv.exists():
        raise FileNotFoundError("missing %s" % csv)
    df = pd.read_csv(csv)
    tcol = [c for c in df.columns if c.lower() in ("time", "date", "month")][0]
    df.index = pd.to_datetime(df[tcol]).dt.to_period("M")
    return df


def _check(sub_series, truth_series, tol):
    import numpy as np
    import pandas as pd
    j = pd.concat([sub_series.rename("a"), truth_series.rename("b")], axis=1)
    n_expected = len(truth_series)
    n_present = int(j["a"].loc[truth_series.index].notna().sum())
    missing = n_expected - n_present
    aligned = j.loc[truth_series.index].dropna()
    if len(aligned) == 0:
        return dict(passed=False, note="no overlapping training months", missing_months=missing)
    diff = np.abs(aligned["a"].values - aligned["b"].values)
    imax = int(np.argmax(diff))
    max_diff = float(diff[imax])
    ok = (missing == 0) and (max_diff <= tol)
    return dict(passed=bool(ok), max_abs_diff=round(max_diff, 5), tol=tol,
                worst_month=str(aligned.index[imax]), missing_months=missing,
                n_checked=len(aligned))


def grade(submission_dir, obs_file):
    """The gate result as a dict (the same fields the formal gate wrote)."""
    result = dict(passed=False, per_index={}, notes_present=False,
                  train_period=[TRAIN_START, CUTOFF])
    result["notes_present"] = (Path(submission_dir) / "processed" / "processing_notes.md").exists()
    truth = _truth(obs_file)
    try:
        df = _submission(submission_dir)
    except Exception as e:
        result["error"] = str(e)
        return result
    checked = []
    for name, tol in TOL.items():
        if name not in df.columns:
            result["per_index"][name] = dict(passed=False, note="absent from submission")
            checked.append(False)
            continue
        try:
            r = _check(df[name], truth[name], tol)
        except Exception as e:
            r = dict(passed=False, note="could not compare: %s" % e)
        result["per_index"][name] = r
        checked.append(r["passed"])
    result["passed"] = all(checked) and result["notes_present"]
    return result
