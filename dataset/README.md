---
pretty_name: SciExam-ENSO
license: other
license_name: mit-and-cc-by-4.0
license_link: LICENSE.md
language:
- en
tags:
- climate
- enso
- agents
- benchmark
- scientific-modeling
configs:
- config_name: runs
  data_files: runs.csv
- config_name: checkpoints
  data_files: checkpoints.csv
- config_name: ablation_candidates
  data_files: ablation/candidates.csv
---

# SciExam-ENSO dataset

Records, models and grader references of SciExam-ENSO, a benchmark in which LLM agents spend
six hours of eligible time turning raw ocean and atmosphere observations into a low-order
stochastic model of the El Nino-Southern Oscillation (ENSO). Each submitted model is a
`model.py` with a `step(state, dt, t, rng)` function and a `params.json`. Hidden graders score it
on statistical properties, dynamical consistency (state reconstruction with an ensemble Kalman
smoother) and predictive skill on the held-out years 2015 to 2024.

The companion code (`sciexam` package) grades any model in this dataset inside a sandbox,
regrades the released models and checkpoints against the records here and regenerates the
paper's tables and figures.

## Layout

| path | content |
|---|---|
| `runs.csv` | one row per released run (12 ranked runs, 3 extra Claude Fable 5.1 runs under changed conditions, and the reference model) |
| `checkpoints.csv` | one row per graded checkpoint of every released run |
| `models/final/<system>/` | the final model of each of the 12 ranked runs |
| `models/checkpoints/<system>/round_NN/` | every graded checkpoint of the 12 ranked runs |
| `models/fable_conditions/<condition>/round_NN/` | best and final checkpoint of each extra Claude Fable 5.1 run |
| `models/reference/5d-reference/` | the published five-variable model of Zhang, Chen, Vialard and Fang (2024), in the submission interface (reference only, not ranked) |
| `grader_obs/` | observation references read only by the grader (never mounted where a submission runs) |
| `task/` | the agent-facing task files, unchanged except that the reference paper is not included (`task/papers/CITATION.md`) |
| `ablation/` | simplified models from the structural ablation that the paper reports, with `candidates.csv` |
| `scores/` | the paper's tables and quoted values as CSV |
| `evidence/` | per-run evidence behind the evidence columns of `runs.csv`, and `checkpoint_times.csv` (eligible time of every checkpoint) |
| `figure_data/` | derived values the figure scripts need that are not in the tables above |
| `LICENSE.md` | the license terms of this dataset |
| `MANIFEST.sha256` | sha256 of every other file |

Every model folder holds `model.py`, `params.json`, usually `nondim_scales.json` and
`model_card.md` (the agent's own description), and a `meta.json` written for this dataset (run,
round, role and calendar offset). Agent-written files are unchanged.

## Scores

All scores follow one rule set.

* statistics: five groups (distribution, seasonal variance, autocorrelation, event frequencies,
  event diversity) from a 2100-year free run after 200 years of burn-in, combined as
  `0.5 * mean + 0.5 * min` over the groups
* physics: mean Nash-Sutcliffe efficiency of five reconstructed variables (two assimilation tests)
* predictivity: forecast skill against persistence, `0.7 * all targets + 0.3 * extreme targets`
* composite: `0.3 * statistics + 0.3 * physics + 0.4 * predictivity`, only for models whose 50-year
  free run stays finite

**Calendar alignment.** The task defined model time `t` in months from the start of the run but
not which calendar month `t = 0` is. Each run is scored under the convention stated by its own
agent: the model's `step` receives `t + s`, where `s` is `calendar_offset` in the tables (`-1`
when the agent placed January at `t = 0`, otherwise `0`). Physics and predictivity are run at
`t + s`. Because `s` is a whole number of months, the statistics are computed from the free run
started at `t = 0` with its month labels shifted by `-s` months. `calendar_offset_source` says
whether the offset was stated by the agent (`stated`), read from its fitting code
(`fitting_fallback`), irrelevant because the model has no time dependence (`no_time_dependence`)
or built into the parameters (`built_in`, the reference model).

Scores are stored unrounded where the record is unrounded. Physics and predictivity of runs whose
calendar offset is 0 are stored at four decimals.

## `runs.csv`

| column | meaning |
|---|---|
| `run_id` | `main/<arm>`, `fable_conditions/<condition>` or `reference/5d` |
| `group` | `main` (ranked), `fable_condition` or `reference` |
| `arm`, `display_name`, `model_id` | internal key, name used in the paper, model identifier at the provider |
| `scaffold`, `route` | agent scaffold and how the model was served |
| `campaign` | the batch of runs the run belongs to |
| `condition`, `condition_description` | information condition of the run |
| `eligible_time_s` | eligible time used (ranked runs) |
| `n_snapshots`, `n_checkpoints_graded` | snapshots taken and checkpoints graded |
| `model_dir` | folder of the final model |
| `calendar_offset`, `calendar_offset_source`, `calendar_offset_judgement` | offset `s`, its source, and whether reading it needed judgement |
| `final_round`, `final_*` | final checkpoint and its composite, statistics, physics, predictivity and the five statistics groups |
| `best_round`, `best_*` | highest-composite checkpoint and the same scores |
| `scaffold_version` to `cost_usd`, `cost_basis`, `evidence_json` | what the run records show (scaffold version, route, provider pin, reasoning effort, clock, context, compactions, use of the reference paper, network condition, cost), each traced in `evidence/<group>__<run>.json` (see `evidence/README.md`) |

## `checkpoints.csv`

`run_id`, `arm`, `round`, `calendar_offset`, `graded`, `is_final`, `is_best`, the scores
(`composite`, `statistics`, `physics`, `predictivity` and the five groups). Kimi K3 took 59
snapshots, of which 56 could be graded. The other runs graded every snapshot.

## `scores/`

| file | used for |
|---|---|
| `leaderboard_final.csv`, `leaderboard_best.csv` | final and best leaderboards with the reference model |
| `fable_conditions.csv` | Claude Fable 5.1 under four conditions |
| `model_summary.csv` | original and simplified composite of each final model |
| `structural_vote.csv` | the structural family each simplified model retains |
| `fable51_simplification.csv` | Claude Fable 5.1 original and simplified model scores |
| `ablation_effects.csv` | single-group removals quoted in the text |
| `fable51_final_forecast_correlation.csv`, `fable51_final_event_counts.csv` | diagnostics of the Claude Fable 5.1 final model (stored at four decimals) |

## `ablation/`

For each final model, the simplified model shown in the paper with its refitted `params.json`, and
the other reductions the structural vote compares. `candidates.csv` gives the scores of the original
and the simplified model under the run's calendar offset, the retained structural family and the
role of the model (the role is also in each folder's `meta.json`):

* `vote representative`: the reduction that fills the agent's cell in the structural vote,
* `also qualifies`: a second qualifying reduction of the other family (GPT-5.5),
* `competing reduction`: the reduction of the other family that the vote compares and that does not
  qualify (Claude Opus 5, DeepSeek V4.1 Flash, DeepSeek V4 Pro). These three have no row in
  `candidates.csv`. Their relative change is recorded in `scores/structural_vote.csv`,
* `automatic endpoint`: the selected reduction of the three agents outside the vote.

The originals are the final models in `models/final/`. The `original_*` columns of `candidates.csv`
and the original row of `scores/fable51_simplification.csv` were computed by the ablation tool in
the same pass as the simplified models, so they can differ from the leaderboard record in
`runs.csv` by up to 5e-4 (Claude Fable 5.1: statistics 0.7142 and composite 0.5154 here, 0.7145 and
0.5155 in `runs.csv`). The paper prints the `runs.csv` values for the original models.
`sciexam ablation` regrades every simplified model and checks it and the structural vote against
these records. A few simplified models use
`numba`.

## `figure_data/`

Values that `sciexam figures` needs and that the tables above do not hold:

* `fable51_final_diagnostics.json`: diagnostics of the final Claude Fable 5.1 model (PDF, seasonal
  variance and autocorrelation curves with their ranges and the observed curves, simulated event
  peaks, and the reconstruction ensembles of the two assimilation tests, 1980 to 2014).

## `grader_obs/`

| file | content | source |
|---|---|---|
| `indices_truth.nc` | the five monthly indices 1980 to 2024, including the held-out years | NOAA ERSST v5, NCEP GODAS and NCEP/NCAR Reanalysis 1, processed as `task/data_processing.md` prescribes |
| `stat_obs_sst_70yr.npz` | Nino 3 and Nino 4 SST anomalies, 1950 to 2019 | `obs_data.mat` of the Zenodo record of Chen and Fang (CC BY 4.0), whose Nino indices derive from HadISST1.1 |
| `obs_bivariate_events.npz` | peak strength and longitude of the observed El Nino events | the ERSST v5 field distributed by the Asia-Pacific Data-Research Center |
| `reg_te_tc_hw_ssta.mat`, `lon_sst.mat` | regression of the equatorial SST anomaly on the two temperature indices, and its longitudes | files of the Zenodo record of Chen and Fang (CC BY 4.0), unchanged |

## Not included

Raw gridded observations (public NOAA products, rebuilt by `sciexam prepare-data`), the reference
paper given to the agents (Jin, 1997, cited in `task/papers/`, fetched and checked by
`sciexam fetch-paper`), session transcripts, agent workspaces and logs.

## License

* The agent-written code, every `model.py` in `models/` and `ablation/`, is released under the MIT
  License, the license of the companion code (`LICENSE.md`).
* Everything else (parameters, model cards, scores, run records, evidence, task text, derived
  observation files) is released under the Creative Commons Attribution 4.0 International License
  (CC BY 4.0), subject to the third-party terms below. We grant rights only to the extent that we
  hold them.

## AI-generated content

Every file in `models/` except `models/reference/` and every file in `ablation/` was written by an
AI system, not by a person: the system named in `meta.json` and `runs.csv` (Claude Fable 5.1, Claude
Opus 5, GPT-6 Astra, GPT-5.6-Sol, GPT-5.5, Gemini 3.8 Flash, Kimi K3, DeepSeek V4.1 Flash, DeepSeek
V4 Pro, MiniMax-M3, GLM-5.2 or Qwen3-Max) working as an autonomous agent. The simplified models in
`ablation/` are those agent models with refitted coefficients. The agents ran through the providers'
subscription products (Anthropic Claude Code, OpenAI Codex, Google Antigravity) or through an API
gateway to the providers. The providers' terms may restrict using these outputs to develop competing
models. This dataset is a benchmark record and is not intended as training data.

## Third-party data and attributions

* **ERSST v5.** Huang, B., P. W. Thorne, V. F. Banzon, T. Boyer, G. Chepurin, J. H. Lawrimore,
  M. J. Menne, T. M. Smith, R. S. Vose and H.-M. Zhang, 2017: NOAA Extended Reconstructed Sea
  Surface Temperature (ERSST), Version 5. NOAA National Centers for Environmental Information,
  doi:10.7289/V5T72FNM. Also Huang et al., 2017, J. Climate, 30, 8179 to 8205. The field behind
  `obs_bivariate_events.npz` was obtained from the Asia-Pacific Data-Research Center (APDRC) of the
  International Pacific Research Center, University of Hawaii.
* **NCEP GODAS.** Behringer, D. W., and Y. Xue, 2004: Evaluation of the global ocean data
  assimilation system at NCEP: The Pacific Ocean. Eighth Symposium on Integrated Observing and
  Assimilation Systems for Atmosphere, Oceans, and Land Surface, AMS 84th Annual Meeting.
* **NCEP/NCAR Reanalysis 1.** Kalnay, E., and coauthors, 1996: The NCEP/NCAR 40-year reanalysis
  project. Bull. Amer. Meteor. Soc., 77, 437 to 471.
* **NOAA PSL.** GODAS, NCEP/NCAR Reanalysis 1 and ERSST v5 data provided by the NOAA PSL, Boulder,
  Colorado, USA, from their website at https://psl.noaa.gov.
* **Zenodo record of Chen and Fang.** Chen, N., and X. Fang: Model programs for "A Simple Multiscale
  Intermediate Coupled Stochastic Model for El Nino Diversity and Complexity", Zenodo,
  doi:10.5281/zenodo.6797996, licensed under CC BY 4.0. The files `obs_data.mat` (behind
  `stat_obs_sst_70yr.npz`), `reg_te_tc_hw_ssta.mat` and `lon_sst.mat` come from this record, and the
  grader's statistics curves, event definitions and event counts follow its programs.
* **HadISST1.1.** The Nino indices of that record derive from HadISST1.1. HadISST data were obtained
  from https://www.metoffice.gov.uk/hadobs/hadisst/ and are (c) British Crown Copyright, Met Office,
  2003, provided under an Open Government Licence
  https://www.nationalarchives.gov.uk/doc/open-government-licence/version/2/. Rayner, N. A., D. E.
  Parker, E. B. Horton, C. K. Folland, L. V. Alexander, D. P. Rowell, E. C. Kent and A. Kaplan, 2003:
  Global analyses of sea surface temperature, sea ice, and night marine air temperature since the
  late nineteenth century. J. Geophys. Res., 108(D14), 4407, doi:10.1029/2002JD002670. See also
  www.metoffice.gov.uk/hadobs.
* **Reference model.** The five-variable model in `models/reference/` implements the model
  identified by Zhang, Y., N. Chen, J. Vialard and X. Fang, 2024: A physics-informed auto-learning
  framework for developing stochastic conceptual models for ENSO diversity. J. Climate, 37(23),
  arXiv:2402.04585 (CC BY 4.0), with the coefficients of its Table 4.
* **Reference paper given to the agents (not included).** Jin, F.-F., 1997: An equatorial ocean
  recharge paradigm for ENSO. Part I: Conceptual model. J. Atmos. Sci., 54(7), 811 to 829,
  doi:10.1175/1520-0469(1997)054<0811:AEORPF>2.0.CO;2.

## Integrity

`MANIFEST.sha256` lists the sha256 of every file. `sciexam download` refuses a copy in which any file
is missing, changed or unlisted.
