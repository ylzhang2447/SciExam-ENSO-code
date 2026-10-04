"""Stochastic, seasonal, nonlinear two-region recharge oscillator for ENSO diversity.
State (dimensional): TC, TE [degC], hW [m], u, tau [m/s]. Internally non-dimensional
(nondim_scales.json): T/7.5, h/150, u/1.5, tau/5, time/2 months.

Non-dim drift (rates per non-dim time unit), x = (TC, TE, hW, u, tau):
  dx/dt = A x  +  seasonal & nonlinear corrections on TC and TE:
    TC: + (g_TC_c cos + g_TC_s sin) TC + (b_TC_c cos + b_TC_s sin) hW + q_TC TC^2 - n_TC TC^3
    TE: + (g_TE_c cos + g_TE_s sin) TE + (b_TE_c cos + b_TE_s sin) hW + q_TE TE^2 - n_TE TE^3
  cos/sin of 2*pi*(t-0.5)/12, t in months from 1 Jan.
A encodes: Bjerknes/thermocline feedback (hW -> TE, TC), zonal advective feedback (u -> TC),
recharge/discharge (TC, TE, tau -> hW), wind-driven current (tau, hW -> u), and wind stress
response to SST (TC, TE -> tau).
Noise: additive white noise on all variables; tau noise is multiplicative,
  s_tau * max(1 + m_tau*TC, 0.2) * (1 + s_tau_c cos + s_tau_s sin)  (stronger westerly bursts
when the central Pacific is warm -> El Nino/La Nina asymmetry, seasonal wind variance).
Euler-Maruyama in step with a wide safety clip (never active in the normal range).
"""
import numpy as np

SCALES = np.array([7.5, 7.5, 150.0, 1.5, 5.0])
T_SCALE = 2.0
W = 2.0 * np.pi / 12.0
V = ['TC', 'TE', 'hW', 'u', 'tau']


class ENSOModel:
    def __init__(self, params):
        p = {k: float(v) for k, v in params.items() if not k.startswith('_')}
        self.p = p
        self.A = np.array([[p[f'A_{a}_{b}'] for b in V] for a in V])
        self.sig = np.array([p[f's_{v}'] for v in V])

    def drift(self, x, t):
        p = self.p
        TC, TE, hW = x[0], x[1], x[2]
        c = np.cos(W * (t - 0.5)); s = np.sin(W * (t - 0.5))
        d = self.A @ x
        d[0] += ((p['g_TC_c'] * c + p['g_TC_s'] * s) * TC + (p['b_TC_c'] * c + p['b_TC_s'] * s) * hW
                 + p['q_TC'] * TC ** 2 + p['n_TC'] * TC ** 3)
        d[1] += ((p['g_TE_c'] * c + p['g_TE_s'] * s) * TE + (p['b_TE_c'] * c + p['b_TE_s'] * s) * hW
                 + p['q_TE'] * TE ** 2 + p['n_TE'] * TE ** 3)
        return d

    def step(self, state, dt, t, rng):
        p = self.p
        x = np.asarray(state, float) / SCALES[:, None]
        h = dt / T_SCALE
        c = np.cos(W * (t - 0.5)); s = np.sin(W * (t - 0.5))
        sig = np.repeat(self.sig[:, None], x.shape[1], axis=1)
        sig[4] = sig[4] * np.maximum(1.0 + p['m_tau'] * x[0], 0.2) * (1.0 + p['s_tau_c'] * c + p['s_tau_s'] * s)
        noise = sig * np.sqrt(h) * rng.standard_normal(x.shape)
        x = x + self.drift(x, t) * h + noise
        x = np.clip(x, -3.0, 3.0)
        return x * SCALES[:, None]
