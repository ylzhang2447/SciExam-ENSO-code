# Submission interface (enso_ro_calib_001)

The task has two phases with two submissions. Phase 1 is the processed data, checked
against a hidden reference; only after it passes do you submit the Phase 2 model.

## Phase 1 submission: processed data

```
processed/
├── indices.csv            # monthly table, one row per month
└── processing_notes.md    # how each index was built
```

`indices.csv` must have a time column (`time`, `date`, or `month`; any parseable
monthly date) and one column per index with these exact names, over the full provided
period (1980-01 to 2014-12):

```
time,TC,TE,hW,u,tau
1980-01,-0.42,-0.31,3.1,0.02,-0.5
1980-02, ...
```

Units: SST anomalies TC, TE in degrees C; thermocline anomaly hW in meters; current
anomaly u in meters per second; tau the signed WP-box 850 hPa zonal wind anomaly in
meters per second. Because the method is a fixed deterministic recipe
(`data_processing.md`), the checker compares each index element-wise to a reference
processed the same way and requires an exact match within a tight numerical tolerance
(not a correlation). If any index is off it reports which one and the worst month; fix
and resubmit. The later years (2015 onward) are held out for prediction and are not in
the provided data.

## Phase 2 submission: the model

The agent submits a directory `submission/` with the files below. The grader
imports `model.py` and drives it; the agent never runs the grader or sees the
held-out data. Fixing this interface, not the model structure, is what lets many
different models be scored the same way.

```
submission/
├── model.py          # exposes the callable interface below
├── params.json       # calibrated parameters (a flat JSON object)
└── model_card.md     # short prose: state variables, equations, mechanisms
```

## `model.py` contract: an explicit stochastic model via `step`

Your model must be an explicit, runnable stochastic dynamical system, exposed as a
single one-step transition method `step`. The grader builds everything on top of it:
free simulation (statistics, physics), rolling forecasts (predictivity), and data
assimilation (physics). This is the whole model, one source of truth, so the three
scoring dimensions all see the same dynamics.

The state is the five-variable vector, in this fixed order and in DIMENSIONAL units:

```
row 0: TC   central-Pacific SST anomaly      [degrees C]
row 1: TE   eastern-Pacific SST anomaly       [degrees C]
row 2: hW   western-Pacific thermocline anom  [meters]
row 3: u    central-Pacific zonal current an  [meters/second]
row 4: tau  WP zonal wind anomaly             [meters/second]
```

```python
class ENSOModel:
    def __init__(self, params: dict):
        """params is the parsed params.json."""

    def step(self, state, dt, t, rng):
        """
        Advance the state by one stochastic step of size dt.
        state : np.ndarray shape (5, M) -- the five variables above (rows), M
                ensemble members (columns), in DIMENSIONAL units.
        dt    : time increment in MONTHS.
        t     : current time in MONTHS since the run start (for seasonal terms).
        rng   : a numpy Generator; draw all stochastic terms from it.
        Returns the advanced state, same shape (5, M), in dimensional units.
        Apply your drift (deterministic tendency) and your stochastic forcing here
        (e.g. Euler-Maruyama). You may work internally in non-dimensional units using
        nondim_scales.json, but state in and out of `step` is dimensional.
        """
```

## Notes for the interface

- The grader constructs `ENSOModel(json.load(open('params.json')))`, then drives
  `step`. If import fails, `ENSOModel` or `step` is missing, or a call raises or
  returns a non-finite or wrong-shaped array, the submission fails the hard gate.
- `step` must be reproducible: given the same `state`, `dt`, `t`, and a seeded `rng`,
  it returns the same result. The grader owns the seeds.
- How the grader uses `step`:
  - **Free run (statistics, physics):** start from the mean state (zeros), integrate
    with a fixed small `dt`, discard burn-in, sample monthly.
  - **Forecast (predictivity):** initialize the state from the observed indices at
    the initialization month (the state variables ARE the observables), then step an
    ensemble forward; no data assimilation needed to initialize.
  - **Data assimilation (physics):** the grader runs an ensemble Kalman smoother
    around `step`, observing a subset of the five variables and reconstructing the
    rest, to test the inter-variable dependence your model implies.
- Determinism of scoring lives in the grader: it fixes `dt`, run length, burn-in,
  segmentation, forecast initialization months, lead times, and the DA settings.
