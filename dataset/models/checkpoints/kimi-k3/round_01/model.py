"""PLACEHOLDER model: a linear OU process fitted to the observed covariance at
lag 0 and lag 1 (Yule-Walker). Used only to exercise the diagnostics before
the real model is built."""
import numpy as np


class ENSOModel:
    def __init__(self, params):
        self.vars = ['TC', 'TE', 'hW', 'u', 'tau']
        self.A = np.array(params['A'])          # (5,5) drift matrix (monthly)
        self.L = np.array(params['chol'])       # (5,5) noise chol (monthly)
        self.seas_amp = np.array(params.get('seas_amp', [0]*5))
        self.seas_phi = np.array(params.get('seas_phi', [0]*5))

    def step(self, state, dt, t, rng):
        # drift: dx = A x dt + L sqrt(dt) dW, A in 1/month units
        drift = self.A @ state * dt
        noise = (self.L @ rng.standard_normal(state.shape)) * np.sqrt(dt)
        out = state + drift + noise
        return out
