# ENSO diversity stochastic recharge-oscillator model

## State variables (dimensional in/out of `step`)
TC (central-Pacific SST anomaly, degC), TE (eastern-Pacific SST anomaly, degC), hW (western-Pacific
thermocline depth anomaly, m), u (central-Pacific zonal current anomaly, m/s), tau (western-Pacific
zonal wind anomaly, m/s). Internally non-dimensionalized with nondim_scales.json
(T/7.5, h/150, u/1.5, tau/5, time/2 months). `step(state, dt, t, rng)` takes a (5, M) ensemble,
dt in months, t in months since 1 Jan of the run start, and returns the state after dt.

## Equations (non-dimensional; rates per non-dim time unit; t in months from 1 Jan)
x = (TC, TE, hW, u, tau); c, s = cos, sin(2 pi (t-0.5)/12); c2, s2 = the semi-annual harmonics.

    dx/dt = A x + N(x, t) + Sigma(x, t) dW/dt

A is a 5x5 linear operator (params `A_<row>_<col>`) encoding the two-region recharge oscillator:
* Bjerknes/thermocline feedback: hW -> TE, hW -> TC (positive);
* zonal-advective feedback: u -> TC (positive), which makes CP-type warming possible without a deep
  eastern thermocline;
* recharge/discharge: warm TC/TE and westerly tau drain the western thermocline (TE, tau -> hW negative);
* wind-driven current: tau, hW -> u; u damps quickly (~2.5 months);
* atmospheric response: TC, TE -> tau (fast, ~1.5-month memory). tau is the stochastic driver.

Nonlinear and seasonal corrections N:
* seasonal growth rates (g_TC_c c + g_TC_s s) TC and (g_TE_c c + g_TE_s s + g_TE_c2 c2 + g_TE_s2 s2) TE:
  TE growth is largest in late summer/autumn and damping largest in spring, which locks event
  peaks to Nov-Jan; the semi-annual term sharpens the locking;
* seasonal thermocline coupling (b_c c + b_s s) hW on TC and TE; seasonal hW damping (g_hW_c c + g_hW_s s) hW (sets the Jan-max/Aug-min thermocline variance cycle);
* warm-side asymmetry: q_TE TE^2 / (1 + (TE/sat_TE)^2) (saturating quadratic), cubic damping
  n_TE TE^3 caps extreme events; TC has fitted quadratic (q_TC) and cubic (n_TC) damping (plus optional warm-side term qw_TC and constant c_TC, both zero in the current parameters);
* nonlinear discharge q_hW TE^2 / (1 + (TE/sat_hW)^2): strong events of either sign drain hW
  (gives the negative hW skewness); cubic hW damping n_hW hW^3 bounds thermocline excursions.

Noise Sigma: white noise on every variable with amplitude s_<var> (1 + s_c c + s_s s + s_c2 c2 + s_s2 s2);
multiplicative factors (1 + m_TE TE) on TE, (1 + m_TC TC) on TC and (1 + m_tau TC) on tau (floored at 0.2):
westerly wind bursts and eastern-Pacific SST noise are stronger when the Pacific is warm, in boreal
winter/spring for tau and in spring for TE. This state-dependent noise is the main source of
El Nino / La Nina asymmetry (skewness, kurtosis) and of extreme EP events.

Integration: Euler-Maruyama in `step` (sub-stepping is done by the caller through dt), states are
clipped at 3 non-dim units as a safety bound; results are reproducible from the supplied Generator.

## Calibration
1. Linear operator: matrix logarithm of the 1-month lag regression (linear inverse model) of the
   observed 1980-2014 non-dimensional indices (stable by construction).
2. Seasonal, quadratic and cubic coefficients: least-squares on the residual tendencies, then
   hand-amplified (seasonal TE growth, TE asymmetry, multiplicative noise) to match observed seasonal
   variance contrast, peak phase locking, skewness and kurtosis of TE, while keeping the 700-year
   free run inside a physical envelope (TE < ~5.5 degC, |hW| < 75 m).
3. Deterministic drift refit: A and the seasonal growth terms were re-fitted (ridge toward the LIM
   values) to minimise the 1-, 3- and 6-month zero-noise prediction error of the full nonlinear
   model from observed states, so that forecasts from observed initial conditions beat persistence
   (6-month TE rmse/std 0.78 vs persistence 1.15 in sample).

## Mechanisms represented
Recharge-discharge (hW leads TE by ~3/4 period, discharge at peak), Bjerknes growth, zonal-advective
CP mode, seasonal phase locking, warm/cold asymmetry and extreme EP events, stochastic (state- and
season-dependent) wind forcing.
