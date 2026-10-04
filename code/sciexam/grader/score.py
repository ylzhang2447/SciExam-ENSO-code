"""Scoring of one submission: hard gate, statistics, physics, predictivity, composite.

The submission is reached only through ``step`` (and a whole free run, which is built from
``step``). ``model`` below is either a ``RemoteModel`` (the submission runs in a separate
worker container) or a ``LocalModel`` (in process, for debugging only).

Calendar alignment: with offset ``s`` the submission's ``step`` receives ``t + s``. Physics
and predictivity are run at ``t + s``. Statistics are computed from the free run started at
``t = 0`` with its month labels shifted by ``-s`` months, so ``s`` must be a whole number of
months.
"""
import time

import numpy as np

from . import integrate as I
from . import physics, predictivity
from . import statistics as ST

WEIGHTS = dict(statistics=0.3, physics=0.3, predictivity=0.4)
GATE_YEARS = 50


class SubmissionError(RuntimeError):
    """The submission's own code raised."""


class WorkerError(RuntimeError):
    """The worker failed in a way that is not a verdict about the model (never scored)."""


class LocalModel:
    """An in-process submission behind the same interface as ``RemoteModel``."""

    def __init__(self, model):
        self.m = model

    def step(self, state, dt, t, rng):
        return self.m.step(state, dt, t, rng)

    def free_run(self, n_years, dt_months, rng, t_offset=0.0):
        return I.free_run(self.m, n_years=n_years, dt_months=dt_months, rng=rng, t_offset=t_offset)


class Aligned:
    """The submission seen through calendar offset ``s``: ``step`` receives ``t + s``."""

    def __init__(self, model, s):
        self.m, self.s = model, float(s)

    def step(self, state, dt, t, rng):
        return self.m.step(state, dt, t + self.s, rng)


def composite(stat, phys, pred):
    return WEIGHTS["statistics"] * stat + WEIGHTS["physics"] * phys + WEIGHTS["predictivity"] * pred


def _free_run(model, n_years, seed, t_offset):
    rng = np.random.default_rng(seed)
    return model.free_run(n_years=n_years, dt_months=ST.STAT_DT, rng=rng, t_offset=t_offset)


def hard_gate(model, s):
    """A 50-year free run (seed 0) must stay finite and ``step`` must not raise."""
    try:
        sim = _free_run(model, GATE_YEARS, 0, s)
    except WorkerError:
        raise
    except Exception as e:
        return False, "step raised: %s" % str(e)[-1500:]
    for k in I.VARS:
        a = np.asarray(sim[k], float)
        if a.size == 0 or not np.all(np.isfinite(a)):
            return False, "%s not finite" % k
    return True, "pass"


def grade(model, obs, s=0.0, log=None):
    """Score ``model`` against ``obs`` under calendar offset ``s``. Returns a result dict."""
    say = log or (lambda m: None)
    s = float(s)
    if abs(s - round(s)) > 1e-12:
        raise ValueError("calendar offset must be a whole number of months, got %r" % s)
    out = dict(status=None, calendar_offset=s, seconds={})
    t0 = time.time()
    ok, why = hard_gate(model, s)
    out["hard_gate"] = why
    out["seconds"]["hard_gate"] = round(time.time() - t0, 1)
    if not ok:
        out["status"] = "hard_gate_failed"
        return out
    say("hard gate passed")

    t1 = time.time()
    sim, shift = _free_run(model, ST.total_years(), ST.STAT_SEED, 0.0), int(round(-s))
    TE, TC = np.asarray(sim["TE"], float), np.asarray(sim["TC"], float)
    out["free_run_finite"] = bool(np.all(np.isfinite(TE)) and np.all(np.isfinite(TC)))
    curves = ST.curves_from_run(TE, TC, obs, shift)
    stat, groups, panels, events = ST.score(curves)
    out.update(statistics=stat, groups=groups, panels=panels, event_scores=events,
               event_counts=ST.event_summary(curves), bivariate=curves["bivariate"])
    out["seconds"]["statistics"] = round(time.time() - t1, 1)
    say("statistics %.4f" % stat)

    shifted = model if s == 0 else Aligned(model, s)
    t2 = time.time()
    phys, pdet = physics.score_da(shifted, obs)
    out.update(physics=phys, physics_detail=pdet)
    out["seconds"]["physics"] = round(time.time() - t2, 1)
    say("physics %.4f" % phys)

    t3 = time.time()
    pred, qdet = predictivity.score_predictivity(shifted, obs)
    out.update(predictivity=pred, predictivity_detail=qdet)
    out["seconds"]["predictivity"] = round(time.time() - t3, 1)
    say("predictivity %.4f" % pred)

    out["composite"] = composite(stat, phys, pred)
    out["seconds"]["total"] = round(time.time() - t0, 1)
    out["status"] = "scored"
    return out
