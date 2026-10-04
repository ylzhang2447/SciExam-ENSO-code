"""Stochastic conceptual model of ENSO diversity.

Five-variable recharge oscillator with a Central-Pacific branch:

    TC   central Pacific SST anomaly        (Nino4)      [degC]
    TE   eastern Pacific SST anomaly        (Nino3)      [degC]
    hW   western Pacific thermocline anom                [m]
    u    central Pacific zonal current anom              [m/s]
    tau  western Pacific 850 hPa zonal wind anom         [m/s]

Internally everything is non-dimensional (nondim_scales.json) with a time unit
of 2 months; `step` takes and returns dimensional state and dt in months.

See model_card.md for the equations and the mechanisms they stand for.
"""
import numpy as np

T_SCALE = 7.5      # degC
H_SCALE = 150.0    # m
U_SCALE = 1.5      # m/s
TAU_SCALE = 5.0    # m/s
T_UNIT = 2.0       # months per non-dimensional time unit

_DEFAULTS = dict(
    # --- ocean adjustment (Jin 1997 recharge) ---
    r=0.25,          # thermocline relaxation rate
    alpha=0.30,      # wind -> zonal-mean heat content discharge
    beta_h=0.55,     # wind -> east-west thermocline tilt
    beta_hc=0.25,    # wind -> central Pacific thermocline
    # --- eastern Pacific SST ---
    c_E=1.10,        # damping
    gamma_E=0.75,    # thermocline feedback
    s_E=0.30,        # seasonal modulation amplitude of EP growth
    phi_E=8.5,       # calendar month of strongest EP growth
    q_E=0.30,        # quadratic (warm-favouring) nonlinearity
    e_E=0.80,        # cubic saturation
    a_EC=0.15,       # advection of CP anomaly into the east
    sig_E=0.055,     # additive SST noise
    # --- central Pacific SST ---
    c_C=1.05,        # damping
    gamma_C=0.30,    # (weaker) thermocline feedback
    a_uC=0.55,       # zonal advective feedback (u * mean dT/dx)
    s_C=0.18,        # seasonal modulation of CP growth
    phi_C=10.0,
    q_C=-0.20,       # quadratic, opposite sign to the east
    e_C=0.60,
    sig_C=0.055,
    # --- zonal current ---
    r_u=1.6,         # relaxation of u toward the wind-driven value
    mu_u=0.85,       # wind -> current gain
    lam_uh=-0.25,    # thermocline tilt contribution to u
    sig_u=0.06,
    # --- wind ---
    r_tau=2.0,       # relaxation rate (decorrelation ~1 month)
    b_C=1.10,        # CP SST -> wind coupling
    b_E=0.55,        # EP SST -> wind coupling
    sig_tau=0.42,    # background wind noise
    m_w=0.9,         # multiplicative (state-dependent) WWB amplification
    s_tau=0.25,      # seasonal modulation of wind noise
    phi_tau=1.0,     # calendar month of strongest wind noise
    clamp=6.0,       # hard safety bound on non-dimensional state
)


class ENSOModel:
    def __init__(self, params=None):
        p = dict(_DEFAULTS)
        if params:
            p.update({k: v for k, v in params.items() if k in _DEFAULTS})
        self.p = p
        self.scales = np.array([T_SCALE, T_SCALE, H_SCALE, U_SCALE,
                                TAU_SCALE]).reshape(5, 1)

    # ------------------------------------------------------------------ core
    def _drift_diff(self, x, t):
        """Non-dimensional drift and diffusion (per non-dim time unit)."""
        p = self.p
        TC, TE, h, u, tau = x[0], x[1], x[2], x[3], x[4]
        w = 2 * np.pi / 12.0

        # seasonal modulation of the coupled growth rates and of the wind noise
        sE = 1.0 + p["s_E"] * np.cos(w * (t - p["phi_E"]))
        sC = 1.0 + p["s_C"] * np.cos(w * (t - p["phi_C"]))
        sT = 1.0 + p["s_tau"] * np.cos(w * (t - p["phi_tau"]))

        hE = h + p["beta_h"] * tau          # eastern thermocline (Jin 2.1)
        hC = h + p["beta_hc"] * tau         # central Pacific thermocline

        dTE = (-p["c_E"] * TE + sE * p["gamma_E"] * hE
               + p["q_E"] * TE * TE - p["e_E"] * TE ** 3
               + p["a_EC"] * TC)
        dTC = (-p["c_C"] * TC + sC * (p["gamma_C"] * hC + p["a_uC"] * u)
               + p["q_C"] * TC * TC - p["e_C"] * TC ** 3)
        dh = -p["r"] * h - p["alpha"] * tau
        du = -p["r_u"] * (u - p["mu_u"] * tau - p["lam_uh"] * h)
        dtau = -p["r_tau"] * (tau - p["b_C"] * TC - p["b_E"] * TE)

        # state-dependent wind forcing: bursts are stronger when the warm pool
        # and central Pacific are warm (and in boreal winter/spring)
        amp = sT * (1.0 + p["m_w"] * np.tanh(2.0 * TC))
        g_tau = p["sig_tau"] * np.maximum(amp, 0.15) * np.sqrt(p["r_tau"])

        drift = np.stack([dTC, dTE, dh, du, dtau])
        diff = np.stack([np.full_like(TC, p["sig_C"]),
                         np.full_like(TE, p["sig_E"]),
                         np.zeros_like(h),
                         np.full_like(u, p["sig_u"]),
                         g_tau])
        return drift, diff

    # ------------------------------------------------------------- interface
    def step(self, state, dt, t, rng):
        """Euler-Maruyama step. state (5, M) dimensional, dt in months."""
        s = np.asarray(state, dtype=float)
        squeeze = s.ndim == 1
        if squeeze:
            s = s.reshape(5, 1)
        x = s / self.scales
        dtn = dt / T_UNIT                      # non-dimensional time step
        drift, diff = self._drift_diff(x, t)
        dW = rng.standard_normal(x.shape)
        x = x + drift * dtn + diff * np.sqrt(dtn) * dW
        c = self.p["clamp"]
        x = np.clip(x, -c, c)
        x = np.where(np.isfinite(x), x, 0.0)
        out = x * self.scales
        return out[:, 0] if squeeze else out

    # --- convenience wrappers (not used by the grader, handy for diagnostics)
    def simulate(self, n_months, dt=0.05, seed=0, state0=None, t0=0.0):
        rng = np.random.default_rng(seed)
        s = np.zeros((5, 1)) if state0 is None else np.array(state0,
                                                            float).reshape(5, -1)
        nsub = max(1, int(round(1.0 / dt)))
        out = [s.copy()]
        t = t0
        for _ in range(n_months):
            for _ in range(nsub):
                s = self.step(s, 1.0 / nsub, t, rng)
                t += 1.0 / nsub
            out.append(s.copy())
        return np.stack(out, axis=-1)

    def forecast(self, state0, leads, n_members=200, dt=0.05, seed=0, t0=0.0):
        rng = np.random.default_rng(seed)
        s = np.tile(np.asarray(state0, float).reshape(5, 1), (1, n_members))
        nsub = max(1, int(round(1.0 / dt)))
        out, t, m = {}, t0, 0
        for L in range(1, max(leads) + 1):
            for _ in range(nsub):
                s = self.step(s, 1.0 / nsub, t, rng)
                t += 1.0 / nsub
            if L in leads:
                out[L] = s.mean(axis=1)
        return out
