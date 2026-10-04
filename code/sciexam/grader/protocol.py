"""Wire format between the scoring process and the submission worker.

A frame is one JSON header line followed by a raw float64 payload. The random stream is
carried across explicitly: every request ships the bit generator state and the reply returns
the advanced state, so a sandboxed run draws exactly the numbers an in-process run would.
"""
import json

import numpy as np

PROTOCOL = 1
MAX_HEADER_BYTES = 64 * 1024
MAX_PAYLOAD_BYTES = 256 * 1024 * 1024
MAX_DIMS = 4


class ProtocolError(ValueError):
    """A malformed frame. Never a verdict about the model."""


def check_header(head):
    if not isinstance(head, dict):
        raise ProtocolError("header is not an object")
    n = head.get("bytes", 0)
    if not isinstance(n, int) or isinstance(n, bool) or n < 0 or n > MAX_PAYLOAD_BYTES or n % 8:
        raise ProtocolError("bad payload length %r" % (n,))
    shape = head.get("shape")
    if shape is not None:
        if (not isinstance(shape, list) or not shape or len(shape) > MAX_DIMS
                or not all(isinstance(d, int) and not isinstance(d, bool) and d >= 0 for d in shape)):
            raise ProtocolError("bad shape %r" % (shape,))
        want = 8
        for d in shape:
            want *= d
        if want != n:
            raise ProtocolError("shape %r needs %d bytes, header declares %d" % (shape, want, n))
    return head


def _readline(fin):
    buf = bytearray()
    while True:
        ch = fin.read(1)
        if not ch:
            return bytes(buf)
        buf += ch
        if ch == b"\n":
            return bytes(buf)
        if len(buf) > MAX_HEADER_BYTES:
            raise ProtocolError("header longer than %d bytes" % MAX_HEADER_BYTES)


def recv(fin):
    """(header, payload bytes), or (None, None) at end of stream."""
    line = _readline(fin)
    if not line:
        return None, None
    try:
        head = json.loads(line.decode("utf-8"))
    except Exception as e:
        raise ProtocolError("header is not JSON: %s" % e)
    check_header(head)
    n = head.get("bytes") or 0
    buf = b""
    while len(buf) < n:
        chunk = fin.read(n - len(buf))
        if not chunk:
            raise ProtocolError("payload truncated: %d of %d bytes" % (len(buf), n))
        buf += chunk
    return head, buf


def send(fout, head, arr=None):
    payload = b""
    if arr is not None:
        a = np.ascontiguousarray(arr, dtype=np.float64)
        head = dict(head, shape=list(a.shape))
        payload = a.tobytes()
    head = dict(head, bytes=len(payload))
    fout.write((json.dumps(head) + "\n").encode("utf-8"))
    if payload:
        fout.write(payload)
    fout.flush()


def array(head, buf):
    a = np.frombuffer(buf, dtype=np.float64)
    return a.reshape(tuple(head.get("shape") or (a.size,)))


def generator_from_state(state):
    g = np.random.default_rng()
    g.bit_generator.state = state
    return g
