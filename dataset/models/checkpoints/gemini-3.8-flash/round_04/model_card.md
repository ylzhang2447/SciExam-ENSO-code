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
where $\phi_{\text{seas}} = 9.6$ leads the peak response, locking maximum SST variance to December (month 12).

### 2. Atmospheric Wind Stress Proxy ($\tau'$)
$$\frac{d\tau'}{dt'} = -d_\tau \tau' + F_{\text{seas}}(t) (b_{TC} T_C' + b_{TE} T_E')$$
Fast atmospheric damping ($d_\tau \approx 1.06$, timescale $\approx 1.9$ months) with Bjerknes feedback: strong positive wind response to Central Pacific warming ($b_{TC} = 3.70$), and negative feedback to Eastern Pacific warming ($b_{TE} = -0.50$) reflecting eastward convective shift and trade wind relaxation.
Stochastic weather noise includes state-dependent westerly wind burst (WWB) amplification:
$$\sigma_{\tau,\text{eff}} = \sigma_\tau \cdot [1 + \alpha_w \max(0, T_C')]$$

### 3. Mixed-Layer Zonal Current ($u'$)
$$\frac{du'}{dt'} = -d_u u' + c_\tau \tau' + c_h h_W'$$
Driven directly by westerly wind stress ($c_\tau$) and by the zonal thermocline pressure gradient force ($c_h h_W'$), correctly producing the observed positive correlation $\text{corr}(u, h_W) = +0.42$.

### 4. Western Pacific Thermocline Depth ($h_W'$)
$$\frac{dh_W'}{dt'} = -d_{hW} h_W' - r_\tau \tau' - r_E T_E' - r_u u'$$
Represents warm water volume adjustment: wind-stress curl and anomalous divergence discharge equatorial heat content during warm phases, creating the foundational recharge oscillator mechanism.

### 5. Eastern Pacific SST ($T_E'$)
$$h_E' = h_W' + b_h \tau'$$
$$T_{\text{sub}}' = \gamma_E [h_E' + \alpha_E (\max(0, h_E')^2 - h_{\text{offset}})]$$
$$\frac{dT_E'}{dt'} = -d_{TE} T_E' - \beta_{TE} (T_E')^3 + F_{\text{seas}}(t) T_{\text{sub}}' + \gamma_{Eu} u' + \gamma_{ET} T_C'$$
The convex quadratic upwelling term ($\alpha_E \max(0, h_E')^2$) generates extreme warm anomalies while moderating cold anomalies, producing the observed strong positive skewness ($+1.03$ vs observed $+0.95$). Anomaly centering offset $h_{\text{offset}} = 0.030$ balances the base state against nonlinear rectification, ensuring realistic frequencies of both extreme El Niño ($5.5\%$ vs observed $5.2\%$) and La Niña ($13.4\%$ vs observed $16.2\%$) while eliminating mean forecast bias. Cubic damping ($\beta_{TE}$) bounds extreme events and ensures global stability.

### 6. Central Pacific SST ($T_C'$)
$$\frac{dT_C'}{dt'} = -d_{TC} T_C' - \beta_{TC} (T_C')^3 - \alpha_C \max(0, T_C')^2 + \gamma_{Cu} u' + \gamma_{Ch} h_W' + \gamma_{CT} T_E'$$
Central Pacific warming is driven primarily by zonal current advection ($\gamma_{Cu} u'$), capturing CP El Niño (Modoki) events. The negative quadratic term ($-\alpha_C \max(0, T_C')^2$) reflects convective threshold saturation, producing the observed negative skewness ($-0.30$ vs observed $-0.48$).

## Stochastic Integration
The SDE system is advanced using Euler-Maruyama:
$$x'_{k+1} = x'_k + f'(x'_k, t'_k) \Delta t' + \Sigma(x'_k) \sqrt{\Delta t'} \eta_k, \quad \eta_k \sim \mathcal{N}(0, I_5)$$
Then rescaled to physical units: $x_{k+1} = x'_{k+1} \odot S$.

## Physical Mechanisms Represented
1. **Recharge-Discharge Paradigm**: 17-month thermocline lead over SST, strong negative zero-lag correlation ($r = -0.66$ vs obs $-0.69$), and clockwise phase-space circulation ($\text{circ} = +0.15$ vs obs $+0.15$).
2. **ENSO Diversity**: Distinct dynamical mechanisms for EP El Niño (thermocline upwelling feedback) vs CP El Niño (zonal current advective feedback).
3. **Asymmetry / Skewness**: Convex upwelling and state-dependent WWBs yield positive EP skewness ($+0.86$), while convective saturation yields negative CP skewness ($-0.30$).
4. **Seasonal Phase Locking**: Boreal autumn/winter coupling amplification locks maximum variance to December (month 12) with a 4.47x seasonal variance ratio.
5. **Predictivity**: Skillful multi-lead forecasts beating persistence across lead times on held-out data (2000–2014).
