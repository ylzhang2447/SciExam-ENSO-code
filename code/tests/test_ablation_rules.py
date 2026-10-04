import numpy as np

from sciexam.ablation import rules as R
from sciexam.ablation.refit import bases


def sc(stat, phys, pred):
    return dict(statistics=stat, physics=phys, predictivity=pred, composite=0.3 * stat + 0.3 * phys + 0.4 * pred)


def test_screen_thresholds():
    o = sc(0.5, 0.5, 0.3)
    assert R.passes(sc(0.46, 0.5, 0.3), o)            # statistics at 92%
    assert not R.passes(sc(0.44, 0.5, 0.3), o)        # statistics at 88%
    assert R.passes(sc(0.5, 0.5, 0.0), sc(0.5, 0.5, 0.0))   # zero original component


def test_vote_secondary_rule():
    o = sc(0.5, 0.5, 0.3)
    lm = dict(sc(0.5, 0.5, 0.3), candidate="a", role="vote representative", family="linear+multiplicative")
    na = dict(sc(0.47, 0.47, 0.28), candidate="b", role="competing reduction", family="nonlinear+additive")
    row = R.vote_row("x", "X", o, [lm, na])
    assert row["vote"] == "linear+multiplicative" and row["lm_qualifies"] and not row["na_qualifies"]


def test_fable_basis_roundtrip():
    b = bases.load("fable51")
    p = {"A_%s_%s" % (v, w): 0.1 * (i - j) for i, v in enumerate(b.VARS) for j, w in enumerate(b.VARS)}
    p.update(sat_TE=0.35, sat_hW=0.4, q_TC=0.0, n_TC=0.0, qw_TC=0.0, q_TE=0.1, n_TE=0.0, q_hW=0.0, n_hW=0.0,
             q_TE_s=0.5, bu_c=0.2, bu_s=0.0)
    q = b.params_from_theta(p, b.theta_from_params(p))
    assert all(np.isclose(q[k], p[k]) for k in p)
