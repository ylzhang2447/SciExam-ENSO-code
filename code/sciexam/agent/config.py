"""Arm configs (agents/<arm>.yaml) and the user's credential file (.env)."""
import os
import re
from pathlib import Path

from . import yamlmini

SCAFFOLDS = ("claude-code", "codex", "antigravity")
ROUTES = ("gateway", "subscription")

# Defaults equal the formal harness constants. An arm config may restate them (all released
# configs do, with their source), but it cannot drop one silently.
LIFECYCLE_DEFAULTS = dict(
    termination_policy="fixed_duration",
    phase1_turn_cap_s=1800, phase1_max_attempts=4, phase2a_cap_s=5400,
    diagnostics_check_timeout_s=420, diagnostics_repair_rounds=2,
    snapshot_every_s=300, stall_escalate_s=1200, hard_fail_limit=3,
    min_runtime_for_resume_s=5, productive_fatal_limit=8,
    quota_wait_max_events=12, quota_wait_min_s=5, quota_wait_max_s=21600,
    quota_wait_recovery_margin_s=15, pause_on_quota=True, pause_on_provider_service=True,
    provider_service_pause_granularity_s=30, pause_max_per_provider_event_s=600,
    pause_total_credit_cap_multiple=1.0, max_wall_multiple=3.0, stop_hook_block_limit=3,
    agent_uid="1000:1000",
)

# Smoke runs check the plumbing only. Phase 1 is attempted once and never blocks, so the
# run reaches Phase 2 on a short budget. A smoke run is not comparable with the record.
SMOKE_OVERRIDES = dict(phase1_turn_cap_s=180, phase1_max_attempts=1, phase2a_cap_s=240,
                       snapshot_every_s=60)
SMOKE_SECONDS = 900

PIP_HOSTS = ("pypi.org", "files.pythonhosted.org")


class ConfigError(ValueError):
    pass


def _need(d, path):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            raise ConfigError("missing key %r" % path)
        cur = cur[k]
    return cur


def load_arm(path):
    path = Path(path)
    d = yamlmini.load(path)
    if not isinstance(d, dict):
        raise ConfigError("%s: not a mapping" % path)
    for key in ("arm", "scaffold.name", "scaffold.version", "scaffold.binary_sha256",
                "route.kind", "route.model_id", "reasoning.effort",
                "reasoning.pass_effort_flag", "context.working_context_tokens",
                "budget.eligible_seconds", "network.agent_allow_hosts", "resource_gate"):
        _need(d, key)
    if d["scaffold"]["name"] not in SCAFFOLDS:
        raise ConfigError("scaffold.name must be one of %s" % ", ".join(SCAFFOLDS))
    if d["route"]["kind"] not in ROUTES:
        raise ConfigError("route.kind must be one of %s" % ", ".join(ROUTES))
    if d["route"]["kind"] == "gateway":
        for key in ("route.model_alias", "route.provider_order", "route.allow_fallbacks",
                    "route.gateway_version", "route.gateway_patch", "route.upstream_hosts"):
            _need(d, key)
        if d["scaffold"]["name"] != "claude-code":
            raise ConfigError("the gateway route is driven by Claude Code only")
    else:
        _need(d, "route.agent_hosts")
    if not re.fullmatch(r"[0-9a-f]{64}", str(d["scaffold"]["binary_sha256"])):
        raise ConfigError("scaffold.binary_sha256 must be 64 hex digits")
    life = dict(LIFECYCLE_DEFAULTS)
    life.update(d.get("lifecycle") or {})
    unknown = set(life) - set(LIFECYCLE_DEFAULTS)
    if unknown:
        raise ConfigError("unknown lifecycle keys: %s" % ", ".join(sorted(unknown)))
    d["lifecycle"] = life
    d.setdefault("tools", {"disallowed": []})
    d.setdefault("provider_signals", {"classify_failed_turns": False})
    d.setdefault("antigravity", {})
    d.setdefault("codex", {})
    d["_path"] = str(path)
    if d.get("condition"):
        check_condition(d, path)
    return d


# What a condition arm must share with its baseline arm. Everything else that differs is
# named in the condition block.
SAME_AS_BASELINE = ("scaffold", "route", "reasoning", "budget", "lifecycle", "resource_gate",
                    "provider_signals", "context.working_context_tokens", "context.mechanism",
                    "context.enforced", "context.env", "network.agent_allow_hosts")


def check_condition(d, path):
    """Validate the condition block and check that the arm equals its baseline arm (the
    agents/<baseline_arm>.yaml next to it) except for the tools the condition undenies."""
    from . import conditions as K
    from .research import POLICIES
    for key in ("name", "baseline_arm", "task_tree", "network", "undenied_tools"):
        _need(d, "condition." + key)
    c = d["condition"]
    if c["task_tree"] not in K.TASK_TREES:
        raise ConfigError("condition.task_tree must be one of %s" % ", ".join(K.TASK_TREES))
    if c["network"] not in K.NETWORKS:
        raise ConfigError("condition.network must be one of %s" % ", ".join(K.NETWORKS))
    if c["network"] == "research":
        if c.get("research_policy") not in POLICIES:
            raise ConfigError("condition.research_policy must be one of %s" % ", ".join(POLICIES))
        if d["scaffold"]["name"] != "claude-code" or d["route"]["kind"] != "subscription":
            raise ConfigError("the research network is wired for the Claude Code subscription route")
    elif c.get("research_policy"):
        raise ConfigError("condition.research_policy needs condition.network: research")
    undenied = list(c["undenied_tools"] or [])
    base = load_arm(Path(path).parent / ("%s.yaml" % c["baseline_arm"]))
    if base.get("condition"):
        raise ConfigError("the baseline arm of a condition must not itself be a condition")
    for key in SAME_AS_BASELINE:
        if _get(d, key) != _get(base, key):
            raise ConfigError("%s differs from the baseline arm %s" % (key, c["baseline_arm"]))
    want = [t for t in base["tools"]["disallowed"] if t not in undenied]
    if list(d["tools"]["disallowed"]) != want:
        raise ConfigError("tools.disallowed must be the baseline list without %s"
                          % (", ".join(undenied) or "any tool"))


def _get(d, dotted):
    cur = d
    for k in dotted.split("."):
        cur = cur.get(k) if isinstance(cur, dict) else None
    return cur


def allowlist(arm):
    """Hosts the agent container may reach through the egress proxy (arms on the allowlist
    network; the web conditions use the research policy instead)."""
    hosts = list(arm["network"]["agent_allow_hosts"])
    pypi = arm["network"].get("pypi", True)
    if not pypi:
        hosts = [h for h in hosts if h not in PIP_HOSTS]
    for h in PIP_HOSTS if pypi else ():
        if h not in hosts:
            hosts.append(h)
    if arm["route"]["kind"] == "subscription":
        hosts += [h for h in arm["route"]["agent_hosts"] if h not in hosts]
    return hosts


def gateway_allowlist(arm):
    """Hosts the gateway container may reach (gateway arms only)."""
    return list(arm["route"].get("upstream_hosts") or [])


# Credentials the user supplies. Values are read from the environment first, then from the
# env file, and are never printed.
CREDENTIALS = {
    "gateway": [("OPENROUTER_API_KEY", "OpenRouter API key for the LiteLLM gateway")],
    "claude-code": [("CLAUDE_CODE_OAUTH_TOKEN",
                     "Claude subscription token from `claude setup-token`")],
    "codex": [("CODEX_AUTH_JSON", "path to auth.json written by `codex login` (ChatGPT sign-in)")],
    "antigravity": [("ANTIGRAVITY_HOME", "path to the .gemini folder written by the Antigravity "
                                         "CLI after Google sign-in")],
}


def required_credentials(arm):
    if arm["route"].get("upstream") == "openai-compatible":
        return []          # LOCAL_MODEL_API_KEY is optional: many local servers take any key
    if arm["route"]["kind"] == "gateway":
        return CREDENTIALS["gateway"]
    return CREDENTIALS[arm["scaffold"]["name"]]


def read_env_file(path):
    out = {}
    p = Path(path) if path else None
    if not p or not p.exists():
        return out
    for line in p.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        if k.startswith("export "):
            k = k[7:].strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        out[k] = v
    return out


def credential(name, env_file_values):
    v = os.environ.get(name)
    if v:
        return v
    return env_file_values.get(name) or ""
