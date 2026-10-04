"""ENSOModel: stochastic 5-variable model for ENSO diversity.

State (dimensional): [TC, TE, hW, u, tau] in [C, C, m, m/s, m/s]

The linear dynamics are based on an empirical VAR(1) fit to observed monthly
indices, which captures the correct oscillation period (~4yr), the recharge-
discharge phase relationship, and the inter-variable coupling structure.

Nonlinear terms are added to produce El Nino/La Nina asymmetry, seasonal
modulation creates phase locking to boreal winter, and stochastic forcing
maintains variance against the negative linear growth.

Nondim scales: T=7.5C, h=150m, u=1.5m/s, tau=5m/s, t_scale=2months.
"""

import numpy as np


class ENSOModel:
    def __init__(self, params: dict):
        self.p = params
        self.T_s = 7.5
        self.h_s = 150.0
        self.u_s = 1.5
        self.tau_s = 5.0
        self.t_s = params.get("t_scale_months", 2.0)

        # Linear drift matrix A (nondimensional, continuous-time)
        self.A = np.array(params["A_matrix"]).reshape(5, 5)

        # Seasonal coupling matrix dA (multiplied by cos(2pi*(t-pk)/12))
        self.dA = np.array(params.get("dA_matrix", [[0]*5]*5)).reshape(5, 5)

        # Seasonal peak month (1=Jan, 12=Dec)
        self.seas_peak = params.get("season_peak_month", 12)
        self._precompute_seasonal()

    def _precompute_seasonal(self):
        m = np.arange(12)
        self._seas = np.cos(2 * np.pi * (m - (self.seas_peak - 1)) / 12)

    def _season(self, t):
        return self._seas[int(np.floor(t)) % 12]

    def step(self, state, dt, t, rng):
        p = self.p
        M = state.shape[1]

        # --- Nondimensionalize ---
        s = np.zeros((5, M))
        s[0] = state[0] / self.T_s
        s[1] = state[1] / self.T_s
        s[2] = state[2] / self.h_s
        s[3] = state[3] / self.u_s
        s[4] = state[4] / self.tau_s

        dt_nd = dt / self.t_s
        sqdt = np.sqrt(dt_nd)

        seas = self._season(t)

        # ===== Linear drift =====
        A_eff = self.A + seas * self.dA
        drift = A_eff @ s   # shape (5, M)

        # ===== Nonlinear terms =====
        # Thermocline feedback saturation on TE (eastern SST)
        # hE = hW + b*tau (eastern thermocline tilt)
        b = p.get("b_tilt", 0.6)
        hE = s[2] + b * s[4]

        # Cubic saturation: stronger damping for |hE| large
        nl_TE_thermo = -p.get("e_n", 0.0) * hE**3

        # Quadratic asymmetry: always positive → warm bias → positive skew
        nl_TE_asym = p.get("a_E", 0.0) * hE**2

        drift[1] += nl_TE_thermo + nl_TE_asym

        # Thermocline nonlinearity on TC
        nl_TC_thermo = -p.get("e_n_C", 0.0) * s[2]**3

        # TC asymmetry
        nl_TC_asym = p.get("a_C", 0.0) * s[2]**2

        drift[0] += nl_TC_thermo + nl_TC_asym

        # Asymmetric discharge of warm pool
        nl_hW = p.get("r_asym_h", 0.0) * s[2] * np.abs(s[2])
        drift[2] += nl_hW

        # Wind nonlinear saturation
        nl_tau = -p.get("tau_nl", 0.0) * s[4] * np.abs(s[4])
        drift[4] += nl_tau

        # SST-wind multiplicative (Bjerknes) nonlinearity
        # Warm SST + positive wind → amplifies feedback
        mbj_TC = p.get("mbj_TC", 0.0) * s[0] * s[4]
        mbj_TE = p.get("mbj_TE", 0.0) * s[1] * s[4]
        drift[0] += mbj_TC
        drift[1] += mbj_TE

        # ===== Stochastic forcing =====
        # Seasonal noise modulation
        ns_seas = 1.0 + p.get("s_noise_amp", 0.0) * seas

        # Diagonally-dominant noise (mostly independent per variable)
        noise = rng.standard_normal((5, M))

        # Correlate TE with TC noise
        r_n = p.get("noise_corr_te_tc", 0.0)
        if r_n > 0:
            noise[1] = r_n * noise[0] + np.sqrt(1 - r_n**2) * noise[1]

        sigma = np.array(p["sigma_diag"])[:, None]  # (5, 1)
        stoch = sigma * noise * ns_seas * sqdt

        # Multiplicative noise on SST
        for i, key in [(0, "sigma_mult_TC"), (1, "sigma_mult_TE")]:
            mult = p.get(key, 0.0)
            if mult > 0:
                stoch[i] += mult * np.abs(s[i]) * rng.standard_normal(M) * sqdt

        # ===== Euler-Maruyama =====
        s_new = s + drift * dt_nd + stoch

        # ===== Redimensionalize =====
        out = np.zeros_like(state)
        out[0] = s_new[0] * self.T_s
        out[1] = s_new[1] * self.T_s
        out[2] = s_new[2] * self.h_s
        out[3] = s_new[3] * self.u_s
        out[4] = s_new[4] * self.tau_s

        return out

    def simulate(self, n_months, dt=0.1, burn_in=120, rng=None):
        if rng is None:
            rng = np.random.default_rng()
        state = np.zeros((5, 1))
        t = 0.0
        samples = []
        next_sample = burn_in
        n_steps = int((burn_in + n_months) / dt) + 1
        for _ in range(n_steps):
            while t >= next_sample - 1e-8 and len(samples) < n_months:
                samples.append(state[:, 0].copy())
                next_sample += 1.0
            if len(samples) >= n_months:
                break
            state = self.step(state, dt, t, rng)
            t += dt
        while len(samples) < n_months:
            samples.append(state[:, 0].copy())
        return np.arange(n_months) + burn_in, np.column_stack(samples)

    def forecast(self, init_state, lead_months, n_ensemble, dt=0.1, rng=None):
        if rng is None:
            rng = np.random.default_rng()
        state = np.tile(init_state[:, None], (1, n_ensemble)).astype(float)
        t = 0.0
        trajs = []
        next_rec = 1.0
        n_steps = int(lead_months / dt) + 1
        for _ in range(n_steps):
            while t >= next_rec - 1e-8 and len(trajs) < lead_months:
                trajs.append(state.copy())
                next_rec += 1.0
            if t >= lead_months:
                break
            state = self.step(state, dt, t, rng)
            t += dt
        while len(trajs) < lead_months:
            trajs.append(state.copy())
        traj = np.stack(trajs, axis=-1)  # (5, M, Nsteps)
        traj = traj.transpose(1, 0, 2)   # (M, 5, Nsteps)
        mean = traj.mean(axis=0)          # (5, Nsteps)
        return traj, mean