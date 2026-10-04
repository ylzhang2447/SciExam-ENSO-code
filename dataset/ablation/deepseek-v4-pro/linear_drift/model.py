"""ENSOModel: stochastic 5-variable model for ENSO diversity.

State (dimensional): [TC, TE, hW, u, tau] in [C, C, m, m/s, m/s]

Linear dynamics: empirical VAR(1) fit to nondimensional observed indices.
Nonlinear terms produce EP/CP asymmetry (El Nino vs La Nina diversity):
  - Sigmoid asymmetric growth: restoring damping weakened on the warm side of
    TE and on the cold side of TC, giving positive TE skew and negative TC skew.
  - State-dependent multiplicative noise: amplitude grows with |state| and is
    larger on the warm side of TE / cold side of TC; this is the dominant source
    of the stationary skew because Gaussian noise alone gives zero skew.
  - Cubic saturation bounds large excursions.
Seasonal modulation drives phase locking to boreal winter.
Soft saturation keeps the integration numerically stable.

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
        self.A = np.array(params["A_matrix"]).reshape(5, 5)
        self.dA = np.array(params.get("dA_matrix", [[0]*5]*5)).reshape(5, 5)
        self.seas_peak = params.get("season_peak_month", 12)
        m = np.arange(12)
        self._seas = np.cos(2 * np.pi * (m - (self.seas_peak - 1)) / 12)

    def step(self, state, dt, t, rng):
        p = self.p
        if state.ndim == 1:
            state_2d = state[:, None]
            M = 1
            squeeze_out = True
        else:
            state_2d = state
            M = state.shape[1]
            squeeze_out = False

        # Nondimensionalize
        s = np.zeros((5, M))
        s[0] = state_2d[0] / self.T_s
        s[1] = state_2d[1] / self.T_s
        s[2] = state_2d[2] / self.h_s
        s[3] = state_2d[3] / self.u_s
        s[4] = state_2d[4] / self.tau_s
        dt_nd = dt / self.t_s
        sqdt = np.sqrt(dt_nd)
        seas = self._seas[int(np.floor(t)) % 12]

        # Linear drift
        A_eff = self.A + seas * self.dA
        drift = A_eff @ s

        # Nonlinear asymmetry terms
        # Saturating asymmetric growth: the restoring damping is weakened on the
        # warm side (TE>0) and on the cold side (TC<0), producing the observed
        # positive TE skew and negative TC skew.  The sigmoid makes the extra
        # growth switch on sharply for one sign and stay ~0 for the other, and
        # the cubic term bounds the state so the weakened damping cannot run away.
        g_te = p.get("g_asym_TE", 0.0)
        g_tc = p.get("g_asym_TC", 0.0)
        k_asym = p.get("k_asym", 12.0)
        if g_te > 0.0:
            drift[1] += g_te * s[1] / (1.0 + np.exp(-np.clip(k_asym * s[1], -60, 60)))
        if g_tc > 0.0:
            drift[0] += g_tc * s[0] / (1.0 + np.exp(np.clip(k_asym * s[0], -60, 60)))

        # Cubic saturation bounds the asymmetric growth at large amplitude.
        # Applied only to the tail direction that would otherwise diverge:
        # for TE the warm tail (s>0), for TC the cold tail (s<0).
        # This preserves the desired skew while capping the extreme tail.
        c_sat = p.get("c_sat", 0.0)
        c_sat_tc = p.get("c_sat_TC", c_sat)
        c_tail = p.get("c_sat_tail", 0.0)
        if c_sat > 0.0:
            drift[1] -= c_sat * s[1]**3
        if c_tail > 0.0:
            # One-sided: harder wall on warm TE tail
            drift[1] -= c_tail * np.maximum(s[1], 0.0)**3
        if c_sat_tc > 0.0:
            drift[0] -= c_sat_tc * s[0]**3

        # Wind saturation at high amplitude
        drift[4] -= p.get("tau_nl", 0.0) * s[4]**3

        # Stochastic forcing
        ns_seas = 1.0 + p.get("s_noise_amp", 0.0) * seas
        noise = rng.standard_normal((5, M))
        rn = p.get("noise_corr_te_tc", 0.0)
        if rn > 0:
            noise[1] = rn * noise[0] + np.sqrt(max(1e-10, 1 - rn**2)) * noise[1]

        sigma = np.array(p["sigma_diag"])[:, None]
        stoch = sigma * noise * ns_seas * sqdt

        # Base multiplicative noise (symmetric, on absolute value)
        mult_TC = p.get("sigma_mult_TC", 0.0)
        mult_TE = p.get("sigma_mult_TE", 0.0)
        if mult_TC > 0:
            stoch[0] += mult_TC * np.abs(s[0]) * rng.standard_normal(M) * sqdt
        if mult_TE > 0:
            stoch[1] += mult_TE * np.abs(s[1]) * rng.standard_normal(M) * sqdt

        # Asymmetric noise: only on positive TE (reinforces warm events)
        asym_noise_TE = p.get("sigma_asym_TE", 0.0)
        if asym_noise_TE > 0:
            stoch[1] += asym_noise_TE * np.maximum(s[1], 0.0) * rng.standard_normal(M) * sqdt

        # Asymmetric noise on negative TC (reinforces cold CP events)
        asym_noise_TC = p.get("sigma_asym_TC", 0.0)
        if asym_noise_TC > 0:
            stoch[0] += asym_noise_TC * np.maximum(-s[0], 0.0) * rng.standard_normal(M) * sqdt

        # Euler-Maruyama with clipping
        s_new = s + drift * dt_nd + stoch
        s_new = np.clip(s_new, -20, 20)

        # Redimensionalize
        out = np.zeros((5, M))
        out[0] = s_new[0] * self.T_s
        out[1] = s_new[1] * self.T_s
        out[2] = s_new[2] * self.h_s
        out[3] = s_new[3] * self.u_s
        out[4] = s_new[4] * self.tau_s
        if squeeze_out:
            return out[:, 0]
        return out

    def simulate(self, n_months, dt=0.1, burn_in=120, rng=None):
        if rng is None:
            rng = np.random.default_rng()
        state = np.zeros((5, 1))
        t = 0.0
        samples = []
        nsamp = burn_in
        total = burn_in + n_months
        n_steps = int(total / dt) + 1
        for _ in range(n_steps):
            while t >= nsamp - 1e-8 and len(samples) < n_months:
                samples.append(state[:, 0].copy())
                nsamp += 1.0
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
        traj = np.stack(trajs, axis=-1)
        traj = traj.transpose(1, 0, 2)
        mean = traj.mean(axis=0)
        return traj, mean