"""The three agent scaffolds, driven inside the agent container with `docker exec`.

Each adapter runs one agent turn and returns a TurnResult. The command lines, environment
variables and turn semantics follow the formal harness adapters for Claude Code (gateway and
subscription routes), the Codex CLI and the Antigravity CLI.

Credentials never appear on a command line: they are passed as `-e NAME` and the value is
set in the docker client's own environment.
"""
import hashlib
import json
import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path

from . import prompts as P
from . import signals as S


class TurnResult:
    def __init__(self, elapsed_s=0.0, timed_out=False, exit_code=None, log_bytes=0,
                 quota_wait=None, productive=0, transient=None):
        self.elapsed_s = elapsed_s
        self.timed_out = timed_out
        self.exit_code = exit_code
        self.log_bytes = log_bytes
        self.quota_wait = quota_wait
        self.productive = productive
        self.transient = transient

    def to_dict(self):
        d = dict(elapsed_s=round(self.elapsed_s, 1), timed_out=self.timed_out,
                 exit_code=self.exit_code, log_bytes=self.log_bytes)
        if self.quota_wait:
            d["quota_wait"] = self.quota_wait
        if self.productive:
            d["productive_calls"] = self.productive
        if self.transient:
            d["transient"] = self.transient
        return d


class Container:
    """docker exec into the run's agent container."""

    def __init__(self, name, uid):
        self.name = name
        self.uid = uid

    def exec_argv(self, cmd, env=None, secrets=(), workdir=None, user=None, interactive=False):
        a = ["docker", "exec"]
        if interactive:
            a.append("-i")
        if workdir:
            a += ["-w", workdir]
        a += ["--user", user or self.uid]
        for k, v in (env or {}).items():
            a += ["-e", "%s=%s" % (k, v)]
        for k in secrets:
            a += ["-e", k]
        return a + [self.name] + list(cmd)

    def root(self, cmd, timeout=60, input_bytes=None):
        return subprocess.run(self.exec_argv(cmd, user="root", interactive=input_bytes is not None),
                              capture_output=True, timeout=timeout, input=input_bytes)

    def put(self, path, content, mode="644", owner=None):
        """Write a file inside the container as root, then set its mode and owner."""
        data = content.encode() if isinstance(content, str) else content
        d = os.path.dirname(path)
        r = self.root(["sh", "-c", 'mkdir -p "$1" && cat > "$2" && chmod %s "$2"%s'
                       % (mode, ' && chown %s "$2"' % owner if owner else ""),
                       "put", d, path], input_bytes=data)
        if r.returncode != 0:
            raise RuntimeError("could not write %s in %s: %s"
                               % (path, self.name, r.stderr.decode(errors="replace")[-300:]))

    def kill_agent_processes(self, pattern):
        try:
            subprocess.run(["docker", "exec", self.name, "pkill", "-9", "-f", pattern],
                           timeout=20, capture_output=True)
        except Exception:
            pass


def sha256_in_container(ctr, binary):
    probe = ('p=$(command -v %s) || exit 3; echo "PATH=$p"; '
             'echo "VER=$(%s --version 2>&1 | head -1)"; '
             'echo "SHA=$(sha256sum "$p" | cut -d" " -f1)"' % (binary, binary))
    r = subprocess.run(ctr.exec_argv(["sh", "-lc", probe]), capture_output=True, text=True,
                       timeout=120)
    out = {}
    for line in (r.stdout or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v.strip()
    return out


def run_capture(argv, secret_env, timeout, log_path, tag, append, ctr, kill_pattern):
    """One agent turn: stdout and stderr stream to agent_output.txt, a hard timeout kills
    the process group and the processes left inside the container."""
    t0 = time.time()
    try:
        fh = open(log_path, "a" if append else "w", buffering=1)
    except OSError:
        fh = subprocess.DEVNULL
    try:
        fh.write("\n===== %s turn @ %s =====\n" % (tag, time.strftime("%H:%M:%S")))
    except Exception:
        pass
    env = dict(os.environ)
    env.update(secret_env or {})
    try:
        proc = subprocess.Popen(argv, env=env, text=True, stdin=subprocess.DEVNULL,
                                stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
    except Exception as e:
        try:
            fh.write("spawn failed: %r\n" % (e,))
        except Exception:
            pass
        return TurnResult(elapsed_s=0.0, exit_code=-1)
    timed_out = False
    try:
        proc.wait(timeout=max(1, timeout))
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        ctr.kill_agent_processes(kill_pattern)
        try:
            proc.wait(timeout=20)
        except Exception:
            pass
    finally:
        try:
            if fh is not subprocess.DEVNULL:
                fh.close()
        except Exception:
            pass
    try:
        size = Path(log_path).stat().st_size
    except OSError:
        size = 0
    return TurnResult(elapsed_s=time.time() - t0, timed_out=timed_out,
                      exit_code=proc.returncode, log_bytes=size)


# ---- Claude Code ------------------------------------------------------------------------

CLAUDE_BASE_FLAGS = ["--dangerously-skip-permissions", "--strict-mcp-config"]
CLAUDE_CACHE_FLAGS = ["--exclude-dynamic-system-prompt-sections",
                      "--settings", '{"includeGitInstructions":false}']
KILL_PATTERN = "claude|codex|node|python3"


class ClaudeCode:
    """Claude Code headless. Gateway arms reach LiteLLM on the internal network, subscription
    arms sign in with the user's subscription token."""

    def __init__(self, run):
        self.run = run
        self.arm = run.arm

    def command(self, prompt, resume):
        a = self.arm
        cmd = ["claude", "--continue", "-p", prompt] if resume else ["claude", "-p", prompt]
        cmd += list(CLAUDE_BASE_FLAGS)
        for t in a["tools"]["disallowed"] or []:
            cmd += ["--disallowedTools", t]
        cmd += list(CLAUDE_CACHE_FLAGS)
        if a["route"]["kind"] == "gateway":
            cmd += ["--model", a["route"]["model_alias"]]
        else:
            cmd += ["--model", a["route"]["model_id"]]
        if a["reasoning"]["pass_effort_flag"]:
            cmd += ["--effort", a["reasoning"]["effort"]]
        return cmd

    def environment(self):
        r = self.run
        ws = r.ctr_ws
        env = {}
        secrets = []
        if self.arm["route"]["kind"] == "gateway":
            from .docker_env import GATEWAY_ALIAS, GATEWAY_PORT
            env["ANTHROPIC_BASE_URL"] = "http://%s:%d" % (GATEWAY_ALIAS, GATEWAY_PORT)
            secrets.append("ANTHROPIC_API_KEY")
            env["HOME"] = ws + "/.home"
            env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
            for k, v in (self.arm["context"].get("env") or {}).items():
                env[k] = str(v)
            env["CLAUDE_CODE_ATTRIBUTION_HEADER"] = "0"
        else:
            secrets.append("CLAUDE_CODE_OAUTH_TOKEN")
            for k, v in (self.arm["context"].get("env") or {}).items():
                env[k] = str(v)
            env["CLAUDE_CONFIG_DIR"] = ws + "/.claudecfg"
            env["HOME"] = ws + "/.home"
            env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        env.update(r.proxy_env)
        return env, secrets

    def prepare(self):
        r = self.run
        r.ctr.root(["mkdir", "-p", r.ctr_ws + "/.home", r.ctr_ws + "/.claudecfg"])
        r.ctr.root(["chown", r.uid, r.ctr_ws + "/.home", r.ctr_ws + "/.claudecfg"])

    def turn(self, prompt, timeout, resume=False, append=False):
        r = self.run
        env, secrets = self.environment()
        argv = r.ctr.exec_argv(self.command(prompt or P.RESUME_PROMPT, resume), env=env,
                               secrets=secrets, workdir=r.ctr_ws)
        tag = ("gateway:" if self.arm["route"]["kind"] == "gateway" else "claudesub:") + (
            self.arm["route"].get("model_alias") or self.arm["route"]["model_id"])
        res = run_capture(argv, r.secret_values(secrets), timeout, r.ws / "agent_output.txt",
                          tag, append, r.ctr, KILL_PATTERN)
        if (self.arm["provider_signals"].get("classify_failed_turns")
                and res.exit_code not in (0,)):
            text = S.tail_text(r.ws / "agent_output.txt", 4096, marker="===== claudesub:")
            q = S.parse_quota_exhaustion("ERROR", text)
            t = None if q is not None else S.parse_transient_service("ERROR", text)
            if q is not None:
                res.quota_wait = q
            elif t is not None:
                res.transient = t
            if q is not None or t is not None:
                r.log({"event": "claudesub_provider_signal",
                       "classified": "allocation_exhausted" if q else "provider_service",
                       "bounded": (q or {}).get("bounded"),
                       "reset_delay_s": (q or {}).get("reset_delay_s"),
                       "message": text.strip()[-200:]})
        return res


# ---- Codex --------------------------------------------------------------------------------

CODEX_CONFIG_TEMPLATE = "codex-config.toml"


class Codex:
    """Codex CLI on the ChatGPT subscription. CODEX_HOME is <workspace>/.codex, holding the
    user's auth.json and the arm's config.toml, as in the formal runs."""

    def __init__(self, run):
        self.run = run
        self.arm = run.arm

    def config_text(self):
        tpl = (Path(__file__).parent / "assets" / CODEX_CONFIG_TEMPLATE).read_text()
        c = self.arm["context"]
        return (tpl.replace("{MODEL}", self.arm["route"]["model_id"])
                .replace("{EFFORT}", self.arm["reasoning"]["effort"])
                .replace("{AUTO_COMPACT}", str(int(c["codex_auto_compact_token_limit"])))
                .replace("{WEB_SEARCH}", self.arm["codex"].get("web_search", "disabled")))

    def prepare(self):
        r = self.run
        cdx = r.ctr_ws + "/.codex"
        r.ctr.root(["mkdir", "-p", cdx, r.ctr_ws + "/.home"])
        r.ctr.root(["chown", r.uid, r.ctr_ws + "/.home"])
        auth = r.credential("CODEX_AUTH_JSON")
        if auth and Path(auth).is_file():
            r.ctr.put(cdx + "/auth.json", Path(auth).read_bytes(), mode="600", owner=r.uid)

    def turn(self, prompt, timeout, resume=False, append=False):
        r = self.run
        cdx = r.ctr_ws + "/.codex"
        # The config is rewritten on every turn, as the formal harness did. auth.json is
        # written once at setup and then left to the CLI, so a refreshed token is kept.
        r.ctr.put(cdx + "/config.toml", self.config_text(), mode="644", owner=r.uid)
        r.ctr.root(["sh", "-c", 'chown %s "$1" && chmod 700 "$1"' % r.uid, "x", cdx])
        model = self.arm["route"]["model_id"]
        cmd = ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "-m", model]
        cmd += (["resume", "--last", prompt or P.RESUME_PROMPT] if resume else [prompt])
        env = {"CODEX_HOME": cdx, "HOME": r.ctr_ws + "/.home",
               "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
        env.update(r.proxy_env)
        argv = r.ctr.exec_argv(cmd, env=env, workdir=r.ctr_ws)
        res = run_capture(argv, {}, timeout, r.ws / "agent_output.txt", "codexsub:" + model,
                          append, r.ctr, KILL_PATTERN)
        if res.exit_code not in (0,):
            q, t, ev = S.classify_codex_log(r.ws / "agent_output.txt")
            if q is not None:
                res.quota_wait = q
            elif t is not None:
                res.transient = t
            if q is not None or t is not None:
                r.log({"event": "codex_provider_signal",
                       "classified": "allocation_exhausted" if q else "provider_service",
                       "bounded": (q or {}).get("bounded"),
                       "structured": ev["structured"], "message": ev["message"][:200]})
        return res


# ---- Antigravity --------------------------------------------------------------------------

AGY_BIN = "/usr/local/bin/agy"
AGY_HOME = "/home/ubuntu"

_AGY_CLASSES = (
    ("cli_timeout", ("timeout waiting for response", "print timeout", "print-timeout",
                     "deadline exceeded waiting", "context deadline exceeded")),
    ("quota_or_rate_limit", ("429", "rate limit", "rate-limit", "ratelimit", "too many requests",
                             "quota", "resource_exhausted", "resource exhausted", "exhausted",
                             "compute effort", "usage limit", "capacity", "overloaded",
                             "try again later", "throttl", "limit reached", "out of credits",
                             "insufficient")),
    ("authentication", ("unauthenticated", "unauthorized", "401", "403", "permission denied",
                        "invalid_grant", "invalid grant", "oauth", "token expired",
                        "expired token", "credential", "login", "sign in", "sign-in", "reauth",
                        "re-auth", "not authenticated", "forbidden")),
)


def agy_classify(status="", err="", process_exited=False):
    low = ("%s %s" % (status, err)).lower()
    for label, pats in _AGY_CLASSES:
        if any(p in low for p in pats):
            return label
    if process_exited or (status and status.upper() != "SUCCESS"):
        return "fatal_process"
    return "normal_completion"


class Antigravity:
    """One persistent `agy --input-format stream-json` process per harness turn.

    Antigravity has no Stop hook, so during Phase 2B a normal result is answered with
    ANTIGRAVITY_CONTINUE while the submission keeps changing, and the turn yields after
    `block_limit` results with no change (the same rule as the Claude Code Stop hook).
    A fatal result makes the next turn start a fresh conversation. The largest context of
    any call is watched against the runaway cap.
    """

    def __init__(self, run):
        self.run = run
        self.arm = run.arm
        g = self.arm["antigravity"]
        self.block_limit = int(g.get("block_limit", 3))
        self.margin = int(g.get("print_timeout_margin_s", 300))
        self.result_wait = int(g.get("result_wait_s", 900))
        self.cap = int(self.arm["context"].get("runaway_cap_tokens") or 0)
        self.fatal_last = {"fatal": False, "class": None}
        self.tripped = None
        self.tel = {"harness_agent_invocations": 0, "antigravity_conversations": 0,
                    "antigravity_user_turns": 0, "underlying_model_calls": 0,
                    "internal_continuations": 0, "normal_results": 0, "fatal_exits": 0,
                    "yielded_no_change": 0, "input_tokens": 0, "output_tokens": 0,
                    "cache_read_tokens": 0, "thinking_tokens": 0, "max_context_carried": 0,
                    "fresh_conversation_after_fatal": 0, "conversation_ids": []}

    def prepare(self):
        """Install the user's Antigravity sign-in and the root-owned PreToolUse guards."""
        r = self.run
        src = r.credential("ANTIGRAVITY_HOME")
        if src and Path(src).is_dir():
            subprocess.run(["docker", "cp", str(Path(src)) + "/.", "%s:%s/.gemini" % (
                r.ctr.name, AGY_HOME)], check=True, capture_output=True, timeout=300)
        r.ctr.root(["sh", "-c", "mkdir -p %s/.gemini/config && chown -R 1000:1000 %s/.gemini "
                    "&& chown root:root %s/.gemini/config && chmod 755 %s/.gemini/config"
                    % ((AGY_HOME,) * 4)])
        assets = Path(__file__).parent / "assets"
        hooks = json.loads((assets / "antigravity-hooks.json").read_text())
        if not self.arm["resource_gate"]:
            hooks.pop("benchmark-resource-gate", None)
        r.ctr.put(AGY_HOME + "/.gemini/config/hooks.json", json.dumps(hooks, indent=2) + "\n",
                  mode="644", owner="root:root")
        r.ctr.put(AGY_HOME + "/.gemini/config/deny_retrieval.sh",
                  (assets / "deny_retrieval.sh").read_text(), mode="755", owner="root:root")
        w = subprocess.run(r.ctr.exec_argv(["test", "-w", AGY_HOME + "/.gemini/config/hooks.json"]),
                           capture_output=True)
        if w.returncode == 0:
            raise RuntimeError("the agent user can write the retrieval guard")

    def _hook_armed(self):
        p = self.run.ws / ".home" / ".claude" / "settings.json"
        try:
            return bool((json.loads(p.read_text()).get("hooks") or {}).get("Stop"))
        except Exception:
            return False

    def _fp(self):
        h = hashlib.sha256()
        for name in ("model.py", "params.json"):
            try:
                h.update((self.run.ws / "submission" / name).read_bytes())
            except OSError:
                h.update(b"\0")
        return h.hexdigest()[:16]

    def _usage(self, rec):
        try:
            with open(self.run.ws / "agy_usage.jsonl", "a") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            pass

    def turn(self, prompt, timeout, resume=False, append=False):
        r = self.run
        tel = self.tel
        if self.tripped:
            r.log({"event": "agy_safety_stop_replay", "reason": self.tripped})
            return TurnResult(elapsed_s=0.0, exit_code=-2)
        if tel["harness_agent_invocations"] == 0:
            r.log(dict(event="model_identity", model_variant=self.arm["route"]["model_id"],
                       reasoning_level=self.arm["reasoning"]["effort"], scaffold="antigravity"))
        tel["harness_agent_invocations"] += 1
        cmd = [AGY_BIN]
        use_resume = resume
        if resume and self.fatal_last["fatal"] and self.fatal_last["class"] not in (
                "quota_or_rate_limit", "authentication"):
            use_resume = False
            r.log({"event": "agy_fresh_conversation_after_fatal",
                   "previous_class": self.fatal_last["class"]})
            tel["fresh_conversation_after_fatal"] += 1
        self.fatal_last = {"fatal": False, "class": None}
        if use_resume:
            cmd.append("--continue")
        print_timeout = int(timeout) + self.margin
        cmd += ["--model", self.arm["route"]["model_id"], "--dangerously-skip-permissions",
                "--input-format", "stream-json", "--output-format", "stream-json",
                "--print-timeout", "%ds" % print_timeout]
        env = {"HOME": AGY_HOME, "GEMINI_CLI_TRUST_WORKSPACE": "true",
               "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
        env.update(r.proxy_env)
        argv = r.ctr.exec_argv(cmd, env=env, workdir=r.ctr_ws, interactive=True)
        t0 = time.time()
        deadline = t0 + max(1, timeout)
        log_path = r.ws / "agent_output.txt"
        fh = open(log_path, "a" if append else "w", buffering=1)
        fh.write("\n===== agy:%s %s turn @ %s  (harness budget %ds, agy print-timeout %ds) =====\n"
                 % (self.arm["route"]["model_id"], "resume" if resume else "start",
                    time.strftime("%H:%M:%S"), int(timeout), print_timeout))
        try:
            proc = subprocess.Popen(argv, text=True, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1,
                                    start_new_session=True)
        except Exception as e:
            fh.write("spawn failed: %r\n" % (e,))
            fh.close()
            tel["fatal_exits"] += 1
            return TurnResult(elapsed_s=0.0, exit_code=-1)
        q = queue.Queue()

        def reader():
            for line in iter(proc.stdout.readline, ""):
                q.put(line)
            q.put(None)
        threading.Thread(target=reader, daemon=True).start()
        user_turn = [0]

        def send(text):
            msg = json.dumps({"event": "user",
                              "message": {"content": P.ANTIGRAVITY_PREAMBLE.format(wd=r.ctr_ws)
                                          + text}})
            try:
                proc.stdin.write(msg + "\n")
                proc.stdin.flush()
                tel["antigravity_user_turns"] += 1
                user_turn[0] += 1
                return True
            except Exception as e:
                fh.write("stdin write failed: %r\n" % (e,))
                return False

        timed_out = fatal = dead = capped = False
        stop_reason = stop_detail = None
        quota_signal = transient_signal = None
        productive = 0
        conv_id = None
        hook_armed = self._hook_armed()
        fp = self._fp()
        no_change = 0
        if not send(prompt or P.RESUME_PROMPT):
            fatal = True
        last_event = time.time()
        while not (fatal or dead or capped):
            if time.time() >= deadline:
                timed_out = True
                break
            try:
                line = q.get(timeout=1.0)
            except queue.Empty:
                if time.time() - last_event > self.result_wait:
                    fh.write("no event for %ds, treating the process as dead\n" % self.result_wait)
                    dead = True
                continue
            if line is None:
                dead = True
                break
            last_event = time.time()
            fh.write(line if line.endswith("\n") else line + "\n")
            try:
                ev = json.loads(line)
            except Exception:
                continue
            kind = ev.get("event")
            if kind == "init":
                conv_id = (ev.get("init") or {}).get("conversation_id") or ev.get("conversation_id")
                if conv_id and conv_id not in tel["conversation_ids"]:
                    tel["conversation_ids"].append(conv_id)
                    tel["antigravity_conversations"] += 1
            elif kind == "step_update":
                su = ev.get("step_update") or {}
                if su.get("step_type") == "agent_response" and su.get("state") == "DONE":
                    u = su.get("usage") or {}
                    inp = int(u.get("input_tokens") or 0)
                    cac = int(u.get("cache_read_tokens") or 0)
                    out = int(u.get("output_tokens") or 0)
                    ctx = inp + cac
                    tel["underlying_model_calls"] += 1
                    tel["input_tokens"] += inp
                    tel["output_tokens"] += out
                    tel["cache_read_tokens"] += cac
                    tel["thinking_tokens"] += int(u.get("thinking_tokens") or 0)
                    if out > 0:
                        productive += 1
                    tel["max_context_carried"] = max(tel["max_context_carried"], ctx)
                    self._usage({"t": time.time(), "kind": "model_call",
                                 "conversation_id": conv_id, "user_turn": user_turn[0],
                                 "input_tokens": inp, "cache_read_tokens": cac,
                                 "output_tokens": out, "context_carried": ctx,
                                 "stop_hook_armed": hook_armed})
                    if self.cap and tel["max_context_carried"] >= self.cap:
                        stop_reason = "safety_cap"
                        stop_detail = {"cap": "runaway_cap_tokens", "limit": self.cap,
                                       "observed": tel["max_context_carried"]}
                        fh.write("SAFETY CAP: %s\n" % json.dumps(stop_detail))
                        capped = True
                        break
            elif kind == "result":
                res = ev.get("result") or {}
                status = str(res.get("status") or "")
                err = str(res.get("error") or "")
                if status.upper() != "SUCCESS":
                    cls = agy_classify(status, err)
                    stop_reason, stop_detail = cls, {"status": status, "error": err}
                    self.fatal_last = {"fatal": True, "class": cls}
                    tel["fatal_exits"] += 1
                    fh.write("%s: %s %s\n" % (cls.upper(), status, err[:400]))
                    t_sig = S.parse_transient_service(status, err)
                    if t_sig:
                        transient_signal = t_sig
                    if cls == "quota_or_rate_limit":
                        qs = S.parse_quota_exhaustion(status, err)
                        if qs:
                            quota_signal = qs
                    fatal = True
                    break
                tel["normal_results"] += 1
                if not self._hook_armed():
                    break                       # Phase 1 and 2A end when the agent stops
                if time.time() >= deadline:
                    timed_out = True
                    break
                now = self._fp()
                no_change = 0 if now != fp else no_change + 1
                fp = now
                if no_change >= self.block_limit:
                    fh.write("yielding after %d consecutive results with no submission change\n"
                             % no_change)
                    tel["yielded_no_change"] += 1
                    break
                tel["internal_continuations"] += 1
                fh.write("--- internal continuation #%d (submission %s) ---\n"
                         % (tel["internal_continuations"], "changed" if no_change == 0 else "same"))
                if not send(P.ANTIGRAVITY_CONTINUE):
                    fatal = True
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=15)
        except Exception:
            try:
                os.killpg(os.getpgid(proc.pid), 9)
            except Exception:
                proc.kill()
            try:
                proc.wait(timeout=10)
            except Exception:
                pass
        r.ctr.kill_agent_processes(AGY_BIN)
        if stop_reason is None:
            stop_reason = ("harness_timeout" if timed_out else
                           agy_classify(process_exited=True) if dead else "normal_completion")
        if capped:
            self.tripped = stop_reason
            (r.ws / "BUDGET_EXCEEDED").write_text(json.dumps(
                {"source": "antigravity adapter", "reason": stop_reason, "detail": stop_detail}))
        try:
            (r.ws / "agy_telemetry.json").write_text(json.dumps(tel, indent=2))
        except OSError:
            pass
        r.log({"event": "agy_invocation", "conversation_id": conv_id,
               "harness_budget_s": int(timeout), "agy_print_timeout_s": print_timeout,
               "elapsed_s": round(time.time() - t0, 1), "timed_out": timed_out,
               "stop_reason": stop_reason, "fatal": fatal, "process_exited": dead,
               "safety_capped": capped, "underlying_model_calls": tel["underlying_model_calls"],
               "max_context_carried": tel["max_context_carried"]})
        fh.close()
        code = -2 if capped else (-1 if fatal else
                                  (proc.returncode if proc.returncode is not None else 0))
        return TurnResult(elapsed_s=time.time() - t0, timed_out=timed_out, exit_code=code,
                          log_bytes=log_path.stat().st_size, quota_wait=quota_signal,
                          productive=productive, transient=transient_signal)


ADAPTERS = {"claude-code": ClaudeCode, "codex": Codex, "antigravity": Antigravity}
