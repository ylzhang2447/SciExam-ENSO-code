"""Five-variable stochastic recharge oscillator for ENSO diversity."""

from __future__ import annotations

import numpy as np


class ENSOModel:
    """Coupled stochastic model with dimensional input and output."""

    _SCALES = np.array([7.5, 7.5, 150.0, 1.5, 5.0], dtype=float)[:, None]

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
        self.asym_tc = float(params.get("asym_tc", 0.0))
        self.asym_te = float(params.get("asym_te", 0.0))
        self.cubic_tc = float(params.get("cubic_tc", 0.0))
        self.cubic_te = float(params.get("cubic_te", 0.0))
        self.var_tc = float(params.get("var_tc", 0.0))
        self.var_te = float(params.get("var_te", 0.0))

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
        tc = z[0] - self.mean[0]
        te = z[1] - self.mean[1]
        tendency[0] += self.asym_tc * (tc * tc - self.var_tc) - self.cubic_tc * tc**3
        tendency[1] += self.asym_te * (te * te - self.var_te) - self.cubic_te * te**3
        innovation = self.noise @ rng.standard_normal(state.shape)
        z_next = z + float(dt) * tendency + np.sqrt(float(dt)) * innovation
        return z_next * self._SCALES
