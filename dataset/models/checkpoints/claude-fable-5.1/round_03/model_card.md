# ENSO diversity stochastic recharge-oscillator model

## State variables (dimensional in/out of `step`)
TC (central-Pacific SST anomaly, degC), TE (eastern-Pacific SST anomaly, degC), hW (western-Pacific
thermocline depth anomaly, m), u (central-Pacific zonal current anomaly, m/s), tau (western-Pacific
zonal wind anomaly, m/s). Internally non-dimensionalized with nondim_scales.json
(T/7.5, h/150, u/1.5, tau/5, time/2 months).

## Equations (non-dimensional; rates per non-dim time unit; t in months from 1 Jan)
x = (TC, TE, hW, u, tau)

    dx/dt = A x + N(x, t) + Sigma(x, t) dW/dt

A is a 5x5 linear operator (params `A_<row>_<col>`) encoding the two-region recharge oscillator:
* Bjerknes/thermocline feedback: hW -> TE, hW -> TC (positive);
* zonal-advective feedback: u -> TC (positive), which makes CP-type warming possible without a deep
  eastern thermocline;
* recharge/discharge: warm TC/TE and westerly tau drain the western thermocline (TE, tau -> hW negative);
* wind-driven current: tau, hW -> u; u damps quickly (~2.5 months);
* atmospheric response: TC, TE -> tau (fast, ~1.2-month memory). tau is the stochastic driver.

Nonlinear and seasonal corrections N (only on TC and TE):
* seasonal growth rate: (g_c cos + g_s sin)(2 pi (t-0.5)/12) times TC or TE; TE growth is largest
  in late summer/autumn and damping largest in spring, which locks event peaks to Nov-Jan;
* seasonal thermocline coupling: (b_c cos + b_s sin) hW;
* warm-side asymmetry: q_TE TE^2 / (1 + (TE/sat_TE)^2) (saturating), cubic damping n_TE TE^3 caps
  extreme events; TC has fitted quadratic and cubic damping.

Noise Sigma: additive white noise on every variable (amplitudes `s_<var>` from the regression
residuals); multiplicative on TE, s_TE (1 + m_TE TE), and on tau,
s_tau (1 + m_tau TC)(1 + s_tau_c cos + s_tau_s sin): westerly wind bursts are stronger when the
central Pacific is warm and in boreal winter/spring. This state-dependent noise is the main source
of El Nino / La Nina asymmetry (skewness, kurtosis) and of extreme EP events.

Integration: Euler-Maruyama in `step`, reproducible from the supplied Generator.

## Calibration
Linear operator: matrix logarithm of the 1-month lag regression (linear inverse model) of the
observed 1980-2014 non-dimensional indices. Seasonal, quadratic and cubic coefficients: least-squares
on the residual tendencies, then hand-amplified (seasonal TE growth, TE asymmetry, multiplicative
noise) to match observed seasonal variance contrast, peak phase locking, skewness and kurtosis of
TE, while keeping the 600-year free run inside a physical envelope (TE < ~5 degC).

## Mechanisms represented
Recharge-discharge (hW leads TE by ~3/4 period, discharge at peak), Bjerknes growth, zonal-advective
CP mode, seasonal phase locking, warm/cold asymmetry, stochastic wind forcing.
