"""Structural vote of the simplified models (panel c of the structural simplification figure).

For each of the nine analyzed runs (the nine highest final composites), a vote in the column of the
structural family that its simplified model retains: linear dynamics with multiplicative noise, or
nonlinear dynamics with additive noise. Reads ``scores/structural_vote.csv`` and ``runs.csv``.

Drawn in the units of the full figure (2380 units across a 510.2 pt page), so that fonts and line
widths match the printed panel. Only the vote table of the panel is regenerated.
"""
from .. import dataset as DS
from . import common as C

STEM = "fig5c_structural_vote"
UNIT = 510.23622 / 2380          # points per drawing unit
X0, Y0, PW, PH = 1804, 24, 712, 732           # panel frame, ending 31 units below the table
N_ROWS = 9
FAMILIES = {"linear+multiplicative": ("Linear dynamics\n+ multiplicative noise", "#2F7C83", "#E0F1ED"),
            "nonlinear+additive": ("Nonlinear dynamics\n+ additive noise", "#B6733C", "#FAE5CE")}
INK, LINE, PURPLE, LAVENDER, HEAD = "#303348", "#D8D4E5", "#675099", "#F7F4FB", "#ECE6F5"


class _Panel:
    def __init__(self, plt):
        self.fig = plt.figure(figsize=(PW * UNIT / 72, PH * UNIT / 72))
        ax = self.fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(X0, X0 + PW)
        ax.set_ylim(Y0 + PH, Y0)
        ax.axis("off")
        self.ax = ax
        self.z = 0

    def _z(self):
        self.z += 1
        return self.z

    def rect(self, x, y, w, h, fill=None, stroke=None, lw=1.0, r=0):
        from matplotlib.patches import FancyBboxPatch
        style = "round,pad=0,rounding_size=%g" % r if r else "square,pad=0"
        self.ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=style, facecolor=fill or "none",
                                         edgecolor=stroke or "none", linewidth=lw * UNIT if stroke else 0,
                                         zorder=self._z()))

    def circle(self, x, y, r, fill, stroke, lw):
        from matplotlib.patches import Circle
        self.ax.add_patch(Circle((x, y), r, facecolor=fill, edgecolor=stroke, linewidth=lw * UNIT, zorder=self._z()))

    def path(self, pts, col, lw):
        xs, ys = zip(*pts)
        self.ax.plot(xs, ys, color=col, lw=lw * UNIT, solid_capstyle="round", solid_joinstyle="round", zorder=self._z())

    def text(self, x, y, s, size, col=INK, bold=False, align="left", leading=1.48):
        return [self.ax.text(x, y + i * size * leading, part, fontsize=size * UNIT, color=col,
                             weight="bold" if bold else "normal", ha=align, va="baseline", zorder=self._z())
                for i, part in enumerate(s.split("\n"))]

    def px(self, units):
        return units * UNIT * self.fig.dpi / 72

    def vote(self, cx, cy, col, fill):
        """Ballot icon inside a circle (a box with a slot and a ticked card)."""
        self.circle(cx, cy, 18, fill, col, 1)
        s, ox, oy = .62, cx - 10, cy - 14
        p = lambda x, y: (ox + s * x, oy + s * y)  # noqa: E731
        self.rect(ox + s * 0, oy + s * 14, s * 32, s * 21, "#FFFFFF", col, 2 * s, 3 * s)
        self.path([p(7, 19), p(25, 19)], col, 2 * s)
        self.rect(ox + s * 10, oy + s * 0, s * 14, s * 16, "#FFFFFF", col, 1.8 * s, 2 * s)
        self.path([p(13, 8), p(16, 11), p(21, 5)], col, 1.8 * s)


def build(root, out_dir):
    plt = C.pyplot()
    plt.rcParams.update({"font.family": C.FONT_FAMILY, "pdf.fonttype": 42, "savefig.facecolor": "white",
                         "path.simplify": False})
    vote = {r["arm"]: r for r in DS.read_table(root, "scores/structural_vote.csv")}
    runs = [r for r in C.main_runs(root) if r["arm"] in vote]
    if len(runs) != N_ROWS or {r["arm"] for r in C.main_runs(root)[:N_ROWS]} != set(vote):
        raise RuntimeError("structural_vote.csv does not hold the nine highest-ranked runs")
    unknown = {vote[r["arm"]]["vote"] for r in runs} - set(FAMILIES)
    if unknown:
        raise RuntimeError("unknown structural family in structural_vote.csv: %s" % ", ".join(sorted(unknown)))

    d = _Panel(plt)
    d.rect(X0, Y0, PW, PH - 2, "#FFFFFF", LINE, 1.3, 24)
    d.rect(X0 + 1, Y0 + 1, PW - 2, 75, HEAD, None, r=23)
    d.rect(X0 + 1, Y0 + 45, PW - 2, 31, HEAD)
    d.text(1826, 75, "(c)", 33, PURPLE, True)
    d.text(1886, 75, "Where do models stand?", 38, INK, True)

    top = 121                               # the table block, moved up to the panel heading
    d.rect(1844, top, 632, 36, LAVENDER, r=18)
    d.text(2160, top + 25.2, "Nine selected agent-built models", 23, PURPLE, True, "center")
    t0 = top + 49
    x0, cols = 1826, {"linear+multiplicative": 2058, "nonlinear+additive": 2278}
    d.rect(x0, t0, 668, 555, "#FCFBFD", LINE, 1, 15)
    C.fit_width(d.fig, d.text(1840, t0 + 47, "Agent-built model", 21, INK, True), d.px(2058 - 1840 - 24))
    heads = []
    for fam, x in cols.items():
        label, col, fill = FAMILIES[fam]
        d.rect(x, t0 + 1, 214, 80, fill, r=12)
        heads += d.text(x + 107, t0 + 33, label, 18, col, True, "center")
    C.fit_width(d.fig, heads, d.px(214 - 12))
    first_y, row_h = t0 + 88, 50
    counts = {}
    for i, r in enumerate(runs):
        y = first_y + i * row_h
        if i % 2 == 0:
            d.rect(x0 + 7, y, 654, 47, "#F4F3F8", r=8)
        d.text(1846, y + 33, r["display_name"], 18, INK)
        fam = vote[r["arm"]]["vote"]
        counts[fam] = counts.get(fam, 0) + 1
        _, col, fill = FAMILIES[fam]
        d.vote(cols[fam] + 107, y + 24, col, fill)
    print("  fig5c: %s" % ", ".join("%d %s" % (n, f) for f, n in sorted(counts.items())))
    files = C.save(d.fig, out_dir, STEM, dpi=600)
    plt.close(d.fig)
    return files
