# Model card: stochastic two-region recharge-oscillator model of ENSO diversity

## State variables (dimensional, order fixed by interface)
| var | meaning | units |
|-----|---------|-------|
| TC  | central-Pacific SST anomaly | degC |
| TE  | eastern-Pacific SST anomaly | degC |
| hW  | western-Pacific thermocline (equatorial heat-content) anomaly | m |
| u   | central-Pacific zonal current anomaly | m/s |
| tau | western-Pacific 850 hPa zonal wind anomaly (westerly +) | m/s |

Time is in months; integration is Euler–Maruyama. The observed indices were
non-dimensionalized with `nondim_scales.json` (T=7.5 C, h=150 m, u=1.5 m/s,
tau=5 m/s, t=2 months) during fitting to keep state variables O(1); the fitted
parameters were then converted back, and `step` operates in dimensional units.
The scales are stored in `params.json` for reference.

## Equations
The model is a coupled linear stochastic system with additive seasonal and
state-dependent (nonlinear, multiplicative-noise) corrections:

    dx/dt = const + A x  +  [seasonal/nonlinear corrections]  +  L(month) dW/dt

- **A (5x5), const, L (5x5)** are the conditional-maximum-likelihood (Yule–Walker)
  estimate of the coupled drift and noise from the observed monthly indices. This
  linear core is the Jin (1997) recharge oscillator made explicit: the hW row is the
  recharge/discharge equation (hW discharged by easterly/TE anomalies, damped at
  r_h ~ 0.08 /mo), the SST rows contain the thermocline feedback (aCh, aEh > 0) and
  zonal-advective feedback through u (gC, gE > 0), and the wind row carries the
  Bjerknes feedback (tau driven by SST). The linear core reproduces the observed
  variances, the recharge lead–lag (corr(hW, TE) min −0.79 at hW lead 3 months),
  autocorrelations, and the inter-variable partial-correlation structure.

- **Seasonality**: additive seasonal growth rates on the SST rows (RC_m, RE_m,
  per-month, zero-mean; boreal-spring/summer growth, winter damping) and seasonal
  noise-amplitude tables (nC_m, nE_m, nxi_m, nu_m, nh_m) fitted to the observed
  month-by-month standard deviations. These produce the observed December variance
  peak and the seasonal synchronization of events (phase locking).

- **ENSO asymmetry (diversity)**: multiplicative stochastic forcing on the SST rows,
  noise amplitude scaled by (1 + eps TE) on TE (eps = 0.42) and (1 + epsC TC) on TC
  (epsC = −0.28). Warm eastern-Pacific anomalies amplify their own wind/SST noise
  (the westerly-wind-burst / convective nonlinearity), producing the observed
  positive TE skew (+0.87), the rare extreme El Niño events with TE >> TC
  (eastern-Pacific extremes), and the bounded cold tail (no strong La Niña). The
  opposite-signed TC term gives the observed mild negative TC skew.

- **Seasonal recharge coupling**: the wind→thermocline recharge tendency is modulated
  by an annual factor (1 + hmod_m), capturing the seasonal dependence of how winds
  drive equatorial heat-content changes; this gives the observed winter peak and
  summer minimum in hW variance.

- **Seasonal thermocline damping**: the thermocline damping rate is modulated by an
  annual factor (rhseas_m, maximum in boreal summer, minimum in winter), capturing
  the stronger upwelling/vertical mixing that erodes the recharge anomaly in summer.
  The recharge timescale lags this into the observed January hW variance peak and
  August minimum.

- **Asymmetric discharge**: a mean-corrected term −gDis·(max(TE,0)² − ⟨max(TE,0)²⟩)
  enhances heat discharge during strong El Niño (so events terminate and transition
  toward La Niña) while La Niña recharge stays weak (so cold events persist).

- **Asymmetric wind (convective) response**: the wind tendency gets a mean-corrected
  term +bAsym·(max(T̄,0) − ⟨⟩) − 0.5·bAsym·(min(T̄,0) − ⟨⟩), so warm anomalies
  (which trigger deep convection over the warm pool) drive a stronger Bjerknes wind
  feedback than cold anomalies (where convection is suppressed). This produces the
  observed positive wind skew, amplifies El Niño growth (strong/extreme events),
  and lets cold anomalies persist (La Niña), improving the El Niño/La Niña
  asymmetry and the strong-event frequency.

- **State-dependent SST damping**: during La Niña the cold tongue suppresses deep
  convection and the negative surface-heat-flux feedback weakens, so cold SST
  anomalies decay more slowly and persist; warm anomalies damp at the normal rate.
  Implemented as a reduction of the TE damping rate when T̄ < 0 (dAsym = 0.4). This
  lengthens multi-year La Niña events and is the main persistence mechanism.

## Mechanisms represented
- Recharge–discharge: thermocline heat content leads and drives SST; El Niño
  discharges the equatorial band (overshoot into La Niña).
- Bjerknes feedback: SST–wind–current coupling (through A and the seasonal growth).
- Central- vs Eastern-Pacific diversity: separate TC and TE SST equations with
  different local dynamics and noise; multiplicative TE noise generates EP extremes.
- Stochastic forcing: seasonally modulated wind (tau) and current (u) noise,
  including the spring westerly-wind-burst window.
- Seasonal phase locking: seasonal growth + seasonal noise synchronize events to
  peak in boreal winter.

## Calibration
Linear core by conditional MLE on the 1980–2014 indices; seasonal and nonlinear
terms tuned against the observed seasonal cycle, skewness, event statistics, and
phase locking. Forecast skill was validated on a held-out decade (2005–2014) that
was not used for any tuning; the model beats persistence at all lead times there.

## Known limitations
- La Niña multi-year persistence is under-represented (the model oscillates a little
  too regularly); adding regime memory would require a higher-dimensional or
  regime-switching closure.
- The seasonal cycle of hW variance is small in the model (its variance is
  recharge-noise dominated); the observed seasonal hW modulation is only partly
  captured.
