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

All variables are anomalies relative to 1981–2010 monthly climatology.

## Non-dimensionalization
From `nondim_scales.json`: T*=7.5°C, h*=150m, u*=1.5m/s, τ*=5.0m/s, t*=2 months.
X_nd = X_dimensional / X_scale. All model parameters are in non-dimensional units.

## Equations
The system follows an SDE integrated with Euler–Maruyama (dt = 0.1 months):

```
dX/dt = [A + S(t)·dA]·X + N_nonlinear(X) + stochastic
```

### Linear Dynamics (A matrix)
VAR(1) fit to observed 1980–2014 monthly indices. The A matrix captures the basic
ENSO oscillation (~4 yr period), inter-variable coupling, and damping:

- **TE (row 1)**: Damped (−0.24) with thermocline feedback (+0.089 hW), cross-region
  influence (+0.234 u, +0.071 τ), and EP-to-CP coupling from TC (−0.064).
- **TC (row 0)**: Damped (−0.24) with thermocline coupling (+0.149 hW),
  direct atmospheric response to wind (+0.045 τ), influence from TE (+0.096).
  A[0,0] is set equal to A[1,1] so that TC and TE memory are balanced; TC's
  autocorrelation structure then emerges naturally from the coupling pattern.
- **hW (row 2)**: Recharge oscillator equation: damped (−0.22) with discharge from EP
  SST (−0.22 TE) and CP SST (−0.20 TC), wind memory (−0.211 u). τ→hW coupling is set
  to zero: the thermocline is forced by SST and current, not directly by local wind.
- **u (row 3)**: Fast current adjustment (−0.671) driven by thermocline pressure
  gradient (+0.48 hW), with wind-stress forcing (+0.10 τ).
- **τ (row 4)**: Fast atmospheric response (−1.15) driven by CP SST (+2.20 TC) with
  smaller EP contribution (+0.20 TE) and current feedback (+0.38 u).

The hW→u coupling (A[3,2]=0.48) is the dominant control on the oscillation period:
it sets the slow thermocline–current adjustment timescale that, together with the
Bjerknes feedback, places the spectral peak at ~48 months (observed 47 months).

### Seasonal Modulation
dA matrix modulates the drift seasonally: `A_eff = A + seas · dA` where seas =
cos(2π(t−Dec)/12). In boreal winter (seas=+1), TC and TE damping weakens (dA[0,0]=
dA[1,1]=−0.15), allowing stronger growth, while the τ→TC atmospheric bridge
strengthens (dA[4,0]=+0.75). In summer (seas=−1), the opposite occurs — stronger
damping, weaker coupling. This produces phase-locked winter variance peaks and
contributes to the negative lag-12 autocorrelation (enhanced biennial tendency).
Noise amplitude is also seasonally modulated (s_noise_amp=0.20).

### Nonlinear Terms N_nonlinear(X)
Three mechanisms, jointly needed to produce the observed skew while staying stable:

1. **Sigmoid asymmetric growth** — on TE (warm side) and TC (cold side):
   `dTE += gTE · TE / (1 + exp(−k·TE))`  (warm TE growth weakened less)
   `dTC += gTC · TC / (1 + exp(+k·TC))`  (cold TC growth weakened less)
   This selectively reduces restoring damping on one tail, producing the right sign
   of skew. The sigmoid (k=12) makes the extra growth switch on sharply at moderate
   amplitudes while saturating at large ones.

2. **One-sided cubic tail saturation:**
   `dTE −= c_tail · max(TE, 0)³` — caps the warm tail of TE only, preserving the
   cold tail's ability to reach moderate negative amplitudes while preventing
   warm events from diverging.

3. **Symmetric cubic saturation:**
   `dTE −= c_sat · TE³`,  `dTC −= c_sat_TC · TC³` — bounds extreme excursions.
   Separate coefficients allow TC's cold tail to survive.

### Stochastic Forcing
Three-component noise that jointly produces the heavy-tailed, skewed stationary density:

1. **Additive noise:** Diagonal noise amplitudes σ=[0.038, 0.054, 0.006, 0.08, 0.45]
   with TE–TC correlation (ρ=0.75, tuned to match TE–TC correlation +0.71).
   Seasonally modulated (amplified in boreal winter, s_noise_amp=0.20).

2. **Multiplicative noise:** `σ_mult · |X| · dW` — state-dependent noise on TC and TE
   creates heavier tails than Gaussian.

3. **Asymmetric state-dependent noise:**
   `dTE += σ_asym_TE · max(TE, 0) · dW` — noise larger on the warm side → warm
   excursions face larger stochastic perturbations → positive TE skew.
   `dTC += σ_asym_TC · max(−TC, 0) · dW` — noise larger on the cold side → cold CP
   excursions are amplified → negative TC skew.

   This asymmetric noise is the dominant source of skew — it directly shapes the
   stationary density without requiring a drift term strong enough to destabilize
   the linear restoring force.

## Physical Mechanisms

### Recharge–Discharge Oscillator (Jin 1997)
Warm TE → westerly τ → thermocline tilts (hE deeper, hW shallower) → further warming
(Bjerknes feedback). Simultaneously, sustained τ discharges hW. The discharge
eventually erodes the thermocline support, TE decays, and the system transitions
toward a cold phase. The cycle period reflects the balance between fast Bjerknes
growth and slow recharge.

### ENSO Diversity (CP vs EP)
Two SST indices coupled through an atmospheric bridge. τ responds more strongly to
CP than EP SST (2.20 vs 0.20 in A[4,0] vs A[4,1]), producing distinct CP-driven
and EP-driven event types.

### Skew (El Niño / La Niña Asymmetry)
The observed EP skew (+0.95) and CP skew (−0.48) come from two combined mechanisms:
- Sigmoid asymmetric drift weakens restoring force on the tail side.
- Asymmetric state-dependent noise amplifies perturbations on the tail side.
These are stabilized by one-sided + symmetric cubic saturation so the model does
not diverge.

### Seasonal Phase Locking
dA matrix peaks coupling in December, synchronizing event development with the
calendar year and producing the observed seasonal variance cycle.

## Numerical Integration
Euler–Maruyama with dt=0.1 months. Single source of truth is `step()`. Grader
builds free simulation, ensemble forecast, and data assimilation on top.

## Calibrated Parameters
`params.json` — linear dynamics from VAR(1) residual fit, refined by hand-tuning the
thermocline couplings to place the spectral peak at ~48 months and the
recharge–discharge phase relation. Noise and nonlinear parameters tuned to match
observed std, skew, cross-correlation, seasonal cycle, and recharge-discharge phase
relation over 1980–2014.

## Validation
Free-run climate (8 seeds × 2400 months): TC std 0.655 (obs 0.638), TC skew −0.504
(obs −0.477), TE std 0.902 (obs 0.885), TE skew +0.980 (obs +0.954), corr(TC,TE)
+0.679 (obs +0.708), corr(TC,hW) −0.603 (obs −0.603, exact), corr(TE,hW) −0.703
(obs −0.694), corr(u,τ) +0.121 (obs +0.079). Recharge corr(hW,TE) −0.703 at lag 0,
−0.494 at lag 2, −0.291 at lag 4 (obs −0.694, −0.492, −0.264).
Spectral peak 48 months (obs 47). Extreme El Niño frequency 3.9% (obs 3.8%).
Ensemble forecasts (32 members) from observed initial states reduce RMSE over
persistence by 23–33% for TC, 18–29% for TE, and 26–41% for u at leads 3–12 months,
with anomaly correlation exceeding persistence at all leads.

**Residual gaps:** TC autocorr lag 6 (0.43 vs 0.54) and TE autocorr lag 12
(−0.04 vs −0.14) — the single dominant oscillator cannot reproduce the observed
18% of TE power in the 2–3 year band alongside the 3–6 year ENSO band. hW std
(16.6 vs 13.5 m) is inflated by the same coupling that produces the correct
recharge phase and spectral peak; reducing it degrades the recharge relation and
the spectral peak simultaneously.