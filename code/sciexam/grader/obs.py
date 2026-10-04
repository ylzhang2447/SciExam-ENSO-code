"""Observation references read by the grader (``grader_obs/`` of the dataset).

These files are never visible to a submission: in sandboxed grading they are mounted only
into the scoring container. Sources (full attributions in the dataset card):

* ``indices_truth.nc``: the five monthly indices from NOAA ERSST v5, NCEP GODAS and the
  NCEP/NCAR Reanalysis 1 (NOAA PSL), built as the task's ``data_processing.md`` prescribes.
* ``stat_obs_sst_70yr.npz``: Nino 3 and Nino 4 SST anomalies 1950 to 2019 from ``obs_data.mat``
  of the Zenodo record doi:10.5281/zenodo.6797996 (Chen and Fang, CC BY 4.0), which derive from
  HadISST1.1 (Met Office Hadley Centre, Open Government Licence v2).
* ``reg_te_tc_hw_ssta.mat`` and ``lon_sst.mat``: files of the same Zenodo record.
* ``obs_bivariate_events.npz``: peak strength and longitude of the observed El Nino events,
  computed from the ERSST v5 field distributed by the Asia-Pacific Data-Research Center.
"""
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FILES = ("indices_truth.nc", "stat_obs_sst_70yr.npz", "obs_bivariate_events.npz",
         "reg_te_tc_hw_ssta.mat", "lon_sst.mat")


@dataclass
class Observations:
    indices: dict           # var -> pandas.Series of monthly observed indices (1980 to 2024)
    stat_TE: np.ndarray     # Nino-3 SST anomalies, 1950-01 to 2019-12
    stat_TC: np.ndarray     # Nino-4 SST anomalies, 1950-01 to 2019-12
    biv_strength: np.ndarray
    biv_location: np.ndarray
    reg: np.ndarray         # regression of the equatorial SST anomaly on [1, T_E, T_C]
    lon: np.ndarray         # longitudes (degrees E) of the regression rows


def load(obs_dir):
    import scipy.io as sio
    import xarray as xr

    p = Path(obs_dir)
    missing = [f for f in FILES if not (p / f).exists()]
    if missing:
        raise FileNotFoundError("observation files missing in %s: %s" % (p, ", ".join(missing)))
    with xr.open_dataset(p / "indices_truth.nc") as d:
        indices = {v: d[v].to_series().dropna() for v in d.data_vars}
    z = np.load(p / "stat_obs_sst_70yr.npz")
    b = np.load(p / "obs_bivariate_events.npz")
    reg = sio.loadmat(p / "reg_te_tc_hw_ssta.mat")["reg_te_tc_hw_ssta"][:, 0:3]
    lon = sio.loadmat(p / "lon_sst.mat")["lon_sst"].ravel()
    good = np.isfinite(reg).all(1)
    return Observations(indices=indices, stat_TE=z["TE"].astype(float), stat_TC=z["TC"].astype(float),
                        biv_strength=b["strength"], biv_location=b["location"],
                        reg=reg[good], lon=lon[good])
