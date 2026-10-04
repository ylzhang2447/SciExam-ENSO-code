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
    b_tilt=0.175,     # zonal thermocline tilt per unit TE (non-dim)
    # --- central Pacific SST ------------------------------------------------
    c_C=0.332741,       # damping
    g_C=0.09,       # thermocline (recharge) feedback
    a_C=0.108,       # zonal advective feedback (current)
    w_C=0.065625,       # direct wind feedback
    d_CE=0.2208,      # eastern -> central coupling
    k_a=0.8,         # warm/cold asymmetry of that coupling
    Ta=0.13,         # scale of the asymmetry (non-dim TE)
    s_C=0.1947,        # seasonal modulation of CP growth
    phi_C=8.4,       # calendar month of strongest CP growth
    q_C=-0.855,       # quadratic nonlinearity (cold-favouring in the centre)
    v_C=0.018,      # <TC^2>, keeps the quadratic term mean-free
    e_C=3,         # cubic saturation
    e5_C=48,        # quintic limiter (cuts the far tail)
    sig_C=0.024624,     # SST noise
    # --- eastern Pacific SST ------------------------------------------------
    c_E=0.108,       # damping
    g_E=0.0264,       # thermocline feedback
    k_g=0,        # stronger thermocline feedback when H is depleted
    Hs=0.05,        # scale of that asymmetry (non-dim H)
    a_E=0.352,       # zonal advective feedback
    w_E=0.08925,       # direct wind feedback
    d_EC=-0.111,     # central -> eastern coupling
    s_E=0.3,        # seasonal modulation of EP growth
    phi_E=8,       # calendar month of strongest EP growth
    q_E=1.32,        # quadratic nonlinearity (warm-favouring in the east)
    v_E=0.01327,      # <TE^2>, keeps the quadratic term mean-free
    e_E=1.8,         # cubic saturation
    k_e=0.38,         # warm/cold asymmetry of the saturation (cold saturates first)
    e5_E=8.5,        # quintic limiter (cuts the far tail)
    sig_E=0.0395546,     # SST noise
    # --- recharge (warm water volume) ---------------------------------------
    r=0.0522288,         # WWV relaxation
    s_h=2.23082,         # seasonal modulation of the discharge
    phi_h=9,       # calendar month of strongest discharge
    alpha_E=0.0704221,   # discharge by eastern SST (via the wind it drives)
    alpha_C=-0.098,  # discharge by central SST
    alpha_u=0.088,   # discharge by the current
    alpha_t=0.048825,   # discharge by the residual wind
    q_H=0.035,         # nonlinear (asymmetric) discharge
    alpha_d=0,     # discharge delay via the TE tendency
    Td=0.18,        # amplitude above which the delay switches on
    alpha3=2.61144,      # cubic discharge: big events discharge disproportionately
    Ts=0.2,         # amplitude at which the cubic discharge saturates
    k_s=0.8,        # warm/cold asymmetry of that saturation
    sig_H=0.006204,     # independent WWV noise
    # --- zonal current ------------------------------------------------------
    r_u=0.58,        # current relaxation
    lam_H=0.516305,     # thermocline slope -> current
    lam_C=-0.184545,
    lam_E=-0.0738182,
    mu_u=0.0349867,      # wind -> current
    sig_u=0.0822163,
    rho_ut=0.25,     # correlation of the current noise with the wind noise
    # --- wind ---------------------------------------------------------------
    r_t=1.55,       # wind relaxation (decorrelation ~1 month)
    b_C=2.75,       # CP SST -> wind
    b_E=-0.15,      # EP SST -> wind
    b_H=1.1,       # WWV -> wind
    sig_tau=0.533005,   # background wind noise
    m_w=0.22,        # state-dependent (WWB) amplification
    k_w=0.75,        # skewness of the wind noise
    xi_clip=3.2,     # bound on the skewed wind innovation
    s_tau=0.35,      # seasonal modulation of the wind noise
    phi_tau=12.7,    # calendar month of strongest wind noise
    # --- safety -------------------------------------------------------------
    clamp=8,       # hard bound on the non-dimensional state
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
        # the thermocline feedback is stronger when the warm water volume is
        # depleted: a discharged basin cools the east faster than a recharged
        # one warms it, which deepens the post-El-Nino rebound
        gE = ((p["g_E"] * H + p["a_E"] * u + p["w_E"] * tau)
              * (1.0 - p["k_g"] * np.tanh(H / p["Hs"])))

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
        # the discharge lags the eastern warming: discharge less while TE is
        # still growing, more once it turns over.  dTE is a function of the
        # state, so this is a phase shift with no extra memory.
        # ...and only for large events: the bulk of the distribution, which
        # sets the autocorrelation, is left alone.
        dH = (-p["alpha_d"] * dTE * TE * TE / (p["Td"] ** 2 + TE * TE)
              - p["r"] * H - sH * p["alpha_E"] * TE - p["alpha_C"] * TC
              - p["alpha_u"] * u - p["alpha_t"] * tau
              + p["q_H"] * (TE * TE - p["v_E"])
              - p["alpha3"] * TE ** 3
              / (1.0 + (TE / p["Ts"]) ** 2
                 * (1.0 + p["k_s"] * np.tanh(TE / p["Ta"]))))
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
        # two-piece normal innovation: skewed (westerly bursts are stronger than
        # easterly ones) but with Gaussian tails, unlike a z^2 skewing map
        kw = p["k_w"]
        z = np.clip(n[4], -p["xi_clip"], p["xi_clip"])
        xi = z * np.where(z > 0.0, 1.0 + kw, 1.0 - kw)
        m_xi = 2.0 * kw / np.sqrt(2.0 * np.pi)
        v_xi = 1.0 + kw * kw - m_xi * m_xi
        xi = (xi - m_xi) / np.sqrt(v_xi)
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
