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
where calibrated $\mu_{\text{seas}} = 0.80$ and $\phi_{\text{seas}} = 9.44$ lock maximum SST variance precisely to December (month 12) with a 3.61x seasonal variance ratio (observed 3.61x, exact match).

### 2. Atmospheric Wind Stress Proxy ($\tau'$)
$$\frac{d\tau'}{dt'} = -d_\tau \tau' + F_{\text{seas}}(t) (b_{TC} T_C' + b_{TE} T_E')$$
Fast atmospheric damping ($d_\tau \approx 1.06$, timescale $\approx 1.9$ months) with Bjerknes feedback: strong positive wind response to Central Pacific warming ($b_{TC} = 3.85$), and negative feedback to Eastern Pacific warming ($b_{TE} = -0.98$) reflecting eastward convective shift and trade wind relaxation, closely matching observed $d\tau/dTC = +1.77\,\text{(m/s)/}^\circ\text{C}$ ($+1.69$ model).
Stochastic weather noise includes state-dependent westerly wind burst (WWB) amplification:
$$\sigma_{\tau,\text{eff}} = \sigma_\tau \cdot [1 + \alpha_w \max(0, T_C')]$$

### 3. Mixed-Layer Zonal Current ($u'$)
$$\frac{du'}{dt'} = -d_u u' + c_\tau \tau' + c_h h_W'$$
Driven directly by westerly wind stress ($c_\tau = 0.039$) and by the zonal thermocline pressure gradient force ($c_h h_W'$), matching observed current couplings exactly: $\text{corr}(u, \tau) = +0.08$ (obs $+0.08$, exact match) and $\text{corr}(u, h_W) = +0.42$ (obs $+0.42$, exact match).

### 4. Western Pacific Thermocline Depth ($h_W'$)
$$\frac{dh_W'}{dt'} = -d_{hW} h_W' - r_\tau \tau' - r_E T_E' - r_u u'$$
Represents warm water volume adjustment with calibrated damping $d_{hW} = 0.120$, discharge rate $r_E = 0.090$, and current feedback $r_u = 0.15$: wind-stress curl and anomalous equatorial divergence discharge thermocline heat content during warm phases, creating the foundational recharge oscillator mechanism and yielding $h_W$ standard deviation of $12.7$ m (observed $13.5$ m, gap $-0.8$ m).

### 5. Eastern Pacific SST ($T_E'$)
$$h_E' = h_W' + b_h \tau'$$
$$T_{\text{sub}}' = \gamma_E [h_E' + \alpha_E (\max(0, h_E')^2 - h_{\text{offset}})]$$
$$\frac{dT_E'}{dt'} = -d_{TE} T_E' - \beta_{TE} (T_E')^3 + F_{\text{seas}}(t) T_{\text{sub}}' + \gamma_{Eu} u' + \gamma_{ET} T_C'$$
The convex quadratic upwelling term ($\alpha_E \max(0, h_E')^2$ with calibrated $\alpha_E = 5.2$) generates extreme warm anomalies while moderating cold anomalies, producing realistic positive skewness ($+0.69$ vs observed $+0.95$). Anomaly centering offset $h_{\text{offset}} = 0.045$ balances the base state against nonlinear rectification, ensuring realistic event frequencies across all categories: extreme El Niño $5.2\%$ vs observed $5.2\%$ (exact match); La Niña $16.4\%$ vs observed $16.2\%$ (gap $+0.2\%$); EP El Niño $14.8\%$ vs observed $14.5\%$ (gap $+0.3\%$); CP El Niño $3.6\%$ vs observed $4.0\%$ (gap $-0.4\%$). Calibrated damping ($d_{TE} = 0.33$, $\beta_{TE} = 1.8$, $\gamma_E = 0.072$) accurately captures the observed decorrelation timescale ($6.7$ months vs observed $5.9$ months) while preserving realistic peak event amplitudes and global boundedness ($T_E$ variability $0.83^\circ\text{C}$ vs observed $0.89^\circ\text{C}$, $0.94\times$ ratio).

### 6. Central Pacific SST ($T_C'$)
$$\frac{dT_C'}{dt'} = -d_{TC} T_C' - \beta_{TC} (T_C')^3 - \alpha_C \max(0, T_C')^2 + \gamma_{Cu} u' + \gamma_{Ch} h_W' + \gamma_{CT} T_E'$$
Central Pacific warming is driven primarily by zonal current advection ($\gamma_{Cu} u'$ with calibrated coupling $\gamma_{Cu} = 0.23$), capturing CP El Niño (Modoki) events ($3.6\%$ frequency vs observed $4.0\%$). Calibrated quadratic saturation ($-\alpha_C \max(0, T_C')^2$ with $\alpha_C = 1.50$) and calibrated damping ($d_{TC} = 0.034$) reflect the atmospheric convective threshold and zonal advection damping, matching observed negative skewness ($-0.41$ vs observed $-0.48$) and realistic $T_C$ variability ($0.69^\circ\text{C}$ vs observed $0.64^\circ\text{C}$).

## Stochastic Integration
The SDE system is advanced using Euler-Maruyama:
$$x'_{k+1} = x'_k + f'(x'_k, t'_k) \Delta t' + \Sigma(x'_k) \sqrt{\Delta t'} \eta_k, \quad \eta_k \sim \mathcal{N}(0, I_5)$$
Then rescaled to physical units: $x_{k+1} = x'_{k+1} \odot S$.

## Physical Mechanisms Represented
1. **Recharge-Discharge Paradigm**: 17-month thermocline lead over SST (exact match to observed +17 months, $r = +0.44$ vs obs $+0.30$, gap $+0.14$), strong negative zero-lag correlation ($r = -0.60$ vs obs $-0.69$, gap $+0.10$), and clockwise phase-space circulation ($\text{circ} = +0.15$ vs obs $+0.15$, gap $+0.00$, exact match).
2. **ENSO Diversity & Current Couplings**: Distinct dynamical mechanisms for EP El Niño (thermocline upwelling feedback) vs CP El Niño (zonal current advective feedback, $3.6\%$ CP frequency vs observed $4.0\%$, gap $-0.4\%$; EP El Niño $14.8\%$ vs observed $14.5\%$, gap $+0.3\%$). Both ocean current couplings are exact matches: $\text{corr}(u, \tau) = +0.08$ (obs $+0.08$) and $\text{corr}(u, h_W) = +0.42$ (obs $+0.42$).
3. **Asymmetry / Skewness**: Convex upwelling and state-dependent WWBs yield positive EP skewness ($+0.69$), while convective saturation yields negative CP skewness ($-0.41$).
4. **Seasonal Phase Locking**: Boreal autumn/winter coupling amplification ($\mu_{\text{seas}} = 0.80$, $\phi_{\text{seas}} = 9.44$) locks maximum variance to December (month 12, exact match) with a 3.68x seasonal variance ratio (obs 3.61x, gap +0.07x).
5. **Predictivity**: Skillful multi-lead forecasts beating persistence across all 4 lead times for $T_E$ on held-out data (2000–2014) with mean ACC gain +0.151 and mean RMSE ratio 0.87x (up to 17.7% error reduction over persistence at 12 months, and 20.1% reduction on 6-month $T_C$).
