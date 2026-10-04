"""Dynamical consistency: state reconstruction by an ensemble Kalman smoother.

Observed indices 1980-01 to 2014-12. Test A assimilates T_C and T_E and reconstructs h_W,
u and tau. Test B assimilates h_W, u and tau and reconstructs T_C and T_E. After the first
24 months each reconstructed ensemble mean is scored by the Nash-Sutcliffe efficiency
clipped to [0, 1]. The score is the plain mean of the five values.

The smoother (``integrate.enks_reconstruct``) is an implementation of an ensemble Kalman
smoother written for this benchmark: a lagged smoother with perturbed observations whose
forecast step is the submission's own ``step``.
"""
import numpy as np
import pandas as pd

from . import integrate as I

WINDOW = ("1980-01", "2014-12")
DA_ENS = 500
DA_LAG = 3
DA_DT_MONTHS = 0.1
DA_SUB_MONTH = 0.2
SPINUP_MONTHS = 24


def score_da(model, obs):
    df = pd.DataFrame({v: obs.indices[v] for v in I.VARS})
    df = df.loc[WINDOW[0]:WINDOW[1]].dropna()
    truth = {v: df[v].values for v in I.VARS}
    Y = np.array([truth[v] for v in I.VARS])
    corrA, reconA, _ = I.enks_reconstruct(model, truth, ["TC", "TE"], n_ens=DA_ENS, seed=0,
                                          dt_months=DA_DT_MONTHS, lag=DA_LAG, sub_month=DA_SUB_MONTH)
    corrB, reconB, _ = I.enks_reconstruct(model, truth, ["hW", "u", "tau"], n_ens=DA_ENS, seed=0,
                                          dt_months=DA_DT_MONTHS, lag=DA_LAG, sub_month=DA_SUB_MONTH)

    def nse(recon, hidden):
        out = {}
        for v in hidden:
            i = I.VARS.index(v)
            tr = Y[i, SPINUP_MONTHS:]
            mn = np.asarray(recon, float)[i, SPINUP_MONTHS:]
            var = float(np.var(tr))
            out[v] = float(np.clip(1.0 - np.mean((mn - tr) ** 2) / var, 0.0, 1.0)) if var > 0 else 0.0
        return out

    sk = {"A_" + k: v for k, v in nse(reconA, ["hW", "u", "tau"]).items()}
    sk.update({"B_" + k: v for k, v in nse(reconB, ["TC", "TE"]).items()})
    corr = {"A_" + k: v for k, v in corrA.items()}
    corr.update({"B_" + k: v for k, v in corrB.items()})
    return float(np.mean(list(sk.values()))), dict(nse=sk, correlation=corr)
