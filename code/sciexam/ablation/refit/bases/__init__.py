"""Drift bases of the agent models that the refit supports (one module per model).

Each module describes one agent model in the coordinates its own code integrates in, so that
the drift is linear in the refit coefficients::

    d z_i / dt = sum_k theta[i][k] * phi_{i,k}(z, t)       (t in months, z the code state)

and exposes ``VARS``, ``to_code_state(x)``, ``features(z, t, params)``,
``theta_from_params(params)`` and ``params_from_theta(params, theta)``.
"""
import importlib


def load(name):
    return importlib.import_module("%s.%s" % (__name__, name))
