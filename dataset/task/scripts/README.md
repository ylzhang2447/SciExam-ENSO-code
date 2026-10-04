# Raw observational data (not redistributed)

The agents received a `data/` folder with four netCDF files (about 326 MB), subsets of public
NOAA datasets for 1980-01 to 2014-12. The years 2015 to 2024 are held out for the prediction
dimension and were never in the agent's sandbox. The files are not included here. To rebuild
them:

```
bash download_data.sh            # writes task/data/*.nc through OPeNDAP (about 330 MB)
bash download_data.sh --dry-run  # list the sources only
```

| file | dataset | variable | box and period |
|---|---|---|---|
| `ersst_sst.nc` | NOAA ERSST v5, monthly | `sst` | 12S to 12N, 100E to 300E, 1980-01 to 2014-12 |
| `godas_pottmp.nc` | NCEP GODAS, monthly | `pottmp` | 7.9S to 7.9N, 110.5E to 219.5E, 5 to 366 m |
| `godas_ucur.nc` | NCEP GODAS, monthly | `ucur` | 7.9S to 8N, 110E to 220E, 5 to 95 m |
| `ncep_uwnd850.nc` | NCEP-NCAR Reanalysis 1, daily | `uwnd` at 850 hPa | 7.5S to 7.5N, 110E to 190E |

The processing recipe the agent must follow is `../data_processing.md`. The Phase 1 gate
(`grader/grade_data.py`) compares the agent's indices with `grader/obs_reference/indices_truth.nc`.
Datasets are revised on the server from time to time, so a fresh download can differ slightly
from the files the agents used. Scoring a submitted model does not need these files.

Data sources and citations:

* NOAA Extended Reconstructed SST v5 (ERSST v5). Huang, B., et al., 2017: Extended
  Reconstructed Sea Surface Temperature, Version 5 (ERSSTv5): Upgrades, Validations, and
  Intercomparisons. J. Climate, 30, 8179-8205, doi:10.1175/JCLI-D-16-0836.1.
* NCEP Global Ocean Data Assimilation System (GODAS). Behringer, D. W., and Y. Xue, 2004:
  Evaluation of the global ocean data assimilation system at NCEP: The Pacific Ocean. Eighth
  Symposium on Integrated Observing and Assimilation Systems for Atmosphere, Oceans, and Land
  Surface, AMS 84th Annual Meeting.
* NCEP-NCAR Reanalysis 1. Kalnay, E., et al., 1996: The NCEP/NCAR 40-Year Reanalysis
  Project. Bull. Amer. Meteor. Soc., 77, 437-471.

All three are provided by the NOAA Physical Sciences Laboratory (PSL), Boulder, Colorado, USA,
from https://psl.noaa.gov. Please follow the PSL data use and citation guidance.
