"""
ENSO stochastic conceptual model — extended recharge oscillator.

State (dimensional, 5 variables):
    TC  central-Pacific SST anomaly      [deg C]
    TE  eastern-Pacific SST anomaly       [deg C]
    hW  western-Pacific thermocline anom  [m]
    u   central-Pacific zonal current an  [m/s]
    tau WP zonal wind anomaly             [m/s]

Built on Jin (1997) recharge oscillator, extended to 5 variables with
stochastic forcing, nonlinearity, seasonality, and CP/EP diversity.

Nondimensional scales: T=7.5C, h=150m, u=1.5m/s, tau=5m/s, t=2mo.
"""

import numpy as np


class ENSOModel:
    def __init__(self, params: dict):
        self.p = dict(params)

        # Nondimensional scales
        self.T_scale = 7.5
        self.h_scale = 150.0
        self.u_scale = 1.5
        self.tau_scale = 5.0
        self.t_scale = 2.0

        # --- Core parameters ---
        self.c_E = self.p.get('c_E', 0.7)
        self.c_C = self.p.get('c_C', 0.7)
        self.gamma_E = self.p.get('gamma_E', 0.75)
        self.gamma_C = self.p.get('gamma_C', 0.45)
        self.mu = self.p.get('mu', 0.6)
        self.b_E = self.p.get('b_E', 0.7)
        self.b_C = self.p.get('b_C', 1.0)
        self.slope = self.p.get('slope', 2.5)
        self.r = self.p.get('r', 0.25)
        self.a = self.p.get('a', 0.125)

        # Zonal current
        self.r_u = self.p.get('r_u', 0.5)
        self.alpha_u = self.p.get('alpha_u', 0.3)
        self.beta_u = self.p.get('beta_u', 0.5)

        # Nonlinearity: saturating thermocline feedback with asymmetry
        # Different saturation scales for warm (deep thermocline) vs cold (shallow)
        # h_sat_pos > h_sat_neg -> warm events stronger -> positive TE skew
        self.h_sat_E_pos = self.p.get('h_sat_E_pos', 0.3)
        self.h_sat_E_neg = self.p.get('h_sat_E_neg', 0.3)
        self.h_sat_C_pos = self.p.get('h_sat_C_pos', 0.45)
        self.h_sat_C_neg = self.p.get('h_sat_C_neg', 0.45)
        self.en_TE = self.p.get('en_TE', 8.0)
        self.en_TC = self.p.get('en_TC', 4.0)

        self.alpha_CE = self.p.get('alpha_CE', 0.1)
        self.delta_C = self.p.get('delta_C', 0.05)

        # Seasonal modulation
        self.season_amp = self.p.get('season_amp', 0.4)
        self.season_phase = self.p.get('season_phase', 0.0)

        # Wind relaxation rate
        self.r_tau = self.p.get('r_tau', 3.0)

        # Stochastic forcing
        self.sigma_tau = self.p.get('sigma_tau', 0.5)
        self.sigma_h = self.p.get('sigma_h', 0.0)
        self.sigma_T = self.p.get('sigma_T', 0.0)

        # Fraction of tau noise that feeds into ocean dynamics
        # (0 = noise doesn't affect ocean, 1 = full coupling)
        self.noise_to_ocean = self.p.get('noise_to_ocean', 0.3)

    def _seasonal_factor(self, t_nondim):
        omega = 2.0 * np.pi / 6.0
        phase = self.season_phase / self.t_scale
        return 1.0 + self.season_amp * np.cos(omega * t_nondim + phase)

    def step(self, state, dt, t, rng):
        state = np.asarray(state, dtype=np.float64)
        if state.ndim == 1:
            state = state.reshape(-1, 1)
        M = state.shape[1]

        dt_nd = dt / self.t_scale
        t_nd = t / self.t_scale
        sqrt_dt = np.sqrt(dt_nd)

        TC = state[0] / self.T_scale
        TE = state[1] / self.T_scale
        hW = state[2] / self.h_scale
        u  = state[3] / self.u_scale
        tau = state[4] / self.tau_scale

        s = self._seasonal_factor(t_nd)

        # Wind: relaxation toward SST-driven equilibrium + stochastic noise
        tau_eq = self.mu * (self.b_E * TE + self.b_C * TC) * s
        d_tau = -self.r_tau * (tau - tau_eq)

        # Split tau into deterministic (SST-driven) and stochastic components
        # The ocean dynamics respond to the deterministic part primarily
        tau_det = tau_eq  # SST-driven equilibrium wind
        tau_stoch = tau - tau_eq  # stochastic deviation

        # Ocean feels the full tau, but with reduced sensitivity to noise
        tau_ocean = tau_det + self.noise_to_ocean * tau_stoch
        tau_eff = self.slope * tau_ocean

        # Recharge/discharge
        d_hW = -self.r * hW - self.a * tau_eff

        # Thermocline depths
        hE = hW + tau_eff
        hC = hW + 0.5 * tau_eff

        # Saturating thermocline feedback with asymmetric saturation
        # Warm events (hE > 0) use h_sat_pos, cold events (hE < 0) use h_sat_neg
        h_sat_E = np.where(hE > 0, self.h_sat_E_pos, self.h_sat_E_neg)
        h_sat_C = np.where(hC > 0, self.h_sat_C_pos, self.h_sat_C_neg)
        fb_E = h_sat_E * np.tanh(hE / h_sat_E)
        fb_C = h_sat_C * np.tanh(hC / h_sat_C)

        # Eastern Pacific SST
        d_TE = (-self.c_E * TE + self.gamma_E * fb_E * s
                - self.en_TE * TE ** 3)

        # Central Pacific SST
        d_TC = (-self.c_C * TC + self.gamma_C * fb_C * s
                - self.en_TC * TC ** 3
                + self.alpha_CE * TE
                - self.delta_C * u)

        # Zonal current (responds to full tau including noise)
        d_u = -self.r_u * u + self.alpha_u * tau + self.beta_u * hW

        # Stochastic terms
        noise_tau = self.sigma_tau * rng.standard_normal(M) * sqrt_dt * s
        noise_h = self.sigma_h * rng.standard_normal(M) * sqrt_dt
        noise_T = self.sigma_T * rng.standard_normal(M) * sqrt_dt

        # Euler-Maruyama
        TC_new  = TC  + d_TC  * dt_nd + noise_T
        TE_new  = TE  + d_TE  * dt_nd + noise_T * 0.5
        hW_new  = hW  + d_hW  * dt_nd + noise_h
        u_new   = u   + d_u   * dt_nd
        tau_new = tau + d_tau * dt_nd + noise_tau

        # Safety clip
        clip_val = 10.0
        np.clip(TC_new, -clip_val, clip_val, out=TC_new)
        np.clip(TE_new, -clip_val, clip_val, out=TE_new)
        np.clip(hW_new, -clip_val, clip_val, out=hW_new)
        np.clip(u_new, -clip_val, clip_val, out=u_new)
        np.clip(tau_new, -clip_val, clip_val, out=tau_new)

        new_state = np.empty_like(state)
        new_state[0] = TC_new * self.T_scale
        new_state[1] = TE_new * self.T_scale
        new_state[2] = hW_new * self.h_scale
        new_state[3] = u_new * self.u_scale
        new_state[4] = tau_new * self.tau_scale

        return new_state
