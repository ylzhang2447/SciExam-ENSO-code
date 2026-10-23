"""``sciexam prepare-data`` and ``sciexam fetch-paper``."""
import json
import shutil
import time
from pathlib import Path

MIN_FREE_BYTES = 1 << 30     # raw files (about 330 MB) plus the per-year parts while joining


def cmd_prepare_data(a):
    from ..dataset import open_verified
    from . import download as D
    from . import indices as I
    from . import sources as S

    root = open_verified(a.data_dir)
    out = Path(a.out)
    raw_dir = Path(a.raw) if a.raw else out / "raw"
    last = a.last_year
    if not S.FIRST_YEAR <= last <= S.LAST_AVAILABLE:
        raise SystemExit("error: --last-year must be between %d and %d" % (S.FIRST_YEAR, S.LAST_AVAILABLE))
    timing = {}
    if a.check_only or a.raw:
        missing = [n for n in S.SPECS if not (raw_dir / n).exists()]
        if missing:
            raise RuntimeError("--check-only and --raw use raw files already on disk, missing in %s: %s"
                               % (raw_dir, ", ".join(missing)))
        print("using the raw files in %s (no download)" % raw_dir)
    else:
        out.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(out).free
        if free < MIN_FREE_BYTES:
            raise RuntimeError("only %.1f GB free under %s, at least %.1f GB are needed"
                               % (free / 1e9, out, MIN_FREE_BYTES / 1e9))
        print("downloading the raw observations %d-01 to %d-12 into %s (about 330 MB for 1980 to 2014)"
              % (S.FIRST_YEAR, last, raw_dir), flush=True)
        dl = D.download_all(raw_dir, S.FIRST_YEAR, last, jobs=a.jobs,
                            log=lambda m: print(m, flush=True))
        timing["download_s"] = round(dl["seconds"], 1)
        timing["download_mb"] = round(dl["bytes_fetched"] / 1e6, 1)
        print("download: %d remote files, %.0f MB of netCDF written, %.0f s" % (
            dl["files_fetched"], dl["bytes_fetched"] / 1e6, dl["seconds"]), flush=True)

    t0 = time.time()
    df = I.build(raw_dir)
    timing["processing_s"] = round(time.time() - t0, 1)
    csv = out / "processed" / "indices.csv"
    I.write_csv(df, csv)
    print("processing: %.1f s, wrote %s (%s to %s, %d months)" % (
        timing["processing_s"], csv, df.index[0], df.index[-1], len(df)))

    ref = I.load_reference(root)
    first_month = str(df.index[0])
    periods = [("gate", I.GATE_PERIOD)]
    if str(df.index[-1]) > I.GATE_PERIOD[1]:
        periods.append(("held_out", ("%d-01" % (int(I.GATE_PERIOD[1][:4]) + 1), str(df.index[-1]))))
    report = dict(reference="grader_obs/indices_truth.nc", tolerance=I.TOLERANCE,
                  tolerance_source="Phase 1 data gate of the task", timing=timing, periods={})
    ok_all = True
    for label, per in periods:
        per = (max(per[0], first_month), per[1])
        rows = I.compare(df, ref, per)
        report["periods"][label] = dict(period=list(per), indices=rows)
        passed = all(r["passed"] for r in rows.values())
        if label == "gate":
            ok_all = passed
        title = ("months %s to %s, the months the task's Phase 1 gate checks" if label == "gate"
                 else "months %s to %s, held out from the agents (not part of the gate, for information)")
        print("\n" + title % per)
        print("%-5s %6s %8s %12s %9s %8s %10s  %s" % ("index", "months", "missing", "max |diff|",
                                                    "tolerance", "corr", "worst", "result"))
        for k, r in rows.items():
            if r["n"] == 0:
                print("%-5s %6d %8d %12s %9g %8s %10s  %s" % (k, 0, r["missing"], "-", r["tol"], "-", "-", "FAIL"))
                continue
            print("%-5s %6d %8d %12.5f %9g %8.5f %10s  %s" % (
                k, r["n"], r["missing"], r["max_abs_diff"], r["tol"], r["corr"], r["worst_month"],
                "pass" if r["passed"] else "FAIL"))
    (out / "comparison.json").write_text(json.dumps(report, indent=1))

    if not (a.keep_raw or a.check_only or a.raw):
        for n in S.SPECS:
            p = raw_dir / n
            if p.exists():
                p.unlink()
        try:
            raw_dir.rmdir()
        except OSError:
            pass
        print("\nraw files removed (pass --keep-raw to keep them in %s)" % raw_dir)
    print("\n%s. The tolerances are those of the task's Phase 1 data gate. Details in %s"
          % ("All five indices reproduce the dataset reference" if ok_all
             else "Some indices differ from the dataset reference beyond the tolerance", out / "comparison.json"))
    if not ok_all:
        print("Note: NOAA revises these datasets on the server from time to time, so a fresh "
              "download can differ from the files the agents used.")
    return 0 if ok_all else 1


def cmd_fetch_paper(a):
    from ..dataset import default_root
    from . import paper as P
    task_dir = Path(a.task_dir)
    if not a.file:
        print(P.instructions(task_dir))
        return 0
    here = Path(__file__).resolve().parents[2]      # the code checkout
    forbidden = [a.data_dir or default_root(), here]
    return P.install(a.file, task_dir, forbidden=forbidden, accept_different=a.accept_different)


def register(sub):
    from .. import home as H
    p = sub.add_parser("prepare-data",
                       help="download the raw NOAA observations, rebuild the five indices and compare with the dataset")
    p.add_argument("--out", default=str(H.prepared()),
                   help="output folder: raw/ (downloads), processed/indices.csv, comparison.json "
                        "(default %s)" % H.prepared())
    p.add_argument("--keep-raw", action="store_true", help="keep the downloaded netCDF files in OUT/raw")
    p.add_argument("--check-only", action="store_true",
                   help="do not download: rebuild and compare from the raw files already in OUT/raw "
                        "(from an earlier run with --keep-raw)")
    p.add_argument("--raw", help="rebuild from the four raw files in this folder instead of downloading "
                                 "(for example the task's own data/ folder). Implies no download")
    p.add_argument("--last-year", type=int, default=2014,
                   help="last year to download (default 2014, the last year given to the agents). Up to 2024, "
                        "the held-out years are also compared with the reference")
    p.add_argument("--jobs", type=int, default=3, help="parallel OPeNDAP requests (default 3)")
    p.set_defaults(fn=cmd_prepare_data)

    p = sub.add_parser("fetch-paper", help="how to obtain the reference paper given to the agents, and install a copy")
    p.add_argument("--file", help="a downloaded PDF: check its sha256 and copy it into the task folder")
    p.add_argument("--task-dir", default=str(H.papers_parent()),
                   help="task folder that receives papers/<name>.pdf (default %s). Must lie outside "
                        "the dataset and the code" % H.papers_parent())
    p.add_argument("--accept-different", action="store_true",
                   help="install the PDF even when its sha256 differs from the recorded one")
    p.set_defaults(fn=cmd_fetch_paper)
