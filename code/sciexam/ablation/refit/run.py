"""Teacher simulation and least-squares refit of one simplified model.

Runs the original agent model (untrusted code), so ``sciexam ablation --refit`` starts it in a
container without network. Usage inside the container::

    python -m sciexam.ablation.refit.run --original /orig --arm fable51 \
        --candidate S3_affine_periodic_drift --out /out

Step 1 (teacher simulation): the original ``model.py`` with its own ``params.json`` is integrated
from the zero state exactly as the grader integrates it, ``step(state, dt, t, rng)`` with dt in
months and t = 0, dt, 2 dt, and so on. ``chains`` independent copies advance together as the
columns of the (5, chains) state. The first ``burn`` years of every column are discarded and every
later sub-step is kept.

Step 2 (refit): for every equation i the target is the one-step increment per month of the code
state, y_i = (z_i(t + dt) - z_i(t)) / dt, and the regressors are the basis functions of the
model. Ordinary least squares gives the coefficients, with the removed terms fixed at zero.
Everything else in ``params.json`` is copied unchanged.

Step 3: a 300-year free run of the refit model must stay finite.

Writes ``params.json`` and ``fit.json`` to ``--out``.
"""
import argparse
import json
import os
import sys
import time

import numpy as np

from ...grader import integrate as I
from ...grader.worker import load_submission
from . import bases
from .registry import REFITS


def simulate(model, years, burn, chains, dt, seed):
    rng = np.random.default_rng(seed)
    sub = int(round(1.0 / dt))
    n_burn = int(round(burn * 12 * sub))
    n_keep = int(round(years / chains * 12 * sub))
    state = np.zeros((5, chains))
    t = 0.0
    for _ in range(n_burn):
        state = np.asarray(model.step(state, dt, t, rng), float)
        t += dt
    traj = np.empty((n_keep + 1, 5, chains))
    tt = np.empty(n_keep + 1)
    traj[0] = state
    tt[0] = t
    for p in range(1, n_keep + 1):
        state = np.asarray(model.step(state, dt, t, rng), float)
        t += dt
        traj[p] = state
        tt[p] = t
    if not np.all(np.isfinite(traj)):
        raise RuntimeError("non-finite state in the teacher simulation")
    return traj, tt


def fit(basis, p0, traj, t, dt, knockout):
    T1, _, M = traj.shape
    zz = basis.to_code_state(np.transpose(traj, (1, 0, 2)).reshape(5, T1 * M)).reshape(5, T1, M)
    z0 = zz[:, :-1, :].reshape(5, -1)
    z1 = zz[:, 1:, :].reshape(5, -1)
    tt = np.repeat(t[:-1], M)
    y = (z1 - z0) / dt
    F = basis.features(z0, tt, p0)
    th0 = basis.theta_from_params(p0)
    ko = set(tuple(k) for k in knockout)
    unknown = ko - {(i, k) for i in F for k in F[i]}
    if unknown:
        raise ValueError("unknown terms: %s" % sorted(unknown))
    theta, summary = {}, []
    for i in range(5):
        names = [k for k in F[i] if (i, k) not in ko]
        if names:
            X = np.column_stack([F[i][k] for k in names])
            coef = np.linalg.lstsq(X, y[i], rcond=None)[0]
        else:
            coef = np.zeros(0)
        theta[i] = {k: float(c) for k, c in zip(names, coef)}
        for k in F[i]:
            if (i, k) in ko:
                theta[i][k] = 0.0
            summary.append(dict(eq=i, var=basis.VARS[i], term=k, fit=theta[i][k],
                                original=th0[i].get(k, 0.0), removed=(i, k) in ko))
    return basis.params_from_theta(p0, theta), summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--original", required=True, help="folder of the original model (model.py, params.json)")
    ap.add_argument("--arm", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    spec = REFITS[(a.arm, a.candidate)]
    basis = bases.load(spec["basis"])
    cwd = os.getcwd()
    model = load_submission(a.original)
    os.chdir(cwd)
    p0 = json.load(open(os.path.join(a.original, "params.json")))
    te = spec["teacher"]
    t0 = time.time()
    traj, t = simulate(model, te["years"], te["burn"], te["chains"], te["dt"], te["seed"])
    t_sim = time.time() - t0
    p_new, summary = fit(basis, p0, traj, t, te["dt"], spec["knockout"])
    t_fit = time.time() - t0 - t_sim
    refit_model = type(model)(p_new)
    run = I.free_run(refit_model, n_years=300, seed=0)
    finite = bool(all(np.all(np.isfinite(v)) for v in run.values()))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "params.json"), "w") as fh:
        json.dump(p_new, fh, indent=1)
    rec = dict(arm=a.arm, candidate=a.candidate, basis=spec["basis"], teacher=te,
               knockout=[list(k) for k in spec["knockout"]], coefficients=summary,
               stable_300yr=finite, seconds=dict(simulation=round(t_sim, 1), fit=round(t_fit, 1),
                                                 total=round(time.time() - t0, 1)))
    with open(os.path.join(a.out, "fit.json"), "w") as fh:
        json.dump(rec, fh, indent=1)
    print(json.dumps(dict(stable_300yr=finite, seconds=rec["seconds"])), file=sys.stderr)
    return 0 if finite else 1


if __name__ == "__main__":
    sys.exit(main())
