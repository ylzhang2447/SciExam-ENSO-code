# Run evidence

The evidence columns of `runs.csv` and the table `checkpoint_times.csv` are read from what the runs
left behind, never from how they were configured. Configuration has been wrong before, so where a
configured value exists it is kept beside the observed one as `configuration_claim`, and every
disagreement is listed under `configuration_vs_evidence` in the run's file.

## Files

| file | content |
|---|---|
| `<group>__<run>.json` | one file per row of `runs.csv`: each value, its evidence pointers, the method, and any UNKNOWN with its reason |
| `checkpoint_times.csv` | `run_id`, `arm`, `round`, `eligible_s` and `wall_s` since task start, and the trajectory line of every snapshot |

## Pointers

Each evidence item is `{root, path, line, field, note}`. Paths are relative to a root, and no absolute
path is recorded.

| root | meaning |
|---|---|
| `run` | the run's archive: its workspace (`trajectory.jsonl`, `run_meta.json`, the agent's session transcripts, `agent_output.txt`). For the two Batch B runs (GPT-5.6-Sol and DeepSeek V4 Pro) only the results copy survives (trajectory, run_meta, agent output, submission) |
| `harness` | the harness state directory of the run host: `report/` (cost guard state, reconciliation), `otel/` (gateway ledger, CLI telemetry, egress proxy log), `snapshots/`, `research/logs/` (research proxy decisions) |
| `sibling:<run_id>` | the `run` root of another released run launched in the same batch, used only for batch-level network evidence |

Transcripts are not released (see the dataset README). The pointers identify the private archive
from which each value was read.

## Methods

**Clock.** `eligible_s` and `wall_s` are the `quota_summary` record of the trajectory. Credited quota
pauses are `eligible_pause` records with credited seconds above zero. A run is complete when its end
status is complete and its eligible time reaches the 21,600 s budget.

**Checkpoint times.** Eligible seconds of a snapshot equal the snapshot time minus the start time,
minus the credited pause seconds settled before it, with the clock frozen while a pause is in flight
(the harness rule). Snapshot record `round r` is folder `round_{r+1}`. For every run the folder times
match the record times within 0.1 s, and the computed values match the harness's own `elapsed_min`
stamp within its 0.1 min rounding.

**Scaffold, route, effort.** The CLI version stamped on the agent's own records (Claude Code
transcripts, Codex `session_meta`, the Codex exec banner). For Antigravity, whose stream carries no
version, the harness probe of the executing binary. Route follows from where the calls went: gateway
ledger rows for gateway arms, Anthropic request ids for `claudesub`, `model_provider openai` for
`codexsub`, the Antigravity usage log and egress proxy for `agy`. Reasoning effort is the effort field
on each Claude Code assistant record, `turn_context.effort` for Codex, and the model variant reported
at each Antigravity conversation start.

**Provider pin.** For gateway arms, the provider named by the OpenRouter generation record of every
call. Subscription arms have no router.

**Context and compactions.** Gateway arms: the largest `prompt_tokens` (uncached plus cached, as
billed) in the gateway ledger over the run window. Claude Code subscription arms: input plus cache
read plus cache creation per API message in the transcript. Codex: `last_token_usage.input_tokens`
per turn. Antigravity: `context_carried` per model call. Compactions are `compact_boundary` records
(Claude Code), `compacted` records (Codex), or compaction events in the CLI telemetry when the
transcript was lost.

**Jin 1997 PDF.** A tool call that touches the PDF (a Read of the file, or a shell command naming it or
a PDF library) counts as a read when it returns at least 1,500 characters containing at least three
of: thermocline, recharge, discharge, zonal, equatorial, Kelvin, Rossby, oscillator, wind stress,
Sverdrup. Every hit was checked by hand. When only CLI telemetry survives, the rule is applied to the
command, success flag and returned size.

**Network condition.** From the agent's own package installs, downloads and web tool calls: a fresh
download from an index means open egress, DNS or connection failures mean none. For the two web
conditions, the research proxy decision log and its loaded policy. For Antigravity, the egress proxy
log. When an agent made no network request, a result from another arm of the same batch is cited and
marked `batch evidence`. With no such arm the value is UNKNOWN.

**Cost.** The ground truth is OpenRouter key usage minus the batch baseline taken at arming, closed
when every arm's billing window closed (`report/cost_guard_state.json`). It is used directly when the
run was the only gateway arm of its batch. Batch A had three gateway arms sharing one account delta
($199.95), so each of them carries its reconciled per-generation sum, which covers 100% of its calls.
Subscription arms have no per-token cost and record their subscription route. Claude Code telemetry
and the account-wide credits endpoint are never used for cost.

## Anonymisation

No username, email, account or key identifier, hostname or IP address appears in these files. Proxy
addresses, container identifiers, account plan fields and telemetry user ids were dropped at
extraction.
