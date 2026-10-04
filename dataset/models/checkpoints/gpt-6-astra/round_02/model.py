"""Coupled stochastic ENSO model; dimensional observable state at the interface."""
import numpy as np
from scipy.linalg import expm


class ENSOModel:
    def __init__(self, params):
        self.scales = np.array([7.5, 7.5, 150., 1.5, 5.])[:, None]
        self.time_scale = float(params.get('time_scale_months', 2.))
        self.a = np.array([[params[f'A_{i}_{j}'] for j in range(5)] for i in range(5)])
        self.b = np.array([[params[f'B_{i}_{j}'] for j in range(5)] for i in range(5)])
        self.ac = np.array([[params.get(f'C_{i}_{j}', 0.) for j in range(5)] for i in range(5)])
        self.asin = np.array([[params.get(f'S_{i}_{j}', 0.) for j in range(5)] for i in range(5)])
        self._transitions = {}

    def step(self, state, dt, t, rng):
        state = np.asarray(state, dtype=float)
        if state.ndim != 2 or state.shape[0] != 5:
            raise ValueError('state must have shape (5, M)')
        if not np.isfinite(dt) or dt < 0:
            raise ValueError('dt must be finite and nonnegative')
        if dt == 0:
            return state.copy()
        phase = round(float((t + dt/2) % 12), 10)
        key = (dt, phase)
        if key not in self._transitions:
            ds = dt/self.time_scale
            angle = 2*np.pi*phase/12
            a = self.a + self.ac*np.cos(angle) + self.asin*np.sin(angle)
            # Van Loan exponential gives the exact finite-time noise covariance.
            aug = np.zeros((10,10))
            aug[:5,:5] = a
            aug[:5,5:] = self.b @ self.b.T
            aug[5:,5:] = -a.T
            e = expm(aug*ds)
            f = e[:5,:5]
            q = e[:5,5:] @ f.T
            w,v = np.linalg.eigh((q+q.T)/2)
            noise = v @ np.diag(np.sqrt(np.maximum(w,0.)))
            self._transitions[key] = f,noise
        f,noise = self._transitions[key]
        x = state/self.scales
        return self.scales*(f@x + noise@rng.normal(size=x.shape))
