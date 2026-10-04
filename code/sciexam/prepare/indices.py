"""The five monthly indices, built with the task's data processing recipe (``task/data_processing.md``).

* TC (Nino 4): ERSST v5 SST, box 160E to 210E, 5S to 5N.
* TE (Nino 3): ERSST v5 SST, box 210E to 270E, 5S to 5N.
* hW: depth of the 20 degree C isotherm of GODAS potential temperature (Kelvin converted to
  Celsius), box 120E to 180E, 5S to 5N. In each water column the depth is interpolated
  linearly between the two adjacent valid levels that bracket the first crossing from the
  surface. Columns without a crossing, or whose top valid level is already colder than 20
  degrees C, are NaN.
* u: GODAS zonal current averaged over the levels from the surface down to 55 m, then over the
  box 160E to 210E, 5S to 5N.
* tau: NCEP-NCAR Reanalysis 1 daily 850 hPa zonal wind averaged over the box 120E to 180E,
  5S to 5N, then over each calendar month (positive westerly).

Every box average is weighted by the cosine of latitude, uses the grid points inside the box
(boundaries included) on the native grid and skips missing points. Anomalies remove the
monthly climatology of the fixed base period 1981-01 to 2010-12 and nothing else.

This follows the builder of the reference indices shipped in ``grader_obs/indices_truth.nc``
and is written from scratch in array form (the isotherm search walks down the levels once
for all columns).
"""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

NAMES = ("TC", "TE", "hW", "u", "tau")
LAT = (-5.0, 5.0)
LON = {"TC": (160.0, 210.0), "TE": (210.0, 270.0), "hW": (120.0, 180.0),
       "u": (160.0, 210.0), "tau": (120.0, 180.0)}
ISOTHERM_C = 20.0
MIXED_LAYER_M = 55.0
CLIM_BASE = ("1981-01", "2010-12")

# Per-index absolute tolerance of the task's Phase 1 data gate (the checker that compared each
# agent's processed indices with the reference, element by element over the training months
# 1980-01 to 2014-12, before modeling was unlocked). The agent-facing instruction says only that
# the check uses "a tolerance". The values below are the checker's own, a few percent of each
# index's standard deviation (given in brackets).
TOLERANCE = {
    "TC": 0.02,     # degrees C (std about 0.7)
    "TE": 0.02,     # degrees C (std about 0.9)
    "hW": 0.40,     # m (std about 13)
    "u": 0.006,     # m/s (std about 0.16)
    "tau": 0.05,    # m/s (std about 1.9)
}
GATE_PERIOD = ("1980-01", "2014-12")


def _box_mask(coord, lo, hi):
    return (coord >= lo) & (coord <= hi)


def box_mean(arr, lat, lon, lon_box, lat_box=LAT):
    """Cosine-latitude weighted mean over the last two axes (lat, lon) inside the box,
    skipping NaN. Returns NaN where the box holds no valid point."""
    jm = _box_mask(lat, *lat_box)
    im = _box_mask(lon, *lon_box)
    sub = np.asarray(arr, dtype=float)[..., jm, :][..., im]
    w = np.broadcast_to(np.cos(np.deg2rad(np.asarray(lat[jm], dtype=float)))[:, None], sub.shape[-2:])
    ok = np.isfinite(sub)
    num = np.where(ok, sub * w, 0.0).sum(axis=(-2, -1))
    den = np.where(ok, w, 0.0).sum(axis=(-2, -1))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)


def isotherm_depth(temp, levels, iso=ISOTHERM_C):
    """Depth of the first crossing of ``iso`` from the surface. ``temp`` has the level axis
    first. Invalid levels are skipped, so the bracketing levels are adjacent valid ones."""
    temp = np.asarray(temp, dtype=float)
    shape = temp.shape[1:]
    depth = np.full(shape, np.nan)
    done = np.zeros(shape, dtype=bool)
    t_prev = np.full(shape, np.nan)
    z_prev = np.full(shape, np.nan)
    for k, z in enumerate(np.asarray(levels, dtype=float)):
        t = temp[k]
        valid = np.isfinite(t)
        cross = valid & ~done & (t < iso)
        has_prev = np.isfinite(t_prev)
        interp = cross & has_prev & (t_prev != t)
        with np.errstate(invalid="ignore", divide="ignore"):
            d = z_prev + (z - z_prev) * (t_prev - iso) / (t_prev - t)
        depth = np.where(interp, d, depth)
        done |= cross            # a crossing at the top valid level, or with equal ends, stays NaN
        t_prev = np.where(valid, t, t_prev)
        z_prev = np.where(valid, z, z_prev)
    return depth


def monthly_anomaly(s, base=CLIM_BASE):
    """Remove the calendar-month means of the base period."""
    b = s[(s.index >= base[0]) & (s.index <= base[1])]
    if b.notna().groupby(b.index.month).sum().min() == 0:
        raise RuntimeError("the raw data do not cover the climatology base period %s to %s" % base)
    clim = b.groupby(b.index.month).mean()
    return s - clim.reindex(s.index.month).to_numpy()


def _month_index(times):
    return pd.PeriodIndex(pd.DatetimeIndex(times), freq="M")


def _open(raw_dir, name, var):
    import xarray as xr
    p = Path(raw_dir) / name
    if not p.exists():
        raise RuntimeError("missing raw file %s" % p)
    with xr.open_dataset(p) as ds:
        da = ds[var].load()
    return da


def sst_indices(raw_dir):
    da = _open(raw_dir, "ersst_sst.nc", "sst").transpose("time", "lat", "lon")
    idx = _month_index(da["time"].values)
    out = {}
    for name in ("TC", "TE"):
        m = box_mean(da.values, da["lat"].values, da["lon"].values, LON[name])
        out[name] = pd.Series(m, index=idx)
    return out


def _in_box(da, lon_box, lat_box=LAT):
    """The grid points of the box (boundaries included), before any computation."""
    return da.isel(lat=_box_mask(da["lat"].values, *lat_box), lon=_box_mask(da["lon"].values, *lon_box))


def ocean_indices(raw_dir):
    pt = _in_box(_open(raw_dir, "godas_pottmp.nc", "pottmp"), LON["hW"]).transpose("level", "time", "lat", "lon")
    t = pt.values.astype(float)
    if np.nanmax(t) > 200.0:          # Kelvin on the server
        t -= 273.15
    depth = isotherm_depth(t, pt["level"].values)
    hw = box_mean(depth, pt["lat"].values, pt["lon"].values, LON["hW"])
    uc = _in_box(_open(raw_dir, "godas_ucur.nc", "ucur"), LON["u"]).transpose("level", "time", "lat", "lon")
    ml = uc["level"].values <= MIXED_LAYER_M
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)      # all-NaN land columns
        uml = np.nanmean(uc.values[ml].astype(float), axis=0)
    u = box_mean(uml, uc["lat"].values, uc["lon"].values, LON["u"])
    return {"hW": pd.Series(hw, index=_month_index(pt["time"].values)),
            "u": pd.Series(u, index=_month_index(uc["time"].values))}


def wind_index(raw_dir):
    uw = _open(raw_dir, "ncep_uwnd850.nc", "uwnd").transpose("time", "lat", "lon")
    daily = pd.Series(box_mean(uw.values, uw["lat"].values, uw["lon"].values, LON["tau"]),
                      index=pd.DatetimeIndex(uw["time"].values))
    monthly = daily.groupby(daily.index.to_period("M")).mean()
    return {"tau": monthly}


def build(raw_dir):
    """Return a DataFrame indexed by month with the anomaly columns TC, TE, hW, u, tau."""
    raw = {}
    raw.update(sst_indices(raw_dir))
    raw.update(ocean_indices(raw_dir))
    raw.update(wind_index(raw_dir))
    df = pd.DataFrame({k: monthly_anomaly(raw[k].sort_index()) for k in NAMES})
    df.index.name = "time"
    return df


def write_csv(df, path):
    """``processed/indices.csv`` in the task's format (columns time, TC, TE, hW, u, tau)."""
    out = df.copy()
    out.index = out.index.strftime("%Y-%m")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, float_format="%.10g")


def load_reference(root):
    """Reference indices of the dataset (``grader_obs/indices_truth.nc``), by month."""
    import xarray as xr
    with xr.open_dataset(Path(root) / "grader_obs" / "indices_truth.nc") as ds:
        df = ds[list(NAMES)].to_dataframe()
    df.index = _month_index(df.index)
    return df


def compare(mine, ref, period=GATE_PERIOD, tol=TOLERANCE):
    """Element-wise comparison over ``period``, as the Phase 1 gate does: every month of the
    reference must be present and every difference within the tolerance."""
    lo, hi = pd.Period(period[0], "M"), pd.Period(period[1], "M")
    rows = {}
    for k in NAMES:
        r = ref[k].dropna()
        r = r[(r.index >= lo) & (r.index <= hi)]
        m = mine[k].reindex(r.index)
        ok = m.notna()
        missing = int((~ok).sum())
        if ok.sum() == 0:
            rows[k] = dict(passed=False, n=0, missing=missing, tol=tol[k])
            continue
        d = (m[ok] - r[ok]).abs()
        worst = d.idxmax()
        rows[k] = dict(passed=bool(missing == 0 and d.max() <= tol[k]), n=int(ok.sum()), missing=missing,
                       max_abs_diff=float(d.max()), worst_month=str(worst),
                       corr=float(np.corrcoef(m[ok], r[ok])[0, 1]), tol=tol[k],
                       ref_std=float(r.std()))
    return rows
