# SciExam-ENSO

Code for SciExam-ENSO, a benchmark in which LLM agents build low-order stochastic models of the
El Nino-Southern Oscillation (ENSO) from raw observations within a six-hour budget. This
repository holds the grader that scores a submitted model, the tools to fetch and verify the
released dataset, the regrading of every released model and checkpoint, the structural ablation,
the figure scripts, the rebuild of the observational indices and the harness that reruns an agent.

A submission is a folder with `model.py`, which defines `ENSOModel(params)` with a method
`step(state, dt, t, rng)`, and `params.json`. The grader calls nothing else. It scores the model on

* statistical properties of a 2100-year free run against Nino 3 and Nino 4 observations,
* dynamical consistency, as the skill of an ensemble Kalman smoother driven by the model to
  reconstruct withheld variables (1980 to 2014),
* predictive skill of ensemble forecasts on the held-out years 2015 to 2024 against persistence,

and combines them as `0.3 * statistics + 0.3 * physics + 0.4 * predictivity`. A model whose
50-year free run does not stay finite is not scored. `sciexam/grader/` documents every constant.

## Quickstart

```
pip install -e .                       # add '.[figures]' for the figures, '.[numba]' for in-process grading of numba models
sciexam download --local /path/to/sciexam-enso-dataset
sciexam grade --split final --jobs 5
```

1. `pip install -e .` installs the package and the `sciexam` command (Python 3.10 or newer). Grading,
   the refit and the agent harness also need Docker.
2. `sciexam download --local PATH` copies the dataset into `~/.cache/sciexam/dataset` (or
   `$SCIEXAM_DATA`, or `--data-dir DIR` on any command) and checks the sha256 of every file against
   its `MANIFEST.sha256`. Every other command checks the manifest again before it reads the data.
3. `sciexam grade --split final` builds the grading image from `environment/Dockerfile` on first
   use, grades the final model of each of the twelve ranked runs and the reference model in the
   sandbox, and compares every score with the released record at the four decimals the paper prints.

## Commands and measured runtime

Measured on one host with 16 vCPUs (Intel Xeon 6975P-C), 30 GB of memory and Docker 29.7. Each
grading job uses two containers of 2 CPUs each. The checkpoint regrade and the ablation ran at the
same time (five grading jobs in total), so each is a little slower alone than on an idle host.

| command | what it does | time |
|---|---|---|
| `sciexam build-image` | builds the grading image (223 MB compressed, 949 MB on disk) | 43 s |
| `sciexam download --local PATH` | copies and verifies the dataset | a few seconds |
| `sciexam grade-sample DIR` | grades one submission folder | 40 to 60 s, GPT-6 Astra checkpoints up to 26 min |
| `sciexam grade --split final --jobs 5` | regrades the 12 final models and the reference model | 11.7 min |
| `sciexam grade --split checkpoints --jobs 4` | regrades all 637 released checkpoints | 4.6 h, set by the 46 GPT-6 Astra checkpoints (up to 26 min each, two at a time). The other 591 take about 3.3 h |
| `sciexam ablation --jobs 1` | regrades the 16 simplified models and checks them and the structural vote against the records | 14 min (one GPT-6 Astra model, 2.6 min, with numba) |
| `sciexam ablation --refit fable51/S3_affine_periodic_drift` | reruns the teacher simulation and refit of one simplified model | 20 s |
| `sciexam figures` | regenerates the data figures (PDF and PNG) | about 3 s |
| `sciexam prepare-data` | downloads ERSST v5, GODAS and NCEP/NCAR R1 (344 MB) and rebuilds the five indices | 4.9 min (download 292 s, processing 0.5 s) |
| `sciexam fetch-paper --file PDF` | checks the sha256 of the reference paper and places it in a task folder | under 1 s |
| `sciexam run-agent --agent agents/ARM.yaml --dry-run` | assembles the agent container, task tree, prompts and network policy without starting an agent | under 0.1 s |
| `sciexam run-agent --agent agents/ARM.yaml --net-check` | starts the arm's networks and proxy, shows that a non-allowlisted host is refused and PyPI is reachable, removes everything | about 5 s |
| `sciexam run-agent --agent agents/ARM.yaml --hours 6` | reruns one agent for the full budget (needs your own credentials) | 6 h of eligible time |
| `sciexam list-agents` | lists the arms, the credential each needs and the reasoning effort levels each accepts | under 1 s |
| `sciexam run-agent --agent kimi,gpt56 --parallel 2 --effort kimi=high,gpt56=low --hours 6` | reruns several arms, two at a time, each at the chosen effort | 6 h per arm, arms in parallel |
| `sciexam grade-run RUN_DIR --offset S` | grades every checkpoint of a run and reports its final and best scores | about 40 s per checkpoint and job |

## Grading

```
sciexam grade --split final [--arm gpt55,kimi] [--jobs N]
sciexam grade --split checkpoints [--arm X] [--jobs N] [--slow-max 2] [--out DIR]
sciexam grade-sample path/to/model_dir                 # offset from meta.json, else 0
sciexam grade-sample path/to/model_dir --offset -1     # the model's step receives t - 1
```

`--split checkpoints` grades every checkpoint whose files are released: all graded checkpoints of
the twelve ranked runs and the best and final checkpoints of the three extra Claude Fable 5.1 runs.
Results are written one JSON per checkpoint into `--out` (default `sciexam_results/checkpoints`).
A second invocation with the same `--out` reuses what is there, so an interrupted run continues
where it stopped. The command then compares every score with `checkpoints.csv` and re-selects the
best checkpoint of each run from the regraded composites (a tie goes to the earlier checkpoint). `--slow-max` limits how
many GPT-6 Astra checkpoints (about ten times slower than the others) run at the same time.

Each result is printed as `match` (equal to the record at four decimals), `within tolerance`
(absolute difference below 5e-5, half a unit of the fourth decimal) or `MISMATCH`. The records are
never changed by a regrade. Physics and predictivity of the runs whose calendar offset is 0 are
stored at four decimals, and their composite is computed from those values, so a regraded composite
can land on the other side of a rounding boundary. On our host all 637 checkpoints agree with the
released records (593 match, 44 within tolerance), all 13 final models match, and the re-selected
best checkpoint equals the recorded one for all twelve ranked runs.

## Calendar convention

The task defines model time `t` in months from the start of the run but not which calendar month
`t = 0` is. The grader reads calendar month `c` (1 = January) at `t = c`. Each released run is
scored under the convention its own agent stated: the model's `step` receives `t + s`, with the
offset `s` taken from the dataset. Physics and predictivity are run at `t + s`. Because `s` is a
whole number of months, the statistics are computed from the free run started at `t = 0` with its
month labels shifted by `-s` months. An offset that is not a whole number of months is rejected
with an error. Only the time argument changes. No parameter or line of a model is altered.

## Structural ablation

```
sciexam ablation [--jobs N] [--regrade-originals] [--out DIR]
sciexam ablation --refit fable51/S3_affine_periodic_drift
```

The dataset holds, for each final model, the simplified model shown in the paper and the
reductions the structural vote compares. `sciexam ablation` grades each of them in the sandbox under
its agent's calendar offset and compares it with its record in `ablation/candidates.csv` within an
absolute tolerance of 5e-4 on each score (the three competing reductions, which have no row there,
through their relative change in `scores/structural_vote.csv`, within 0.2 percentage points). It
then applies the screen and the vote of `sciexam/ablation/rules.py` to the regraded simplified
models against the recorded originals and compares every vote cell and the tally with
`scores/structural_vote.csv`. `--regrade-originals` also regrades the final models. Each result is
printed as match, within tolerance or mismatch. The regraded tables go to the output folder only,
never into the dataset. On our host every result agrees with the released records within the
stated tolerance (16 simplified models, largest difference 2e-4), and the vote is 4 linear drift
with multiplicative noise against 5 nonlinear drift with additive noise, as recorded.

* Screen: a simplified model qualifies when its composite is at least 95% of the original
  composite and each component at least 90% of the original component.
* Vote: the nine agents whose final composite is at least 0.33. For each agent the reduction of
  each family (linear drift with multiplicative noise, nonlinear drift with additive noise) is
  screened. When both qualify, the weaker must reach 95% of the stronger. The vote goes to the
  qualifying family with the higher composite.

`--refit` reruns the twin experiment that produced a simplified model's parameters: a
20,000-year simulation of the original model (16 chains, step 0.1 month, seed 1) and an ordinary
least-squares refit of the drift coefficients with the removed terms fixed at zero
(`sciexam/ablation/refit/`). It runs the original agent code, so it runs in a container without
network. It is available for the Claude Fable 5.1 simplification and reproduces the released
parameters to a relative difference of 6e-14.

## Figures

```
pip install -e '.[figures]'
sciexam figures [--out DIR] [--only fig3,fig4,fig5c]
```

| name | figure | reads |
|---|---|---|
| `fig3` | Figure 3, checkpoint scores over eligible time and final scores | `runs.csv`, `checkpoints.csv`, `evidence/checkpoint_times.csv` |
| `fig4` | Figure 4, diagnostics of the final Claude Fable 5.1 model | `figure_data/`, `scores/`, `grader_obs/` |
| `fig5c` | Figure 5c, structural vote of the simplified models | `scores/structural_vote.csv`, `runs.csv` |

Figure 1, the overview illustration of the paper, is not distributed (it contains third-party logos and a
page image of the reference paper). Its data are the final composites in `runs.csv`.

## Observational indices and the reference paper

```
sciexam prepare-data [--out DIR] [--last-year 2024] [--keep-raw]
sciexam fetch-paper [--file PDF]
```

`prepare-data` downloads ERSST v5, GODAS potential temperature and zonal current and NCEP/NCAR
Reanalysis 1 850 hPa zonal wind for 1980 to 2014 through the NOAA PSL OPeNDAP service, rebuilds the
five monthly indices as `task/data_processing.md` prescribes, and compares them with the grader's
reference within the tolerance of the task's data gate (0.02 degC for the temperatures, 0.40 m,
0.006 m/s and 0.05 m/s). On our host every index agrees to better than 7e-5. `--last-year 2024`
also rebuilds the held-out years.

The agents received Jin (1997) as a PDF, which is under the publisher's copyright and is not
distributed. `fetch-paper` prints the citation and the DOI and, with `--file`, checks the sha256 of
your copy against the one the agents used and places it in a task folder.

## Requirements

| | grading and regrading | rerunning an agent |
|---|---|---|
| software | Python 3.10 or newer, Docker, git | the same, plus your own model credentials (`.env`, see `.env.example`) |
| CPU and memory | each grading job starts two containers of 2 CPUs, each capped at 4 GB, so plan 4 CPUs and up to 8 GB per job (`--jobs`) | each agent container is capped at 5 CPUs and 10 GB (see Compute below), so Docker needs 5 CPUs and 10 GB per agent running at once, plus an allowlist proxy (256 MB) and, for OpenRouter arms, a LiteLLM gateway |
| disk | about 1 GB for the grading image and 20 MB for the dataset | the agent and gateway images of the arms you run, and the run folders: a run checks for 5 GB plus 2 GB per agent free before it starts |
| network | only to fetch packages and images once | the model endpoint of the arm's route and PyPI, through the allowlist proxy |
| time | see the table above | 6 h of eligible time per run. Provider pauses are credited, so the wall time can reach 18 h (`max_wall_multiple` 3) |
| cost | none | every run is billed to, or counted against, your own account |

Hosts. The reference host is Linux on x86_64. Every image is built and run for `linux/amd64`
because `environment/requirements.lock` and the agent image pin x86_64 builds by sha256, so the
released numbers come from that platform. On an arm64 host (Apple Silicon) Docker runs the same
images under emulation: the numbers are the same, the runs are slower. On an Apple M-series Mac
(8 CPUs and 8 GB given to Docker), `sciexam grade --split final --jobs 1` reproduced all 13
records, with about 6 min per model instead of under 1 min, and GPT-6 Astra took 71 min, past the
default 3600 s limit. Pass `--timeout 14400` there. `SCIEXAM_PLATFORM` overrides
the platform, at the cost of exactness and, for the grading image, of the pinned hashes. Windows
with WSL 2 and Docker has not been tested.


### Compute

The formal runs shared one host of 16 vCPUs and 30 GB among at most three agents at a time, with
no cap on the agent container. Each agent's share of that host is the spec: every agent container
runs with `--cpus 5 --memory 10g`, so running several agents at once gives each the same compute on
any machine. Before a run starts, Docker's CPUs and memory must hold one cap for each agent running
at once (the formal host holds three, a laptop with 8 CPUs and 16 GB holds one), and the disk of the
run folders must have room. On Docker Desktop, raise its CPUs and memory in Settings > Resources.
The interactive setup runs as many agents at once as the machine holds, up to three. During a run
`results/resources.jsonl` samples the agent container (CPU, memory, processes) and the free disk
every minute and ends with the count of out-of-memory kills in the container. `run_meta.json`
records the spec, the host and how many agents ran at once, and the seal covers both.

## Rerunning the benchmark

A full rerun of one system takes four steps: rebuild the observations the agents receive, supply
the reference paper, run the agent for six hours of eligible time, and grade its checkpoints.

```
cp .env.example .env                                   # fill in your own credentials
sciexam prepare-data --keep-raw --out prepared         # the four raw data files, in prepared/raw
sciexam fetch-paper --file /path/to/jin1997.pdf        # checks your copy of the reference paper
sciexam run-agent --agent agents/fable51.yaml --task-data prepared/raw --paper /path/to/jin1997.pdf --dry-run
sciexam run-agent --agent agents/fable51.yaml --task-data prepared/raw --paper /path/to/jin1997.pdf --smoke
sciexam run-agent --agent agents/fable51.yaml --task-data prepared/raw --paper /path/to/jin1997.pdf --hours 6
sciexam grade-run sciexam_runs/fable51-MMDD-HHMM --offset 0
```

`--dry-run` starts nothing. `--smoke` is a 15-minute check of the containers, credentials and
network, with short phase caps, and is not comparable with the paper. `grade-run` grades every
checkpoint in the run's `results/snapshots` in the sandbox, writes one JSON file per checkpoint and a
`summary.json`, and prints the final checkpoint (the one the paper ranks), the best checkpoint and
where the final model would rank next to the released final models and the reference model.

`--offset` is the calendar convention the agent states for its model, as described under
[Calendar convention](#calendar-convention): 0 if the model reads calendar month c at `t = c`
(1 = January), -1 if `t = 0` is January. Read it from the agent's model card or code docstring.
The paper graded each released run under its stated convention (`runs.csv` column
`calendar_offset`).

### Evaluating a model the paper did not run

```
sciexam add-model --route openrouter --model qwen/qwen3-coder
sciexam add-model --route local --model llama-4-70b --api-base http://localhost:8000/v1 \
    --context-tokens 131072 --name "Llama 4 70B"
sciexam run-agent --agent openrouter:qwen/qwen3-coder --dry-run     # adds the model on first use
```

`add-model` writes an arm configuration for the new model from the paper's latest run on its route
and changes only the model, so the run follows the paper's protocol (budget, lifecycle, tool
envelope, network and context policy) and its submission passes the protocol check. The interactive
setup offers the same as "+ add a model" at the end of its agent list. Configurations are kept in
`~/.cache/sciexam/agents` (or `SCIEXAM_AGENTS`), and `list-agents` marks them "added".

| route | the model is reached through | template |
|---|---|---|
| `openrouter` | OpenRouter, via the LiteLLM gateway (`OPENROUTER_API_KEY`). The id is checked against OpenRouter's public model list. No provider is pinned, unlike the paper's runs | DeepSeek V4.1 Flash |
| `claude` | the Claude Code subscription client | Claude Fable 5.1 |
| `codex` | the Codex subscription client | GPT-6 Astra |
| `antigravity` | the Antigravity client | Gemini 3.8 Flash |
| `local` | any OpenAI-compatible endpoint (vLLM, Ollama, a lab server), via the LiteLLM gateway. An endpoint on this machine is reached as `host.docker.internal`; `LOCAL_MODEL_API_KEY` is passed if the server needs a key | DeepSeek V4.1 Flash |

Two checks guard the gateway routes, where a model the paper did not run may behave differently
from the paper's:

* Context window. The paper's runs compact their context at 200,000 tokens. On the OpenRouter
  route the model's window is read from OpenRouter, and on the local route `--context-tokens` gives
  it. A window smaller than 200,000 tokens sets the compaction threshold to 80% of it and is
  recorded under `declared` in the configuration: the run is valid, ranked apart from the paper,
  and its leaderboard name says so ("Llama 4 70B (131k context)").
* Tool calls. The agent acts only through tool calls, which LiteLLM translates for the model but
  which the model itself must make. Before the budget starts, `run-agent` sends one tool-call
  request through the gateway and stops, with advice, if the model answers without one. Serve a
  local model with tool calling on (for vLLM, `--enable-auto-tool-choice` and the model's
  `--tool-call-parser`; for Ollama, a model with the tools capability).

The harness itself does not change for these routes: they run Claude Code through the LiteLLM
gateway exactly as the paper's OpenRouter systems did. A local server has no provider quota, so its
errors count as failures, and a slower model makes fewer turns in the same budget.

A model that needs a newer client than the template pins needs `scaffold.version` and
`scaffold.binary_sha256` updated in its configuration, which the image build checks; that changes
the protocol, and the submission check then reports it.

### Interactive setup

```
sciexam run-agent
```

Without `--agent`, on a terminal, `run-agent` asks for the run one step at a time instead of taking
flags: how to run, the agents, and the task data and paper. How to run is default, the official
leaderboard's settings (its reasoning effort, run time and network, up to 3 agents at a time), or
customize, which asks for the reasoning effort of each agent, the run time, the network and how
many agents run at once. Before it offers to start, it runs the checks of
`--dry-run` (the dataset, Docker, the task data and paper) and shows which credentials are set
(never their values), then a summary and the equivalent command line for scripts. It starts only
when you choose the full run, or a 15-minute smoke run of the same setup; the default is to go
back. Arrow keys move, Enter chooses, Space ticks agents, the left
arrow or `b` goes back a step and `q` quits. On a terminal without raw key input, or with
`NO_COLOR` or `SCIEXAM_PLAIN` set, the same questions are numbered prompts.

The setup that was started is saved to `sciexam_runs/last_setup.json`. The next start offers to
repeat it, or to start new, which keeps the data paths and the contact. A repeated setup opens at
the summary, with every earlier step one step back and its answers kept, so the full run follows a
smoke run in two keys.

Custom settings map to these flags, each recorded as not comparable with the official leaderboard:

| setting | flag |
|---|---|
| run time per agent | `--hours H` |
| network: the model endpoint only, no PyPI | `--network no-pypi` |
| network: the paper's hosts plus others | `--allow-host data.example.org` (repeat or comma separate) |

The web conditions use the research proxy and take neither network flag.

### Several arms and reasoning effort

```
sciexam list-agents
sciexam run-agent --agent kimi,gpt56,opus5 --parallel 2 --task-data prepared/raw --paper PDF --hours 6
sciexam run-agent --agent kimi,gpt56 --effort kimi=high,gpt56=low --task-data prepared/raw --paper PDF --hours 6
sciexam run-agent --agent fable51 --effort high --dry-run
```

`--agent` takes a config path or an arm key, and several of them, comma separated or repeated.
With more than one arm, `--parallel N` runs at most N at a time. Each arm runs as its own
`sciexam run-agent` process with its own containers and networks, writes its run folder to
`--batch-dir` (default `sciexam_runs/batch-<time>`) and its output to `<arm>[-<effort>].log`
there, and `batch.json` records the exit code of each. `--dry-run`, `--net-check` and `--smoke`
work on a batch too. Grade each run afterwards with `sciexam grade-run`.

`--effort` chooses the reasoning effort: `low`, `medium` or `high`, one level for every arm, or
per arm as `kimi=high,gpt56=low` (`all=medium` sets the arms not named). Without it each arm
runs at the level of its formal run. `sciexam list-agents` shows that level and how each scaffold
receives another one:

| scaffold | how the level is set |
|---|---|
| Claude Code, subscription arms | the `--effort` flag, as in the formal runs |
| Claude Code, OpenRouter arms | the formal runs passed no flag and ran at the CLI default, high. `high` reproduces that exactly; `low` and `medium` add the flag, which LiteLLM forwards to the upstream model. Whether a provider honors it depends on the provider |
| Codex | `model_reasoning_effort` in the run's `config.toml` |
| Antigravity | the model variant: the level is the suffix of the model id, so `--effort low` selects `gemini-3.8-flash-low`, which must exist in your Antigravity CLI |

A run at a level other than its formal run prints `CHANGED ... not comparable with the paper` in
the dry run, and its provenance records `reasoning.paper_effort` and
`reasoning.comparable_with_paper: false`.

### What the harness does

`agents/<arm>.yaml` records, for each of the twelve ranked runs, the scaffold and its version, the
model identifier, the route (subscription product or API gateway), the provider pin, the reasoning
effort, the context policy and the 21,600 s eligible budget, each value traced to the run records
in `runs.csv` and `evidence/`. `run-agent` wraps the harness of the formal runs with the same
agent-facing prompts. The harness keeps the lifecycle of the formal runs: a
data phase with a data gate, the modeling phases, a snapshot of the submission every 300 s,
pauses credited for provider quota and service interruptions, and the fixed 21,600 s budget.
`--dry-run` prints the arm summary, the task tree with the sha256 of each file, the image builds,
the network policy and container spec, the first command line, which credentials are set (never
their values) and every prompt with its sha256. A real run also needs the four raw data files
(`sciexam prepare-data --keep-raw`, then `--task-data OUT/raw`) and the reference paper
(`--paper PDF`).

The agent container has no internet access except the model endpoint of its route and Python
packages from PyPI, through an allowlist proxy. The proprietary command-line clients (Claude Code,
Antigravity) are not part of this repository: `environment/agent/Dockerfile` installs them at build
time from their official sources at a pinned version with a sha256 check, and each user signs in
with their own account.

## Submitting a run to the leaderboard

```
sciexam package-run sciexam_runs/kimi-1012-0930 --out my-submission
sciexam verify-submission my-submission
```

A run carries what its submission needs, fixed when it starts so that nothing has to be
remembered after six hours: `run-agent` writes into `run_meta.json` the leaderboard name (the
arm's display name, followed by any setting changed from the paper), the contact (`--contact`, or
asked once by the interactive setup and kept in `~/.cache/sciexam/profile.json`), and how many full
runs of the same system, this one included, the run ledger `~/.cache/sciexam/runs.jsonl` holds.
The calendar offset is left to the maintainers, who judge it from the model as the paper did, and
the checks grade both conventions. `package-run` options override any of these.

Every checkpoint is hashed when it is written and chained to the one before it, and when the run
ends `run-agent` seals the results folder (`SEAL.json`: the sha256 of every file and the last chain
value). `package-run` refuses a folder changed, added to or removed from after its run.

`package-run` copies from the run folder only what the leaderboard needs: the final checkpoint
(`final/`), every checkpoint (`checkpoints/round_NN/`), the run records and the seal (`logs/`), the
arm configuration (`agent.yaml`), `metadata.json` and `MANIFEST.sha256`. It never copies the agent
workspace, which holds your sign-in files, and it stops without writing anything if a copied file
contains one of your credential values or a common secret pattern.

`verify-submission` runs the checks the maintainers run, and prints each as `ok`, `decl` or `FAIL`:

| check | passes when |
|---|---|
| manifest | every file matches `MANIFEST.sha256` and none is unlisted |
| seal | every checkpoint and log matches the seal written when the run ended, and the checkpoints reproduce its chain |
| arm configuration | `agent.yaml` follows the protocol of a released arm. A new model may change its model, names and scaffold version, not the budget, lifecycle, tool envelope, network or context policy |
| prompts | every agent-facing text has the sha256 of this harness |
| scaffold and model, lifecycle | the run used the configuration in `agent.yaml` and the formal lifecycle (no smoke runs) |
| budget, network, reasoning effort | the paper's settings, or `decl` when the run recorded a change (`--hours`, `--network`, `--allow-host`, `--effort`) |
| run completion | the run finished its full eligible budget |
| compute | the agent container had the spec's cap (5 CPUs, 10 GB), on a host that held every agent running at once |
| compute samples | `resources.jsonl` sampled the run throughout, and the disk never came within 1 GB of full. Peak CPU and memory and any out-of-memory kills inside the cap are reported |
| checkpoints | one checkpoint per snapshot event, and `final/` is the last one |
| egress log | every connection went to a host on the allowlist |
| regrade | the final model scores in the sandbox, at the stated calendar offset or at both 0 and -1 (and matches `claimed_scores` in `metadata.json`, if given) |

The verdict is `consistent`, `consistent, declared changes` (ranked apart from the paper's
settings) or `inconsistent`. The run records are written on your own machine, so the checks show
that a submission is internally consistent and reproduces its score, and the seal rules out edits
after the run. They cannot rule out a harness rewritten to record something else. A consistent submission is listed as self-reported, with its run records published for
anyone to inspect, and the maintainers read them before it is listed. Only a run on infrastructure
the maintainers control is listed as verified.

## Rerunning the Claude Fable 5.1 condition runs

```
sciexam run-agent --agent agents/fable51_years_anonymised.yaml --dry-run --task-data OUT/raw --paper PDF
sciexam run-agent --agent agents/fable51_web_literature_and_data.yaml --net-check
sciexam run-agent --agent agents/fable51_web_literature_only.yaml --hours 6 --task-data OUT/raw --paper PDF
```

The three extra Claude Fable 5.1 runs each change one condition of the offline arm
`agents/fable51.yaml`. Their configs carry a `condition:` block, and `run-agent` checks on load
that every other value equals the baseline arm.

| config | task given to the agent | network | tools |
|---|---|---|---|
| `fable51_years_anonymised.yaml` | years replaced by relative labels | allowlist proxy, as every arm | baseline envelope |
| `fable51_web_literature_and_data.yaml` | web research section added | research proxy, literature and data | WebFetch allowed |
| `fable51_web_literature_only.yaml` | web research section added, data sources refused | research proxy, literature only | WebFetch allowed |

* Years anonymised. The task tree is built from the dataset task text and the raw data of
  `prepare-data --keep-raw` (`sciexam/agent/anonymise.py`). Observation years in
  `data_processing.md` and `interface.md` become labels `Y001-01` to `Y035-12`, the product names
  are removed, a note states that the calendar years in the files are synthetic, and the four data
  files are renamed and written fresh with the epoch of their time axis moved by 244 years. Month
  of year, day of month and month lengths are unchanged, which the build checks for every time
  step. Phase 1 is graded on real dates: the agent's labels are translated in a copy outside the
  workspace and the months in the feedback are translated back. The grader needs no change, since
  the model's time argument carries no year and the run is scored under the calendar offset in
  `runs.csv`.
* Web access. `instruction.md` gets the local-file-system sandbox rule and the web research
  section of the condition (`sciexam/agent/assets/conditions/`). The agent container reaches the
  network only through the research proxy (`sciexam/agent/research/`, a mitmproxy addon built
  from `environment/research-proxy/`). It intercepts TLS with a CA generated for the run and
  installed in the agent container, passes the model hosts through undecrypted, and refuses the
  works named in `blacklist.txt` (by identifier, by the document's own identity and by copied
  text, from hashed fingerprints), uploads, requests that carry workspace text, internal
  addresses and anything it cannot decode and read in full. The literature-only policy also
  refuses observational data sources by host, path and file extension. Every decision is logged
  in `results/research/log/decisions.jsonl` and every delivered body is kept next to it.
* List the benchmark's own public pages (results site, repositories) in
  `sciexam/agent/research/benchmark_self.json`, or pass `--benchmark-self FILE`. The released file
  is empty.

`--dry-run` prints the condition's task tree with the sha256 of each file against the file the
original run received, the tree hash, the text diff against the dataset task, the tool envelope,
the network policy and every prompt. `--net-check` on a web condition builds the research proxy,
probes it from a throwaway container (no direct route, TLS through the run's CA, a prohibited
identifier and an upload refused, the data-source rule of the policy, passthrough of the model
host) and removes the containers and networks.

The task text reproduces the original runs byte for byte. Rebuilt raw data differ from the files
the agents received, so the data files and the tree hash differ. Given the original raw files,
the anonymisation reproduces the anonymised data files of the original run byte for byte.

## Sandbox

Submitted code is untrusted. Each grading job starts two containers from the grading image, both
with `--network none`:

* the worker runs `model.py` as an unprivileged user on a read-only root file system, with only the
  staged submission mounted (read only), capped memory, CPU and process count, and no capabilities,
* the scorer holds the observation references and computes the scores, and never sees the
  submission's files.

The host relays the byte streams between the two. The worker receives states and returns states.
Observations used for scoring never reach it, and the random stream is passed across so that the
numbers equal those of an in-process run. `grade-sample --in-process` skips Docker for debugging
and runs the code in the calling Python process.

## Environment and exactness

`environment/Dockerfile` pins the base image by digest and installs Python packages from
`environment/requirements.lock` with `--require-hashes` (numpy 2.5.1, scipy 1.18.0, pandas 3.0.5,
xarray 2026.7.0, netCDF4 1.7.4, numba 0.67.0 for the reference model and some simplified models).
Exact reproduction of the released numbers needs this image. On other numerical libraries a few
models can differ in the last digits.

## Data and licensing

* The code in this repository is released under the MIT License (`LICENSE`).
* The dataset is released under CC BY 4.0, except the agent-written `model.py` files, which are
  under the MIT License like this code. The agent files are AI-generated. The agents ran through the
  providers' subscription products (Anthropic Claude Code, OpenAI Codex, Google Antigravity) or an
  API gateway, and the providers' terms may restrict using the outputs to develop competing models.
* Third-party data keep their terms and need their citations: NOAA ERSST v5 (Huang et al., 2017),
  NCEP GODAS (Behringer and Xue, 2004) and NCEP/NCAR Reanalysis 1 (Kalnay et al., 1996) provided by
  NOAA PSL, the ERSST v5 field distributed by the Asia-Pacific Data-Research Center, HadISST1.1
  (Met Office Hadley Centre, Open Government Licence v2) and the Zenodo record
  doi:10.5281/zenodo.6797996 of Chen and Fang (CC BY 4.0), whose observation files and methods the
  statistics use. The reference model implements Zhang, Chen, Vialard and Fang (2024, J. Climate
  37(23), arXiv:2402.04585). The dataset card lists the full attributions.
* Not included: the reference paper (Jin, 1997, J. Atmos. Sci. 54(7), 811 to 829), the raw gridded
  observations (rebuilt by `prepare-data`), session transcripts, and the proprietary agent clients.
* The API gateway of the OpenRouter arms (`environment/gateway/`) installs `litellm==1.83.9` and
  the open dependencies of its proxy, without the `proxy` extra, which pulls in the proprietary
  `litellm-enterprise` package. Our patch to it ships as a diff with the MIT notice of LiteLLM.

## Layout

```
environment/            grading image: Dockerfile, requirements.in, requirements.lock
environment/agent/      agent image (the proprietary clients are installed at build time)
environment/research-proxy/  web research proxy image of the web conditions
agents/                 one configuration per ranked run and per condition run
sciexam/cli.py          the sciexam command
sciexam/dataset.py      dataset location, download and sha256 verification
sciexam/grader/         integrations, statistics, physics, predictivity, scoring, sandbox, worker
sciexam/ablation/       screen and vote, rescoring, teacher refit
sciexam/figures/        figure scripts
sciexam/prepare/        download and rebuild of the observational indices, reference paper check
sciexam/agent/          agent harness, prompts, network policy, condition runs
tests/                  unit tests (pytest)
```
