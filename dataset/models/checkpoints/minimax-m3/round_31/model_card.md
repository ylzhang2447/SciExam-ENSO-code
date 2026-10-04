# ENSO Conceptual Stochastic Model — Model Card

## State variables (dimensional; row order fixed)

| Row | Name | Units | Meaning |
|----:|------|-------|---------|
| 0 | TC  | deg C | Central-Pacific SST anomaly (Niño 4 box) |
| 1 | TE  | deg C | Eastern-Pacific SST anomaly (Niño 3 box) |
| 2 | hW  | m     | Western-Pacific heat content anomaly (warm water volume) |
| 3 | u   | m/s   | Central-Pacific zonal current anomaly (mixed-layer mean) |
| 4 | tau | m/s   | Western-Pacific 850 hPa zonal wind anomaly |

## Integration

The grader drives `ENSOModel.step(state, dt, t, rng)` from an external driver
(free run, ensemble forecast, data assimilation). The state in and out is
dimensional; the integrator works internally in non-dim units obtained from
`nondim_scales.json` (T 7.5 deg C, h 150 m, u 1.5 m/s, tau 5 m/s, time 2
months). The non-dim time-step is `dt_nd = dt_months / 2`.

The drift and the diffusion are evaluated at the start of each step and an
Euler-Maruyama update is applied. The non-dim state is soft-clipped to
|x_SST| < 0.5 for TC/TE and |x| < 1.0 for the other variables as a numerical
safety net; in normal operation the cubic damping keeps the state well
inside that range.

## Deterministic drift (non-dim units)

Let x = (TC, TE, hW, u, tau) be the non-dim state. The seasonal modulation
is `s(t) = cos(2 pi (t_month % 12) / 12 + phi)`; the growth-rate modulation
is `g(t) = max(0.3, 1 + A s(t))`. With `phi = 0` and `A = 0.0` (current
calibration), g(t) = 1 throughout the year.

```
dTC/dt_nd = aC g(t) TC + cC g(t) tau + dC hW + bC TE
            + nC TC tau - pC_pos TC_pos^3 - pC_neg TC_neg^3
            + kC TC_pos^2 - lC TC_neg^2
dTE/dt_nd = aE g(t) TE + cE g(t) tau + dE hW + bE TC
            + nE TE tau - pE_pos TE_pos^3 - pE_neg TE_neg^3
            + kE TE_pos^2 - lE TE_neg^2
dhW/dt_nd = -r hW - muT TE - muC TC + muU u + alphaH tau
du/dt_nd  = -rU u + alphaU tau - betaU hW
dtau/dt_nd = -rTau tau + bTauE TE + bTauC TC
```

### Sign convention (Jin 1997)

The crucial sign in the SST equations is the `+dC hW` and `+dE hW`
coupling. Following Jin (1997), positive heat content (`hW > 0`, warm
subsurface / deeper thermocline) *warms* the SST through the thermocline
feedback. The SST in turn discharges the heat content (`-muT TE`) —
this is the recharge-discharge oscillator. With both signs positive,
the loop TE+ → hW- → TE- → hW+ → TE+ gives a self-sustaining oscillation.

In the prior version of this model the coupling was negative (`-dC hW`);
that produced a linearly unstable system whose only attractor was the
cubic limit (bistability). Flipping the sign was the change that made
the model oscillate.

### Nonlinearity and asymmetry

- Cubic damping is split between warm and cold (`pE_pos`, `pE_neg`) with
  cold-side damping much stronger (`pE_neg >> pE_pos`). This damps La
  Niña excursions more than El Niño excursions, generating the observed
  positive TE skewness.
- Quadratic terms `+lE TE_neg^2` (cold-side extra damping) and
  `-lE TE_neg^2` further enhance the asymmetry.
- Multiplicative noise on tau (`sigmaTau_asym * max(tau, 0)`) gives extra
  westerly wind bursts, propagating to TE via the Bjerknes feedback.

## Mechanisms represented

- **Recharge-discharge (Jin 1997 core).** Positive hW warms SST (via
  `+dE hW`); warm SST discharges hW (via `-muT TE`). hW is restored by
  `-r hW` and forced by the zonal current (`muU u`). The observed anti-
  correlation between hW and TE (r ≈ -0.72) is captured.
- **Bjerknes positive feedback.** The SSTs grow via `aC g(t) TC`,
  `aE g(t) TE`, `cC g(t) tau`, `cE g(t) tau`; the wind anomaly `tau` is
  in turn driven by the SSTs through `bTauE TE + bTauC TC`, closing the
  Bjerknes loop. This is the stochastic ENSO oscillator.
- **Damped oscillatory behavior.** The 5-variable system is a damped
  RO; the natural oscillation period depends on `dE`, `dC`, `muT`, `r`
  via `T ~ 2 pi / sqrt(dE * muT)`. With the current calibration the
  period is ~50 months (observed ~52).
- **Central / Eastern Pacific diversity.** TC and TE have distinct
  responses: EP (TE) is more strongly coupled to hW (`dE > dC`); CP (TC)
  is more strongly coupled to wind (`cC > cE`). The TE→TC cross coupling
  `bC` lets an EP event seed a CP warming. Independent additive noise on
  TC (`sigmaC`) and on u (`sigmaU`) lets CP/EP events decouple.
- **El Niño / La Niña asymmetry.** Asymmetric cubic damping (`pE_neg >
  pE_pos`), asymmetric quadratic terms (`lE`), and asymmetric wind noise
  (`sigmaTau_asym`) all combine to give TE positive skewness (+0.8,
  observed +0.92).
- **Zonal-current dynamics.** The current `u` damps (`-rU u`) and is
  forced by the wind via `alphaU` and opposed by the pressure gradient
  `-betaU hW`. It forces the thermocline (`muU u`), closing the ocean-
  atmosphere loop.

## Stochastic forcing

The wind anomaly `tau` is a mean-reverting AR(1) process driven by Wiener
noise:

```
dtau = (-rTau tau + bTauE TE + bTauC TC) dt + sigma dW
```

with `sigma = sigma0 * (1 + sigmaS s(t))` plus an asymmetric component
`sigmaTau_asym * max(tau, 0)` for westerly wind bursts. Independent additive
noise is added to TC (`sigmaC`) and to u (`sigmaU`) to allow CP events to
be partially independent of the wind forcing.

## Parameters (current values)

```
aC=0.10, bC=0.05, cC=0.30, dC=0.20, nC=0.0
pC=15.0, pC_pos=15.0, pC_neg=15.0, kC=0.0, lC=0.0
aE=0.10, bE=0.05, cE=0.20, dE=0.30, nE=0.50
pE=12.0, pE_pos=3.0, pE_neg=20.0, kE=0.0, lE=2.0
r=0.80, muT=0.30, muC=0.0, muU=0.50, alphaH=0.0
rU=2.0, alphaU=0.0, betaU=0.0
rTau=1.0, sigma0=0.40, sigmaS=0.0
sigmaE_mult=0.0, sigmaTau_asym=0.40
sigmaU=0.20, sigmaC=0.05
bTauE=0.30, bTauC=0.0
season_phase_offset=0.0, season_growth_amp=0.0
```

These are stored in `params.json` and read at construction time; the
class attributes of `ENSOModel` can be overridden by `__init__(params)`.

## Validation against observations

Key statistics vs observed (1980-2010 in-sample, per-seed ensemble of 8):

| Variable | Metric          | Sim   | Obs   |
|----------|-----------------|-------|-------|
| TE       | std             | 1.12  | 0.92  |
| TC       | std             | 1.03  | 0.65  |
| hW-TE    | correlation     | -0.69 | -0.72 |
| tau-TE   | correlation     | +0.43 | +0.43 |
| TE       | skewness        | +1.13 | +0.92 |
| TC-TE    | correlation     | +0.74 | +0.71 |
| u-TE     | correlation     | +0.01 | -0.04 |
| TE       | period          | 52 mo | 52 mo |
| EL       | mean duration   | 9.9 mo | 11.6 mo |
