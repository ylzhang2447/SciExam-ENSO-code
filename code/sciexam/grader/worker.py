"""The untrusted side: runs a submission and nothing else.

It holds no observations and computes no score. It answers two requests over stdin/stdout:

    free_run  integrate from the zero state with no external input (no hidden data is
              involved, so the whole run happens here)
    step      advance one sub-step and return the state (used by the smoother and the
              forecasts, whose observations stay on the scoring side)

Usage (inside the worker container): python -m sciexam.grader.worker --submission /sub
"""
import argparse
import importlib.util
import json
import os
import sys
import traceback

import numpy as np

from . import integrate as I
from . import protocol as P


def load_submission(sub_dir):
    """Import ``model.py`` with the submission directory as working directory."""
    sub_dir = os.path.abspath(sub_dir)
    os.chdir(sub_dir)
    if sub_dir not in sys.path:
        sys.path.insert(0, sub_dir)
    spec = importlib.util.spec_from_file_location("submission_model", os.path.join(sub_dir, "model.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with open(os.path.join(sub_dir, "params.json"), encoding="utf-8") as fh:
        params = json.load(fh)
    return mod.ENSOModel(params)


def main(argv=None):
    ap = argparse.ArgumentParser(description="submission worker")
    ap.add_argument("--submission", required=True)
    a = ap.parse_args(argv)
    fin, fout = sys.stdin.buffer, sys.stdout.buffer
    sys.stdout = sys.stderr            # anything the submission prints goes to stderr

    try:
        model = load_submission(a.submission)
    except Exception:
        P.send(fout, {"ok": False, "kind": "load_failed", "error": traceback.format_exc()[-4000:]})
        return 3
    P.send(fout, {"ok": True, "kind": "ready", "protocol": P.PROTOCOL, "numpy": np.__version__})

    while True:
        try:
            head, payload = P.recv(fin)
        except P.ProtocolError as e:
            P.send(fout, {"ok": False, "kind": "protocol_error", "error": str(e)})
            return 4
        if head is None:
            return 0
        kind = head.get("kind")
        try:
            if kind == "shutdown":
                P.send(fout, {"ok": True, "kind": "bye"})
                return 0
            if kind == "free_run":
                g = P.generator_from_state(head["rng_state"])
                out = I.free_run(model, n_years=head["n_years"], dt_months=head["dt_months"],
                                 rng=g, t_offset=float(head.get("t_offset", 0.0)))
                arr = np.array([out[v] for v in I.VARS], dtype=np.float64)
                P.send(fout, {"ok": True, "kind": "free_run", "vars": I.VARS,
                              "rng_state": g.bit_generator.state}, arr)
                continue
            if kind == "step":
                state = np.array(np.frombuffer(payload, dtype=np.float64), dtype=np.float64,
                                 copy=True).reshape(head["shape"])
                g = P.generator_from_state(head["rng_state"])
                nxt = np.asarray(model.step(state, head["dt"], head["t"], g), float)
                P.send(fout, {"ok": True, "kind": "step", "rng_state": g.bit_generator.state}, nxt)
                continue
            P.send(fout, {"ok": False, "kind": "bad_request", "error": "unknown request %r" % kind})
        except Exception:
            P.send(fout, {"ok": False, "kind": "submission_raised", "request": kind,
                          "error": traceback.format_exc()[-4000:]})


if __name__ == "__main__":
    sys.exit(main())
