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
is `s(t) = cos(2 pi (t_month % 12) / 12 - 11 pi / 6)`, peak in
November-January. The growth-rate modulation is `g(t) = max(0.3, 1 + A s(t))`
with A = 0.35, so positive SST growth is stronger in boreal winter.

```
dTC/dt_nd = aC g(t) TC + cC g(t) tau - dC hW + bC TE + nC TC tau - pC TC^3
dTE/dt_nd = aE g(t) TE + cE g(t) tau - dE hW + bE TC + nE TE tau - pE TE^3
dhW/dt_nd = -rH hW + muU u + alphaH tau
du/dt_nd  = -rU u + alphaU tau - betaU hW
dtau/dt_nd = -rTau tau + sigma(t) xi(t)
```

where `xi(t)` is a unit Wiener process and
`sigma(t) = sigma0 (1 + sigmaS s(t))` (clipped at >= 0.5 so wind noise never
fully vanishes).

## Mechanisms represented

- **Recharge-discharge (Jin 1997 core).** The heat content `hW` discharges
  when SSTs are warm and recharges when SSTs are cold, via the `-dC hW` and
  `-dE hW` damping terms; the thermocline is restored (`-rH hW`) and forced
  by the zonal current and the wind (`muU u + alphaH tau`). This produces
  the observed anti-correlation between hW and TE/TC, and the half-period
  phase lag (TE peaks, then hW peaks, then TE troughs).
- **Bjerknes positive feedback.** `aC g(t) TC`, `aE g(t) TE`, `cC g(t) tau`,
  `cE g(t) tau` couple the SSTs and the wind to themselves; with the wind
  forced by an AR(1) + noise process this is the stochastic ENSO
  oscillator.
- **Central / Eastern Pacific diversity.** `aE > aC` and `dE < dC` put more
  growth and less direct thermocline damping in the eastern box (so EP-type
  El Ninos dominate in TE), while the central box has stronger hW damping
  but stronger cross-coupling `bC > bE` to TE (so CP warming can be
  triggered by an EP event in TE). The smaller `cE` and `cC` together
  with `nE > nC` give TE more nonlinear amplification on warm events
  (El Nino asymmetry).
- **Nonlinearity / El Nino asymmetry.** Cubic damping `-pC TC^3` and
  `-pE TE^3` bounds the SST variance; the multiplicative terms `nC TC tau`
  and `nE TE tau` amplify positive SST + westerly wind combinations (so
  warm events are larger than cold events, matching the observed positive
  skew of TE).
- **Seasonality.** The growth-rate and noise-amplitude modulations
  `g(t)` and `sigma(t)` peak in boreal winter, producing the observed
  seasonal synchronization of variance and the November-January phase
  locking of event peaks.
- **Zonal-current dynamics.** The current `u` is forced by the wind
  (`alphaU tau`) and opposed by the pressure gradient set up by hW
  (`-betaU hW`), then drives the thermocline (`muU u`), closing the
  ocean-atmosphere loop.

## Stochastic forcing

A single Wiener process `xi(t)` drives the wind anomaly `tau` through an
AR(1) (mean-reverting) process with damping rate `rTau`. All other variables
receive their stochastic forcing through the wind-SST and wind-hW couplings.
The noise amplitude has a mild seasonal modulation so winter westerlies are
noisier (matching the observed stronger wind variability during the ENSO
active season).

## Parameters

The twenty parameters above (`aC, bC, cC, dC, nC, pC, aE, bE, cE, dE, nE,
pE, rH, muU, alphaH, rU, alphaU, betaU, rTau, sigma0, sigmaS,
season_growth_amp`) are stored in `params.json`. They are interpreted by
the class attributes of `ENSOModel` at construction time; re-running with
different parameters requires only an updated `params.json`.
