#!/usr/bin/env python3
"""Rebuild the agent's raw-data folder (task data/) from the public NOAA PSL archives.

The benchmark gives the agent four netCDF files covering 1980-01 to 2014-12 (the held-out
2015-2024 period is removed). They are subsets of public datasets and are not redistributed
here. This script downloads the same variables, boxes and period through OPeNDAP and writes:

    data/ersst_sst.nc      ERSST v5 monthly SST, lat -12..12, lon 100..300 (2 degree grid)
    data/godas_pottmp.nc   GODAS monthly potential temperature, levels 5..366 m, lat -7.9..7.9, lon 110.5..219.5
    data/godas_ucur.nc     GODAS monthly zonal current, levels 5..95 m, lat -7.9..8.0, lon 110..220
    data/ncep_uwnd850.nc   NCEP-NCAR Reanalysis 1 daily 850 hPa zonal wind, lat -7.5..7.5, lon 110..190

Dataset versions on the server can change (ERSST is revised in place), so a fresh download is
not guaranteed to be bit-identical to the files the agents received. The grader does not need
these files: it scores against the derived indices in grader/obs_reference/. They are only
needed to re-run Phase 1 (data processing) with an agent.

Usage:
    python download_data.py --out ../data            # about 330 MB
    python download_data.py --out ../data --dry-run  # print what would be fetched
Requires: xarray, netCDF4 (with OPeNDAP support), numpy.
"""
import argparse
import os

BASE = "https://psl.noaa.gov/thredds/dodsC/Datasets"
PERIOD = ("1980-01-01", "2014-12-31")
YEARS = range(1980, 2015)

SPECS = {
    "ersst_sst.nc": dict(urls=[BASE + "/noaa.ersst.v5/sst.mnmean.nc"], var="sst",
                         lat=(-12.0, 12.0), lon=(100.0, 300.0), level=None),
    "godas_pottmp.nc": dict(urls=[BASE + "/godas/pottmp.%d.nc" % y for y in YEARS], var="pottmp",
                            lat=(-7.9, 7.9), lon=(110.5, 219.5), level=(5.0, 366.0)),
    "godas_ucur.nc": dict(urls=[BASE + "/godas/ucur.%d.nc" % y for y in YEARS], var="ucur",
                          lat=(-7.9, 8.0), lon=(110.0, 220.0), level=(5.0, 95.0)),
    "ncep_uwnd850.nc": dict(urls=[BASE + "/ncep.reanalysis/Dailies/pressure/uwnd.%d.nc" % y for y in YEARS],
                            var="uwnd", lat=(-7.5, 7.5), lon=(110.0, 190.0), level=(850.0, 850.0)),
}


def _between(coord, lo, hi):
    return (coord >= lo - 1e-6) & (coord <= hi + 1e-6)


def fetch(spec):
    import xarray as xr
    parts = []
    for url in spec["urls"]:
        ds = xr.open_dataset(url)
        da = ds[spec["var"]]
        da = da.sel(time=slice(*PERIOD))
        # index on the coordinate values only, so OPeNDAP transfers just the box
        sel = {"lat": _between(da["lat"].values, *spec["lat"]),
               "lon": _between(da["lon"].values, *spec["lon"])}
        if spec["level"] is not None:
            sel["level"] = _between(da["level"].values, *spec["level"])
        da = da.isel(**sel)
        parts.append(da.load())
        ds.close()
    out = parts[0] if len(parts) == 1 else xr.concat(parts, dim="time")
    return out.sortby("lat").to_dataset(name=spec["var"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", nargs="*", default=None, help="subset of file names to fetch")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for name, spec in SPECS.items():
        if a.only and name not in a.only:
            continue
        print("%-18s %d source file(s), e.g. %s" % (name, len(spec["urls"]), spec["urls"][0]))
        if a.dry_run:
            continue
        ds = fetch(spec)
        ds.to_netcdf(os.path.join(a.out, name))
        print("  wrote", os.path.join(a.out, name), dict(ds.sizes))


if __name__ == "__main__":
    main()
