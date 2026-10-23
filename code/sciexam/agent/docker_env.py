"""Docker resources of one run: two networks, the egress proxy, the gateway, the agent.

    egress network (ordinary bridge)          internal network (--internal, no route out)
    ------------------------------            -------------------------------------------
    proxy   (allowlist, CONNECT only)  <---->  proxy alias "egress-proxy"
    gateway (LiteLLM, gateway arms)    <---->  gateway alias "llm-gateway"
                                               agent  (HTTPS_PROXY -> egress-proxy:3128)

The agent container is attached to the internal network only, so it has no route to any
address outside it. Package installs and the model route of subscription arms go through
the proxy, which admits pypi.org, files.pythonhosted.org and the hosts of the arm's route
and refuses everything else. Gateway arms reach their model through the gateway on the
internal network. The gateway (our own configuration of an open-source router) is the only
other container with an outside route.

The web conditions (``network: research`` in the condition block) put the web research proxy
(sciexam/agent/research, a mitmproxy addon) in the place of the allowlist proxy. It allows
the public web under the leakage controls of the condition's research policy, intercepts TLS
with a CA generated for the run (installed in the agent container), and passes the model
hosts of the route through without decrypting them.
"""
import os
import shlex
import subprocess
from pathlib import Path

from . import resources as R

# Every image of a run is built and run for linux/amd64: the agent image installs the Linux x64
# builds of Node.js and the agent CLIs, pinned by sha256. On an arm64 host Docker emulates it.
PLATFORM = os.environ.get("SCIEXAM_PLATFORM", "linux/amd64")

PROXY_IMAGE = ("python:3.12-slim@sha256:"
               "2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9")
PROXY_PORT = 3128
PROXY_ALIAS = "egress-proxy"
GATEWAY_ALIAS = "llm-gateway"
GATEWAY_PORT = 4000
PIP_INDEX_URL = "https://pypi.org/simple"
RESEARCH_DIR = Path(__file__).parent / "research"


def repo_root():
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "environment" / "agent" / "Dockerfile").exists():
            return p
    return None


class Names:
    def __init__(self, prefix, key):
        base = "%s-%s" % (prefix, key)
        self.key = key
        self.internal = base + "-int"
        self.egress = base + "-egress"
        self.proxy = base + "-proxy"
        self.gateway = base + "-gateway"
        self.agent = base + "-agent"
        self.probe = base + "-probe"
        self.label = "sciexam.run=%s" % base


def agent_image_tag(arm, prefix):
    s = arm["scaffold"]
    return "%s-agent:%s-%s" % (prefix, s["name"], s["version"])


def gateway_image_tag(arm, prefix):
    r = arm["route"]
    return "%s-gateway:litellm-%s-%s" % (prefix, r["gateway_version"],
                                         "patched" if r["gateway_patch"] != "none" else "plain")


def is_research(arm):
    """True for a web condition, whose egress is the research proxy."""
    return (arm.get("condition") or {}).get("network") == "research"


def research_image_tag(prefix):
    return "%s-research-proxy:mitmproxy-12.1.2" % prefix


def agent_build_args(arm, env_values):
    """Build arguments of environment/agent/Dockerfile: the pinned CLI and its sha256."""
    s = arm["scaffold"]
    if s["name"] == "claude-code":
        return {"CLAUDE_CODE_VERSION": s["version"], "CLAUDE_CODE_SHA256": s["binary_sha256"]}
    if s["name"] == "codex":
        return {"CODEX_VERSION": s["version"], "CODEX_SHA256": s["binary_sha256"]}
    return {"ANTIGRAVITY_URL": env_values.get("ANTIGRAVITY_URL", ""),
            "ANTIGRAVITY_SHA256": s["binary_sha256"]}


def proxy_env(arm):
    """Variables set on the agent container, so every process in it uses the proxy."""
    from .research import CA_IN_AGENT, PROXY_PORT as RESEARCH_PORT
    no_proxy = ["127.0.0.1", "localhost"]
    if arm["route"]["kind"] == "gateway":
        no_proxy.append(GATEWAY_ALIAS)
    url = "http://%s:%d" % (PROXY_ALIAS, RESEARCH_PORT if is_research(arm) else PROXY_PORT)
    np = ",".join(no_proxy)
    env = {"HTTPS_PROXY": url, "https_proxy": url, "HTTP_PROXY": url, "http_proxy": url,
           "NO_PROXY": np, "no_proxy": np, "PIP_INDEX_URL": PIP_INDEX_URL}
    if is_research(arm):
        # The research proxy terminates TLS, so every client must trust the run's CA.
        env.update({"NODE_EXTRA_CA_CERTS": CA_IN_AGENT, "REQUESTS_CA_BUNDLE": CA_IN_AGENT,
                    "SSL_CERT_FILE": CA_IN_AGENT, "CURL_CA_BUNDLE": CA_IN_AGENT})
    return env


def build_commands(arm, prefix, repo, env_values):
    argv = ["docker", "build", "--platform", PLATFORM, "-f", str(repo / "environment/agent/Dockerfile")]
    for k, v in agent_build_args(arm, env_values).items():
        argv += ["--build-arg", "%s=%s" % (k, v)]
    out = [("build agent image",
            argv + ["-t", agent_image_tag(arm, prefix), str(repo / "environment/agent")])]
    if arm["route"]["kind"] == "gateway":
        out.append(("build gateway image",
                    ["docker", "build", "--platform", PLATFORM, "-f", str(repo / "environment/gateway/Dockerfile"),
                     "--build-arg", "APPLY_CACHE_USAGE_PATCH=%d"
                     % (1 if arm["route"]["gateway_patch"] != "none" else 0),
                     "-t", gateway_image_tag(arm, prefix), str(repo / "environment/gateway")]))
    if is_research(arm):
        out.append(("build research proxy image",
                    ["docker", "build", "--platform", PLATFORM, "-f", str(repo / "environment/research-proxy/Dockerfile"),
                     "-t", research_image_tag(prefix), str(repo / "environment/research-proxy")]))
    return out


def up_commands(arm, prefix, n, paths, proxy_script):
    """(label, argv, secret_names) to bring the run's resources up, in order."""
    lab = ["--label", n.label]
    cmds = [
        ("create internal network (no route out)",
         ["docker", "network", "create", "--internal"] + lab + [n.internal], ()),
        ("create egress network",
         ["docker", "network", "create"] + lab + [n.egress], ()),
    ]
    from .config import allowlist
    if is_research(arm):
        cmds.append(("start research proxy (TLS interception, policy %s)"
                     % arm["condition"]["research_policy"], research_proxy_argv(prefix, n, paths),
                     ()))
    else:
        cmds.append((
            "start allowlist proxy",
            ["docker", "run", "-d", "--platform", PLATFORM, "--name", n.proxy] + lab +
            ["--network", n.egress, "--log-driver", "none", "--read-only", "--cap-drop", "ALL",
             "--security-opt", "no-new-privileges", "--user", "65534:65534",
             "--memory", "256m", "--pids-limit", "256",
             "-v", "%s:/opt/proxy/egress_proxy.py:ro" % proxy_script,
             "-v", "%s:/log" % paths["proxy_log_dir"],
             PROXY_IMAGE, "python3", "/opt/proxy/egress_proxy.py", "--port", str(PROXY_PORT),
             "--allow", ",".join(allowlist(arm)), "--log", "/log/egress.jsonl"], ()))
    cmds.append(("attach proxy to the internal network",
                 ["docker", "network", "connect", "--alias", PROXY_ALIAS, n.internal, n.proxy],
                 ()))
    if arm["route"]["kind"] == "gateway":
        cmds.append((
            "start LiteLLM gateway",
            ["docker", "run", "-d", "--platform", PLATFORM, "--name", n.gateway] + lab +
            ["--network", n.egress, "--log-driver", "none", "--cap-drop", "ALL",
             "--security-opt", "no-new-privileges",
             "-e", "OPENROUTER_API_KEY", "-e", "LITELLM_MASTER_KEY", "-e", "LOCAL_MODEL_API_KEY"]
            + (["--add-host", "host.docker.internal:host-gateway"]
               if arm["route"].get("upstream") == "openai-compatible" else [])
            + ["-v", "%s:/config.yaml:ro" % paths["gateway_config"],
             gateway_image_tag(arm, prefix), "litellm", "--config", "/config.yaml",
             "--port", str(GATEWAY_PORT)],
            ("OPENROUTER_API_KEY", "LITELLM_MASTER_KEY", "LOCAL_MODEL_API_KEY")))
        cmds.append(("attach gateway to the internal network",
                     ["docker", "network", "connect", "--alias", GATEWAY_ALIAS, n.internal,
                      n.gateway], ()))
    env = proxy_env(arm)
    argv = (["docker", "run", "-d", "--platform", PLATFORM, "--name", n.agent] + lab
            + ["--network", n.internal, "--log-driver", "none"] + R.docker_flags())
    for k, v in env.items():
        argv += ["-e", "%s=%s" % (k, v)]
    argv += ["-v", "%s:%s" % (paths["workspace"], paths["ctr_workspace"]),
             "-w", paths["ctr_workspace"], agent_image_tag(arm, prefix), "sleep", "infinity"]
    cmds.append(("start agent container (internal network only)", argv, ()))
    return cmds


def research_proxy_argv(prefix, n, paths):
    """docker run of the research proxy: mitmdump with guard.py and addon.py, the run's
    configuration read only, a host folder for the decision log and the delivered bodies,
    and a host folder in which mitmproxy generates the run's CA. It runs as the invoking
    user, so everything it writes on the host belongs to that user."""
    from .research import PROXY_PORT as RESEARCH_PORT
    uid = "%d:%d" % (os.getuid(), os.getgid()) if hasattr(os, "getuid") else "1000:1000"
    return (["docker", "run", "-d", "--platform", PLATFORM, "--name", n.proxy, "--label", n.label,
             "--network", n.egress, "--log-driver", "none", "--read-only",
             "--tmpfs", "/tmp", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
             "--user", uid, "--memory", "1g", "--pids-limit", "512",
             "-v", "%s:/opt/research:ro" % RESEARCH_DIR,
             "-v", "%s:/policy:ro" % paths["research_config"],
             "-v", "%s:/logs" % paths["research_log_dir"],
             "-v", "%s:/ca" % paths["research_ca_dir"],
             "-e", "HOME=/tmp", "-e", "RESEARCH_CONFIG=/policy",
             "-e", "RESEARCH_LOG=/logs/decisions.jsonl", "-e", "RESEARCH_ARTIFACTS=/logs/artifacts",
             "-e", "RESEARCH_EXPECTED_EPOCH=%s" % paths.get("research_epoch", ""),
             "--entrypoint", "mitmdump", research_image_tag(prefix),
             "-q", "--set", "confdir=/ca", "--set", "connection_strategy=lazy",
             "--listen-host", "0.0.0.0", "--listen-port", str(RESEARCH_PORT),
             "-s", "/opt/research/guard.py", "-s", "/opt/research/addon.py"])


def research_ca_commands(n, ca_host_path):
    """Install the run's CA in the agent container (as root), in the order they run."""
    from .research import CA_IN_AGENT
    return [("copy the run's CA into the agent container",
             ["docker", "cp", str(ca_host_path), "%s:%s" % (n.agent, CA_IN_AGENT)]),
            ("add it to the system trust store",
             ["docker", "exec", "--user", "root", n.agent, "update-ca-certificates"]),
            ("check its sha256 inside the container",
             ["docker", "exec", "--user", "root", n.agent, "sha256sum", CA_IN_AGENT])]


def down_commands(n):
    return [("remove containers", ["docker", "rm", "-f", n.agent, n.gateway, n.proxy, n.probe]),
            ("remove networks", ["docker", "network", "rm", n.internal, n.egress])]


def render(argv):
    return " ".join(shlex.quote(x) for x in argv)


def run(argv, env_extra=None, check=True, timeout=None, input_bytes=None, quiet=False):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    r = subprocess.run(argv, env=env, capture_output=True, timeout=timeout, input=input_bytes)
    if check and r.returncode != 0:
        raise RuntimeError("command failed (%d): %s\n%s" % (
            r.returncode, render(argv)[:300], (r.stderr or b"").decode(errors="replace")[-800:]))
    return r


def gateway_config(arm):
    """LiteLLM config for one gateway arm. The model_name is the alias Claude Code is given.
    OpenRouter arms pin their providers as the formal runs did (a new model without a pin leaves
    the choice to OpenRouter); an openai-compatible arm points LiteLLM at its own endpoint."""
    r = arm["route"]
    if r.get("upstream") == "openai-compatible":
        return ("model_list:\n"
                "  - model_name: %s\n"
                "    litellm_params:\n"
                "      model: openai/%s\n"
                "      api_base: %s\n"
                "      api_key: os.environ/LOCAL_MODEL_API_KEY\n"
                "litellm_settings:\n"
                "  drop_params: true\n"
                "  telemetry: false\n"
                "general_settings: {master_key: os.environ/LITELLM_MASTER_KEY}\n"
                % (r["model_alias"], r["model_id"], r["api_base"]))
    if r["provider_order"]:
        provider = "{order: [%s], allow_fallbacks: %s}" % (
            ", ".join(r["provider_order"]), "true" if r["allow_fallbacks"] else "false")
    else:
        provider = "{allow_fallbacks: %s}" % ("true" if r["allow_fallbacks"] else "false")
    return ("model_list:\n"
            "  - model_name: %s\n"
            "    litellm_params:\n"
            "      model: openrouter/%s\n"
            "      api_key: os.environ/OPENROUTER_API_KEY\n"
            "      extra_body:\n"
            "        session_id: sciexam-%s\n"
            "        provider: %s\n"
            "litellm_settings:\n"
            "  drop_params: true\n"
            "  telemetry: false\n"
            "general_settings: {master_key: os.environ/LITELLM_MASTER_KEY}\n"
            % (r["model_alias"], r["model_id"], r["model_alias"], provider))
