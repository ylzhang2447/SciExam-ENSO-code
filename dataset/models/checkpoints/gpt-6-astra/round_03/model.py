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
        self.constant = np.array([params.get(f'constant_{i}', 0.) for i in range(5)])[:, None]
        self.q = np.array([params.get(f'q_{i}', 0.) for i in range(2)])[:, None]
        self.r = np.array([params.get(f'r_{i}', 0.) for i in range(2)])[:, None]
        self.m2 = np.array([params.get(f'm2_{i}', 0.) for i in range(2)])[:, None]
        self.m3 = np.array([params.get(f'm3_{i}', 0.) for i in range(2)])[:, None]
        self.wind_q = float(params.get('wind_q', 0.))
        self._transitions = {}

    def _nonlinear(self, x, ds):
        # Implicit midpoint for the saturated local SST feedback. The cubic
        # derivative bounds the positive quadratic feedback at large amplitude.
        old = x[:2]
        y = old.copy()
        for _ in range(6):
            mid = (old+y)*.5
            tendency = self.constant[:2] + self.q*(mid*mid-self.m2) - self.r*(mid**3-self.m3)
            residual = y-old-ds*tendency
            derivative = 1-ds*(self.q*mid-1.5*self.r*mid*mid)
            y = y-residual/derivative
        out = x + ds*self.constant
        out[:2] = y
        mid_c = (old[0]+y[0])*.5
        out[4] += ds*self.wind_q*(mid_c*mid_c-self.m2[0])
        return out

    def step(self, state, dt, t, rng):
        state = np.asarray(state, dtype=float)
        if state.ndim != 2 or state.shape[0] != 5:
            raise ValueError('state must have shape (5, M)')
        if not np.isfinite(dt) or dt < 0:
            raise ValueError('dt must be finite and nonnegative')
        if dt == 0:
            return state.copy()
        if dt > .25:
            count = int(np.ceil(dt/.25))
            h = dt/count
            x = state.copy()
            for k in range(count):
                x = self.step(x,h,t+k*h,rng)
            return x
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
        x = self._nonlinear(state/self.scales,dt/self.time_scale/2)
        x = f@x + noise@rng.normal(size=x.shape)
        return self.scales*self._nonlinear(x,dt/self.time_scale/2)
