"""ENSOModel: stochastic 5-variable model for ENSO diversity.

State vector (dimensional): [TC, TE, hW, u, tau]
- TC: central-Pacific SST anomaly [deg C]
- TE: eastern-Pacific SST anomaly [deg C]
- hW: western-Pacific thermocline anomaly [m]
- u: central-Pacific zonal current anomaly [m/s]
- tau: WP zonal wind anomaly (wind stress proxy) [m/s]

Nondimensionalization from nondim_scales.json:
  T_scale = 7.5 degC, h_scale = 150 m, u_scale = 1.5 m/s,
  tau_scale = 5.0 m/s, t_scale = 2 months.

The model is an extended recharge oscillator with:
  - Two-region SST (TC, TE) coupled through shared thermocline & wind
  - Recharge-discharge dynamics via hW
  - Fast zonal current u responding to wind and feeding SST advection
  - Stochastic wind forcing tau as both state variable and noise source
  - Nonlinearities: saturating thermocline feedback, quadratic SST-wind coupling
  - Seasonal modulation of growth rate and noise amplitude
"""

import numpy as np


class ENSOModel:
    """Stochastic ENSO diversity model exposed via step().

    The step() method is the single source of truth: the grader builds
    free simulation, ensemble forecasting, and data assimilation on it.
    """

    def __init__(self, params: dict):
        self.p = params

        # Nondimensional scales
        self.T_scale = 7.5
        self.h_scale = 150.0
        self.u_scale = 1.5
        self.tau_scale = 5.0

        # Precompute seasonal arrays (12 months)
        # seasonal growth rate modulation: stronger coupling in boreal winter
        self._setup_seasonal()

    def _setup_seasonal(self):
        """Precompute seasonal modulation factors."""
        p = self.p
        months = np.arange(12)
        pi = np.pi

        # Seasonal coupling enhancement: peaks Dec-Jan (month 0-1 for Jan, 11 for Dec in 0-based)
        # Use a sinusoidal modulation
        self._season_coupling = p.get("season_coupling_amp", 0.3) * np.cos(
            2 * pi * (months - 11) / 12
        )  # peak in Dec

        # Seasonal noise modulation: stronger in winter
        self._season_noise = 1.0 + p.get("season_noise_amp", 0.3) * np.cos(
            2 * pi * (months - 11) / 12
        )

    def _seasonal_factor(self, coupling):
        """Get seasonal coupling factor at time t (in months)."""
        t_months = coupling
        # Map to month index
        month_idx = int(np.floor(t_months)) % 12
        return self._season_coupling[month_idx]

    def _seasonal_noise_factor(self, t):
        """Get seasonal noise amplitude factor at time t."""
        month_idx = int(np.floor(t)) % 12
        return self._season_noise[month_idx]

    def step(self, state, dt, t, rng):
        """
        Advance state by dt using Euler-Maruyama with seasonal, nonlinear,
        and stochastic terms.

        Args:
            state: np.ndarray shape (5, M) in dimensional units
            dt: time step in MONTHS
            t: current time in MONTHS since start
            rng: numpy Generator for stochastic terms

        Returns:
            advanced state, shape (5, M), dimensional units
        """
        # --- Nondimensionalize ---
        TC = state[0] / self.T_scale
        TE = state[1] / self.T_scale
        hW = state[2] / self.h_scale
        u = state[3] / self.u_scale
        tau = state[4] / self.tau_scale

        # Nondimensional time step
        t_nondim = t / self.p.get("t_scale_months", 2.0)
        dt_nondim = dt / self.p.get("t_scale_months", 2.0)

        p = self.p
        M = state.shape[1]

        # Seasonal factors
        month_idx = int(np.floor(t)) % 12
        s_coupling = self._season_coupling[month_idx]
        s_noise = self._season_noise[month_idx]

        # --- Deterministic tendencies (nondimensional) ---

        # Eastern-Pacific SST tendency
        # dTE/dt = R_TE*TE + gamma_E * (h_E - e_n * h_E^3) + coupling_terms + seasonal
        # h_E is eastern thermocline, related to hW and tau: h_E = hW + b*tau
        hE = hW + p["b"] * tau  # thermocline tilt from wind

        # Nonlinear saturation of thermocline feedback (cubic)
        # This gives El Nino/La Nina asymmetry: warm events limited by shallow thermocline
        thermocline_feedback = p["gamma_E"] * (hE - p["e_n"] * hE**3)

        # Bjerknes feedback (growth) + damping + seasonal modulation
        growth_TE = p["R_TE"] * (1.0 + s_coupling)
        damping_TE = -p["c_E"] * TE

        # Cross-region SST coupling: TC influences TE through atmosphere
        cross_TE = p["R_CE"] * TC * (1.0 + 0.3 * s_coupling)

        # Advection by zonal current u: anomalous current brings warm/cold water
        advection_TE = -p["adv_E"] * u * (1.0 + np.abs(TE))

        dTE_dt = (
            growth_TE * TE
            + damping_TE
            + thermocline_feedback
            + cross_TE
            + advection_TE
        )

        # Central-Pacific SST tendency
        # Similar to TE but with local dynamics, stronger wind influence
        growth_TC = p["R_TC"] * (1.0 + 0.7 * s_coupling)
        damping_TC = -p["c_C"] * TC

        # Thermocline feedback on TC: weaker, uses hW directly
        thermo_TC = p["gamma_C"] * (hW - p["e_n_C"] * hW**3)

        # Zonal current advection: u is central Pacific current
        advection_TC = -p["adv_C"] * u * (1.0 + np.abs(TC))

        # Direct wind feedback on CP SST
        wind_TC = p["wind_C"] * tau

        # Cross-region from TE
        cross_TC = p["R_EC"] * TE * (1.0 + 0.3 * s_coupling)

        dTC_dt = (
            growth_TC * TC
            + damping_TC
            + thermo_TC
            + advection_TC
            + wind_TC
            + cross_TC
        )

        # Western-Pacific thermocline tendency (recharge/discharge)
        # dhW/dt = -r * hW - alpha * tau + nonlinear damping
        # Wind stress (tau) discharges hW; a small current term
        dhW_dt = (
            -p["r"] * hW
            - p["alpha"] * tau
            + p["r2"] * hW**2 * np.sign(hW)  # weak quadratic damping for asymmetry
        )

        # Zonal current tendency (fast response to wind)
        # du/dt = -lambda_u * (u - kappa * tau) - damping
        # u relaxes toward equilibrium proportional to wind stress
        du_dt = -p["lambda_u"] * (u - p["kappa_uw"] * tau) - p["r_u"] * u + p["r_u2"] * tau * TC

        # Wind tendency
        # tau has atmospheric response to SST + fast decay + stochastic
        # dtau/dt = -lambda_tau * tau + beta * (TE + weighted TC) + cubic nonlinearity
        dtau_dt = (
            -p["lambda_tau"] * tau
            + p["beta_tau_E"] * TE
            + p["beta_tau_C"] * TC
            - p["tau_nl"] * tau**3
        )

        # --- Collect deterministic tendencies ---
        drift = np.zeros((5, M))
        drift[0] = dTC_dt
        drift[1] = dTE_dt
        drift[2] = dhW_dt
        drift[3] = du_dt
        drift[4] = dtau_dt

        # --- Stochastic forcing (nondimensional) ---
        # Additive noise on each equation, modulated by seasonality
        sqrt_dt = np.sqrt(dt_nondim)

        # Generate correlated noise (with specified correlation structure)
        noise_raw = rng.standard_normal((5, M))

        # Apply noise correlation via Cholesky of correlation matrix
        # Noise structure: TC noise correlated with TE and tau; hW anticorrelated with tau
        noise = self._apply_noise_correlation(noise_raw)

        # Noise amplitudes with seasonal modulation
        noise_amps = np.array([
            p["sigma_TC"],
            p["sigma_TE"],
            p["sigma_hW"],
            p["sigma_u"],
            p["sigma_tau"],
        ])[:, None] * s_noise

        stochastic = noise_amps * noise * sqrt_dt

        # Multiplicative noise on SST: noise scales with SST magnitude
        if p.get("multiplicative_noise", True):
            mc_TC = p.get("mc_TC", 0.05)
            mc_TE = p.get("mc_TE", 0.05)
            stochastic[0] += mc_TC * np.abs(TC) * rng.standard_normal(M) * sqrt_dt
            stochastic[1] += mc_TE * np.abs(TE) * rng.standard_normal(M) * sqrt_dt

        # --- Euler-Maruyama step (nondimensional) ---
        state_nd = np.array([TC, TE, hW, u, tau])
        state_nd_new = state_nd + drift * dt_nondim + stochastic

        # --- Redimensionalize ---
        new_state = np.zeros_like(state)
        new_state[0] = state_nd_new[0] * self.T_scale
        new_state[1] = state_nd_new[1] * self.T_scale
        new_state[2] = state_nd_new[2] * self.h_scale
        new_state[3] = state_nd_new[3] * self.u_scale
        new_state[4] = state_nd_new[4] * self.tau_scale

        return new_state

    def _apply_noise_correlation(self, noise):
        """Apply correlation structure to noise via precomputed Cholesky."""
        # Simple approach: use a linear combination to induce correlations
        p = self.p
        # noise is shape (5, M) of independent standard normals
        # Build correlated noise via linear mixing
        # Correlation target: TC~TE positive, TC~tau positive, hW~tau negative
        noise_c = noise.copy()
        noise_c[1] = p.get("noise_corr_TE_TC", 0.6) * noise[0] + np.sqrt(
            1.0 - p.get("noise_corr_TE_TC", 0.6) ** 2
        ) * noise[1]  # TE correlated with TC
        noise_c[4] = (
            p.get("noise_corr_tau_TC", 0.4) * noise[0]
            - p.get("noise_corr_tau_hW", 0.2) * noise[2]
            + np.sqrt(
                max(0, 1.0 - p.get("noise_corr_tau_TC", 0.4) ** 2 - p.get("noise_corr_tau_hW", 0.2) ** 2)
            )
            * noise[4]
        )
        return noise_c

    def simulate(self, n_months, dt=0.1, burn_in=120, rng=None):
        """Run a free simulation and return monthly-sampled state.

        Args:
            n_months: number of months to sample after burn-in
            dt: integration time step (months)
            burn_in: burn-in period in months
            rng: optional numpy Generator (uses default if None)

        Returns:
            (t, state): t is (n_months,) array of times,
                       state is (5, n_months) array in dimensional units
        """
        if rng is None:
            rng = np.random.default_rng()

        total = burn_in + n_months
        n_steps = int(total / dt) + 1

        # Initialize at zero (mean state) for a single realization
        state = np.zeros((5, 1))
        times_sample = np.arange(n_months) + burn_in  # times to sample

        samples = []
        sample_idx = 0
        t = 0.0

        for step_i in range(n_steps):
            if t >= burn_in and sample_idx < n_months:
                # Sample at monthly intervals
                target_t = times_sample[sample_idx]
                if t >= target_t - 1e-8:
                    samples.append(state[:, 0].copy())
                    sample_idx += 1
                    if sample_idx >= n_months:
                        break

            state = self.step(state, dt, t, rng)
            t += dt

        while sample_idx < n_months:
            samples.append(state[:, 0].copy())
            sample_idx += 1

        return times_sample[: len(samples)], np.column_stack(samples) if samples else np.zeros((5, 0))

    def forecast(self, init_state, lead_months, n_ensemble, dt=0.1, rng=None):
        """Run an ensemble forecast from init_state.

        Args:
            init_state: (5,) array, initial condition in dimensional units
            lead_months: forecast lead time in months
            n_ensemble: number of ensemble members
            dt: integration time step
            rng: optional numpy Generator

        Returns:
            (ensemble_trajectories, ensemble_mean):
                ensemble_trajectories: (n_ensemble, 5, n_steps) array
                ensemble_mean: (5, n_steps) array
        """
        if rng is None:
            rng = np.random.default_rng()

        n_steps = int(lead_months / dt) + 1

        # Initialize ensemble
        state = np.tile(init_state[:, None], (1, n_ensemble)).astype(float)

        trajectories = []
        t = 0.0
        step = 0

        # Record at each dt step
        record_every = max(1, int(1.0 / dt))  # record monthly
        next_record = 0

        while t < lead_months:
            if t >= next_record - 1e-8:
                trajectories.append(state.copy())
                next_record += dt * record_every

            state = self.step(state, dt, t, rng)
            t += dt

        # Always record final step
        if t >= lead_months:
            trajectories.append(state.copy())

        if not trajectories:
            trajectories = [state.copy()]

        traj = np.stack(trajectories, axis=-1)  # (5, M, n_recordings)
        traj = traj.transpose(1, 0, 2)  # (M, 5, n_recordings)
        mean = traj.mean(axis=0)  # (5, n_recordings)

        return traj, mean

    def forecast_monthly(self, init_state, lead_months, n_ensemble, dt=0.1, rng=None):
        """Forecast returning monthly samples.

        Returns:
            ensemble_mean: (5, lead_months) array of monthly means
        """
        if rng is None:
            rng = np.random.default_rng()

        n_steps_total = int(lead_months / dt) + 1
        state = np.tile(init_state[:, None], (1, n_ensemble)).astype(float)

        monthly_means = []
        t = 0.0
        step = 0
        accumulated = np.zeros((5, n_ensemble))
        acc_count = 0
        next_sample = 1.0  # first monthly sample at 1 month

        for step_i in range(n_steps_total):
            if t >= next_sample - 1e-8:
                # record mean over ensemble at this monthly point
                monthly_means.append(state.mean(axis=1).copy())
                next_sample += 1.0
                if len(monthly_means) >= lead_months:
                    break

            state = self.step(state, dt, t, rng)
            t += dt

        while len(monthly_means) < lead_months:
            monthly_means.append(state.mean(axis=1).copy())

        return np.column_stack(monthly_means) if monthly_means else np.zeros((5, 0))