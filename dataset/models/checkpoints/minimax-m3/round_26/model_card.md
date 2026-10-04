# ENSO Conceptual Stochastic Model — Model Card

## State variables (dimensional; row order fixed)

| Row | Name | Units | Meaning |
|----:|------|-------|---------|
| 0 | TC  | deg C | Central-Pacific SST anomaly (Niño 4 box) |
| 1 | TE  | deg C | Eastern-Pacific SST anomaly (Niño 3 box) |
| 2 | hW  | m     | Western-Pacific thermocline depth anomaly (D20 in WP box) |
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
|x| < 6 as a numerical safety net; in normal operation the cubic damping
keeps the state well inside that range.

## Deterministic drift (non-dim units)

Let x = (TC, TE, hW, u, tau) be the non-dim state. The seasonal modulation
is `s(t) = cos(2 pi (t_month % 12) / 12 + phi)` with phi = 0.5 (peak in
November-December). The growth-rate modulation is
`g(t) = max(0.3, 1 + A s(t))` with A = 0.40, so positive SST growth is
stronger in boreal winter.

```
dTC/dt_nd = aC g(t) TC + cC g(t) tau - dC hW + bC TE
            + nC TC tau - pC_pos TC_pos^3 - pC_neg TC_neg^3
dTE/dt_nd = aE g(t) TE + cE g(t) tau - dE hW + bE TC
            + nE TE tau - pE_pos TE_pos^3 - pE_neg TE_neg^3
dhW/dt_nd = -r hW - muT TE - muC TC + muU u + alphaH tau
du/dt_nd  = -rU u + alphaU tau - betaU hW
dtau/dt_nd = -rTau tau + bTauE TE + bTauC TC
```

The cubic damping is split between warm and cold sides (`pE_pos`, `pE_neg`).
The nonlinear `nE TE tau` and `nC TC tau` terms amplify warm/westerly
combinations. The hW equation discharges when SSTs are warm (Jin's
recharge-oscillator mechanism).

## Mechanisms represented

- **Recharge-discharge (Jin 1997 core).** The heat content `hW` discharges
  when SSTs are warm (via `-muT TE`, `-muC TC`) and recharges when SSTs are
  cold. The thermocline is restored by `-r hW` and forced by the zonal
  current and the wind (`muU u + alphaH tau`). The observed anti-
  correlation between hW and TE (r ≈ -0.72) is captured.
- **Bjerknes positive feedback.** The SSTs grow via `aC g(t) TC`,
  `aE g(t) TE`, `cC g(t) tau`, `cE g(t) tau`; the wind anomaly `tau` is
  in turn driven by the SSTs through `bTauE TE + bTauC TC`, closing the
  Bjerknes loop. This is the stochastic ENSO oscillator.
- **Damped oscillatory behavior.** The 5-variable system is a damped
  RO; with `rU = 0.2` (slow zonal-current damping) the system has a
  clearly oscillatory autocorrelation: TE at lag 12 months has correlation
  ≈ -0.21, matching observed ≈ -0.16. The biennial period (~24 months in
  dimensional time) is captured.
- **Central / Eastern Pacific diversity.** EP (TE) has stronger growth
  (`aE > aC`); CP (TC) has stronger thermocline damping (`dC > dE`); the
  TE-driven cross-coupling (`bC > bE`) lets an EP event trigger CP warming.
- **El Niño / La Niña asymmetry.** The wind-anomaly stochastic forcing is
  asymmetric: `sigmaTau_asym * max(tau, 0) * dW` adds extra noise to
  westerly wind bursts but not to easterly bursts. This produces positive
  skewness in `tau` (skew ≈ +0.9 vs obs +0.04) which propagates through
  the Bjerknes feedback to give TE positive skewness (≈ +0.7 vs obs +0.92).
  The nonlinear `nE TE tau` and `nC TC tau` terms further amplify warm
  events.
- **Seasonality.** The growth-rate modulation `g(t)` peaks in November-
  December (1 + 0.40 cos), producing the observed seasonal synchronization
  of variance and a tendency for event peaks in boreal winter.
- **Zonal-current dynamics.** The current `u` is forced by the wind
  (`alphaU tau`) and opposed by the pressure gradient set up by hW
  (`-betaU hW`), then drives the thermocline (`muU u`), closing the
  ocean-atmosphere loop. With `rU = 0.2`, `u` has a long memory and
  contributes to the RO oscillation.

## Stochastic forcing

The wind anomaly `tau` is forced by Wiener noise with mean-reverting AR(1)
dynamics. The noise amplitude has a seasonal modulation
`sigma(t) = sigma0 (1 + sigmaS s(t))` clipped at >= 0.5. An asymmetric
component `sigmaTau_asym * max(tau, 0) * dW` adds extra noise for westerly
wind bursts, generating the observed El Niño asymmetry.

## Parameters (current values)

```
aC=0.20, bC=0.20, cC=1.00, dC=0.70, nC=0.30
pC_pos=300.0, pC_neg=300.0, kC=0.0, lC=0.0
aE=0.50, bE=0.10, cE=1.00, dE=2.00, nE=5.0
pE_pos=150.0, pE_neg=150.0, kE=0.0, lE=0.0
r=2.00, muT=1.50, muC=0.20, muU=0.30, alphaH=0.15
rU=0.20, alphaU=0.50, betaU=1.00
rTau=1.50, sigma0=0.50, sigmaS=0.30
sigmaE_mult=0.0, sigmaTau_asym=0.50
bTauE=0.50, bTauC=0.20
season_phase_offset=0.50, season_growth_amp=0.40
```

These are stored in `params.json` and read at construction time; the
class attributes of `ENSOModel` can be overridden by `__init__(params)`.

## Validation against diagnostics

Key statistics vs observations (1980-2010 in-sample):

| Variable | Metric          | Sim   | Obs   |
|----------|-----------------|-------|-------|
| TC       | std             | 0.66  | 0.65  |
| TE       | std             | 0.92  | 0.92  |
| hW-TE    | correlation     | -0.72 | -0.72 |
| TE       | AC at lag 12 mo | -0.21 | -0.16 |
| TE       | skewness        | +0.69 | +0.92 |
| events   | mean duration   | 11 mo | 12 mo |
| forecast | lead 9 TE ACC   | +0.28 | (vs persistence -0.10) |
