"""Two-region stochastic recharge oscillator for ENSO diversity (TC, TE, hW, u, tau).

Internally non-dimensional (nondim_scales.json: T/7.5 C, h/150 m, u/1.5 m/s, tau/5 m/s,
time/2 months); the state passed in and out of `step` is dimensional.  Integration is
Euler-Maruyama with internal sub-steps so that results are insensitive to the caller's dt.
t is months since the run start, with t = 0 taken as 1 January (calendar month = t mod 12).
"""
import numpy as np

SCALE = np.array([7.5, 7.5, 150.0, 1.5, 5.0])[:, None]
T_SCALE = 2.0          # months per non-dimensional time unit
MAX_SUBSTEP = 0.1      # months
CLIP = 4.0             # non-dimensional safety bound (far outside the observed range)


class ENSOModel:
    def __init__(self, params):
        self.p = dict(params)

    # ---- deterministic tendency (non-dimensional) -----------------------------------
    def drift(self, x, t):
        p = self.p
        TC, TE, hW, u, tau = x
        ph = 2.0 * np.pi * (t % 12.0) / 12.0
        # seasonal growth-rate modulation; phase_* is the calendar month (0 = Jan) of maximum growth
        sC = np.cos(ph - 2.0 * np.pi * p['phase_C'] / 12.0)
        sE = np.cos(ph - 2.0 * np.pi * p['phase_E'] / 12.0)
        RC = p['R_C0'] + p['R_C1'] * sC
        RE = p['R_E0'] + p['R_E1'] * sE
        # TC: bilinear -q_CE*TC*TE limits warm CP anomalies during EP events and deepens
        # cold ones (negative TC skew); TE: quadratic warm-favouring term (positive TE skew)
        # x_CEm: extra coupling from cold eastern anomalies only (cold tongue -> central Pacific),
        # so La Nina cools both regions while warm EP events stay confined to the east
        dTC = (RC * TC + p['x_CE'] * TE + p.get('x_CEm', 0.0) * np.minimum(TE, 0.0)
               + p['g_C'] * hW + p['b_C'] * u + p['e_C'] * tau
               - p['q_CE'] * TC * TE - p['c_C'] * TC ** 3 + p['f_C'])
        # thermocline feedback on TE is stronger when the warm pool is recharged (hW > 0)
        dTE = (RE * TE + p['x_EC'] * TC + p['g_E'] * hW * (1.0 + p['gam_h'] * hW) + p['b_E'] * u + p['e_E'] * tau
               + p['q_E'] * TE * TE - p['c_E'] * TE ** 3 + p['f_E'])
        # discharge efficiency (Sverdrup transport response to wind) varies seasonally
        sA = 1.0 + p['a_seas'] * np.cos(ph - 2.0 * np.pi * p['phase_a'] / 12.0)
        # asymmetric discharge: warm events discharge more than cold events recharge
        # (a_q TE^2, mean effect cancelled by the offset f_h) -> cold phases last longer
        dh = (-p['r_h'] * hW - sA * (p['a_C'] * TC + p['a_E'] * TE + p['a_q'] * TE * TE
                                     + p['a_u'] * u + p['a_tau'] * tau) + p['f_h'])
        du = -p['r_u'] * u + p['u_h'] * hW + p['u_tau'] * tau - p['u_C'] * TC
        dtau = -p['r_tau'] * (tau - p['k_C'] * TC - p['k_E'] * TE - p['k_h'] * hW - p['k_u'] * u)
        return np.array([dTC, dTE, dh, du, dtau])

    # ---- stochastic amplitudes (non-dimensional, per sqrt(time unit)) -----------------
    def noise_amp(self, x, t):
        p = self.p
        TC = x[0]
        ph = 2.0 * np.pi * (t % 12.0) / 12.0
        seas = 1.0 + p['sig_tau_seas'] * np.cos(ph - 2.0 * np.pi * p['phase_sig'] / 12.0)
        # multiplicative (state-dependent) wind noise: stronger during warm central Pacific
        mult = 1.0 + p['mult'] * np.tanh(TC / 0.1)
        sig = np.empty_like(x)
        sig[0] = p['sig_C']
        sig[1] = p['sig_E']
        sig[2] = p['sig_h']
        sig[3] = p['sig_u'] * (1.0 + p['sig_u_seas'] * np.cos(ph - 2.0 * np.pi * p['phase_su'] / 12.0))
        sig[4] = p['sig_tau'] * seas * mult
        return sig

    def step(self, state, dt, t, rng):
        x = np.array(state, dtype=float) / SCALE
        nsub = max(1, int(np.ceil(dt / MAX_SUBSTEP - 1e-9)))
        h = dt / nsub                 # months
        hn = h / T_SCALE              # non-dimensional
        sq = np.sqrt(hn)
        tt = float(t)
        for _ in range(nsub):
            f = self.drift(x, tt)
            s = self.noise_amp(x, tt)
            w = rng.standard_normal(x.shape)
            # shared component of the SST noise (unresolved processes warming both regions)
            rho = self.p['rho_T']
            w[1] = rho * w[0] + np.sqrt(max(0.0, 1.0 - rho * rho)) * w[1]
            x = x + f * hn + s * sq * w
            x = np.clip(x, -CLIP, CLIP)
            tt += h
        return x * SCALE
