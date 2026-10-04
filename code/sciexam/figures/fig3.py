"""Model development and final scores.

Panel (a): composite score of every graded checkpoint of the twelve ranked runs, with the final
checkpoint marked. Panel (b): final scores of the twelve runs and the reference model as stacked
weighted contributions (0.3 statistics, 0.3 dynamics, 0.4 prediction) with the composite at the end.

Reads ``runs.csv``, ``checkpoints.csv`` and ``evidence/checkpoint_times.csv``. The x axis of panel (a)
is the eligible time since task start at which each checkpoint was taken (``eligible_s``). Checkpoints
that could not be graded are not drawn, the line joins the graded neighbours. If the time table is
missing, the checkpoint number is used instead and a TODO line is printed.
"""
import numpy as np

from .. import dataset as DS
from . import common as C

STEM = "fig3_checkpoint_and_final_scores"
TIMES, TIME_COLUMN = "evidence/checkpoint_times.csv", "eligible_s"

W, H = 10.8, 3.75
P = dict(ink="#393B52", muted="#626377", edge="#999AA6", grid="#E7E7EC",
         violet="#57468C", teal="#346A79")
CAT = [("statistics", "Statistics", .3, "#73A9A5"),
       ("physics", "Dynamics", .3, "#A58CBD"),
       ("predictivity", "Prediction", .4, "#E4AE78")]
STYLES = {
    "fable51": ("#7B234B", "-"), "kimi": ("#57468C", "-"), "gpt56": ("#3976AC", "-"),
    "gpt6astra": ("#35465F", (0, (6, 1.8))), "gpt55": ("#98733E", (0, (4, 1.6))),
    "opus5": ("#258E88", "-"), "dsflash": ("#C16A24", (0, (4, 1.2, 1, 1.2))),
    "gemini38": ("#A55F98", (0, (4, 1.5))), "deepseek": ("#B94F60", (0, (4, 1.2, 1, 1.2))),
    "minimax": ("#5C8245", (0, (1, 1.5))), "glm52": ("#AC912D", (0, (4, 2))),
    "qwen3max": ("#858596", (0, (1, 1.5)))}
L = dict(A=[.70, .58, 4.35, 2.66], B=[7.29, .58, 3.35, 2.66], swatch=[5.20, 5.40], name=5.52,
         panel_header=3.55)
F = dict(title=15.5, panel_letter=15.5, axes=13, ticks=12.9, model=12.2, total=13, legend=11.3)


def _times(root):
    """{(run_id, round): eligible seconds}, or None when the table or its column is missing."""
    if not (root / TIMES).is_file():
        return None
    table = DS.read_table(root, TIMES)
    if not table or TIME_COLUMN not in table[0]:
        return None
    return {(t["run_id"], t["round"]): t[TIME_COLUMN] for t in table}


def _trajectories(root, runs):
    """{arm: (x, y, final_x, final_y)} and a flag telling whether x is eligible time in hours."""
    by_run = {}
    for c in DS.read_table(root, "checkpoints.csv"):
        if c["graded"] and c["composite"] is not None:
            by_run.setdefault(c["run_id"], []).append(c)
    times = _times(root)
    has_time = times is not None and all(times.get((c["run_id"], c["round"])) is not None
                                         for r in runs for c in by_run[r["run_id"]])
    xof = (lambda c: times[(c["run_id"], c["round"])] / 3600) if has_time else (lambda c: C.round_index(c["round"]))
    out = {}
    for r in runs:
        cks = sorted(by_run[r["run_id"]], key=lambda c: C.round_index(c["round"]))
        x = np.array([xof(c) for c in cks], float)
        y = np.array([c["composite"] for c in cks], float)
        if has_time and np.any(np.diff(x) <= 0):
            raise RuntimeError("%s: eligible times of %s do not increase with the round" % (TIMES, r["run_id"]))
        fin = [c for c in cks if c["round"] == r["final_round"]][0]
        out[r["arm"]] = (x, y, xof(fin), fin["composite"])
    return out, has_time


def build(root, out_dir):
    plt = C.pyplot()
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    plt.rcParams.update({
        "font.family": C.FONT_FAMILY, "font.size": 12, "text.color": P["ink"],
        "axes.labelcolor": P["ink"], "axes.edgecolor": P["edge"], "axes.linewidth": .7,
        "axes.spines.top": True, "axes.spines.right": True, "xtick.color": P["muted"],
        "ytick.color": P["muted"], "xtick.labelsize": F["ticks"], "ytick.labelsize": F["ticks"],
        "xtick.major.size": 3, "ytick.major.size": 3, "xtick.major.width": .7, "ytick.major.width": .7,
        "pdf.fonttype": 42, "savefig.facecolor": "white", "path.simplify": False})

    runs = C.main_runs(root)
    ref = C.reference_run(root)
    rows = [dict(arm=r["arm"], name=r["display_name"], composite=r["final_composite"],
                 **{k: r["final_" + k] for k, *_ in CAT}) for r in runs]
    rows.append(dict(arm="reference", name="Reference model", composite=ref["final_composite"],
                     **{k: ref["final_" + k] for k, *_ in CAT}))
    order = sorted(rows, key=lambda row: -row["composite"])
    traj, has_time = _trajectories(root, runs)
    if not has_time:
        print("  note: %s with column %s (eligible time of each checkpoint) is missing or incomplete, "
              "panel (a) uses the checkpoint number on the x axis" % (TIMES, TIME_COLUMN))

    fig = plt.figure(figsize=(W, H))

    def ft(x, y, s, **kw):
        return fig.text(x / W, y / H, s, **kw)

    def make_ax(key):
        x, y, w, h = L[key]
        ax = fig.add_axes([x / W, y / H, w / W, h / H], facecolor="white")
        ax.set_axisbelow(True)
        return ax

    ft(.08, L["panel_header"], "(a)", fontsize=F["panel_letter"], weight="bold", va="center")
    ft(.55, L["panel_header"], "Checkpoint scores", fontsize=F["title"], weight="bold", color=P["violet"], va="center")
    ft(5.20, L["panel_header"], "(b)", fontsize=F["panel_letter"], weight="bold", va="center")
    ft(5.68, L["panel_header"], "Final scores", fontsize=F["title"], weight="bold", color=P["teal"], va="center")

    axA = make_ax("A")
    axA.grid(axis="y", color=P["grid"], lw=.65)
    for r in reversed(runs):
        arm = r["arm"]
        x, y, fx, fy = traj[arm]
        color, ls = STYLES[arm]
        axA.plot(x, y, color=color, ls=ls, lw=1.55 if arm == "fable51" else 1.20, alpha=.96,
                 zorder=4 if arm == "fable51" else 3)
        axA.scatter([fx], [fy], s=23, color=color, edgecolor="white", linewidth=.55, zorder=8)
    if has_time:
        axA.set_xlim(0, 6.12)
        axA.set_xticks(np.arange(7))
        axA.set_xlabel("Eligible time (hours)", labelpad=5, fontsize=F["axes"])
    else:
        n = max(r["n_snapshots"] for r in runs)
        axA.set_xlim(0, n * 1.02)
        axA.set_xticks(np.arange(0, n + 1, 10))
        axA.set_xlabel("Checkpoint", labelpad=5, fontsize=F["axes"])
    axA.set_ylim(0, .6)
    axA.set_yticks(np.arange(0, .61, .1))
    axA.set_ylabel("Composite score", labelpad=5, fontsize=F["axes"])

    axB = make_ax("B")
    axB.set_ylim(len(order) - .35, -.65)
    axB.set_xlim(0, .66)
    axB.set_xticks(np.arange(0, .601, .1))
    axB.set_yticks([])
    axB.grid(axis="x", color=P["grid"], lw=.55)
    axB.set_xlabel("Composite score", labelpad=5, fontsize=F["axes"])
    bx, _, bw, _ = L["B"]
    trans = axB.get_yaxis_transform()

    fig.canvas.draw()
    pixels_per_score = axB.get_window_extent(fig.canvas.get_renderer()).width / .66
    names = []
    for i, row in enumerate(order):
        arm = row["arm"]
        is_ref = arm == "reference"
        if not is_ref:
            color, ls = STYLES[arm]
            axB.add_line(Line2D([(v - bx) / bw for v in L["swatch"]], [i, i], transform=trans,
                                clip_on=False, color=color, ls=ls, lw=1.6, zorder=4))
        names.append(axB.text((L["name"] - bx) / bw, i, row["name"], transform=trans, clip_on=False, va="center",
                              ha="left", fontsize=F["model"], weight="bold" if is_ref else "normal"))
        left = 0
        for key, _, weight, color in CAT:
            width = row[key] * weight
            bar = axB.barh(i, width, left=left, height=.66, color=color, edgecolor="white",
                           linewidth=.55, zorder=3)[0]
            if is_ref:
                bar.set_hatch("///")
                bar.set_edgecolor(P["muted"])
                bar.set_linewidth(.5)
            left += width
        axB.text(left + 8 / pixels_per_score, i, "%.4f" % row["composite"], ha="left", va="center",
                 fontsize=F["total"], color=P["ink"], zorder=4)

    # model names end at least 0.12 inch before the bars (as with the design font)
    C.fit_width(fig, names, (L["B"][0] - L["name"] - .12) * fig.dpi)
    fig.legend([Patch(facecolor=c, edgecolor="none") for *_, c in CAT], [name for _, name, _, _ in CAT],
               ncol=3, loc="center right", bbox_to_anchor=(10.68 / W, L["panel_header"] / H),
               fontsize=F["legend"], frameon=False, handlelength=.8, handletextpad=.45, columnspacing=1.1)
    files = C.save(fig, out_dir, STEM, dpi=240)
    plt.close(fig)
    return files
