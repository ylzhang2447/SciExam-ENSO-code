"""The year-anonymised task tree, and the Phase 1 gate that grades it on real dates.

The agent of this condition never sees an absolute Gregorian observation year. The tree is
derived from the same inputs the other arms use (the dataset task text and the four raw data
files) by three kinds of edit:

TEXT     every statement of an observation year in the task text becomes a relative label
         (Y001-01 to Y035-12), the names of the observational products are removed (a named
         product states its own coverage, and so the period), and a note says that the
         calendar years in the files are synthetic. The reference paper year (Jin 1997) is
         publication identity, not observation identity, and stays.
NAMES    the data files are renamed, because a file name such as ``godas_pottmp.nc`` names
         the product. Variable names inside the files are unchanged.
NETCDF   each file is written fresh from the source arrays and an allowlist of attributes,
         never copied and patched (a deleted HDF5 attribute can stay readable in the raw
         bytes). The time coordinate keeps its values and its CF units, and only the epoch
         year of the units moves by YEAR_SHIFT = 244 years. Over this 420-month window both
         spans place their leap years at the same offsets and meet no non-leap century year,
         so every month, day and month length lands identically. This is verified point by
         point for every file, and the finished file is scanned as raw bytes and as parsed
         metadata for product names and observation years.

The shifted years stay inside the datetime64[ns] range (up to 2262), so the files decode
through the same path as the originals.

Phase 1 is graded on real dates. ``gate`` copies the agent's table into a private folder
outside the workspace, rewrites only its time column from labels to real months, grades it
with ``data_gate.grade`` and maps every month in the result back to a label. A string in the
result that still looks like a date, and is not a month the map knows, stops the report: the
agent is told the check could not be reported (fail closed). The map between labels and real
months is kept on the host only.
"""
import hashlib
import re
import shutil
from pathlib import Path

YEAR_SHIFT = 244
LABEL = "Y%03d-%02d"
OBS_YEARS = frozenset(range(1980, 2025))      # the supplied window plus the held-out years

# Raw data file -> name in the anonymised workspace.
RENAME = {"ersst_sst.nc": "sst_monthly.nc",
          "godas_pottmp.nc": "ocean_pottmp_monthly.nc",
          "godas_ucur.nc": "ocean_ucur_monthly.nc",
          "ncep_uwnd850.nc": "wind850_daily.nc"}
TIME_SOURCE = "ersst_sst.nc"                   # the monthly file whose time axis defines the map

# Attributes that name a product, a data centre or a storage detail. They are not needed to
# read, scale, mask or interpret the data.
DROP_ATTRS = ("dataset", "center", "sub_center", "parameter_table_version",
              "parameter_number", "gds_grid_type", "level_indicator",
              "GRIB_id", "GRIB_name", "_ChunkSizes")

# Product and centre names, matched case-insensitively as whole tokens against the finished
# files (raw bytes and parsed metadata) and the edited text. A token match, because a plain
# substring test would flag "Conceptual" for "ncep".
BLOCKED_RE = [re.compile(p, re.I) for p in (
    rb"\bersst\b", rb"\bgodas\b", rb"\bncep\b", rb"\bnoaa\b", rb"\breanalysis\b",
    rb"extended reconstructed sst", rb"national weather service",
    rb"environmental modeling center")]

# (file, text before, text after). Each anchor must occur exactly once in the dataset text.
TEXT_EDITS = [
    ("data_processing.md",
     "The provided data covers **1980-01 to 2014-12**. The later years are held out for the",
     "The provided data covers **Y001-01 to Y035-12**. The later months are held out for the"),
    ("data_processing.md",
     "1. **SST** (ERSST v5, monthly, 2 degree grid) : sea surface temperature.",
     "1. **SST** (monthly, 2 degree grid) : sea surface temperature."),
    ("data_processing.md",
     "2. **Ocean** (GODAS, monthly) : potential temperature on depth levels, and zonal",
     "2. **Ocean** (monthly) : potential temperature on depth levels, and zonal"),
    ("data_processing.md",
     "3. **Wind** (NCEP-NCAR reanalysis, daily) : zonal wind at 850 hPa.",
     "3. **Wind** (daily) : zonal wind at 850 hPa."),
    ("data_processing.md",
     "interpolation between the two adjacent GODAS levels bracketing the first crossing",
     "interpolation between the two adjacent ocean levels bracketing the first crossing"),
    ("data_processing.md",
     "For every index, remove the **monthly-mean climatology over the fixed 1981-2010 base\n"
     "period**: for each calendar month, subtract that month's 1981-2010 average. Same base",
     "For every index, remove the **monthly-mean climatology over the fixed Y002-01 to\n"
     "Y031-12 base period**: for each calendar month, subtract that month's Y002 to Y031\n"
     "average. Same base"),
    ("data_processing.md",
     "tau`, over the provided 1980-01 to 2014-12 period. Also write `processed/",
     "tau`, over the provided Y001-01 to Y035-12 period. Also write `processed/"),
    ("data_processing.md",
     "- **Fill values and masks** : NOAA netCDF files use fill values (e.g. 1e20,",
     "- **Fill values and masks** : the netCDF files use fill values (e.g. 1e20,"),
    ("data_processing.md",
     "- **Units** : GODAS potential temperature is in Kelvin; convert to Celsius before",
     "- **Units** : the provided ocean potential-temperature variable pottmp is in Kelvin;\n"
     "  convert to Celsius before"),
    ("interface.md",
     "`indices.csv` must have a time column (`time`, `date`, or `month`; any parseable\n"
     "monthly date) and one column per index with these exact names, over the full provided\n"
     "period (1980-01 to 2014-12):",
     "`indices.csv` must have a time column (`time`, `date`, or `month`) holding the\n"
     "relative monthly labels `Y001-01` .. `Y035-12`, and one column per index with these\n"
     "exact names, over the full provided period (Y001-01 to Y035-12):"),
    ("interface.md",
     "time,TC,TE,hW,u,tau\n1980-01,-0.42,-0.31,3.1,0.02,-0.5\n1980-02, ...",
     "time,TC,TE,hW,u,tau\nY001-01,-0.42,-0.31,3.1,0.02,-0.5\nY001-02, ..."),
    ("interface.md",
     "and resubmit. The later years (2015 onward) are held out for prediction and are not in",
     "and resubmit. The later months (after Y035-12) are held out for prediction and are not in"),
]

# Inserted after the (already edited) coverage paragraph of data_processing.md.
CAL_ANCHOR = ("The provided data covers **Y001-01 to Y035-12**. The later months are held "
              "out for the\nprediction stage and are intentionally absent; process the full "
              "provided period.\n")
CAL_NOTE = ("\nCalendar years in the supplied files are synthetic labels used to preserve "
            "month\nordering and calendar spacing. They do not denote the historical "
            "observation years.\nThe relative labels `Y001` .. `Y035` index the supplied "
            "years in order: `Y001` is the\nfirst calendar year present in the supplied "
            "files, and `-01` .. `-12` are January .. December.\n")


class AnonymisationError(RuntimeError):
    pass


def blocked_hits(raw):
    """Product names found in ``raw`` (bytes or text), as whole tokens."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8", "replace")
    return sorted({m.group().decode("utf-8", "replace").lower()
                   for r in BLOCKED_RE for m in r.finditer(raw)})


# Year strings that are publication identity, not observation identity: the reference paper
# (Jin 1997, and its file name) and DOIs. They stay in the text.
PUBLICATION_CONTEXTS = re.compile(r"Jin,? (?:F\.-F\. )?\(?1997\)?|Jin_1997_|10\.\d{4,9}/\S+")


def year_hits(text):
    """Observation years (1980 to 2024) appearing as a standalone four-digit number outside a
    publication reference."""
    text = PUBLICATION_CONTEXTS.sub(" ", text)
    return sorted({m.group(1) for m in re.finditer(r"(?<![\d.])(\d{4})(?!\.?\d)", text)
                   if int(m.group(1)) in OBS_YEARS})


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---- text ----------------------------------------------------------------------------------

def edit_texts(task_dir):
    """The edited task texts, as {relative path: text}. Files without edits are not listed."""
    task_dir = Path(task_dir)
    out = {}
    for fn, before, after in TEXT_EDITS:
        s = out.get(fn) or (task_dir / fn).read_text(encoding="utf-8")
        if s.count(before) != 1:
            raise AnonymisationError("%s: anchor not found exactly once: %r" % (fn, before[:60]))
        out[fn] = s.replace(before, after, 1)
    s = out["data_processing.md"]
    if s.count(CAL_ANCHOR) != 1:
        raise AnonymisationError("data_processing.md: calendar-note anchor not found exactly once")
    out["data_processing.md"] = s.replace(CAL_ANCHOR, CAL_ANCHOR + CAL_NOTE, 1)
    return out


# ---- time map ------------------------------------------------------------------------------

def _decode_times(var):
    import netCDF4
    return netCDF4.num2date(var[:], var.units, getattr(var, "calendar", "standard"),
                            only_use_cftime_datetimes=True)


def time_map(sst_path):
    """Labels <-> real months, derived from the time axis of the monthly SST file.

    ``Y001`` is the first calendar year in the file. Synthetic months are the real months
    shifted by YEAR_SHIFT years, as the anonymised files decode them.
    """
    import netCDF4
    with netCDF4.Dataset(str(sst_path)) as d:
        times = _decode_times(d.variables["time"])
    y0 = times[0].year
    real = ["%04d-%02d" % (t.year, t.month) for t in times]
    anon = [LABEL % (t.year - y0 + 1, t.month) for t in times]
    synth = ["%04d-%02d" % (t.year + YEAR_SHIFT, t.month) for t in times]
    return {"n_months": len(real), "year_shift": YEAR_SHIFT,
            "anon_first": anon[0], "anon_last": anon[-1],
            "anon_to_real": dict(zip(anon, real)),
            "synthetic_to_real": dict(zip(synth, real)),
            "real_to_anon": dict(zip(real, anon))}


# ---- netCDF --------------------------------------------------------------------------------

_UNITS = re.compile(r"^(\s*\w+\s+since\s+)(\d{4})(-.*)$")


def shift_units(units):
    """'days since 1800-01-01' -> 'days since 2044-01-01' (epoch year + YEAR_SHIFT)."""
    m = _UNITS.match(str(units))
    if not m:
        raise AnonymisationError("time units %r are not of the form '<unit> since YYYY-..'" % units)
    return "%s%04d%s" % (m.group(1), int(m.group(2)) + YEAR_SHIFT, m.group(3))


def write_clean_nc(src, dst):
    """Write ``dst`` fresh from the arrays of ``src`` with the product identity removed.

    Arrays are copied unscaled and unmasked, so the stored values are the stored values.
    Returns the list of attribute edits.
    """
    import netCDF4
    import numpy as np
    a = netCDF4.Dataset(str(src))
    a.set_auto_maskandscale(False)
    b = netCDF4.Dataset(str(dst), "w", format=a.data_model)
    b.set_auto_maskandscale(False)
    edits = []
    try:
        for name, dim in a.dimensions.items():
            b.createDimension(name, None if dim.isunlimited() else len(dim))
        for vn, va in a.variables.items():
            fv = va.getncattr("_FillValue") if "_FillValue" in va.ncattrs() else None
            vb = b.createVariable(vn, va.dtype, va.dimensions, fill_value=fv, zlib=False)
            vb.set_auto_maskandscale(False)
            for at in va.ncattrs():
                if at == "_FillValue":
                    continue
                val = va.getncattr(at)
                if at in DROP_ATTRS or (isinstance(val, str) and blocked_hits(val)):
                    edits.append({"var": vn, "attr": at, "before": str(val), "after": None})
                    continue
                if vn == "time" and at == "units":
                    nv = shift_units(val)
                    vb.setncattr(at, nv)
                    edits.append({"var": vn, "attr": at, "before": str(val), "after": nv})
                    continue
                if vn == "time" and at == "actual_range":
                    tv = np.asarray(va[:], dtype=float)
                    nv = np.array([tv.min(), tv.max()], dtype=np.atleast_1d(val).dtype)
                    vb.setncattr(at, nv)
                    edits.append({"var": vn, "attr": at,
                                  "before": [float(x) for x in np.atleast_1d(val)],
                                  "after": [float(x) for x in nv]})
                    continue
                vb.setncattr(at, val)
            if va.ndim == 0:
                vb[...] = va[...]
            else:
                n = va.shape[0]
                step = max(1, min(n, int(2e7 // max(1, int(np.prod(va.shape[1:]) or 1)))))
                for i in range(0, n, step):
                    vb[i:i + step] = va[i:i + step]
        for at in a.ncattrs():
            val = a.getncattr(at)
            if at in DROP_ATTRS or (isinstance(val, str) and blocked_hits(val)):
                edits.append({"var": "(global)", "attr": at, "before": str(val), "after": None})
                continue
            b.setncattr(at, val)
    finally:
        a.close()
        b.close()
    return edits


def verify_nc(src, dst):
    """Refuse unless ``dst`` holds the calendar of ``src`` shifted by YEAR_SHIFT years and no
    product name or observation year. Returns the number of time steps checked."""
    import netCDF4
    raw = Path(dst).read_bytes()
    hit = blocked_hits(raw)
    if hit:
        raise AnonymisationError("%s still contains %s in its raw bytes" % (dst, hit))
    with netCDF4.Dataset(str(src)) as a, netCDF4.Dataset(str(dst)) as b:
        ta, tb = _decode_times(a.variables["time"]), _decode_times(b.variables["time"])
        if len(ta) != len(tb):
            raise AnonymisationError("%s: time axis length changed" % dst)
        for x, y in zip(ta, tb):
            if (y.year != x.year + YEAR_SHIFT or (y.month, y.day, y.hour, y.minute, y.second)
                    != (x.month, x.day, x.hour, x.minute, x.second)):
                raise AnonymisationError("%s: %s does not map to %s shifted by %d years"
                                         % (dst, y, x, YEAR_SHIFT))
        texts = ["%s=%s" % (k, b.getncattr(k)) for k in b.ncattrs()]
        for vn, v in b.variables.items():
            texts += ["%s:%s=%s" % (vn, k, v.getncattr(k)) for k in v.ncattrs()
                      if isinstance(v.getncattr(k), str)]
        meta = "\n".join(texts)
        if blocked_hits(meta) or year_hits(meta):
            raise AnonymisationError("%s: metadata still names %s" % (
                dst, blocked_hits(meta) or year_hits(meta)))
    return len(tb)


# ---- the tree ------------------------------------------------------------------------------

def build(task_dir, data_dir, out_dir, text_files):
    """Write the anonymised task tree into ``out_dir``.

    ``text_files`` are the task text files to copy (relative paths). Returns a manifest with
    the renames, the text edits and the netCDF attribute edits. Deterministic: the same inputs
    give the same bytes.
    """
    task_dir, data_dir, out_dir = Path(task_dir), Path(data_dir), Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "data").mkdir(parents=True)
    edited = edit_texts(task_dir)
    for rel in text_files:
        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if rel in edited:
            dst.write_text(edited[rel], encoding="utf-8")
        else:
            shutil.copyfile(task_dir / rel, dst)
        leak = blocked_hits(dst.read_bytes())
        if leak:
            raise AnonymisationError("%s names %s" % (rel, leak))
    man = {"year_shift_years": YEAR_SHIFT, "text_edits": len(TEXT_EDITS) + 1,
           "renamed": {"data/" + k: "data/" + v for k, v in sorted(RENAME.items())},
           "netcdf": {}}
    for src_name, dst_name in sorted(RENAME.items()):
        src, dst = data_dir / src_name, out_dir / "data" / dst_name
        edits = write_clean_nc(src, dst)
        steps = verify_nc(src, dst)
        man["netcdf"]["data/" + dst_name] = {"source": "data/" + src_name, "time_steps": steps,
                                             "attribute_edits": edits}
    return man


def instruction_leaks(out_dir, text_files):
    """(file, what) for every observation year or product name left in the edited texts."""
    out = []
    for rel in text_files:
        p = Path(out_dir) / rel
        if not p.exists():
            continue
        t = p.read_text(encoding="utf-8", errors="replace")
        for y in year_hits(t):
            out.append((rel, y))
        for b in blocked_hits(t):
            out.append((rel, b))
    return out


# ---- Phase 1 -------------------------------------------------------------------------------

_ANON_LABEL = re.compile(r"\AY(\d{3})-(\d{2})\Z")
_SYNTH_LABEL = re.compile(r"\A(\d{4})-(\d{2})(?:-\d{2})?\Z")
TIME_COLS = ("time", "date", "month")

# A date shape: four digits, then a month (01 to 12) and optionally a day (01 to 31), either
# with one separator used consistently or written compactly (203107, 2031:07:15).
_DATE_SHAPE = re.compile(r"""
    (?<![0-9A-Za-z])
    (?P<y>\d{4})
    (?:
        (?P<sep>[^0-9A-Za-z])(?P<m1>\d{2})(?:(?P=sep)(?P<d1>\d{2}))?
      | (?P<m2>\d{2})(?P<d2>\d{2})?
    )
    (?![0-9A-Za-z])
""", re.X)
_YEAR_TOKEN = re.compile(r"(?<![\d.])(\d{4})(?!\.?\d)")
_DATE_KEY = re.compile(r"(date|month|year|period|time|epoch|day)", re.I)
APPROVED_DATE_KEYS = frozenset(("worst_month", "train_period", "missing_months"))


class LeakError(Exception):
    """A real or unrecognised date survived translation. Nothing is reported."""


def string_leaks(s):
    """Date-shaped runs and observation years in a string."""
    out = []
    for m in _DATE_SHAPE.finditer(s):
        month = int(m.group("m1") or m.group("m2"))
        day = m.group("d1") or m.group("d2")
        if 1 <= month <= 12 and (day is None or 1 <= int(day) <= 31):
            out.append(m.group())
    out += [m.group() for m in _YEAR_TOKEN.finditer(s) if int(m.group(1)) in OBS_YEARS]
    return sorted(set(out))


def translate_csv(src, dst, M):
    """Rewrite only the time column of the agent's table, label -> real month.

    Accepts the relative labels (Y001-01) and the synthetic months the files decode to
    (2224-01). Every other byte is carried over unchanged. Returns (ok, why, counts).
    """
    text = Path(src).read_text(encoding="utf-8")
    lines = text.splitlines()
    head = next((i for i, line in enumerate(lines) if line.strip()), None)
    if head is None:
        return False, "the submitted table is empty", {}
    cols = [c.strip().lower() for c in lines[head].split(",")]
    idx = next((i for i, c in enumerate(cols) if c in TIME_COLS), None)
    if idx is None:
        return False, "no time column named time, date or month", {}
    a2r, s2r, r2a = M["anon_to_real"], M["synthetic_to_real"], M["real_to_anon"]
    out = list(lines[:head + 1])
    counts = {"anon": 0, "synthetic": 0, "real_seen": 0, "unknown": 0, "rows": 0}
    bad = 0
    for line in lines[head + 1:]:
        if not line.strip():
            out.append(line)
            continue
        f = line.split(",")
        if len(f) <= idx:
            return False, "a row has fewer columns than the header", counts
        counts["rows"] += 1
        raw = f[idx].strip()
        if _ANON_LABEL.match(raw) and raw in a2r:
            f[idx] = a2r[raw]
            counts["anon"] += 1
        elif _SYNTH_LABEL.match(raw) and raw[:7] in s2r:
            f[idx] = s2r[raw[:7]]
            counts["synthetic"] += 1
        else:
            counts["real_seen" if raw[:7] in r2a else "unknown"] += 1
            bad += 1
        out.append(",".join(f))
    if bad:
        return False, ("time labels are not in the required Y001-01 .. Y035-12 form "
                       "(%d of %d rows)" % (bad, counts["rows"])), counts
    Path(dst).write_text("\n".join(out) + ("\n" if text.endswith("\n") else ""),
                         encoding="utf-8")
    return True, None, counts


def sanitize(obj, M, path="$"):
    """The grader result with every real month replaced by its label.

    Numbers are never read as dates (a tolerance of 0.1997 is a number). A string that is a
    real month is translated, and any other string that looks like a date raises LeakError,
    as does a key whose name promises a date and is not one of APPROVED_DATE_KEYS.
    """
    r2a = M["real_to_anon"]
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            ks = str(k)
            if _DATE_KEY.search(ks) and ks not in APPROVED_DATE_KEYS:
                raise LeakError("%s.%s: a field whose name promises a date" % (path, ks))
            if string_leaks(ks):
                raise LeakError("%s: the field name %r carries a date" % (path, ks[:50]))
            out[ks] = sanitize(v, M, "%s.%s" % (path, ks))
        return out
    if isinstance(obj, (list, tuple)):
        return [sanitize(v, M, "%s[%d]" % (path, i)) for i, v in enumerate(obj)]
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        if obj.strip() in r2a:
            return r2a[obj.strip()]
        if string_leaks(obj):
            raise LeakError("%s: %r is not a month the map knows" % (path, obj[:70]))
        return obj
    raise LeakError("%s: unexpected value type %s" % (path, type(obj).__name__))


def gate(submission_dir, obs_file, M, private_dir, grade):
    """Phase 1 of the anonymised condition.

    Returns the data-gate result with every month given as a label and ``feedback`` set to
    the text the agent receives. ``grade`` is ``data_gate.grade``. The staging copy with real
    dates lives in ``private_dir``, which is never mounted into the agent container.
    """
    from . import prompts as P
    stage = Path(private_dir) / "phase1" / "submission"
    if stage.parent.exists():
        shutil.rmtree(stage.parent)
    (stage / "processed").mkdir(parents=True)
    src = Path(submission_dir) / "processed"
    for name in ("indices.csv", "processing_notes.md"):
        if (src / name).is_file():
            shutil.copyfile(src / name, stage / "processed" / name)
    csv = stage / "processed" / "indices.csv"
    if not csv.exists():
        return {"passed": False, "feedback": P.ANON_P1_MISSING}
    ok, why, _counts = translate_csv(csv, csv, M)
    if not ok:
        return {"passed": False, "feedback": P.ANON_P1_REJECTED % why}
    try:
        clean = sanitize(grade(stage, obs_file), M)
    except LeakError:
        return {"passed": False, "feedback": P.ANON_P1_UNREPORTABLE}
    _passed, fb = P.phase1_feedback(clean)
    if string_leaks(fb):
        return {"passed": False, "feedback": P.ANON_P1_UNREPORTABLE}
    clean["feedback"] = fb
    return clean
