# ENSO Diversity Model Card

## State Variables (dimensional)
The model evolves five variables representing the state of the tropical Pacific:

| Variable | Name | Units | Description |
|----------|------|-------|-------------|
| `TC` | Central-Pacific SST | °C | Niño4 SST anomaly (160°E–210°E, 5°S–5°N) — represents CP ENSO |
| `TE` | Eastern-Pacific SST | °C | Niño3 SST anomaly (210°E–270°E, 5°S–5°N) — represents EP ENSO |
| `hW` | Western thermocline depth | m | 20°C isotherm anomaly over western Pacific (120°E–180°E, 5°S–5°N) — warm pool / recharge reservoir |
| `u` | Central-Pacific zonal current | m/s | Mixed-layer zonal current anomaly (160°E–210°E, 5°S–5°N) |
| `tau` | Westerly wind stress proxy | m/s | 850 hPa zonal wind anomaly over western Pacific (120°E–180°E, 5°S–5°N) |

All variables are anomalies relative to the 1981–2010 monthly climatology.

## Non-dimensionalization
Characteristic scales from `nondim_scales.json`:
- Temperature: T* = 7.5 °C
- Thermocline depth: h* = 150 m
- Zonal current: u* = 1.5 m/s
- Wind: τ* = 5.0 m/s
- Time: t* = 2 months

Non-dimensional variables: X_nd = X_dimensional / X_scale. All model parameters are in non-dimensional units (2-month timescale).

## Equations

The system follows a stochastic differential equation (SDE) of the form:

```
dX/dt = (A + S(t) · dA) · X + N(X) + B · η(t)
```

### Linear Dynamics (A matrix)
The linear drift matrix A (5×5) is calibrated from a vector autoregression (VAR(1)) fit to the observed monthly indices over 1980–2014. This ensures that the basic oscillation period (~4 years), inter-variable coupling structure, and damping timescales match observations. Key features:

- **TE (row 1):** Moderately damped (−0.10) with positive thermocline feedback (+0.11 hW), CP cross-influence, zonal advection, and tilt from wind stress (+0.07 via hE = hW + b·τ)
- **TC (row 0):** Moderately damped (−0.17) with weaker thermocline coupling (+0.15 hW), stronger cross-region influence from EP (+0.10 TE), and direct wind response
- **hW (row 2):** Recharge-discharge dynamics: damped (−0.16) with discharge from EP SST (−0.15 TE, via atmospheric bridge) and from wind stress (−0.06 τ), plus CP recharging (+0.09 TC)
- **u (row 3):** Fast adjustment (−0.67) driven primarily by thermocline pressure gradient (+0.78 hW), with weaker wind and EP SST contributions
- **τ (row 4):** Fast atmospheric response (−1.06) primarily to CP SST (+2.50 TC) with secondary EP contribution (+0.20 TE) and current feedback (+0.28 u)

### Seasonal Modulation (dA matrix × cos(2π(t−Dec)/12))
Seasonal variations in coupling strength peak in December–January (boreal winter), when ENSO variance is maximized. The modulation matrix dA enhances:
- SST growth rates (both CP and EP), especially TE
- Wind–SST coupling (atmospheric sensitivity to SST)
- Thermocline–current coupling
- Noise amplitude (via `s_noise_amp = 0.40`)

### Nonlinear Terms N(X)
1. **Quadratic skew:** `dTE/dt += asym_TE * TE²` (asym_TE > 0) — positive quadratic feedback amplifies warm El Niño events more than cold La Niña events, producing the observed positive TE skew. The term is non-negative and capped by linear damping.

2. **SST-dependent growth:** `dTC/dt += asym_TC * TC·|TC|` (asym_TC < 0) — negative cubic-damping makes cold CP events persist longer, contributing to La Niña dominance in the central Pacific (negative TC skew).

3. **Wind saturation:** Cubic damping on τ provides a soft bound on wind stress at extreme values.

### Stochastic Forcing B · η(t)
Three categories of stochastic forcing are applied:

1. **Additive noise:** Diagonal noise amplitudes (σ_TC, σ_TE, σ_hW, σ_u, σ_τ) with TE–TC correlation (ρ ≈ 0.35) from shared atmospheric sources. Noise is seasonally modulated (amplified in boreal winter).

2. **Multiplicative (state-dependent) noise:** `σ_mult · |X| · dW` — state-dependent noise on TC and TE creates heavier tails than Gaussian.

3. **Asymmetric noise:** `σ_asym · max(TE, 0) · dW` — noise amplitude depends only on positive TE, not negative. This introduces an explicit asymmetry: warm events face larger stochastic perturbations → larger warm excursions → positive TE skew. Similarly, `σ_asym · max(−TC, 0) · dW` amplifies noise during cold CP phases → negative TC skew.

## Physical Mechanisms

### Recharge–Discharge Oscillator (Jin 1997)
The core mechanism follows the recharge oscillator paradigm. Warm eastern Pacific SST (TE > 0) induces westerly wind anomalies (τ > 0) via the atmospheric Gill response. These winds tilt the equatorial thermocline — deepening in the east (positive hE), shoaling in the west (negative hW) — which further warms TE through enhanced upwelling feedback. This is the Bjerknes positive feedback.

Simultaneously, the sustained westerly wind stress discharges the warm pool (hW becomes more negative over months), gradually reducing the thermocline depth anomaly available to sustain TE. When hW has discharged sufficiently, TE begins to decay, and the system transitions toward a cold phase. The opposite process (trade wind strengthening, warm pool recharging) drives the La Niña phase. The cycle period is determined by the balance between the rapid Bjerknes growth and the slow recharge timescale.

### ENSO Diversity (Central vs Eastern Pacific)
The model represents ENSO diversity through two distinct SST indices (TC and TE) that are coupled through:

1. **Atmospheric bridge:** TC influences TE via cross-region atmospheric teleconnections (cross_CE = 0.096), and TE influences TC reciprocally (cross_EC = 0.10).

2. **Differential wind sensitivity:** τ responds preferentially to TC (β_TC = 2.50 ≫ β_TE = 0.20), reflecting the empirical finding that central-Pacific SST anomalies are more effective at driving basin-scale wind anomalies than eastern-Pacific anomalies.

3. **Differential thermocline sensitivity:** TC responds to the western thermocline depth (hW) directly, while TE responds to the eastern thermocline depth (hE = hW + b·τ) which includes the wind-driven tilt component.

This structure allows for both CP-dominated events (large TC, moderate TE) and EP-dominated events (large TE, modest TC), as well as canonical events where both indices evolve together.

### Seasonal Phase Locking
ENSO events tend to peak in boreal winter (November–January). This phase locking arises from the seasonal modulation of ocean–atmosphere coupling strength. The dA matrix peaks the Bjerknes growth rate, thermocline feedback, and wind response during December, synchronizing event development with the calendar year.

### El Niño / La Niña Asymmetry
El Niño events are typically stronger than La Niña events (positive skew in TE). In this model, the asymmetry arises from:

- Asymmetric state-dependent noise (larger stochastic perturbations during warm phases)
- Positive quadratic nonlinearity in TE (warm SST increases growth more than cold SST)
- The different sensitivity of wind response to CP vs EP SST anomalies (cold EP events are partially offset by CP dynamics)

## Numerical Integration
The model uses Euler–Maruyama integration with a fixed time step dt (typically 0.1 months ≈ 0.05 non-dimensional units). The step() method is the single source of truth: the grader builds free simulation, ensemble forecasting, and data assimilation on top of it.

## Parameters
All calibrated parameters are provided in `params.json`. The linear dynamics (A and dA matrices) were empirically estimated from the 1980–2014 monthly indices. Noise amplitudes were calibrated from the VAR(1) residual covariance. Nonlinear and seasonal parameters were tuned to match observed skewness, seasonal variance ratios, and cross-correlation patterns.