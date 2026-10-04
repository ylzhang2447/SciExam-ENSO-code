# ENSO Diversity Stochastic Conceptual Model

## State Variables
- **TC**: Central Pacific SST anomaly (Niño4 region, 160-210°E, 5°S-5°N) in °C
- **TE**: Eastern Pacific SST anomaly (Niño3 region, 210-270°E, 5°S-5°N) in °C  
- **hW**: Western Pacific thermocline depth anomaly (120-180°E, 5°S-5°N) in meters
- **u**: Central Pacific zonal current anomaly (160-210°E, 5°S-5°N, mixed layer) in m/s
- **tau**: Western Pacific 850 hPa zonal wind stress anomaly (120-180°E, 5°S-5°N) in m/s

## Model Equations
The model extends the Jin (1997) recharge oscillator framework to represent ENSO diversity through a two-region SST structure. The system consists of coupled stochastic differential equations:

**SST Equations (Central and Eastern Pacific):**
```
dTC/dt = α_TC * hW - β_TC * TC - μ_TC * TC³ + seasonal_TC(t)
dTE/dt = α_TE * hW - β_TE * TE - μ_TE * TE³ + seasonal_TE(t)
```

**Thermocline Equation (Recharge/Discharge):**
```
dhW/dt = -ε * (γ_TC * TC + γ_TE * TE) - κ * hW - ν * hW³
```

**Zonal Current Equation:**
```
du/dt = ζ * tau - η * u
```

**Wind Stress Equation (AR(1) Stochastic Forcing):**
```
dtau/dt = -ρ_tau * tau + σ_tau * dW/dt
```

## Key Mechanisms
1. **Recharge Oscillator**: Thermocline anomalies (hW) drive SST growth in both regions, while SST anomalies feed back to discharge the thermocline, creating the oscillatory behavior.

2. **ENSO Diversity**: Separate TC and TE equations with different growth rates (α) and damping (β) allow for independent Central Pacific (CP) and Eastern Pacific (EP) variability patterns.

3. **Nonlinearity**: Cubic terms (μ, ν) create El Niño/La Niña asymmetry, with stronger positive SST anomalies consistent with observed skewness.

4. **Seasonal Phase Locking**: Time-dependent seasonal coefficients modulate SST growth rates, locking ENSO variance to boreal winter.

5. **Stochastic Forcing**: AR(1) wind stress forcing (tau) provides realistic noise structure with temporal correlation, driving the system away from equilibrium.

The model is non-dimensionalized internally using characteristic scales for numerical stability, but maintains dimensional input/output units as required by the interface.