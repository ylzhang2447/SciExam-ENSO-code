"""Predictive skill on the held-out years 2015 to 2024.

From each monthly start 2015-01 to 2023-12 the model is initialised with the five observed
indices at ``t`` = the calendar month of the start and a 50-member ensemble is run for 12
months (seed = start index). Ensemble means of T_C and T_E are compared with the
observations and with persistence:

    all-target skill  = clip(1 - mean_lead NRMSE_model / mean_lead NRMSE_persistence, 0, 1)
    extreme skill     = the RMSE ratio pooled over targets with |anomaly| > 1 std (0 if < 10)
    predictivity      = 0.7 mean(all-target skill) + 0.3 mean(extreme skill)

Correlations by lead are returned as diagnostics and are not scored.
"""
import numpy as np
import pandas as pd

from . import integrate as I

HELDOUT = ("2015-01", "2024-12")
MAX_LEAD = 12
MIN_EXTREME = 10               # fewer extreme targets than this give an extreme skill of 0
PRED_ENS = 50
PRED_VARS = ["TC", "TE"]


def score_predictivity(model, obs):
    df = pd.DataFrame({v: obs.indices[v] for v in I.VARS}).dropna()
    ho = df.loc[HELDOUT[0]:HELDOUT[1]]
    n = len(ho)
    fc = {v: [] for v in PRED_VARS}
    per = {v: [] for v in PRED_VARS}
    tru = {v: [] for v in PRED_VARS}
    for i in range(0, n - MAX_LEAD):
        istate = ho.iloc[i][I.VARS].to_numpy(float)
        f = I.ensemble_forecast(model, istate, MAX_LEAD, n_members=PRED_ENS, seed=i,
                                start_t=float(ho.index[i].month))
        for v in PRED_VARS:
            fc[v].append(np.asarray(f[v], float).mean(0))
            per[v].append(np.full(MAX_LEAD, ho.iloc[i][v]))
            tru[v].append(ho[v].to_numpy(float)[i + 1:i + 1 + MAX_LEAD])

    detail, all_skill, ext_skill = {}, {}, {}
    for v in PRED_VARS:
        F = np.array(fc[v])
        P = np.array(per[v])
        Tr = np.array(tru[v])
        sd = np.nanstd(Tr)
        corr, corr_p, nrmse, nrmse_p = [], [], [], []
        for j in range(MAX_LEAD):
            fj, pj, tj = F[:, j], P[:, j], Tr[:, j]
            ok = np.isfinite(fj) & np.isfinite(tj)
            corr.append(float(np.corrcoef(fj[ok], tj[ok])[0, 1]) if ok.sum() > 3 else np.nan)
            corr_p.append(float(np.corrcoef(pj[ok], tj[ok])[0, 1]) if ok.sum() > 3 else np.nan)
            nrmse.append(float(np.sqrt(np.nanmean((fj - tj) ** 2)) / sd) if sd > 0 else np.nan)
            nrmse_p.append(float(np.sqrt(np.nanmean((pj - tj) ** 2)) / sd) if sd > 0 else np.nan)
        mnm = float(np.nanmean(nrmse))
        mnp = float(np.nanmean(nrmse_p))
        all_skill[v] = float(np.clip(1.0 - mnm / mnp, 0.0, 1.0)) if mnp > 0 else 0.0
        ext = np.isfinite(F) & np.isfinite(Tr) & (np.abs(Tr) > 1.0 * sd)
        if ext.sum() >= MIN_EXTREME:
            rm = float(np.sqrt(np.mean((F[ext] - Tr[ext]) ** 2)))
            rp = float(np.sqrt(np.mean((P[ext] - Tr[ext]) ** 2)))
            ext_skill[v] = float(np.clip(1.0 - rm / rp, 0.0, 1.0)) if rp > 0 else 0.0
        else:
            ext_skill[v] = 0.0
        detail[v] = dict(all_target_skill=all_skill[v], extreme_skill=ext_skill[v],
                         correlation_by_lead=corr, persistence_correlation_by_lead=corr_p)
    all_score = float(np.mean([all_skill[v] for v in PRED_VARS]))
    ext_score = float(np.mean([ext_skill[v] for v in PRED_VARS]))
    return 0.7 * all_score + 0.3 * ext_score, detail
