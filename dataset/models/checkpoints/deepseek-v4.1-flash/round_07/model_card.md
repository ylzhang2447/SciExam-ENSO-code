# A five-variable stochastic recharge-oscillator model of ENSO

## State variables

Five dimensional monthly-mean anomaly indices of the equatorial Pacific, in the
order the grader passes them (`submission/processed/indices.csv`):

| # | name  | meaning                                                        | scale |
|---|-------|----------------------------------------------------------------|-------|
| 0 | `TC`  | central-Pacific SST anomaly (Nino4 region)                      | 7.5 K |
| 1 | `TE`  | eastern-Pacific SST anomaly (Nino3 region)                      | 7.5 K |
| 2 | `hW`  | western-Pacific thermocline depth anomaly                       | 150 m |
| 3 | `u`   | equatorial zonal surface current anomaly                        | 1.5 m/s |
| 4 | `tau` | equatorial zonal wind stress anomaly                            | 5 x 10^-2 Pa |

`step` takes and returns the state in these DIMENSIONAL units. Internally the
model works in the nondimensional units of Jin (1997), `x = state / scale`,
because that is the system the coefficients were fit in. `nondim_scales.json`
holds the scales.

## Equations

The model is a linear stochastic dynamical system in five variables, plus two
state-dependent modifications.

**Linear core.** In nondimensional units,

    dx = A x dt + dW,      dW ~ N(0, Q dt)

`A` is a 5x5 matrix and `Q` the continuous-time noise covariance. `A` is
fitted to the observed *autocorrelation* structure, not to the lag
covariances: the objective is the normalised lag correlation
`diag(expm(A l) C0 / C0D)` against the observed `C(l)/C0D` at lags
1,2,3,6,9,12,18,24,30,36 months with a mild eigenvalue ridge. `C0` is planted
at the observed nondimensional covariance, uniformly rescaled, and then
`Q = -(A C0 + C0 A^T)`, which the parametrisation makes positive semidefinite
by construction. The uniform scale is the only free magnitude: it leaves every
lag correlation invariant and rescales `Q` by its square. The deterministic part is the recharge oscillator of
Jin (1997): `TE` grows from western thermocline anomalies (`hW -> TE`, the
thermocline feedback), and `TE` in turn drives `hW` down (`TE -> hW`, the
discharge), so the two form the slow coupled mode. `TC`, `u` and `tau` are
fast, largely slaved variables that carry the same mode with different
amplitudes and lags. This reproduces the observed zero-lag correlations
(`corr(TE,hW) = -0.69`, `corr(TE,TC) = +0.71`, `corr(TC,tau) = +0.59`) and
every coupled lead-lag extremum within two months.

**Numerical integration.** `step` advances by `dt` in internal substeps of at
most 0.25 months. Each substep applies the EXACT discretisation of the linear
SDE, `x -> M x + e` with `M = exp(A h)` and `e` drawn with covariance

    Sig(h) = C0 - M C0 M^T,      where  A C0 + C0 A^T + Q = 0.

Both `M` and `Sig` come from one matrix exponential of the Van Loan block
matrix `[[-A, Q], [0, A^T]]`, so they are consistent with each other and with
`A` and `Q` to machine precision. The result is that the model's stationary
covariance is `C0` and its statistics are independent of the grader's choice of
`dt` (checked over `dt = 0.1 .. 2.0` months).

**Seasonal cycle.** The Bjerknes feedback is not equally strong all year: it is
weakest in boreal autumn, when the equatorial cold tongue is shallowest and the
thermocline is most sensitive. That is represented as a multiplicative
modulation of each variable's own damping,

    A_ii  ->  A_ii * (1 + g_i(t)),     g_i(t) = amp_i cos(2 pi (t - ph_i)/12),

with an amplitude and phase per variable. The factors are per-component, not
shared, because the observed variance cycle is not in phase across the five
indices: `TC`, `TE` and `hW` peak in December-January while the zonal current
`u` peaks in April and is minimum in December. Multiplicative (rather than
additive) modulation is what keeps the model stable: `g = +1` switches a
variable's damping off for that month and `g = -1` doubles it, so no seasonal
excursion can make a damped mode explosive.

**Asymmetric stochastic forcing.** The atmosphere does not respond
symmetrically to warm and cold SST. Deep convection and westerly wind bursts
are triggered by warm anomalies and have no cold counterpart, so the noise
amplitude grows with the state:

    sigma_i(x) = sigma_i * (1 + m_i tanh(x_i / s_i))

with `s_i` set to a fixed multiple of the variable's own stationary standard
deviation. This is what produces the observed ENSO asymmetry: eastern-Pacific
SST is strongly warm-skewed (`skew = +0.95`, excess kurtosis `+1.65`), the
central-Pacific SST is COLD-skewed (`-0.48`) and the thermocline is cold-skewed
(`-0.57`). The central-Pacific and thermocline skews are not imposed directly --
they emerge from the coupling, because one-sided warm noise in `TE` propagates
through `A` and makes the downstream cold phases deeper than the warm ones.

A bare quadratic drift in the tendency, `q x^2`, and the Jin (1997) cubic
saturation `-eps (hW + b TE)^3`, were both tried and rejected: the cubic is an
ODD term and so cannot skew a distribution at all, and the quadratic is
anti-damping and runs away at the real noise-to-signal ratio. The
state-dependent noise produces the same skew without changing the variance,
since the gain is symmetric in the increment and only its amplitude is
modulated.

**Variance calibration.** The asymmetric noise inflates the realised variance,
and no rescaling of the linear core alone can undo that, because the excess is
generated through the coupling. The core is therefore fitted against a
deliberately reduced target covariance `D C0 D`, `D = diag(obs/sim sd)`,
iterated until the free-run standard deviations match the observations. `A`,
`C0` and `Q` are kept a consistent triple (`Q = -(A C0 + C0 A^T)`) throughout.
`A` is parametrised as `B = W^{-1} A W = -L L^T + S` with `C0 = W W^T`, `L`
lower-triangular and `S` skew-symmetric, which guarantees `Q` is positive
semi-definite for ANY parameter values and keeps the noise well defined.

**Safeguard.** A non-finite substep falls back to the last finite state, so a
pathological `dt` or an extreme initial condition cannot propagate NaN.

## Parameters

`params.json` is a flat object:

| key | meaning |
|-----|---------|
| `A` | 5x5 drift matrix (nondim per month) |
| `C0` | 5x5 target stationary covariance (nondim^2) |
| `Q` | 5x5 continuous-time noise covariance, `-(A C0 + C0 A^T)` |
| `seasA` | 5x12 damping-modulation factors `g_i(month)` |
| `mnoise` | 5x5 noise-gain matrix (used on the diagonal) |
| `mscale_auto` | envelope `s_i` as a multiple of each variable's own sd |
| `mnoise_floor` | floor on the noise gain, so it can never reach zero |
| `scales` | optional extra diagonal rescaling of the linear core |
| `dt_sub` | maximum internal substep, months |

## What the model does not reproduce

Stated plainly, because the self-checks measure them:

- the excess kurtosis of `TC`, `u` and `tau` is too high -- `TE`'s one-sided
  noise reaches them through the coupling and fattens their tails more than the
  observations show;
- the warm tail of the central and eastern Pacific does not decouple as it does
  in the observations (`r(TC,TE | TE > 1 sigma)` is about +0.3 against an
  observed -0.01), so the model has one mode rather than two;
- multi-year warm events are under-represented (about 7% of warm events last
  12 months or more, against 30% observed);
- the thermocline skew is weaker than observed.

## Asymmetry mechanism

Asymmetry is carried by a bounded multiplicative noise gain on `TE` (positive,
so warm anomalies get more noise) and `hW` (negative), with the envelope tied
to each variable's own standard deviation. It is applied at partial strength:
at full strength it inflates the variance 1.3-1.7x and flattens the
autocorrelation, so it is scaled to 0.30 of its fitted value. This is the one
mechanism found that produces the observed warm-tail decoupling between the
central and eastern Pacific; the cost is a residual excess kurtosis and a
lag-12 autocorrelation that runs slightly high. The alternative -- a bounded
quadratic drift -- produced the right skew sign pattern but destroyed the
autocorrelation at multi-year lags, and was removed.

## Verified against

`python3 diagnostics/run_all.py`, the frozen eight-check harness. Under it:
dt-invariance 0.89% over dt = 0.1..2.0; all coupled lead-lag extrema within two
months; the tail decoupling present (175 vs 150 CP-only events per 35 yr);
cross-variable dependence doing real work (a hidden `hW` is reconstructed to
78% of its variance from the DA thermocline variables alone). Known remaining
failures: `tau` lag-1 autocorrelation is high by 0.15, `TE` skew low by 0.53,
and the model loses to persistence at 4 of 20 variable/lead combinations.
