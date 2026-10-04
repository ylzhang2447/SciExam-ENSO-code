"""Stochastic, seasonal, nonlinear two-region recharge oscillator for ENSO diversity.
State (dimensional): TC, TE [degC], hW [m], u, tau [m/s]. Internally non-dimensional
(nondim_scales.json): T/7.5, h/150, u/1.5, tau/5, time/2 months.

Non-dim drift (rates per non-dim time unit), x = (TC, TE, hW, u, tau):
  dx/dt = A x  +  seasonal & nonlinear corrections on TC and TE:
    TC: + (g_TC_c cos + g_TC_s sin + g_TC_c2 cos2 + g_TC_s2 sin2) TC + (b_TC_c cos + b_TC_s sin) hW + q_TC (1 + q_TC_s sin) TC^2 + n_TC TC^3 + qw_TC TC^2 H(TC) + c_TC  (c_TC: constant offset balancing q_TC so the mean stays ~0; H: warm-side-only extra damping, SST convective saturation)
    TE: + (g_TE_c cos + g_TE_s sin + g_TE_c2 cos2 + g_TE_s2 sin2) TE  (annual + semi-annual growth-rate cycle) + (b_TE_c cos + b_TE_s sin) hW + q_TE (1 + q_TE_s sin) TE^2/(1+(TE/sat_TE)^2) + n_TE TE^3 + n5_TE TE^5  (saturating warm-side growth, seasonally modulated: q_TE_s<0 strengthens it in boreal autumn)
  cos/sin of 2*pi*(t-0.5)/12, t in months from 1 Jan.
A encodes: Bjerknes/thermocline feedback (hW -> TE, TC), zonal advective feedback (u -> TC),
recharge/discharge (TC, TE, tau -> hW), wind-driven current (tau, hW -> u), and wind stress
response to SST (TC, TE -> tau).
    u:  + A_u_hW (bu_c cos + bu_s sin) hW  (seasonally modulated thermocline->current coupling)
    hW: + (g_hW_c cos + g_hW_s sin) hW + q_hW TE^2/(1+(TE/sat_hW)^2) + n_hW hW^3  (seasonal damping; saturating nonlinear discharge: strong events of either sign drain the western thermocline)
Noise: additive white noise on all variables, each with seasonal amplitude (1 + s_v_c cos + s_v_s sin + s_v_c2 cos2 + s_v_s2 sin2);
  TC, TE noise multiplicative s_v*max(1+m_v*v,0.2) (factors capped at mcap_TC / mcap_TE / mcap_tau); tau noise multiplicative s_tau*max(1+m_tau*TC,0.2)
  (stronger westerly bursts when the central Pacific is warm -> El Nino/La Nina asymmetry).
Euler-Maruyama in step with a wide safety clip (never active in the normal range); dt > 0.5 month is
split into equal sub-steps of <= 0.5 month so the scheme stays well-behaved at coarse dt.
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
        self.sc = np.array([p.get(f's_{v}_c', 0.0) for v in V])   # seasonal noise modulation (cos)
        self.ss = np.array([p.get(f's_{v}_s', 0.0) for v in V])   # seasonal noise modulation (sin)
        self.sc2 = np.array([p.get(f's_{v}_c2', 0.0) for v in V])  # semi-annual noise modulation
        self.ss2 = np.array([p.get(f's_{v}_s2', 0.0) for v in V])

    def drift(self, x, t):
        p = self.p
        TC, TE, hW = x[0], x[1], x[2]
        c = np.cos(W * (t - 0.5)); s = np.sin(W * (t - 0.5))
        c2 = np.cos(2 * W * (t - 0.5)); s2 = np.sin(2 * W * (t - 0.5))
        d = self.A @ x
        d[0] += ((p['g_TC_c'] * c + p['g_TC_s'] * s + p.get('g_TC_c2', 0.0) * c2 + p.get('g_TC_s2', 0.0) * s2) * TC + (p['b_TC_c'] * c + p['b_TC_s'] * s) * hW
                 + p['q_TC'] * (1.0 + p.get('q_TC_s', 0.0) * s) * TC ** 2 + p['n_TC'] * TC ** 3 + p['qw_TC'] * TC ** 2 * (TC > 0) + p.get('c_TC', 0.0))
        d[1] += ((p['g_TE_c'] * c + p['g_TE_s'] * s + p['g_TE_c2'] * c2 + p['g_TE_s2'] * s2) * TE + (p['b_TE_c'] * c + p['b_TE_s'] * s) * hW
                 + p['q_TE'] * (1.0 + p.get('q_TE_s', 0.0) * s) * TE ** 2 / (1.0 + (TE / p['sat_TE']) ** 2) + p['n_TE'] * TE ** 3 + p.get('n5_TE', 0.0) * TE ** 5 + p.get('c_TE', 0.0))
        d[3] += p['A_u_hW'] * (p.get('bu_c', 0.0) * c + p.get('bu_s', 0.0) * s) * hW   # seasonal modulation of the thermocline->current (geostrophic) coupling
        d[2] += p.get('c_hW', 0.0) + (p['g_hW_c'] * c + p['g_hW_s'] * s) * hW + p['q_hW'] * TE ** 2 / (1.0 + (TE / p['sat_hW']) ** 2) + p['n_hW'] * hW ** 3
        return d

    def step(self, state, dt, t, rng):
        state = np.asarray(state, float)
        if state.ndim == 1:                       # tolerate a single (5,) state; return the same shape
            return self.step(state[:, None], dt, t, rng)[:, 0]
        # sub-step when dt is coarse (> 0.5 month) so the Euler map cannot overshoot into the clip
        n = int(np.ceil(dt / 0.5)) if dt > 0.5 else 1
        if n > 1:
            for k in range(n):
                state = self._substep(state, dt / n, t + k * dt / n, rng)
            return state
        return self._substep(state, dt, t, rng)

    def _substep(self, state, dt, t, rng):
        p = self.p
        x = np.asarray(state, float) / SCALES[:, None]
        h = dt / T_SCALE
        c = np.cos(W * (t - 0.5)); s = np.sin(W * (t - 0.5))
        c2 = np.cos(2 * W * (t - 0.5)); s2 = np.sin(2 * W * (t - 0.5))
        seas = 1.0 + self.sc * c + self.ss * s + self.sc2 * c2 + self.ss2 * s2   # seasonal noise amplitude per variable
        sig = np.repeat((self.sig * seas)[:, None], x.shape[1], axis=1)
        sig[0] = sig[0] * np.minimum(np.maximum(1.0 + p['m_TC'] * x[0], 0.2), p.get('mcap_TC', 1e9))
        sig[1] = sig[1] * np.minimum(np.maximum(1.0 + p['m_TE'] * x[1], 0.2), p.get('mcap_TE', 1e9))
        sig[4] = sig[4] * np.minimum(np.maximum(1.0 + p['m_tau'] * x[0], 0.2), p.get('mcap_tau', 1e9))
        sig[1] = sig[1] * np.maximum(1.0 + p.get('mh_TE', 0.0) * x[2], 0.2)   # optional hW-dependent TE noise (recharged state -> stronger forcing)
        sig[4] = sig[4] * np.maximum(1.0 + p.get('mh_tau', 0.0) * x[2], 0.2)
        noise = sig * np.sqrt(h) * rng.standard_normal(x.shape)
        x = x + self.drift(x, t) * h + noise
        x = np.clip(x, -3.0, 3.0)
        return x * SCALES[:, None]
