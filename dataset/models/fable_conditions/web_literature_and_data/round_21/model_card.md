# Model card: two-region stochastic recharge oscillator for ENSO diversity

## State (dimensional in/out of `step`)
| row | variable | meaning | unit | scale (nondim) |
|---|---|---|---|---|
| 0 | TC | central-Pacific SST anomaly | C | 7.5 |
| 1 | TE | eastern-Pacific SST anomaly | C | 7.5 |
| 2 | hW | western-Pacific thermocline-depth anomaly (20 C isotherm) | m | 150 |
| 3 | u | central-Pacific mixed-layer zonal-current anomaly | m/s | 1.5 |
| 4 | tau | western-Pacific 850 hPa zonal-wind anomaly (stochastic forcing) | m/s | 5 |

Internally everything is non-dimensional (`nondim_scales.json`), one time unit = 2 months.
`t` is months since the run start with `t = 0` taken as 1 January; the calendar phase is
`ph = 2 pi (t mod 12)/12`. Integration is Euler-Maruyama with internal sub-steps of at most
0.1 month, so the climate is insensitive to the caller's `dt` (tested 0.05-1.0 month). A
safety clip at |x| <= 4 (non-dimensional; several times the observed range) guarantees finite
output for arbitrary input states.

## Equations (non-dimensional)
Seasonal factors: `sX = cos(ph - 2 pi phase_X / 12)`.

```
dTC/dt = (R_C0 + R_C1 sC) TC + x_CE TE + g_C hW + b_C u + e_C tau
         - q_CE TC TE - c_C TC^3 + f_C
dTE/dt = (R_E0 + R_E1 sE) TE + x_EC TC + g_E hW (1 + gam_h hW) + b_E u + e_E tau
         + q_E TE^2 - c_E TE^3 + f_E
dhW/dt = -r_h hW - (1 + a_seas sA) (a_C TC + a_E TE + a_q TE^2 + a_u u + a_tau tau) + f_h
du/dt  = -r_u u + u_h hW + u_tau tau - u_C TC
dtau/dt= -r_tau (tau - k_C TC - k_E TE - k_h hW - k_u u)
```
Stochastic forcing (per sqrt of a time unit), all drawn from the supplied `rng`:
* tau: `sig_tau (1 + sig_tau_seas cos(ph - phase_sig)) (1 + mult tanh(TC/0.1)) dW`
  (red-noise wind forcing with an annual cycle peaking in late winter, weakly state dependent);
* u: `sig_u (1 + sig_u_seas cos(ph - phase_su)) dW` (seasonal current noise);
* TC, TE: additive `sig_C`, `sig_E` with correlation `rho_T` (unresolved shared heating);
* hW: additive `sig_h`.

## Mechanisms represented
* **Bjerknes growth and recharge-discharge (Jin 1997).** SST grows through the seasonally
  modulated rates `R_*`; thermocline feedback `g_* hW` warms the east/centre when the warm
  pool is recharged; SST-driven winds discharge the warm pool (`a_E`, `a_C`, `a_tau`;
  the TC-driven discharge `a_C` is what makes warm events roll over into La Nina the
  next winter) and the zonal current `u` acts as the fast surface branch of the discharge
  (`a_u`), while hW drives u (`u_h`).  Because u is itself driven by hW, `a_u` acts as an
  effective damping of the warm-water volume and sets the hW variance.  The linear core gives a damped ~4-year oscillatory mode that is
  sustained by wind noise; hW leads TE by ~15 months (recharge) and lags by ~3 months
  with opposite sign (discharge).
* **Two regions / ENSO diversity.** TE is dominated by thermocline feedback (`g_E`), TC
  by zonal advection (`b_C u`) and direct wind forcing (`e_C tau`) with strong cubic
  saturation (`c_C`), so central-Pacific events stay moderate while eastern events can
  become extreme.  Cross-advection terms `x_CE`, `x_EC` couple the regions.
* **Asymmetry / nonlinearity.** `q_E TE^2` and `gam_h` give positive TE skew and heavy warm
  tails (extreme EP events); `-q_CE TC TE` limits TC during EP events and deepens cold
  central anomalies (negative TC skew); `a_q TE^2` makes warm events discharge more than
  cold events recharge (negative hW skew, longer cold phases).  Offsets `f_*` cancel the
  mean shift of the quadratic terms so the mean state stays at zero anomaly.
* **Seasonality / phase locking.** Growth rates peak in late summer (`phase_C`, `phase_E`
  around Aug-Sep), the discharge efficiency peaks in Oct-Nov (`a_seas`), and the wind and
  current noise have annual cycles, so event peaks lock to Nov-Jan.
* **Stochastic wind forcing.** tau is a fast red-noise process slaved to TC (`k_C`), with a
  negative TE contribution (`k_E` < 0: for a given central-Pacific warming, an eastern-
  shifted pattern puts the westerly response further east, off the central box) and a
  weak dependence on u; this reproduces the observed tau-TC correlation (~0.6), the
  month-to-month memory and the observed lagged tau-TE relation used by the LIM check.
* **Seasonal growth amplitude.** The seasonal modulation of the growth rates (`R_C1`,
  `R_E1`) is strong (of the same order as the mean damping), so both regions are net
  unstable in late summer/autumn and strongly damped in spring.  This is what gives the
  Dec variance peak, the spring persistence barrier and the high rate of El Nino -> La
  Nina transitions.

## Calibration
Linear couplings were anchored by regression of monthly tendencies of the observed
non-dimensional indices (1980-2004 only), then all parameters were tuned by free 10,000-yr
simulations against the observed 1980-2014 statistics (std, skewness, kurtosis, seasonal
variance cycle, ACF/spectrum, ONI-style EP/CP/La Nina event rates, recharge lag relation).
Forecast skill was checked on 2005-2014 initial states that were never used in fitting.

The final tuning deliberately sits in a noise-driven regime: the thermocline feedback
`g_E` is moderate and the SST noise is comparatively strong, so the linear oscillatory
mode is damped (e-folding ~20-25 months, obs ~12) rather than self-sustained.  This was
chosen because it reproduces the observed warm-water-volume relation (hW leads TE with
correlation ~0.3 at 13-17 months, strong anti-phase at lag 0) better than a more
deterministic oscillator, at the cost of a weaker biennial signature in the TE
autocorrelation at lag 24 months.
