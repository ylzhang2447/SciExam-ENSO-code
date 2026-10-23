"""Models the paper did not run: configurations made from the released arm of each route."""
from pathlib import Path

import pytest

from sciexam.agent import config as C
from sciexam.agent import docker_env as D
from sciexam.agent import newmodel as NM
from sciexam.agent.commands import resolve_agents
from sciexam.submission import verify as V

AGENTS = Path(__file__).resolve().parents[1] / "agents"


@pytest.fixture(autouse=True)
def user_agents(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIEXAM_AGENTS", str(tmp_path / "agents"))


def protocol_same(arm):
    t = V.released_template(arm)
    return all(V._get(arm, k) == V._get(t, k) for k in V.PROTOCOL_KEYS)


@pytest.mark.parametrize("route,model", [("openrouter", "qwen/qwen3-coder"), ("claude", "claude-opus-5-5"),
                                         ("codex", "gpt-6"), ("antigravity", "gemini-3.9-pro-medium")])
def test_each_route_keeps_the_protocol(route, model):
    arm = C.load_arm(NM.make(route, model))
    assert arm["route"]["model_id"] == model and "run_id" not in arm
    assert protocol_same(arm)
    t = C.load_arm(AGENTS / ("%s.yaml" % NM.TEMPLATES[route]))
    assert arm["scaffold"] == t["scaffold"] and arm["lifecycle"] == t["lifecycle"]


def test_openrouter_model_is_not_pinned():
    arm = C.load_arm(NM.make("openrouter", "qwen/qwen3-coder"))
    cfg = D.gateway_config(arm)
    assert "model: openrouter/qwen/qwen3-coder" in cfg and "provider: {allow_fallbacks: true}" in cfg


def test_local_endpoint():
    arm = C.load_arm(NM.make("local", "llama-4-70b", api_base="http://localhost:8000/v1"))
    assert arm["route"]["api_base"] == "http://host.docker.internal:8000/v1"
    assert arm["route"]["upstream_hosts"] == ["host.docker.internal"]
    assert C.required_credentials(arm) == []
    cfg = D.gateway_config(arm)
    assert "model: openai/llama-4-70b" in cfg and "api_base: http://host.docker.internal:8000/v1" in cfg
    names = D.Names("sciexam", "x")
    paths = {"proxy_log_dir": "/tmp/p", "gateway_config": "/tmp/g.yaml", "workspace": "/tmp/w",
             "ctr_workspace": "/work/x"}
    gw = [c for c in D.up_commands(arm, "sciexam", names, paths, "/tmp/e.py") if c[0] == "start LiteLLM gateway"][0]
    assert "host.docker.internal:host-gateway" in gw[1]
    assert protocol_same(arm)
    remote = C.load_arm(NM.make("local", "m", api_base="https://llm.lab.example.org/v1", key="labm"))
    assert remote["route"]["upstream_hosts"] == ["llm.lab.example.org"]


def test_bad_input():
    with pytest.raises(NM.ModelError):
        NM.make("local", "m")                         # no endpoint
    with pytest.raises(NM.ModelError):
        NM.make("openrouter", "has space")
    with pytest.raises(NM.ModelError):
        NM.make("openrouter", "x", key="kimi")        # a released arm's key
    with pytest.raises(NM.ModelError):
        NM.gateway_api_base("ftp://x")


def test_route_model_shorthand_adds_once():
    p1 = resolve_agents(["openrouter:qwen/qwen3-coder"])[0]
    p2 = resolve_agents(["openrouter-qwen-qwen3-coder"])[0]
    assert p1 == p2 and p1.parent == NM.user_dir()
    assert [p.stem for p in resolve_agents(["kimi,openrouter:qwen/qwen3-coder"])] == ["kimi", "openrouter-qwen-qwen3-coder"]


def test_released_gateway_configs_are_unchanged():
    # the paper's arms keep their provider pins exactly
    cfg = D.gateway_config(C.load_arm(AGENTS / "kimi.yaml"))
    assert "provider: {order: [moonshotai], allow_fallbacks: false}" in cfg


def test_context_window_from_openrouter_listing():
    listing = {"data": [{"id": "a/small", "context_length": 32768},
                        {"id": "a/big", "top_provider": {"context_length": 1000000}}, {"id": "a/none"}]}
    assert NM.parse_models(listing, "a/small") == 32768
    assert NM.parse_models(listing, "a/big") == 1000000
    assert NM.parse_models(listing, "a/none") == 0
    assert NM.parse_models(listing, "a/missing") is None


def test_a_smaller_context_window_is_declared():
    arm = C.load_arm(NM.make("local", "llama-4", api_base="http://localhost:8000/v1", context_tokens=32768))
    assert arm["context"]["working_context_tokens"] == 32768
    assert arm["context"]["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == 26214      # 80% of the window
    assert arm["declared"] == {"context_tokens": 32768}
    from sciexam.agent import ledger as LG
    assert LG.system_name(arm, 21600) == "llama-4 (32k context)"
    rep = V.Report()
    import tempfile, shutil
    d = Path(tempfile.mkdtemp())
    shutil.copyfile(NM.user_dir() / "local-llama-4.yaml", d / "agent.yaml")
    V.check_config(d, rep)
    assert rep.checks[0]["status"] == "declared" and "32768 tokens instead of 200000" in rep.checks[0]["detail"]
    # a window at least as large as the paper's changes nothing
    big = C.load_arm(NM.make("openrouter", "a/big", context_tokens=1000000))
    assert big["context"]["working_context_tokens"] == 200000 and not big.get("declared")
    with pytest.raises(NM.ModelError):
        NM.make("local", "tiny", api_base="http://localhost:8000/v1", context_tokens=8000)


def test_gateway_routes_get_the_tool_call_preflight():
    assert C.load_arm(NM.make("openrouter", "a/x"))["preflight"] == {"tool_call": True}
    assert C.load_arm(NM.make("local", "y", api_base="http://localhost:1/v1"))["preflight"] == {"tool_call": True}
    assert not C.load_arm(NM.make("claude", "claude-z")).get("preflight")
    assert not C.load_arm(AGENTS / "kimi.yaml").get("preflight")        # the paper's arms are unchanged


def test_tool_call_reply_parsing():
    from sciexam.agent.commands import tool_call_ok
    ok, detail = tool_call_ok('{"content": [{"type": "tool_use", "name": "write_file", "input": {"path": "check.txt", "text": "ok"}}]}')
    assert ok and "write_file" in detail
    ok, detail = tool_call_ok('{"content": [{"type": "text", "text": "I would write ok."}]}')
    assert not ok and "without a tool call" in detail
    ok, detail = tool_call_ok('{"error": "HTTPError: 400", "body": "tools not supported"}')
    assert not ok and "tools not supported" in detail
    assert not tool_call_ok("<html>bad gateway</html>")[0]
