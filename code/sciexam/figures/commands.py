"""``sciexam figures``: regenerate the data figures of the paper from the dataset.

| name  | paper figure                                                        | reads                                   |
|-------|---------------------------------------------------------------------|-----------------------------------------|
| fig1  | Figure 1, illustration with final scores (not distributed, prints a note) |                                   |
| fig3  | Figure 3, checkpoint scores over the run and final scores           | runs.csv, checkpoints.csv, evidence/    |
| fig4  | Figure 4, diagnostics of the final Claude Fable 5.1 model           | figure_data/, scores/, grader_obs/      |
| fig5c | Figure 5c, structural vote of the simplified models                 | scores/structural_vote.csv, runs.csv    |

Every figure is written as a vector PDF and a PNG. The command only reads the dataset.
"""
import importlib
import time
from pathlib import Path

from .. import dataset as DS

FIGURES = ("fig1", "fig3", "fig4", "fig5c")


def register(sub):
    p = sub.add_parser("figures", help="regenerate the paper's data figures from the dataset (PDF and PNG)")
    p.add_argument("--out", default="sciexam_figures", help="output folder (default sciexam_figures)")
    p.add_argument("--only", help="comma-separated subset of %s" % ",".join(FIGURES))
    p.set_defaults(fn=run)


def run(a):
    names = FIGURES
    if a.only:
        names = [n.strip() for n in a.only.split(",") if n.strip()]
        bad = [n for n in names if n not in FIGURES]
        if bad:
            raise SystemExit("error: unknown figure %s (choose from %s)" % (", ".join(bad), ",".join(FIGURES)))
    root = DS.open_verified(a.data_dir)
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        raise RuntimeError("sciexam figures needs matplotlib. Install the figures extra: pip install -e '.[figures]'")
    from . import common
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    common.pyplot()
    print("writing %s to %s (font %s)" % (", ".join(names), out, common.font_in_use()), flush=True)
    written = 0
    for name in names:
        t = time.time()
        files = importlib.import_module("sciexam.figures." + name).build(root, out)
        written += len(files)
        print("%-6s %-60s %5.1f s" % (name, ", ".join(p.name for p in files) or "no file", time.time() - t), flush=True)
    print("%d files in %s, %.1f s" % (written, out, time.time() - t0))
    return 0
