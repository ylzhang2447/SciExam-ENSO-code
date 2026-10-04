"""ENSOModel: stochastic 5-variable model for ENSO diversity.

State (dimensional): [TC, TE, hW, u, tau]
 - TC: central-Pacific SST anomaly [deg C] - Nino4
 - TE: eastern-Pacific SST anomaly [deg C] - Nino3
 - hW: western-Pacific thermocline anomaly [m] - warm pool depth
 - u: central-Pacific zonal current anomaly [m/s]
 - tau: WP zonal wind anomaly (wind stress proxy) [m/s]

Physical picture (extended Jin 1997 recharge oscillator):
 The Bjerknes feedback couples SST to wind: warm SST → westerly wind.
 Wind tilts the thermocline (deepens east, shoals west) → positive feedback
 on east SST. The recharge mechanism: sustained wind discharges the western
 warm pool over months-years → the phase transition. Nonlinear saturation
 of thermocline feedback gives El Nino / La Nina asymmetry. Two SST indices
 (TC, TE) allow Central vs Eastern Pacific event diversity.

Nondimensional scales: T=7.5C, h=150m, u=1.5m/s, tau=5m/s, t=2months.
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

        # Seasonal modulation: cos(2pi*(m - peak)/12), peak in Dec
        m = np.arange(12)
        pk = params.get("season_peak_month", 12)  # 12=Dec, 1-based
        self._seas_cos = np.cos(2 * np.pi * (m - (pk - 1)) / 12)

    def _S(self, t):
        """Seasonal factor at time t (months)."""
        return self._seas_cos[int(np.floor(t)) % 12]

    def step(self, state, dt, t, rng):
        p = self.p
        M = state.shape[1]

        # --- Nondimensionalize ---
        TC = state[0] / self.T_s
        TE = state[1] / self.T_s
        hW = state[2] / self.h_s
        u  = state[3] / self.u_s
        tau = state[4] / self.tau_s

        dt_nd = dt / self.t_s
        sqdt = np.sqrt(dt_nd)

        seas = self._S(t)

        # Seasonal modulations
        cpl_seas = p["s_cpl_amp"] * seas       # coupling enhancement
        ns_seas  = 1.0 + p["s_noise_amp"] * seas  # noise enhancement

        # --- Derived variables ---
        # Eastern thermocline: tilt from wind
        # hE = hW + b*tau  (westerly wind deepens east, shallows west)
        hE = hW + p["b"] * tau

        # --- TE (Eastern Pacific SST) equation ---
        # dTE/dt = R*TE + gamma*hE - e*hE^3 + ... + noise
        # R = growth rate (Bjerknes feedback)
        # gamma*hE = linear thermocline upwelling feedback
        # -e*hE^3 = nonlinear saturation (stronger for deep hE → El Nino limitation)
        # This creates positive skew: warm events (deep hE) are capped, cold are not

        growth_E = p["R_E"] + cpl_seas
        damping_E = -p["c_E"]

        # Thermocline feedback with cubic saturation
        # quadratic term gives asymmetry: positive hE → El Nino → damped → weaker warm events
        # BUT El Ninos ARE stronger (positive TE skew in obs), need the opposite.
        # Obs shows positive TE skew = more extreme warm events.
        # This means cold events are more capped, warm events less.
        # Cubic term: -e*hE^3. For hE>0 (warm event), -e*hE^3 is negative → limits warming.
        # For hE<0, -e*hE^3 is positive → limits cooling. This is symmetric.
        # Need an asymmetric term: use hE^2 (quadratic).
        # For hE>0 (warm), +asym*hE^2 → extra warming (positive). For hE<0, +asym*hE^2 → also positive.
        # This shifts the whole distribution positive → can't create skew.
        # Better: use hE*|hE| which is asymmetric: for hE>0 it's hE^2, for hE<0 it's -hE^2.
        # OR: use a threshold: warm events limited by -e*hE^3 when hE>some_threshold.
        #
        # The cubic -e*hE^3 + gamma*hE gives overall shape: for small hE, linear; for large,
        # cubic dominates. Since positive hE (warm) has cubic damping, it limits El Nino.
        # But observations show El Ninos ARE stronger! So the cubic alone gives wrong skew.
        #
        # Solution: additive noise creates the skew through multiplicative noise
        # OR: a different functional form. Use -e_n * hE^2 * hW for asymmetry.
        # When hE>0 and hW<0 (discharged, El Nino mature), the nonlinear term is
        # -e_n * hE^2 * hW > 0 → reinforces warming. When hW>0 and hE<0 (charged, La Nina),
        # -e_n * hE^2 * hW < 0 → reinforces cooling but less.
        #
        # Actually, the skew comes naturally from multiplicative/state-dependent noise
        # plus the cubic saturation: the cubic limits WARM events less than cold ones
        # if the noise pushes harder in warm direction, OR if we use an asymmetric
        # saturation. Let's try: gamma*hE + asym*hE^2 - e_n*hE^3.
        # For positive hE: gamma*hE + asym*hE^2 - e_n*hE^3
        # For negative hE: gamma*hE + asym*hE^2 - e_n*hE^3 = gamma*hE + asym*|hE|^2 + e_n*|hE|^3
        # The quadratic always adds positive (warming), so it pushes warm events stronger.
        # This creates positive skew!

        thermo_E = p["g_E"] * hE
        thermo_asym_E = p.get("g_asym", 0.0) * hE**2  # always >= 0 → warm bias → positive TE skew
        thermo_nl_E = -p["e_n"] * hE**3

        # Advection by zonal current
        # Obs shows corr(TE,u) ~ -0.05, small negative
        # u>0 (eastward/westerly current) brings warm pool east → TE should warm
        # But obs shows slight negative correlation → counterintuitive
        # Possibly: increased u is part of the current that drains warm pool
        # Let's keep small for now
        adv_E = -p.get("adv_E", 0.03) * u

        # Cross from CP SST
        cross_E = p["cross_CE"] * TC

        # Bjerknes multiplicative: TE itself amplified by tau (wind)
        mbj_E = p.get("mbj_E", 0.0) * TE * tau

        dTE_dt = ((growth_E + damping_E) * TE + thermo_E + thermo_asym_E
                  + thermo_nl_E + adv_E + cross_E + mbj_E)

        # --- TC (Central Pacific SST) equation ---
        # Similar to TE but:
        # - weaker thermocline coupling
        # - local wind effect stronger
        # - influenced by TE through atmosphere
        growth_C = p["R_C"] + p.get("s_cpl_C_share", 0.4) * cpl_seas
        # CP is more local, less growth from Bjerknes

        thermo_C = p["g_C"] * hW
        thermo_nl_C = -p["e_n_C"] * hW**3

        # Wind local effect: westerly wind warms CP directly
        wind_C = p["wind_C"] * tau

        # Advection
        adv_C = -p.get("adv_C", 0.05) * u

        # Cross from EP
        cross_C = p["cross_EC"] * TE

        dTC_dt = ((growth_C - p["c_C"]) * TC + thermo_C + thermo_nl_C
                  + wind_C + adv_C + cross_C)

        # --- hW (Western thermocline) equation ---
        # dhW/dt = -r*hW - alpha*tau (+ nonlinear damping)
        # Westerly wind (tau>0) → Ekman pumping → shallower western thermocline → discharge
        # The recharge process: during La Nina, enhanced trades pile up warm water
        recharge = -p["r_h"] * hW
        discharge = -p["alpha"] * tau

        # Asymmetric discharge: El Nino discharge may be faster than La Nina recharge
        asym_h = p.get("r_asym_h", 0.0) * hW * np.abs(hW)

        dhW_dt = recharge + discharge + asym_h

        # --- u (Zonal current) equation ---
        # Fast response to wind forcing
        # du/dt = -lambda_u * u + kappa_u * tau (+ thermocline gradient)
        # u is in the central Pacific box
        relax_u = -p["lambda_u"] * u
        wind_u = p["kappa_u"] * tau

        # Thermocline pressure gradient: east-west tilt drives current
        # hE - hW = b*tau → this IS the tilt already proportional to tau
        # But we could also include a direct dependence on hE
        pg_u = p.get("kappa_uh", 0.0) * hE

        du_dt = relax_u + wind_u + pg_u

        # --- tau (Wind) equation ---
        # dtau/dt = -lambda_tau * tau + beta_E * TE + beta_C * TC (+ nonlinear damping)
        # Atmospheric Gill-type response to SST
        relax_tau = -p["lambda_tau"] * tau
        atmos_E = p["beta_E"] * TE
        atmos_C = p["beta_C"] * TC
        nl_tau = -p.get("tau_nl", 0.0) * tau * np.abs(tau)

        dtau_dt = relax_tau + atmos_E + atmos_C + nl_tau

        # --- Deterministic drift ---
        drift = np.array([dTC_dt, dTE_dt, dhW_dt, du_dt, dtau_dt])

        # --- Stochastic forcing ---
        noise = rng.standard_normal((5, M))

        # Correlate TE noise with TC noise (common atmospheric forcing)
        r_n = p.get("noise_corr", 0.4)
        noise[1] = r_n * noise[0] + np.sqrt(max(0, 1 - r_n**2)) * noise[1]

        sigma = np.array([p["sigma_TC"], p["sigma_TE"], p["sigma_hW"],
                          p["sigma_u"], p["sigma_tau"]])[:, None]

        stoch = sigma * noise * ns_seas * sqdt

        # Multiplicative noise on SST: noise amplitude ∝ |state|
        # This creates fatter tails and can produce skew
        if p.get("mult_TC", 0) > 0:
            stoch[0] += p["mult_TC"] * np.abs(TC) * rng.standard_normal(M) * sqdt
        if p.get("mult_TE", 0) > 0:
            stoch[1] += p["mult_TE"] * np.abs(TE) * rng.standard_normal(M) * sqdt

        # --- Euler-Maruyama ---
        s = np.array([TC, TE, hW, u, tau])
        s_new = s + drift * dt_nd + stoch

        # --- Redimensionalize ---
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
        total = burn_in + n_months
        n_steps = int(total / dt) + 1
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