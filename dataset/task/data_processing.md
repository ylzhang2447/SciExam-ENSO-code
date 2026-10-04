# Task Section: Data Processing (Phase 1)

The raw observational data is provided in `data/` (see below). Process it into the
five monthly indices using EXACTLY the method specified here. This is a fixed,
deterministic recipe: your indices are checked element-wise against a reference
processed the same way, so follow every step precisely (regions, base period,
isotherm method, averaging). A wrong region, unit, sign, or base period will fail
the check; a correct implementation matches to numerical precision.

The provided data covers **1980-01 to 2014-12**. The later years are held out for the
prediction stage and are intentionally absent; process the full provided period.

## Provided raw data (`data/`)

1. **SST** (ERSST v5, monthly, 2 degree grid) : sea surface temperature.
2. **Ocean** (GODAS, monthly) : potential temperature on depth levels, and zonal
   current on depth levels.
3. **Wind** (NCEP-NCAR reanalysis, daily) : zonal wind at 850 hPa.

## The five indices (model variable in parentheses)

All regional averages are **cosine-of-latitude weighted**, over the exact boxes below
(longitudes in 0 to 360; e.g. 150 degrees W = 210 degrees E).

- **Niño4 (TC)** : SST, box 160 E to 210 E, 5 S to 5 N.
- **Niño3 (TE)** : SST, box 210 E to 270 E, 5 S to 5 N.
- **hW** : 20 degree C isotherm depth, box 120 E to 180 E, 5 S to 5 N. For each water
  column, find the depth where potential temperature crosses 20 degrees C by LINEAR
  interpolation between the two adjacent GODAS levels bracketing the first crossing
  from the surface; columns with no crossing are NaN. Then take the box average of
  the isotherm depth.
- **u** : zonal current, box 160 E to 210 E, 5 S to 5 N, averaged over the mixed layer
  (mean of the levels from the surface down to 55 m), then box-averaged.
- **tau** : 850 hPa zonal wind, box 120 E to 180 E, 5 S to 5 N. Box-average the daily
  wind, then take the monthly mean. Positive is westerly.

## Anomalies

For every index, remove the **monthly-mean climatology over the fixed 1981-2010 base
period**: for each calendar month, subtract that month's 1981-2010 average. Same base
period for all five. Remove the monthly climatology only, no additional detrending.

## Output

`processed/indices.csv` with a `time` column (monthly) and columns `TC, TE, hW, u,
tau`, over the provided 1980-01 to 2014-12 period. Also write `processed/
processing_notes.md` describing what you did (for the record).

## Tips and pitfalls

- **Fill values and masks** : NOAA netCDF files use fill values (e.g. 1e20,
  -9.96e36) and land masks. Convert `_FillValue` / `missing_value` to NaN before any
  averaging, or regional means are corrupted by huge numbers.
- **NaN** : use NaN-aware reductions (`nanmean`) for spatial averages; exclude land
  points. Do not let NaN or inf propagate into the indices.
- **Longitude convention** : several boxes cross the dateline (Niño4 is 160 E to
  210 E). Be consistent with 0 to 360; a wrong slice silently yields the wrong index.
- **Units** : GODAS potential temperature is in Kelvin; convert to Celsius before
  finding the 20 degree C isotherm.
- **Time axes** : SST and ocean are monthly, wind is daily. Average the wind over the
  box first, then reduce to monthly means on a consistent monthly axis.
- **Averaging** : weight spatial averages by cos(latitude). Slice the boxes directly
  on the native grid (do not regrid to a finer mesh first).
