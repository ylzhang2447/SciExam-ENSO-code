"""The condition runs: arm configs, the year-anonymised task tree and its Phase 1 gate.

The anonymisation tests build small raw files of the same layout as the four data files (the
monthly SST in the layout of the files the agents received, the other three as
``sciexam prepare-data`` writes them) and task text that carries every edited passage.
"""
import json
import re
from pathlib import Path

import numpy as np
import pytest

from sciexam.agent import anonymise as A
from sciexam.agent import conditions as K
from sciexam.agent import config as C
from sciexam.agent.task import TASK_TEXT_FILES

ROOT = Path(__file__).resolve().parents[1]
CONDITIONS = ("years_anonymised", "web_literature_and_data", "web_literature_only")


# ---- arm configs ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", CONDITIONS)
def test_condition_config_loads(name):
    arm = C.load_arm(ROOT / "agents" / ("fable51_%s.yaml" % name))
    base = C.load_arm(ROOT / "agents" / "fable51.yaml")
    c = arm["condition"]
    assert c["name"] == name and c["task_tree"] == name and c["baseline_arm"] == "fable51"
    assert arm["route"] == base["route"] and arm["scaffold"] == base["scaffold"]
    web = name.startswith("web_")
    assert c["network"] == ("research" if web else "allowlist")
    assert c["undenied_tools"] == (["WebFetch"] if web else [])
    assert ("WebFetch" in arm["tools"]["disallowed"]) is not web
    assert len(arm["tools"]["disallowed"]) == (34 if web else 35)
    assert c["research_policy"] == {"years_anonymised": None,
                                    "web_literature_and_data": "literature_and_data",
                                    "web_literature_only": "literature_only"}[name]


def _variant(tmp_path, name, old, new):
    src = (ROOT / "agents" / ("fable51_%s.yaml" % name)).read_text()
    assert old in src
    d = tmp_path / "agents"
    d.mkdir(exist_ok=True)
    (d / "fable51.yaml").write_text((ROOT / "agents" / "fable51.yaml").read_text())
    p = d / ("fable51_%s.yaml" % name)
    p.write_text(src.replace(old, new, 1))
    return p


def test_condition_config_must_match_its_baseline(tmp_path):
    p = _variant(tmp_path, "web_literature_only", "  effort: medium", "  effort: high")
    with pytest.raises(C.ConfigError, match="reasoning differs"):
        C.load_arm(p)
    p = _variant(tmp_path, "web_literature_only", "undenied_tools: [WebFetch]",
                 "undenied_tools: [WebFetch, Skill]")
    with pytest.raises(C.ConfigError, match="baseline list without"):
        C.load_arm(p)
    p = _variant(tmp_path, "years_anonymised", "network: allowlist", "network: research")
    with pytest.raises(C.ConfigError, match="research_policy"):
        C.load_arm(p)


# ---- fixtures ------------------------------------------------------------------------------

def _task_dir(path):
    """Task text holding every passage the anonymisation edits, plus years it must keep."""
    path.mkdir()
    dp = "\n\n".join(b for f, b, _a in A.TEXT_EDITS if f == "data_processing.md")
    dp = dp.replace(A.TEXT_EDITS[0][1], A.TEXT_EDITS[0][1] + "\nprediction stage and are "
                    "intentionally absent; process the full provided period.\n")
    (path / "data_processing.md").write_text("# Data\n\n" + dp + "\n")
    (path / "interface.md").write_text(
        "\n\n".join(b for f, b, _a in A.TEXT_EDITS if f == "interface.md") + "\n")
    (path / "instruction.md").write_text("Read the provided reference paper (Jin 1997).\n")
    (path / "blacklist.txt").write_text("Vialard et al. (2025), Reviews of Geophysics "
                                        "(10.1029/2024RG000843)\n")
    (path / "nondim_scales.json").write_text("{}\n")
    (path / "papers").mkdir()
    (path / "papers" / "README.md").write_text("- Jin_1997_Recharge.pdf\n  Jin, F.-F. (1997).\n")
    return path


def _raw_dir(path):
    """Four small files over 1980-01 to 2014-12: SST as the agents received it (days since
    1800, product attributes), the others as prepare-data writes them."""
    import netCDF4
    import pandas as pd
    import xarray as xr
    path.mkdir()
    months = pd.date_range("1980-01-01", "2014-12-01", freq="MS")
    with netCDF4.Dataset(str(path / "ersst_sst.nc"), "w") as d:
        d.createDimension("time", None)
        d.createDimension("lat", 2)
        d.createDimension("lon", 3)
        t = d.createVariable("time", "f8", ("time",))
        t.units = "days since 1800-01-01 00:00:00"
        t.actual_range = np.array([19723.0, 82696.0])
        t[:] = netCDF4.date2num(months.to_pydatetime(), t.units)
        v = d.createVariable("sst", "f4", ("time", "lat", "lon"), fill_value=-9.96921e36)
        v.dataset = "NOAA Extended Reconstructed SST V5"
        v.long_name = "Monthly Means of Sea Surface Temperature"
        v[:] = np.random.default_rng(0).standard_normal((len(months), 2, 3))
    rng = np.random.default_rng(1)
    for name, var, times in (("godas_pottmp.nc", "pottmp", months),
                             ("godas_ucur.nc", "ucur", months),
                             ("ncep_uwnd850.nc", "uwnd",
                              pd.date_range("1980-01-01", "2014-12-31", freq="D"))):
        ds = xr.Dataset({var: (("time", "lat"), rng.standard_normal((len(times), 2))
                               .astype("float32"))},
                        coords={"time": times, "lat": [-1.0, 1.0]})
        ds.attrs["source"] = "https://psl.noaa.gov/thredds/dodsC/Datasets/example.nc"
        ds.to_netcdf(path / name)
    return path


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    base = tmp_path_factory.mktemp("anon")
    task, raw = _task_dir(base / "task"), _raw_dir(base / "raw")
    trees = []
    for i in (1, 2):
        out = base / ("tree%d" % i)
        man = A.build(task, raw, out, TASK_TEXT_FILES)
        trees.append((out, man))
    return task, raw, trees


def _hashes(tree):
    return {p.relative_to(tree).as_posix(): A.sha256_file(p)
            for p in sorted(tree.rglob("*")) if p.is_file()}


# ---- anonymisation -------------------------------------------------------------------------

def test_anonymisation_is_deterministic(built):
    _task, _raw, [(t1, m1), (t2, m2)] = built
    assert _hashes(t1) == _hashes(t2)
    assert sorted(_hashes(t1)) == sorted(list(TASK_TEXT_FILES) + [
        "data/" + n for n in A.RENAME.values()])
    assert m1 == m2


def test_no_real_year_or_product_remains(built):
    import netCDF4
    _task, _raw, [(tree, _man), _] = built
    for rel in TASK_TEXT_FILES:
        text = (tree / rel).read_text()
        assert A.year_hits(text) == [], rel
        assert A.blocked_hits(text) == [], rel
    assert "Jin 1997" in (tree / "instruction.md").read_text()     # publication year kept
    assert "Y001-01" in (tree / "interface.md").read_text()
    for name in A.RENAME.values():
        path = tree / "data" / name
        assert A.blocked_hits(path.read_bytes()) == []
        with netCDF4.Dataset(str(path)) as d:
            meta = [str(d.getncattr(k)) for k in d.ncattrs()]
            for v in d.variables.values():
                meta += [str(v.getncattr(k)) for k in v.ncattrs()]
            years = {t.year for t in A._decode_times(d.variables["time"])}
        assert not any(A.year_hits(m) for m in meta), (name, meta)
        assert not any(re.search(r"\b(19[89]\d|20[0-2]\d)\b", m) for m in meta), (name, meta)
        assert min(years) == 1980 + A.YEAR_SHIFT and max(years) == 2014 + A.YEAR_SHIFT


def test_month_of_year_and_month_lengths_preserved(built):
    import netCDF4
    _task, raw, [(tree, _man), _] = built
    for src_name, dst_name in A.RENAME.items():
        with netCDF4.Dataset(str(raw / src_name)) as a, netCDF4.Dataset(str(tree / "data" / dst_name)) as b:
            ta = A._decode_times(a.variables["time"])
            tb = A._decode_times(b.variables["time"])
            assert np.array_equal(a.variables["time"][:], b.variables["time"][:])
        assert [t.month for t in ta] == [t.month for t in tb]
        assert [t.day for t in ta] == [t.day for t in tb]
        # days per calendar month, and the spacing between consecutive steps
        per_month = lambda ts: [sum(1 for t in ts if (t.year, t.month) == ym)
                                for ym in sorted({(t.year, t.month) for t in ts})]
        assert per_month(ta) == per_month(tb)
        gaps = lambda ts: [(y - x).days for x, y in zip(ts[:-1], ts[1:])]
        assert gaps(ta) == gaps(tb)
    feb29 = sum(1 for t in tb if t.month == 2 and t.day == 29)
    assert feb29 == 9                                   # 1980, 1984, ... 2012 shifted


def test_anonymised_text_edits_and_label_map(built):
    task, raw, [(tree, man), _] = built
    assert man["text_edits"] == len(A.TEXT_EDITS) + 1
    dp = (tree / "data_processing.md").read_text()
    assert A.CAL_NOTE in dp and "Y002-01 to\nY031-12 base period" in dp
    M = A.time_map(raw / "ersst_sst.nc")
    assert M["n_months"] == 420 and (M["anon_first"], M["anon_last"]) == ("Y001-01", "Y035-12")
    assert M["anon_to_real"]["Y006-03"] == "1985-03"
    assert M["synthetic_to_real"]["2229-03"] == "1985-03"


# ---- Phase 1 gate --------------------------------------------------------------------------

def _submission(path, labels):
    sub = path / "submission"
    (sub / "processed").mkdir(parents=True)
    rows = ["time,TC,TE,hW,u,tau"] + ["%s,0.1,0.2,0.3,0.4,0.5" % t for t in labels]
    (sub / "processed" / "indices.csv").write_text("\n".join(rows) + "\n")
    (sub / "processed" / "processing_notes.md").write_text("notes\n")
    return sub


def test_gate_translates_labels_and_maps_the_result_back(built, tmp_path):
    _task, raw, _trees = built
    M = A.time_map(raw / "ersst_sst.nc")
    seen = {}

    def grade(sub, obs):
        text = (Path(sub) / "processed" / "indices.csv").read_text()
        seen["first"] = text.splitlines()[1].split(",")[0]
        return {"passed": False, "notes_present": True, "train_period": ["1980-01", "2014-12"],
                "per_index": {"TC": {"passed": False, "worst_month": "1985-03", "tol": 0.02},
                              "TE": {"passed": True}}}

    sub = _submission(tmp_path, list(M["anon_to_real"]))
    r = A.gate(sub, None, M, tmp_path / "private", grade)
    assert seen["first"] == "1980-01"                       # the grader saw real months
    assert r["passed"] is False and r["train_period"] == ["Y001-01", "Y035-12"]
    assert r["feedback"] == ("PHASE 1 NOT PASSED. Off indices: TC (largest discrepancy "
                             "near Y006-03).")
    assert "1985" not in json.dumps(r)
    # the synthetic months the files decode to are accepted as well
    sub2 = _submission(tmp_path / "b", list(M["synthetic_to_real"]))
    assert A.gate(sub2, None, M, tmp_path / "private", grade)["feedback"].endswith("Y006-03).")


def test_gate_rejects_real_dates_and_fails_closed(built, tmp_path):
    _task, raw, _trees = built
    M = A.time_map(raw / "ersst_sst.nc")
    sub = _submission(tmp_path, list(M["real_to_anon"]))
    r = A.gate(sub, None, M, tmp_path / "private", lambda s, o: {"passed": True})
    assert r == {"passed": False, "feedback": "PHASE 1 NOT PASSED. time labels are not in the "
                 "required Y001-01 .. Y035-12 form (420 of 420 rows)."}
    sub = _submission(tmp_path / "b", list(M["anon_to_real"]))
    leaky = lambda s, o: {"passed": False, "per_index": {"TC": {"passed": False,
                                                                "note": "gap after 2031-07-15"}}}
    r = A.gate(sub, None, M, tmp_path / "private", leaky)
    assert r == {"passed": False, "feedback": "PHASE 1 NOT PASSED. The check could not be reported."}
    r = A.gate(tmp_path / "c", None, M, tmp_path / "private", leaky)
    assert r["feedback"] == "PHASE 1 NOT PASSED. processed/indices.csv is missing."


# ---- web task text -------------------------------------------------------------------------

def _dataset_task():
    from sciexam import dataset as DS
    try:
        root = Path(DS.default_root())
    except Exception:
        return None
    return root / "task" if (root / "task" / "instruction.md").exists() else None


@pytest.mark.skipif(_dataset_task() is None, reason="needs the released dataset")
@pytest.mark.parametrize("name", CONDITIONS)
def test_condition_text_reproduces_the_formal_run(name):
    """With the released dataset, every edited text file equals the one the formal run had."""
    from sciexam.agent.provenance import CONDITION_FILES_SHA256
    import hashlib
    for rel, text in K.edited_texts(name, _dataset_task()).items():
        assert hashlib.sha256(text.encode()).hexdigest() == CONDITION_FILES_SHA256[name][rel]


def test_web_instruction_edit(tmp_path):
    (tmp_path / "instruction.md").write_text("# Task\n\n## Rules\n\n" + K.SANDBOX_RULE
                                             + K.INSTRUCTION_END)
    both = K.web_instruction(tmp_path, "web_literature_and_data")
    lit = K.web_instruction(tmp_path, "web_literature_only")
    for s in (both, lit):
        assert K.SANDBOX_RULE not in s
        assert "for all local filesystem access" in s and "## Web research" in s
    assert "data portals" not in both.split("## Web research")[1]
    assert "Observational data sources are out of scope" in lit
