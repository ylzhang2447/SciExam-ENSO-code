"""
ENSO stochastic conceptual model — extended recharge oscillator with diversity.

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

        # Nondimensional scales (from nondim_scales.json)
        self.T_scale = 7.5
        self.h_scale = 150.0
        self.u_scale = 1.5
        self.tau_scale = 5.0
        self.t_scale = 2.0

        # --- Core coupling ---
        self.c_E = self.p.get('c_E', 0.3)
        self.c_C = self.p.get('c_C', 0.3)
        self.gamma_E = self.p.get('gamma_E', 0.75)
        self.gamma_C = self.p.get('gamma_C', 0.45)
        self.mu = self.p.get('mu', 0.33)
        self.b_E = self.p.get('b_E', 0.7)
        self.b_C = self.p.get('b_C', 1.0)
        self.slope = self.p.get('slope', 2.5)
        self.r = self.p.get('r', 0.25)
        self.a = self.p.get('a', 0.125)

        # Zonal current
        self.r_u = self.p.get('r_u', 1.0)
        self.alpha_u = self.p.get('alpha_u', 0.1)
        self.beta_u = self.p.get('beta_u', 1.2)

        # Nonlinearity: saturating thermocline feedback with asymmetry
        self.h_sat_E_pos = self.p.get('h_sat_E_pos', 1.0)
        self.h_sat_E_neg = self.p.get('h_sat_E_neg', 0.20)
        self.h_sat_C_pos = self.p.get('h_sat_C_pos', 0.45)
        self.h_sat_C_neg = self.p.get('h_sat_C_neg', 0.45)
        self.en_TE = self.p.get('en_TE', 12.0)
        self.en_TC = self.p.get('en_TC', 6.0)

        # Nonlinear SST-wind coupling (quadratic: stronger westerlies during warm events)
        # Creates positive TE skew: warm events have stronger wind feedback
        self.nw_E = self.p.get('nw_E', 0.0)  # nonlinear wind feedback for TE
        self.nw_C = self.p.get('nw_C', 0.0)  # nonlinear wind feedback for TC

        # Coupling TE→TC (Bjerknes spreading)
        self.alpha_CE = self.p.get('alpha_CE', 0.10)
        self.delta_C = self.p.get('delta_C', 0.05)

        # Seasonal modulation
        self.season_amp = self.p.get('season_amp', 0.4)
        self.season_phase = self.p.get('season_phase', -5.0)
        # Noise seasonal modulation (independent of coupling)
        self.noise_season_amp = self.p.get('noise_season_amp', 0.5)
        self.noise_season_phase = self.p.get('noise_season_phase', 2.0)

        # Wind relaxation rate
        self.r_tau = self.p.get('r_tau', 0.7)

        # Stochastic forcing
        self.sigma_tau = self.p.get('sigma_tau', 0.45)
        self.sigma_h = self.p.get('sigma_h', 0.0)
        self.sigma_TC = self.p.get('sigma_TC', 0.0)
        self.sigma_TE = self.p.get('sigma_TE', 0.0)
        self.sigma_u = self.p.get('sigma_u', 0.12)

        # Multiplicative noise: noise amplitude increases with warm SST
        self.mult_noise = self.p.get('mult_noise', 0.0)

        # Fraction of tau noise that feeds into ocean dynamics
        self.noise_to_ocean = self.p.get('noise_to_ocean', 0.1)

    def _seasonal_factor(self, t_nondim):
        """Seasonal modulation of coupling strength (phase locking)."""
        omega = 2.0 * np.pi / 6.0  # period = 12 months = 6 nondim units
        phase = self.season_phase / self.t_scale
        return 1.0 + self.season_amp * np.cos(omega * t_nondim + phase)

    def _noise_seasonal_factor(self, t_nondim):
        """Seasonal modulation of noise amplitude (independent phase)."""
        omega = 2.0 * np.pi / 6.0
        phase = self.noise_season_phase / self.t_scale
        return 1.0 + self.noise_season_amp * np.cos(omega * t_nondim + phase)

    def step(self, state, dt, t, rng):
        state = np.asarray(state, dtype=np.float64)
        if state.ndim == 1:
            state = state.reshape(-1, 1)
        M = state.shape[1]

        dt_nd = dt / self.t_scale
        t_nd = t / self.t_scale
        sqrt_dt = np.sqrt(dt_nd)

        # Nondimensionalize
        TC = state[0] / self.T_scale
        TE = state[1] / self.T_scale
        hW = state[2] / self.h_scale
        u  = state[3] / self.u_scale
        tau = state[4] / self.tau_scale

        s = self._seasonal_factor(t_nd)
        s_noise = self._noise_seasonal_factor(t_nd)

        # Wind: relaxation toward SST-driven equilibrium + stochastic noise
        # Nonlinear wind coupling: stronger response for warm SST
        tau_eq = self.mu * (self.b_E * TE + self.b_C * TC
                            + self.nw_E * TE ** 2 + self.nw_C * TC ** 2) * s
        d_tau = -self.r_tau * (tau - tau_eq)

        # Ocean sees deterministic wind + reduced noise
        tau_stoch = tau - tau_eq
        tau_ocean = tau_eq + self.noise_to_ocean * tau_stoch
        tau_eff = self.slope * tau_ocean

        # Recharge/discharge
        d_hW = -self.r * hW - self.a * tau_eff

        # Thermocline depths (Sverdrup balance)
        hE = hW + tau_eff
        hC = hW + 0.5 * tau_eff

        # Saturating thermocline feedback with asymmetric saturation
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

        # Zonal current (fast damping, wind + thermocline driven)
        d_u = -self.r_u * u + self.alpha_u * tau + self.beta_u * hW

        # Stochastic terms (independent draws per variable)
        # Multiplicative noise: stronger during warm events
        mult_factor = 1.0 + self.mult_noise * np.maximum(TE, 0.0)
        noise_tau = self.sigma_tau * mult_factor * rng.standard_normal(M) * sqrt_dt * s_noise
        noise_h = self.sigma_h * rng.standard_normal(M) * sqrt_dt
        noise_TC = self.sigma_TC * rng.standard_normal(M) * sqrt_dt
        noise_TE = self.sigma_TE * rng.standard_normal(M) * sqrt_dt
        noise_u = self.sigma_u * rng.standard_normal(M) * sqrt_dt * s_noise

        # Euler-Maruyama
        TC_new  = TC  + d_TC  * dt_nd + noise_TC
        TE_new  = TE  + d_TE  * dt_nd + noise_TE
        hW_new  = hW  + d_hW  * dt_nd + noise_h
        u_new   = u   + d_u   * dt_nd + noise_u
        tau_new = tau + d_tau * dt_nd + noise_tau

        # Safety clip (nondimensional)
        clip_val = 10.0
        np.clip(TC_new, -clip_val, clip_val, out=TC_new)
        np.clip(TE_new, -clip_val, clip_val, out=TE_new)
        np.clip(hW_new, -clip_val, clip_val, out=hW_new)
        np.clip(u_new, -clip_val, clip_val, out=u_new)
        np.clip(tau_new, -clip_val, clip_val, out=tau_new)

        # Redimensionalize
        new_state = np.empty_like(state)
        new_state[0] = TC_new * self.T_scale
        new_state[1] = TE_new * self.T_scale
        new_state[2] = hW_new * self.h_scale
        new_state[3] = u_new * self.u_scale
        new_state[4] = tau_new * self.tau_scale

        return new_state
