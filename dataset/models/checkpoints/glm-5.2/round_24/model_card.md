# ENSO Stochastic Conceptual Model

## State Variables

The model state is a 5-variable vector in dimensional units:

| Variable | Description | Unit |
|----------|-------------|------|
| TC | Central Pacific SST anomaly (Niño 4 region) | °C |
| TE | Eastern Pacific SST anomaly (Niño 3 region) | °C |
| hW | Western Pacific thermocline depth anomaly | m |
| u | Central Pacific zonal current anomaly | m/s |
| tau | Western Pacific 850 hPa zonal wind anomaly | m/s |

## Equations

The model is an extended recharge oscillator based on Jin (1997), nondimensionalized
using scales T=7.5°C, h=150m, u=1.5m/s, tau=5m/s, t=2 months. All equations
below are in nondimensional units.

### Wind stress (tau)
Fast relaxation toward SST-driven equilibrium with stochastic forcing,
nonlinear wind-SST coupling, and asymmetric cubic damping:
```
d(tau)/dt = -r_tau * (tau - tau_eq) - en_tau_asym * tau^3 + sigma_tau * mult_factor * s_noise * dW
tau_eq = mu * (b_E*TE + b_C*TC + nw_E*TE^2) * s(t)
en_tau_asym = en_tau_pos  if tau > 0   (damps westerly anomalies)
            = en_tau_neg  if tau <= 0  (light damping on easterlies)
```
- **Asymmetric cubic wind damping** (en_tau_pos=0.9 > en_tau_neg=0.15): Damps
  positive (westerly) wind anomalies more strongly than easterlies, reducing the
  positive skew of tau toward the observed near-zero value.
- **Quadratic wind coupling** (`nw_E*TE^2`): Stronger westerly forcing during
  warm events.
- **Multiplicative noise** (`mult_factor = 1 + mult_noise * max(TE,0)`):
  Increases stochastic wind variance during warm events, contributing to
  positive TE skewness.

### Thermocline (hW)
Recharge-discharge dynamics driven by wind stress:
```
d(hW)/dt = -r * hW - a * tau_eff
```
where `tau_eff = slope * tau_ocean` and `tau_ocean` combines the deterministic
SST-driven wind and a fraction (noise_to_ocean) of the stochastic component.

### Thermocline depths (Sverdrup balance)
```
hE = hW + tau_eff           (eastern Pacific)
hC = hW + hC_frac * tau_eff (central Pacific)
```
The `hC_frac` parameter controls the fraction of wind-driven tilt felt by the
central Pacific thermocline, decoupling CP and EP variability.

### SST (TE, TC)
Saturating thermocline feedback with asymmetric saturation and asymmetric cubic damping:
```
d(TE)/dt = -c_E*TE + gamma_E*fb_E*s(t) - damp_TE*TE^3 + nl_TE*TE*max(hE,0)
d(TC)/dt = -c_C*TC + gamma_C*fb_C*s(t) - damp_TC*TC^3 + alpha_CE*TE - delta_C*u
fb_E = h_sat_E * tanh(hE / h_sat_E)
fb_C = h_sat_C * tanh(hC / h_sat_C)
h_sat_E = h_sat_E_pos  if hE > 0   (broad warm thermocline response)
        = h_sat_E_neg  if hE <= 0  (limited cold response)
damp_TE = en_TE_pos  if TE > 0     (stronger warm damping)
        = en_TE_neg  if TE <= 0   (weaker cold damping)
damp_TC = en_TC_pos  if TC > 0     (stronger warm CP damping)
        = en_TC_neg  if TC <= 0   (weaker cold CP damping)
```
Key nonlinearity:
- **Asymmetric saturation**: h_sat_E_pos=1.0, h_sat_E_neg=0.15. Cold thermocline
  anomalies saturate quickly (limited La Niña thermocline feedback), while warm
  anomalies have a broader response.
- **Asymmetric cubic damping on TE**: en_TE_pos=62 > en_TE_neg=25. Stronger
  damping on warm EP events limits their frequency.
- **Asymmetric cubic damping on TC**: en_TC_pos=25 > en_TC_neg=2. Strong damping
  on warm CP SST creates negative TC skew.
- **Nonlinear Bjerknes feedback** (nl_TE): Extra warming when both SST and
  thermocline are warm (`TE * max(hE,0)`), amplifying warm events.
- **Reduced CP linear damping** (c_C=0.25): Lower than c_E to maintain TC
  autocorrelation and variance without white noise injection.
- **TC noise** (sigma_TC=0.02): Small independent stochastic forcing on CP SST.

### Zonal current (u)
```
d(u)/dt = -r_u*u + alpha_u*tau + beta_u*hW + sigma_u*s_noise*dW
```
Wind-driven (alpha_u) and thermocline-driven (beta_u), with stochastic forcing.
The beta_u term creates the observed positive u-hW correlation.

### Seasonal modulation
```
s(t) = 1 + season_amp * cos(2*pi*t/12 + season_phase)     (coupling)
s_noise(t) = 1 + noise_season_amp * cos(2*pi*t/12 + noise_season_phase)  (noise)
```
Coupling strength is modulated by the annual cycle, peaking in boreal winter
(December) for phase locking. Noise amplitude has an independent seasonal cycle.

## Mechanisms

1. **Bjerknes feedback**: SST anomaly → wind anomaly → thermocline tilt → SST
   amplification. The nonlinear wind coupling (nw_E) and nonlinear Bjerknes
   feedback (nl_TE) strengthen this for warm events.
2. **Recharge-discharge**: Wind stress → Sverdrup transport → western thermocline
   adjustment → phase transition. The delayed thermocline response creates the
   oscillation.
3. **ENSO diversity**: Two SST boxes (CP and EP) with different thermocline
   feedback strengths. hC_frac=0.35 decouples central from eastern Pacific.
   Reduced c_C and minimal sigma_TC maintain TC autocorrelation.
4. **Seasonal phase locking**: Coupling modulated by annual cycle, peaking in
   boreal winter (December). Independent noise seasonal cycle captures spring
   variance peaks. TC and TE peak months match observations.
5. **Nonlinear asymmetry**: Multiple mechanisms create positive TE skew:
   - Asymmetric thermocline saturation (h_sat_E_neg << h_sat_E_pos)
   - Asymmetric cubic damping (en_TE_pos > en_TE_neg for warm events)
   - Asymmetric wind damping (en_tau_pos > en_tau_neg, reducing tau skew)
   - Multiplicative noise on wind (stronger during warm events)
   - Nonlinear Bjerknes feedback (nl_TE term)
6. **Stochastic forcing**: Wind noise sustains the damped oscillation. A fraction
   of the stochastic wind forcing feeds into ocean dynamics (noise_to_ocean).

## Parameters

Calibrated to match observed statistics (1980-2000 training period). Key parameters:
- mu=0.32, c_E=0.35, c_C=0.25 (coupling and SST damping)
- slope=2.5, r=0.25, a=0.155 (Jin 1997 ocean adjustment)
- en_TE_pos=62, en_TE_neg=25, nl_TE=5.0 (asymmetric TE damping + nonlinear feedback)
- en_TC_pos=25, en_TC_neg=2, sigma_TC=0.02 (asymmetric TC damping + minimal noise)
- en_tau_pos=0.9, en_tau_neg=0.15 (asymmetric cubic wind damping)
- nw_E=1.0, mult_noise=5.0 (nonlinear wind coupling + multiplicative noise)
- h_sat_E_pos=1.0, h_sat_E_neg=0.15 (asymmetric thermocline saturation)
- hC_frac=0.35, alpha_CE=0.05 (CP-EP decoupling)
- gamma_C=0.55 (central Pacific thermocline feedback)
- season_amp=0.5, season_phase=-6.0 (boreal winter December coupling peak)
- noise_season_amp=0.5, noise_season_phase=2 (spring noise peak)
- r_tau=0.40, sigma_tau=0.31 (wind relaxation and stochastic forcing)
- noise_to_ocean=0.22 (fraction of noise coupling to ocean)
- r_u=1.2, alpha_u=0.2, beta_u=1.5, sigma_u=0.10 (zonal current)

## Model Performance

Key statistics (sim vs obs, training 1980-2000):
- TE std: 0.86 vs 1.01
- TE skew: 0.73 vs 1.07
- TC std: 0.61 vs 0.63
- TC skew: -0.33 vs -0.50
- hW std: 13.6 vs 13.8
- hW skew: -0.31 vs -0.56
- tau std: 1.92 vs 1.92
- tau skew: 0.27 vs 0.14
- u std: 0.17 vs 0.15
- TC AC3: 0.78 vs 0.85
- TE AC3: 0.61 vs 0.77
- hW AC3: 0.86 vs 0.84
- tau AC3: 0.39 vs 0.52
- TC/TE peak month: 12 (matches obs 12, pattern_corr=0.97)
- corr(TC,TE): 0.75 vs 0.72
- corr(TE,hW): -0.55 vs -0.76
- corr(u,hW): 0.55 vs 0.40
- EP El Niño: 24% vs 18%
- La Niña: 30% vs 27%
- Extreme events: 10% vs 9%
- Forecast: beats persistence on RMSE at all leads 3-12 for TE, TC, hW, u
- TE lead-6: model RMSE 0.62 vs persistence 0.70 (12% better)
- TE lead-9: model RMSE 0.78 vs persistence 0.88 (11% better)
- TE lead-12: model RMSE 0.73 vs persistence 1.06 (31% better)
- Stability: all finite, reproducible, stable at dt=0.1/0.25/0.5
