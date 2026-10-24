"""`sciexam package-run` and `sciexam verify-submission`."""
import json
from pathlib import Path

from . import package as PK
from . import verify as V

MARK = {"pass": "ok  ", "declared": "decl", "fail": "FAIL"}


def cmd_package_run(a):
    try:
        md = PK.package(a.run_dir, a.out, a.system_name, a.contact, a.offset, a.runs_attempted,
                        agent_config=a.agent, env_file=a.env_file, notes=a.notes or "")
    except PK.PackageError as e:
        raise RuntimeError(str(e))
    print("submission written to %s (%d files, final %s, %d checkpoints)"
          % (a.out, md["files"], md["final_round"], md["n_checkpoints"]))
    print("system %s, contact %s, run %d of this system" % (md["system_name"], md["contact"],
                                                            md["runs_attempted"]))
    if not md["comparable_with_paper"]:
        print("this run changed the official leaderboard's settings, so it is ranked apart from it")
    print("check it before you submit:  sciexam verify-submission %s" % a.out)
    return 0


def cmd_verify_submission(a):
    from .. import dataset as DS
    root = DS.open_verified(a.data_dir)
    rep = V.verify(a.submission, root, grade=not a.no_grade, image=a.image, timeout=a.timeout,
                   in_process=a.in_process)
    for c in rep["checks"]:
        print("  [%s] %-20s %s" % (MARK[c["status"]], c["check"], c["detail"]))
    print("\nverdict: %s" % rep["verdict"])
    if rep["verdict"] != "inconsistent":
        print("A consistent submission is listed as self-reported: these checks cannot rule out "
              "records fabricated before packaging.")
    if a.out:
        Path(a.out).write_text(json.dumps(rep, indent=1) + "\n")
        print("report written to %s" % a.out)
    return 0 if rep["verdict"] != "inconsistent" else 1


def register(sub):
    p = sub.add_parser("package-run", help="turn a run folder of run-agent into a leaderboard submission")
    p.add_argument("run_dir", help="the run folder written by sciexam run-agent")
    p.add_argument("--out", required=True, help="the submission folder to write (must not exist)")
    p.add_argument("--system-name", help="override the name the run recorded (the arm's display name)")
    p.add_argument("--contact", help="override the contact the run recorded")
    p.add_argument("--offset", type=float,
                   help="the model's calendar offset, if you know it (see Calendar convention in the "
                        "README). Without it the maintainers judge it, and the checks grade both")
    p.add_argument("--runs-attempted", type=int,
                   help="override the number of runs of this system that the run ledger counted")
    p.add_argument("--agent", help="the arm yaml the run used (default agents/<arm>.yaml)")
    p.add_argument("--env-file", default=".env", help="credential file whose values are scanned for")
    p.add_argument("--notes", help="free text shown with the submission")
    p.set_defaults(fn=cmd_package_run)

    p = sub.add_parser("verify-submission",
                       help="check a submission folder against the rules and regrade its final model")
    p.add_argument("submission")
    p.add_argument("--no-grade", action="store_true", help="skip the regrade")
    p.add_argument("--in-process", action="store_true", help=argparse_suppress())
    p.add_argument("--image", default=None)
    p.add_argument("--timeout", type=int, default=3600)
    p.add_argument("--out", help="write the report as JSON")
    p.set_defaults(fn=cmd_verify_submission)


def argparse_suppress():
    import argparse
    return argparse.SUPPRESS
