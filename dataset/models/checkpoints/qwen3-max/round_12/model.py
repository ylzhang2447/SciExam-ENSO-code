import numpy as np
import json

class ENSOModel:
    def __init__(self, params: dict):
        """Initialize the ENSO model with parameters."""
        self.params = params

        # Load non-dimensionalization scales
        scales_file = __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "nondim_scales.json")
        with open(scales_file, 'r') as f:
            scales = json.load(f)

        self.T_scale = scales["T_scale_degC"]
        self.h_scale = scales["h_scale_m"]
        self.u_scale = scales["u_scale_m_per_s"]
        self.tau_scale = scales["tau_scale_m_per_s"]
        self.t_scale = scales["t_scale_months"]

    def step(self, state, dt, t, rng):
        """
        Advance the state by one stochastic step of size dt.
        state : np.ndarray shape (5, M) -- the five variables above (rows), M ensemble members (columns), in DIMENSIONAL units.
        dt    : time increment in MONTHS.
        t     : current time in MONTHS since the run start (for seasonal terms).
        rng   : a numpy Generator; draw all stochastic terms from it.
        Returns the advanced state, same shape (5, M), in dimensional units.
        """
        # Extract state variables (dimensional units)
        TC = state[0]  # Central Pacific SST anomaly [degC]
        TE = state[1]  # Eastern Pacific SST anomaly [degC]
        hW = state[2]  # Western Pacific thermocline anomaly [m]
        u = state[3]   # Central Pacific zonal current anomaly [m/s]
        tau = state[4] # WP zonal wind anomaly [m/s]

        # Convert to non-dimensional units for computation
        TC_nd = TC / self.T_scale
        TE_nd = TE / self.T_scale
        hW_nd = hW / self.h_scale
        u_nd = u / self.u_scale
        tau_nd = tau / self.tau_scale

        # Get parameters
        p_TC = self.params["TC"]
        p_TE = self.params["TE"]
        p_hW = self.params["hW"]
        p_u = self.params["u"]
        p_tau = self.params["tau"]
        p_nonlin = self.params["nonlinear"]
        p_seas = self.params["seasonal"]

        # Seasonal cycle (time in months, seasonal period = 12 months)
        season_phase = (t % 12) / 12.0 * 2 * np.pi
        seasonal_TC = 1.0 + p_seas["amp_TC"] * np.cos(season_phase - p_seas["phase_TC"] * np.pi / 6.0)
        seasonal_TE = 1.0 + p_seas["amp_TE"] * np.cos(season_phase - p_seas["phase_TE"] * np.pi / 6.0)

        # Nonlinear terms for asymmetry
        # Cubic term for general nonlinearity, quadratic term for TE asymmetry
        TC_nonlin = p_nonlin["T_nonlin"] * TC_nd**3
        TE_nonlin = p_nonlin["T_nonlin"] * TE_nd**3 + p_nonlin.get("TE_quad", 0.0) * TE_nd**2
        hW_nonlin = p_nonlin["h_nonlin"] * hW_nd**3

        # Linear feedback coefficients for thermocline discharge
        gamma_TC = p_TC.get("gamma", 0.1)
        gamma_TE = p_TE.get("gamma", 0.15)

        # Drift terms (deterministic tendencies in non-dimensional units per non-dim time)
        # SST equations - thermocline-forced growth with damping and nonlinearity
        dTC_dt_nd = (p_TC["alpha"] * hW_nd - p_TC["beta"] * TC_nd - p_TC["mu"] * TC_nonlin) * seasonal_TC
        dTE_dt_nd = (p_TE["alpha"] * hW_nd - p_TE["beta"] * TE_nd - p_TE["mu"] * TE_nonlin) * seasonal_TE

        # Thermocline equation - forced by zonal current and discharged by SST anomalies
        # Positive u (eastward current) deepens western thermocline
        # Positive SST anomalies (El Nino) discharge the western thermocline
        dhW_dt_nd = p_hW["epsilon"] * u_nd - p_hW["kappa"] * (gamma_TC * TC_nd + gamma_TE * TE_nd) - p_hW["xi"] * hW_nd - p_nonlin["h_nonlin"] * hW_nonlin

        # Zonal current equation - wind-driven with damping
        du_dt_nd = p_u["zeta"] * tau_nd - p_u["eta"] * u_nd

        # Wind stress equation - AR(1) process with Bjerknes feedback from SST
        # Positive SST anomalies strengthen westerly wind anomalies (positive feedback)
        bjerknes_TC = p_tau.get("bjerknes_TC", 0.1) * TC_nd
        bjerknes_TE = p_tau.get("bjerknes_TE", 0.15) * TE_nd
        dtau_dt_nd = -p_tau["rho_tau"] * tau_nd + bjerknes_TC + bjerknes_TE

        # Convert drifts to dimensional units per month
        # Non-dim time unit = t_scale months, so divide by t_scale
        dTC_dt_dim = dTC_dt_nd * self.T_scale / self.t_scale
        dTE_dt_dim = dTE_dt_nd * self.T_scale / self.t_scale
        dhW_dt_dim = dhW_dt_nd * self.h_scale / self.t_scale
        du_dt_dim = du_dt_nd * self.u_scale / self.t_scale
        dtau_dt_dim = dtau_dt_nd * self.tau_scale / self.t_scale

        # Stochastic forcing (Euler-Maruyama scheme)
        # dt is in months, so scale noise appropriately
        sqrt_dt = np.sqrt(dt)
        sigma_tau_dim = p_tau["sigma_tau"] * self.tau_scale / np.sqrt(self.t_scale)  # dimensional noise amplitude

        # Generate random noise for tau
        dW_tau = rng.normal(0, 1, size=tau.shape) * sqrt_dt

        # Update state using Euler-Maruyama
        TC_new = TC + dTC_dt_dim * dt
        TE_new = TE + dTE_dt_dim * dt
        hW_new = hW + dhW_dt_dim * dt
        u_new = u + du_dt_dim * dt
        tau_new = tau + dtau_dt_dim * dt + sigma_tau_dim * dW_tau

        # Assemble new state
        new_state = np.vstack([TC_new, TE_new, hW_new, u_new, tau_new])

        return new_state