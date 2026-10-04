"""Stochastic two-region (Central/Eastern Pacific) recharge-oscillator model.

State (dimensional, months): TC, TE [degC], hW [m], u [m/s], tau [m/s].
Euler-Maruyama. Parameters were fitted on indices non-dimensionalized with
nondim_scales.json (scales stored in params for reference); step is dimensional.

Core: linear coupled drift A_fit (Yule-Walker / conditional-MLE estimate of the
recharge-oscillator system) + correlated noise (Cholesky L). On top:
  - seasonal modulation of wind coupling, growth rates, and noise amplitudes
  - state-dependent growth R1*Tbar (spring instability) and quadratic a*T^2
    (El Nino / La Nina asymmetry)
  - multiplicative noise eps*TE on TE (extreme eastern-Pacific events)
  - seasonal mean adjustments k_m to control event asymmetry.
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

        self.A = np.asarray(p['A'], float)          # (5,5) drift /month
        self.L = np.asarray(p['L'], float)          # (5,5) noise chol
        self.const = np.asarray(p.get('const', [0]*5), float)

        def tab(key, n=12, default=0.0):
            v = p.get(key)
            return np.asarray(v, float) if v is not None else np.full(n, default)
        # seasonal additive growth adjustments (per month) on TC, TE rows
        self.RC_m = tab('RC_m')
        self.RE_m = tab('RE_m')
        self.kTC_m = tab('kTC_m')
        self.kTE_m = tab('kTE_m')
        # seasonal noise scale multipliers
        self.nC_m = tab('nC_m', default=1.0)
        self.nE_m = tab('nE_m', default=1.0)
        self.nxi_m = tab('nxi_m', default=1.0)
        self.nu_m = tab('nu_m', default=1.0)
        self.nh_m = tab('nh_m', default=1.0)
        self.gH_m = tab('gH_m', default=0.0)
        self.hmod_m = tab('hmod_m', default=0.0)
        # scalars
        for k in ['R1C', 'R1E', 'aCC', 'aEE', 'eps', 'bmod', 'gLN', 'fbC', 'fbE', 'gDis', 'epsC', 'epsH', 'ln_damp_frac', 'epsTau', 'epsTauE', 'bTE', 'bTE_TC', 'gDis_mean']:
            setattr(self, k, p.get(k, 0.0))
        w = p.get('winter_m')
        self.winter_m = np.asarray(w, float) if w is not None else np.array([1,1,0,0,0,0,0,0,0,0,0,1], float)

    def step(self, state, dt, t, rng):
        m = int(np.floor(t)) % 12
        TC, TE = state[0], state[1]
        Tbar = 0.5 * (TC + TE)
        dW = rng.standard_normal((5, state.shape[1])) * np.sqrt(dt)

        drift = self.const[:, None] + self.A @ state
        # wind responds to eastern-Pacific convection too (positive TE skew ->
        # positive tau skew); reduce TC weight to hold wind variance
        drift[4] = drift[4] + self.bTE * TE - self.bTE_TC * TC
        # seasonal + nonlinear SST adjustments
        drift[0] = drift[0] + self.RC_m[m] * TC + self.R1C * Tbar * TC \
            + self.aCC * TC * TC + self.kTC_m[m]
        drift[1] = drift[1] + self.RE_m[m] * TE + self.R1E * Tbar * TE \
            + self.aEE * TE * TE + self.kTE_m[m]
        drift[2] = drift[2] + self.gH_m[m]
        # seasonal modulation of the recharge (wind->hW) coupling: gives a resonant
        # annual cycle in hW (the seasonal recharge oscillator)
        drift[2] = drift[2] * (1.0 + self.hmod_m[m])
        # extra recharge feedback hW -> SST (strengthens oscillator)
        drift[0] = drift[0] + self.fbC * state[2]
        drift[1] = drift[1] + self.fbE * state[2]
        # asymmetric discharge: strong El Nino enhances heat discharge (termination),
        # La Nina recharge stays weak (persistence). Mean-corrected so it does not
        # bias the mean state (subtract the climatological E[max(TE,0)^2]).
        warm = np.maximum(TE, 0.0)
        drift[2] = drift[2] - self.gDis * (warm * warm - self.gDis_mean)
        # Asymmetric seasonal termination: in winter (Dec-Feb) strong damping applies
        # to warm events (El Nino terminates) but is weak for cold (La Nina persists).
        if self.gLN > 0 and self.winter_m[m] > 0:
            damp = np.where(Tbar > 0, self.gLN, self.gLN * self.ln_damp_frac)
            drift[0] = drift[0] - damp * TC * self.winter_m[m]
            drift[1] = drift[1] - damp * TE * self.winter_m[m]

        # seasonal noise: scale rows C, E, xi(wind)
        L = self.L.copy()
        L[0, :] = L[0, :] * self.nC_m[m]
        L[1, :] = L[1, :] * self.nE_m[m]
        L[2, :] = L[2, :] * self.nh_m[m]
        L[3, :] = L[3, :] * self.nu_m[m]
        L[4, :] = L[4, :] * self.nxi_m[m]
        noise = L @ dW
        # multiplicative noise on TE (and weakly on TC, opposite sign for -skew)
        noise[0] = noise[0] * (1.0 + self.epsC * TC)
        noise[1] = noise[1] * (1.0 + self.eps * TE)
        noise[2] = noise[2] * (1.0 + self.epsH * state[2] / 13.46)
        noise[4] = noise[4] * (1.0 + self.epsTau * Tbar) + self.epsTauE * np.maximum(TE, 0.0) * np.abs(dW[3]) / np.sqrt(max(dt, 1e-9)) * np.sqrt(dt)

        return state + drift * dt + noise
