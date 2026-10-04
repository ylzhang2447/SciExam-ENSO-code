"""PLACEHOLDER linear stochastic recharge oscillator (Phase 2A stand-in to exercise the
diagnostics). Will be replaced by the calibrated nonlinear seasonal model in Phase 2B.
State (dimensional): TC, TE [degC], hW [m], u, tau [m/s]. Internally non-dimensional."""
import numpy as np

SCALES = np.array([7.5, 7.5, 150.0, 1.5, 5.0])   # T, T, h, u, tau
T_SCALE = 2.0                                      # months per non-dim time unit


class ENSOModel:
    def __init__(self, params):
        self.p = dict(params)
        p = self.p
        # linear drift matrix in non-dim units (rows: TC, TE, hW, u, tau)
        self.A = np.array([
            [-p['dC'], p['cCE'], p['bC'], p['uC'], 0.0],
            [0.0, -p['dE'], p['bE'], 0.0, 0.0],
            [-p['aC'], -p['aE'], -p['dh'], 0.0, 0.0],
            [0.0, 0.0, 0.0, -p['du'], p['tu']],
            [p['cT'], 0.0, 0.0, 0.0, -p['dtau']],
        ])
        self.sig = np.array([p['sC'], p['sE'], p['sh'], p['su'], p['stau']])

    def step(self, state, dt, t, rng):
        x = np.asarray(state, float) / SCALES[:, None]
        h = dt / T_SCALE
        drift = self.A @ x
        noise = self.sig[:, None] * np.sqrt(h) * rng.standard_normal(x.shape)
        x = x + drift * h + noise
        return x * SCALES[:, None]
