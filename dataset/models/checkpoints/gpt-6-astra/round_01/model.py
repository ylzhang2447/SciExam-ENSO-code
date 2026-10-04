"""Uncalibrated independent OU baseline for exercising Phase-2A instruments.

Replace during modeling. This is a runnable stochastic baseline, not a fitted
ENSO model and not a representation of recharge or ENSO diversity mechanisms.
"""
import numpy as np


class ENSOModel:
    def __init__(self, params):
        self.scales = np.array([7.5, 7.5, 150., 1.5, 5.])[:, None]
        self.sd = np.array([params[name + '_sd'] for name in
                            ['TC', 'TE', 'hW', 'u', 'tau']])[:, None] / self.scales
        self.relaxation_months = float(params['relaxation_months'])
        if self.relaxation_months <= 0 or np.any(self.sd <= 0):
            raise ValueError('OU relaxation time and stationary SDs must be positive')

    def step(self, state, dt, t, rng):
        state = np.asarray(state, dtype=float)
        if state.ndim != 2 or state.shape[0] != 5:
            raise ValueError('state must have shape (5, M)')
        if not np.isfinite(dt) or dt < 0:
            raise ValueError('dt must be finite and nonnegative')
        # Exact transition of dx = -x/L dt + sd*sqrt(2/L) dW, in months.
        decay = np.exp(-dt / self.relaxation_months)
        noise_sd = np.sqrt(-np.expm1(-2 * dt / self.relaxation_months))
        x = state / self.scales
        return self.scales * (decay * x + self.sd * noise_sd * rng.normal(size=x.shape))
