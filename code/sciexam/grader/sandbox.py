"""Sandboxed grading with Docker.

Every grading job runs two containers from the grading image, both without network:

    worker  runs the submission (``model.py`` is untrusted). It sees only the staged
            submission, read only, as an unprivileged user with a read-only root file system.
    scorer  runs the scoring code. It sees the observation references, never the
            submission's files, and writes the result JSON.

This process relays the byte streams between the two (worker stdout to scorer stdin and
back). Nothing the submission can write reaches the scorer except arrays of states, whose
shapes are checked.
"""
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import sciexam

IMAGE = os.environ.get("SCIEXAM_IMAGE", "sciexam-grader:%s" % sciexam.__version__)
PREFIX = os.environ.get("SCIEXAM_CONTAINER_PREFIX", "sciexam-")
PKG_DIR = Path(sciexam.__file__).resolve().parent
STAGED_FILES = ("model.py", "params.json", "nondim_scales.json", "model_card.md")
USER = "65534:65534"
# The grading image is built and run for linux/amd64 on every host. requirements.lock pins the
# x86_64 wheels by sha256 (the environment of the released numbers), so on an arm64 host such as
# Apple Silicon Docker builds and runs the same image under emulation instead of failing.
PLATFORM = os.environ.get("SCIEXAM_PLATFORM", "linux/amd64")


def docker():
    return os.environ.get("SCIEXAM_DOCKER", "docker").split()


def environment_dir():
    d = PKG_DIR.parent / "environment"
    if not (d / "Dockerfile").exists():
        raise FileNotFoundError("environment/Dockerfile not found next to the package (install with pip install -e .)")
    return d


def image_present(image=IMAGE):
    r = subprocess.run(docker() + ["image", "inspect", image], capture_output=True)
    return r.returncode == 0


def build_image(image=IMAGE, quiet=False):
    argv = docker() + ["build", "--platform", PLATFORM, "-t", image, str(environment_dir())]
    if quiet:
        argv.insert(len(docker()) + 1, "-q")
    t0 = time.time()
    subprocess.run(argv, check=True)
    return time.time() - t0


def ensure_image(image=IMAGE):
    if not image_present(image):
        print("building the grading image %s (first use only) ..." % image, flush=True)
        build_image(image)


def stage(sub_dir, dest, fallback_scales=None):
    """Copy the submission files the grader uses into ``dest`` (readable by the worker user)."""
    sub_dir, dest = Path(sub_dir), Path(dest)
    dest.mkdir(parents=True)
    for f in ("model.py", "params.json"):
        if not (sub_dir / f).exists():
            raise FileNotFoundError("%s has no %s" % (sub_dir, f))
    for f in STAGED_FILES:
        src = sub_dir / f
        if not src.exists() and f == "nondim_scales.json" and fallback_scales:
            src = Path(fallback_scales)
        if src.exists():
            shutil.copyfile(src, dest / f)
            os.chmod(dest / f, 0o444)
    os.chmod(dest, 0o555)


def _common(name, cpus, memory):
    return docker() + [
        "run", "--rm", "-i", "--platform", PLATFORM, "--name", name,
        "--log-driver", "none", "--network", "none",
        "--user", USER, "--read-only", "--tmpfs", "/tmp:rw,size=1g",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--memory", memory, "--cpus", str(cpus), "--pids-limit", "512",
        "-e", "HOME=/tmp", "-e", "NUMBA_CACHE_DIR=/tmp/numba", "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-e", "PYTHONPATH=/opt/sciexam",
        "-v", "%s:/opt/sciexam/sciexam:ro" % PKG_DIR,
    ]


def _pump(src, dst, stop):
    """Copy bytes from file object ``src`` to file object ``dst`` until end of stream."""
    fd_in, fd_out = src.fileno(), dst.fileno()
    try:
        while not stop.is_set():
            b = os.read(fd_in, 1 << 16)
            if not b:
                break
            view = memoryview(b)
            while view:
                n = os.write(fd_out, view)
                view = view[n:]
    except OSError:
        pass
    finally:
        try:
            dst.close()
        except OSError:
            pass


def _rm(name):
    subprocess.run(docker() + ["rm", "-f", name], capture_output=True)


def run(sub_dir, obs_dir, s=0.0, image=IMAGE, timeout_s=3600,
        workdir=None, fallback_scales=None, cpus_worker=2, cpus_scorer=2, memory="4g"):
    """Grade one submission in the sandbox. Returns the result dict (always has ``status``)."""
    tag = secrets.token_hex(4)
    names = (PREFIX + "worker-" + tag, PREFIX + "scorer-" + tag)
    tmp = Path(tempfile.mkdtemp(prefix="sciexam-", dir=workdir)).resolve()
    os.chmod(tmp, 0o755)
    out_dir = tmp / "out"
    out_dir.mkdir()
    os.chmod(out_dir, 0o777)
    rec = dict(status=None, submission=str(sub_dir), image=image, calendar_offset=float(s))
    t0 = time.time()
    try:
        stage(sub_dir, tmp / "sub", fallback_scales)
        worker = _common(names[0], cpus_worker, memory) + [
            "-v", "%s:/sub:ro" % (tmp / "sub"), image,
            "python3", "-m", "sciexam.grader.worker", "--submission", "/sub"]
        scorer = _common(names[1], cpus_scorer, memory) + [
            "-v", "%s:/obs:ro" % Path(obs_dir).resolve(), "-v", "%s:/out" % out_dir, image,
            "python3", "-m", "sciexam.grader.scorer", "--obs", "/obs", "--offset", repr(float(s)),
            "--out", "/out/result.json"]
        with open(tmp / "worker.log", "wb") as lw, open(tmp / "scorer.log", "wb") as ls:
            pw = subprocess.Popen(worker, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=lw)
            ps = subprocess.Popen(scorer, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=ls)
            stop = threading.Event()
            a = threading.Thread(target=_pump, args=(pw.stdout, ps.stdin, stop), daemon=True)
            b = threading.Thread(target=_pump, args=(ps.stdout, pw.stdin, stop), daemon=True)
            a.start()
            b.start()
            try:
                ps.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                rec["status"] = "timeout"
            finally:
                stop.set()
                for n in names:
                    _rm(n)
                for p in (pw, ps):
                    try:
                        p.wait(timeout=60)
                    except subprocess.TimeoutExpired:
                        p.kill()
        res_path = out_dir / "result.json"
        if rec["status"] is None:
            if res_path.exists():
                rec.update(json.loads(res_path.read_text()))
            else:
                rec["status"] = "grader_error"
                rec["error"] = (tmp / "scorer.log").read_text(errors="replace")[-3000:] + \
                    (tmp / "worker.log").read_text(errors="replace")[-3000:]
        if rec.get("status") != "scored":
            rec.setdefault("worker_log_tail", (tmp / "worker.log").read_text(errors="replace")[-3000:])
    finally:
        rec["wall_seconds"] = round(time.time() - t0, 1)
        if (tmp / "sub").exists():
            os.chmod(tmp / "sub", 0o755)
        shutil.rmtree(tmp, ignore_errors=True)
    return rec
