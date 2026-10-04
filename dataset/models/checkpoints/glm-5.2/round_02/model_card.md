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

The model is an extended recharge oscillator based on Jin (1997), nondimensionalized using scales T=7.5°C, h=150m, u=1.5m/s, tau=5m/s, t=2 months.

### Wind stress (tau)
Fast relaxation toward SST-driven equilibrium with stochastic forcing:
```
d(tau)/dt = -r_tau * (tau - mu * (b_E*TE + b_C*TC) * s(t)) + sigma_tau * dW
```
where s(t) is the seasonal modulation factor.

### Thermocline (hW)
Recharge-discharge dynamics driven by wind stress:
```
d(hW)/dt = -r * hW - a * slope * tau_ocean
```
where `tau_ocean` combines the deterministic SST-driven wind and a reduced fraction (10%) of the stochastic component, preventing noise from disrupting the oscillation.

### Thermocline depths (Sverdrup balance)
```
hE = hW + slope * tau_ocean    (eastern Pacific)
hC = hW + 0.5 * slope * tau_ocean  (central Pacific)
```

### SST (TE, TC)
Saturating thermocline feedback with asymmetric saturation and cubic damping:
```
d(TE)/dt = -c_E * TE + gamma_E * tanh(hE/h_sat) * h_sat * s(t) - en_TE * TE³
d(TC)/dt = -c_C * TC + gamma_C * tanh(hC/h_sat) * h_sat * s(t) - en_TC * TC³
           + alpha_CE * TE - delta_C * u
```
The tanh saturation limits the thermocline feedback for large anomalies (Jin's nonlinearity). Asymmetric saturation scales (h_sat_E_pos > h_sat_E_neg) create El Niño / La Niña asymmetry.

### Zonal current (u)
```
d(u)/dt = -r_u * u + alpha_u * tau + beta_u * hW
```
Wind-driven and thermocline-driven components.

### Seasonal modulation
```
s(t) = 1 + season_amp * cos(2π * t / 12 months + season_phase)
```
Coupling strength is modulated by the annual cycle, peaking in boreal winter (December) for phase locking.

## Mechanisms

1. **Bjerknes feedback**: SST anomaly → wind anomaly → thermocline tilt → SST amplification
2. **Recharge-discharge**: Wind stress → Sverdrup transport → western thermocline adjustment → phase transition
3. **ENSO diversity**: Two SST boxes (CP and EP) with different thermocline feedback strengths
4. **Seasonal phase locking**: Coupling modulated by annual cycle, strongest in boreal winter
5. **Nonlinear saturation**: Tanh thermocline feedback limits growth; asymmetric saturation creates El Niño/La Niña asymmetry
6. **Stochastic forcing**: Wind noise sustains the damped oscillation; reduced noise-to-ocean coupling preserves oscillation coherence

## Parameters

Calibrated to match observed statistics (1980-2000 training period). Key parameters:
- mu=0.33 (subcritical coupling, stochastically sustained)
- c_E=c_C=0.3 (low SST damping for ~4-year period)
- r=0.25, a=0.125 (ocean adjustment, Jin 1997 values)
- en_TE=12, en_TC=6 (cubic SST damping for amplitude limitation)
- h_sat_E_pos=1.0, h_sat_E_neg=0.20 (asymmetric nonlinearity)
- season_amp=0.4, season_phase=-5 (boreal winter peak)
- sigma_tau=0.45 (stochastic wind forcing)
- noise_to_ocean=0.1 (reduced noise coupling to ocean)
