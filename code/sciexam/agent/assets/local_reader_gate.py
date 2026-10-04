#!/usr/bin/env python3
"""Resource gate: the file tool does not hand a PDF to the model transport.

Given no page range, the Claude Code Read tool attaches the raw bytes of a PDF to the next
request and leaves the decoding to the provider, so whether an agent can read the reference
paper would depend on its route. This PreToolUse hook makes that path fail softly and
locally instead. The file stays present and readable, every other tool is unaffected, and
an agent may still extract the text with Bash or Python. Installed root-owned, so the agent
cannot switch it off. Used by the arms whose formal run had it (resource_gate in the arm
config).
"""
import json
import os
import sys

GATED = {".pdf": "PDF"}

REASON = ("%s files are not read by this tool in this environment. The file itself is "
          "present, unmodified and readable, so you may process it with Bash or python if "
          "you choose. Other task resources and other tools are unaffected.")


def _targeted_extension(raw, ev):
    path = (ev.get("tool_input") or {}).get("file_path") if isinstance(ev, dict) else None
    if path:
        return os.path.splitext(str(path))[1].lower()
    low = raw.lower()
    for ext in GATED:
        if ext in low:
            return ext
    return None


def main():
    schema, tools = "claude", ("Read",)
    args = sys.argv[1:]
    if "--schema" in args:
        schema = args[args.index("--schema") + 1]
    if "--tools" in args:
        tools = tuple(args[args.index("--tools") + 1].split(","))
    raw = sys.stdin.read()
    try:
        ev = json.loads(raw)
    except Exception:
        ev = {}
    name = ev.get("tool_name") or ev.get("name") or ""
    if name and name not in tools:
        return 0
    label = GATED.get(_targeted_extension(raw, ev))
    if not label:
        return 0
    reason = REASON % label
    if schema == "antigravity":
        json.dump({"decision": "deny", "reason": reason}, sys.stdout)
    else:
        json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                          "permissionDecision": "deny",
                                          "permissionDecisionReason": reason}}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
