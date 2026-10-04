# Model card: two-region stochastic recharge oscillator for ENSO diversity

## State variables (dimensional in/out of `step`)
| row | name | meaning | unit |
|---|---|---|---|
| 0 | TC | central-Pacific SST anomaly | degC |
| 1 | TE | eastern-Pacific SST anomaly | degC |
| 2 | hW | western-Pacific thermocline depth anomaly (recharge state) | m |
| 3 | u | central-Pacific zonal current anomaly (zonal advection) | m/s |
| 4 | tau | western-Pacific 850 hPa zonal wind anomaly (stochastic atmosphere) | m/s |

Internally the model is non-dimensional: T/7.5 degC, h/150 m, u/1.5 m/s, tau/5 m/s,
time/2 months (`nondim_scales.json`). Time `t` is months since run start, t = 0 is January.

## Equations (non-dimensional, x = (tc, te, h, u, ta))
Linear core (Jin 1997 recharge oscillator generalised to two SST regions plus current and wind):
```
dtc/dt = A_tc.x + [Rs_tc cos(2pi(t-ph_tc)/12) + Rs2 cos(4pi(t-ph2)/12)] tc + q_tc tc te + q_tc2 te^2 - c_tc tc^3 + b_tc   (c_tc_warm replaces c_tc when tc > 0)
dte/dt = A_te.x + [Rs_te cos(2pi(t-ph_te)/12) + Rs2 cos(4pi(t-ph2)/12)] te + q_te r^2/(1+(r/rs_te)^2) + Rs_teh cos(2pi(t-ph_teh)/12) h + r_cold min(te,0) - c_te te^3 + b_te,   r = max(te-te0, 0); c_te_cold is used instead of c_te when te < 0
dh/dt  = A_h_h h + [1 + Rs_h cos(2pi(t-ph_h)/12)] (A_h_tc tc + A_h_te te + A_h_u u + A_h_ta ta) + b_h
du/dt  = A_u.x
dta/dt = A_ta.x + sig_ta [1 + m_ta te]_+ [1 + Ss_ta cos(2pi(t-ph_sta)/12)] dW/dt
```
Each of tc, te, h, u also receives small additive white noise (sig_*); the tc/te and u/tau noise increments are correlated (rho_tcte, rho_uta), as in the LIM residuals. `A_*` are the entries of
a 5x5 drift matrix; `A_ta_u` is fixed to zero (wind responds to SST and thermocline only).
Integration is Euler-Maruyama with internal sub-stepping so the step never exceeds 0.1 month. The cubic damping terms are applied semi-implicitly (x/(1+dt c x^2)) and the non-dimensional state is boxed at roughly 5x the observed extremes (15 degC, 300 m, 4.5 m/s, 20 m/s); the box is never active in normal runs, but together these guarantee finite output from any initial state (tested to 1000x observed maxima).

## Mechanisms represented
- **Bjerknes growth and recharge-discharge** (Jin 1997): warm TE drives westerly tau (via TC/TE),
  which discharges hW (A_h_te, A_h_ta < 0); hW feeds back on SST through the zonal current u
  (A_u_h > 0, A_te_u > 0) and directly (A_tc_h). The linear part has a least-damped oscillatory
  mode of about 3.5 years with a 16-month e-folding time, so the oscillation is noise-sustained.
- **Wind as red multiplicative noise**: tau is an Ornstein-Uhlenbeck process (~1.4 month memory)
  slaved to the SST state, with variance increasing in warm TE states (westerly wind bursts) and in
  boreal winter. Its low-frequency part is the coupled atmospheric response; the residual is the
  stochastic forcing of the ocean.
- **Seasonal phase locking**: the SST growth rates peak in late boreal summer (ph = 8, September)
  and are most damped in late winter/spring, so variance peaks in Nov-Dec and events peak in NDJ.
  The wind-driven forcing of hW has a similar seasonal modulation (Rs_h, ph_h) and the thermocline
  damping is itself seasonal (Rs_hh, strongest in late boreal spring), giving a winter maximum and a
  late-summer minimum of thermocline variance (ratio ~1.6, obs 1.7) and a February recharge peak. The thermocline feedback on TE is itself
  seasonal (Rs_teh, strongest in boreal spring, weakest in late autumn), which sharpens the
  spring predictability barrier and the winter termination of events.
- **ENSO diversity (EP vs CP)**: TC and TE are separate regions with distinct drivers: TC responds
  to zonal advection (u) and thermocline; TE to thermocline through u and wind. Moderate warm
  events are often CP-like; the thresholded, saturating warm feedback on TE (active above te0 =
  0.75 degC) makes the strongest events EP-like (corr(TE-TC, TE+TC) > 0), gives TE positive
  skewness and extreme El Nino events, while the tc*te interaction (q_tc < 0) saturates TC during
  strong EP events and deepens TC cooling during La Nina (negative TC skewness).
- **Asymmetry and boundedness**: cubic damping on both SST variables guarantees a single
  bounded attractor; the model recovers from 6x the largest observed anomaly within two years.

## Calibration
The linear drift matrix and additive noise levels were estimated from the training part of the
processed indices (Y001-Y028; Y029-Y035 held out) as a monthly linear inverse model (matrix log of
the one-month propagator). TE damping, the seasonal, nonlinear and wind-noise parameters were then
hand-tuned against free-run statistics (seasonal variance cycle, PDFs, autocorrelation, spectrum,
event frequencies, phase locking, lead/lag relations), then refined by a greedy random-perturbation
search whose objective used only free-run statistics and forecast skill on the training years.
The held-out years (Y029-Y035) were used only to check forecasts and ensemble-smoother
reconstructions after the fact, never in any fit or search objective. No published calibrated model of this system was used.
