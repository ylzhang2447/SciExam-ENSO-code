"""Stochastic conceptual model of ENSO diversity (two-region recharge oscillator).

State (dimensional): TC [C], TE [C], hW [m], u [m/s], tau [m/s].
Internally non-dimensional (nondim_scales.json): T/7.5, h/150, u/1.5, tau/5, time/2 months.
Time t is in months; t mod 12 == 0 is January (seasonal terms use omega = 2*pi/12).

Deterministic drift (per non-dimensional time unit):
  dTE  = R_E(t) TE + (1 + g_s cos(omega (t - phi_g))) gam_E hW + alp_E u + b_E tau + k_EC TC
         + q_E TE W_E tanh(sp(TE - T0_E)/W_E) - d_E TE sp(TE) - v_E - c_E TE^3
  dTC  = R_C(t) TC + gam_C hW + alp_C u + b_C tau + k_CE TE - d_C TC sp(TC) + q_C TC^2 - v_C - c_C TC^3
  dhW  = -r_h hW - (1 + a_s cos(omega (t - phi_as))) (a_E TE + a_C TC) - b_h tau - a_u u
  sp(x) = softplus(x) (smooth positive part, sharpness k_sp). Nonlinearities (all warm-side):
   d_E: moderate warm TE is damped extra (limited thermocline feedback for weak warming -> such
        events are Central-Pacific led); q_E, T0_E: above the threshold T0_E strong eastern warming
        grows super-linearly (nonlinear thermocline feedback -> extreme EP events), the extra growth
        rate saturating at q_E*W_E so no warm fixed point exists; d_C: warm TC
        saturates (nonlinear convective damping -> negative TC skewness). v_E, v_C are constants
        that remove the mean shift these asymmetric terms would otherwise induce.
  du   = -r_u u + beta_t tau + beta_h hW
  dtau = -r_t tau + (1 + mu_a cos(omega (t - phi_a))) (m_C TC + m_E TE + m_2 Tm sp(Tm)) + m_h hW,  Tm = (TC+TE)/2
  (m_2: convex wind response to basin-mean warming, a convection-threshold effect: moderate warmings
   drive weak westerlies (CP-like), strong warmings drive strong westerlies (EP-like))
  R_X(t) = R_X0 (1 + R_Xa cos(omega (t - phi_X)) + R_Xb cos(2 omega (t - phi_X2)))   (annual + semiannual
           modulation of the net growth rate / Bjerknes feedback)
Stochastic forcing (Euler-Maruyama, increments ~ sqrt(dt)):
  tau: sig_t * (1 + s_t cos(omega (t - phi_t))) * (1 + mu_t * softplus(TC)) * xi   (state-dependent
       westerly-burst noise, warm-phase enhanced), plus additive noise on TE, TC, hW, u
       with TC noise cold-enhanced by (1 + mu_Cn * softplus(-TC)), TE noise warm-enhanced by (1 + mu_E * softplus(TE)) and seasonally modulated by
       (1 + s_E cos(omega (t - phi_En))); hW and u noise seasonally modulated.
Cubic damping is applied implicitly (x /(1 + c dt x^2)) so the scheme is stable for dt up to 1 month.
"""
import numpy as np

SC_T, SC_H, SC_U, SC_TAU, SC_TIME = 7.5, 150.0, 1.5, 5.0, 2.0
OMEGA = 2.0 * np.pi / 12.0   # per month


def _sp(x, k=25.0):
    """smooth positive part (softplus) of a nondim-scaled variable; k sets sharpness."""
    return np.log1p(np.exp(np.clip(k * x, -50, 50))) / k


class ENSOModel:
    def __init__(self, params):
        self.p = dict(params)

    # ---- non-dimensional drift; x shape (5, M) nondim; t in months ----
    def drift(self, x, t):
        p = self.p
        TC, TE, hW, u, tau = x
        cE = np.cos(OMEGA * (t - p['phi_E'])); cC = np.cos(OMEGA * (t - p['phi_C']))
        RE = p['R_E0'] * (1.0 + p['R_Ea'] * cE + p['R_Eb'] * np.cos(2 * OMEGA * (t - p['phi_E2'])))
        RC = p['R_C0'] * (1.0 + p['R_Ca'] * cC + p['R_Cb'] * np.cos(2 * OMEGA * (t - p['phi_C2'])))
        gs = 1.0 + p.get('g_s', 0.0) * np.cos(OMEGA * (t - p.get('phi_g', 0.0)))   # seasonal thermocline feedback
        dTE = (RE * TE + gs * p['gam_E'] * hW + p['alp_E'] * u + p['b_E'] * tau + p['k_EC'] * TC
               + p['q_E'] * TE * p['W_E'] * np.tanh(_sp(TE - p['T0_E'], p['k_sp']) / p['W_E'])
               - p['d_E'] * TE * _sp(TE, p['k_sp']) - p['v_E'])
        dTC = (RC * TC + p['gam_C'] * hW + p['alp_C'] * u + p['b_C'] * tau + p['k_CE'] * TE
               - p['d_C'] * TC * _sp(TC, p['k_sp']) + p['q_C'] * TC * TC - p['v_C'] + p['q_CE'] * TC * TE)
        cs = 1.0 + p['a_s'] * np.cos(OMEGA * (t - p['phi_as']))   # seasonal discharge efficiency
        dh = -p['r_h'] * hW - cs * (p['a_E'] * TE + p['a_C'] * TC) - p['b_h'] * tau - p['a_u'] * u
        du = -p['r_u'] * u + p['beta_t'] * tau + p['beta_h'] * hW
        ca = 1.0 + p['mu_a'] * np.cos(OMEGA * (t - p['phi_a']))   # seasonal atmospheric sensitivity
        Tm = 0.5 * (TC + TE)
        dtau = -p['r_t'] * tau + ca * (p['m_C'] * TC + p['m_E'] * TE + p['m_2'] * Tm * _sp(Tm, p['k_sp'])) + p['m_h'] * hW
        return np.vstack([dTC, dTE, dh, du, dtau])

    def noise_amp(self, x, t):
        """per-variable noise amplitude (nondim, per sqrt(nondim time))."""
        p = self.p
        TC, TE = x[0], x[1]
        st = p['sig_t'] * (1.0 + p['s_t'] * np.cos(OMEGA * (t - p['phi_t']))) * (1.0 + p['mu_t'] * _sp(TC, p['k_sp']))
        sE = (p['sig_TE'] * (1.0 + p.get('s_E', 0.0) * np.cos(OMEGA * (t - p.get('phi_En', 0.0))))
              * (1.0 + p['mu_E'] * _sp(TE, p['k_sp'])))
        M = x.shape[1]
        sh = p['sig_h'] * (1.0 + p['s_h'] * np.cos(OMEGA * (t - p['phi_h'])))
        su = p['sig_u'] * (1.0 + p['s_u'] * np.cos(OMEGA * (t - p['phi_u'])))
        sC = p['sig_TC'] * (1.0 + p.get('mu_Cn', 0.0) * _sp(-TC, p['k_sp']))   # cold-enhanced TC noise
        return np.vstack([sC, sE, np.full(M, sh), np.full(M, su), st])

    def step(self, state, dt, t, rng):
        p = self.p
        x = np.array(state, dtype=float)
        if x.ndim == 1:
            x = x[:, None]
        x = x / np.array([SC_T, SC_T, SC_H, SC_U, SC_TAU])[:, None]
        dtn = dt / SC_TIME
        f = self.drift(x, t)
        amp = self.noise_amp(x, t)
        xi = rng.standard_normal(x.shape)
        y = x + f * dtn + amp * np.sqrt(dtn) * xi
        # implicit cubic damping on the SST variables (unconditionally stable)
        y[0] = y[0] / (1.0 + p['c_C'] * dtn * y[0] * y[0])
        y[1] = y[1] / (1.0 + p['c_E'] * dtn * y[1] * y[1])
        y = np.clip(y, -5.0, 5.0)   # hard safety bound (never active in normal operation)
        out = y * np.array([SC_T, SC_T, SC_H, SC_U, SC_TAU])[:, None]
        return out.reshape(np.shape(state)) if np.ndim(state) == 1 else out
