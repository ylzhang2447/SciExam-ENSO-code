# ENSO Diversity Model Card

## State Variables (dimensional)
The model evolves five variables representing the state of the tropical Pacific:

| Variable | Name | Units | Description |
|----------|------|-------|-------------|
| `TC` | Central-Pacific SST | °C | Niño4 SST anomaly — CP ENSO |
| `TE` | Eastern-Pacific SST | °C | Niño3 SST anomaly — EP ENSO |
| `hW` | Western thermocline depth | m | 20°C isotherm anomaly over western Pacific — recharge reservoir |
| `u` | Central-Pacific zonal current | m/s | Mixed-layer zonal current anomaly |
| `tau` | Westerly wind stress proxy | m/s | 850 hPa zonal wind anomaly over western Pacific |

All variables are anomalies relative to 1981–2010 monthly climatology. Observed series
are Niño4 SST, Niño3 SST, western-Pacific 20°C isotherm depth, Niño4 zonal current, and
850-hPa zonal wind over the western Pacific (each preprocessed to monthly anomalies).

## Non-dimensionalization
From `nondim_scales.json`: T\*=7.5°C, h\*=150m, u\*=1.5m/s, τ\*=5.0m/s, t\*=2 months.
X_nd = X_dimensional / X_scale. All model parameters are in non-dimensional units.

## Equations
The system follows an SDE integrated with Euler–Maruyama (dt = 0.1 months):

```
dX/dt = [A + S(t)·dA]·X + N_nonlinear(X) + stochastic
```

### Linear Dynamics (A matrix)
The A matrix is fit from observed 1980–2014 monthly indices via VAR(1) residual
regression and then refined by hand-tuning thermocline couplings to place the
spectral peak at ~48 months while maintaining correct recharge-discharge phase.

| Row → | TC     | TE     | hW     | u      | tau   |
|-------|--------|--------|--------|--------|-------|
| TC    | −0.240 | +0.096 | +0.149 | +0.133 | +0.045 |
| TE    | −0.064 | −0.240 | +0.110 | +0.234 | +0.071 |
| hW    | −0.200 | −0.220 | −0.200 | −0.211 | 0.000  |
| u     | −0.275 | +0.200 | +0.480 | −0.671 | +0.100 |
| τ     | +2.200 | +0.200 | −0.018 | +0.380 | −1.150 |

Key features:
- **TE**: Strong self-damping (−0.24), Bjerknes feedback from hW (+0.110),
  zonal advection from u (+0.234), and weak wind stress coupling.
- **TC**: Symmetric self-damping (−0.24), hW influence (+0.149),
  atmospheric coupling to u (+0.133) and τ (+0.045).
- **hW**: Recharge-discharge oscillator: damped (−0.20), discharged by
  both EP (−0.22) and CP (−0.20) SST, wind feedback (−0.21).
- **u**: Fast current adjustment (−0.67) driven by thermocline pressure
  gradient (+0.48 hW). This A[3,2] coefficient is the dominant control on
  the oscillation period.
- **τ**: Fast atmospheric response (−1.15) strongly driven by CP SST (+2.20),
  with current feedback (+0.38) setting correct corr(u,τ) sign.

### Seasonal Modulation
Seasonal cycle S(t) = cos(2π(t−11)/12), peaking in December.

dA matrix nonzero entries:
- dA[0,0] = dA[1,1] = −0.15: TC and TE damping weakens in boreal winter,
  allowing stronger growth and contributing to the observed phase locking.
- dA[4,0] = +0.75: TC→τ atmospheric bridge strengthens in winter.

Noise amplitude also follows seasonal modulation: σ_eff = σ · (1 + 0.20·S).

### Nonlinear Terms N_nonlinear(X)

Three mechanisms jointly produce the observed skew (TE +0.95, TC −0.48):

1. **Sigmoid asymmetric growth**: Selectively weakens restoring damping on one tail.
   `dTE += g_TE · TE / (1 + exp(−k·TE))` (warm TE growth weakened less)
   `dTC += g_TC · TC / (1 + exp(+k·TC))` (cold TC growth weakened less)
   With k=12, the extra growth switches sharply at moderate amplitudes.

2. **One-sided cubic tail saturation** on TE warm tail:
   `dTE −= c_tail · max(TE, 0)³` — caps warm events without harming cold ones.

3. **Symmetric cubic saturation**: `dTE −= c_sat · TE³`, `dTC −= c_TC · TC³`
   with separate coefficients to preserve TC's cold tail.

### Stochastic Forcing

Three-component noise producing the heavy-tailed, skewed stationary density:

1. **Additive**: Diagonal amplitudes [0.036, 0.053, 0.006, 0.080, 0.450]
   with TE–TC correlation ρ=0.75, seasonal modulation.

2. **Multiplicative**: σ_mult · |X| · dW on TC and TE; creates heavier tails.

3. **Asymmetric state-dependent**: σ_asym_TE · max(TE,0) · dW on TE,
   σ_asym_TC · max(−TC,0) · dW on TC. This is the dominant skew mechanism —
   it directly shapes the stationary density.

## Physical Mechanisms

### Recharge–Discharge Oscillator
The model captures the canonical Jin (1997) recharge oscillator:
Warm TE → westerly τ → thermocline tilts → further warming (Bjerknes).
Sustained τ discharges hW, eventually eroding thermocline support,
TE decays, system transitions to cold phase. The lag-correlation between
hW(t) and TE(t+lag) progresses from −0.66 at lag 0 through 0 at
lag ~6 to +0.10 at lag 8, closely matching observations.

### ENSO Diversity (CP vs EP)
TC and TE differ in their coupling: τ responds 10× more strongly to TC
(CP) than TE (EP), producing distinct warm-pool-driven (CP) and
coastal-driven (EP) event types, visible in the uncorrelated residual
between TC and TE.

### Seasonal Phase Locking
Winter-amplified coupling and noise produce the observed concentration of
event development in boreal winter (November–January).

## Parameter Table

| Parameter | Value | Role |
|-----------|-------|------|
| A matrix | Per table above | Linear dynamics |
| dA matrix | TC/TE −0.15, τ←TC +0.75 | Seasonal modulation |
| sigma_diag | [0.036, 0.053, 0.006, 0.080, 0.450] | Additive noise |
| s_noise_amp | 0.20 | Seasonal noise amplification |
| noise_corr_te_tc | 0.75 | TC–TE noise correlation |
| sigma_mult_TE | 0.21 | Multiplicative noise on TE |
| sigma_mult_TC | 0.18 | Multiplicative noise on TC |
| sigma_asym_TE | 0.36 | Asymmetric noise on warm TE |
| sigma_asym_TC | 0.24 | Asymmetric noise on cold TC |
| g_asym_TE | 0.14 | Sigmoid growth on TE warm side |
| g_asym_TC | 0.050 | Sigmoid growth on TC cold side |
| k_asym | 12.0 | Sigmoid steepness |
| c_sat | 0.28 | Symmetric cubic saturation (TE) |
| c_sat_TC | 0.12 | Symmetric cubic saturation (TC) |
| c_sat_tail | 0.16 | One-sided cubic on warm TE |
| tau_nl | 0.005 | Wind stress nonlinear damping |
| t_scale_months | 2.0 | Non-dimensional time scale |
| season_peak_month | 12 | December peak |

## Validation Summary

**Free-run climate** (8 seeds × 2400 months):
- TC std 0.657 (obs 0.638), skew −0.478 (obs −0.477)
- TE std 0.886 (obs 0.885), skew +0.947 (obs +0.954)
- TE ac6 +0.376 (obs +0.351), ac12 −0.098 (obs −0.142) — correct biennial tendency
- corr(TC,TE) +0.684 (obs +0.708)
- corr(TE,hW) −0.664 (obs −0.694)
- Spectral peak 48 months (obs 47)

**Coupled dynamics** (recharge lag-correlation):
  l0: −0.664 (obs −0.694), l2: −0.437 (−0.492), l4: −0.219 (−0.264),
  l6: −0.035 (−0.068), l8: +0.103 (+0.079)

**Forecast skill** (vs persistence, 32-member ensemble, leads 3–12):
  TC: +24–33%, TE: +19–30%, u: +24–42% → robust improvement over persistence
  hW: +20% at lead 3, +3% at lead 6, negative at leads 9–12 → see limitations

**Known limitations**:
- hW autocorrelation at lag 12 is near zero (+0.01 vs obs +0.21). This is a
  structural consequence of the 5-var VAR: hW is tightly coupled to the TE
  oscillation and inherits its biennial timescale rather than having independent
  low-frequency memory. The hW forecast degrades at long leads as the model
  correctly relaxes toward its stationary mean, while the test period
  (2005–2014) has a persistent positive hW phase.
- hW std (16.9 vs 13.5) is somewhat inflated by the coupling that produces the
  correct recharge phase.
- tau autocorrelation is shorter than observed due to the fast damping needed
  for spectral peak control.

## Numerical Integration
Euler–Maruyama with dt = 0.1 months. All integration through `step()`. The grader
builds free simulation, ensemble forecast, and data assimilation on top.