# ENSO Conceptual Model Card

## State Variables
The model state is a 5-element vector in dimensional physical units:
- `TC`: Central-Pacific SST anomaly [°C] (Niño4 region: 160°E-210°E, 5°S-5°N)
- `TE`: Eastern-Pacific SST anomaly [°C] (Niño3 region: 210°E-270°E, 5°S-5°N)
- `hW`: Western-Pacific thermocline depth anomaly [m] (120°E-180°E, 5°S-5°N)
- `u`: Central-Pacific mixed-layer zonal current anomaly [m/s] (160°E-210°E, 5°S-5°N, 5-55m)
- `tau`: Western-Pacific 850 hPa zonal wind stress proxy anomaly [m/s] (120°E-180°E, 5°S-5°N)

## Dynamical Formulation
The model represents the coupled tropical Pacific atmosphere-ocean system via stochastic differential equations:
1. SST tendencies (`dTC`, `dTE`) governed by damping, thermocline upwelling feedback, and zonal advective feedback.
2. Thermocline adjustment (`dhW`) driven by western Pacific recharge/discharge via wind-driven Sverdrup transport.
3. Mixed-layer zonal current (`du`) driven by wind stress anomalies and pressure gradient / thermocline slope.
4. Zonal wind stress (`dtau`) driven by Bjerknes atmospheric convective response to SST anomalies plus stochastic weather noise.

## Calibration Status
Initial baseline model established for Phase 2A diagnostics verification. Parameter calibration and nonlinear / seasonal enhancements to be conducted in Phase 2B.
