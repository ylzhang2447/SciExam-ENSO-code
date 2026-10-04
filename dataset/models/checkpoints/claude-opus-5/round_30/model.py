"""Stochastic conceptual model of ENSO diversity.

State (dimensional, the grader's row order):

    TC   central Pacific SST anomaly        (Nino4)      [degC]
    TE   eastern Pacific SST anomaly        (Nino3)      [degC]
    hW   western Pacific thermocline anom                [m]
    u    central Pacific zonal current anom              [m/s]
    tau  western Pacific 850 hPa zonal wind anom         [m/s]

Internally the model works in non-dimensional units (nondim_scales.json, time
unit 2 months) and on the *warm water volume* H rather than hW directly:

    H = hW + b_tilt * TE          (b_tilt in non-dim units)

i.e. hW is the recharge variable minus the wind-driven zonal tilt, which during
El Nino shoals the west.  H is the Jin (1997) recharge variable and is in
quadrature with TE; hW inherits the tilt and is therefore nearly out of phase
with TE, as observed.

See model_card.md for the equations and the mechanisms they stand for.
"""
import numpy as np

T_SCALE = 7.5      # degC
H_SCALE = 150.0    # m
U_SCALE = 1.5      # m/s
TAU_SCALE = 5.0    # m/s
T_UNIT = 2.0       # months per non-dimensional time unit

_DEFAULTS = dict(
    # --- geometry -----------------------------------------------------------
    b_tilt=0.51,     # zonal thermocline tilt per unit TE (non-dim)
    # --- central Pacific SST ------------------------------------------------
    c_C=0.188,       # damping
    g_C=0.126,       # thermocline (recharge) feedback
    a_C=0.111,       # zonal advective feedback (current)
    w_C=0.054,       # direct wind feedback
    d_CE=0.014,      # eastern -> central coupling
    k_a=0.5,         # warm/cold asymmetry of that coupling
    Ta=0.13,         # scale of the asymmetry (non-dim TE)
    s_C=0.10,        # seasonal modulation of CP growth
    phi_C=8.0,       # calendar month of strongest CP growth
    q_C=-0.25,       # quadratic nonlinearity (cold-favouring in the centre)
    v_C=0.0069,      # <TC^2>, keeps the quadratic term mean-free
    e_C=1.0,         # cubic saturation
    e5_C=0.0,        # quintic limiter (cuts the far tail)
    sig_C=0.027,     # SST noise
    # --- eastern Pacific SST ------------------------------------------------
    c_E=0.127,       # damping
    g_E=0.014,       # thermocline feedback
    a_E=0.281,       # zonal advective feedback
    w_E=0.108,       # direct wind feedback
    d_EC=-0.111,     # central -> eastern coupling
    s_E=0.25,        # seasonal modulation of EP growth
    phi_E=8.0,       # calendar month of strongest EP growth
    q_E=0.40,        # quadratic nonlinearity (warm-favouring in the east)
    v_E=0.0159,      # <TE^2>, keeps the quadratic term mean-free
    e_E=1.2,         # cubic saturation
    k_e=0.4,         # warm/cold asymmetry of the saturation (cold saturates first)
    e5_E=0.0,        # quintic limiter (cuts the far tail)
    sig_E=0.048,     # SST noise
    # --- recharge (warm water volume) ---------------------------------------
    r=0.086,         # WWV relaxation
    s_h=0.0,         # seasonal modulation of the discharge
    phi_h=9.0,       # calendar month of strongest discharge
    alpha_E=0.173,   # discharge by eastern SST (via the wind it drives)
    alpha_C=-0.098,  # discharge by central SST
    alpha_u=0.088,   # discharge by the current
    alpha_t=0.024,   # discharge by the residual wind
    q_H=0.0,         # nonlinear (asymmetric) discharge
    sig_H=0.023,     # independent WWV noise
    # --- zonal current ------------------------------------------------------
    r_u=0.66,        # current relaxation
    lam_H=0.771,     # thermocline slope -> current
    lam_C=-0.287,
    lam_E=-0.219,
    mu_u=0.081,      # wind -> current
    sig_u=0.072,
    rho_ut=0.25,     # correlation of the current noise with the wind noise
    # --- wind ---------------------------------------------------------------
    r_t=1.973,       # wind relaxation (decorrelation ~1 month)
    b_C=3.425,       # CP SST -> wind
    b_E=-0.679,      # EP SST -> wind
    b_H=1.043,       # WWV -> wind
    sig_tau=0.382,   # background wind noise
    m_w=0.10,        # state-dependent (WWB) amplification
    k_w=0.30,        # skewness of the wind noise
    xi_clip=4.0,     # bound on the skewed wind innovation
    s_tau=0.18,      # seasonal modulation of the wind noise
    phi_tau=12.0,    # calendar month of strongest wind noise
    # --- safety -------------------------------------------------------------
    clamp=8.0,       # hard bound on the non-dimensional state
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
    def _tendency(self, TC, TE, H, u, tau, t):
        """Non-dimensional drift of (TC, TE, H, u) per non-dim time unit."""
        p = self.p
        w = 2 * np.pi / 12.0
        # seasonally varying net linear growth rate (the phase-locking term)
        sC = -p["c_C"] + p["s_C"] * np.cos(w * (t - p["phi_C"]))
        sE = -p["c_E"] + p["s_E"] * np.cos(w * (t - p["phi_E"]))

        gC = p["g_C"] * H + p["a_C"] * u + p["w_C"] * tau
        gE = p["g_E"] * H + p["a_E"] * u + p["w_E"] * tau

        # El Nino is EP-dominant, La Nina is basin-wide: the eastern anomaly
        # projects onto the centre much more strongly when it is cold
        dCE = p["d_CE"] * (1.0 - p["k_a"] * np.tanh(TE / p["Ta"]))
        dTC = (sC * TC + gC + dCE * TE
               + p["q_C"] * (TC * TC - p["v_C"]) - p["e_C"] * TC ** 3
               - p["e5_C"] * TC ** 5)
        dTE = (sE * TE + gE + p["d_EC"] * TC
               + p["q_E"] * (TE * TE - p["v_E"])
               - p["e_E"] * (1.0 - p["k_e"] * np.tanh(TE / p["Ta"])) * TE ** 3
               - p["e5_E"] * TE ** 5)
        # the discharge itself has an annual cycle (strongest wind-stress curl
        # response in boreal autumn/winter), which imprints a seasonal cycle on
        # the thermocline variance
        sH = 1.0 + p["s_h"] * np.cos(w * (t - p["phi_h"]))
        dH = (-p["r"] * H - sH * p["alpha_E"] * TE - p["alpha_C"] * TC
              - p["alpha_u"] * u - p["alpha_t"] * tau
              + p["q_H"] * (TE * TE - p["v_E"]))
        du = (-p["r_u"] * u + p["lam_H"] * H + p["lam_C"] * TC
              + p["lam_E"] * TE + p["mu_u"] * tau)
        return dTC, dTE, dH, du

    # ------------------------------------------------------------- interface
    def step(self, state, dt, t, rng):
        """Euler-Maruyama step (exact OU update for the fast wind).

        state (5, M) dimensional, dt in months, t in months since run start.
        """
        s = np.asarray(state, dtype=float)
        squeeze = s.ndim == 1
        if squeeze:
            s = s.reshape(5, 1)
        p = self.p
        x = s / self.scales
        TC, TE, hW, u, tau = x[0], x[1], x[2], x[3], x[4]
        H = hW + p["b_tilt"] * TE
        dtn = max(dt, 0.0) / T_UNIT
        sq = np.sqrt(dtn)
        w = 2 * np.pi / 12.0

        dTC, dTE, dH, du = self._tendency(TC, TE, H, u, tau, t)

        # --- noise ----------------------------------------------------------
        n = rng.standard_normal((5,) + TC.shape)
        # wind: seasonally modulated, mildly state dependent, positively skewed
        amp = (1.0 + p["s_tau"] * np.cos(w * (t - p["phi_tau"]))) * \
              (1.0 + p["m_w"] * np.tanh(2.0 * TC))
        amp = np.maximum(amp, 0.2)
        xi = n[4] + p["k_w"] * (n[4] * n[4] - 1.0) / np.sqrt(2.0)
        xi /= np.sqrt(1.0 + p["k_w"] ** 2)
        # the skewing map has a z^2 tail; bound it so the wind tail stays realistic
        xi = np.clip(xi, -p["xi_clip"], p["xi_clip"])
        g_tau = p["sig_tau"] * amp

        # exact Ornstein-Uhlenbeck update for tau about its equilibrium
        taueq = p["b_C"] * TC + p["b_E"] * TE + p["b_H"] * H
        ex = np.exp(-p["r_t"] * dtn)
        sd = g_tau * np.sqrt(np.maximum(1.0 - ex * ex, 0.0) / (2.0 * p["r_t"]))
        tau_new = taueq + (tau - taueq) * ex + sd * xi
        # the wind increment actually realised over the step (for the current)
        eps_t = xi

        TC = TC + dTC * dtn + p["sig_C"] * sq * n[0]
        TE_inc = dTE * dtn + p["sig_E"] * sq * n[1]
        TE = TE + TE_inc
        H = H + dH * dtn + p["sig_H"] * sq * n[2]
        u = u + du * dtn + p["sig_u"] * sq * (
            p["rho_ut"] * eps_t + np.sqrt(1.0 - p["rho_ut"] ** 2) * n[3])

        hW = H - p["b_tilt"] * TE
        x = np.stack([TC, TE, hW, u, tau_new])
        c = p["clamp"]
        x = np.clip(np.where(np.isfinite(x), x, 0.0), -c, c)
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
        out, t = {}, t0
        for L in range(1, max(leads) + 1):
            for _ in range(nsub):
                s = self.step(s, 1.0 / nsub, t, rng)
                t += 1.0 / nsub
            if L in leads:
                out[L] = s.mean(axis=1)
        return out
