"""Stochastic conceptual model of ENSO diversity: a two-region (Central/Eastern Pacific)
recharge oscillator with zonal-current (u) and wind (tau) state variables.

State (dimensional, rows): TC [degC], TE [degC], hW [m], u [m/s], tau [m/s].
Internally non-dimensionalised with nondim_scales.json (T/7.5, h/150, u/1.5, tau/5,
time/2 months). Time t is months since run start with t=0 = January.

Non-dimensional equations (x = (tc, te, h, u, ta)):
  dtc/dt = [A_tc_tc(1+s_tc(t))] tc + A_tc_te te + A_tc_h h + A_tc_u u + A_tc_ta ta
           + q_tc tc*te + q_tc2 te^2 - c_tc tc^3 (c_tc_warm for tc>0) + b_tc
  dte/dt = [A_te_te + s_te(t)] te + A_te_tc tc + A_te_h h + A_te_u u + A_te_ta ta
           + q_te r^2/(1+(r/rs_te)^2) + q_teh te*h + Rs_teh cos(2pi(t-ph_teh)/12) h + r_cold min(te,0) - c_te te^3 + b_te,  r = max(te - te0, 0)  (c_te_cold replaces c_te for te<0)
  dh/dt  = A_h_h [1 + Rs_hh cos(2pi(t-ph_hh)/12)] h + s_h(t)*(A_h_tc tc + A_h_te te + A_h_te_warm max(te,0) + A_h_u u + A_h_ta ta) + b_h   (recharge/discharge; A_h_te_warm optional, default 0)
           s_h(t) = 1 + Rs_h cos(2 pi (t - ph_h)/12)  (seasonal wind-stress-curl efficiency)
  du/dt  = A_u_u u + A_u_tc tc + A_u_te te + A_u_h h + A_u_ta ta            (zonal current)
  dta/dt = A_ta_ta ta + A_ta_tc tc + A_ta_te te + A_ta_h h                  (wind, red noise)
  s_te(t) = Rs_te cos(2 pi (t - ph_te)/12) + Rs2 cos(4 pi (t - ph2)/12);  s_tc likewise (same 2nd harmonic).
Noise (Euler-Maruyama): additive sig_* on each variable; tau noise amplitude
  sig_ta * (1 + m_ta*te)_+ * (1 + Ss_ta cos(2 pi (t - ph_sta)/12)).
The step sub-divides dt internally so the Euler step never exceeds `dt_max` months; the cubic
damping terms are applied semi-implicitly and the state is boxed at ~5x observed extremes,
so the integrator stays finite from any initial state.
"""
import numpy as np

SC = dict(T=7.5, h=150.0, u=1.5, tau=5.0, t=2.0)
NAMES = ['tc', 'te', 'h', 'u', 'ta']
BOUND = np.array([[2.0], [2.0], [2.0], [3.0], [4.0]])   # nondim: 15 degC, 300 m, 4.5 m/s, 20 m/s


class ENSOModel:
    def __init__(self, params):
        p = dict(params)
        self.p = p
        A = np.zeros((5, 5))
        for i, a in enumerate(NAMES):
            for j, b in enumerate(NAMES):
                A[i, j] = p.get(f'A_{a}_{b}', 0.0)
        self.A = A
        self.sig = np.array([p.get(f'sig_{n}', 0.0) for n in NAMES])
        self.dt_max = p.get('dt_max', 0.1)

    def drift(self, x, t):
        p, A = self.p, self.A
        tc, te, h, u, ta = x
        f = A @ x
        ph = 2*np.pi*t/12.0
        s2 = p['Rs2']*np.cos(2*ph - 4*np.pi*p['ph2']/12.0)
        s_te = p['Rs_te']*np.cos(ph - 2*np.pi*p['ph_te']/12.0) + s2
        s_tc = p['Rs_tc']*np.cos(ph - 2*np.pi*p['ph_tc']/12.0) + s2
        s_h = 1.0 + p['Rs_h']*np.cos(ph - 2*np.pi*p['ph_h']/12.0)
        s_teh = p.get('Rs_teh', 0.0)*np.cos(ph - 2*np.pi*p.get('ph_teh', 4.0)/12.0)
        rhc = p.get('rh_cold', 0.0)
        if rhc:
            s_h = s_h*(1.0 - rhc/(1.0 + np.exp(te/0.1)))   # slower recharge forcing while TE is cold
        f[2] += p.get('A_h_te_warm', 0.0)*np.maximum(te, 0.0)   # optional extra discharge efficiency for warm TE
        s_hh = 1.0 + p.get('Rs_hh', 0.0)*np.cos(ph - 2*np.pi*p.get('ph_hh', 7.0)/12.0)   # optional seasonal thermocline damping
        f[2] = s_hh*A[2, 2]*h + s_h*(f[2] - A[2, 2]*h) + p['b_h']
        r = np.maximum(te - p['te0'], 0.0)
        f[0] += s_tc*tc + p['q_tc']*tc*te + p['q_tc2']*te**2 + p['b_tc']
        f[1] += s_te*te + p['q_te']*r*r/(1.0 + (r/p['rs_te'])**2) + p['q_teh']*te*h + s_teh*h + p['r_cold']*np.minimum(te, 0.0) + p['b_te']
        # cubic damping rates (treated semi-implicitly in step(): x/(1+d*rate)), never explode
        damp = np.zeros_like(x)
        damp[0] = np.where(tc > 0, p.get('c_tc_warm', p['c_tc']), p['c_tc'])*tc**2
        damp[1] = np.where(te > 0, p['c_te'], p['c_te_cold'])*te**2
        return f, damp

    def step(self, state, dt, t, rng):
        p = self.p
        s = np.asarray(state, dtype=float)
        one_d = (s.ndim == 1)
        if one_d:
            s = s[:, None]
        x = s / np.array([SC['T'], SC['T'], SC['h'], SC['u'], SC['tau']])[:, None]
        nsub = max(1, int(np.ceil(dt/self.dt_max - 1e-9)))
        h_m = dt/nsub                       # months
        d = h_m/SC['t']                     # nondim
        sq = np.sqrt(d)
        for k in range(nsub):
            tk = t + k*h_m
            f, damp = self.drift(x, tk)
            n = rng.standard_normal(x.shape)
            rho = p.get('rho_tcte', 0.0)
            if rho:
                n[0] = np.sqrt(1.0 - rho*rho)*n[0] + rho*n[1]
            rho2 = p.get('rho_uta', 0.0)
            if rho2:
                n[3] = np.sqrt(1.0 - rho2*rho2)*n[3] + rho2*n[4]
            amp = self.sig[:, None]*np.ones_like(x)
            ph = 2*np.pi*tk/12.0
            mult = np.clip(1.0 + p['m_ta']*x[1], 0.2, 5.0)*(1 + p['Ss_ta']*np.cos(ph - 2*np.pi*p['ph_sta']/12.0))
            amp[4] *= mult
            x = (x + f*d + amp*sq*n)/(1.0 + damp*d)
            x = np.clip(x, -BOUND, BOUND)     # safety box (never active in normal runs; ~5x obs extremes)
        out = x * np.array([SC['T'], SC['T'], SC['h'], SC['u'], SC['tau']])[:, None]
        return out[:, 0] if one_d else out
