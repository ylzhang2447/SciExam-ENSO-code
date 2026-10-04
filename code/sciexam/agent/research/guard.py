"""Fail-closed guard of the web research proxy, loaded before ``addon.py``.

If ``addon.py`` fails to import, or a reload of it fails, mitmproxy keeps proxying without
it, so traffic would pass uninspected and unrecorded. This addon holds no rules. It refuses
every request (503) unless the ``Research`` addon is in mitmproxy's current addon chain and
has published the enforcement epoch the proxy was started with (RESEARCH_EXPECTED_EPOCH).
"""
import json
import os
import sys
import time

from mitmproxy import ctx, http

ENFORCER_CLASS = "Research"
EXPECTED = (os.environ.get("RESEARCH_EXPECTED_EPOCH") or "").strip()
LOG = os.environ.get("RESEARCH_LOG", "/logs/decisions.jsonl")


def _addon_live():
    try:
        chain = ctx.master.addons.chain
    except Exception:
        return False

    def walk(a, depth=0):
        if type(a).__name__ == ENFORCER_CLASS:
            return True
        if depth >= 3:
            return False
        for attr in ("addons", "chain"):
            sub = getattr(a, attr, None)
            if isinstance(sub, (list, tuple)) and any(walk(x, depth + 1) for x in sub):
                return True
        return False

    return any(walk(a) for a in chain)


def enforcement_state():
    """(ok, reason): the rules are loaded, live, and the ones the proxy started with."""
    if not _addon_live():
        return False, "the research policy addon is not in the proxy's addon chain"
    tok = sys.modules.get("sciexam_research_enforcement")
    if tok is None or not getattr(tok, "ACTIVE", False):
        return False, "the research policy addon is not loaded"
    if EXPECTED and getattr(tok, "EPOCH", "") != EXPECTED:
        return False, "the enforcement epoch is not the one the proxy was started with"
    return True, None


def _refuse(flow, why):
    rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "decision": "deny",
           "event": "ENFORCEMENT_INACTIVE_BLOCK", "stage": "guard", "reason": why,
           "url": getattr(getattr(flow, "request", None), "pretty_url", None)}
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        print("[guard] %s" % why, file=sys.stderr)
    flow.response = http.Response.make(503, b"refused: the research policy is not in force\n",
                                       {"Content-Type": "text/plain"})


class Guard:
    def request(self, flow):
        ok, why = enforcement_state()
        if not ok:
            _refuse(flow, why)

    def responseheaders(self, flow):
        ok, why = enforcement_state()
        if not ok:
            _refuse(flow, why)


addons = [Guard()]
