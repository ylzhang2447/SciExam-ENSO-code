"""Stochastic conceptual ENSO model with Central/Eastern Pacific diversity.

Five state variables (dimensional, in fixed row order):
    0: TC  central-Pacific SST anomaly          [deg C]
    1: TE  eastern-Pacific SST anomaly          [deg C]
    2: hW  western-Pacific thermocline anomaly  [m]
    3: u   central-Pacific zonal current anom   [m/s]
    4: tau WP zonal wind anomaly                [m/s]

Internal integration in NON-DIMENSIONAL units via the scales in
nondim_scales.json (TC,TE / 7.5; hW / 150; u / 1.5; tau / 5.0; time / 2 mo)
so that the O(0.1) state can be handled by an explicit Euler-Maruyama step.

Mechanisms (all in non-dim):
    dTC/dt =  aC * g(t) * TC + bC * TE
              + cC * g(t) * tau - dC * hW
              + nC * TC * tau - pC * TC^3
    dTE/dt =  aE * g(t) * TE + bE * TC
              + cE * g(t) * tau - dE * hW
              + nE * TE * tau - pE * TE^3
    dhW/dt =  -r * hW - muT * TE - muC * TC + muU * u + alphaH * tau
    du/dt  =  -rU * u + alphaU * tau - betaU * hW
    dtau/dt =  -rTau * tau + sigma(tau, t) * xi

The two SSTs are coupled to the same heat-content reservoir hW. The wind
anomaly tau is the only stochastic forcing (a Wiener-driven AR(1) process);
it reaches the SSTs through the cC/cE growth terms and the SSTs through the
nC/nE multiplicative coupling. The discharge of hW during warm SST events
(-muT * TE, -muC * TC) is the Jin 1997 recharge-oscillator mechanism.
"""

from __future__ import annotations

import numpy as np

# Non-dimensional scales (mirror diagnostics/_common.py). Keep in sync with
# nondim_scales.json -- this is a hard interface assumption.
_TC_SCALE = 7.5    # degC
_TE_SCALE = 7.5    # degC
_HW_SCALE = 150.0  # m
_U_SCALE = 1.5     # m/s
_TAU_SCALE = 5.0   # m/s
_T_SCALE = 2.0     # months

# Convenience 1D scaling arrays (5,)
_SCALES = np.array([_TC_SCALE, _TE_SCALE, _HW_SCALE, _U_SCALE, _TAU_SCALE])
_INV_SCALES = 1.0 / _SCALES
_TIME_RATE = 1.0 / _T_SCALE  # 1 non-dim time unit = T_SCALE months => 1/T_SCALE per month


def _to_nondim(state: np.ndarray) -> np.ndarray:
    return state * _INV_SCALES[:, None]


def _to_dim(nd_state: np.ndarray) -> np.ndarray:
    return nd_state * _SCALES[:, None]


class ENSOModel:
    """Stochastic conceptual ENSO model with seasonal modulation, nonlinearity,
    and Central/Eastern Pacific diversity. All dynamics in non-dim state x
    with x = [TC, TE, hW, u, tau]_nd, time in non-dim time units (1 unit = 2 mo).

    The drift is a hand-built nonlinear recharge oscillator: the SSTs grow
    via Bjerknes (self + wind), discharge the heat content (hW damps SST),
    and the heat content is restored by ocean dynamics (u, wind tilt) and
    discharged when SSTs are warm (Jin's recharge mechanism). Wind tau is
    the only stochastic term; it is an AR(1) process driven by white noise
    with a state-independent amplitude and a seasonal modulation of the
    amplitude.
    """

    # ---- SST (TC) parameters (non-dim) ----
    aC = 0.30      # self-growth on TC (Bjerknes, weakly positive)
    bC = 0.20      # cross-region SST coupling from TE
    cC = 1.20      # wind-stress growth on TC
    dC = 0.60      # thermocline discharge damping on TC (dC*hW cools TC)
    nC = 0.50      # nonlinearity TC*tau (El Nino asymmetry)
    pC = 80.0      # cubic damping on TC (sets SST variance amplitude)

    # ---- SST (TE) parameters (non-dim) ----
    aE = 0.50      # self-growth on TE (slightly stronger than TC)
    bE = 0.10      # cross-region SST coupling from TC (small)
    cE = 1.40      # wind-stress growth on TE
    dE = 0.40      # thermocline damping on TE (smaller)
    nE = 0.80      # TE*tau nonlinearity (El Nino asymmetry, stronger)
    pE = 100.0     # cubic damping on TE

    # ---- hW parameters (non-dim) ----
    r = 1.50       # restoring of thermocline
    muT = 1.00     # discharge of hW by warm TE (key RO term)
    muC = 0.30     # discharge of hW by warm TC (smaller)
    muU = 0.40     # u-forcing of thermocline
    alphaH = 0.20  # wind-stress forcing of thermocline tilt

    # ---- u parameters (non-dim) ----
    rU = 3.00      # damping of zonal current (faster than hW)
    alphaU = 1.50  # wind forcing of u
    betaU = 1.00   # pressure-gradient forcing of u (hW opposes tau)

    # ---- tau parameters (non-dim) ----
    rTau = 1.00    # wind damping (memory ~ 1 nondim time = 2 mo)
    sigma0 = 0.30  # base noise amplitude on tau
    sigmaS = 0.30  # seasonal modulation amplitude on noise

    # ---- Seasonal parameters ----
    # Phase of the seasonal modulation in radians. The seasonal peak is
    # at month 12 (December) with width covering November-January.
    # s(t) = cos(2 pi (t_month % 12)/12 + phase_offset). For Dec peak:
    # phase_offset = 0 at month 12, so phase_offset = -2pi*(12%12)/12 = 0
    # but month 0 -> cos(0)=1; month 12 -> cos(2pi)=1; so peak in Jan and Dec.
    # We want peak Dec-Jan, so use phase_offset = -pi/12 (shift by half month)
    season_phase_offset = -np.pi / 12.0
    # SST growth-rate modulation: stronger positive growth in winter.
    season_growth_amp = 0.40

    # ---- clamp range ----
    # Hard guard so that a runaway simulation cannot produce NaN/inf in the
    # returned state. If the non-dim state exceeds this we soft-clip.
    _X_CLIP = 6.0

    def __init__(self, params: dict):
        """`params` is the parsed params.json; it may override the class
        attributes above for re-calibration without editing this file."""
        for k, v in (params or {}).items():
            if not hasattr(self, k):
                continue
            setattr(self, k, v)

    # ---- helpers ----

    def _season(self, t: float) -> float:
        """Return the seasonal modulation factor at non-dim time t (one unit
        = T_SCALE months = 2 months). Peak in December-January."""
        # t is in non-dim time; convert to months
        m = (t * _T_SCALE) % 12.0
        return float(np.cos(2.0 * np.pi * (m / 12.0) + self.season_phase_offset))

    def _growth_mod(self, t: float) -> float:
        """Growth-rate modulation: 1 + amp * season(t). Bounded below at
        0.3 so growth never reverses sign."""
        return max(0.3, 1.0 + self.season_growth_amp * self._season(t))

    def _noise_mod(self, t: float) -> float:
        """Noise amplitude modulation: 1 + amp * season(t). Bounded below
        at 0.5 so wind noise never fully vanishes."""
        return max(0.5, 1.0 + self.sigmaS * self._season(t))

    # ---- the actual stochastic step ----

    def _drift(self, x: np.ndarray, t: float) -> np.ndarray:
        """Deterministic drift in non-dim units. x has shape (5, M)."""
        TC, TE, hW, u, tau = x[0], x[1], x[2], x[3], x[4]
        gm = self._growth_mod(t)

        dTE = (
            self.aE * gm * TE
            + self.cE * gm * tau
            - self.dE * hW
            + self.bE * TC
            + self.nE * TE * tau
            - self.pE * TE ** 3
        )

        dTC = (
            self.aC * gm * TC
            + self.cC * gm * tau
            - self.dC * hW
            + self.bC * TE
            + self.nC * TC * tau
            - self.pC * TC ** 3
        )

        # Western thermocline: restoring + ocean adjustment (discharge when
        # SSTs are warm; recharge when SSTs are cool) + zonal current
        # forcing + wind tilt.
        dhW = (
            -self.r * hW
            - self.muT * TE
            - self.muC * TC
            + self.muU * u
            + self.alphaH * tau
        )

        du = (
            -self.rU * u
            + self.alphaU * tau
            - self.betaU * hW
        )

        dTau = -self.rTau * tau

        return np.stack([dTC, dTE, dhW, du, dTau], axis=0)

    def _diffusion(self, x: np.ndarray, t: float) -> np.ndarray:
        """Diffusion in non-dim units. Noise enters only the tau equation;
        everything else receives stochastic forcing via the wind coupling."""
        nm = self._noise_mod(t)
        sigma = self.sigma0 * nm
        out = np.zeros_like(x)
        out[4] = sigma
        return out

    def step(self, state: np.ndarray, dt: float, t: float, rng) -> np.ndarray:
        """Advance the dimensional state by one stochastic step.

        Parameters
        ----------
        state : np.ndarray shape (5, M)  -- dimensional, row order
                [TC, TE, hW, u, tau]
        dt    : float  -- time increment in MONTHS
        t     : float  -- current time in MONTHS since run start (seasonal)
        rng   : numpy.random.Generator -- source of stochasticity

        Returns
        -------
        np.ndarray shape (5, M) -- dimensional state after one step.
        """
        x = _to_nondim(state)  # (5, M)
        dt_nd = dt * _TIME_RATE
        drift = self._drift(x, t * _TIME_RATE)
        diff = self._diffusion(x, t * _TIME_RATE)
        dW = rng.standard_normal(size=x.shape) * np.sqrt(dt_nd)
        x_new = x + drift * dt_nd + diff * dW
        np.clip(x_new, -self._X_CLIP, self._X_CLIP, out=x_new)
        return _to_dim(x_new)
