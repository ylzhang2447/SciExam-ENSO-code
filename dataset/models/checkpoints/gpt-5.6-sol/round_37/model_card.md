# Coupled stochastic recharge oscillator

## State and units

The state is `(TC, TE, hW, u, tau)` in the dimensional units required by the
interface. Internally, the state is divided by the supplied scales `(7.5 degC,
7.5 degC, 150 m, 1.5 m/s, 5 m/s)`, and time is divided by the supplied two-month
scale. Thus the integration is performed entirely in nondimensional variables
before conversion back to dimensional output.

## Equations

Let `z` be the nondimensional state, `m` its fitted equilibrium, `s=t/2` the
nondimensional time, and `G` the full coupled drift matrix. In per-month notation,
the drift is

`F(z,t) = G(z-m) + Fseason(z,t) + Fnl(z)`.

The equivalent nondimensional SDE integrated by Euler--Maruyama is

`dz = 2 F(z,t) ds + sqrt(2) L dW_s`.

Every row of `G` depends on multiple state variables. In particular, SST excites
the rapidly adjusting wind state; wind and eastern SST discharge western heat
content; western heat content drives the current; and thermocline, current, and
wind feedbacks act differently on central and eastern SST. The least-damped
complex mode is the interannual recharge oscillator.

Two periodic coefficients represent the seasonal basic state. The atmospheric
response to central SST is strongest in late boreal summer, and a separate
central-to-eastern SST coupling follows the seasonal transition coefficient in
the calibration record. These terms synchronize event growth and termination
with boreal winter without imposing an SST curve.

For asymmetry, define `C(v)=v^3/(1+(v/0.5)^2)`. The TC equation damps its positive
tail with `C(max(TC-mTC,0))`, while the TE equation damps its negative tail with
`C(min(TE-mTE,0))`. This bounded thermocline/SST saturation permits stronger
eastern warm events and stronger central cold events while remaining globally
well behaved. The TC/TE one-sided coefficients are 24 and 28; symmetric TC and
TE coefficients of 0.05 and 0.2 supply additional soft saturation. A weak bounded current
saturation (coefficient 0.3) controls unrealistically large `u` excursions without
clipping the recharge cycle. A heat-content saturation (0.4) limits
rare hW excursions and prevents excessive ocean-state variance.

A small bounded warm-central transfer into the eastern SST equation represents
nonlinear eastward development of established central events. It changes event
type through the coupled state and does not prescribe event timing.

`L` is a non-diagonal diffusion factor, so unresolved forcing is shared across
the coupled variables. The first driver has negatively skewed weather
innovations, and the second includes rare positive heating impulses at 0.03 per
month. Part of that driver is shared with TC. Its Bernoulli probability scales with `dt`, preserving
its physical event rate when the timestep changes. The explicit `tau` state is a
fast, noisy atmospheric process coupled back to all four ocean variables.

## Calibration

The initial monthly transition and residual covariance were estimated from only
January 1980--December 2004 after nondimensionalization. The transition was
converted to a quarter-month Euler generator and the diffusion was converted so
four substeps recover the monthly residual covariance. The slow complex mode,
seasonal terms, and bounded saturation were then adjusted against the fixed
calibration diagnostics. Post-2004 values were used only by the provided forecast
validation check, not as fitting targets.

## Validation summary

All supplied numerical checks complete with deterministic seeded behavior, no
input mutation, and finite 80-year integrations. In the default long run, both
SST seasonal-variance maxima occur in December, and TE skewness is close to the
observed value. Both simulated SST periodograms select 58.4 months rather than
60. Western heat content has the observed three-month lag behind TE and a
four-month lag behind TC. The extreme-EP rate is about 7.8 per century (observed
8), mixed events occur about 2.8 times per century, and episodes lasting at least
12 months occur about 17 times per century (observed 20). On the untouched forecast
block, SST ensemble-mean RMSE beats persistence at every supplied lead: at 12
months it is about 0.114 versus 0.150, with CRPS about 0.064 versus persistence MAE 0.120.

Known compromises are overly weak 24-month anticorrelation, excess cold-event
frequency, and somewhat excessive tau variance and upper tails. Attempts to correct
these directly degraded recharge geometry, spectral concentration, stability, or
forecast skill, so they were not retained.
