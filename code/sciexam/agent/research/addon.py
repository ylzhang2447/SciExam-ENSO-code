"""mitmproxy addon of the web research proxy: the only route out of a web-condition agent.

Loaded by ``mitmdump -s guard.py -s addon.py`` inside the research proxy container
(environment/research-proxy/Dockerfile). The rules themselves are in ``policy.py``; this file
applies them to live traffic and keeps the record.

Connections
    Every host name is resolved here, once per client connection, and every address it
    resolves to must be globally routable and outside ``blocked_networks``. One address is
    pinned as the upstream destination (the name is kept for SNI), so no connection is ever
    made to an address this proxy did not check. The model and sign-in hosts of the route
    (``passthrough_hosts``) are TLS passthrough: never decrypted and never inspected, and
    only when the CONNECT target equals the SNI and resolves here. All other TLS is
    intercepted with the per-run CA that the harness installs in the agent container.

Requests
    ``policy.request_decision``: telemetry hosts, request shape (GET and HEAD, no body, no
    oversized or file-shaped values, no runs of the task files), prohibited identifiers, the
    benchmark's own URLs, data sources (literature-only condition), host names.

Responses
    The body is held (never streamed), decoded, inspected in full
    (``policy.response_decision``), recorded and stored, and only then delivered. If
    inspection raises, or the record or the stored copy cannot be written, the body is
    withheld.

Every decision is one JSON line in RESEARCH_LOG, written with fsync before the response is
released, and every delivered body is stored under RESEARCH_ARTIFACTS by its sha256. Each
record carries the enforcement epoch: the sha256 over the hashes of the configuration files,
this addon, the rules and the guard.
"""
import hashlib
import ipaddress
import json
import os
import socket
import sys
import time
import types
import urllib.parse

from mitmproxy import http

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import policy as R                     # noqa: E402  (policy.py next to this file)

CONFIG = os.environ.get("RESEARCH_CONFIG", "/policy")
LOG = os.environ.get("RESEARCH_LOG", "/logs/decisions.jsonl")
ARTIFACTS = os.environ.get("RESEARCH_ARTIFACTS", "/logs/artifacts")
CONFIG_FILES = ("policy.json", "works.json", "content.json", "shingles.json")

POLICY = R.load_json(os.path.join(CONFIG, "policy.json"))
FP = R.load_json(os.path.join(CONFIG, "works.json"))
CFP = R.load_json(os.path.join(CONFIG, "content.json"))
SHINGLES = R.load_json(os.path.join(CONFIG, "shingles.json"))
SHINGLES["hashes"] = set(SHINGLES.get("hashes", []))
NETS = [ipaddress.ip_network(n) for n in POLICY["blocked_networks"]]
PASSTHROUGH = [h.lower() for h in POLICY["passthrough_hosts"]]
MAX_DOWN = int(POLICY.get("max_download_bytes", 50 * 1024 * 1024))
SEQ = [0]
BLOCKED_CONNS = set()
PINNED = {}        # (client connection, host name) -> the address validated and pinned
PIN_BACK = {}      # (client connection, address, port) -> the host name it was pinned for
RESOLVED = {}      # (client connection, host name) -> (addresses, refusal reason)
DEAD_END = ("127.0.0.1", 9)


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def enforcement_epoch():
    """sha256 over the sorted map of file name -> sha256 of everything that decides."""
    here = os.path.dirname(os.path.abspath(__file__))
    parts = {name: os.path.join(CONFIG, name) for name in CONFIG_FILES}
    parts.update({"addon.py": os.path.abspath(__file__), "policy.py": R.__file__,
                  "guard.py": os.path.join(here, "guard.py")})
    digests = {}
    for name, path in parts.items():
        try:
            with open(path, "rb") as fh:
                digests[name] = _sha(fh.read())
        except OSError:
            digests[name] = "MISSING"
    return _sha(json.dumps(digests, sort_keys=True).encode())


EPOCH = enforcement_epoch()


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _rid():
    SEQ[0] += 1
    return "r%06d" % SEQ[0]


def write_record(rec):
    """Append one decision record and return only once it is on disk."""
    rec.setdefault("policy_epoch", EPOCH)
    blob = (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        view = memoryview(blob)
        while view:
            n = os.write(fd, view)
            if not n:
                raise IOError("short write of a decision record")
            view = view[n:]
        os.fsync(fd)
    finally:
        os.close(fd)


def write_record_best_effort(rec):
    """For records written after the body was already withheld: never raises."""
    try:
        write_record(rec)
    except Exception:
        sys.stderr.write("RESEARCH_RECORD_FAILURE %s\n" % json.dumps(rec)[:800])


def store_artifact(body, digest, suffix):
    """Write a delivered body as <sha256><suffix>, fsync it and read it back."""
    os.makedirs(ARTIFACTS, exist_ok=True)
    path = os.path.join(ARTIFACTS, digest + suffix)
    if os.path.exists(path):
        with open(path, "rb") as fh:
            if _sha(fh.read()) != digest:
                raise IOError("an existing artifact does not match its name")
        return path
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(body)
        fh.flush()
        os.fsync(fh.fileno())
    os.rename(tmp, path)
    with open(path, "rb") as fh:
        if _sha(fh.read()) != digest:
            raise IOError("the stored artifact does not read back as written")
    return path


def resolve_validated(host):
    """(addresses, refusal reason). Every address must be global and outside the blocked
    networks; a name that does not resolve is refused."""
    h = (host or "").lower().rstrip(".")
    if h in [x.lower() for x in POLICY.get("blocked_hostnames", [])]:
        return set(), "an internal hostname, not the public web"
    try:
        addrs = {sa[0] for _f, _t, _p, _c, sa in socket.getaddrinfo(h, None)}
    except Exception as e:
        return set(), "the name does not resolve here (%s)" % type(e).__name__
    if not addrs:
        return set(), "the name resolves to nothing"
    for a in addrs:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            return set(), "an address that is not an address: %s" % a[:40]
        if any(ip in n for n in NETS) or not ip.is_global or ip.is_multicast:
            return set(), "resolves to a private, loopback or link-local address (%s)" % a
    return addrs, None


def resolve_for(cid, host):
    """The one resolution of ``host`` on client connection ``cid``."""
    key = (cid, (host or "").lower().rstrip("."))
    if key not in RESOLVED:
        RESOLVED[key] = resolve_validated(host)
    return RESOLVED[key]


def _block(flow, code, msg):
    flow.metadata["research_decision"] = "blocked"
    flow.response = http.Response.make(code, msg.encode(),
                                       {"content-type": "text/plain; charset=utf-8"})


def _base(flow, rid):
    req = flow.request
    return {"request_id": rid, "t": _now(), "method": req.method, "url": req.pretty_url,
            "normalized_url": R.normalize_url(req.pretty_url), "host": req.pretty_host,
            "scheme": req.scheme}


class Research:
    """Applies the research policy to every connection, request and response."""

    def running(self):
        cfg = {}
        for name in CONFIG_FILES:
            with open(os.path.join(CONFIG, name), "rb") as fh:
                cfg[name] = _sha(fh.read())
        write_record_best_effort({
            "event": "policy_loaded", "t": _now(), "decision": "n/a",
            "policy": POLICY.get("policy"), "config_sha256": cfg,
            "addon_sha256": _sha(open(os.path.abspath(__file__), "rb").read()),
            "policy_module_sha256": _sha(open(R.__file__, "rb").read()),
            "pdf_text_available": R.PDF_OK, "prohibited_works": [w["id"] for w in FP["works"]],
            "benchmark_self": {k: len(v) for k, v in (POLICY.get("benchmark_self") or {}).items()},
            "passthrough_hosts": POLICY["passthrough_hosts"],
            "workspace_shingles": len(SHINGLES["hashes"])})

    def tls_clienthello(self, data):
        """Pass through a connection to a passthrough host only when the CONNECT target is
        that host (or the address pinned for it) on port 443 and it resolves here."""
        sni = (data.client_hello.sni or "").lower().rstrip(".")
        if sni not in PASSTHROUGH:
            return
        try:
            target = data.context.server.address or ("", 0)
            thost, tport = str(target[0]).lower().rstrip("."), int(target[1])
            cid = getattr(getattr(data.context, "client", None), "id", None)
        except Exception:
            thost, tport, cid = "", 0, None
        named = PIN_BACK.get((cid, thost, tport), thost)
        ok = sni == named and tport == 443
        if ok:
            addrs, why = resolve_for(cid, sni)
            ok = bool(addrs) and not why and (thost == named or thost in addrs)
        if ok:
            data.ignore_connection = True
        else:
            write_record_best_effort({"t": _now(), "decision": "deny", "event": "TLS_BINDING_BLOCK",
                                      "stage": "tls", "host": thost or sni, "sni": sni,
                                      "url": "connect://%s:%s" % (thost, tport),
                                      "reason": "the connection does not go to the approved "
                                                "%s endpoint" % sni})

    def server_connect(self, data):
        """Validate and pin the upstream address before a transport exists."""
        try:
            addr = data.server.address or ("", 0)
            host, port = str(addr[0]), int(addr[1] or 443)
        except Exception:
            host, port = "", 443
        cid = getattr(getattr(data, "client", None), "id", None)

        def deny(reason, event):
            write_record_best_effort({"t": _now(), "decision": "deny", "stage": "connect",
                                      "event": event, "host": host,
                                      "url": "connect://%s:%s" % (host, port), "reason": reason})
            if cid:
                BLOCKED_CONNS.add(cid)
            try:
                data.server.error = "refused by the research policy: %s" % reason
            except Exception:
                data.server.address = DEAD_END
            raise ConnectionRefusedError("refused by the research policy: %s" % reason)

        if not host:
            return deny("no destination to validate", "PEER_BINDING_BLOCK")
        addrs, why = resolve_for(cid, host)
        if why:
            return deny(why, "PRIVATE_NETWORK_BLOCK" if "private" in why or "internal" in why
                        else "DNS_BLOCK")
        v4 = sorted(a for a in addrs if ":" not in a)
        chosen = (v4 or sorted(addrs))[0]
        try:
            if not getattr(data.server, "sni", None):
                data.server.sni = host
            data.server.address = (chosen, port)
        except Exception as e:
            return deny("the destination could not be pinned (%s)" % type(e).__name__,
                        "PEER_BINDING_BLOCK")
        PINNED[(cid, host)] = chosen
        PIN_BACK[(cid, chosen, port)] = host

    def server_connected(self, data):
        """Refuse a connection whose peer is not the pinned address."""
        try:
            host = str((data.server.address or ("", 0))[0])
            peer = (data.server.peername or (None,))[0]
        except Exception:
            host, peer = "", None
        cid = getattr(getattr(data, "client", None), "id", None)
        expected = PINNED.get((cid, host))
        known = RESOLVED.get((cid, (host or "").lower().rstrip(".")), (set(), None))[0]
        if peer is None or not (str(peer) == expected or str(peer) == host or str(peer) in known):
            write_record_best_effort({"t": _now(), "decision": "deny", "stage": "connected",
                                      "event": "PEER_BINDING_BLOCK", "host": host,
                                      "peer": str(peer), "expected": expected,
                                      "reason": "the peer is not the address this proxy pinned"})
            if cid:
                BLOCKED_CONNS.add(cid)
            try:
                data.server.error = "refused by the research policy: peer binding"
            except Exception:
                pass
            raise ConnectionRefusedError("refused by the research policy: peer binding")

    def client_disconnected(self, client):
        """Forget the pins and lookups of a closed client connection."""
        cid = getattr(client, "id", None)
        if not cid:
            return
        for table in (PINNED, RESOLVED, PIN_BACK):
            for k in [k for k in table if k[0] == cid]:
                table.pop(k, None)
        BLOCKED_CONNS.discard(cid)

    def _conn_blocked(self, flow):
        return any(getattr(c, "id", None) in BLOCKED_CONNS
                   for c in (getattr(flow, "server_conn", None), getattr(flow, "client_conn", None)))

    def error(self, flow):
        if flow.metadata.get("research_decision") == "blocked":
            return
        write_record_best_effort({"t": _now(), "decision": "deny", "stage": "transport",
                                  "event": "TRANSPORT_ERROR",
                                  "host": getattr(flow.request, "pretty_host", ""),
                                  "url": getattr(flow.request, "pretty_url", ""),
                                  "reason": str(getattr(flow, "error", ""))[:200]})

    def responseheaders(self, flow):
        if flow.response is not None:
            flow.response.stream = False           # hold the body until it is inspected

    # ---- requests --------------------------------------------------------------------------

    def request(self, flow):
        try:
            self._request(flow)
        except Exception as e:
            write_record_best_effort({"t": _now(), "host": flow.request.pretty_host,
                                      "url": flow.request.pretty_url, "decision": "deny",
                                      "event": "ADDON_ERROR", "stage": "request",
                                      "reason": "%s: %s" % (type(e).__name__, e)})
            _block(flow, 500, "the research policy could not examine this request")

    def _request(self, flow):
        req = flow.request
        rid = _rid()
        flow.metadata["research_rid"] = rid
        base = _base(flow, rid)
        if self._conn_blocked(flow):
            return _block(flow, 502, "refused by the research policy: peer binding")
        if req.pretty_host.lower() in PASSTHROUGH:
            # A genuine passthrough connection never reaches the request stage.
            write_record(dict(base, decision="deny", stage="tls", event="TLS_BINDING_BLOCK",
                              reason="a request naming %s that was not going to it"
                                     % req.pretty_host))
            return _block(flow, 403, "refused by the research policy")
        decision, code, event, why, wid = R.request_decision(
            req.method, req.pretty_url, dict(req.headers), req.raw_content or b"",
            POLICY, FP, SHINGLES)
        if decision == "deny":
            rec = dict(base, decision="deny", stage="request", event=event, reason=why)
            if wid:
                rec["work_id"] = wid
            write_record_best_effort(rec)
            return _block(flow, code, "refused by the research policy")
        cid = getattr(getattr(flow, "client_conn", None), "id", None)
        addrs, why = resolve_for(cid, req.pretty_host)
        if why:
            write_record_best_effort(dict(base, decision="deny", stage="request",
                                          event="PRIVATE_NETWORK_BLOCK", reason=why))
            return _block(flow, 403, "refused by the research policy")
        flow.metadata["research_addrs"] = sorted(addrs)

    # ---- responses -------------------------------------------------------------------------

    def response(self, flow):
        try:
            self._response(flow)
        except Exception as e:
            _block(flow, 502, "the research policy could not examine this response")
            write_record_best_effort({"t": _now(), "host": flow.request.pretty_host,
                                      "url": flow.request.pretty_url, "decision": "deny",
                                      "event": "ADDON_ERROR", "stage": "response",
                                      "reason": "%s: %s" % (type(e).__name__, e),
                                      "body_withheld": True})

    def _response(self, flow):
        if flow.response is None or flow.metadata.get("research_decision") == "blocked":
            return
        if flow.request.pretty_host.lower() in PASSTHROUGH:
            return
        rid = flow.metadata.get("research_rid") or _rid()
        if self._conn_blocked(flow):
            return _block(flow, 502, "refused by the research policy: peer binding")
        validated = set(flow.metadata.get("research_addrs") or [])
        try:
            peer = (flow.server_conn.peername or (None,))[0]
        except Exception:
            peer = None
        resp = flow.response
        raw = resp.raw_content or b""
        enc = resp.headers.get("content-encoding", "")
        url = flow.request.pretty_url
        base = dict(_base(flow, rid), status=resp.status_code,
                    mime=resp.headers.get("content-type", ""),
                    content_encoding=enc or "identity", raw_bytes=len(raw), final_url=url,
                    is_redirect=300 <= resp.status_code < 400)
        loc = resp.headers.get("location")
        if loc:
            base["redirect_to"] = base["final_url"] = urllib.parse.urljoin(url, loc)

        def refuse(code, reason, event, work_id=None, stage="content"):
            _block(flow, code, "refused by the research policy")
            rec = dict(base, decision="deny", reason=reason, stage=stage, event=event,
                       body_withheld=True)
            if work_id:
                rec["work_id"] = work_id
            write_record_best_effort(rec)

        if validated and (peer is None or str(peer) not in validated):
            return refuse(502, "the connection went to an address this proxy did not validate",
                          "PEER_BINDING_BLOCK", stage="peer")
        body, why = R.decode_body(raw, enc)
        if body is None:
            return refuse(415, "content that could not be decoded cannot be inspected: %s" % why,
                          "UNDECODABLE_BLOCK")
        if len(body) > MAX_DOWN:
            return refuse(413, "download over the size limit", "SIZE_BLOCK", stage="size")
        decision, code, event, why, wid, text = R.response_decision(
            body, base["mime"], url, POLICY, FP, CFP)
        if decision == "deny":
            return refuse(code, why, event, wid)
        if decision == "redact":
            body = text.encode("utf-8")
        kind = R.sniff(body)
        rec = dict(base, decision=decision, kind=kind, bytes_delivered=len(body),
                   sha256=_sha(body))
        if decision == "redact":
            rec["event"] = "GRADER_LEAKAGE_REDACT"
        ax, doi = R.ids_in(R.normalize_url(url))
        if ax:
            rec["arxiv_id"] = sorted(ax)[0]
        if doi:
            rec["doi"] = sorted(doi)[0]
        if text and kind == "text":
            ident = R.document_identity(text, base["mime"], url)
            if ident["titles"]:
                rec["title"] = ident["titles"][-1][:200]
        if body:
            try:
                rec["artifact"] = os.path.basename(store_artifact(
                    body, rec["sha256"], ".pdf" if kind == "pdf" else ".txt"))
            except Exception as e:
                return refuse(502, "the delivered body could not be stored (%s)"
                              % type(e).__name__, "ARTIFACT_FAILURE", stage="record")
        try:
            write_record(rec)
        except Exception as e:
            return refuse(502, "the decision could not be recorded (%s)" % type(e).__name__,
                          "RECORD_FAILURE", stage="record")
        if decision == "redact":
            flow.response.text = text


def _publish_enforcement():
    """Tell guard.py that the rules are loaded, with the epoch they were loaded under."""
    tok = types.ModuleType("sciexam_research_enforcement")
    tok.ACTIVE = True
    tok.EPOCH = EPOCH
    sys.modules["sciexam_research_enforcement"] = tok


_publish_enforcement()
addons = [Research()]
