# Model card: a five-variable stochastic recharge oscillator with a CP branch

## State

| row | symbol | meaning | units |
|---|---|---|---|
| 0 | `TC`  | central Pacific SST anomaly (Nino4)        | degC |
| 1 | `TE`  | eastern Pacific SST anomaly (Nino3)        | degC |
| 2 | `hW`  | western Pacific thermocline depth anomaly  | m |
| 3 | `u`   | central Pacific zonal current anomaly      | m/s |
| 4 | `tau` | warm-pool 850 hPa zonal wind anomaly       | m/s |

`step(state, dt, t, rng)` takes and returns this vector in dimensional units,
with `dt` in months and `t` in months since the run start (`t = 0` is taken to
be 1 January, so the calendar month of a sample at time `t` is
`floor(t) % 12 + 1`). Internally everything is non-dimensional following
`nondim_scales.json` (T 7.5 degC, h 150 m, u 1.5 m/s, tau 5 m/s, one time unit
= 2 months); all parameters below are quoted in those units.

## The internal variable: warm water volume, not hW

The model does not integrate `hW` directly. It carries the zonal-mean warm water
volume

```
H = hW + b_tilt * TE ,
```

and converts at the two ends of `step` (`H` in, `hW = H - b_tilt*TE` out). The
reason is empirical: in the processed observations `hW + b*TE` with
`b ~ 8 m per degC` is in near-perfect quadrature with `TE` (lag-0 correlation
~0, maximum +0.35 with `H` leading by 9-12 months, maximum -0.63 with `TE`
leading by 6 months), which is exactly the Jin (1997) recharge variable.
Raw `hW` is that recharge variable *minus the wind-driven zonal tilt*: during
El Nino the trades slacken, the thermocline flattens and the west shoals
promptly. That tilt term is why the observed `corr(TE, hW)` is -0.74, close to
antiphase, rather than the ~0 a textbook recharge oscillator would give. Writing
`hW = H - b_tilt*TE` reproduces the lag-0 correlation, the 3-month lead of `TE`
over the discharge, and the negative skew of `hW` (inherited from the positive
skew of `TE`) at the same time.

## Equations

With `w = 2*pi/12`, seasonal factors

```
sC(t) = -c_C + s_C*cos(w*(t - phi_C))        net linear growth rate of TC
sE(t) = -c_E + s_E*cos(w*(t - phi_E))        net linear growth rate of TE
```

the drift (per non-dimensional time unit) is

```
dTC/dt = sC(t)*TC + g_C*H + a_C*u + w_C*tau
         + d_CE*(1 - k_a*tanh(TE/Ta))*TE
         + q_C*(TC^2 - v_C) - e_C*TC^3 - e5_C*TC^5

dTE/dt = sE(t)*TE + g_E*H + a_E*u + w_E*tau + d_EC*TC
         + q_E*(TE^2 - v_E) - e_E*(1 - k_e*tanh(TE/Ta))*TE^3 - e5_E*TE^5

dH/dt  = -r*H - (1 + s_h*cos(w*(t - phi_h)))*alpha_E*TE - alpha_C*TC
         - alpha_u*u - alpha_t*tau + q_H*(TE^2 - v_E)

du/dt  = -r_u*u + lam_H*H + lam_C*TC + lam_E*TE + mu_u*tau

tau    :  Ornstein-Uhlenbeck about  tau_eq = b_C*TC + b_E*TE + b_H*H,
          relaxation r_t, noise amplitude
          sig_tau * (1 + s_tau*cos(w*(t - phi_tau))) * (1 + m_w*tanh(2*TC))
          driven by a positively skewed innovation
          xi = (z + k_w*(z^2-1)/sqrt(2)) / sqrt(1+k_w^2),  z ~ N(0,1)
```

`TC`, `TE`, `H` and `u` are advanced by Euler-Maruyama with additive noise
`sig_C, sig_E, sig_H, sig_u`; the current noise is correlated with the wind
innovation at `rho_ut`. The wind uses the *exact* OU update
(`tau_eq + (tau-tau_eq)*exp(-r_t*dt) + sd*xi`) rather than Euler, so its
variance and its one-month decorrelation time do not depend on the step size the
grader chooses; the measured drift of the free-run standard deviations between
`dt = 0.01` and `dt = 0.5` months is at most a few percent. A hard clamp at 8
non-dimensional units and a non-finite guard sit at the end of `step`; in a
1000-year free run the clamp is never touched, so the tails are set by the
physics and not by the safety net.

## Mechanisms represented

**Recharge-discharge.** `-alpha_E*TE` (plus smaller `TC`, `u` and wind terms)
discharges the warm water volume when the east is warm; `g_E*H` and `a_E*u`
return it to the SST. The discharge itself carries an annual cycle (`s_h`,
`phi_h`, strongest in boreal autumn): without it the thermocline has almost no
seasonal cycle of variance, and with it the modelled `hW` variance contrast
matches the observed 1.57 and the discharge lead-lags come out exact. A small
`q_H*(TE^2 - v_E)` makes the discharge asymmetric, which keeps `hW` from
inheriting too much negative skew from `TE`; it is a positive feedback and the
free run runs away above `q_H ~ 0.2`, so it is kept small.
The pair is a damped oscillator with a ~4.3-year period
and an e-folding time of about 1.5 years, so the free run is a noise-sustained
oscillation rather than a limit cycle: `H` leads `TE` by roughly a quarter
period, `hW` composites are positive 12-18 months before a warm peak and
strongly negative at the peak, and the (hW, TE) phase plane circulates
anticlockwise at the observed rate.

**Two flavours.** `TE` is driven mainly by the thermocline and by zonal
advection; `TC` also feels the warm-pool wind directly (`w_C*tau`), and because
the wind is in turn slaved to `TC` (`b_C`), the centre carries its own weakly
damped, wind-driven CP mode. That mode gives central-Pacific events that are not
simply small eastern events, which is what produces a realistic CP share of warm
events and the observed fraction of months with `|TC| > |TE|`.

**Nonlinear flavour separation.** The projection of the eastern anomaly onto the
centre is asymmetric, `d_CE*(1 - k_a*tanh(TE/Ta))`: cold anomalies spread
basin-wide (La Nina is one broad pattern), warm ones stay east (El Nino splits
into EP and CP types). This reproduces the observed contrast between the
regression slope of `TC` on `TE` on the warm side and on the cold side.

**Asymmetry of the PDF.** `q_E > 0` makes warm eastern anomalies grow faster
than cold ones, and the cubic saturation is itself asymmetric
(`k_e > 0`: cold events saturate sooner), so `TE` is positively skewed with a
long warm tail while `TC` (with `q_C < 0`) is negatively skewed. The
skew *contrast* between the two regions, not just its magnitude, is the
signature of ENSO diversity the model is built to carry.

**Seasonal phase locking.** The seasonality is in the *net linear growth rate*
of the two SSTs, not in the coupling coefficients: `TE` grows fastest around
month 8 and is most damped in boreal spring, which locks event peaks to late
boreal winter and puts the variance maximum in Dec-Feb. The wind noise carries
its own annual cycle (`s_tau`, `phi_tau`) peaking in early boreal winter.

**Stochastic forcing.** The warm-pool wind is 55-65% noise: an OU process with a
one-month decorrelation time, seasonally modulated, mildly amplified when the
central Pacific is warm (westerly wind bursts) and positively skewed. It is the
main source of irregularity; the SST equations carry only small additive noise.
The wind index used here is a warm-pool/CP index that is almost uncorrelated
with Nino3 once `TC` is removed, so `w_E` is deliberately small: in the
observations this wind is not the Bjerknes wind of the eastern Pacific, and
making it one injects several times too much eastern variance.

## Fitting

Parameters were initialised from a VAR(1) fit to the processed indices over
1980-2004 (converted to a continuous drift by a matrix logarithm) and then tuned
by hand against the diagnostics in `diagnostics/`: marginal moments and the
lag-0 correlation matrix, seasonal phase locking, autocorrelation and spectra,
the recharge lead-lag and composites, event statistics and the EP/CP split,
forecast skill against persistence, and an ensemble Kalman reconstruction of
unobserved variables. The decade 2005-2014 was held out of the fitting and used
only as a final check; the model beats persistence there at every lead tested
for both `TE` and `TC`.

## Known limitations

* `c_E` is a *net* linear coefficient (the fast Bjerknes feedbacks that operate
  through the wind are folded into it), so it is close to zero and cannot be
  read as a physical SST damping time.
* The negative lobe of the `TE` autocorrelation is -0.32 against -0.41
  observed: the biennial rebound is too weak. Its depth is set by the delay in
  the `H -> u -> TE` feedback, i.e. by `r_u`; a slower current reaches the
  observed -0.41 exactly, but then `u` decorrelates in 6 months instead of 3.5
  and its lag-0 correlations with the two SSTs change sign. The chosen `r_u`
  splits that difference.
* The forecast ensemble is still underdispersive at short leads: spread is about
  0.77 of the RMS error at lead 3.
* Cold events are somewhat too frequent (33 vs 28 per century) and the fraction
  of months with `|TC| > |TE|` is 38% against 46% observed.
* `tau` decorrelates in 2.5 months against 5.3 in the observations. This is a
  sampling difference, not a model error: the observed index is a monthly mean,
  which suppresses the one-month wind noise and lengthens its autocorrelation,
  while the free run is sampled instantaneously. The wind's noise share (66% vs
  65%) and noise decorrelation time (1.0 month) both match.
