"""Diagnostics on monthly index series (1-D arrays, index 0 = the first month of a year).

The event definitions and counts follow the programs of the Zenodo record
doi:10.5281/zenodo.6797996 (Chen and Fang, CC BY 4.0).
"""
import numpy as np


def seasonal_variance(x, month0=0):
    """Variance within each calendar month; index ``i`` has calendar month ``(month0 + i) % 12``."""
    x = np.asarray(x, float)
    m = (np.arange(len(x)) + month0) % 12
    return np.array([np.nanvar(x[m == k]) for k in range(12)])


def autocorr(x, max_lag=36):
    """Autocorrelation function for lags 0 to ``max_lag`` months."""
    x = np.asarray(x, float)
    x = x - np.nanmean(x)
    v = np.nanmean(x * x)
    out = [1.0]
    for k in range(1, max_lag + 1):
        out.append(float(np.nanmean(x[:-k] * x[k:]) / v))
    return np.array(out)


def _collapse_multiyear(ev):
    """Count runs of two or more consecutive event years, each run once."""
    my = (ev[:-1] * ev[1:]).astype(float)
    for i in range(len(my) - 1):
        if my[i] == 1 and my[i + 1] == 1:
            my[i + 1] = 0
    return int(my.sum())


def event_counts(TE, TC):
    """ENSO event counts from boreal-winter (December to February) means.

    El Nino: winter mean of T_E or T_C above 0.5 (eastern Pacific type if T_E > T_C, central
    Pacific otherwise). La Nina: either below -0.5. Extreme: maximum of T_E from April to
    March around the winter at least 2.5. Multi-year: consecutive event winters.
    """
    TE = np.asarray(TE, float)
    TC = np.asarray(TC, float)
    n = min(len(TE), len(TC))
    TE, TC = TE[:n], TC[:n]
    nyr = n // 12 - 1
    EN = np.zeros(nyr)
    EP = np.zeros(nyr)
    CP = np.zeros(nyr)
    EX = np.zeros(nyr)
    LN = np.zeros(nyr)
    for k in range(1, nyr + 1):
        idx = [j - 1 for j in (k * 12, k * 12 + 1, k * 12 + 2) if 1 <= j <= n]
        ext = [j - 1 for j in range(k * 12 - 8, k * 12 + 4) if 1 <= j <= n]
        if not idx:
            continue
        ki = k - 1
        if ext and np.nanmax(TE[ext]) >= 2.5:
            EX[ki] = 1
        mE, mC = np.nanmean(TE[idx]), np.nanmean(TC[idx])
        if mE > 0.5 or mC > 0.5:
            EN[ki] = 1
            (EP if mE > mC else CP)[ki] = 1
        elif mE < -0.5 or mC < -0.5:
            LN[ki] = 1
    return dict(EN=int(EN.sum()), EP=int(EP.sum()), CP=int(CP.sum()), EX=int(EX.sum()),
                LN=int(LN.sum()), MYEN=_collapse_multiyear(EN), MYLN=_collapse_multiyear(LN))


def event_bivariate(TE, TC, reg, lon):
    """Strength and location of every El Nino winter.

    The winter-mean zonal SST anomaly profile is reconstructed by the regression
    ``[1, T_E, T_C] @ reg.T``. Strength is its peak and location the longitude of the peak.
    """
    TE = np.asarray(TE, float)
    TC = np.asarray(TC, float)
    n = min(len(TE), len(TC))
    TE, TC = TE[:n], TC[:n]
    S, L = [], []
    for k in range(1, n // 12):
        idx = [j - 1 for j in (k * 12, k * 12 + 1, k * 12 + 2) if 1 <= j <= n]
        if not idx:
            continue
        mE, mC = np.nanmean(TE[idx]), np.nanmean(TC[idx])
        if mE > 0.5 or mC > 0.5:
            prof = reg @ np.array([1.0, mE, mC])
            S.append(float(np.nanmax(prof)))
            L.append(float(lon[np.nanargmax(prof)]))
    return np.array(S), np.array(L)
