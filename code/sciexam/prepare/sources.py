"""Public raw data sources of the task and their citations.

The agents received four netCDF files in ``data/``, subsets of public NOAA datasets for
1980-01 to 2014-12 (the years 2015 to 2024 are held out for the prediction dimension). They are
not redistributed. ``sciexam prepare-data`` fetches the same variables, boxes and period
through the OPeNDAP service of the NOAA Physical Sciences Laboratory (PSL):

=====================  ===========================================================================
file                   OPeNDAP source
=====================  ===========================================================================
``ersst_sst.nc``       https://psl.noaa.gov/thredds/dodsC/Datasets/noaa.ersst.v5/sst.mnmean.nc
``godas_pottmp.nc``    https://psl.noaa.gov/thredds/dodsC/Datasets/godas/pottmp.YYYY.nc (one per year)
``godas_ucur.nc``      https://psl.noaa.gov/thredds/dodsC/Datasets/godas/ucur.YYYY.nc (one per year)
``ncep_uwnd850.nc``    https://psl.noaa.gov/thredds/dodsC/Datasets/ncep.reanalysis/Dailies/pressure/uwnd.YYYY.nc
=====================  ===========================================================================

The same files are served over plain HTTPS (whole files, much larger than the subsets) under
https://downloads.psl.noaa.gov/Datasets/ with the same relative paths. Dataset pages:
https://psl.noaa.gov/data/gridded/data.noaa.ersst.v5.html,
https://psl.noaa.gov/data/gridded/data.godas.html and
https://psl.noaa.gov/data/gridded/data.ncep.reanalysis.html.

Citations:

* NOAA Extended Reconstructed SST v5 (ERSST v5). Huang, B., P. W. Thorne, V. F. Banzon,
  T. Boyer, G. Chepurin, J. H. Lawrimore, M. J. Menne, T. M. Smith, R. S. Vose and H.-M. Zhang,
  2017: Extended Reconstructed Sea Surface Temperature, Version 5 (ERSSTv5): Upgrades,
  Validations, and Intercomparisons. J. Climate, 30, 8179-8205, doi:10.1175/JCLI-D-16-0836.1.
  Dataset: NOAA National Centers for Environmental Information, doi:10.7289/V5T72FNM.
* NCEP Global Ocean Data Assimilation System (GODAS). Behringer, D. W., and Y. Xue, 2004:
  Evaluation of the global ocean data assimilation system at NCEP: The Pacific Ocean. Eighth
  Symposium on Integrated Observing and Assimilation Systems for Atmosphere, Oceans, and Land
  Surface, AMS 84th Annual Meeting, Seattle, Washington.
* NCEP-NCAR Reanalysis 1. Kalnay, E., et al., 1996: The NCEP/NCAR 40-Year Reanalysis Project.
  Bull. Amer. Meteor. Soc., 77, 437-471.

Acknowledgement requested by the provider: data provided by the NOAA PSL, Boulder, Colorado,
USA, from their website at https://psl.noaa.gov.

The servers revise these datasets from time to time (ERSST v5 is updated in place), so a fresh
download is not guaranteed to be bit identical to the files the agents received.
"""

BASE = "https://psl.noaa.gov/thredds/dodsC/Datasets"

FIRST_YEAR = 1980
LAST_YEAR = 2014          # last year given to the agents, later years are held out
LAST_AVAILABLE = 2024     # last year of the reference indices in the dataset

# Boxes of the files the agents received (latitude, longitude in 0 to 360 and depth in m,
# inclusive). They contain the index boxes of the processing recipe with a margin.
SPECS = {
    "ersst_sst.nc": dict(var="sst", url=BASE + "/noaa.ersst.v5/sst.mnmean.nc", per_year=False,
                         lat=(-12.0, 12.0), lon=(100.0, 300.0), level=None),
    "godas_pottmp.nc": dict(var="pottmp", url=BASE + "/godas/pottmp.{year}.nc", per_year=True,
                            lat=(-7.9, 7.9), lon=(110.5, 219.5), level=(5.0, 366.0)),
    "godas_ucur.nc": dict(var="ucur", url=BASE + "/godas/ucur.{year}.nc", per_year=True,
                          lat=(-7.9, 8.0), lon=(110.0, 220.0), level=(5.0, 95.0)),
    "ncep_uwnd850.nc": dict(var="uwnd", url=BASE + "/ncep.reanalysis/Dailies/pressure/uwnd.{year}.nc",
                            per_year=True, lat=(-7.5, 7.5), lon=(110.0, 190.0), level=(850.0, 850.0)),
}


def urls(name, first=FIRST_YEAR, last=LAST_YEAR):
    spec = SPECS[name]
    if not spec["per_year"]:
        return [(None, spec["url"])]
    return [(y, spec["url"].format(year=y)) for y in range(first, last + 1)]
