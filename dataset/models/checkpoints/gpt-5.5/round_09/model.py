"""Stochastic low-order ENSO diversity model.

The public interface is intentionally only ENSOModel.step.  State passed into and
out of step is dimensional; the tendency is evaluated internally in the
non-dimensional variables used for calibration.
"""

from __future__ import annotations

import numpy as np


class ENSOModel:
    def __init__(self, params: dict):
        self.params = dict(params)
        self.scales = np.asarray(
            [
                self.params.get("T_scale_degC", 7.5),
                self.params.get("T_scale_degC", 7.5),
                self.params.get("h_scale_m", 150.0),
                self.params.get("u_scale_m_per_s", 1.5),
                self.params.get("tau_scale_m_per_s", 5.0),
            ],
            dtype=float,
        )
        self.c = np.asarray(self.params["drift_intercept"], dtype=float).reshape(5, 1)
        self.a = np.asarray(self.params["drift_matrix"], dtype=float)
        self.chol = np.asarray(self.params["noise_cholesky"], dtype=float)
        self.seasonal_noise = np.asarray(self.params["seasonal_noise_factor"], dtype=float)
        self.noise_scale = float(self.params.get("noise_scale", 1.0))
        self.noise_variable_scale = np.asarray(self.params.get("noise_variable_scale", [1.0] * 5), dtype=float).reshape(5, 1)
        self.seasonal_noise_by_var = np.asarray(self.params.get("seasonal_noise_by_var", [[1.0] * 12] * 5), dtype=float)
        self.sat_strength = np.asarray(self.params.get("saturation_strength", [0.0] * 5), dtype=float).reshape(5, 1)
        self.sat_threshold = np.asarray(self.params.get("saturation_threshold", [1.0] * 5), dtype=float).reshape(5, 1)
        self.extra_linear_damping = np.asarray(self.params.get("extra_linear_damping", [0.0] * 5), dtype=float).reshape(5, 1)
        self.clip = np.asarray(self.params.get("state_clip_nondim", [np.inf] * 5), dtype=float).reshape(5, 1)
        self.warm_te_asymmetry = float(self.params.get("warm_te_asymmetry", 0.0))
        self.warm_te_extreme_asymmetry = float(self.params.get("warm_te_extreme_asymmetry", 0.0))
        self.warm_te_extreme_threshold = float(self.params.get("warm_te_extreme_threshold", 0.0))
        self.cold_te_rebound = float(self.params.get("cold_te_rebound", 0.0))
        self.cold_tc_asymmetry = float(self.params.get("cold_tc_asymmetry", 0.0))
        self.cold_tc_extreme_asymmetry = float(self.params.get("cold_tc_extreme_asymmetry", 0.0))
        self.cold_tc_extreme_threshold = float(self.params.get("cold_tc_extreme_threshold", 0.0))
        self.negative_hw_asymmetry = float(self.params.get("negative_hw_asymmetry", 0.0))
        self.recharge_boost = float(self.params.get("coupled_recharge_boost", 0.0))
        self.recharge_threshold = float(self.params.get("coupled_recharge_threshold", 0.0))
        self.cp_diversity_noise = float(self.params.get("cp_diversity_noise", 0.0))
        self.cp_diversity_te_counter = float(self.params.get("cp_diversity_te_counter", 0.0))
        self.cp_diversity_season = np.asarray(self.params.get("cp_diversity_season", [1.0] * 12), dtype=float)
        self.common_sst_noise = float(self.params.get("common_sst_noise", 0.0))
        self.common_sst_season = np.asarray(self.params.get("common_sst_season", [1.0] * 12), dtype=float)
        self.te_positive_noise_feedback = float(self.params.get("te_positive_noise_feedback", 0.0))
        self.tc_negative_noise_feedback = float(self.params.get("tc_negative_noise_feedback", 0.0))
        self.hw_negative_noise_feedback = float(self.params.get("hw_negative_noise_feedback", 0.0))

    def step(self, state, dt, t, rng):
        state = np.asarray(state, dtype=float)
        if state.ndim != 2 or state.shape[0] != 5:
            raise ValueError("state must have shape (5, M)")

        x = state / self.scales.reshape(5, 1)
        drift = self.c + self.a @ x
        drift -= self.extra_linear_damping * x

        # Weak nonlinear damping keeps long integrations finite without changing
        # the fitted linear recharge oscillator near the observed state cloud.
        q = x / np.maximum(self.sat_threshold, 1.0e-9)
        drift -= self.sat_strength * x * q * q

        te_pos = np.maximum(x[1], 0.0)
        te_neg = np.minimum(x[1], 0.0)
        tc_neg = np.minimum(x[0], 0.0)
        tc_extreme_neg = np.minimum(x[0] + self.cold_tc_extreme_threshold, 0.0)
        hw_neg = np.minimum(x[2], 0.0)
        te_extreme = np.maximum(x[1] - self.warm_te_extreme_threshold, 0.0)
        drift[1] += self.warm_te_asymmetry * te_pos * te_pos
        drift[1] += self.warm_te_extreme_asymmetry * te_extreme * te_extreme
        drift[1] += self.cold_te_rebound * te_neg * te_neg
        drift[0] += self.cold_tc_asymmetry * tc_neg * tc_neg
        drift[0] -= self.cold_tc_extreme_asymmetry * tc_extreme_neg * tc_extreme_neg
        drift[2] -= self.negative_hw_asymmetry * hw_neg * hw_neg
        te_discharge = np.maximum(x[1] - self.recharge_threshold, 0.0)
        drift[2] -= self.recharge_boost * x[1] * te_discharge

        month = int(np.floor(float(t))) % 12
        z = rng.normal(size=x.shape)
        noise = self.chol @ z
        noise *= self.noise_scale * self.seasonal_noise[month]
        noise *= self.noise_variable_scale * self.seasonal_noise_by_var[:, month].reshape(5, 1)
        if self.te_positive_noise_feedback:
            noise[1:2] *= 1.0 + self.te_positive_noise_feedback * np.maximum(x[1:2], 0.0)
        if self.tc_negative_noise_feedback:
            noise[0:1] *= 1.0 + self.tc_negative_noise_feedback * np.maximum(-x[0:1], 0.0)
        if self.hw_negative_noise_feedback:
            noise[2:3] *= 1.0 + self.hw_negative_noise_feedback * np.maximum(-x[2:3], 0.0)
        if self.common_sst_noise:
            zsst = rng.normal(size=(1, x.shape[1]))
            common = self.common_sst_noise * self.common_sst_season[month] * zsst
            noise[0:1] += common
            noise[1:2] += common
        if self.cp_diversity_noise or self.cp_diversity_te_counter:
            zcp = rng.normal(size=(1, x.shape[1]))
            cp_amp = self.cp_diversity_season[month]
            noise[0:1] += cp_amp * self.cp_diversity_noise * zcp
            noise[1:2] -= cp_amp * self.cp_diversity_te_counter * zcp

        x_next = x + float(dt) * drift + np.sqrt(max(float(dt), 0.0)) * noise
        x_next = np.clip(x_next, -self.clip, self.clip)
        return x_next * self.scales.reshape(5, 1)
