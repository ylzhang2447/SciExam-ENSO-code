#!/usr/bin/env python3
"""Allowlist CONNECT proxy: the only way out of an agent container.

Standard library only, so it runs on a stock Python image. It accepts HTTPS CONNECT to an
exact host name on port 443 and refuses everything else with 403. It resolves the name
itself, so the agent container needs no DNS for the outside world. TLS runs end to end
through the tunnel: the proxy never sees plaintext and installs no certificate.

Every decision is written as one JSON line to stdout and, with --log, to a file.

    python3 egress_proxy.py --port 3128 --allow pypi.org,files.pythonhosted.org
"""
import argparse
import http.server
import json
import select
import socket
import socketserver
import sys
import threading
import time

IDLE_S = 300
_lock = threading.Lock()
_log_fh = None


def log(event, **kw):
    line = json.dumps(dict(t=round(time.time(), 3), event=event, **kw))
    with _lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
        if _log_fh is not None:
            _log_fh.write(line + "\n")
            _log_fh.flush()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # Unbuffered reads: a client that sends its first TLS bytes right behind the CONNECT
    # line would otherwise lose them in the read-ahead buffer.
    rbufsize = 0
    server_version = "allowlist-proxy"
    allowed = frozenset()
    ports = frozenset((443,))

    def log_message(self, *a):
        pass

    def _refuse(self, code, target, why):
        log("deny", client=self.client_address[0], target=target, method=self.command,
            reason=why)
        body = ("blocked by the benchmark network policy: %s\n" % why).encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_CONNECT(self):
        host, _, port = self.path.rpartition(":")
        host = host.strip("[]").lower().rstrip(".")
        try:
            port = int(port)
        except ValueError:
            return self._refuse(400, self.path, "malformed CONNECT target")
        if host not in self.allowed:
            return self._refuse(403, self.path, "host not on the allowlist")
        if port not in self.ports:
            return self._refuse(403, self.path, "port not allowed")
        try:
            upstream = socket.create_connection((host, port), timeout=30)
        except OSError as e:
            log("upstream_error", client=self.client_address[0], target=self.path,
                error=str(e)[:200])
            self.send_response(502)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            return
        log("allow", client=self.client_address[0], target=self.path)
        self.send_response(200, "Connection Established")
        self.end_headers()
        self._relay(self.connection, upstream)

    def _relay(self, a, b):
        a.settimeout(60)
        b.settimeout(60)
        socks = [a, b]
        last = time.time()
        try:
            while time.time() - last < IDLE_S:
                r, _, x = select.select(socks, [], socks, 5.0)
                if x:
                    break
                for s in r:
                    try:
                        data = s.recv(65536)
                    except (BlockingIOError, InterruptedError):
                        continue
                    if not data:
                        return
                    (b if s is a else a).sendall(data)
                    last = time.time()
        except OSError:
            pass
        finally:
            try:
                b.close()
            except OSError:
                pass

    def _plain(self):
        self._refuse(403, self.path, "only HTTPS CONNECT is allowed")

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_OPTIONS = do_PATCH = _plain


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main(argv=None):
    global _log_fh
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=3128)
    ap.add_argument("--allow", required=True, help="comma-separated host names")
    ap.add_argument("--log", help="also append the JSON decision log to this file")
    a = ap.parse_args(argv)
    Handler.allowed = frozenset(h.strip().lower() for h in a.allow.split(",") if h.strip())
    if a.log:
        _log_fh = open(a.log, "a", buffering=1)
    srv = Server((a.bind, a.port), Handler)
    log("start", bind=a.bind, port=a.port, allowed=sorted(Handler.allowed))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
