# Model card: two-region stochastic recharge oscillator for ENSO diversity

## State variables (dimensional in/out of `step`; non-dimensional inside)
| row | variable | meaning | scale |
|---|---|---|---|
| 0 | TC | central-Pacific (Nino-4 box) SST anomaly | 7.5 C |
| 1 | TE | eastern-Pacific (Nino-3 box) SST anomaly | 7.5 C |
| 2 | hW | western-Pacific 20C-isotherm depth anomaly (heat content / recharge state) | 150 m |
| 3 | u | central-Pacific upper-ocean zonal current anomaly | 1.5 m/s |
| 4 | tau | western-Pacific 850 hPa zonal wind anomaly (westerly positive) | 5 m/s |

Time unit inside the model is 2 months (`nondim_scales.json`); `t` is in months and `t mod 12 == 0` is
January, so all seasonal terms use `cos(2*pi/12 * (t - phase))` with phases in months.

## Equations (non-dimensional; `sp(x)` = softplus with sharpness `k_sp`, `omega = 2 pi / 12` per month)
```
dTE/dt  = R_E(t) TE + gam_E hW + alp_E u + b_E tau + k_EC TC
          + q_E TE W_E tanh(sp(TE - T0_E)/W_E) - d_E TE sp(TE) - v_E - c_E TE^3
dTC/dt  = R_C(t) TC + gam_C hW + alp_C u + b_C tau + k_CE TE
          - d_C TC sp(TC) + q_C TC^2 - v_C - c_C TC^3
dhW/dt  = -r_h hW - (1 + a_s cos(omega(t - phi_as))) (a_E TE + a_C TC) - b_h tau - a_u u
du/dt   = -r_u u + beta_t tau + beta_h hW
dtau/dt = -r_t tau + (1 + mu_a cos(omega(t - phi_a))) (m_C TC + m_E TE + m_2 Tm sp(Tm)) + m_h hW
R_X(t)  = R_X0 (1 + R_Xa cos(omega(t - phi_X)) + R_Xb cos(2 omega(t - phi_X2)))   X = E, C ;  Tm = (TC + TE)/2
```
Stochastic forcing (Euler-Maruyama, independent Gaussian increments scaled by sqrt(dt)):
```
tau : sig_t (1 + s_t cos(omega(t - phi_t))) (1 + mu_t sp(TC))     state-dependent westerly-wind-burst noise
TE  : sig_TE (1 + s_E cos(omega(t - phi_En))) (1 + mu_E sp(TE))     warm-phase enhanced, spring-peaking (phi_En ~ 3) SST noise
TC  : sig_TC (1 + mu_Cn sp(-TC))                                   cold-phase enhanced SST noise (negative TC skew
      without a warm-side damping that would suppress Central-Pacific events) ;  hW : sig_h (1 + s_h cos(omega(t - phi_h))) ;  u : sig_u (1 + s_u cos(omega(t - phi_u)))
```
The cubic terms are applied implicitly (`x <- x / (1 + c dt x^2)`) after the explicit update, so the
scheme is unconditionally stable for the cubic part; a hard clip at |x| = 5 (non-dimensional, i.e. 37 C,
750 m) is a last-resort guard that is never reached in normal operation. Every stochastic term is drawn
from the `rng` passed to `step`, so results are reproducible for a given seed.

## Mechanisms represented
- **Recharge-discharge oscillator (Jin 1997):** eastern SST grows through the Bjerknes feedback
  (thermocline term `gam_E hW`, wind-driven tilt `b_E tau`, advection `alp_E u`) and discharges the
  western-Pacific heat content (`a_E TE`, `a_C TC` in the hW equation); the slowly recharging hW then
  leads the next event. The fitted linear core is a damped oscillator (annual-mean leading mode: period
  about 4 years, e-folding time about 12 months), i.e. the noise-driven damped regime.
- **ENSO diversity (CP vs EP):** the central-Pacific SST is driven mainly by zonal advection (`alp_C u`)
  and directly by the wind (`b_C tau`), the eastern SST by the thermocline / wind-driven tilt. Moderate
  warmings are damped extra in the east (`d_E`) so they stay Central-Pacific-led; above a threshold
  (`T0_E`, about 0.75 C) strong eastern warming receives an additional, saturating growth rate
  (`q_E`, `W_E`) representing the nonlinear thermocline feedback that produces extreme EP events. Warm
  central-Pacific SST saturates (`d_C`), giving negative TC skewness.
- **Seasonality / phase locking:** the eastern and central growth rates (annual + semiannual), the
  atmospheric sensitivity (`mu_a` ~ 0.7, strongest in Aug-Sep), the discharge efficiency and the TE / u / hW
  noise amplitudes all carry an annual cycle. The seasonal atmospheric sensitivity is the main locking
  agent: coupled growth is strongest in late summer-autumn and weakest in late winter-spring, so events
  peak in Nov-Jan and terminate in spring (spring predictability barrier). The TE noise peaks in boreal
  spring, which keeps the ratio of winter to spring TE variance near the observed value while the
  coupling cycle is strong.
- **Stochastic forcing:** wind noise is multiplicative in the warm phase of TC (westerly wind bursts
  are more frequent over a warm, eastward-displaced warm pool), which produces the observed positive
  TE skewness, high TE kurtosis and the El Nino / La Nina amplitude asymmetry.
- **Zonal current:** u is a fast (about 3-month) variable driven by the wind and by the zonal
  thermocline slope (`beta_h hW`); it carries the advective feedback into TC.

## Calibration
- Data: workspace-processed monthly indices 1980-2002 only (2003-2014 held out for forecast checks).
- Deterministic drift parameters: least squares on 1- to 6-month-lead deterministic predictions
  (`scripts/fit_drift.py`), with physical bounds (thermocline feedback on TE >= 0.1, advection weighted
  toward TC, seasonal coupling amplitude <= 0.35).
- Noise, asymmetry and seasonal-noise parameters: Nelder-Mead on free-run statistics (standard
  deviations, skewness, kurtosis, seasonal variance cycle, event counts EP/CP/LN, event strengths,
  NDJ peak fraction, spring persistence, composite differences), `scripts/tune_noise.py`.
- All parameters are in `params.json` (flat JSON, non-dimensional units, phases in months).

## Known limitations
- Eastern- and Central-Pacific warm winters occur about equally often (about 6:6 per 34 winters vs
  4:8 observed): moderate warm winters are too often eastern-led. The mean strength of EP events
  (about 1.3 C) is below the observed value, which is dominated by 1982/83 and 1997/98.
- Winter phase locking is weaker than observed: about 58% of warm-event TE peaks fall in Nov-Jan
  (observed ~70%); the modal peak month is December rather than November. Cold events lock slightly
  more strongly than observed.
- The zonal-wind seasonal variance cycle peaks in autumn (observed: boreal spring) because the wind
  variance is dominated by the seasonally modulated coupled response; spring-peaking wind noise would
  fix the cycle but removes the autumn bursts that build extreme events.
- TC-hW and TE-tau are somewhat more tightly correlated than observed, and the advective link
  between u and TC tendency is slightly weaker (correlation ~0.5 vs 0.6).
- Forecast ensembles are slightly under-dispersive at 6-month lead on the hold-out period; hold-out
  TE skill beats persistence at all leads but drops to ~0.15 at 9 months.
