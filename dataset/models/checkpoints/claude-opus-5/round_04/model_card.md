# ENSO diversity model — model card

**Status: first-cut structure, not yet calibrated.** The equations below are in
place and the interface is working; the parameters are initial guesses carried
over from Jin (1997) plus rough scaling arguments, and are being fitted in the
next phase. The diagnostics in `diagnostics/` currently report large gaps in
the TE–hW phase relation, the TC/TE skew contrast and the zonal current.

## State

Dimensional, in the order the interface requires:

| row | variable | meaning | units |
|---|---|---|---|
| 0 | TC | central Pacific (Niño4) SST anomaly | degC |
| 1 | TE | eastern Pacific (Niño3) SST anomaly | degC |
| 2 | hW | western Pacific 20 °C isotherm depth anomaly | m |
| 3 | u | central Pacific mixed-layer zonal current anomaly | m/s |
| 4 | tau | western Pacific 850 hPa zonal wind anomaly | m/s |

Internally the model works non-dimensionally with the scales in
`nondim_scales.json` (T 7.5 degC, h 150 m, u 1.5 m/s, tau 5 m/s) and a time unit
of 2 months. `step` converts on the way in and out, so its argument and return
value are always dimensional and `dt` is always in months.

## Equations (non-dimensional; overdot is d/dt in units of 2 months)

Ocean adjustment, following Jin (1997) Eqs. (2.1) and (2.3):

    hE = h + beta_h  * tau            eastern thermocline (Sverdrup tilt)
    hC = h + beta_hc * tau            central Pacific thermocline
    h_dot  = -r h - alpha tau         recharge / discharge of warm-pool heat

SST, one equation per flavour, each with its own dominant feedback:

    TE_dot = -c_E TE + S_E(t) gamma_E hE + q_E TE^2 - e_E TE^3 + a_EC TC
    TC_dot = -c_C TC + S_C(t) (gamma_C hC + a_uC u) + q_C TC^2 - e_C TC^3

Eastern Pacific SST is driven by thermocline (upwelling) feedback; central
Pacific SST is driven mainly by zonal advection of the mean temperature
gradient by `u`, with a weaker thermocline term. The quadratic terms carry the
opposite signs that the observed skews demand (TE positively skewed, TC
negatively skewed); the cubics bound the amplitude.

Current and wind:

    u_dot   = -r_u (u - mu_u tau - lam_uh h)
    tau_dot = -r_tau (tau - b_C TC - b_E TE) + sigma(TC, t) xi

`S_E(t)`, `S_C(t)` are `1 + s cos(2 pi (t - phi)/12)` with `t` in months, so the
coupled growth rate has an annual cycle — this is the phase-locking mechanism.
The wind is an Ornstein–Uhlenbeck process relaxing toward its SST-forced value,
with a state-dependent and seasonally modulated amplitude
`sigma = sigma_tau (1 + m_w tanh(2 TC)) (1 + s_tau cos(2 pi (t - phi_tau)/12))`:
westerly bursts are stronger over a warm central Pacific and in boreal
winter–spring. This multiplicative noise is the model's source of El Niño /
La Niña asymmetry and of event-to-event irregularity.

Integration is Euler–Maruyama with all random numbers drawn from the supplied
`rng`, plus a hard clip of the non-dimensional state at `clamp` as a numerical
backstop (it should never bind; d01 reports how often it does).

## Mechanisms represented

- **Bjerknes feedback**: SST → tau → thermocline tilt → SST, positive loop.
- **Recharge–discharge**: westerly wind discharges zonal-mean heat content
  (`-alpha tau`), which turns the event around a few months after its peak.
- **Diversity**: two SST equations with different dominant feedbacks
  (thermocline in the east, zonal advection in the centre) and different signs
  of quadratic nonlinearity.
- **Phase locking**: annual modulation of the coupled growth rates and of the
  wind-burst amplitude.
- **Stochastic excitation**: the linear system is damped; the oscillation is
  sustained by the wind noise, whose amplitude depends on the state.

## Time convention

`t` is months since the run start and `t = 0` is taken to be 1 January, so a
state sampled at `t = k` belongs to calendar month `k % 12 + 1`. Seasonal
terms use this directly.
