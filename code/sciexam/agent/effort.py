"""Reasoning effort of an arm: the levels a rerun may choose and how each scaffold receives one.

Every released arm records the effort its formal run used (`reasoning.effort`). A rerun may ask
for another level with `sciexam run-agent --effort`. Each scaffold takes the level its own way:

    claude-code   the --effort flag of Claude Code. Gateway arms ran without the flag, at the
                  CLI default (high), so asking for high reproduces them exactly, and any other
                  level adds the flag, which LiteLLM forwards to the upstream model.
    codex         model_reasoning_effort in the run's config.toml.
    antigravity   the model variant: the level is the suffix of the model id
                  (gemini-3.8-flash-medium), so another level selects another variant.

A run whose level differs from the formal run is recorded as not comparable with the paper.
"""
import copy

LEVELS = ("low", "medium", "high")
VARIANT_SUFFIXES = tuple("-" + lv for lv in LEVELS)


class EffortError(ValueError):
    pass


def mechanism(arm):
    """One line on how this arm's scaffold receives a level."""
    s = arm["scaffold"]["name"]
    if s == "claude-code":
        if arm["reasoning"]["pass_effort_flag"]:
            return "--effort flag"
        return "--effort flag (paper: no flag, CLI default high)"
    if s == "codex":
        return "config.toml model_reasoning_effort"
    if s == "antigravity":
        return "model variant suffix (%s)" % arm["route"]["model_id"]
    return "unknown scaffold"


def options(arm):
    """Levels this arm accepts. Every scaffold takes low, medium and high, except an
    antigravity arm whose model id carries no level suffix."""
    if arm["scaffold"]["name"] == "antigravity" and not _variant_base(arm["route"]["model_id"]):
        return (arm["reasoning"]["effort"],)
    return LEVELS


def _variant_base(model_id):
    for suf in VARIANT_SUFFIXES:
        if model_id.endswith(suf):
            return model_id[: -len(suf)]
    return None


def apply(arm, level):
    """Return a copy of ``arm`` set to ``level``. The formal level is kept in
    ``reasoning.paper_effort`` and ``reasoning.comparable_with_paper`` says whether they agree."""
    if level not in LEVELS:
        raise EffortError("effort must be one of %s, got %r" % (", ".join(LEVELS), level))
    if level not in options(arm):
        raise EffortError("%s accepts only %s" % (arm["arm"], ", ".join(options(arm))))
    out = copy.deepcopy(arm)
    r = out["reasoning"]
    paper = r["effort"]
    r["paper_effort"] = paper
    r["comparable_with_paper"] = level == paper
    if level == paper:
        return out
    r["effort"] = level
    s = out["scaffold"]["name"]
    if s == "claude-code":
        r["pass_effort_flag"] = True
    elif s == "antigravity":
        out["route"]["model_id"] = "%s-%s" % (_variant_base(out["route"]["model_id"]), level)
    return out


def parse(spec, arm_keys):
    """``--effort`` value to {arm key: level}. ``high`` sets every arm, ``kimi=high,gpt56=low``
    sets the named arms, and ``all=medium`` (or a bare level) sets the rest."""
    if not spec:
        return {}
    out, default = {}, None
    for part in [p.strip() for p in spec.split(",") if p.strip()]:
        if "=" in part:
            k, v = [x.strip() for x in part.split("=", 1)]
            if k == "all":
                default = v
            elif k in arm_keys:
                out[k] = v
            else:
                raise EffortError("--effort names %r, which is not among the arms %s"
                                  % (k, ", ".join(arm_keys)))
        else:
            default = part
    for v in list(out.values()) + ([default] if default else []):
        if v not in LEVELS:
            raise EffortError("effort must be one of %s, got %r" % (", ".join(LEVELS), v))
    if default:
        for k in arm_keys:
            out.setdefault(k, default)
    return out
