"""Where SciExam keeps its files.

An install made by install.sh keeps everything in one folder the user chose, and its launcher
sets SCIEXAM_HOME to it:

    $SCIEXAM_HOME/
      env/              the Python environment
      code/             the code checkout, when install.sh cloned it
      data/dataset/     the released dataset (sciexam download)
      data/prepared/    the rebuilt observations; raw/ holds the four files the agents receive
      data/papers/      the reference paper you supply
      runs/             one folder per run, and the last setup of the interactive setup
      state/            the run ledger, the contact and the models added with add-model
      .env              your credentials, readable only by you

Without SCIEXAM_HOME the older defaults hold: the dataset and the state in ~/.cache/sciexam, the
runs, the rebuilt observations and .env in the folder the command runs in. SCIEXAM_DATA,
SCIEXAM_LEDGER, SCIEXAM_PROFILE and SCIEXAM_AGENTS still override single paths.
"""
import os
from pathlib import Path


def home():
    h = os.environ.get("SCIEXAM_HOME")
    return Path(h).expanduser() if h else None


def _cache():
    return Path.home() / ".cache" / "sciexam"


def dataset():
    h = home()
    return h / "data" / "dataset" if h else _cache() / "dataset"


def state():
    h = home()
    return h / "state" if h else _cache()


def runs():
    h = home()
    return h / "runs" if h else Path("sciexam_runs")


def prepared():
    h = home()
    return h / "data" / "prepared" if h else Path("sciexam_prepare")


def papers_parent():
    """The folder that receives papers/<the paper>.pdf (fetch-paper's task folder)."""
    h = home()
    return h / "data" if h else Path("task")


def env_file():
    h = home()
    return str(h / ".env") if h else ".env"
