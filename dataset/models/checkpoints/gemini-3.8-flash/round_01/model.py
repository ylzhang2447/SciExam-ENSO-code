import json
import numpy as np

class ENSOModel:
    """
    Baseline stochastic conceptual model of ENSO.
    State vector:
      row 0: TC  [deg C]          central-Pacific SST anomaly
      row 1: TE  [deg C]          eastern-Pacific SST anomaly
      row 2: hW  [m]              western-Pacific thermocline anomaly
      row 3: u   [m/s]            central-Pacific zonal current anomaly
      row 4: tau [m/s]            WP zonal wind anomaly
    """
    def __init__(self, params: dict):
        self.params = params
        # Linear damping rates (per month)
        self.d_TC = params.get("d_TC", 0.15)
        self.d_TE = params.get("d_TE", 0.15)
        self.d_hW = params.get("d_hW", 0.10)
        self.d_u  = params.get("d_u", 0.50)
        self.d_tau= params.get("d_tau", 0.80)
        
        # Coupling parameters
        self.gamma_TC = params.get("gamma_TC", 0.02)  # thermocline influence on TC
        self.gamma_TE = params.get("gamma_TE", 0.04)  # thermocline influence on TE
        self.b_tau    = params.get("b_tau", 1.5)      # wind response to TC/TE
        self.r_hW     = params.get("r_hW", 2.0)       # discharge by wind/SST
        self.c_u      = params.get("c_u", 0.05)       # wind driving current
        
        # Noise amplitudes (per sqrt(month))
        self.sigma_TC = params.get("sigma_TC", 0.10)
        self.sigma_TE = params.get("sigma_TE", 0.15)
        self.sigma_hW = params.get("sigma_hW", 1.0)
        self.sigma_u  = params.get("sigma_u", 0.05)
        self.sigma_tau= params.get("sigma_tau", 1.2)

    def step(self, state, dt, t, rng):
        """
        Advance state by stochastic step dt (months).
        state: np.ndarray shape (5, M) in dimensional units.
        t: current time in months.
        rng: np.random.Generator.
        """
        state = np.asarray(state, dtype=np.float64)
        TC, TE, hW, u, tau = state[0], state[1], state[2], state[3], state[4]
        
        # Deterministic tendencies
        dTC = -self.d_TC * TC + self.gamma_TC * hW + 0.5 * u
        dTE = -self.d_TE * TE + self.gamma_TE * hW + 0.2 * TC
        dhW = -self.d_hW * hW - self.r_hW * (0.6 * TC + 0.4 * TE)
        du  = -self.d_u  * u  + self.c_u * tau
        dtau= -self.d_tau* tau + self.b_tau * (0.7 * TC + 0.3 * TE)
        
        # Noise
        sqrtdt = np.sqrt(dt)
        M = state.shape[1]
        noise = rng.standard_normal((5, M))
        
        new_state = np.empty_like(state)
        new_state[0] = TC + dTC * dt + self.sigma_TC * sqrtdt * noise[0]
        new_state[1] = TE + dTE * dt + self.sigma_TE * sqrtdt * noise[1]
        new_state[2] = hW + dhW * dt + self.sigma_hW * sqrtdt * noise[2]
        new_state[3] = u  + du  * dt + self.sigma_u  * sqrtdt * noise[3]
        new_state[4] = tau+ dtau* dt + self.sigma_tau* sqrtdt * noise[4]
        
        return new_state
