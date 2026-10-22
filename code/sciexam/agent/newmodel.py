"""New models: an arm configuration made from the released arm of the same route.

A new model runs on the protocol of a paper system (scaffold, budget, lifecycle, tool envelope,
network and context policy are copied) and only its model changes, so its result is comparable with
the paper and its submission passes the protocol check. The template of each route is the paper's
latest run on it (the batches of 12 and 13 September 2026, with the gateway's cache-usage patch and
the soft PDF gate that every container had from 11 September on):

    openrouter   any model on OpenRouter, through the LiteLLM gateway (template: DeepSeek V4.1
                 Flash). No provider is pinned and OpenRouter may fall back, unlike the paper's runs.
    claude       another model of the Claude Code subscription client (template: Claude Fable 5.1)
    codex        another model of the Codex subscription client (template: GPT-6 Astra)
    antigravity  another model of the Antigravity client (template: Gemini 3.8 Flash)
    local        any OpenAI-compatible endpoint (vLLM, Ollama, a lab server), through the LiteLLM
                 gateway (template: DeepSeek V4.1 Flash). An endpoint on this machine is reached
                 from the gateway container as host.docker.internal.

Two things differ for a model the paper did not run on the gateway routes:

    context      the paper's runs compact their context at 200,000 tokens. A model with a smaller
                 window (read from OpenRouter, or given for a local model) gets its own threshold,
                 80% of its window, recorded under ``declared`` as a change from the paper.
    tool calls   the agent works only through tool calls, which many local models do not make.
                 ``preflight.tool_call`` makes run-agent send one tool-call request through the
                 gateway before the budget starts, and stop with advice if no tool call comes back.

The configuration is written to the user's agents folder (~/.cache/sciexam/agents, or
SCIEXAM_AGENTS), next to which `list-agents`, `run-agent` and the interactive setup look.
"""
import json
import os
import re
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from . import config as C

RELEASED_DIR = Path(__file__).resolve().parents[2] / "agents"
TEMPLATES = {"openrouter": "dsflash", "claude": "fable51", "codex": "gpt6astra",
             "antigravity": "gemini38", "local": "dsflash"}
ROUTE_LABELS = {
    "openrouter": "any model on OpenRouter (OPENROUTER_API_KEY)",
    "claude": "a model of the Claude Code subscription (CLAUDE_CODE_OAUTH_TOKEN)",
    "codex": "a model of the Codex subscription (CODEX_AUTH_JSON)",
    "antigravity": "a model of the Antigravity client (ANTIGRAVITY_HOME)",
    "local": "an OpenAI-compatible endpoint: vLLM, Ollama or a lab server",
}
LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


class ModelError(ValueError):
    pass


def user_dir():
    return Path(os.environ.get("SCIEXAM_AGENTS") or Path.home() / ".cache" / "sciexam" / "agents")


def agent_dirs():
    """Where arm configurations are looked up: the released ones, then the user's."""
    return [RELEASED_DIR, user_dir()]


def all_configs():
    out = []
    for d in agent_dirs():
        if d.is_dir():
            out += sorted(d.glob("*.yaml"))
    return out


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:48] or "model"


def _set(text, key, value, block=None):
    """Replace the value of ``key`` (inside ``block`` when given), keeping its comment."""
    lines = text.split("\n")
    inside = block is None
    for i, ln in enumerate(lines):
        if block is not None:
            if re.match(r"^%s:\s*$" % re.escape(block), ln):
                inside = True
                continue
            if inside and re.match(r"^\S", ln):
                inside = False
        if inside and re.match(r"^\s*%s:" % re.escape(key), ln):
            indent = re.match(r"^(\s*)", ln).group(1)
            lines[i] = "%s%s: %s" % (indent, key, value)
            return "\n".join(lines)
    raise ModelError("the template has no %s%s" % (block + "." if block else "", key))


def _drop(text, key):
    return "\n".join(ln for ln in text.split("\n") if not re.match(r"^%s:" % re.escape(key), ln))


PAPER_CONTEXT = 200000
COMPACT_FRACTION = 0.8


def parse_models(listing, model_id):
    """From OpenRouter's /models listing: None if the model is absent, else its context length
    (None when unstated)."""
    for m in listing.get("data", []):
        if m.get("id") == model_id:
            n = m.get("context_length") or (m.get("top_provider") or {}).get("context_length")
            return int(n) if n else 0
    return None


def openrouter_info(model_id, timeout=10):
    """{'exists': bool, 'context_length': int or None}, or None when the list cannot be read."""
    try:
        with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=timeout) as r:
            listing = json.load(r)
    except Exception:
        return None
    n = parse_models(listing, model_id)
    return {"exists": n is not None, "context_length": n or None}


def check_openrouter(model_id, timeout=10):
    """True or False when OpenRouter's public model list could be read, None when it could not."""
    info = openrouter_info(model_id, timeout)
    return None if info is None else info["exists"]


def gateway_api_base(url):
    """The endpoint as the gateway container reaches it: this machine is host.docker.internal."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ModelError("the endpoint must be an http(s) URL, for example http://localhost:8000/v1")
    host = "host.docker.internal" if u.hostname in LOCAL_HOSTS else u.hostname
    netloc = host + (":%d" % u.port if u.port else "")
    return u._replace(netloc=netloc).geturl(), host


def make(route, model_id, name=None, api_base=None, key=None, context_tokens=None):
    """Write the configuration of a new model and return its path. ``context_tokens`` is the
    model's context window, on the gateway routes."""
    if route not in TEMPLATES:
        raise ModelError("route must be one of %s" % ", ".join(TEMPLATES))
    model_id = (model_id or "").strip()
    if not model_id or any(c.isspace() for c in model_id):
        raise ModelError("give the model id without spaces, for example qwen/qwen3-coder")
    key = slug(key or "%s-%s" % (route, model_id))
    if (RELEASED_DIR / ("%s.yaml" % key)).exists():
        raise ModelError("%s is a released arm, choose another name" % key)
    name = (name or model_id).replace('"', "'")
    text = (RELEASED_DIR / ("%s.yaml" % TEMPLATES[route])).read_text()
    text = re.sub(r"^# Arm configuration.*?\n(?=arm:)",
                  "# Arm configuration for `sciexam run-agent`: %s, made by `sciexam add-model` from the\n"
                  "# released arm %s. Only the model differs from that arm's protocol.\n"
                  % (name, TEMPLATES[route]), text, flags=re.S)
    text = _set(text, "arm", key)
    text = _set(text, "display_name", '"%s"' % name)
    text = _drop(_drop(text, "run_id"), "campaign_id")
    text = _set(text, "model_id", model_id, "route")
    if route in ("openrouter", "local"):
        text = _set(text, "model_alias", key, "route")
        text = _set(text, "provider_order", "[]", "route")
        text = _set(text, "allow_fallbacks", "true" if route == "openrouter" else "false", "route")
    if route == "local":
        if not api_base:
            raise ModelError("a local model needs its endpoint, for example http://localhost:8000/v1")
        base, host = gateway_api_base(api_base)
        text = _set(text, "upstream", "openai-compatible", "route")
        text = _set(text, "upstream_hosts", "[%s]" % host, "route")
        text = text.replace("  upstream: openai-compatible",
                            "  upstream: openai-compatible\n  api_base: %s" % base, 1)
    for k in ("observed_max_context_tokens", "observed_compactions"):
        text = re.sub(r"^\s*%s:.*\n" % k, "", text, flags=re.M)
    if route in ("openrouter", "local"):
        text = text.rstrip("\n") + ("\n\n# Before the budget starts, one tool-call request through the gateway checks that\n"
                                    "# the model makes tool calls, which the agent needs for every action.\n"
                                    "preflight:\n  tool_call: true\n")
        if context_tokens:
            n = int(context_tokens)
            if n < 16000:
                raise ModelError("a context window of %d tokens is too small for the task" % n)
            if n < PAPER_CONTEXT:
                text = _set(text, "working_context_tokens", str(n), "context")
                text = re.sub(r"(CLAUDE_CODE_MAX_CONTEXT_TOKENS:)\s*\d+",
                              r"\g<1> %d" % int(n * COMPACT_FRACTION), text)
                text += ("\n# The model's context window is smaller than the leaderboard's 200,000 tokens, so\n"
                         "# the agent compacts at 80%% of it. A declared change: ranked apart from the\n"
                         "# official leaderboard.\n"
                         "declared:\n  context_tokens: %d\n" % n)
    d = user_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / ("%s.yaml" % key)
    path.write_text(text)
    try:
        C.load_arm(path)
    except C.ConfigError as e:
        path.unlink()
        raise ModelError("the new configuration does not load: %s" % e)
    return path


def template_for(arm):
    """The released arm whose protocol an arm the paper did not run must follow."""
    s, k = arm["scaffold"]["name"], arm["route"]["kind"]
    route = ("codex" if s == "codex" else "antigravity" if s == "antigravity"
             else "openrouter" if k == "gateway" else "claude")
    return TEMPLATES[route]


def parse_spec(spec):
    """``openrouter:qwen/qwen3-coder`` style --agent values to (route, model id), or None."""
    if ":" not in spec or spec.endswith(".yaml"):
        return None
    route, model = spec.split(":", 1)
    return (route, model) if route in TEMPLATES and route != "local" else None
