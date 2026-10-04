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
    aC = 0.80      # self-growth on TC (Bjerknes, weakly positive)
    bC = 0.20      # cross-region SST coupling from TE
    cC = 1.00      # wind-stress growth on TC
    dC = 0.70      # thermocline discharge damping on TC (dC*hW cools TC)
    nC = 0.30      # nonlinearity TC*tau (El Nino asymmetry)
    pC = 70.0      # base cubic damping on TC
    pC_pos = 70.0  # cubic damping for warm TC (no asymmetry by default)
    pC_neg = 70.0  # cubic damping for cold TC
    kC = 0.0       # quadratic growth (faster for warm TC) -> skewness
    lC = 0.0       # quadratic damping for cold TC -> skewness

    # ---- SST (TE) parameters (non-dim) ----
    aE = 1.06      # self-growth on TE (slightly stronger than TC)
    bE = 0.10      # cross-region SST coupling from TC (small)
    cE = 1.00      # wind-stress growth on TE
    dE = 0.85      # thermocline damping on TE (smaller)
    nE = 0.50      # TE*tau nonlinearity (El Nino asymmetry, stronger)
    pE = 90.0      # base cubic damping on TE
    pE_pos = 90.0  # cubic damping for warm TE
    pE_neg = 90.0  # cubic damping for cold TE
    kE = 0.0       # quadratic growth (faster for warm TE) -> skewness
    lE = 0.0       # quadratic damping for cold TE -> skewness

    # ---- hW parameters (non-dim) ----
    r = 1.20       # restoring of thermocline
    muT = 1.20     # discharge of hW by warm TE (key RO term)
    muC = 0.20     # discharge of hW by warm TC (smaller)
    muU = 0.30     # u-forcing of thermocline
    alphaH = 0.15  # wind-stress forcing of thermocline tilt

    # ---- u parameters (non-dim) ----
    rU = 3.00      # damping of zonal current (faster than hW)
    alphaU = 1.50  # wind forcing of u
    betaU = 1.00   # pressure-gradient forcing of u (hW opposes tau)

    # ---- tau parameters (non-dim) ----
    rTau = 1.50    # wind damping (memory ~ 0.7 nondim time = 1.3 mo)
    sigma0 = 0.50  # base noise amplitude on tau
    sigmaS = 0.30  # seasonal modulation amplitude on noise
    sigmaE_mult = 0.0  # multiplicative noise on TE (state-dependent, off by default)
    sigmaTau_asym = 0.0  # asymmetric noise on tau: extra noise for tau>0
    # Bjerknes feedback on tau: warm SST -> westerly wind anomaly
    bTauE = 0.50   # tau response to TE (westerly when TE warm)
    bTauC = 0.20   # tau response to TC (weaker)

    # ---- Seasonal parameters ----
    # Phase of the seasonal modulation in radians. The seasonal peak is
    # at month 12 (December) with width covering November-January.
    # s(t) = cos(2 pi (t_month % 12)/12 + phase_offset). For Dec peak:
    # phase_offset = 0 at month 12, so phase_offset = -2pi*(12%12)/12 = 0
    # but month 0 -> cos(0)=1; month 12 -> cos(2pi)=1; so peak in Jan and Dec.
    # We want peak Dec-Jan, so use phase_offset = -pi/12 (shift by half month)
    season_phase_offset = 0.5
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
        TE_pos = np.maximum(TE, 0.0)  # warm part
        TE_neg = np.minimum(TE, 0.0)  # cold part (negative or zero)
        TC_pos = np.maximum(TC, 0.0)
        TC_neg = np.minimum(TC, 0.0)

        # Asymmetric cubic damping: stronger for cold anomalies, weaker for
        # warm. Combined with extra growth on the warm side this produces
        # the observed positive skew of TE (and negative skew of hW).
        dTE = (
            self.aE * gm * TE
            + self.cE * gm * tau
            - self.dE * hW
            + self.bE * TC
            + self.nE * TE * tau
            - self.pE_pos * TE_pos ** 3
            - self.pE_neg * TE_neg ** 3
            + self.kE * TE_pos ** 2  # El Nino: extra growth on warm side
            - self.lE * TE_neg ** 2  # La Nina: extra damping on cold side
        )

        dTC = (
            self.aC * gm * TC
            + self.cC * gm * tau
            - self.dC * hW
            + self.bC * TE
            + self.nC * TC * tau
            - self.pC_pos * TC_pos ** 3
            - self.pC_neg * TC_neg ** 3
            + self.kC * TC_pos ** 2
            - self.lC * TC_neg ** 2
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

        # Wind anomaly tau: AR(1) damping + Bjerknes feedback from SSTs
        # (warm SST -> westerly wind anomaly -> couples tau to TE/TC).
        # This is the only equation with stochastic forcing.
        dTau = -self.rTau * tau + self.bTauE * TE + self.bTauC * TC

        return np.stack([dTC, dTE, dhW, du, dTau], axis=0)

    def _diffusion(self, x: np.ndarray, t: float) -> np.ndarray:
        """Diffusion in non-dim units. Noise enters only the tau equation;
        everything else receives stochastic forcing via the wind coupling.
        A small state-dependent (multiplicative) noise is added to TE to
        generate the observed positive skew (El Nino asymmetry). An
        asymmetric noise on tau (stronger for westerlies, tau>0) creates
        positive skew in the wind itself, which feeds through Bjerknes
        feedback to give TE positive skew without biasing the mean."""
        nm = self._noise_mod(t)
        sigma = self.sigma0 * nm
        out = np.zeros_like(x)
        # Base noise on tau (constant amplitude)
        out[4] = sigma
        # Asymmetric noise on tau: extra amplitude for tau>0 (westerly bursts)
        # This creates positive skew in tau without biasing the mean.
        # tau_asym = sigmaTau_asym * max(tau, 0) * xi
        if self.sigmaTau_asym > 0:
            out[4] = sigma + self.sigmaTau_asym * np.maximum(x[4], 0.0)
        # Multiplicative noise on TE: sigma * |TE| * xi (entering TE eq)
        out[1] = self.sigmaE_mult * np.abs(x[1])
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
