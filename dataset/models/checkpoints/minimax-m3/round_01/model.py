"""Stochastic conceptual ENSO model with Central/Eastern Pacific diversity.

Five state variables (dimensional, in fixed row order):
    0: TC  central-Pacific SST anomaly          [deg C]
    1: TE  eastern-Pacific SST anomaly          [deg C]
    2: hW  western-Pacific thermocline anomaly  [m]
    3: u   central-Pacific zonal current anom   [m/s]
    4: tau WP zonal wind anomaly                [m/s]

Internal integration in NON-DIMENSIONAL units via the scales in
nondim_scales.json (TC,TE / 7.5; hW / 150; u / 1.5; tau / 5.0; time / 2 mo)
so that the O(1) state can be handled by an explicit Euler-Maruyama step.

Mechanisms (all in non-dim):
    dTC/dt =  aC * TC + bC * (TE - TC) + cC * tau - dC * hW
              + N_C(TC, season) - damp_C(TC)
    dTE/dt =  aE * TE + bE * TC          + cE * tau - dE * hW
              + N_E(TE, season) - damp_E(TE)
    dhW/dt =  -r * hW - mu_u * u + F_h(tau)
    du/dt  =  -r_u * u + alpha * tau - beta * hW
    dtau/dt =  -r_tau * tau + sigma(tau, season) * xi

The TC and TE SST ODEs have three positive growth terms (Bjerknes feedback:
growth on the same SST sign, growth on the cross-region SST and on the wind
anomaly) and one negative feedback via the heat content (recharge/discharge).
A seasonal modulation multiplies the positive-growth and noise terms to
produce boreal-winter phase locking. A quadratic nonlinearity (in the form
TC * tau and TE * tau -> wind-SST coupling has the wind anomaly enter
multiplicatively with SST) and cubic damping keep the SST anomalies bounded
and produce El Nino / La Nina asymmetry.

State is propagated with Euler-Maruyama on the non-dim equations; the
returned state is the dimensional one.
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
    """Stochastic conceptual ENSO model. All dynamics in non-dim state x with
    x = [TC, TE, hW, u, tau]_nd, time in non-dim time units (1 unit = 2 mo).
    The drift f(x, t) is a hand-built nonlinear recharge oscillator with
    seasonal modulation; the noise is a single Wiener process on tau (the
    wind anomaly), with state-dependent amplitude that is also seasonally
    modulated.
    """

    # ---- physical / damping rates (non-dim) ----
    # The SST equation has a weakly-unstable Bjerknes feedback (aC, aE),
    # cross-region SST coupling (bC, bE), wind-stress growth (cC, cE),
    # thermocline discharge damping (-dC hW, -dE hW), El-Nino asymmetric
    # coupling (nC TC*tau, nE TE*tau), and strong cubic damping that
    # keeps the SST variance at the observed O(0.1) non-dim amplitude.
    aC = 0.55      # self-growth on TC (Bjerknes, weakly unstable)
    bC = 0.10      # cross-region SST coupling from TE
    cC = 1.30      # wind-stress growth on TC
    dC = 1.80      # thermocline discharge damping on TC
    nC = 0.40      # nonlinearity TC*tau (El Nino asymmetry)
    pC = 80.0      # cubic damping on TC (sets SST variance amplitude)
    # TE equation
    aE = 0.80      # self-growth on TE (stronger than TC, EP dominance)
    bE = 0.05      # cross-region SST coupling from TC (small)
    cE = 1.50      # wind-stress growth on TE
    dE = 0.80      # thermocline damping on TE
    nE = 0.60      # TE*tau nonlinearity (El Nino asymmetry, stronger)
    pE = 100.0     # cubic damping on TE
    # hW equation
    rH = 2.00      # restoring of thermocline (mean-reverting to zero)
    muU = 0.80     # u-forcing of thermocline
    alphaH = 0.40  # wind-stress forcing of thermocline tilt
    # u equation
    rU = 5.00      # damping of zonal current (faster than hW)
    alphaU = 0.60  # wind forcing of u
    betaU = 1.50   # pressure-gradient forcing of u (hW opposes tau)
    # tau equation
    rTau = 1.00    # wind damping (memory ~ 1 nondim time = 2 mo)
    sigma0 = 0.55  # base noise amplitude on tau
    sigmaS = 0.30  # seasonal modulation amplitude on noise
    # Seasonal modulation: annual cycle (peak in boreal winter, ~Dec)
    # annual_phase in radians, 0 = Jan 1.
    annual_phase = 0.0
    # SST growth-rate modulation: stronger positive growth in winter.
    season_growth_amp = 0.35

    # ---- clamp range ----
    # Hard guard so that a runaway simulation cannot produce NaN/inf in the
    # returned state. If the non-dim state exceeds this we soft-clip; the
    # stochastic step then has a chance to recover.
    _X_CLIP = 6.0

    def __init__(self, params: dict):
        """`params` is the parsed params.json; it may override the class
        attributes above for re-calibration without editing this file."""
        for k, v in (params or {}).items():
            if not hasattr(self, k):
                # ignore unknown keys silently -- this lets future param
                # additions pass through without breaking old params.json.
                continue
            setattr(self, k, v)

    # ---- helpers ----

    @staticmethod
    def _season(t: float) -> float:
        """Return the seasonal modulation factor at non-dim time t (one unit
        = T_SCALE months = 2 months). The growth is amplified in boreal
        winter (Dec-Feb) and reduced in boreal spring.
        """
        # t is in non-dim time; convert to months first
        m = (t * _T_SCALE) % 12.0  # month index 0..12 within the year
        # peak at month 12 (December, with month 12 = month 0 of next year in
        # modular arithmetic); use cos with phase pi (December) - pi/6 to
        # widen the boreal-winter window (Nov-Jan).
        return float(np.cos(2.0 * np.pi * (m / 12.0) - 11.0 * np.pi / 6.0))

    def _growth_mod(self, t: float) -> float:
        """Growth-rate modulation: 1 + amp * season(t). Bounded below at 0.3
        so growth never reverses sign."""
        return max(0.3, 1.0 + self.season_growth_amp * self._season(t))

    def _noise_mod(self, t: float) -> float:
        """Noise amplitude modulation: 1 + amp * season(t). Bounded below at
        0.5 so wind noise never fully vanishes."""
        return max(0.5, 1.0 + self.sigmaS * self._season(t))

    # ---- the actual stochastic step ----

    def _drift(self, x: np.ndarray, t: float) -> np.ndarray:
        """Deterministic drift in non-dim units. x has shape (5, M)."""
        TC, TE, hW, u, tau = x[0], x[1], x[2], x[3], x[4]
        gm = self._growth_mod(t)

        # Eastern-Pacific SST (TE): self-growth, wind-growth, hW discharge,
        # TC coupling, TE*tau nonlinearity (El Nino asymmetry: warm SST
        # combined with westerly wind anomaly amplifies), cubic damping.
        dTE = (
            self.aE * gm * TE
            + self.cE * gm * tau
            - self.dE * hW
            + self.bE * TC
            + self.nE * TE * tau
            - self.pE * TE ** 3
        )

        # Central-Pacific SST (TC): self-growth, wind-growth, hW discharge,
        # TE coupling, TC*tau nonlinearity, cubic damping. dC > dE because
        # the central Pacific sees the western thermocline tilt more
        # directly.
        dTC = (
            self.aC * gm * TC
            + self.cC * gm * tau
            - self.dC * hW
            + self.bC * TE
            + self.nC * TC * tau
            - self.pC * TC ** 3
        )

        # Western thermocline: restoring + zonal-current forcing + wind
        # tilt (westerlies deepen hW). The sign on muU is positive so a
        # positive (eastward) current anomaly deepens the western
        # thermocline.
        dhW = (
            -self.rH * hW
            + self.muU * u
            + self.alphaH * tau
        )

        # Zonal current u: wind-stress forcing, pressure-gradient damping
        # from hW (negative hW -> eastward u), damping.
        du = (
            -self.rU * u
            + self.alphaU * tau
            - self.betaU * hW
        )

        # Wind anomaly tau: AR(1) damping (mean-reverting noise) -- this is
        # the only stochastic term in the system. The drift on tau is just
        # -rTau * tau (mean-reversion toward zero).
        dTau = -self.rTau * tau

        return np.stack([dTC, dTE, dhW, du, dTau], axis=0)

    def _diffusion(self, x: np.ndarray, t: float) -> np.ndarray:
        """Diffusion (state- and season-dependent) in non-dim units.
        Noise is applied to the tau equation only; all other variables
        receive their stochastic forcing through the tau -> SST, hW, u
        coupling. Returns a (5, M) array of noise multipliers (multiplied
        by sqrt(dt_nd) and a standard normal draw in step()).
        """
        nm = self._noise_mod(t)
        sigma = self.sigma0 * nm
        # noise enters only the tau equation (a Wiener forcing of the wind)
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
        # Convert to non-dim for the integrator
        x = _to_nondim(state)  # (5, M)

        # Convert dt (months) -> dt (non-dim time units)
        dt_nd = dt * _TIME_RATE  # e.g. dt=0.1 months => dt_nd = 0.05

        # Euler-Maruyama. Drift uses state at start of step; noise uses
        # normal draws from rng.
        drift = self._drift(x, t * _TIME_RATE)
        diff = self._diffusion(x, t * _TIME_RATE)
        # Wiener increment: dW ~ N(0, dt_nd) per integration dimension
        dW = rng.standard_normal(size=x.shape) * np.sqrt(dt_nd)
        x_new = x + drift * dt_nd + diff * dW

        # Soft-clip to keep things bounded against any blow-up (the cubic
        # damping already provides saturation, but this is a safety net so
        # the hard gate on finiteness never trips).
        np.clip(x_new, -self._X_CLIP, self._X_CLIP, out=x_new)

        return _to_dim(x_new)
