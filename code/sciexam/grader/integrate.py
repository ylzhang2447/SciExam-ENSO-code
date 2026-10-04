"""Integrations built on a submission's ``step(state, dt, t, rng)``.

The grader calls nothing else on a submission. Every experiment (free run, ensemble Kalman
smoother, ensemble forecast) is written here in terms of ``step``, so the same equations and
parameters are tested in all three dimensions.

Time convention: model time ``t`` is in months. A state at model time ``t`` belongs to
calendar month ``t mod 12`` with 1 meaning January. Monthly values are one-month centred
running means of the sub-steps, sampled at ``t = 1, 2, ...``.
"""
import numpy as np

VARS = ["TC", "TE", "hW", "u", "tau"]
DT_MONTHS = 0.1                                  # 10 sub-steps per month
SCALES = np.array([7.5, 7.5, 150.0, 1.5, 5.0])   # [TC, TE, hW, u, tau] in physical units


def movmean_full(traj, k):
    """Centred running mean over ``k`` rows, every row kept, window shrunk at the edges.

    For even ``k`` the window of row ``i`` is ``[i - k/2, i + k/2 - 1]``.
    """
    n = traj.shape[0]
    c = np.concatenate([np.zeros((1, traj.shape[1])), np.cumsum(traj, axis=0)])
    hl = k // 2
    idx = np.arange(n)
    a = np.clip(idx - hl, 0, n)
    b = np.clip(idx + (k - hl), 0, n)
    return (c[b] - c[a]) / (b - a)[:, None]


def substeps(dt_months):
    n = max(1, round(1.0 / dt_months))
    return n, 1.0 / n


def free_run(model, n_years, seed=0, dt_months=DT_MONTHS, rng=None, t_offset=0.0):
    """Free stochastic run from the zero state.

    Returns a dict of monthly 1-D arrays (length ``n_years * 12``, physical units) keyed by
    ``VARS``. ``t_offset`` is added to the time passed to ``step`` (calendar alignment).
    """
    rng = np.random.default_rng(seed) if rng is None else rng
    n_months = int(n_years * 12)
    sub, dt = substeps(dt_months)
    state = np.zeros((5, 1))
    t = 0.0
    traj = np.empty((n_months * sub + 1, 5))
    traj[0] = state[:, 0]
    for p in range(1, n_months * sub + 1):
        state = np.asarray(model.step(state, dt, t + t_offset, rng), float)
        t += dt
        traj[p] = state[:, 0]
    out = movmean_full(traj, sub)[sub::sub]          # t = 1, 2, ..., n_months
    return {v: out[:, i] for i, v in enumerate(VARS)}


def enks_reconstruct(model, truth, obs_vars, n_ens=500, obs_noise_frac=0.05,
                     spinup_months=24, seed=0, dt_months=DT_MONTHS, lag=3, sub_month=0.2):
    """Ensemble Kalman smoother driven by the submission's ``step``.

    Perturbed observations, transform in ensemble space, and every stacked state of the
    lag window is updated by each analysis, so month ``k`` is estimated from observations
    up to month ``k + lag``. Integration of the next month continues from the updated
    current state. Initial spread is ``0.1 * SCALES`` and the observation error standard
    deviation is ``obs_noise_frac * SCALES``.

    Returns (correlations of the hidden variables, reconstruction (5, T), spread (5, T)).
    """
    rng = np.random.default_rng(seed)
    obs_idx = [VARS.index(v) for v in obs_vars]
    hidden_idx = [i for i in range(5) if i not in obs_idx]
    r_std = obs_noise_frac * SCALES[obs_idx]
    Y = np.array([np.asarray(truth[v], float) for v in VARS])
    T = Y.shape[1]
    sub, dt = substeps(dt_months)

    A = Y[:, 0:1] + (0.1 * SCALES)[:, None] * rng.standard_normal((5, n_ens))
    per_month = max(1, int(round(1.0 / sub_month))) if sub_month else 1
    stride = max(1, sub // per_month)
    window = []
    recon = np.empty((5, T))
    spread = np.empty((5, T))
    w = 0
    t = 0.0
    eye = np.eye(n_ens)
    for k in range(T):
        blocks = []
        for j in range(sub):
            A = np.asarray(model.step(A, dt, t, rng), float)
            t += dt
            if (j + 1) % stride == 0:
                blocks.append(A.copy())
        if not blocks:
            blocks = [A.copy()]
        window.append(blocks)
        HA = blocks[-1][obs_idx]                     # observation time = month end
        E = r_std[:, None] * rng.standard_normal((len(obs_idx), n_ens))
        Dp = (Y[obs_idx, k][:, None] + E) - HA
        S = HA - HA.mean(1, keepdims=True)
        C = S @ S.T + E @ E.T
        X = eye + S.T @ np.linalg.solve(C, Dp)
        window = [[b @ X for b in blk] for blk in window]
        A = window[-1][-1].copy()
        if len(window) > lag:
            blk = window.pop(0)
            recon[:, w] = blk[-1].mean(1)
            spread[:, w] = blk[-1].std(1)
            w += 1
    while window:
        blk = window.pop(0)
        recon[:, w] = blk[-1].mean(1)
        spread[:, w] = blk[-1].std(1)
        w += 1

    s = slice(spinup_months, None)
    corr = {}
    for i in hidden_idx:
        a, b = recon[i, s], Y[i, s]
        corr[VARS[i]] = float(np.corrcoef(a, b)[0, 1]) if np.std(a) > 0 else 0.0
    return corr, recon, spread


def ensemble_forecast(model, init_state, lead_months, n_members=50, seed=0,
                      dt_months=DT_MONTHS, start_t=0.0):
    """Ensemble forecast from one observed state.

    ``start_t`` is the model time of the initial state, i.e. the calendar month number
    (1 to 12) of the initialisation month. The run continues half a month past the last
    lead so that the centred monthly mean of the last lead is complete. Returns a dict of
    arrays shaped (n_members, lead_months).
    """
    rng = np.random.default_rng(seed)
    sub, dt = substeps(dt_months)
    state = np.repeat(np.asarray(init_state, float).reshape(5, 1), n_members, axis=1)
    n_ens = state.shape[1]
    t = float(start_t)
    npts = lead_months * sub + sub // 2 + 1
    traj = np.empty((npts, 5, n_ens))
    traj[0] = state
    for p in range(1, npts):
        state = np.asarray(model.step(state, dt, t, rng), float)
        t += dt
        traj[p] = state
    flat = traj.reshape(npts, -1)
    out = movmean_full(flat, sub)[sub::sub][:lead_months].reshape(lead_months, 5, n_ens)
    return {v: out[:, i, :].T for i, v in enumerate(VARS)}
