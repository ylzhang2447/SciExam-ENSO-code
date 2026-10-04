"""Drift basis of the Claude Fable 5.1 final model, in code coordinates, rates per month.

The model's drift uses two-month time units, so every feature carries a factor of 1/2. Only
drift terms present in the parameters are refit. Noise and saturation scales stay fixed. The
products q_TE * q_TE_s and A_u_hW * bu_{c,s} are fitted as independent linear coefficients and
converted back to the model's parameterization afterwards.
"""
import numpy as np

SCALES = np.array([7.5, 7.5, 150.0, 1.5, 5.0])
VARS = ["TC", "TE", "hW", "u", "tau"]
FIXED = ["sat_TE", "sat_hW"]   # noise parameters are excluded by construction


def to_code_state(x_dim):
    return np.asarray(x_dim, float) / SCALES[:, None]


def features(z, t, params):
    z = np.asarray(z, float)
    angle = 2 * np.pi * (np.asarray(t) - 0.5) / 12
    c, s = np.cos(angle), np.sin(angle)
    harmonics = {"c": c, "s": s, "c2": np.cos(2 * angle), "s2": np.sin(2 * angle)}
    tc, te, hw = z[:3]
    F = {i: {"A_%s_%s" % (v, w): z[j] / 2 for j, w in enumerate(VARS)}
         for i, v in enumerate(VARS)}
    for i, v in [(0, "TC"), (1, "TE"), (2, "hW")]:
        for suffix, wave in harmonics.items():
            key = "g_%s_%s" % (v, suffix)
            if key in params:
                F[i][key] = wave * z[i] / 2
        for suffix, wave in [("c", c), ("s", s)]:
            key = "b_%s_%s" % (v, suffix)
            if key in params:
                F[i][key] = wave * hw / 2
        key = "c_" + v
        if key in params:
            F[i][key] = np.ones_like(tc) / 2
    F[0].update(q_TC=tc**2 / 2, n_TC=tc**3 / 2, qw_TC=tc**2 * (tc > 0) / 2)
    F[1].update(q_TE=te**2 / (1 + (te / params["sat_TE"])**2) / 2, n_TE=te**3 / 2)
    F[2].update(q_hW=te**2 / (1 + (te / params["sat_hW"])**2) / 2, n_hW=hw**3 / 2)
    for i, v in [(0, "TC"), (1, "TE")]:
        if "q_%s_s" % v in params:
            F[i]["q_%s_season" % v] = F[i]["q_" + v] * s
    for suffix, wave in [("c", c), ("s", s)]:
        if "bu_" + suffix in params:
            F[3]["u_hW_" + suffix] = hw * wave / 2
    for i, key, value in [(1, "k_TE_TEhW", te * hw / 2),
                          (1, "n5_TE", te**5 / 2), (2, "qd_hW", te * np.abs(te) / 2)]:
        if key in params:
            F[i][key] = value
    return F


def theta_from_params(p):
    F = features(np.zeros((5, 1)), 0.0, p)
    th = {i: {} for i in F}
    for i in F:
        for key in F[i]:
            if key.endswith("_season"):
                base = key[:-len("_season")]
                value = p[base] * p[base + "_s"]
            elif key.startswith("u_hW_"):
                value = p["A_u_hW"] * p["bu_" + key[-1]]
            else:
                value = p[key]
            th[i][key] = float(value)
    return th


def params_from_theta(p, theta):
    q = dict(p)
    for values in theta.values():
        for key, value in values.items():
            if not key.endswith("_season") and not key.startswith("u_hW_"):
                q[key] = float(value)
    for values in theta.values():
        for key, value in values.items():
            if key.endswith("_season"):
                base = key[:-len("_season")]
                target, divisor = base + "_s", q[base]
            elif key.startswith("u_hW_"):
                target, divisor = "bu_" + key[-1], q["A_u_hW"]
            else:
                continue
            if abs(divisor) < 1e-12:
                if abs(value) > 1e-12:
                    raise ValueError("cannot map a nonzero product coefficient with a zero base: " + key)
                q[target] = 0.0
            else:
                q[target] = float(value / divisor)
    return q
