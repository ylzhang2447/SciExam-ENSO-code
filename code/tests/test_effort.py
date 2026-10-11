"""Reasoning effort overrides of `sciexam run-agent --effort` and the multi-arm argument parsing."""
from pathlib import Path

import pytest

from sciexam.agent import config as C
from sciexam.agent import effort as E
from sciexam.agent.commands import resolve_agents

AGENTS = Path(__file__).resolve().parents[1] / "agents"


def arm(key):
    return C.load_arm(AGENTS / ("%s.yaml" % key))


def test_paper_level_is_unchanged():
    for key in ("kimi", "fable51", "gpt56", "gemini38"):
        a = arm(key)
        b = E.apply(a, a["reasoning"]["effort"])
        assert b["reasoning"]["comparable_with_paper"] is True
        assert b["reasoning"]["pass_effort_flag"] == a["reasoning"]["pass_effort_flag"]
        assert b["route"]["model_id"] == a["route"]["model_id"]


def test_gateway_arm_adds_the_flag_only_when_changed():
    a = arm("kimi")
    assert a["reasoning"]["pass_effort_flag"] is False
    b = E.apply(a, "low")
    assert b["reasoning"]["effort"] == "low" and b["reasoning"]["pass_effort_flag"] is True
    assert b["reasoning"]["paper_effort"] == "high"
    assert b["reasoning"]["comparable_with_paper"] is False
    assert a["reasoning"]["effort"] == "high"          # the loaded arm is not modified


def test_codex_level_reaches_config_toml():
    from sciexam.agent.scaffolds import Codex

    class Run:
        pass
    r = Run()
    r.arm = E.apply(arm("gpt56"), "high")
    assert 'model_reasoning_effort = "high"' in Codex(r).config_text()


def test_antigravity_level_selects_the_variant():
    b = E.apply(arm("gemini38"), "low")
    assert b["route"]["model_id"] == "gemini-3.8-flash-low"


def test_rejects_unknown_level():
    with pytest.raises(E.EffortError):
        E.apply(arm("kimi"), "max")


def test_parse():
    keys = ["kimi", "gpt56"]
    assert E.parse(None, keys) == {}
    assert E.parse("medium", keys) == {"kimi": "medium", "gpt56": "medium"}
    assert E.parse("kimi=low", keys) == {"kimi": "low"}
    assert E.parse("kimi=low,all=high", keys) == {"kimi": "low", "gpt56": "high"}
    with pytest.raises(E.EffortError):
        E.parse("opus5=low", keys)
    with pytest.raises(E.EffortError):
        E.parse("extreme", keys)


def test_resolve_agents_accepts_keys_paths_and_lists():
    got = resolve_agents(["kimi,gpt56", str(AGENTS / "opus5.yaml")])
    assert [p.stem for p in got] == ["kimi", "gpt56", "opus5"]
    with pytest.raises(RuntimeError):
        resolve_agents(["not-an-arm"])
