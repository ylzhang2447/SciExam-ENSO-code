"""Five-variable stochastic recharge oscillator for ENSO diversity."""

from __future__ import annotations

import numpy as np


class ENSOModel:
    """Coupled stochastic model with dimensional input and output."""

    _SCALES = np.array([7.5, 7.5, 150.0, 1.5, 5.0], dtype=float)[:, None]
    _TIME_SCALE = 2.0

    def __init__(self, params: dict):
        self.mean = np.array([params[f"mean_{j}"] for j in range(5)], dtype=float)[:, None]
        self.drift = np.array(
            [[params[f"drift_{i}_{j}"] for j in range(5)] for i in range(5)],
            dtype=float,
        )
        self.noise = np.array(
            [[params[f"noise_{i}_{j}"] for j in range(5)] for i in range(5)],
            dtype=float,
        )
        self.season_amp = float(params.get("season_amp", 0.0))
        self.season_peak_month = float(params.get("season_peak_month", 0.0))
        self.te_season_tc = float(params.get("te_season_tc", 0.0))
        self.te_season_phase = float(params.get("te_season_phase", 0.0))
        self.asym_tc = float(params.get("asym_tc", 0.0))
        self.asym_te = float(params.get("asym_te", 0.0))
        self.cp_to_te = float(params.get("cp_to_te", 0.0))
        self.cubic_tc = float(params.get("cubic_tc", 0.0))
        self.cubic_te = float(params.get("cubic_te", 0.0))
        self.cubic_other = np.array(
            [params.get(f"cubic_{j}", 0.0) for j in range(2, 5)], dtype=float
        )[:, None]
        self.var_tc = float(params.get("var_tc", 0.0))
        self.var_te = float(params.get("var_te", 0.0))
        self.nonlinear_scale = float(params.get("nonlinear_scale", 0.5))
        self.noise_skew = np.array(
            [params.get(f"noise_skew_{j}", 0.0) for j in range(5)], dtype=float
        )[:, None]
        self.burst_prob = np.array(
            [params.get(f"burst_prob_{j}", 0.0) for j in range(5)], dtype=float
        )[:, None]
        self.burst_sign = np.array(
            [params.get(f"burst_sign_{j}", 1.0) for j in range(5)], dtype=float
        )[:, None]

    def step(self, state, dt, t, rng):
        """Advance one Euler--Maruyama step; ``dt`` and ``t`` are in months."""
        state = np.asarray(state, dtype=float)
        if state.ndim != 2 or state.shape[0] != 5:
            raise ValueError("state must have shape (5, M)")
        z = state / self._SCALES
        tendency = self.drift @ (z - self.mean)
        # Seasonal modulation of the rapid atmospheric response to central SST.
        phase = 2.0 * np.pi * (float(t) - self.season_peak_month) / 12.0
        tendency[4] += (self.season_amp * np.cos(phase) * self.drift[4, 0]
                        * (z[0] - self.mean[0]))
        tendency[1] += self.te_season_tc * np.cos(
            2.0 * np.pi * (float(t) - self.te_season_phase) / 12.0
        ) * (z[0] - self.mean[0])
        tc = z[0] - self.mean[0]
        te = z[1] - self.mean[1]
        def limited_cubic(value):
            return value**3 / (1.0 + (value / self.nonlinear_scale) ** 2)

        tendency[0] -= (self.cubic_tc * limited_cubic(tc)
                        + self.asym_tc * limited_cubic(np.maximum(tc, 0.0)))
        tendency[1] -= (self.cubic_te * limited_cubic(te)
                        + self.asym_te * limited_cubic(np.minimum(te, 0.0)))
        tc_warm = np.maximum(tc, 0.0)
        tendency[1] += self.cp_to_te * tc_warm**2 / (
            1.0 + (tc_warm / self.nonlinear_scale) ** 2
        )
        other = z[2:5] - self.mean[2:5]
        tendency[2:5] -= self.cubic_other * limited_cubic(other)
        white = rng.standard_normal(state.shape)
        # A centered quadratic normal transform permits asymmetric weather bursts
        # while retaining unit variance and independent driving components.
        white = (white + self.noise_skew * (white * white - 1.0)) / np.sqrt(
            1.0 + 2.0 * self.noise_skew * self.noise_skew
        )
        active = self.burst_prob > 0.0
        if np.any(active):
            uniform = rng.random(state.shape)
            # ``burst_prob`` is a Poisson-like rate per physical month. Scaling
            # its Bernoulli probability with dt keeps burst frequency consistent.
            p = np.where(
                active,
                np.clip(self.burst_prob * float(dt), 1.0e-8, 0.25),
                0.5,
            )
            burst = self.burst_sign * ((uniform < p) - p) / np.sqrt(p * (1.0 - p))
            white = np.where(active, burst, white)
        innovation = self.noise @ white
        # Integrate in the supplied nondimensional time s=t/(2 months).
        ds = float(dt) / self._TIME_SCALE
        z_next = (z + ds * (self._TIME_SCALE * tendency)
                  + np.sqrt(ds) * (np.sqrt(self._TIME_SCALE) * innovation))
        return z_next * self._SCALES
