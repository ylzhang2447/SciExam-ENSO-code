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
Fast relaxation toward SST-driven equilibrium with stochastic forcing and
nonlinear wind-SST coupling:
```
d(tau)/dt = -r_tau * (tau - tau_eq) + sigma_tau * s_noise * dW
tau_eq = mu * (b_E*TE + b_C*TC + nw_E*TE^2) * s(t)
```
The quadratic wind coupling term `nw_E*TE^2` creates stronger westerly wind
forcing during warm events, contributing to El Niño/La Niña asymmetry.

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
central Pacific thermocline.

### SST (TE, TC)
Saturating thermocline feedback with asymmetric saturation and cubic damping:
```
d(TE)/dt = -c_E*TE + gamma_E*tanh(hE/h_sat_E)*h_sat_E*s(t) - en_TE*TE^3
d(TC)/dt = -c_C*TC + gamma_C*tanh(hC/h_sat_C)*h_sat_C*s(t) - en_TC*TC^3
           + alpha_CE*TE - delta_C*u
```
The tanh saturation limits the thermocline feedback for large anomalies.
Asymmetric saturation scales (h_sat_E_pos > h_sat_E_neg) create El Niño / La
Niña asymmetry. The cubic damping provides amplitude limitation.

### Zonal current (u)
```
d(u)/dt = -r_u*u + alpha_u*tau + beta_u*hW + sigma_u*s_noise*dW
```
Wind-driven, thermocline-driven, and stochastic components.

### Seasonal modulation
```
s(t) = 1 + season_amp * cos(2*pi*t/12 + season_phase)     (coupling)
s_noise(t) = 1 + noise_season_amp * cos(2*pi*t/12 + noise_season_phase)  (noise)
```
Coupling strength is modulated by the annual cycle, peaking in boreal winter
for phase locking. Noise amplitude has an independent seasonal cycle to capture
the observed spring peak in wind and current variance.

## Mechanisms

1. **Bjerknes feedback**: SST anomaly → wind anomaly → thermocline tilt → SST
   amplification. The nonlinear wind coupling (nw_E) strengthens this for warm events.
2. **Recharge-discharge**: Wind stress → Sverdrup transport → western thermocline
   adjustment → phase transition. The delayed thermocline response creates the
   oscillation.
3. **ENSO diversity**: Two SST boxes (CP and EP) with different thermocline
   feedback strengths and saturation scales.
4. **Seasonal phase locking**: Coupling modulated by annual cycle, strongest in
   boreal winter. Independent noise seasonal cycle captures spring variance peaks.
5. **Nonlinear saturation**: Tanh thermocline feedback limits growth; asymmetric
   saturation creates El Niño/La Niña asymmetry. Cubic SST damping provides
   additional amplitude limitation.
6. **Stochastic forcing**: Wind noise sustains the damped oscillation. A fraction
   of the stochastic wind forcing feeds into ocean dynamics (noise_to_ocean),
   providing irregular variability.

## Parameters

Calibrated to match observed statistics (1980-2000 training period). Key parameters:
- mu=0.33, c_E=c_C=0.4 (moderate coupling and SST damping for ~5-year period)
- slope=2.5, r=0.25, a=0.125 (Jin 1997 ocean adjustment values)
- en_TE=15, en_TC=6 (cubic SST damping)
- nw_E=0.5 (nonlinear wind coupling for warm-event amplification)
- h_sat_E_pos=1.0, h_sat_E_neg=0.20 (asymmetric thermocline saturation)
- season_amp=0.4, season_phase=-5 (boreal winter coupling peak)
- noise_season_amp=0.5, noise_season_phase=2 (spring noise peak)
- r_tau=0.5, sigma_tau=0.35 (wind relaxation and stochastic forcing)
- noise_to_ocean=0.20 (fraction of noise coupling to ocean)
- r_u=1.5, alpha_u=0.2, beta_u=0.8, sigma_u=0.12 (zonal current)
