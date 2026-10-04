"""The trusted side: scores a submission that runs in a separate worker.

stdin and stdout of this process carry the worker protocol (the host relays them to the
worker container). The observations are read here and are never sent to the worker: the
smoother update and the forecast targets stay on this side. The result is written as JSON
to ``--out``.

Usage (inside the scoring container):
    python -m sciexam.grader.scorer --obs /obs --offset -1 --out /out/result.json
"""
import argparse
import json
import math
import sys
import time
import traceback

import numpy as np

from . import obs as O
from . import protocol as P
from .score import SubmissionError, WorkerError, grade


class RemoteModel:
    """Looks like a submission to the integrations; is a pipe to the worker."""

    def __init__(self, fin, fout):
        self.fin, self.fout = fin, fout
        self.calls = 0
        head, _ = self._recv()
        if not head.get("ok") or head.get("kind") != "ready":
            raise WorkerError("worker not ready: %s" % head.get("error", head)[-2000:])
        self.ready = head

    def _recv(self):
        try:
            head, buf = P.recv(self.fin)
        except P.ProtocolError as e:
            raise WorkerError("protocol: %s" % e)
        if head is None:
            raise WorkerError("the worker closed the stream")
        if not head.get("ok", True):
            if head.get("kind") == "submission_raised":
                raise SubmissionError(head.get("error", "")[-2000:])
            if head.get("kind") == "load_failed":
                raise SubmissionError("model.py could not be loaded:\n" + head.get("error", "")[-2000:])
            raise WorkerError("%s: %s" % (head.get("kind"), head.get("error", "")[-2000:]))
        return head, buf

    def step(self, state, dt, t, rng):
        a = np.asarray(state, float)
        self.calls += 1
        P.send(self.fout, {"kind": "step", "dt": float(dt), "t": float(t),
                           "rng_state": rng.bit_generator.state}, a)
        head, buf = self._recv()
        rng.bit_generator.state = head["rng_state"]
        out = P.array(head, buf)
        if out.shape != a.shape:
            raise SubmissionError("step returned shape %s for a state of shape %s" % (out.shape, a.shape))
        return out

    def free_run(self, n_years, dt_months, rng, t_offset=0.0):
        P.send(self.fout, {"kind": "free_run", "n_years": float(n_years), "dt_months": float(dt_months),
                           "t_offset": float(t_offset), "rng_state": rng.bit_generator.state})
        head, buf = self._recv()
        rng.bit_generator.state = head["rng_state"]
        arr = P.array(head, buf)
        if arr.shape != (5, int(n_years * 12)):
            raise SubmissionError("free run returned shape %s" % (arr.shape,))
        return {v: arr[i] for i, v in enumerate(head["vars"])}

    def close(self):
        try:
            P.send(self.fout, {"kind": "shutdown"})
            P.recv(self.fin)
        except Exception:
            pass


def _clean(x):
    """JSON-safe copy: numpy scalars to floats, non-finite floats to None."""
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, np.ndarray):
        return [_clean(v) for v in x.tolist()]
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return v if math.isfinite(v) else None
    if isinstance(x, np.integer):
        return int(x)
    return x


def write_result(res, path):
    with open(path, "w") as fh:
        json.dump(_clean(res), fh, indent=1)
        fh.write("\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="trusted scoring process")
    ap.add_argument("--obs", required=True)
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    fin, fout = sys.stdin.buffer, sys.stdout.buffer
    sys.stdout = sys.stderr
    log = lambda m: print("[scorer %s] %s" % (time.strftime("%H:%M:%S"), m), file=sys.stderr, flush=True)  # noqa: E731
    res = {"status": None}
    try:
        obs = O.load(a.obs)
        model = RemoteModel(fin, fout)
        res = grade(model, obs, s=a.offset, log=log)
        res["worker"] = {"numpy": model.ready.get("numpy"), "step_calls": model.calls}
        res["scorer"] = {"numpy": np.__version__}
        model.close()
    except SubmissionError as e:
        res = dict(res, status="submission_error", error=str(e)[-3000:])
    except WorkerError as e:
        res = dict(res, status="grader_error", error=str(e)[-3000:])
    except Exception:
        res = dict(res, status="grader_error", error=traceback.format_exc()[-3000:])
    write_result(res, a.out)
    log("status %s" % res.get("status"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
