"""The four observation files the agents received in the formal runs, from one archive.

The archive is a release asset of the code repository. It holds the files byte for byte, and
each is checked against the sha256 the harness records (agent/provenance.py), so a rerun gives
the agents exactly the files of the paper's runs. `sciexam prepare-data --keep-raw` rebuilds them
from NOAA instead (106 requests); NOAA revises these datasets, so a rebuild may differ.
"""
import hashlib
import shutil
import tarfile
import urllib.request
from pathlib import Path

from ..agent.provenance import DATA_FILES, TASK_FILES_SHA256

URL = ("https://github.com/ylzhang2447/SciExam-ENSO-code/releases/download/task-data-v1/"
       "sciexam-enso-task-data-v1.tar.gz")
ARCHIVE_SHA256 = "b67a797051aa4e0fe8cac8fbf1bf73da9fccc943ea07dec3e1e07573d7d01018"
ARCHIVE_MB = 180


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def present(raw_dir):
    """True when every file is in ``raw_dir`` with the recorded sha256."""
    raw = Path(raw_dir)
    return all((raw / n).exists() and _sha(raw / n) == TASK_FILES_SHA256["data/" + n]
               for n in DATA_FILES)


def fetch(raw_dir, url=URL, log=print, progress=None):
    """Download the archive, check it, and put the four files in ``raw_dir``. Returns True when
    every file is in place with its recorded sha256; on any failure nothing half-written stays.
    ``progress(done_bytes, total_bytes)`` draws the download, else a line per tenth is logged."""
    raw = Path(raw_dir)
    raw.mkdir(parents=True, exist_ok=True)
    part = raw / ".task-data.tar.gz.part"
    try:
        log("downloading %s (%d MB)" % (url, ARCHIVE_MB))
        with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got, shown = 0, 0
            for chunk in iter(lambda: r.read(1 << 20), b""):
                f.write(chunk)
                got += len(chunk)
                if progress and total:            # no bar without a known size
                    progress(got, total)
                elif total and got * 10 // total > shown:
                    shown = got * 10 // total
                    log("  %3d%%  %.0f of %.0f MB" % (shown * 10, got / 1e6, total / 1e6))
        if _sha(part) != ARCHIVE_SHA256:
            log("the archive's sha256 is not the recorded one: not used")
            return False
        with tarfile.open(part, "r:gz") as tar:
            for name in DATA_FILES:
                member = tar.getmember(name)          # only the four names, never a path
                src = tar.extractfile(member)
                with open(raw / (name + ".part"), "wb") as out:
                    shutil.copyfileobj(src, out)
        for name in DATA_FILES:
            p = raw / (name + ".part")
            if _sha(p) != TASK_FILES_SHA256["data/" + name]:
                log("%s does not have the recorded sha256: not used" % name)
                return False
        for name in DATA_FILES:
            (raw / (name + ".part")).replace(raw / name)
        log("the four files are in %s, each with the sha256 of the formal runs" % raw)
        return True
    except (OSError, tarfile.TarError, KeyError) as e:
        log("the download did not finish: %s" % e)
        return False
    finally:
        for p in [part] + [raw / (n + ".part") for n in DATA_FILES]:
            if p.exists():
                p.unlink()
