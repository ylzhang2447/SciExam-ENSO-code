"""Coupled five-state ENSO diffusion, in the task's prescribed internal units.

The observable state contains all prognostic information. Cached matrices depend
only on timestep and annual calendar phase; no observations are read at runtime.
"""
import numpy as np
from scipy.linalg import expm


class ENSOModel:
    def __init__(self, params):
        self.scales = np.array([7.5, 7.5, 150.0, 1.5, 5.0])[:, None]
        self.time_scale = 2.0
        self.a = np.array([[params[f'A_{i}_{j}'] for j in range(5)] for i in range(5)])
        self.ac = np.array([[params[f'C_{i}_{j}'] for j in range(5)] for i in range(5)])
        self.asin = np.array([[params[f'S_{i}_{j}'] for j in range(5)] for i in range(5)])
        self.b = np.array([[params[f'B_{i}_{j}'] for j in range(5)] for i in range(5)])
        self.season2cos = np.array([params[f'season2cos_{i}'] for i in range(2)])
        self.season2sin = np.array([params[f'season2sin_{i}'] for i in range(2)])
        self.constant = np.array([params[f'constant_{i}'] for i in range(5)])[:, None]
        self.r = np.array([params[f'r_{i}'] for i in range(2)])
        self.m2 = np.array([params[f'm2_{i}'] for i in range(2)])
        self.m3 = np.array([params[f'm3_{i}'] for i in range(2)])
        self.central_gain = float(params['central_gain'])
        self.central_c = float(params['central_C'])
        self.central_offset = float(params['central_offset'])
        self.central_mean = float(params['central_mean'])
        self.thermo_gain = float(params['thermo_gain'])
        self.thermo_e = float(params['thermo_E'])
        self.thermo_h = float(params['thermo_h'])
        self.thermo_offset = float(params['thermo_offset'])
        self.thermo_mean = float(params['thermo_mean'])
        self.recharge_q = float(params['recharge_q'])
        self.wind_q = float(params['wind_q'])
        self.wind_gate = float(params['wind_gate'])
        self.gate_width = float(params['gate_width'])
        self.gate_moment = float(params['gate_moment'])
        self.wind_asym = float(params['wind_asym'])
        self.wind_width = float(params['wind_asym_width'])
        self.wind_moment = float(params['wind_asym_moment'])
        self.noise_state = np.array([params['noise_state_C'], params['noise_state_E']])
        self.noise_cos = np.array([[params[f'noise_cos{h}_{i}'] for i in range(5)] for h in [1, 2]])
        self.noise_sin = np.array([[params[f'noise_sin{h}_{i}'] for i in range(5)] for h in [1, 2]])
        self.heat_capacity = float(params['heat_capacity'])
        self.heat_width = float(params['heat_capacity_width']) * 150.0
        self._transitions = {}

    def _nonlinear(self, x, ds, wind_heat, wind_relax):
        return _astra_nonlinear_kernel(x, ds, wind_heat, wind_relax, self.central_c, self.central_gain, self.central_mean, self.central_offset, self.constant, self.gate_moment, self.gate_width, self.m2, self.m3, self.r, self.recharge_q, self.thermo_e, self.thermo_gain, self.thermo_h, self.thermo_mean, self.thermo_offset, self.wind_asym, self.wind_gate, self.wind_moment, self.wind_q, self.wind_width)

    @staticmethod
    def _covariance_factor(q):
        # Remove roundoff-level negative eigenvalues in an integrated covariance.
        w, v = np.linalg.eigh((q + q.T) / 2)
        return (v * np.sqrt(np.maximum(w, 0.0))) @ v.T

    def _step_core(self, state, dt, t, rng):
        if dt > 0.25:
            count = int(np.ceil(dt / 0.25))
            h = dt / count
            x = state.copy()
            for k in range(count):
                x = self._step_core(x, h, t + k * h, rng)
            return x
        phase = round(float((t + dt / 2) % 12), 10)
        key = (dt, phase)
        ds = dt / self.time_scale
        if key not in self._transitions:
            angle = 2 * np.pi * phase / 12
            a = self.a + self.ac * np.cos(angle) + self.asin * np.sin(angle)
            a[np.arange(2), np.arange(2)] += self.season2cos * np.cos(2 * angle) + self.season2sin * np.sin(2 * angle)
            modulation = np.exp(self.noise_cos[0] * np.cos(angle) + self.noise_sin[0] * np.sin(angle) + self.noise_cos[1] * np.cos(2 * angle) + self.noise_sin[1] * np.sin(2 * angle))
            b = self.b * modulation[:, None]
            aug = np.zeros((10, 10))
            aug[:5, :5], aug[5:, 5:] = a, -a.T
            aug[:5, 5:] = b @ b.T
            e = expm(aug * ds)
            f = e[:5, :5]
            q = e[:5, 5:] @ f.T
            # Separate the independent wind channel before applying its activity.
            aug[:5, 5:] = np.outer(b[:, 4], b[:, 4])
            ew = expm(aug * ds)
            qw = ew[:5, 5:] @ f.T
            shared = self._covariance_factor(q - qw)
            wind = self._covariance_factor(qw)
            self._transitions[key] = f, shared, wind, float(a[1, 4]), float(a[4, 4])
        f, shared, wind, wind_heat, wind_relax = self._transitions[key]
        x = self._nonlinear(state / self.scales, ds / 2, wind_heat, wind_relax)
        activity = np.exp(np.tanh(self.noise_state @ x[:2]))
        y = f @ x + shared @ rng.normal(size=x.shape)
        y += activity * (wind @ rng.normal(size=x.shape))
        return self.scales * self._nonlinear(y, ds / 2, wind_heat, wind_relax)

    def step(self, state, dt, t, rng):
        """Advance dimensional (5,M) observables; dt and t are in months."""
        state = np.asarray(state, dtype=float)
        if state.ndim != 2 or state.shape[0] != 5:
            raise ValueError('state must have shape (5,M)')
        if not np.isfinite(dt) or dt < 0:
            raise ValueError('dt must be finite and nonnegative')
        if dt == 0:
            return state.copy()
        x = state.copy()
        eta, length = self.heat_capacity, self.heat_width
        shifted = x[2] - eta * length
        x[2] = (shifted + eta * np.sqrt(shifted * shifted + (1 - eta * eta) * length * length)) / (1 - eta * eta)
        out = self._step_core(x, dt, t, rng)
        out[2] -= eta * (np.sqrt(out[2] * out[2] + length * length) - length)
        return out

from numba import njit
@njit(cache=False, fastmath=False)
def _astra_nonlinear_kernel(x, ds, wind_heat, wind_relax, p_central_c, p_central_gain, p_central_mean, p_central_offset, p_constant, p_gate_moment, p_gate_width, p_m2, p_m3, p_r, p_recharge_q, p_thermo_e, p_thermo_gain, p_thermo_h, p_thermo_mean, p_thermo_offset, p_wind_asym, p_wind_gate, p_wind_moment, p_wind_q, p_wind_width):
    """Implicit midpoint for bounded feedbacks and the recharge tendency."""
    yc = x[0].copy()
    for _ in range(6):
        m = 0.5 * (x[0] + yc)
        response = np.tanh(p_central_offset + p_central_c * m)
        f = p_constant[0] - p_r[0] * (m**3 - p_m3[0])
        f += p_central_gain * (response - p_central_mean)
        derivative = 1 + 1.5 * ds * p_r[0] * m * m
        derivative -= 0.5 * ds * p_central_gain * p_central_c * (1 - response * response)
        yc -= (yc - x[0] - ds * f) / derivative
    mc = 0.5 * (x[0] + yc)

    wind_tendency = p_constant[4] + p_wind_q * (mc * mc - p_m2[0])
    yw = x[4] + ds * wind_tendency
    for _ in range(6):
        mw = 0.5 * (x[4] + yw)
        z = mw / p_wind_width
        logcosh = np.logaddexp(z, -z) - np.log(2.0)
        f = wind_tendency + wind_relax * p_wind_asym * p_wind_width * (logcosh - p_wind_moment)
        derivative = 1 - 0.5 * ds * wind_relax * p_wind_asym * np.tanh(z)
        yw -= (yw - x[4] - ds * f) / derivative
    wind = 0.5 * (x[4] + yw)

    gain = wind_heat * p_wind_gate
    ye = x[1].copy()
    for _ in range(6):
        m = 0.5 * (x[1] + ye)
        gate = np.tanh((m - mc) / p_gate_width)
        mh = x[2] + 0.5 * ds * (p_constant[2] + p_recharge_q * (m * m - p_m2[1]))
        therm = np.tanh(p_thermo_offset + p_thermo_e * m + p_thermo_h * mh)
        f = p_constant[1] - p_r[1] * (m**3 - p_m3[1])
        f += gain * (wind * gate - p_gate_moment)
        f += p_thermo_gain * (therm - p_thermo_mean)
        derivative = 1 + 1.5 * ds * p_r[1] * m * m
        derivative -= 0.5 * ds * gain * wind * (1 - gate * gate) / p_gate_width
        derivative -= 0.5 * ds * p_thermo_gain * (1 - therm * therm) * (p_thermo_e + p_thermo_h * ds * p_recharge_q * m)
        ye -= (ye - x[1] - ds * f) / derivative
    me = 0.5 * (x[1] + ye)
    out = x + ds * p_constant
    out[0], out[1], out[4] = yc, ye, yw
    out[2] += ds * p_recharge_q * (me * me - p_m2[1])
    return out
