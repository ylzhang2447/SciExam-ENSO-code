"""Scientific diagnostics of the final model of Claude Fable 5.1.

Panels (a to c, e to g): PDF, seasonal variance and autocorrelation of T_C and T_E, model mean with a
band of one standard deviation across 70-year segments, against observations 1950 to 2019.
(d): event counts per 71 years with the 2.5th to 97.5th percentile range. (h): peak anomaly against
peak longitude of simulated and observed El Nino events. (i to m): state reconstruction, ensemble
mean with two ensemble standard deviations against the withheld indices. (n, o): correlation of the
ensemble-mean forecast with observations over 2015 to 2024 at leads of one to twelve months, against
persistence.

Reads ``figure_data/fable51_final_diagnostics.json`` (curves, simulated events, reconstructions),
``scores/fable51_final_event_counts.csv``, ``scores/fable51_final_forecast_correlation.csv``,
``grader_obs/obs_bivariate_events.npz`` and ``grader_obs/indices_truth.nc``.
"""
import numpy as np

from .. import dataset as DS
from . import common as C

STEM = "fig4_final_diagnostics"
RUN_ID = "main/fable51"

W, H = 7.2, 6.25
P = dict(blue="#57468C", teal="#346A79", violet="#7F5586", coral="#8C5631", ink="#393B52",
         muted="#626377", green="#DFF0EE", plum="#EDDEF1", rose="#F8E1C9")
MODEL, OBS, BAND = P["blue"], "#C16A24", "#B0A8C9"
MODEL_STYLE = "-"
REFERENCE_STYLE = (0, (3.4, 1.8))
FONT = dict(base=7.8, tick=7.0, title=8.1, block=10.0, legend=7.2)
EVENTS = ["EN", "EP", "CP", "EX", "MYEN", "LN", "MYLN"]


def _truth(root):
    import xarray as xr
    with xr.open_dataset(root / "grader_obs" / "indices_truth.nc") as ds:
        ds = ds.sel(time=slice("1980-01-01", "2014-12-31")).load()
    if ds.time.size != 420:
        raise RuntimeError("indices_truth.nc does not cover 1980 to 2014 monthly")
    return {v: ds[v].values for v in ("TC", "TE", "hW", "u", "tau")}


def build(root, out_dir):
    plt = C.pyplot()
    from matplotlib.lines import Line2D
    from matplotlib.patches import FancyBboxPatch, Patch, Rectangle
    from matplotlib.ticker import MaxNLocator
    plt.rcParams.update({
        "font.family": C.FONT_FAMILY, "font.size": FONT["base"], "text.color": P["ink"],
        "axes.labelcolor": P["ink"], "axes.edgecolor": "#9B9AA8", "axes.linewidth": .55,
        "axes.spines.right": True, "axes.spines.top": True, "axes.labelsize": 7.4, "axes.labelpad": 2.5,
        "xtick.color": P["muted"], "ytick.color": P["muted"], "xtick.labelsize": FONT["tick"],
        "ytick.labelsize": FONT["tick"], "xtick.major.width": .55, "ytick.major.width": .55,
        "xtick.major.size": 2.0, "ytick.major.size": 2.0, "xtick.major.pad": 2.4, "ytick.major.pad": 2.4,
        "pdf.fonttype": 42, "mathtext.fontset": "dejavusans", "legend.frameon": False,
        "savefig.facecolor": "white", "path.simplify": False})

    D = C.read_json(root, "figure_data/fable51_final_diagnostics.json")
    if D["run_id"] != RUN_ID:
        raise RuntimeError("figure_data/fable51_final_diagnostics.json is not for %s" % RUN_ID)
    run = [r for r in DS.read_table(root, "runs.csv") if r["run_id"] == RUN_ID][0]
    if run["final_round"] != D["round"]:
        raise RuntimeError("figure data are for %s, the final checkpoint is %s" % (D["round"], run["final_round"]))
    events = {r["event"]: r for r in DS.read_table(root, "scores/fable51_final_event_counts.csv")}
    forecast = DS.read_table(root, "scores/fable51_final_forecast_correlation.csv")
    obs_events = np.load(root / "grader_obs" / "obs_bivariate_events.npz")
    truth = _truth(root)
    stats = D["statistics"]
    grid = stats["grid"]

    fig = plt.figure(figsize=(W, H))

    def ftext(x, y, text, **kw):
        return fig.text(x / W, y / H, text, **kw)

    def card(name, xywh, fill, accent):
        x, y, w, h = xywh
        p = FancyBboxPatch((x / W, y / H), w / W, h / H, boxstyle="round,pad=0,rounding_size=0.009",
                           transform=fig.transFigure, facecolor="white", edgecolor=fill, linewidth=.65, zorder=-20)
        fig.add_artist(p)
        header_height = .27
        header_bottom = y + h - header_height
        bar = Rectangle((x / W, header_bottom / H), w / W, header_height / H, transform=fig.transFigure,
                        facecolor=fill, edgecolor="none", alpha=.70, zorder=-10)
        bar.set_clip_path(p)
        fig.add_artist(bar)
        fig.add_artist(Line2D([x / W, (x + w) / W], [header_bottom / H, header_bottom / H],
                              transform=fig.transFigure, color=accent, alpha=.25, lw=.55, zorder=-9))
        ftext(x + .14, y + h - header_height / 2, name, fontsize=FONT["block"], weight="bold", color=accent, va="center")

    def ax_at(x, y, w, h, tiny=False):
        ax = fig.add_axes([x / W, y / H, w / W, h / H], facecolor="white")
        ax.grid(axis="y", color="#E7E7EC", linewidth=.65, alpha=.95)
        ax.set_axisbelow(True)
        if tiny:
            ax.tick_params(axis="y", labelsize=6.4, pad=2, length=1.7)
        return ax

    def title(ax, letter, text):
        ax.set_title("(%s)" % letter + ("  %s" % text if text else ""), loc="left", fontsize=FONT["title"],
                     weight="bold", pad=4.5)

    def line(ax, x, y, role, **kw):
        kw.setdefault("ls", MODEL_STYLE if role == "model" else REFERENCE_STYLE)
        kw.setdefault("zorder", 3 if role == "model" else 4)
        ax.plot(x, y, color=MODEL if role == "model" else OBS, **kw)

    card("Statistical properties", (.08, 3.17, 7.04, 3.01), P["green"], P["teal"])
    card("Data assimilation", (.08, .08, 4.50, 3.04), P["plum"], P["violet"])
    card("Prediction", (4.70, .08, 2.42, 3.04), P["rose"], P["coral"])

    fig.legend([Line2D([0], [0], color=MODEL, lw=1.25, ls=MODEL_STYLE),
                Line2D([0], [0], color=OBS, lw=1.1, ls=REFERENCE_STYLE)],
               [run["display_name"], "Observed"], loc="center right", bbox_to_anchor=(6.98 / W, 6.045 / H),
               ncol=2, fontsize=FONT["legend"], handlelength=1.8, columnspacing=1.0, handletextpad=.5)

    # Statistics: T_C and T_E rows, PDF, seasonal variance and ACF columns, events on the right.
    xs, pw = [.52, 2.05, 3.58, 5.36], 1.12
    pg = grid["pdf_anomaly_degC"]
    xgrid = {"pdf": np.linspace(pg["start"], pg["stop"], pg["num"]),
             "sv": np.array(grid["seasonal_variance_month"], float),
             "acf": np.array(grid["acf_lag_months"], float) / 12}
    labels = {"pdf": (r"Anomaly ($^\circ$C)", "Density"), "sv": ("Month", r"Variance ($^\circ$C$^2$)"),
              "acf": ("Lag (years)", "Correlation")}
    for r, (var, y) in enumerate([("TC", 4.80), ("TE", 3.50)]):
        symbol = r"$T_C$" if var == "TC" else r"$T_E$"
        ftext(.205, y + .44, symbol, ha="center", va="center", fontsize=9.2, color=P["teal"])
        for c, metric in enumerate(["pdf", "sv", "acf"]):
            ax = ax_at(xs[c], y, pw, .88)
            rec = stats["model"][var][metric]
            xx = xgrid[metric]
            ax.fill_between(xx, rec["lo"], rec["hi"], color=BAND, alpha=.35, lw=0)
            line(ax, xx, rec["mean"], "model", lw=1.15)
            line(ax, xx, stats["observed"][var][metric], "observed", lw=1.05)
            title(ax, "abcdefgh"[r * 4 + c], ["PDF", "Seasonal variance", "ACF"][c] if r == 0 else "")
            xlabel, ylabel = labels[metric]
            if r == 1:
                ax.set_xlabel(xlabel)
            if metric != "pdf":
                ax.set_ylabel(ylabel, labelpad=1.0 if metric == "sv" else 2.5)
            if metric == "pdf":
                ax.set_xlim(-4, 4.8)
                ax.set_xticks([-4, -2, 0, 2, 4])
                ax.set_ylim(bottom=0)
                ax.yaxis.set_major_locator(MaxNLocator(3))
            elif metric == "sv":
                ax.set_xlim(1, 12)
                ax.set_xticks([1, 4, 7, 10, 12])
                ax.set_ylim(bottom=0)
                ax.yaxis.set_major_locator(MaxNLocator(3))
            else:
                ax.set_xlim(0, 5)
                ax.set_xticks([0, 1, 2, 3, 4, 5])
                ax.set_ylim(-.45, 1.04)
                ax.set_yticks([-.4, 0, .4, .8])

    ax = ax_at(xs[3], 4.80, 1.64, .88)
    means = np.array([events[k]["model_mean"] for k in EVENTS], float)
    lows = np.array([events[k]["p2_5"] for k in EVENTS], float)
    highs = np.array([events[k]["p97_5"] for k in EVENTS], float)
    observed = np.array([events[k]["observed"] for k in EVENTS], float)
    xx = np.arange(7)
    ax.errorbar(xx - .10, means, yerr=[means - lows, highs - means], fmt="o", ms=2.5, color=MODEL, lw=.7,
                capsize=1.6, zorder=3)
    ax.scatter(xx + .10, observed, marker="D", s=8, facecolor="none", edgecolor=OBS, lw=.8, zorder=4)
    title(ax, "d", "Event frequency")
    ax.set_xlim(-.55, 6.55)
    ax.set_ylim(0, 35)
    ax.set_yticks([0, 10, 20, 30])
    ax.set_xticks(xx)
    ax.set_xticklabels(EVENTS, rotation=0, ha="center", fontsize=FONT["tick"])
    ax.set_ylabel("Events per 71 years")

    ax = ax_at(xs[3], 3.50, 1.64, .88)
    biv = D["bivariate_events_model"]
    model = np.column_stack([biv["peak_longitude_degE"], biv["peak_anomaly_degC"]])
    obs = np.column_stack([obs_events["location"], obs_events["strength"]])
    ax.scatter(model[:, 0], model[:, 1], s=4, facecolor=MODEL, edgecolor="none", alpha=.25)
    ax.scatter(obs[:, 0], obs[:, 1], s=11, marker="D", facecolor="none", edgecolor=OBS, lw=.8, zorder=3)
    title(ax, "h", "Bivariate distribution")
    xy = np.vstack([model, obs])
    ax.set_xlim(np.floor(xy[:, 0].min() / 10) * 10 - 2, np.ceil(xy[:, 0].max() / 10) * 10 + 2)
    ax.set_ylim(0, np.ceil(xy[:, 1].max() * 2) / 2 + .1)
    ax.set_xticks([180, 210, 240, 270])
    ax.yaxis.set_major_locator(MaxNLocator(3))
    ax.set_xlabel(r"Peak longitude ($^\circ$E)")
    ax.set_ylabel(r"Peak anomaly ($^\circ$C)")

    # State reconstruction, shown after the 1980 and 1981 spin-up.
    fig.legend([Line2D([0], [0], color=MODEL, lw=1.2, ls=MODEL_STYLE), Patch(facecolor=BAND, alpha=.45, edgecolor="none"),
                Line2D([0], [0], color=OBS, lw=.9, ls=REFERENCE_STYLE)],
               ["Ensemble mean", "±2 SD", "Observed"], loc="center right", bbox_to_anchor=(4.46 / W, 2.985 / H),
               ncol=3, fontsize=7.0, handlelength=1.6, columnspacing=.5, handletextpad=.3)

    def test_label(y, letter, detail):
        ftext(.535, y + .006, "Test %s" % letter, ha="center", va="center", fontsize=8.0, weight="bold", color=P["violet"])
        ftext(.93, y + .006, detail, fontsize=7.7, va="center", color=P["ink"])

    test_label(2.675, "A", r"Given $T_C, T_E$, recover $h_W, u, \tau$")
    test_label(1.275, "B", r"Given $h_W, u, \tau$, recover $T_C, T_E$")
    da = D["assimilation"]
    times = 1980 + np.arange(da["months"]) / 12
    use = times >= 1982
    targets = [("A", "hW", 2.245, r"$h_W$", "m"), ("A", "u", 1.805, r"$u$", "m/s"),
               ("A", "tau", 1.365, r"$\tau$", "m/s"), ("B", "TC", .825, r"$T_C$", r"$^\circ$C"),
               ("B", "TE", .39, r"$T_E$", r"$^\circ$C")]
    for j, (case, var, y, symbol, unit) in enumerate(targets):
        ax = ax_at(.84, y, 3.54, .355, tiny=True)
        rec = da["tests"][case]["recovered"][var]
        mean, lo, hi = (np.asarray(rec[k])[use] for k in ("mean", "lo", "hi"))
        obs = truth[var][use]
        ax.fill_between(times[use], lo, hi, color=BAND, alpha=.43, lw=0)
        line(ax, times[use], mean, "model", lw=.85)
        line(ax, times[use], obs, "observed", lw=.85)
        lower, upper = min(lo.min(), obs.min()), max(hi.max(), obs.max())
        pad = (upper - lower) * .08
        ax.set_ylim(lower - pad, upper + pad)
        ax.yaxis.set_major_locator(MaxNLocator(3, min_n_ticks=2))
        ax.set_xlim(1982, 2015)
        ax.set_xticks([1985, 1995, 2005, 2015])
        if j != 4:
            ax.tick_params(axis="x", labelbottom=False, length=1.7)
        else:
            ax.set_xlabel("Year", labelpad=1.5)
        ftext(.16, y + .25, "(%s)" % "ijklm"[j], fontsize=8.1, weight="bold")
        ftext(.47, y + .205, symbol, fontsize=8.1, ha="center", va="center")
        ftext(.47, y + .07, "(%s)" % unit, fontsize=6.5, ha="center", va="center", color=P["muted"])

    fig.legend([Line2D([0], [0], color=OBS, lw=1, ls=REFERENCE_STYLE)], ["Persistence"], loc="center right",
               bbox_to_anchor=(6.99 / W, 2.985 / H), ncol=1, fontsize=7.2, handlelength=1.8, handletextpad=.5)
    lead = np.array([r["lead"] for r in forecast], float)
    for var, y, letter, symbol in [("TC", 1.74, "n", r"$T_C$"), ("TE", .43, "o", r"$T_E$")]:
        ax = ax_at(5.20, y, 1.68, .90)
        line(ax, lead, [r["corr_" + var] for r in forecast], "model", lw=1.30, marker="o", ms=2.0,
             markevery=[0, 2, 5, 8, 11])
        line(ax, lead, [r["persistence_" + var] for r in forecast], "persistence", lw=1.05)
        ax.set_xlim(1, 12)
        ax.set_xticks([1, 3, 6, 9, 12])
        ax.set_ylim(-.20, 1.045)
        ax.set_yticks([0, .5, 1])
        ax.axhline(0, color=P["muted"], lw=.4, ls=":", alpha=.6)
        if var == "TE":
            ax.set_xlabel("Forecast lead (months)")
        ax.set_ylabel("Correlation")
        title(ax, letter, symbol + " forecast correlation")

    files = C.save(fig, out_dir, STEM, dpi=260)
    plt.close(fig)
    return files
