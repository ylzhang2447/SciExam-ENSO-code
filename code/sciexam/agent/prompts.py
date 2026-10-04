"""Every text the agent reads from the harness, byte identical to the formal runs.

Nothing in this module may be reworded, reflowed or re-punctuated. The strings below are
what all twelve ranked runs received, and `sciexam run-agent --dry-run` prints their sha256
so a rerun can be checked against the released record (see PROMPT_SHA256 at the end).

Only the self-evaluation condition is kept. The formal runs never used the feedback or
external-check variants of the Phase 2 brief, so those are not shipped.
"""
import hashlib
import json

# Appended to every prompt of every arm (the harness wraps the agent call once, so no call
# site can omit it).
PERSISTENT_MEMORY_POLICY = (
    "\n\n"
    "Because the working context is bounded and may be compacted, maintain a concise\n"
    "persistent research history in the workspace throughout the run.\n"
    "\n"
    "Use one or a small number of human-readable workspace files, such as\n"
    "research_log.md, state.md, or notes.md.\n"
    "\n"
    "Record information that would be costly to rediscover, including:\n"
    "- important decisions and their rationale\n"
    "- current model/formulation\n"
    "- best results so far\n"
    "- parameter choices\n"
    "- important diagnostics/findings\n"
    "- failed approaches and why they were abandoned\n"
    "- open questions\n"
    "- current TODO / next actions\n"
    "\n"
    "Update the persistent history after meaningful progress or major decisions, and\n"
    "consult it when needed after context compaction or when resuming a line of work.\n"
    "\n"
    "Do not rely only on conversation history for important long-term project state.")


def with_memory_policy(prompt):
    return prompt + PERSISTENT_MEMORY_POLICY


RESUME_PROMPT = (
    "Keep going. Three things that do not change:\n"
    "- Only your BEST snapshot over the whole budget is graded, and snapshots are taken "
    "automatically. A change that makes the model worse cannot cost you anything, so "
    "there is never a reason to protect the current version or to stop early.\n"
    "- The three files existing and matching the interface is the starting condition, "
    "not the finish.\n"
    "- No feedback is coming beyond the checks in diagnostics/, which are read-only. If "
    "they cover one of the three things you are judged on and not the other two, that is "
    "where your grade is going, and it is too late to add a check for it.\n"
    "- Your checks agreeing with observation is not the finish. Nothing here has ever "
    "matched closely, so a check that has stopped complaining has run out of the errors "
    "it can see, which is not the same as there being none.\n"
    "- Change the model, re-run the checks, read what they print. That is the loop.\n"
    "Pick the weakest thing your checks show, change the term of the model that controls "
    "it, and measure it again. Keep the reply short."
)

STALL_PROMPTS = [
    "Your submission has not changed in three resumes. Do not re-verify it and do not "
    "restate what the deliverables contain: whether the files are present and documented "
    "has no effect on your grade. Run your own diagnostics now, find the weakest of the "
    "three things you are judged on, and change the term of the model that controls it.",
    "Your submission still has not changed. Treat the current model as a draft that is "
    "wrong somewhere. If your tests all look acceptable, the likeliest reason is that you "
    "are not testing the right things: check the parts of the task you have measured "
    "least, and check what is actually in diagnostics/ rather than what you remember "
    "concluding. Edit model.py or params.json and re-measure. A change that makes a score "
    "worse is still progress; leaving the file untouched is not.",
    "Local tuning has stopped moving your submission and time still remains, so you will "
    "keep being resumed until the budget runs out. The question is not whether to "
    "continue but what to change. If parameter tuning is exhausted the structure may be "
    "wrong. If "
    "you genuinely have no change left to try, say so in submission/model_card.md under "
    "a heading 'Why I stopped' and state what you would try with more time. Otherwise "
    "edit the model now.",
]


def phase1_prompt(feedback=None):
    p = ("You are in a sandbox for an ENSO conceptual-modeling benchmark. This is "
         "PHASE 1 (data processing). Read instruction.md and data_processing.md, then "
         "process the raw data in data/ into the five monthly indices, writing "
         "submission/processed/indices.csv (columns: time,TC,TE,hW,u,tau) and "
         "submission/processed/processing_notes.md. Follow data_processing.md exactly.")
    if feedback:
        p += f"\n\nFeedback on your previous attempt: {feedback}\nFix and rewrite."
    return p


def phase1_feedback(result):
    """(passed, feedback) from a data-gate result, in the words the formal runs used. A result
    that already carries its feedback (the year-anonymised gate) is passed through."""
    if "feedback" in result:
        return bool(result.get("passed")), result["feedback"]
    if result.get("passed"):
        return True, "PHASE 1 PASSED."
    offs = [f"{k} (largest discrepancy near {v.get('worst_month', '?')})"
            for k, v in result.get("per_index", {}).items() if not v.get("passed")]
    fb = "PHASE 1 NOT PASSED. Off indices: " + "; ".join(offs) + "."
    if not result.get("notes_present"):
        fb += " processing_notes.md is missing."
    return False, fb


# Phase 1 feedback of the year-anonymised condition when the table cannot be graded as
# submitted (sciexam/agent/anonymise.py). The per-index feedback above is used otherwise,
# with the month of the largest discrepancy given as a relative label.
ANON_P1_MISSING = "PHASE 1 NOT PASSED. processed/indices.csv is missing."
ANON_P1_REJECTED = "PHASE 1 NOT PASSED. %s."
ANON_P1_UNREPORTABLE = "PHASE 1 NOT PASSED. The check could not be reported."


def phase2a_prompt(remaining_min):
    return (
        "PHASE 2A (build your instruments), now unlocked. Read instruction.md, "
        "interface.md, and the papers in papers/.\n\n"
        "You get no feedback. Nothing in this workspace scores your model, and nothing "
        "will tell you how you are doing until the run is over. Before you start fitting, "
        "build the checks you will judge your own model by, as scripts under diagnostics/. "
        "Each one should read submission/model.py and submission/params.json, run whatever "
        "it needs, and print what it found. Hold back part of the observed record from "
        "your fitting if you want an honest check.\n\n"
        "When you stop, diagnostics/ is made read-only for the rest of the run. After that "
        "you change the model and re-run these checks; you cannot add to them or rewrite "
        "them. So build the set you want to be judging yourself with for the next several "
        "hours, and while you are still here, edit or delete the ones you do not trust "
        "rather than leaving a near-copy beside them.\n\n"
        "Make each check report how far off the model is, not whether it passed. A check "
        "that prints a verdict stops being useful the moment it says yes: it cannot tell "
        "you that a match is close, or that one part is closer than another, and you will "
        "be reading these for hours after everything obvious has been fixed. Report the "
        "quantity, the observed value and the gap; whether that gap is acceptable is for "
        "you to decide, not for the check to announce.\n\n"
        "Do the reading inside the check. A check that prints a table hands you back the "
        "job of working out what it means, and you will be doing that again on every "
        "iteration for the rest of the run. Have the script find the discrepancy and say "
        "it: which quantity, in which direction, by how much. 'Seasonal variance peaks in "
        "month 11, observed month 1' is a finding; twelve rows of monthly variance is the "
        "raw material for one. Aim for a handful of lines a check, and remember that "
        "everything printed stays in front of you and gets re-read hundreds of times.\n\n"
        "After the run your model is scored by a grader you never see, against "
        "observations you do not have, on three things:\n"
        "  1. Whether a long free run of your model looks like the observed climate.\n"
        "  2. Whether it behaves as a coupled dynamical system rather than a set of "
        "curves that happen to match.\n"
        "  3. Whether it forecasts, from an observed initial state, better than "
        "persistence.\n"
        "Those are descriptions, not metrics. Do not try to reconstruct the grader; decide "
        "for yourself what is worth measuring and measure it.\n\n"
        "Stop when your instruments are ready. Time spent here is time not spent modeling, "
        "and you have about %.0f minutes of budget in total." % remaining_min)


SELF_BLOCK = (
    "You get no feedback. Nothing in this workspace scores your model, and nothing "
    "will tell you how you are doing until the run is over.\n\n"
    "diagnostics/ is now read-only: it holds the checks you built, and it is what you "
    "have to judge yourself by from here. To try something, change model.py or "
    "params.json and re-run the checks. Do not write new evaluation code; you already "
    "decided what to measure, and the point of having fixed it is that your standard "
    "cannot follow your results.\n\n"
    "Your checks agreeing with observation is not the finish. They were built to be "
    "passable, and no model of this kind has ever matched the observed record closely; "
    "when a check stops complaining it means you have run out of the errors that check "
    "can see, not that there is nothing left. Whichever quantity is closest to "
    "matching, there is a gap in it somewhere, and finding where is the work. Keep "
    "your replies short: say what you changed and what the checks reported, and leave "
    "the numbers in their output."
)


def phase2_prompt(remaining_min):
    """The Phase 2B brief, issued once. The resume prompt repeats what has to stay live."""
    body = (
        "PHASE 2 (modeling), now unlocked. Read instruction.md, interface.md, and the "
        "papers in papers/. Build submission/model.py (class ENSOModel exposing "
        "step(state, dt, t, rng) on the 5-var state [TC,TE,hW,u,tau]), "
        "submission/params.json, and submission/model_card.md. Non-dimensionalize using "
        "nondim_scales.json. Do not use any blacklisted reference (blacklist.txt)."
        "\n\n"
        + SELF_BLOCK +
        "\n\n"
        "After the run your model is scored by a grader you never see, against "
        "observations you do not have, on three things:\n"
        "  1. Whether a long free run of your model looks like the observed climate.\n"
        "  2. Whether it behaves as a coupled dynamical system rather than a set of "
        "curves that happen to match.\n"
        "  3. Whether it forecasts, from an observed initial state, better than "
        "persistence.\n"
        "Those are descriptions, not metrics. Do not try to reconstruct the grader; build "
        "the best model you can and judge it with tests you trust."
        "\n\n"
        "How the run works:\n"
        "- Your submission is snapshotted automatically as you work, and the BEST "
        "snapshot is what counts. A failed experiment cannot lower your grade, so explore "
        "freely rather than protecting a working version.\n"
        "- Simulation and script runtime is charged to the same clock as your thinking. A "
        "long free run costs you budget, so choose run lengths deliberately.\n"
        "- This is a long-horizon task. Keep iterating for the whole budget; do not stop "
        "early and do not wait idle.\n"
        "- Having the three files present and interface-correct is the starting "
        "condition, not the finish."
    )
    return body + "\n\nYou have about %.0f minutes of budget remaining." % remaining_min


def diagnostics_repair_prompt(bad):
    """Sent when a check does not run, to keep the agent in the metrics phase."""
    lines = "\n".join("  %s: %s" % (b["script"], b["error"]) for b in bad)
    return ("Not frozen yet. These checks do not run:\n" + lines + "\n\n"
            "Each one has to execute and print something before the set can be fixed, "
            "because once it is frozen you cannot repair it and whatever a broken check "
            "was measuring stops being measured. Fix or delete them, run every check once "
            "yourself to confirm, and stop again.")


def resume_prompt(no_improve_s, stall_escalate_s):
    """What a resumed Phase 2B turn is told, given how long no new snapshot appeared."""
    idx = int(no_improve_s // stall_escalate_s) - 1
    if idx >= 0:
        return STALL_PROMPTS[min(idx, len(STALL_PROMPTS) - 1)]
    return RESUME_PROMPT


# The Stop hook installed for the Claude Code arms during Phase 2B. The file lands in the
# agent's home, so its bytes are agent-visible and are kept exactly.
STOP_HOOK = """#!/bin/bash
cat >/dev/null
SUB="$SFORGE_SUBMISSION"
STATE=/tmp/sforge-stop-state
LIMIT=3

fp=$(cat "$SUB/model.py" "$SUB/params.json" 2>/dev/null | cksum | cut -d' ' -f1)
prev=$(cut -d' ' -f1 "$STATE" 2>/dev/null)
n=$(cut -d' ' -f2 "$STATE" 2>/dev/null)
[ -z "$n" ] && n=0

if [ "$fp" != "$prev" ]; then n=0; else n=$((n+1)); fi
echo "$fp $n" > "$STATE"

if [ "$n" -ge "$LIMIT" ]; then
  exit 0
fi

hint="Check the model against the part of the record you set aside: whether its free-run climate matches, whether it behaves as a coupled system, and whether it forecasts better than persistence. Whichever is weakest, change the term that controls it and re-measure."
printf '{"decision":"block","reason":"Not finished. %s"}\n' "$hint"
"""


def stop_hook_settings(submission_dir, hook_path, enabled):
    """The Claude Code settings.json the formal harness wrote, byte for byte."""
    if not enabled:
        return json.dumps({"hooks": {}}, indent=2)
    return json.dumps(
        {"hooks": {"Stop": [{"hooks": [{"type": "command",
                                        "command": "SFORGE_SUBMISSION=%s %s"
                                        % (submission_dir, hook_path)}]}]}},
        indent=2)


def stop_hook_env(submission_dir):
    return 'export SFORGE_SUBMISSION="%s"\n' % submission_dir


# Antigravity arm. The CLI never tells the model its working directory, so every user turn
# is prefixed with this block, and a normal result during Phase 2B is answered with
# ANTIGRAVITY_CONTINUE instead of ending the turn (Antigravity has no Stop hook).
ANTIGRAVITY_PREAMBLE = """<WORKSPACE_RULES>
Your workspace root is: {wd}

1. PATHS. Any path in the task below that looks relative (submission/model.py,
   submission/params.json, diagnostics/, data/) is relative to the workspace root above.
   Always pass ABSOLUTE paths built from it. Your default working directory is NOT the
   workspace, so a bare relative path will silently resolve somewhere else.
2. run_command. Always set Cwd to {wd} unless you have a specific reason not to.
3. NOT ARTIFACTS. Everything you create here is an ordinary source file: code, config,
   data, plots. None of it is an Antigravity artifact. When calling write_to_file you
   MUST NOT pass ArtifactMetadata. Passing it makes the call artifact-only and the write
   is rejected with "is not a valid artifact path".
4. Use the structured file tools (write_to_file, replace_file_content, view_file) for
   editing. They work against this workspace once rule 3 is respected.
</WORKSPACE_RULES>

"""

ANTIGRAVITY_HINT = ("Check the model against the part of the record you set aside: whether its "
                    "free-run climate matches, whether it behaves as a coupled system, and whether "
                    "it forecasts better than persistence. Whichever is weakest, change the term "
                    "that controls it and re-measure.")

ANTIGRAVITY_CONTINUE = """Continue working on the benchmark. A valid submission or passing checks do
not mean the optimization task is complete. Inspect the current submission and the
diagnostics output, identify the highest-value next improvement, implement it, and
validate it. %s

Continue until the external benchmark controller terminates this session.""" % ANTIGRAVITY_HINT

# Reason returned by the resource gate (arms launched with it, see `resource_gate` in the
# arm configs) when a tool tries to read a PDF directly.
RESOURCE_GATE_REASON = (
    "%s files are not read by this tool in this environment. The file itself is "
    "present, unmodified and readable, so you may process it with Bash or python if "
    "you choose. Other task resources and other tools are unaffected.")

# Antigravity PreToolUse guard: the decision it prints for every retrieval tool.
DENY_RETRIEVAL_DECISION = (
    '{"decision":"deny","reason":"BENCHMARK_NETWORK_POLICY_DENY: external retrieval and '
    'network-capable tools are disabled for this benchmark run."}')


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def prompt_digests():
    """sha256 of every fixed agent-facing text, and of the templates rendered at fixed
    arguments, for the dry run and for comparison with the formal runs."""
    return {
        "PERSISTENT_MEMORY_POLICY": _sha(PERSISTENT_MEMORY_POLICY),
        "RESUME_PROMPT": _sha(RESUME_PROMPT),
        "STALL_PROMPTS": _sha("\0".join(STALL_PROMPTS)),
        "phase1_prompt()": _sha(phase1_prompt()),
        "phase2a_prompt(360)": _sha(phase2a_prompt(360.0)),
        "SELF_BLOCK": _sha(SELF_BLOCK),
        "phase2_prompt(300)": _sha(phase2_prompt(300.0)),
        "STOP_HOOK": _sha(STOP_HOOK),
        "ANTIGRAVITY_PREAMBLE": _sha(ANTIGRAVITY_PREAMBLE),
        "ANTIGRAVITY_CONTINUE": _sha(ANTIGRAVITY_CONTINUE),
        "RESOURCE_GATE_REASON": _sha(RESOURCE_GATE_REASON),
        "DENY_RETRIEVAL_DECISION": _sha(DENY_RETRIEVAL_DECISION),
        "ANON_P1_TEXTS": _sha("\0".join((ANON_P1_MISSING, ANON_P1_REJECTED, ANON_P1_UNREPORTABLE))),
    }
