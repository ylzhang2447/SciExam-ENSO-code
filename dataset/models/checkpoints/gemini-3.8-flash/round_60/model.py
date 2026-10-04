import json
import numpy as np

class ENSOModel:
    """
    Stochastic conceptual model of ENSO diversity in non-dimensional coordinates.
    State vector (in physical units):
      row 0: TC  [deg C]          central-Pacific SST anomaly
      row 1: TE  [deg C]          eastern-Pacific SST anomaly
      row 2: hW  [m]              western-Pacific thermocline anomaly
      row 3: u   [m/s]            central-Pacific zonal current anomaly
      row 4: tau [m/s]            WP zonal wind anomaly
    """
    def __init__(self, params: dict):
        self.params = params
        
        # Characteristic scaling constants (nondim_scales.json)
        self.S_TC = 7.5       # deg C
        self.S_TE = 7.5       # deg C
        self.S_hW = 150.0     # m
        self.S_u  = 1.5       # m/s
        self.S_tau= 5.0       # m/s
        self.S_t  = 2.0       # months per nondim time unit
        
        # Central Pacific SST (TC) parameters
        self.d_TC = params.get("d_TC", 0.036)
        self.gamma_Cu = params.get("gamma_Cu", 0.228)
        self.gamma_Ch = params.get("gamma_Ch", 0.0896)
        self.gamma_CT = params.get("gamma_CT", 0.065)
        self.beta_TC = params.get("beta_TC", 0.94)
        self.alpha_C = params.get("alpha_C", 1.57)
        self.tc_offset = params.get("tc_offset", 0.0)
        
        # Eastern Pacific SST (TE) parameters
        self.d_TE = params.get("d_TE", 0.387)
        self.gamma_E = params.get("gamma_E", 0.072)
        self.b_h = params.get("b_h", 0.998)
        self.alpha_E = params.get("alpha_E", 9.3)
        self.h_offset = params.get("h_offset", 0.0363)
        self.beta_TE = params.get("beta_TE", 3.665)
        self.gamma_Eu = params.get("gamma_Eu", 0.146)
        self.gamma_ET = params.get("gamma_ET", 0.0175)
        
        # Thermocline (hW) parameters
        self.d_hW = params.get("d_hW", 0.1201)
        self.r_tau = params.get("r_tau", 0.042)
        self.r_E = params.get("r_E", 0.0574)
        self.r_u = params.get("r_u", 0.15)
        
        # Zonal current (u) parameters
        self.d_u = params.get("d_u", 0.52)
        self.c_tau = params.get("c_tau", 0.0525)
        self.c_h = params.get("c_h", 0.66)
        
        # Wind stress proxy (tau) parameters
        self.d_tau = params.get("d_tau", 1.06)
        self.b_TC = params.get("b_TC", 3.85)
        self.b_TE = params.get("b_TE", -1.27)
        
        # Seasonality parameters
        self.mu_seas = params.get("mu_seas", 0.7908)
        self.phi_seas = params.get("phi_seas", 9.656)
        
        # Noise amplitudes (per sqrt(nondim time))
        self.sigma_TC = params.get("sigma_TC", 0.030)
        self.sigma_TE = params.get("sigma_TE", 0.047)
        self.sigma_hW = params.get("sigma_hW", 0.026)
        self.sigma_u  = params.get("sigma_u", 0.060)
        self.sigma_tau= params.get("sigma_tau", 0.34)
        self.alpha_w  = params.get("alpha_w", 1.31)

    def step(self, state, dt, t, rng):
        """
        Advance state by stochastic step dt (months).
        state: np.ndarray shape (5, M) in dimensional units.
        t: current time in months since run start.
        rng: np.random.Generator.
        """
        state = np.asarray(state, dtype=np.float64)
        
        # 1. Non-dimensionalize state variables
        TC = state[0] / self.S_TC
        TE = state[1] / self.S_TE
        hW = state[2] / self.S_hW
        u  = state[3] / self.S_u
        tau= state[4] / self.S_tau
        
        # Non-dimensional time increment
        dt_nd = dt / self.S_t
        sqrtdt_nd = np.sqrt(dt_nd)
        
        # 2. Seasonal modulation factor
        theta = 2.0 * np.pi * (t - self.phi_seas) / 12.0
        F_seas = 1.0 + self.mu_seas * np.cos(theta)
        
        # 3. Deterministic tendencies in nondim units (dX/dt_nd)
        # Western wind stress
        f_wind = self.b_TC * TC + self.b_TE * TE
        dtau = -self.d_tau * tau + F_seas * f_wind
        
        # Mixed-layer zonal current (driven by pressure gradient / thermocline & wind)
        du = -self.d_u * u + self.c_tau * tau + self.c_h * hW
        
        # Thermocline adjustment (recharge / discharge)
        dhW = -self.d_hW * hW - self.r_tau * tau - self.r_E * TE - self.r_u * u
        
        # Eastern Pacific SST (thermocline upwelling & advection)
        hE = hW + self.b_h * tau
        # Nonlinear convex upwelling feedback
        T_sub = self.gamma_E * (hE + self.alpha_E * (np.maximum(0.0, hE)**2 - self.h_offset))
        dTE = -self.d_TE * TE - self.beta_TE * (TE**3) + F_seas * T_sub + self.gamma_Eu * u + self.gamma_ET * TC
        
        # Central Pacific SST (zonal advection & thermocline)
        dTC = -self.d_TC * TC - self.beta_TC * (TC**3) - self.alpha_C * (np.maximum(0.0, TC)**2 - self.tc_offset) + self.gamma_Cu * u + self.gamma_Ch * hW + self.gamma_CT * TE
        
        # 4. Stochastic noise (Euler-Maruyama)
        M = state.shape[1]
        noise = rng.standard_normal((5, M))
        
        # State-dependent westerly wind burst enhancement
        wwb_factor = 1.0 + self.alpha_w * np.maximum(0.0, TC)
        
        # 5. Advance in nondimensional state
        new_TC = TC + dTC * dt_nd + self.sigma_TC * sqrtdt_nd * noise[0]
        new_TE = TE + dTE * dt_nd + self.sigma_TE * sqrtdt_nd * noise[1]
        new_hW = hW + dhW * dt_nd + self.sigma_hW * sqrtdt_nd * noise[2]
        new_u  = u  + du  * dt_nd + self.sigma_u  * sqrtdt_nd * noise[3]
        new_tau= tau+ dtau* dt_nd + (self.sigma_tau * wwb_factor) * sqrtdt_nd * noise[4]
        
        # 6. Dimensionalize back to physical units
        new_state = np.empty_like(state)
        new_state[0] = new_TC * self.S_TC
        new_state[1] = new_TE * self.S_TE
        new_state[2] = new_hW * self.S_hW
        new_state[3] = new_u  * self.S_u
        new_state[4] = new_tau* self.S_tau
        
        return new_state
