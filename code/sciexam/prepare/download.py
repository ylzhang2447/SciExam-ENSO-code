"""Download the raw observations through OPeNDAP (see ``sources`` for URLs and citations).

Only the boxes of the files the agents received are transferred: each request is one
contiguous hyperslab of the remote variable. GODAS and the NCEP-NCAR daily wind are stored
one file per year on the server, so each year is fetched to ``parts/`` first (an interrupted
download resumes from the years already there) and the years are then joined into one file
per source, named as in the agents' ``data/`` folder.
"""
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
from pathlib import Path

import numpy as np

from . import sources as S

RETRIES = 4


def _span(values, lo, hi):
    """Contiguous index range of a monotonic coordinate inside [lo, hi] (inclusive)."""
    idx = np.where((values >= lo - 1e-6) & (values <= hi + 1e-6))[0]
    if len(idx) == 0:
        raise RuntimeError("no coordinate value in [%g, %g]" % (lo, hi))
    return slice(int(idx[0]), int(idx[-1]) + 1)


def _times(var):
    import netCDF4
    t = netCDF4.num2date(var[:], var.units, getattr(var, "calendar", "standard"),
                         only_use_cftime_datetimes=False, only_use_python_datetimes=True)
    return np.array([np.datetime64(x.replace(tzinfo=None), "ns") for x in t])


def _fetch_once(name, url, first, last):
    """Read the box of one remote file and return an ``xarray.Dataset`` (float32, NaN for
    missing values)."""
    import netCDF4
    import xarray as xr
    spec = S.SPECS[name]
    with netCDF4.Dataset(url) as d:
        v = d.variables[spec["var"]]
        dims = v.dimensions
        times = _times(d.variables["time"])
        keep = (times >= np.datetime64("%d-01-01" % first)) & (times < np.datetime64("%d-01-01" % (last + 1)))
        if not keep.any():
            raise RuntimeError("%s has no time step in %d to %d" % (url, first, last))
        tsl = slice(int(np.where(keep)[0][0]), int(np.where(keep)[0][-1]) + 1)
        lat = np.asarray(d.variables["lat"][:])
        lon = np.asarray(d.variables["lon"][:])
        sl = {"time": tsl, "lat": _span(lat, *spec["lat"]), "lon": _span(lon, *spec["lon"])}
        coords = {"time": times[tsl], "lat": lat[sl["lat"]], "lon": lon[sl["lon"]]}
        if "level" in dims:
            lev = np.asarray(d.variables["level"][:])
            sl["level"] = _span(lev, *spec["level"])
            coords["level"] = lev[sl["level"]]
        v.set_auto_maskandscale(True)
        data = v[tuple(sl[k] for k in dims)]
        data = np.ma.filled(np.ma.masked_invalid(data).astype(np.float32), np.nan)
        attrs = {k: v.getncattr(k) for k in ("units", "long_name") if k in v.ncattrs()}
    out_dims = list(dims)
    if spec["level"] is not None and spec["level"][0] == spec["level"][1]:
        data = data.take(0, axis=dims.index("level"))      # single pressure level
        out_dims.remove("level")
        scalar_level = float(coords.pop("level")[0])
    else:
        scalar_level = None
    da = xr.DataArray(data, dims=out_dims, coords={k: coords[k] for k in out_dims}, attrs=attrs)
    ds = da.sortby("lat").to_dataset(name=spec["var"])
    if scalar_level is not None:
        ds = ds.assign_coords(level=np.float32(scalar_level))
    ds.attrs["source"] = url
    return ds


def fetch_part(name, year, url, path, first, last):
    """Fetch one remote file into ``path`` (written atomically). Returns (bytes, seconds)."""
    t0 = time.time()
    err = None
    for attempt in range(RETRIES):
        try:
            ds = _fetch_once(name, url, first, last)
            tmp = Path(str(path) + ".tmp")
            ds.to_netcdf(tmp)
            os.replace(tmp, path)
            return os.path.getsize(path), time.time() - t0
        except (OSError, RuntimeError) as e:
            err = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("could not fetch %s after %d attempts: %s" % (url, RETRIES, err))


def _join(name, parts, path):
    import xarray as xr
    dss = [xr.open_dataset(p) for p in parts]
    try:
        ds = xr.concat([d.load() for d in dss], dim="time") if len(dss) > 1 else dss[0].load()
    finally:
        for d in dss:
            d.close()
    ds.attrs["source"] = S.SPECS[name]["url"]
    tmp = Path(str(path) + ".tmp")
    ds.to_netcdf(tmp)
    os.replace(tmp, path)


def download_all(raw_dir, first=S.FIRST_YEAR, last=S.LAST_YEAR, jobs=3, log=print):
    """Fetch every source into ``raw_dir``. Files already complete are kept. Returns a dict
    with the bytes transferred and the wall time."""
    raw_dir = Path(raw_dir)
    parts_dir = raw_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    todo, plan = [], {}
    for name in S.SPECS:
        final = raw_dir / name
        if final.exists():
            log("  %-16s present, not downloaded again" % name)
            continue
        plan[name] = []
        for year, url in S.urls(name, first, last):
            tag = "%s.%s.nc" % (name[:-3], year if year is not None else "all")
            p = parts_dir / tag
            plan[name].append(p)
            if not p.exists():
                todo.append((name, year, url, p))
    total = 0
    if todo:
        log("  fetching %d remote files with %d parallel requests" % (len(todo), jobs))
        with ProcessPoolExecutor(max_workers=max(1, jobs), mp_context=get_context("spawn")) as ex:
            futs = {ex.submit(fetch_part, n, y, u, p, first, last): (n, y) for n, y, u, p in todo}
            for i, f in enumerate(as_completed(futs), 1):
                n, y = futs[f]
                nbytes, dt = f.result()
                total += nbytes
                log("  [%d/%d %5.0f s] %-16s %s  %5.1f MB in %4.1f s" % (
                    i, len(todo), time.time() - t0, n, y if y is not None else "", nbytes / 1e6, dt))
    for name, parts in plan.items():
        _join(name, parts, raw_dir / name)
        for p in parts:
            p.unlink()
    try:
        parts_dir.rmdir()
    except OSError:
        pass
    return dict(bytes_fetched=total, seconds=time.time() - t0, files_fetched=len(todo))
