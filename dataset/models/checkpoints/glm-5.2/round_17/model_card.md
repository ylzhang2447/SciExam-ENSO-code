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
d(tau)/dt = -r_tau * (tau - tau_eq) + sigma_tau * mult_factor * s_noise * dW
tau_eq = mu * (b_E*TE + b_C*TC + nw_E*TE^2) * s(t)
```
The quadratic wind coupling term `nw_E*TE^2` creates stronger westerly wind
forcing during warm events. Multiplicative noise (`mult_factor = 1 + mult_noise * max(TE,0)`)
increases stochastic wind variance during warm events, contributing to the
positive skewness of ENSO.

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
d(TE)/dt = -c_E*TE + gamma_E*tanh(hE/h_sat_E)*h_sat_E*s(t)
           - damp_TE*TE^3 + nl_TE*TE*max(hE,0)
d(TC)/dt = -c_C*TC + gamma_C*tanh(hC/h_sat_C)*h_sat_C*s(t)
           - damp_TC*TC^3 + alpha_CE*TE - delta_C*u
```
Key nonlinearity:
- **Asymmetric saturation**: h_sat_E_pos=1.0, h_sat_E_neg=0.15. Cold thermocline
  anomalies saturate quickly (limited La Niña thermocline feedback), while warm
  anomalies have a broader response.
- **Asymmetric cubic damping**: damp_TE = en_TE_pos for TE>0, en_TE_neg for TE<0.
  Different damping rates for warm vs cold SST.
- **Nonlinear Bjerknes feedback** (nl_TE): Extra warming when both SST and
  thermocline are warm (`TE * max(hE,0)`), amplifying warm events.
- **TC noise** (sigma_TC): Independent stochastic forcing on CP SST decouples
  TC from TE, matching the observed correlation ~0.72.

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
for phase locking. Noise amplitude has an independent seasonal cycle.

## Mechanisms

1. **Bjerknes feedback**: SST anomaly → wind anomaly → thermocline tilt → SST
   amplification. The nonlinear wind coupling (nw_E) and nonlinear Bjerknes
   feedback (nl_TE) strengthen this for warm events.
2. **Recharge-discharge**: Wind stress → Sverdrup transport → western thermocline
   adjustment → phase transition. The delayed thermocline response creates the
   oscillation.
3. **ENSO diversity**: Two SST boxes (CP and EP) with different thermocline
   feedback strengths. hC_frac=0.35 decouples central from eastern Pacific.
   sigma_TC adds independent CP variability.
4. **Seasonal phase locking**: Coupling modulated by annual cycle, peaking in
   boreal winter. Independent noise seasonal cycle captures spring variance peaks.
5. **Nonlinear asymmetry**: Three mechanisms create positive TE skew:
   - Asymmetric thermocline saturation (h_sat_E_neg << h_sat_E_pos)
   - Asymmetric cubic damping (en_TE_pos > en_TE_neg for warm events)
   - Multiplicative noise on wind (stronger during warm events)
   - Nonlinear Bjerknes feedback (nl_TE term)
6. **Stochastic forcing**: Wind noise sustains the damped oscillation. A fraction
   of the stochastic wind forcing feeds into ocean dynamics (noise_to_ocean).

## Parameters

Calibrated to match observed statistics (1980-2000 training period). Key parameters:
- mu=0.35, c_E=0.35, c_C=0.4 (coupling and SST damping)
- slope=2.5, r=0.25, a=0.125 (Jin 1997 ocean adjustment)
- en_TE_pos=42, en_TE_neg=25, nl_TE=3.25 (asymmetric damping + nonlinear feedback)
- nw_E=1.0, mult_noise=10.0 (nonlinear wind coupling + multiplicative noise)
- h_sat_E_pos=1.0, h_sat_E_neg=0.15 (asymmetric thermocline saturation)
- hC_frac=0.35, sigma_TC=0.06 (CP-EP decoupling)
- gamma_C=0.55, alpha_CE=0.05 (central Pacific coupling)
- season_amp=0.4, season_phase=-5.5 (boreal winter coupling peak)
- noise_season_amp=0.5, noise_season_phase=2 (spring noise peak)
- r_tau=0.7, sigma_tau=0.35 (wind relaxation and stochastic forcing)
- noise_to_ocean=0.18 (fraction of noise coupling to ocean)
- r_u=1.2, alpha_u=0.2, beta_u=1.5, sigma_u=0.12 (zonal current)

## Model Performance

Key statistics (sim vs obs):
- TE std: 0.97 vs 1.01
- TE skew: 0.95 vs 1.07 (PDF diagnostic: "ok")
- hW std: 14.5 vs 13.8
- corr(TC,TE): 0.73 vs 0.72
- corr(u,hW): 0.39 vs 0.40
- EP El Niño: 24% vs 18%
- La Niña: 28% vs 27%
- Extreme events: 12% vs 9%
- TE forecast lead-6: beats persistence by 4% RMSE
- Stability: all finite, variance ratio 1.00
- Period: 59 months vs 63 months
