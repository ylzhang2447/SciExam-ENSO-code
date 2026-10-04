import io

import numpy as np
import pytest

from sciexam.grader import integrate as I
from sciexam.grader import metrics as M
from sciexam.grader import protocol as P
from sciexam.grader.score import Aligned, LocalModel, grade


class Linear:
    """A small seasonal linear model used only in tests."""

    def step(self, state, dt, t, rng):
        a = -0.1 + 0.05 * np.cos(2 * np.pi * t / 12.0)
        noise = 0.1 * np.sqrt(dt) * rng.standard_normal(np.shape(state))
        return state + a * state * dt + noise


def test_protocol_roundtrip_and_rng_carry():
    buf = io.BytesIO()
    g = np.random.default_rng(3)
    P.send(buf, {"kind": "step", "rng_state": g.bit_generator.state}, np.arange(10.0).reshape(5, 2))
    buf.seek(0)
    head, payload = P.recv(buf)
    arr = P.array(head, payload)
    assert arr.shape == (5, 2) and arr[4, 1] == 9.0
    g2 = P.generator_from_state(head["rng_state"])
    assert g.standard_normal() == g2.standard_normal()


def test_month_shift_equals_rolled_labels():
    x = np.random.default_rng(0).standard_normal(120)
    a = M.seasonal_variance(x, 1)
    b = M.seasonal_variance(np.roll(x, 1), 0)
    assert np.allclose(a, b)


def test_free_run_offset_matches_aligned_wrapper():
    m = Linear()
    a = I.free_run(m, n_years=2, seed=1, t_offset=-1.0)
    rng = np.random.default_rng(1)
    b = LocalModel(m).free_run(n_years=2, dt_months=0.1, rng=rng, t_offset=-1.0)
    assert all(np.array_equal(a[v], b[v]) for v in I.VARS)
    s = Aligned(m, -1.0)
    st = np.zeros((5, 1))
    assert np.array_equal(s.step(st + 1, 0.1, 3.0, np.random.default_rng(0)),
                          m.step(st + 1, 0.1, 2.0, np.random.default_rng(0)))


def test_fractional_offset_is_rejected():
    with pytest.raises(ValueError, match="whole number of months"):
        grade(LocalModel(Linear()), None, s=0.5)
