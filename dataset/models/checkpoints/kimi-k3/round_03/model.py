"""Stochastic two-region (Central/Eastern Pacific) recharge-oscillator model.

State (dimensional, months): TC, TE [degC], hW [m], u [m/s], tau [m/s].
Internally non-dimensionalized with nondim_scales.json. Euler-Maruyama.

Structure (Jin 1997 recharge-oscillator core + stochastic wind + diversity):
  tau = b(m)*TC + xi ,   dxi = -xi/tau_xi dt + s_xi(m) dW       (wind, OU residual)
  dhW = h0 - r_h*hW - c_tau*tau - c_TC*TC - c_TE*TE - c_u*u     (recharge)
  du  = -r_u*u dt + s_u(m) dW                                   (fast current noise)
  dTC = drift_C(TC,TE,hW,u) + s_C(m) dW_C
  dTE = drift_E(TC,TE,hW,u) + s_E(m)[rho dW_C + sqrt(1-rho^2) dW_E]*(1+eps*TE)
SST drifts have seasonal growth R(m), state-dependent growth R1*T (spring
instability), quadratic nonlinearity a*T^2 (asymmetry), recharge a_h*hW.
"""
import numpy as np


class ENSOModel:
    def __init__(self, params):
        p = params
        self.p = p
        self.Ts = p.get('T_scale', 7.5)
        self.hs = p.get('h_scale', 150.0)
        self.us = p.get('u_scale', 1.5)
        self.ws = p.get('tau_scale', 5.0)
        self.ts = p.get('t_scale', 2.0)
        # per-month tables
        def tab(key, default):
            v = p.get(key)
            return np.asarray(v, float) if v is not None else np.full(12, default)
        self.b_m = tab('b_m', 1.72)
        self.mu_w_m = tab('mu_w_m', 0.0)
        self.sigxi_m = tab('sigxi_m', 1.5)
        self.sigC_m = tab('sigC_m', 0.15)
        self.sigE_m = tab('sigE_m', 0.26)
        self.sigu_m = tab('sigu_m', 0.11)
        self.RC_m = tab('RC_m', -0.05)   # seasonal growth adders (per month)
        self.RE_m = tab('RE_m', -0.05)
        # scalars
        for k in ['tau_xi','r_h','h0','c_tau','c_TC','c_TE','c_u','r_u',
                  'RC0','RE0','R1C','R1E','aCC','aEE','aCE','aEC','aCh','aEh',
                  'gC','gE','rho','eps','kC','kE']:
            setattr(self, k, p.get(k, 0.0))

    def step(self, state, dt, t, rng):
        m = int(np.floor(t)) % 12
        S = np.array([self.Ts, self.Ts, self.hs, self.us, self.ws])[:, None]
        x = state / S
        TC, TE, hW, u, tau = x[0], x[1], x[2], x[3], x[4]
        T = 0.5 * (TC + TE)
        dW = rng.standard_normal((4, state.shape[1])) * np.sqrt(dt)

        # wind
        b = self.b_m[m]
        xi = tau - self.mu_w_m[m] / self.ws - b * TC
        xi_new = xi - xi / self.tau_xi * dt + (self.sigxi_m[m] / self.ws) * dW[3]
        tau_new = self.mu_w_m[m] / self.ws + b * TC + xi_new

        # thermocline recharge
        dhW = (self.h0 - self.r_h * hW - self.c_tau * tau
               - self.c_TC * TC - self.c_TE * TE - self.c_u * u) * dt

        # current OU
        du = -self.r_u * u * dt + (self.sigu_m[m] * np.sqrt(2 * self.r_u) / self.us) * dW[2]

        # SST
        RC = self.RC0 + self.RC_m[m] + self.R1C * T + self.aCC * TC
        RE = self.RE0 + self.RE_m[m] + self.R1E * T + self.aEE * TE
        fC = RC * TC + self.aCE * TE + self.aCh * hW + self.gC * u + self.kC
        fE = RE * TE + self.aEC * TC + self.aEh * hW + self.gE * u + self.kE
        dTC = fC * dt + (self.sigC_m[m] / self.Ts) * dW[0]
        mult = 1.0 + self.eps * TE
        dTE = fE * dt + (self.sigE_m[m] / self.Ts) * mult * (
            self.rho * dW[0] + np.sqrt(max(1.0 - self.rho**2, 0.0)) * dW[1])

        xn = np.vstack([TC + dTC, TE + dTE, hW + dhW, u + du, tau_new])
        return xn * S
