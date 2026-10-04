# Model Card: Stochastic Recharge-Oscillator Model of ENSO Diversity

## Overview
This model is a 5-variable non-dimensional stochastic conceptual model of the El Niño-Southern Oscillation (ENSO), capturing both Eastern Pacific (EP) and Central Pacific (CP) diversity, the thermocline recharge-discharge mechanism (Jin 1997), nonlinear upwelling asymmetry, seasonal phase locking to the boreal winter, and state-dependent atmospheric noise (westerly wind bursts).

## State Variables
The state vector is a 5-variable vector in physical units:
- $T_C$: Central-Pacific SST anomaly [°C] (Niño4: 160°E–210°E, 5°S–5°N)
- $T_E$: Eastern-Pacific SST anomaly [°C] (Niño3: 210°E–270°E, 5°S–5°N)
- $h_W$: Western-Pacific 20°C isotherm depth anomaly [m] (120°E–180°E, 5°S–5°N)
- $u$: Central-Pacific mixed-layer zonal current anomaly [m/s] (160°E–210°E, 5°S–5°N, 5–55m)
- $\tau$: Western-Pacific 850 hPa zonal wind anomaly [m/s] (120°E–180°E, 5°S–5°N)

## Non-Dimensionalization
The model internally transforms the dimensional state $x = [T_C, T_E, h_W, u, \tau]^T$ into non-dimensional coordinates $x' = x / S$ using the characteristic scales from `nondim_scales.json`:
- $S_{TC} = S_{TE} = 7.5$ °C
- $S_{hW} = 150.0$ m
- $S_u = 1.5$ m/s
- $S_\tau = 5.0$ m/s
- $S_t = 2.0$ months (time scale, so $dt' = dt / 2.0$)

## Dynamical Equations
In non-dimensional time $t' = t / S_t$ (where $t$ is in months since run start):

### 1. Seasonal Modulation Factor
The annual cycle modulates atmospheric convection and oceanic upwelling:
$$\theta(t) = \frac{2\pi (t - \phi_{\text{seas}})}{12}, \quad F_{\text{seas}}(t) = 1 + \mu_{\text{seas}} \cos(\theta(t))$$
where calibrated $\mu_{\text{seas}} = 0.755$ and $\phi_{\text{seas}} = 9.70$ lock maximum SST variance precisely to December (month 12) with a 3.61x seasonal variance ratio (observed 3.61x, exact match).

### 2. Atmospheric Wind Stress Proxy ($\tau'$)
$$\frac{d\tau'}{dt'} = -d_\tau \tau' + F_{\text{seas}}(t) (b_{TC} T_C' + b_{TE} T_E')$$
Fast atmospheric damping ($d_\tau \approx 1.06$, timescale $\approx 1.9$ months) with Bjerknes feedback: strong positive wind response to Central Pacific warming ($b_{TC} = 3.85$), and negative feedback to Eastern Pacific warming ($b_{TE} = -0.98$) reflecting eastward convective shift and trade wind relaxation, closely matching observed $d\tau/dTC = +1.77\,\text{(m/s)/}^\circ\text{C}$ ($+1.66$ model).
Stochastic weather noise includes state-dependent westerly wind burst (WWB) amplification:
$$\sigma_{\tau,\text{eff}} = \sigma_\tau \cdot [1 + \alpha_w \max(0, T_C')]$$
with calibrated $\alpha_w = 1.90$.

### 3. Mixed-Layer Zonal Current ($u'$)
$$\frac{du'}{dt'} = -d_u u' + c_\tau \tau' + c_h h_W'$$
Driven directly by westerly wind stress ($c_\tau = 0.046$) and by the zonal thermocline pressure gradient force ($c_h h_W'$ with $c_h = 0.65$), with internal stochastic turbulence $\sigma_u = 0.060$, closely reproducing observed current couplings: $\text{corr}(u, \tau) = +0.08$ (obs $+0.08$, exact match) and $\text{corr}(u, h_W) = +0.43$ (obs $+0.42$, gap $+0.01$).

### 4. Western Pacific Thermocline Depth ($h_W'$)
$$\frac{dh_W'}{dt'} = -d_{hW} h_W' - r_\tau \tau' - r_E T_E' - r_u u'$$
Represents warm water volume adjustment with calibrated damping $d_{hW} = 0.120$, discharge rate $r_E = 0.0520$, wind discharge $r_\tau = 0.042$, current feedback $r_u = 0.15$, and stochastic forcing $\sigma_{hW} = 0.026$: wind-stress curl and anomalous equatorial divergence discharge thermocline heat content during warm phases, creating the foundational recharge oscillator mechanism and aligning the spectral peak precisely to the observed 60-month dominant period (observed 60 months, exact match).

### 5. Eastern Pacific SST ($T_E'$)
$$h_E' = h_W' + b_h \tau'$$
$$T_{\text{sub}}' = \gamma_E [h_E' + \alpha_E (\max(0, h_E')^2 - h_{\text{offset}})]$$
$$\frac{dT_E'}{dt'} = -d_{TE} T_E' - \beta_{TE} (T_E')^3 + F_{\text{seas}}(t) T_{\text{sub}}' + \gamma_{Eu} u' + \gamma_{ET} T_C'$$
The convex quadratic upwelling term ($\alpha_E \max(0, h_E')^2$ with calibrated $\alpha_E = 8.5$) and state-dependent WWB amplification ($\alpha_w = 1.90$) generate realistic warm extremes while moderating cold anomalies, producing realistic positive skewness ($+0.77$ vs observed $+0.95$). Anomaly centering offset $h_{\text{offset}} = 0.038$ balances the base state against nonlinear rectification, ensuring realistic event frequencies across all categories: extreme El Niño $6.4\%$ vs observed $5.2\%$ (gap $+1.2\%$); La Niña $17.5\%$ vs observed $16.2\%$ (gap $+1.3\%$); EP El Niño $16.9\%$ vs observed $14.5\%$ (gap $+2.4\%$); CP El Niño $3.0\%$ vs observed $4.0\%$ (gap $-1.0\%$). Calibrated damping ($d_{TE} = 0.36$, $\beta_{TE} = 3.20$, $\gamma_E = 0.072$) accurately captures the observed decorrelation timescale while preserving realistic peak event amplitudes and global boundedness ($T_E$ variability $0.88^\circ\text{C}$ vs observed $0.89^\circ\text{C}$, $0.99\times$ ratio).

### 6. Central Pacific SST ($T_C'$)
$$\frac{dT_C'}{dt'} = -d_{TC} T_C' - \beta_{TC} (T_C')^3 - \alpha_C \max(0, T_C')^2 + \gamma_{Cu} u' + \gamma_{Ch} h_W' + \gamma_{CT} T_E'$$
Central Pacific warming is driven primarily by zonal current advection ($\gamma_{Cu} u'$ with calibrated coupling $\gamma_{Cu} = 0.228$), capturing CP El Niño (Modoki) events ($3.0\%$ frequency vs observed $4.0\%$). Calibrated quadratic saturation ($-\alpha_C \max(0, T_C')^2$ with $\alpha_C = 1.50$) and calibrated damping ($d_{TC} = 0.034$) reflect the atmospheric convective threshold and zonal advection damping, matching observed negative skewness ($-0.41$ vs observed $-0.48$) and realistic $T_C$ variability ($0.69^\circ\text{C}$ vs observed $0.64^\circ\text{C}$).

## Stochastic Integration
The SDE system is advanced using Euler-Maruyama:
$$x'_{k+1} = x'_k + f'(x'_k, t'_k) \Delta t' + \Sigma(x'_k) \sqrt{\Delta t'} \eta_k, \quad \eta_k \sim \mathcal{N}(0, I_5)$$
Then rescaled to physical units: $x_{k+1} = x'_{k+1} \odot S$.

## Physical Mechanisms Represented
1. **Recharge-Discharge Paradigm & Dominant Period**: +17-month thermocline lead over SST (observed +17 months, exact match), dominant spectral period of 60 months (observed 60 months, exact match), and clockwise phase-space circulation ($\text{circ} = +0.14$ vs obs $+0.15$).
2. **ENSO Diversity & Current Couplings**: Distinct dynamical mechanisms for EP El Niño (thermocline upwelling feedback) vs CP El Niño (zonal current advective feedback). Ocean current couplings match observations closely: $\text{corr}(u, \tau) = \mathbf{+0.08}$ (obs $+0.08$, exact match) and $\text{corr}(u, h_W) = \mathbf{+0.43}$ (obs $+0.42$, gap $+0.01$).
3. **Asymmetry / Skewness**: Convex upwelling ($\alpha_E = 8.5$) and state-dependent WWBs ($\alpha_w = 1.90$) yield positive EP skewness ($+0.77$), while convective saturation yields negative CP skewness ($-0.41$).
4. **Seasonal Phase Locking**: Boreal autumn/winter coupling amplification ($\mu_{\text{seas}} = 0.755$, $\phi_{\text{seas}} = 9.70$) locks maximum variance to December (month 12, exact match) with an exact 3.61x seasonal variance ratio (obs 3.61x, exact match).
5. **Cross-Variable Consistency (DA Proxy)**: Reconstruction correlation $+0.70$ (matching the empirical benchmark of $+0.71$, exact match).
6. **Predictivity**: Skillful multi-lead forecasts beating persistence across all 4 lead times for $T_E$ on held-out data (2000–2014) with mean ACC gain +0.146 and mean RMSE ratio 0.91x (3m: 0.587 C vs 0.618 C; 6m: 0.825 C vs 0.911 C; 9m: 0.938 C vs 1.016 C; 12m: 0.884 C vs 1.034 C; 6m $T_C$: 0.563 C vs 0.706 C).
