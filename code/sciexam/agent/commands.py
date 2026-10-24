"""`sciexam run-agent`: rerun one ranked arm, or a Claude Fable 5.1 condition run, with the
released harness. Several arms can run in one call (`--agent a,b --parallel N`), each at a chosen
reasoning effort (`--effort`). `sciexam list-agents` shows the arms and the levels each accepts."""
import argparse
import json
import os
import secrets as _secrets
import subprocess
import sys
import time
from pathlib import Path

from .. import home as H
from . import conditions as K
from . import config as C
from . import custom as X
from . import docker_env as D
from . import effort as E
from . import ledger as LG
from . import newmodel as NM
from . import prompts as P
from . import resources as R
from . import task as T

PROBE_SCRIPT = r'''
import hashlib, json, os, socket, subprocess, sys, urllib.request
out = {}
def tcp(host, port):
    try:
        socket.create_connection((host, port), timeout=8).close()
        return "connected"
    except Exception as e:
        return "failed: %s" % type(e).__name__ + (" (%s)" % e if str(e) else "")
out["direct example.com:443 (no proxy)"] = tcp("example.com", 443)
out["direct 1.1.1.1:443 (no proxy)"] = tcp("1.1.1.1", 443)
proxy = os.environ["HTTPS_PROXY"].split("//", 1)[1]
ph, pp = proxy.rsplit(":", 1)
def connect(target):
    try:
        s = socket.create_connection((ph, int(pp)), timeout=10)
        s.sendall(("CONNECT %s HTTP/1.1\r\nHost: %s\r\n\r\n" % (target, target)).encode())
        line = s.recv(4096).split(b"\r\n", 1)[0].decode(errors="replace")
        s.close()
        return line
    except Exception as e:
        return "failed: %r" % e
out["proxy CONNECT example.com:443"] = connect("example.com:443")
try:
    urllib.request.urlopen("https://example.com/", timeout=15)
    out["https://example.com via HTTPS_PROXY"] = "reachable"
except Exception as e:
    out["https://example.com via HTTPS_PROXY"] = "blocked: %s" % e
for h in sys.argv[2:]:
    if h.startswith("http://"):
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(h, timeout=10) as r:
                out["gateway %s (internal network, no proxy)" % h] = "HTTP %d %s" % (r.status, r.read(60))
        except Exception as e:
            out["gateway %s (internal network, no proxy)" % h] = "failed: %r" % e
        continue
    out["proxy CONNECT %s:443 (route host)" % h] = connect(h + ":443")
r = subprocess.run([sys.executable, "-m", "pip", "download", "--no-deps", "--no-cache-dir",
                    "-d", "/tmp/dl", sys.argv[1]], capture_output=True, text=True, timeout=300)
files = sorted(os.listdir("/tmp/dl")) if os.path.isdir("/tmp/dl") else []
out["pip download %s" % sys.argv[1]] = {
    "returncode": r.returncode, "files": files,
    "sha256": [hashlib.sha256(open("/tmp/dl/" + f, "rb").read()).hexdigest() for f in files],
    "last_line": (r.stdout.strip().splitlines() or [""])[-1][:200],
    "stderr_tail": r.stderr.strip()[-300:]}
print(json.dumps(out, indent=1))
'''


def _hr(title):
    print("\n" + "=" * 100 + "\n" + title + "\n" + "=" * 100)


def _run_key(arm, a):
    import re
    key = a.run_name or "%s-%s" % (arm["arm"], time.strftime("%m%d-%H%M%S"))
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", key).strip("-")


def _paths(arm, a, key):
    wd = Path(a.workdir or (H.runs() / key)).resolve()
    # A condition run works in /work/<baseline arm>, so the path does not name the condition.
    ctr_name = a.run_name or (arm.get("condition") or {}).get("baseline_arm") or arm["arm"]
    out = {"workdir": str(wd), "workspace": str(wd / "workspace"),
           "results": str(wd / "results"), "proxy_log_dir": str(wd / "results" / "proxy"),
           "gateway_config": str(wd / "results" / "gateway_config.yaml"),
           "ctr_workspace": "/work/%s" % ctr_name}
    if arm.get("condition"):
        # Host-side folders of a condition run. None of them is mounted into the agent.
        out["condition_task"] = str(wd / "condition_task")
        out["private"] = str(wd / "private")
    if D.is_research(arm):
        out["research_config"] = str(wd / "results" / "research" / "config")
        out["research_log_dir"] = str(wd / "results" / "research" / "log")
        out["research_ca_dir"] = str(wd / "results" / "research" / "ca")
    return out


def _credentials(arm, a):
    envf = C.read_env_file(a.env_file)
    names = [n for n, _ in C.required_credentials(arm)]
    if arm["scaffold"]["name"] == "antigravity":
        names.append("ANTIGRAVITY_URL")
    vals = {n: C.credential(n, envf) for n in names}
    vals["SCIEXAM_PROVIDER_TZ"] = C.credential("SCIEXAM_PROVIDER_TZ", envf) or "UTC"
    if arm["route"]["kind"] == "gateway":
        vals["LITELLM_MASTER_KEY"] = (C.credential("LITELLM_MASTER_KEY", envf)
                                      or "sk-local-" + _secrets.token_hex(16))
        vals["ANTHROPIC_API_KEY"] = vals["LITELLM_MASTER_KEY"]
        vals.setdefault("OPENROUTER_API_KEY", "")
        vals["LOCAL_MODEL_API_KEY"] = C.credential("LOCAL_MODEL_API_KEY", envf) or "none"
    return vals, names


def _budget(arm, a):
    if a.smoke:
        return float(C.SMOKE_SECONDS)
    if a.hours is not None:
        return float(a.hours) * 3600.0
    return float(arm["budget"]["eligible_seconds"])


def _agent_first_command(arm, ctr_ws):
    """The first agent command line, with the prompt shown as <PROMPT>."""
    from .scaffolds import CLAUDE_BASE_FLAGS, CLAUDE_CACHE_FLAGS, AGY_BIN
    s = arm["scaffold"]["name"]
    if s == "claude-code":
        cmd = ["claude", "-p", "<PROMPT>"] + CLAUDE_BASE_FLAGS
        for t in arm["tools"]["disallowed"] or []:
            cmd += ["--disallowedTools", t]
        cmd += CLAUDE_CACHE_FLAGS + ["--model", arm["route"].get("model_alias")
                                     if arm["route"]["kind"] == "gateway"
                                     else arm["route"]["model_id"]]
        if arm["reasoning"]["pass_effort_flag"]:
            cmd += ["--effort", arm["reasoning"]["effort"]]
        return cmd
    if s == "codex":
        return ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "-m",
                arm["route"]["model_id"], "<PROMPT>"]
    return [AGY_BIN, "--model", arm["route"]["model_id"], "--dangerously-skip-permissions",
            "--input-format", "stream-json", "--output-format", "stream-json",
            "--print-timeout", "<turn budget + 300>s", "(prompt sent on stdin as stream-json)"]


def _condition_task_tree(arm, a, root):
    """Dry run: build the condition's task tree in a temporary folder and print it."""
    tree = arm["condition"]["task_tree"]
    _hr("TASK TREE (condition %s: built from the dataset task text and --task-data, then "
        "copied into the agent workspace)" % tree)
    t0 = time.time()
    rows, problems, manifest = K.dry_build(tree, root / "task", a.task_data, a.paper)
    for row in rows:
        mark = ("same bytes as the formal run" if row["same_as_formal"]
                else "DIFFERS from the formal run (formal %s)" % (row["formal_sha256"] or "?")[:16])
        print("  %-66s %s  %s" % (row["path"], row["sha256"][:16], mark))
    print("  submission/processed/  (empty folders, created by the harness)")
    for p in problems:
        print("  MISSING: " + p)
    full = not problems
    print("task tree sha256  %s%s" % (K.tree_sha256(rows), "" if full else "  (incomplete tree)"))
    print("formal tree       %s  (sha256 of the sorted 'path sha256' lines of the formal "
          "workspace)" % K.formal_tree_sha256(tree))
    print("data files        " + ", ".join("%s <- %s" % (d, s_) for d, s_ in
                                          sorted(manifest["planned_data"].items())))
    an = manifest.get("anonymisation")
    if an:
        print("anonymisation     epoch year +%d, %d text edits, every time step verified:"
              % (an["year_shift_years"], an["text_edits"]))
        for f, e in sorted(an["netcdf"].items()):
            print("  %-34s from %-22s %6d time steps, %d attribute edits (%s)" % (
                f, e["source"], e["time_steps"], len(e["attribute_edits"]),
                ", ".join(sorted({"%s:%s" % (x["var"], x["attr"]) for x in e["attribute_edits"]}))))
    elif tree == "years_anonymised":
        print("anonymisation     needs the raw data (--task-data) to build and verify the files")
    if tree == "years_anonymised":
        print("phase 1 gate      the agent's time labels (Y001-01, or the synthetic months the files "
              "decode to) are rewritten to real months in a private copy outside the workspace, "
              "graded by the data gate, and every month in the result is mapped back to a label; "
              "a result carrying any other date is not reported (label map derived from the raw "
              "SST time axis, kept in the run's private folder)")
    print("built in %.1f s (temporary folder, removed)" % (time.time() - t0))
    _hr("TASK TEXT DIFF (dataset task text -> workspace)")
    print(K.text_diff(tree, root / "task").rstrip())


def _tool_envelope(arm):
    _hr("TOOL ENVELOPE")
    if arm["scaffold"]["name"] != "claude-code":
        print("not a Claude Code arm: see the scaffold block of the arm config")
        return
    dis = list(arm["tools"]["disallowed"] or [])
    print("--disallowedTools  %d tools: %s" % (len(dis), " ".join(dis)))
    cond = arm.get("condition")
    if cond:
        und = cond["undenied_tools"] or []
        print("condition          %s" % ("undenies %s against the baseline arm %s"
                                         % (", ".join(und), cond["baseline_arm"]) if und else
                                         "the envelope of the baseline arm %s" % cond["baseline_arm"]))


def _research_policy(arm, a, root, n, paths):
    """Dry run: stage the research configuration in a temporary folder and print it."""
    import tempfile
    from . import research as RS
    cond = arm["condition"]
    name = cond["research_policy"]
    pol, works, content = RS.load(name, a.benchmark_self)
    tmp = Path(tempfile.mkdtemp(prefix="sciexam-research-"))
    try:
        digests = RS.stage(name, list(K.task_texts(cond["task_tree"], root / "task").values()),
                           tmp, a.benchmark_self)
        epoch = RS.expected_epoch(tmp)
        shingles = json.loads((tmp / "shingles.json").read_text())["count"]
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    paths["research_epoch"] = epoch
    print("research proxy    %s on %s and %s, alias %s:%d (image %s: mitmproxy 12.1.2, "
          "mitmdump -s guard.py -s addon.py)" % (n.proxy, n.egress, n.internal, D.PROXY_ALIAS,
                                                 RS.PROXY_PORT, D.research_image_tag(a.name_prefix)))
    print("policy            %s (sciexam/agent/research/policies/%s.json): %s"
          % (name, name, pol["description"]))
    print("default           %s; methods %s, no request body; header allowlist of %d names"
          % (pol["default_decision"], "/".join(pol["allowed_methods"]),
             len(pol["request_header_allowlist"])))
    print("TLS               intercepted with a CA generated for this run in %s, installed in the "
          "agent at %s" % (paths["research_ca_dir"], RS.CA_IN_AGENT))
    print("passthrough       " + ", ".join(pol["passthrough_hosts"]) + " (never decrypted)")
    print("telemetry refused " + ", ".join(pol["silent_deny_hosts"]))
    print("addresses         every resolved address must be global and outside "
          + ", ".join(pol["blocked_networks"]) + "; names " + ", ".join(pol["blocked_hostnames"]))
    print("prohibited works  %d (hashed identifiers, titles and phrases), content fingerprints "
          "%d runs in %d works, scored-target patterns %d"
          % (len(works["works"]), sum(len(r) for w in content["works"] for r in w["regions"]),
             len(content["works"]), len(works.get("scored_target_regexes", []))))
    bs = pol["benchmark_self"]
    print("benchmark pages   %d hosts, %d URL fragments, %d phrases%s"
          % (len(bs["hosts"]), len(bs["url_substrings"]), len(bs["phrases"]),
             "" if any(bs.values()) else "  (EMPTY: list the benchmark's own public pages in "
             "sciexam/agent/research/benchmark_self.json or pass --benchmark-self FILE)"))
    print("data sources      %s" % ("refused: %d hosts, %d path fragments, %d extensions" % (
        len(pol["data_hosts"]), len(pol["data_url_substrings"]), len(pol["data_extensions"]))
        if pol["data_hosts"] else "allowed"))
    if pol["data_hosts"]:
        print("  hosts           " + ", ".join(pol["data_hosts"]))
        print("  paths           " + " ".join(pol["data_url_substrings"]))
        print("  extensions      " + " ".join(pol["data_extensions"]))
    print("header shape      punctuation-density test on header values: %s"
          % ("yes" if pol["header_punctuation_check"] else "no"))
    print("listings          %s" % {"any_mention": "a search listing that names a prohibited "
                                    "work is redacted (Atom, JSON) or withheld (HTML)",
                                    "blocked_only": "a search listing is redacted only when it "
                                    "would be blocked as a whole"}[pol["listing_redaction"]])
    print("workspace runs    %d eight-word runs of the workspace task text (exfiltration check)"
          % shingles)
    print("config files      " + ", ".join("%s %s" % (k, v[:16]) for k, v in sorted(digests.items())))
    print("epoch             %s (the guard refuses all traffic under any other)" % epoch)
    print("log               %s/decisions.jsonl, delivered bodies in %s/artifacts"
          % (paths["research_log_dir"], paths["research_log_dir"]))


def dry_run(arm, a, root):
    t0 = time.time()
    key = _run_key(arm, a)
    n = D.Names(a.name_prefix, key)
    paths = _paths(arm, a, key)
    budget = _budget(arm, a)
    creds, names = _credentials(arm, a)
    repo = D.repo_root() or Path(".")
    L = dict(arm["lifecycle"])
    if a.smoke:
        L.update(C.SMOKE_OVERRIDES)

    _hr("ARM  %s  (%s)" % (arm["arm"], arm["_path"]))
    s, r = arm["scaffold"], arm["route"]
    print("display name      %s  (runs.csv %s, campaign %s)" % (
        arm.get("display_name"), arm.get("run_id"), arm.get("campaign_id")))
    print("scaffold          %s %s  binary sha256 %s" % (s["name"], s["version"], s["binary_sha256"]))
    if r["kind"] == "gateway":
        print("route             gateway: LiteLLM %s (patch: %s) -> %s, model %s as alias %r"
              % (r["gateway_version"], r["gateway_patch"], r["upstream"], r["model_id"],
                 r["model_alias"]))
        print("provider pin      order %s, allow_fallbacks %s" % (r["provider_order"],
                                                                 r["allow_fallbacks"]))
    else:
        print("route             subscription: %s, model %s" % (r.get("product"), r["model_id"]))
    print("reasoning effort  %s (%s)" % (arm["reasoning"]["effort"],
                                         "--effort flag" if arm["reasoning"]["pass_effort_flag"]
                                         else "no flag: CLI default, config file or model id"))
    for k, v in (arm.get("custom") or {}).items():
        if k != "comparable_with_paper":
            print("custom            %s: %s  (not comparable with the official leaderboard)" % (k, v))
    if "paper_effort" in arm["reasoning"] and not arm["reasoning"]["comparable_with_paper"]:
        print("                  CHANGED from the leaderboard's %s: not comparable with the official leaderboard"
              % arm["reasoning"]["paper_effort"])
    c = arm["context"]
    print("context policy    %s tokens, %s, enforced=%s%s" % (
        c["working_context_tokens"], c.get("mechanism"), c.get("enforced"),
        ", env %s" % c["env"] if c.get("env") else ""))
    print("resource gate     %s" % arm["resource_gate"])
    if arm.get("declared"):
        print("declared          %s  (not comparable with the official leaderboard)" % arm["declared"])
    if (arm.get("preflight") or {}).get("tool_call"):
        print("preflight         one tool-call request through the gateway before the budget starts")
    print("budget            %.0f s eligible%s" % (budget, "  (SMOKE, not comparable)" if a.smoke else ""))
    h, at_once = R.host(), a.agents_at_once or 1
    print("compute           each agent capped at %d CPUs and %d GB; Docker here: %s, holds %d at once"
          % (R.AGENT_CPUS, R.AGENT_MEMORY_GB, "%d CPUs, %.1f GB" % (h["cpus"], h["memory_gb"])
             if h else "not answering", R.fit(h)))
    for prob in R.problems(h, at_once, paths["workdir"]):
        print("                  PROBLEM: " + prob)
    print("lifecycle         " + ", ".join("%s=%s" % kv for kv in L.items()))
    cond = arm.get("condition")
    if cond:
        print("condition         %s: %s" % (cond["name"], cond.get("description")))
        print("                  baseline arm %s, task tree %s, network %s%s, undenied tools %s"
              % (cond["baseline_arm"], cond["task_tree"], cond["network"],
                 " (policy %s)" % cond["research_policy"] if cond.get("research_policy") else "",
                 ", ".join(cond["undenied_tools"] or []) or "none"))

    _hr("PATHS")
    for k, v in paths.items():
        print("%-18s %s" % (k, v))
    print("snapshots          %s/snapshots/round_NN (outside the agent workspace)" % paths["results"])

    if cond:
        _condition_task_tree(arm, a, root)
    else:
        _hr("TASK TREE (copied into the agent workspace)")
        rows, excluded, problems = T.plan(root / "task", a.task_data, a.paper)
        for row in rows:
            mark = ("same bytes as the formal runs" if row["same_as_formal"]
                    else "DIFFERS from the formal runs (formal %s)" % (row["formal_sha256"] or "?")[:16])
            print("  %-66s %s  %s" % (row["path"], row["sha256"][:16], mark))
        print("  submission/processed/  (empty folders, created by the harness)")
        print("excluded from the workspace:")
        for e in excluded:
            print("  %-66s %s" % (e, T.excluded_reason(e)))
        for p in problems:
            print("  MISSING: " + p)
    _tool_envelope(arm)

    _hr("IMAGES")
    for label, argv in D.build_commands(arm, a.name_prefix, repo, creds):
        print("# " + label)
        print(D.render(argv))

    _hr("NETWORK POLICY")
    print("agent container   networks: %s only (docker network create --internal: no route out)"
          % n.internal)
    if D.is_research(arm):
        _research_policy(arm, a, root, n, paths)
    else:
        print("egress proxy      %s on %s and %s, alias %s:%d, CONNECT to port 443 only"
              % (n.proxy, n.egress, n.internal, D.PROXY_ALIAS, D.PROXY_PORT))
        print("proxy allowlist   " + ", ".join(C.allowlist(arm)))
    if r["kind"] == "gateway":
        print("gateway           %s on %s and %s, alias %s:%d, upstream %s"
              % (n.gateway, n.egress, n.internal, D.GATEWAY_ALIAS, D.GATEWAY_PORT,
                 ", ".join(C.gateway_allowlist(arm))))
    print("agent env         " + " ".join("%s=%s" % kv for kv in D.proxy_env(arm).items()))
    if not D.is_research(arm):
        print("everything else   refused by the proxy (403), no DNS or route for direct connections")

    _hr("CONTAINER SPEC (in order, credentials pass as -e NAME and never as values)")
    for label, argv, sec in D.up_commands(arm, a.name_prefix, n, paths,
                                          Path(__file__).parent / "egress_proxy.py"):
        print("# " + label + ("   [secrets from the environment: %s]" % ", ".join(sec) if sec else ""))
        print(D.render(argv))
    if r["kind"] == "gateway":
        print("# gateway config (%s):" % paths["gateway_config"])
        print(D.gateway_config(arm).rstrip())
    if D.is_research(arm):
        print("# wait for %s/mitmproxy-ca-cert.pem, then install it as root:" % paths["research_ca_dir"])
        for label, argv in D.research_ca_commands(n, Path(paths["research_ca_dir"])
                                                  / "mitmproxy-ca-cert.pem"):
            print("#   " + label)
            print(D.render(argv))
    if arm["scaffold"]["name"] == "codex":
        from .scaffolds import Codex
        fake = type("R", (), {"arm": arm})()
        print("# codex config.toml (written to <workspace>/.codex each turn):")
        print(Codex(fake).config_text().rstrip())
    print("# teardown")
    for label, argv in D.down_commands(n):
        print(D.render(argv))

    _hr("FIRST AGENT COMMAND (docker exec -w %s --user %s %s ...)" % (
        paths["ctr_workspace"], L["agent_uid"], n.agent))
    print(D.render(_agent_first_command(arm, paths["ctr_workspace"])))

    _hr("CREDENTIALS (values never printed)")
    for nm, desc in C.required_credentials(arm):
        print("  %-26s %-8s %s" % (nm, "set" if creds.get(nm) else "MISSING", desc))
    if arm["scaffold"]["name"] == "antigravity":
        print("  %-26s %-8s %s" % ("ANTIGRAVITY_URL", "set" if creds.get("ANTIGRAVITY_URL")
                                   else "MISSING", "official Antigravity CLI download (build time)"))
    if r["kind"] == "gateway":
        print("  %-26s %-8s %s" % ("LITELLM_MASTER_KEY", "set", "local gateway key (generated per run "
                                   "unless given)"))

    _hr("PROMPTS (byte identical to the formal runs, persistent-memory policy appended to each)")
    b_min = budget / 60.0
    shown = [("Phase 1", P.phase1_prompt()),
             ("Phase 2A (at the start of the budget)", P.phase2a_prompt(b_min)),
             ("Phase 2B brief (example: 300 minutes left)", P.phase2_prompt(300.0)),
             ("Phase 2B resume", P.RESUME_PROMPT)]
    for i, sp in enumerate(P.STALL_PROMPTS):
        shown.append(("Phase 2B stall escalation %d (after %d s without a new snapshot)"
                      % (i + 1, (i + 1) * L["stall_escalate_s"]), sp))
    if cond and cond["task_tree"] == "years_anonymised":
        shown.append(("Phase 1 feedback, anonymised table missing", P.ANON_P1_MISSING))
        shown.append(("Phase 1 feedback, time labels rejected (example)",
                      P.ANON_P1_REJECTED % "time labels are not in the required Y001-01 .. "
                                           "Y035-12 form (3 of 420 rows)"))
        shown.append(("Phase 1 feedback, result not reportable", P.ANON_P1_UNREPORTABLE))
    if arm["scaffold"]["name"] == "antigravity":
        shown.append(("Antigravity workspace preamble (prefixed to every user turn)",
                      P.ANTIGRAVITY_PREAMBLE.format(wd=paths["ctr_workspace"])))
        shown.append(("Antigravity continuation (Phase 2B, submission still changing)",
                      P.ANTIGRAVITY_CONTINUE))
    for title, text in shown:
        full = P.with_memory_policy(text)
        print("\n--- %s  [%d bytes]" % (title, len(full.encode())))
        print(full)
    if arm["scaffold"]["name"] == "claude-code":
        print("\n--- Stop hook script (Phase 2B, %s/.home/.claude/stop-hook.sh)" % paths["ctr_workspace"])
        print(P.STOP_HOOK)
    print("\n--- sha256 of the fixed texts")
    for k, v in P.prompt_digests().items():
        print("  %-26s %s" % (k, v))
    print("\ndry run assembled in %.2f s (no container started)" % (time.time() - t0))
    return 0


def net_check(arm, a):
    """Bring up the networks and the proxy of this arm and probe them from a throwaway
    container on the internal network. Removes everything it created."""
    key = _run_key(arm, a) + "-netcheck"
    n = D.Names(a.name_prefix, key)
    paths = _paths(arm, a, key)
    Path(paths["proxy_log_dir"]).mkdir(parents=True, exist_ok=True)
    os.chmod(paths["proxy_log_dir"], 0o777)
    route_hosts = [h for h in C.allowlist(arm) if h not in C.PIP_HOSTS][:1]
    t0 = time.time()
    cmds = D.up_commands(arm, a.name_prefix, n, paths, Path(__file__).parent / "egress_proxy.py")
    with_gateway = (arm["route"]["kind"] == "gateway" and subprocess.run(
        ["docker", "image", "inspect", D.gateway_image_tag(arm, a.name_prefix)],
        capture_output=True).returncode == 0)
    cmds = [c for c in cmds if "agent container" not in c[0]
            and (with_gateway or "gateway" not in c[0])]
    if with_gateway:
        Path(paths["gateway_config"]).write_text(D.gateway_config(arm))
        route_hosts = ["http://%s:%d/health/liveliness" % (D.GATEWAY_ALIAS, D.GATEWAY_PORT)]
    # a placeholder upstream key: the check never calls the model
    dummy = {"OPENROUTER_API_KEY": "placeholder", "LITELLM_MASTER_KEY": "sk-net-check"}
    try:
        for label, argv, sec in cmds:
            print("[net-check] " + label)
            D.run(argv, env_extra={k: dummy[k] for k in sec})
        time.sleep(2)
        if with_gateway:
            for _ in range(60):
                h = subprocess.run(["docker", "exec", n.gateway, "python", "-c",
                                    "import urllib.request;urllib.request.urlopen("
                                    "'http://127.0.0.1:%d/health/liveliness',timeout=2)"
                                    % D.GATEWAY_PORT], capture_output=True)
                if h.returncode == 0:
                    break
                time.sleep(2)
        probe = ["docker", "run", "--rm", "--platform", D.PLATFORM, "--name", n.probe, "--label", n.label,
                 "--log-driver", "none", "--network", n.internal, "--user", "65534:65534",
                 "-e", "HOME=/tmp"]
        for k, v in D.proxy_env(arm).items():
            probe += ["-e", "%s=%s" % (k, v)]
        probe += [a.probe_image or D.PROXY_IMAGE, "python3", "-c", PROBE_SCRIPT,
                  a.probe_package] + route_hosts
        print("[net-check] probe container on %s only" % n.internal)
        t1 = time.time()
        r = subprocess.run(probe, capture_output=True, text=True, timeout=600)
        print(r.stdout)
        if r.returncode != 0:
            print(r.stderr[-2000:])
        print("[net-check] probe ran %.1f s" % (time.time() - t1))
        log = Path(paths["proxy_log_dir"]) / "egress.jsonl"
        if log.exists():
            print("[net-check] proxy decisions:")
            for line in log.read_text().splitlines():
                print("  " + line)
        try:
            res = json.loads(r.stdout)
        except ValueError:
            res = {}
        ok = (all(str(v).startswith("failed") for k, v in res.items() if k.startswith("direct"))
              and all(str(v).startswith("HTTP 200") for k, v in res.items()
                      if k.startswith("gateway"))
              and "403" in str(res.get("proxy CONNECT example.com:443", ""))
              and res.get("pip download %s" % a.probe_package, {}).get("returncode") == 0)
    finally:
        for label, argv in D.down_commands(n):
            subprocess.run(argv, capture_output=True)
        print("[net-check] removed containers and networks of %s" % n.label)
    print("[net-check] %s in %.1f s" % ("PASS" if ok else "FAIL", time.time() - t0))
    return 0 if ok else 1


RESEARCH_PROBE_SCRIPT = r'''
import json, os, socket, ssl, subprocess, sys, urllib.error, urllib.request
out = {}
def tcp(host, port):
    try:
        socket.create_connection((host, port), timeout=8).close()
        return "connected"
    except Exception as e:
        return "failed: %s" % type(e).__name__
out["direct example.com:443 (no proxy)"] = tcp("example.com", 443)
out["direct 1.1.1.1:443 (no proxy)"] = tcp("1.1.1.1", 443)
def fetch(url, method="GET"):
    req = urllib.request.Request(url, method=method, data=b"x" if method == "POST" else None,
                                 headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return "HTTP %d" % r.status
    except urllib.error.HTTPError as e:
        return "HTTP %d" % e.code
    except Exception as e:
        return "failed: %r" % e
out["GET https://example.com/"] = fetch("https://example.com/")
out["POST https://example.com/"] = fetch("https://example.com/", "POST")
out["GET prohibited arXiv id"] = fetch("https://arxiv.org/abs/2402.04585")
out["GET data page"] = fetch(sys.argv[2])
ph, pp = os.environ["HTTPS_PROXY"].split("//", 1)[1].rsplit(":", 1)
def passthrough(host):
    try:
        s = socket.create_connection((ph, int(pp)), timeout=15)
        s.sendall(("CONNECT %s:443 HTTP/1.1\r\nHost: %s:443\r\n\r\n" % (host, host)).encode())
        line = s.recv(4096).split(b"\r\n", 1)[0].decode(errors="replace")
        ctx = ssl.create_default_context(cafile="/etc/ssl/certs/ca-certificates.crt")
        t = ctx.wrap_socket(s, server_hostname=host)
        issuer = dict(x[0] for x in t.getpeercert()["issuer"]).get("organizationName")
        t.close()
        return "%s, public certificate (issuer %s)" % (line, issuer)
    except Exception as e:
        return "failed: %r" % e
out["passthrough " + sys.argv[3]] = passthrough(sys.argv[3])
r = subprocess.run([sys.executable, "-m", "pip", "download", "--no-deps", "--no-cache-dir",
                    "-d", "/tmp/dl", sys.argv[1]], capture_output=True, text=True, timeout=300)
out["pip download %s" % sys.argv[1]] = "returncode %d: %s" % (
    r.returncode, (r.stderr.strip().splitlines() or r.stdout.strip().splitlines() or [""])[-1][:160])
print(json.dumps(out, indent=1))
'''
DATA_PROBE_URL = "https://psl.noaa.gov/data/gridded/data.noaa.ersst.v5.html"


def research_net_check(arm, a, root):
    """Bring up the research proxy of a web condition and probe it from a throwaway container
    on the internal network: no direct route, TLS interception with the run's CA, a prohibited
    identifier refused, uploads refused, the data-source rule of the policy, and TLS
    passthrough for the model host. Removes every container and network it created."""
    from . import research as RS
    key = _run_key(arm, a) + "-netcheck"
    n = D.Names(a.name_prefix, key)
    paths = _paths(arm, a, key)
    cond = arm["condition"]
    texts = list(K.task_texts(cond["task_tree"], root / "task").values())
    RS.stage(cond["research_policy"], texts, paths["research_config"], a.benchmark_self)
    for k in ("research_log_dir", "research_ca_dir"):
        Path(paths[k]).mkdir(parents=True, exist_ok=True)
    paths["research_epoch"] = RS.expected_epoch(paths["research_config"])
    repo = D.repo_root()
    if subprocess.run(["docker", "image", "inspect", D.research_image_tag(a.name_prefix)],
                      capture_output=True).returncode != 0:
        label, argv = [c for c in D.build_commands(arm, a.name_prefix, repo, {})
                       if "research" in c[0]][0]
        print("[net-check] " + label)
        subprocess.run(argv, check=True, capture_output=True)
    t0 = time.time()
    cmds = [c for c in D.up_commands(arm, a.name_prefix, n, paths,
                                     Path(__file__).parent / "egress_proxy.py")
            if "agent container" not in c[0]]
    pol = RS.load(cond["research_policy"], a.benchmark_self)[0]
    ok = False
    try:
        for label, argv, _sec in cmds:
            print("[net-check] " + label)
            D.run(argv)
        ca = Path(paths["research_ca_dir"]) / "mitmproxy-ca-cert.pem"
        log = Path(paths["research_log_dir"]) / "decisions.jsonl"
        for _ in range(60):
            if ca.exists() and log.exists() and "policy_loaded" in log.read_text():
                break
            time.sleep(1)
        probe = ["docker", "run", "--rm", "--platform", D.PLATFORM, "--name", n.probe, "--label", n.label,
                 "--log-driver", "none", "--network", n.internal, "--user", "65534:65534",
                 "-e", "HOME=/tmp", "-v", "%s:/ca:ro" % paths["research_ca_dir"],
                 "-e", "SSL_CERT_FILE=/ca/mitmproxy-ca-cert.pem",
                 "-e", "REQUESTS_CA_BUNDLE=/ca/mitmproxy-ca-cert.pem"]
        for k, v in D.proxy_env(arm).items():
            if k not in ("NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE",
                         "CURL_CA_BUNDLE"):
                probe += ["-e", "%s=%s" % (k, v)]
        probe += [a.probe_image or D.PROXY_IMAGE, "python3", "-c", RESEARCH_PROBE_SCRIPT,
                  a.probe_package, DATA_PROBE_URL, arm["route"]["agent_hosts"][0]]
        print("[net-check] probe container on %s only" % n.internal)
        r = subprocess.run(probe, capture_output=True, text=True, timeout=900)
        print(r.stdout)
        if r.returncode != 0:
            print(r.stderr[-2000:])
        print("[net-check] proxy decisions:")
        for line in log.read_text().splitlines() if log.exists() else []:
            rec = json.loads(line)
            print("  %-6s %-26s %-6s %s  %s" % (rec.get("decision"), rec.get("event") or "",
                                               rec.get("status") or "", rec.get("url") or
                                               rec.get("policy") or "", (rec.get("reason") or "")[:90]))
        try:
            res = json.loads(r.stdout)
        except ValueError:
            res = {}
        data_want = "HTTP 451" if pol["data_hosts"] else None
        data_got = str(res.get("GET data page", ""))
        ok = (all(str(v).startswith("failed") for k, v in res.items() if k.startswith("direct"))
              and res.get("GET https://example.com/") == "HTTP 200"
              and res.get("POST https://example.com/") == "HTTP 405"
              and res.get("GET prohibited arXiv id") == "HTTP 451"
              and (data_got == data_want if data_want else data_got.startswith("HTTP")
                   and data_got != "HTTP 451")
              and "public certificate" in str(res.get("passthrough %s"
                                                      % arm["route"]["agent_hosts"][0], "")))
    finally:
        for label, argv in D.down_commands(n):
            subprocess.run(argv, capture_output=True)
        print("[net-check] removed containers and networks of %s" % n.label)
    print("[net-check] %s in %.1f s" % ("PASS" if ok else "FAIL", time.time() - t0))
    return 0 if ok else 1


def _anonymised_gate(a, paths, record):
    """The Phase 1 gate of the year-anonymised condition. The label map is derived from the
    raw SST file and written to the private folder next to the run (never mounted)."""
    import functools
    from . import anonymise as A
    from . import data_gate
    private = Path(paths["private"])
    private.mkdir(parents=True, exist_ok=True)
    os.chmod(private, 0o700)
    M = A.time_map(Path(a.task_data) / A.TIME_SOURCE)
    (private / "anon_time_map.json").write_text(json.dumps(M, indent=1))
    record["time_map"] = {"months": M["n_months"], "labels": "%s .. %s" % (
        M["anon_first"], M["anon_last"]), "year_shift": M["year_shift"],
        "path": str(private / "anon_time_map.json")}
    return functools.partial(A.gate, M=M, private_dir=private, grade=data_gate.grade)


def _stage_research(arm, a, paths, rows):
    """Write the research proxy configuration of this run and return its record."""
    from . import research as RS
    cond = arm["condition"]
    texts = [Path(r["source"]).read_text(encoding="utf-8") for r in rows
             if r["path"] in T.TASK_TEXT_FILES]
    digests = RS.stage(cond["research_policy"], texts, paths["research_config"], a.benchmark_self)
    for k in ("research_log_dir", "research_ca_dir"):
        Path(paths[k]).mkdir(parents=True, exist_ok=True)
    paths["research_epoch"] = RS.expected_epoch(paths["research_config"])
    return {"policy": cond["research_policy"], "config_sha256": digests,
            "epoch": paths["research_epoch"], "log": paths["research_log_dir"]}


def _install_research_ca(n, paths, timeout=60):
    """Wait for the research proxy to generate its CA and load the policy, then install the
    CA in the agent container and check it there by sha256."""
    from ..dataset import sha256_file
    ca = Path(paths["research_ca_dir"]) / "mitmproxy-ca-cert.pem"
    log = Path(paths["research_log_dir"]) / "decisions.jsonl"
    t0 = time.time()
    while not (ca.exists() and log.exists() and "policy_loaded" in log.read_text()):
        if time.time() - t0 > timeout:
            raise RuntimeError("the research proxy did not come up (no CA or no policy_loaded "
                               "record in %s)" % log)
        time.sleep(1)
    want = sha256_file(ca)
    out = b""
    for label, argv in D.research_ca_commands(n, ca):
        out = D.run(argv).stdout
    if want not in (out or b"").decode(errors="replace"):
        raise RuntimeError("the CA in the agent container is not the proxy's CA")
    return want


def live_run(arm, a, root):
    from .orchestrator import Run, orchestrate
    from .scaffolds import ADAPTERS, Container, sha256_in_container
    key = _run_key(arm, a)
    n = D.Names(a.name_prefix, key)
    paths = _paths(arm, a, key)
    creds, names = _credentials(arm, a)
    missing = [nm for nm in names if not creds.get(nm)]
    if missing:
        raise RuntimeError("missing credentials: %s (see .env.example)" % ", ".join(missing))
    ws = Path(paths["workspace"])
    if ws.exists() and any(ws.iterdir()):
        raise RuntimeError("workspace %s is not empty, use a new --workdir" % ws)
    host, at_once = R.host(), a.agents_at_once or 1
    short = R.problems(host, at_once, paths["workdir"])
    if short:
        raise RuntimeError("this machine does not meet the run's spec:\n  " + "\n  ".join(short))
    cond = arm.get("condition")
    condition_record = None
    if cond:
        rows, problems, condition_record = K.build(cond["task_tree"], root / "task", a.task_data,
                                                   a.paper, paths["condition_task"])
    else:
        rows, _, problems = T.plan(root / "task", a.task_data, a.paper)
    if problems and not a.smoke:
        raise RuntimeError("task tree incomplete:\n  " + "\n  ".join(problems))
    if cond and cond["task_tree"] == "years_anonymised" and "anonymisation" not in condition_record:
        raise RuntimeError("the year-anonymised tree needs the raw data, even for a smoke run "
                           "(--task-data OUT/raw)")
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "submission" / "processed").mkdir(parents=True)
    T.install(rows, ws)
    res_dir = Path(paths["results"])
    res_dir.mkdir(parents=True, exist_ok=True)
    Path(paths["proxy_log_dir"]).mkdir(parents=True, exist_ok=True)
    os.chmod(paths["proxy_log_dir"], 0o777)
    if arm["route"]["kind"] == "gateway":
        Path(paths["gateway_config"]).write_text(D.gateway_config(arm))
    gate = None
    if cond and cond["task_tree"] == "years_anonymised":
        gate = _anonymised_gate(a, paths, condition_record)
    if D.is_research(arm):
        condition_record["research"] = _stage_research(arm, a, paths, rows)
    repo = D.repo_root()
    if not a.no_build:
        if repo is None:
            raise RuntimeError("environment/agent/Dockerfile not found: run from a source checkout "
                               "or pass --no-build with prebuilt images")
        for label, argv in D.build_commands(arm, a.name_prefix, repo, creds):
            print("[build] " + label)
            subprocess.run(argv, check=True)
    lifecycle = dict(arm["lifecycle"])
    if a.smoke:
        lifecycle.update(C.SMOKE_OVERRIDES)
    arm = dict(arm, lifecycle=lifecycle)
    ctr = Container(n.agent, lifecycle["agent_uid"])
    os.environ["SCIEXAM_PROVIDER_TZ"] = creds.get("SCIEXAM_PROVIDER_TZ", "UTC")
    sealed_chain = None
    sampler = None
    try:
        for label, argv, sec in D.up_commands(arm, a.name_prefix, n, paths,
                                              Path(__file__).parent / "egress_proxy.py"):
            print("[up] " + label)
            D.run(argv, env_extra={k: creds.get(k, "") for k in sec})
        cws = paths["ctr_workspace"]
        ctr.root(["chown", "-R", lifecycle["agent_uid"], cws])
        ctr.root(["chmod", "0777", cws])
        if arm["resource_gate"]:
            _install_resource_gate(ctr)
        if D.is_research(arm):
            condition_record["research"]["ca_sha256"] = _install_research_ca(n, paths)
        run = Run(arm, ws, cws, res_dir, ctr, D.proxy_env(arm), creds,
                  root / "grader_obs" / "indices_truth.nc", smoke=a.smoke, gate=gate)
        agent = ADAPTERS[arm["scaffold"]["name"]](run)
        agent.prepare()
        binary = {"claude-code": "claude", "codex": "codex", "antigravity": "agy"}[
            arm["scaffold"]["name"]]
        ident = sha256_in_container(ctr, binary)
        run.log({"event": "cli_identity", "binary": binary, "version": ident.get("VER"),
                 "sha256": ident.get("SHA"), "expected_sha256": arm["scaffold"]["binary_sha256"]})
        if ident.get("SHA") != arm["scaffold"]["binary_sha256"]:
            raise RuntimeError("the %s binary in the agent image (sha256 %s) is not the pinned one %s"
                               % (binary, ident.get("SHA"), arm["scaffold"]["binary_sha256"]))
        if arm["route"]["kind"] == "gateway":
            _wait_gateway(ctr, run)
            if (arm.get("preflight") or {}).get("tool_call") and not a.smoke:
                _preflight_tool_call(ctr, run, arm, creds)
        meta = {"arm": arm["arm"], "run_id": arm.get("run_id"), "scaffold": arm["scaffold"],
                "route": arm["route"], "reasoning": arm["reasoning"], "context": arm["context"],
                "lifecycle": lifecycle, "budget_s": _budget(arm, a), "smoke": a.smoke,
                "network_allowlist": C.allowlist(arm), "prompt_sha256": P.prompt_digests(),
                "custom": arm.get("custom"), "resources": R.record(host, at_once, paths["workdir"]),
                "task_files": rows, "reference_paper": T.reference_paper(rows),
                "task_data": T.task_data(rows), "started_epoch": int(time.time())}
        inputs = T.inputs_note(meta["reference_paper"], meta["task_data"])
        # What the run's submission needs, fixed now rather than asked after six hours: the
        # leaderboard name, the contact, and (for a full run) how many runs of this system the
        # ledger now holds, this one included.
        contact = a.contact or LG.load_profile().get("contact")
        LG.save_contact(a.contact)
        meta["submission"] = {"system_name": LG.system_name(arm, _budget(arm, a), inputs),
                              "contact": contact}
        if not a.smoke:
            meta["submission"]["runs_attempted"] = LG.record_start(arm, _budget(arm, a), key,
                                                                   paths["workdir"], inputs)
        if cond:
            meta["condition"] = dict(K.summary(arm), **condition_record)
            meta["condition"]["task_tree_sha256"] = K.tree_sha256(rows)
            meta["condition"]["formal_task_tree_sha256"] = K.formal_tree_sha256(cond["task_tree"])
            meta["tools_disallowed"] = arm["tools"]["disallowed"]
            meta["network"] = cond["network"]
            if D.is_research(arm):
                meta["network_allowlist"] = None      # the research policy decides instead
            # A condition's run_meta names host paths and, for the anonymised tree, the raw
            # data files, so it is kept out of the agent workspace.
            (res_dir / "run_meta.json").write_text(json.dumps(meta, indent=2, default=str))
        else:
            (ws / "run_meta.json").write_text(json.dumps(meta, indent=2, default=str))
        sampler = R.Sampler(n.agent, res_dir).start()
        out = orchestrate(run, agent, _budget(arm, a))
        sampler.stop()
        sampler = None
        out["ended_epoch"] = int(time.time())
        (res_dir / "summary.json").write_text(json.dumps(out, indent=2, default=str))
        for f in ("trajectory.jsonl", "run_meta.json", "agent_output.txt"):
            if (ws / f).exists():
                (res_dir / f).write_bytes((ws / f).read_bytes())
        print("run finished: %s, %d snapshots in %s" % (
            out["status"], len(out.get("learning_curve") or []), res_dir / "snapshots"))
        print("grade a snapshot with: sciexam grade-sample %s/snapshots/round_NN"
              % res_dir)
        sealed_chain = run.seal_chain
        return 0 if out["status"] == "complete" else 1
    finally:
        if sampler is not None:
            sampler.stop()
        if not a.keep:
            for label, argv in D.down_commands(n):
                subprocess.run(argv, capture_output=True)
        # Seal the results once the proxy and gateway are down, so that no log can still grow.
        # A run that did not reach its end is not sealed and cannot be packaged.
        if sealed_chain is not None:
            from . import seal
            seal.write(res_dir, sealed_chain)
            print("results sealed: %s" % (res_dir / seal.SEAL_FILE))


def _install_resource_gate(ctr):
    assets = Path(__file__).parent / "assets"
    ctr.put("/usr/local/lib/sciexam/local_reader_gate.py",
            (assets / "local_reader_gate.py").read_text(), mode="755", owner="root:root")
    ctr.put("/etc/claude-code/managed-settings.json",
            (assets / "claude-managed-settings.json").read_text(), mode="644", owner="root:root")
    probe = '{"tool_name":"Read","tool_input":{"file_path":"/x/paper.pdf"}}'
    r = subprocess.run(ctr.exec_argv(["/usr/local/lib/sciexam/local_reader_gate.py", "--schema",
                                      "claude", "--tools", "Read"], interactive=True),
                       input=probe.encode(), capture_output=True, timeout=60)
    if b'"permissionDecision": "deny"' not in (r.stdout or b""):
        raise RuntimeError("the resource gate did not deny a PDF read")


def _wait_gateway(ctr, run):
    from .docker_env import GATEWAY_ALIAS, GATEWAY_PORT
    url = "http://%s:%d/health/liveliness" % (GATEWAY_ALIAS, GATEWAY_PORT)
    code = ("import urllib.request,sys\n"
            "try:\n urllib.request.urlopen(%r,timeout=3)\nexcept Exception:\n sys.exit(1)\n" % url)
    for _ in range(90):
        r = subprocess.run(ctr.exec_argv(["python3", "-c", code], env={"NO_PROXY": GATEWAY_ALIAS}),
                           capture_output=True)
        if r.returncode == 0:
            run.log({"event": "gateway_ready", "url": url})
            return
        time.sleep(2)
    raise RuntimeError("the gateway did not come up at %s" % url)


# One request in the shape Claude Code sends, through the gateway, that a model can only answer
# well with a tool call. Run inside the agent container, before the budget starts.
PREFLIGHT_CODE = r'''
import json, os, sys, urllib.request
req = {"model": os.environ["SCIEXAM_ALIAS"], "max_tokens": 512,
       "tools": [{"name": "write_file", "description": "Write text to a file in the workspace.",
                  "input_schema": {"type": "object", "properties": {
                      "path": {"type": "string"}, "text": {"type": "string"}},
                      "required": ["path", "text"]}}],
       "tool_choice": {"type": "any"},
       "messages": [{"role": "user", "content":
                     "Use the write_file tool to write the text ok to the file check.txt."}]}
r = urllib.request.Request(os.environ["SCIEXAM_GW"] + "/v1/messages", data=json.dumps(req).encode(),
                           headers={"content-type": "application/json", "anthropic-version": "2023-06-01",
                                    "x-api-key": os.environ["SCIEXAM_KEY"]})
try:
    print(urllib.request.urlopen(r, timeout=300).read().decode()[:20000])
except Exception as e:
    body = getattr(e, "read", lambda: b"")().decode(errors="ignore")[:2000]
    print(json.dumps({"error": "%s: %s" % (type(e).__name__, e), "body": body}))
'''


def tool_call_ok(text):
    """(ok, detail) from the gateway's reply to the preflight request."""
    try:
        resp = json.loads(text)
    except ValueError:
        return False, "the gateway returned no JSON: %s" % text[:200]
    if resp.get("error"):
        return False, "%s %s" % (resp["error"], resp.get("body", ""))[:400]
    calls = [b for b in resp.get("content") or [] if b.get("type") == "tool_use"]
    if not calls:
        said = " ".join(b.get("text", "") for b in resp.get("content") or [] if b.get("type") == "text")
        return False, "the model answered without a tool call: %r" % said[:200]
    return True, "tool call %s(%s)" % (calls[0].get("name"), json.dumps(calls[0].get("input"))[:120])


def _preflight_tool_call(ctr, run, arm, creds):
    from .docker_env import GATEWAY_ALIAS, GATEWAY_PORT
    env = {"NO_PROXY": GATEWAY_ALIAS, "SCIEXAM_ALIAS": arm["route"]["model_alias"],
           "SCIEXAM_GW": "http://%s:%d" % (GATEWAY_ALIAS, GATEWAY_PORT)}
    # the key passes as -e NAME from this process's environment, never on the command line
    r = subprocess.run(ctr.exec_argv(["python3", "-c", PREFLIGHT_CODE], env=env, secrets=("SCIEXAM_KEY",)),
                       capture_output=True, text=True, timeout=360,
                       env=dict(os.environ, SCIEXAM_KEY=creds["LITELLM_MASTER_KEY"]))
    ok, detail = tool_call_ok((r.stdout or "").strip())
    run.log({"event": "preflight_tool_call", "ok": ok, "detail": detail})
    if not ok:
        raise RuntimeError(
            "preflight: %s.\nThe agent acts only through tool calls, so the run was not started. "
            "Serve the model with tool calling on (for vLLM: --enable-auto-tool-choice and the "
            "--tool-call-parser of the model; for Ollama: a model with the tools capability), "
            "or choose another model." % detail)
    print("preflight: %s" % detail)


AGENTS_DIR = Path(__file__).resolve().parents[2] / "agents"


def resolve_agents(values):
    """--agent values to config paths: paths, arm keys (released or added with add-model), or
    route:model (openrouter:qwen/qwen3-coder, claude:..., codex:..., antigravity:...), which adds
    the model on first use. Comma separated or repeated."""
    out = []
    for v in values or []:
        for item in [x.strip() for x in v.split(",") if x.strip()]:
            p = Path(item)
            spec = NM.parse_spec(item)
            if spec and not p.exists():
                key = NM.slug("%s-%s" % spec)
                p = NM.user_dir() / ("%s.yaml" % key)
                if not p.exists():
                    info = NM.openrouter_info(spec[1]) if spec[0] == "openrouter" else None
                    try:
                        p = NM.make(spec[0], spec[1],
                                    context_tokens=(info or {}).get("context_length"))
                    except NM.ModelError as e:
                        raise RuntimeError(str(e))
                    print("added %s as arm %s (%s)" % (spec[1], key, p))
            elif not p.exists() and not item.endswith(".yaml"):
                p = next((d / ("%s.yaml" % item) for d in NM.agent_dirs()
                          if (d / ("%s.yaml" % item)).exists()), p)
            if not p.exists():
                raise RuntimeError("no arm config %s (see sciexam list-agents, or sciexam add-model)"
                                   % item)
            out.append(p)
    if not out:
        raise RuntimeError("no agent given")
    return out


def load_with_effort(path, levels, a=None):
    arm = C.load_arm(path)
    level = levels.get(arm["arm"])
    try:
        if level:
            arm = E.apply(arm, level)
        if a is not None:
            arm = X.apply(arm, getattr(a, "network", None), getattr(a, "allow_host", None))
    except (E.EffortError, X.CustomError) as e:
        raise RuntimeError(str(e))
    return arm


def cmd_run_agent(a):
    from .. import dataset as DS
    if not a.agent:
        if not (a.interactive or sys.stdin.isatty()):
            raise RuntimeError("--agent is required (run it on a terminal for the interactive setup)")
        from .wizard import interactive_argv
        argv = interactive_argv(env_file=a.env_file)
        if argv is None:
            return 1
        from ..cli import main
        return main((["--data-dir", a.data_dir] if a.data_dir else []) + ["run-agent"] + argv)
    paths = resolve_agents(a.agent)
    keys = [C.load_arm(p)["arm"] for p in paths]
    try:
        levels = E.parse(a.effort, keys)
    except E.EffortError as e:
        raise RuntimeError(str(e))
    if len(paths) > 1 or a.parallel > 1:
        return run_batch(a, paths, keys, levels)
    arm = load_with_effort(paths[0], levels, a)
    if a.dry_run:
        root = Path(a.data_dir or DS.default_root())
        if not (root / "task").exists():
            raise RuntimeError("no dataset at %s (sciexam download, or --data-dir)" % root)
        return dry_run(arm, a, root)
    if a.net_check:
        if D.is_research(arm):
            root = Path(a.data_dir or DS.default_root())
            if not (root / "task").exists():
                raise RuntimeError("no dataset at %s (sciexam download, or --data-dir)" % root)
            return research_net_check(arm, a, root)
        return net_check(arm, a)
    root = DS.open_verified(a.data_dir)
    return live_run(arm, a, root)


def run_batch(a, paths, keys, levels):
    """Run several arms, at most ``a.parallel`` at a time. Each arm runs as its own
    `sciexam run-agent` process with its own run folder, containers and networks, and writes
    its output to <batch folder>/<arm>[-<effort>].log."""
    import threading
    if a.run_name or a.workdir:
        raise RuntimeError("--run-name and --workdir name one run, use --batch-dir for several arms")
    batch = Path(a.batch_dir or (H.runs() / ("batch-%s" % time.strftime("%m%d-%H%M%S")))).resolve()
    if not (a.dry_run or a.net_check):
        short = R.problems(R.host(), min(max(1, a.parallel), len(paths)), batch)
        if short:
            raise RuntimeError("this machine does not meet the runs' spec:\n  " + "\n  ".join(short))
    batch.mkdir(parents=True, exist_ok=True)
    jobs, seen = [], {}
    for p, k in zip(paths, keys):
        level = levels.get(k)
        name = "%s-%s" % (k, level) if level else k
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            name = "%s-%d" % (name, seen[name])
        argv = [sys.executable, "-m", "sciexam"]
        if a.data_dir:
            argv += ["--data-dir", a.data_dir]
        argv += ["run-agent", "--agent", str(p), "--env-file", a.env_file,
                 "--name-prefix", a.name_prefix]
        if not (a.dry_run or a.net_check):
            argv += ["--workdir", str(batch / name)]
        if level:
            argv += ["--effort", level]
        argv += ["--agents-at-once", str(min(max(1, a.parallel), len(paths)))]
        for flag in ("smoke", "dry_run", "net_check", "no_build", "keep"):
            if getattr(a, flag):
                argv.append("--" + flag.replace("_", "-"))
        if a.network and a.network != "paper":
            argv += ["--network", a.network]
        for h in a.allow_host or []:
            argv += ["--allow-host", h]
        if a.contact:
            argv += ["--contact", a.contact]
        for opt in ("hours", "task_data", "paper", "benchmark_self"):
            v = getattr(a, opt)
            if v is not None:
                argv += ["--" + opt.replace("_", "-"), str(v)]
        jobs.append({"name": name, "arm": k, "effort": level, "argv": argv,
                     "log": batch / ("%s.log" % name), "rc": None})
    _hr("batch of %d arm(s), %d at a time, folder %s" % (len(jobs), a.parallel, batch))
    for j in jobs:
        print("  %-28s effort %-7s log %s" % (j["name"], j["effort"] or "leaderboard", j["log"].name))
    gate = threading.Semaphore(max(1, a.parallel))
    start_lock = threading.Lock()

    def work(j):
        with gate:
            with start_lock:
                time.sleep(1.1)   # run keys carry the start second, so no two runs share one
            print("start  %s" % j["name"], flush=True)
            with open(j["log"], "w") as f:
                j["rc"] = subprocess.run(j["argv"], stdout=f, stderr=subprocess.STDOUT).returncode
            print("done   %s  exit %d" % (j["name"], j["rc"]), flush=True)

    threads = [threading.Thread(target=work, args=(j,)) for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    summary = [{k: (str(v) if isinstance(v, Path) else v) for k, v in j.items() if k != "argv"}
               for j in jobs]
    (batch / "batch.json").write_text(json.dumps(summary, indent=1) + "\n")
    _hr("batch finished")
    for j in jobs:
        print("  %-28s exit %-3s %s" % (j["name"], j["rc"], j["log"]))
    return 0 if all(j["rc"] == 0 for j in jobs) else 1


def cmd_list_agents(a):
    """The arms in agents/, their route, the credential each needs and the effort levels."""
    rows = []
    for p in NM.all_configs():
        arm = C.load_arm(p)
        cond = (arm.get("condition") or {}).get("name") or ("added" if p.parent != NM.RELEASED_DIR else "")
        cred = C.required_credentials(arm)
        rows.append((arm["arm"], arm.get("display_name") or "", arm["scaffold"]["name"],
                     arm["route"]["kind"], cred[0][0] if cred else "(none)",
                     arm["reasoning"]["effort"], "/".join(E.options(arm)), E.mechanism(arm),
                     cond or ""))
    head = ("arm", "system", "scaffold", "route", "credential", "paper", "effort options",
            "how the level is set", "note")
    w = [max(len(str(r[i])) for r in rows + [head]) for i in range(len(head))]
    for r in [head] + rows:
        print("  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)).rstrip())
    print("\nRun several arms with --agent kimi,gpt56 --parallel 2, and choose a level with "
          "--effort high or --effort kimi=high,gpt56=low. A level other than the leaderboard's is "
          "recorded as not comparable with the official leaderboard.\nAdd a model with sciexam add-model, or "
          "--agent openrouter:<model id> (also claude:, codex:, antigravity:).")
    return 0


def cmd_add_model(a):
    context = a.context_tokens
    if a.route == "openrouter" and not a.no_check:
        info = NM.openrouter_info(a.model)
        if info is None:
            print("note: could not read OpenRouter's model list, the id is not checked")
        elif not info["exists"]:
            raise RuntimeError("OpenRouter lists no model %r (see https://openrouter.ai/models), "
                               "or pass --no-check" % a.model)
        elif context is None:
            context = info["context_length"]
    if a.route == "local" and not context:
        raise RuntimeError("a local model needs --context-tokens: the context window it is served with")
    try:
        p = NM.make(a.route, a.model, name=a.name, api_base=a.api_base, key=a.key,
                    context_tokens=context)
    except NM.ModelError as e:
        raise RuntimeError(str(e))
    arm = C.load_arm(p)
    print("added arm %s: %s on the protocol of %s" % (arm["arm"], arm["route"]["model_id"],
                                                     NM.TEMPLATES[a.route]))
    print("configuration: %s" % p)
    if arm.get("declared"):
        print("context window %d tokens, smaller than the leaderboard's 200,000: the agent compacts at "
              "%s tokens, and the run is ranked apart from the official leaderboard" % (
                  arm["declared"]["context_tokens"], arm["context"]["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"]))
    print("check it:  sciexam run-agent --agent %s --dry-run" % arm["arm"])
    return 0


def register(sub):
    from .start import cmd_start
    p = sub.add_parser("start", help="new here? checks what a run needs, helps with what is missing, "
                                     "then sets up a run")
    p.add_argument("--env-file", default=H.env_file(),
                   help="credential file (default %s)" % H.env_file())
    p.set_defaults(fn=cmd_start)

    p = sub.add_parser("run-agent", help="rerun one ranked arm or condition run with the released "
                                         "harness (Docker, the user's own credentials)")
    p.add_argument("--agent", action="append",
                   help="arm config or arm key, e.g. agents/kimi.yaml or kimi. Several arms: "
                        "kimi,gpt56 or repeat --agent. Without --agent, on a terminal, an "
                        "interactive setup asks for every setting")
    p.add_argument("--interactive", action="store_true",
                   help="ask for the settings interactively (the default without --agent)")
    p.add_argument("--effort", help="reasoning effort, low, medium or high: one level for every "
                                    "arm, or per arm as kimi=high,gpt56=low (default: the official "
                                    "leaderboard's level of each arm, see sciexam list-agents)")
    p.add_argument("--network", choices=X.NETWORKS,
                   help="paper (default): the model endpoint and PyPI, as on the official leaderboard. "
                        "no-pypi: the model endpoint only. Not comparable with the official "
                        "leaderboard when changed")
    p.add_argument("--allow-host", action="append",
                   help="add a host to the agent's allowlist (repeat or comma separate). Not "
                        "comparable with the official leaderboard")
    p.add_argument("--contact", help="email or GitHub handle written into the run for its "
                                     "leaderboard submission (remembered after the first use)")
    p.add_argument("--agents-at-once", type=int, help=argparse.SUPPRESS)   # set by a batch
    p.add_argument("--parallel", type=int, default=1,
                   help="with several arms, how many run at the same time (default 1)")
    p.add_argument("--batch-dir", help="with several arms, the folder of their runs and logs "
                                       "(default %s/batch-<time>)" % H.runs())
    g = p.add_mutually_exclusive_group()
    g.add_argument("--smoke", action="store_true",
                   help="15-minute plumbing check: short caps, Phase 1 not required, not comparable")
    g.add_argument("--hours", type=float, help="eligible budget in hours (default: the arm's, 6)")
    p.add_argument("--dry-run", action="store_true",
                   help="print the container spec, task tree, network policy and prompts, start nothing")
    p.add_argument("--net-check", action="store_true",
                   help="start the arm's networks and proxy, probe them from a throwaway container, "
                        "remove everything")
    p.add_argument("--workdir", help="run folder (default %s/<arm>-<time>)" % H.runs())
    p.add_argument("--run-name", help="name of the run, also the workspace path /work/<name> "
                                      "inside the container (default: the arm key)")
    p.add_argument("--env-file", default=H.env_file(),
                   help="credential file (default %s, see .env.example)" % H.env_file())
    p.add_argument("--task-data", help="folder with the four raw data files "
                                       "(sciexam prepare-data --keep-raw writes them to OUT/raw)")
    p.add_argument("--paper", help="path to the Jin (1997) PDF")
    p.add_argument("--benchmark-self", help="JSON with the benchmark's own public pages for the "
                                            "research proxy of the web conditions (default: "
                                            "sciexam/agent/research/benchmark_self.json)")
    p.add_argument("--name-prefix", default="sciexam", help="prefix of container, network and image names")
    p.add_argument("--no-build", action="store_true", help="use images already built")
    p.add_argument("--keep", action="store_true", help="leave the containers and networks up")
    p.add_argument("--probe-image", help=argparse_suppress())
    p.add_argument("--probe-package", default="six==1.17.0", help=argparse_suppress())
    p.set_defaults(fn=cmd_run_agent)

    p = sub.add_parser("list-agents", help="list the released arms, the credential each needs and "
                                           "the reasoning effort levels each accepts")
    p.set_defaults(fn=cmd_list_agents)

    p = sub.add_parser("add-model", help="add a model that is not on the official leaderboard, on the protocol "
                                         "of the released arm of its route")
    p.add_argument("--route", required=True, choices=sorted(NM.TEMPLATES),
                   help="; ".join("%s: %s" % kv for kv in NM.ROUTE_LABELS.items()))
    p.add_argument("--model", required=True, help="the model id, e.g. qwen/qwen3-coder")
    p.add_argument("--name", help="the display name (default: the model id)")
    p.add_argument("--api-base", help="local route: the OpenAI-compatible endpoint, e.g. "
                                      "http://localhost:8000/v1")
    p.add_argument("--key", help="the arm key (default: route-model)")
    p.add_argument("--context-tokens", type=int,
                   help="the model's context window (read from OpenRouter on that route, required on "
                        "the local route)")
    p.add_argument("--no-check", action="store_true", help="do not check the id against OpenRouter")
    p.set_defaults(fn=cmd_add_model)


def argparse_suppress():
    import argparse
    return argparse.SUPPRESS
