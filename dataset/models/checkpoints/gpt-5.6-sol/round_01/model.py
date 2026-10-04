"""Uncalibrated Phase-2A baseline used to exercise the diagnostic instruments."""

import numpy as np


class ENSOModel:
    """Independent damped stochastic anomalies; intentionally has no ENSO coupling."""

    def __init__(self, params: dict):
        self.damping = np.array([
            params["damping_TC"], params["damping_TE"], params["damping_hW"],
            params["damping_u"], params["damping_tau"],
        ], dtype=float)[:, None]
        self.noise = np.array([
            params["noise_TC"], params["noise_TE"], params["noise_hW"],
            params["noise_u"], params["noise_tau"],
        ], dtype=float)[:, None]

    def step(self, state, dt, t, rng):
        """Euler--Maruyama step in the required dimensional units."""
        x = np.asarray(state, dtype=float)
        innovation = rng.standard_normal(x.shape)
        return x - dt * self.damping * x + np.sqrt(dt) * self.noise * innovation
