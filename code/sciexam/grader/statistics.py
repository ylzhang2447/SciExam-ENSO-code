"""Statistical properties: five groups scored from a long free run.

Free run: 200 years of burn-in, then 30 non-overlapping 70-year segments. For each segment
and for the observations (Nino 3 and Nino 4, 1950 to 2019) three curves per index are
computed (PDF, seasonal variance, ACF). Events are counted in 71-year segments.

    curve score  = max(0, corr(mu, obs)) * <exp(-0.5 ((mu - obs) / (C_CURVE R))^2)>_w
    event group  = mean over 7 types of exp(-0.5 ((m - o) / (C_EVENT o))^2)
    statistics   = 0.5 * mean(groups) + 0.5 * min(groups)

The curve diagnostics, the event definitions and the event counting follow the programs and
observation files of the Zenodo record doi:10.5281/zenodo.6797996 (Chen and Fang, CC BY 4.0).

``month_shift`` applies the calendar offset: the free run is read with its month labels
moved by ``month_shift`` months (PDF and ACF do not depend on labels).
"""
import numpy as np

from . import metrics as M

BURN_IN_YEARS = 200
SEG_YEARS = 70
N_SEGMENTS = 30
EVENT_SEG_YEARS = 71
OBS_YEARS = (1950, 2019)       # the observed Nino 3 and Nino 4 record the statistics compare with
STAT_SEED = 0
STAT_DT = 0.1
ACF_LAGS = 36
C_CURVE = 0.35
C_EVENT = 0.20
XGRID = np.linspace(-4.0, 4.5, 120)
OBS_EVENTS_71YR = dict(EN=24, EP=14, CP=10, EX=4, MYEN=5, LN=24, MYLN=8)
EP_SPLIT_LON = 210.0          # degrees E (150 W)
GROUPS = ("shape_pdf", "phase_locking", "memory_acf", "event_freq", "diversity_bivariate")


def total_years():
    return BURN_IN_YEARS + SEG_YEARS * N_SEGMENTS


def series_curves(TE, TC, month0=0):
    """PDF on ``XGRID``, seasonal variance (12 months) and ACF (lags 0 to 36) of T_E and T_C."""
    from scipy.stats import gaussian_kde
    out = {}
    for name, x in (("TE", np.asarray(TE, float)), ("TC", np.asarray(TC, float))):
        x = x[np.isfinite(x)]
        try:
            pdf = gaussian_kde(x)(XGRID)
        except Exception:
            pdf = np.full(XGRID.shape, np.nan)
        out[name] = dict(pdf=pdf, sv=M.seasonal_variance(x, month0), acf=M.autocorr(x, ACF_LAGS))
    return out


def score_bivariate(mTE, mTC, obs):
    """Diversity group: 0.5 * ordering + 0.5 * coverage, reported to three decimals.

    ordering: simulated events peaking east of 150 W must be stronger on average than the
    others (full marks for a 0.5 degC difference). coverage: fraction of observed events whose
    density under a standardised kernel density of the simulated events is at least the 5th
    percentile of the simulated events' own densities.
    """
    from scipy.stats import gaussian_kde
    Smod, Lmod = M.event_bivariate(mTE, mTC, obs.reg, obs.lon)
    Sobs, Lobs = obs.biv_strength, obs.biv_location
    if len(Smod) < 10 or len(Sobs) < 3:
        return dict(score=0.0, note="too few events for a bivariate")
    ep, cp = Lmod >= EP_SPLIT_LON, Lmod < EP_SPLIT_LON
    ep_str = float(np.mean(Smod[ep])) if ep.any() else np.nan
    cp_str = float(np.mean(Smod[cp])) if cp.any() else np.nan
    s_order = (float(np.clip((ep_str - cp_str) / 0.5, 0.0, 1.0))
               if np.isfinite(ep_str) and np.isfinite(cp_str) else 0.0)
    mu = np.array([Lmod.mean(), Smod.mean()])
    sd = np.array([Lmod.std() + 1e-9, Smod.std() + 1e-9])
    P = np.vstack([(Lmod - mu[0]) / sd[0], (Smod - mu[1]) / sd[1]])
    try:
        kde = gaussian_kde(P)
        thr = np.percentile(kde(P), 5)
        Q = np.vstack([(Lobs - mu[0]) / sd[0], (Sobs - mu[1]) / sd[1]])
        coverage = float(np.mean(kde(Q) >= thr))
    except Exception:
        coverage = 0.0
    score = 0.5 * s_order + 0.5 * coverage
    return dict(score=round(score, 3), order_score=round(s_order, 3), coverage=round(coverage, 3),
                ep_strength=round(ep_str, 2), cp_strength=round(cp_str, 2),
                n_model=len(Smod), n_obs=len(Sobs))


def curves_from_run(TE, TC, obs, month_shift=0):
    """Segment curves, event counts per 71 years and the bivariate diagnostic of one free run."""
    TE = np.asarray(TE, float)
    TC = np.asarray(TC, float)
    k = int(month_shift) % 12
    burn, seg = BURN_IN_YEARS * 12, SEG_YEARS * 12
    segs = []
    for i in range(N_SEGMENTS):
        sl = slice(burn + i * seg, burn + (i + 1) * seg)
        sc = series_curves(TE[sl], TC[sl])
        if k:
            for b, x in (("TE", TE[sl]), ("TC", TC[sl])):
                sc[b]["sv"] = M.seasonal_variance(x[np.isfinite(x)], k)
        segs.append(sc)
    eseg = EVENT_SEG_YEARS * 12
    pTE, pTC = TE[burn:], TC[burn:]
    freq = {}
    for i in range(len(pTE) // eseg):
        a, c = pTE[i * eseg:(i + 1) * eseg], pTC[i * eseg:(i + 1) * eseg]
        if k:
            a, c = np.roll(a, k), np.roll(c, k)
        for name, v in M.event_counts(a, c).items():
            freq.setdefault(name, []).append(float(v))
    if k:
        biv = score_bivariate(np.roll(pTE, k), np.roll(pTC, k), obs)
    else:
        biv = score_bivariate(pTE, pTC, obs)
    return dict(segments=segs, obs=series_curves(obs.stat_TE, obs.stat_TC), freq=freq, bivariate=biv)


def _prep(ob, seg, kind):
    seg = np.asarray(seg, float)
    mu = np.nanmean(seg, 0)
    ob = np.asarray(ob, float)
    w = None
    if kind == "acf":                 # lag 0 is identically 1
        ob, mu = ob[1:], mu[1:]
    elif kind == "pdf":               # weight by probability mass
        w = (np.clip(ob, 0, None) + np.clip(mu, 0, None)) / 2.0
    R = float(np.nanstd(ob))
    R = max(R, 1e-6 * max(1.0, float(np.nanmax(np.abs(ob)))))
    return ob, mu, w, R


def curve_score(ob, seg, kind, c=C_CURVE):
    ob, mu, w, R = _prep(ob, seg, kind)
    level = np.exp(-0.5 * ((mu - ob) / (c * R)) ** 2)
    ok = np.isfinite(level)
    if w is not None:
        w = np.where(ok, w, 0.0)
        lvl = float(np.nansum(w * level) / np.nansum(w)) if np.nansum(w) > 0 else 0.0
    else:
        lvl = float(np.nanmean(level[ok])) if ok.any() else 0.0
    m2, o2 = mu[ok], ob[ok]
    if m2.size < 3 or np.nanstd(m2) < 1e-9 or np.nanstd(o2) < 1e-9:
        shape = 0.0
    else:
        r = float(np.corrcoef(m2, o2)[0, 1])
        shape = 0.0 if not np.isfinite(r) else max(0.0, r)
    return float(np.clip(shape * lvl, 0.0, 1.0))


def _agg(v):
    return 0.5 * float(np.mean(v)) + 0.5 * float(np.min(v))


def score(curves, c_curve=C_CURVE, c_event=C_EVENT):
    """Statistics score from ``curves_from_run`` output: (total, groups, panels, events)."""
    panels = {}
    for box in ("TE", "TC"):
        for field, kind in (("pdf", "pdf"), ("sv", "plain"), ("acf", "acf")):
            seg = [s[box][field] for s in curves["segments"]]
            panels["%s_%s" % (field, box)] = curve_score(curves["obs"][box][field], seg, kind, c_curve)
    events = {}
    for name, ov in OBS_EVENTS_71YR.items():
        vals = np.array(curves["freq"].get(name, []), float)
        vals = vals[np.isfinite(vals)]
        if vals.size < 2:
            events[name] = 0.0
            continue
        m = float(vals.mean())
        events[name] = float(np.exp(-0.5 * ((m - ov) / (c_event * ov)) ** 2))
    groups = {
        "shape_pdf": float(np.mean([panels["pdf_TE"], panels["pdf_TC"]])),
        "phase_locking": float(np.mean([panels["sv_TE"], panels["sv_TC"]])),
        "memory_acf": float(np.mean([panels["acf_TE"], panels["acf_TC"]])),
        "event_freq": float(np.mean(list(events.values()))),
        "diversity_bivariate": curves["bivariate"]["score"],
    }
    return _agg(list(groups.values())), groups, panels, events


def event_summary(curves):
    """Mean and 2.5 to 97.5 percentile range of the event counts per 71 years."""
    out = {}
    for name, ov in OBS_EVENTS_71YR.items():
        v = np.array(curves["freq"].get(name, []), float)
        v = v[np.isfinite(v)]
        if v.size:
            lo, hi = np.percentile(v, [2.5, 97.5])
            out[name] = dict(observed=float(ov), model_mean=float(v.mean()), p2_5=float(lo), p97_5=float(hi))
    return out
