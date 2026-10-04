"""Shared helpers of the figure modules: matplotlib setup, dataset readers and export."""
import json
import logging

from .. import dataset as DS

# Arial is the design font. Liberation Sans has the same metrics, DejaVu Sans ships with matplotlib.
FONT_FAMILY = ["Arial", "Helvetica", "Liberation Sans", "DejaVu Sans"]
# No creator, producer or date in the exported files.
PDF_METADATA = {"Creator": None, "Producer": None, "CreationDate": None}
PNG_METADATA = {"Software": None}


def pyplot():
    """matplotlib.pyplot on the non-interactive Agg backend, with font fallback messages silenced."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    plt.rcdefaults()
    return plt


def font_in_use():
    from matplotlib import font_manager
    from pathlib import Path
    return Path(font_manager.findfont(font_manager.FontProperties(family=FONT_FAMILY))).stem


def fit_width(fig, texts, max_width_px):
    """Shrink a group of texts by one common factor so that the widest fits in ``max_width_px``.

    The layouts are designed for Arial. With a wider fallback font a few labels would otherwise
    touch their neighbours. Nothing changes when the texts already fit.
    """
    renderer = fig.canvas.get_renderer()
    widest = max(t.get_window_extent(renderer).width for t in texts)
    if widest > max_width_px:
        for t in texts:
            t.set_fontsize(t.get_fontsize() * max_width_px / widest)


def save(fig, out_dir, stem, dpi):
    """Write ``stem``.pdf (vector) and ``stem``.png, return both paths."""
    pdf, png = out_dir / (stem + ".pdf"), out_dir / (stem + ".png")
    fig.savefig(pdf, metadata=PDF_METADATA)
    fig.savefig(png, dpi=dpi, metadata=PNG_METADATA)
    return [pdf, png]


def main_runs(root):
    """The twelve ranked runs, highest final composite first."""
    runs = [r for r in DS.read_table(root, "runs.csv") if r["group"] == "main"]
    return sorted(runs, key=lambda r: -r["final_composite"])


def reference_run(root):
    return [r for r in DS.read_table(root, "runs.csv") if r["group"] == "reference"][0]


def round_index(name):
    return int(name.split("_")[-1])


def read_json(root, rel):
    return json.loads((root / rel).read_text())
