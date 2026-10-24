# SciExam for ENSO: code and data

Code and data of **SciExam for ENSO: Can AI Agents Build Climate Models?**

Yinling Zhang, Langchen Liu, Dongbin Xiu, Xueyan Zou, Xu Kuang, Mengdi Wang, Shilong Liu

[Paper](https://arxiv.org/abs/2610.10513) · [Website](https://enso.aisexam.com/) · [Detailed results](https://enso.aisexam.com/results/)

SciExam-ENSO is a benchmark in which LLM agents build low-order stochastic models of
the El Nino-Southern Oscillation from raw observations within a six-hour budget.

| folder | content | license |
|---|---|---|
| `code/` | the `sciexam` package: grader, regrading, structural ablation, figures, observation rebuild and the agent harness. See `code/README.md` | MIT |
| `dataset/` | the released records: runs, checkpoints, agent-built models, simplified models, grader observations and task files. See `dataset/README.md` | CC BY 4.0, with third-party terms listed in `dataset/LICENSE.md` |

## Getting started: run the benchmark yourself

Two commands take you from a fresh computer to a running agent. Everything between them is a
guided checklist that says what it will do before doing it.

```
git clone https://github.com/ylzhang2447/SciExam-ENSO-code.git && sh SciExam-ENSO-code/install.sh
sciexam start
```

### What you need

| | |
|---|---|
| computer | macOS or Linux. An ordinary laptop is enough: the agent spends most of its time waiting for the model |
| Docker | Docker Desktop (macOS) or Docker Engine (Linux), with at least 5 CPUs and 10 GB of memory for each agent you run at once. On Docker Desktop set Memory to 11 GB or more in Settings > Resources (Docker reports a little less than you set) |
| Python | 3.10 or newer. The `python3` that comes with macOS is 3.9: install a newer one with `brew install python@3.12` |
| disk | about 8 GB free for one agent (images, data, results) |
| a model account | an OpenRouter API key, a Claude subscription, a ChatGPT sign-in for Codex, or a Google sign-in for Antigravity, depending on the models you run. Every run is billed to, or counted against, your own account |
| time | a smoke run takes 15 minutes. A full run takes 6 hours of eligible time per agent, and up to 18 hours of wall time when the provider pauses (paused time is credited). The computer must stay awake and online throughout |

You do not need to rent a server. The formal runs used one because they ran many models at once.

### Step 1: install

`install.sh` finds Python 3.10 or newer, asks which folder to keep everything in (press Enter for
`~/sciexam`, or type any path, for example on an external drive), lists what it will do and waits
for your yes. It then creates a Python environment in that folder, installs SciExam and writes the
command `<folder>/sciexam`. It asks separately whether to make `sciexam` work in every terminal
(a link in `~/.local/bin`) and, if that folder is not on your PATH, whether to add one line to
your shell's startup file. Nothing else outside the chosen folder is changed.

### Step 2: `sciexam start`, the checklist

`sciexam start` shows what a run needs, one page at a time. For the first item that is not ready it
either offers to do it, saying first what it will do, or says exactly what only you can do and
checks again. You can leave at any point and nothing is lost: the next `sciexam start` picks up
where you left off.

| item | what `sciexam start` does | what you do |
|---|---|---|
| Docker installed | finds it | install Docker Desktop (it needs your administrator password) |
| Docker running | opens Docker Desktop on macOS and waits for it | start the Docker service on Linux |
| Docker CPUs and memory | shows what Docker has and how many agents it holds at once | raise them in Docker Desktop, Settings > Resources, if needed |
| dataset | copies it from the code checkout and checks the sha256 of every file (seconds) | nothing |
| observation data | downloads the four files the agents received in the formal runs, one 180 MB archive, and checks each against its recorded sha256 | nothing |
| reference paper | opens the publisher's page and picks the PDF up from your Downloads folder | click Download PDF |
| disk | checks the free space | free some if needed |
| model accounts | saves a key you paste (not shown on screen) to `.env`, readable only by you, or the path to a sign-in file | sign in with the provider |

**The reference paper** (Jin 1997, J. Atmos. Sci.) is free to read but under the publisher's
copyright, so we may not ship it, and the publisher's site admits browsers only, so no program may
fetch it. It is the one file you download yourself, and it takes one click: choose download, click
Download PDF on the page that opens, and the checklist finds the file in your Downloads folder on
its own and moves on. The publisher stamps each page of every download with a line
("Downloaded <date>"), so no two downloads have the same bytes. The check therefore compares the
text of the PDF, with the stamp removed, to the text of the copy the agents read: all 19 pages
must match word for word. A different rendering of the article can still be used, and the run
records it.

**The observation data** are the very files the formal runs gave the agents, published as the
[task-data-v1](https://github.com/ylzhang2447/SciExam-ENSO-code/releases/tag/task-data-v1)
release. `sciexam prepare-data --keep-raw` rebuilds them from NOAA instead (106 downloads); NOAA
revises these datasets, so a rebuild may differ, and the run records that too.

### Step 3: set up the run

When the checklist is complete, the run setup opens. It asks:

1. **How to run.** *default* uses the settings of the official leaderboard: each model's reasoning
   effort, a 6 hour budget, the leaderboard's network, and as many agents at once as your machine
   holds, up to three. *customize* lets you choose the effort, the run time, the network and how
   many agents run at once. Any change from the default is recorded, and such a run is ranked
   apart from the official leaderboard.
2. **Which models.** The 12 models of the paper, any model you added with `sciexam add-model`
   (OpenRouter, subscriptions, or a local OpenAI-compatible server), and the condition runs.
3. **Your contact** (email or GitHub handle), asked once and remembered, for the leaderboard.

It then checks everything again (dataset, Docker, compute, disk, data and paper, credentials) and
shows a summary with the equivalent command line. Nothing starts until you choose: a 15-minute
**smoke run** of the same setup first (recommended, it checks the containers, the credentials and
the network), or the **full run**. After a smoke run, the next `sciexam start` offers to repeat the
setup, which opens at the summary, so the full run is two keys away.

### Step 4: after the run

Each run gets a folder in `<folder>/runs/`. Its results are sealed when the run ends, so any later
change to them is detected. Grade it, and turn it into a leaderboard submission:

```
sciexam grade-run ~/sciexam/runs/<run> --offset 0
sciexam package-run ~/sciexam/runs/<run> --out my-submission
sciexam verify-submission my-submission
```

The submission records the model, its settings, the compute it ran on, the paper and data it was
given, and how many runs you made of the same system. See `code/README.md`, "Submitting a run to
the leaderboard".

### Where everything is kept

```
~/sciexam/                  (or the folder you chose)
  sciexam                   the command
  env/                      the Python environment
  code/                     the code, when install.sh downloaded it
  data/dataset/             the released dataset
  data/prepared/raw/        the four observation files
  data/papers/              the reference paper
  runs/                     one folder per run
  state/                    the run ledger, your contact, models you added
  .env                      your credentials, readable only by you
```

To uninstall, delete the folder (and `~/.local/bin/sciexam`, if you made the link).

### If something goes wrong

* **`pip install` fails with a message about setup.py.** The Python is too old (macOS ships 3.9).
  Install Python 3.12 and run `install.sh` again.
* **The compute check says Docker holds 0 agents.** Docker has less than 5 CPUs or 10 GB. Raise
  them in Docker Desktop, Settings > Resources (Memory 11 GB or more), Apply & restart.
* **The paper is not picked up.** Make sure the PDF went to your Downloads folder, or choose
  "it is already downloaded somewhere" and drag the file into the terminal.
* **A menu looks garbled.** Make the terminal window a little larger; the menus redraw to fit it.
* **You want the command line instead.** Every choice of the setup is a flag of
  `sciexam run-agent`; the summary prints the exact command.

## Quickstart

```
python3 -m venv .venv && . .venv/bin/activate
pip install -e code                        # Python 3.10 or newer; grading also needs Docker
sciexam download --local dataset           # checks the sha256 of every data file
sciexam grade --split final --jobs 5       # regrades the 12 final models and the reference model
sciexam grade-sample dataset/models/final/claude-fable-5.1 --in-process   # one model, no Docker
```

The package needs Python 3.10 or newer. On macOS the built-in `python3` is 3.9, and its old pip
fails with a message about `setup.py`: create the environment with a newer Python instead, for
example `python3.12 -m venv .venv` (Homebrew: `brew install python@3.12`).

Rerunning an agent, grading a new run and rerunning the Claude Fable 5.1 condition runs are
described in `code/README.md`.

## Citation

```bibtex
@misc{zhang2026sciexamensoaiagents,
  title         = {SciExam for ENSO: Can AI Agents Build Climate Models?},
  author        = {Yinling Zhang and Langchen Liu and Dongbin Xiu and Xueyan Zou
                   and Xu Kuang and Mengdi Wang and Shilong Liu},
  year          = {2026},
  eprint        = {2610.10513},
  archivePrefix = {arXiv},
  primaryClass  = {cs.AI},
  url           = {https://arxiv.org/abs/2610.10513}
}
```

Contact: Shilong Liu (slongliu86@gmail.com)
