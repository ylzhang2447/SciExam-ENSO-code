"""A small YAML reader for the arm configs, so the package needs no YAML dependency.

Supported subset (the configs in agents/ use nothing else, and they are valid YAML for any
full parser as well):

* block mappings, nested by indentation (spaces only)
* block sequences of scalars (``- item``)
* flow sequences of scalars (``[a, b, "c"]``)
* scalars: double or single quoted strings, integers, floats, true, false, null, plain text
* comments starting with ``#`` at the start of a line or after whitespace
"""
import re

_INT = re.compile(r"^[-+]?\d+$")
_FLOAT = re.compile(r"^[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$")


class YamlError(ValueError):
    pass


def _strip_comment(line):
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote and (quote == "'" or line[i - 1] != "\\"):
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(tok, where):
    t = tok.strip()
    if t == "" or t in ("null", "~", "Null", "NULL"):
        return None
    if t[0] == '"':
        if len(t) < 2 or t[-1] != '"':
            raise YamlError("%s: unterminated string %r" % (where, t))
        body = t[1:-1]
        return (body.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")
                .replace("\\\\", "\\"))
    if t[0] == "'":
        if len(t) < 2 or t[-1] != "'":
            raise YamlError("%s: unterminated string %r" % (where, t))
        return t[1:-1].replace("''", "'")
    if t in ("true", "True", "TRUE"):
        return True
    if t in ("false", "False", "FALSE"):
        return False
    if _INT.match(t):
        return int(t)
    if _FLOAT.match(t):
        return float(t)
    if t[0] in "[{&*!|>%@`":
        raise YamlError("%s: unsupported YAML construct %r" % (where, t))
    return t


def _split_flow(body, where):
    items, cur, quote = [], [], None
    for i, ch in enumerate(body):
        if quote:
            cur.append(ch)
            if ch == quote and body[i - 1] != "\\":
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            cur.append(ch)
        elif ch == ",":
            items.append("".join(cur))
            cur = []
        elif ch in "[]{}":
            raise YamlError("%s: nested flow collections are not supported" % where)
        else:
            cur.append(ch)
    last = "".join(cur)
    if last.strip() or items:
        items.append(last)
    return [_scalar(x, where) for x in items if x.strip() != ""]


def _value(tok, where):
    t = tok.strip()
    if t.startswith("["):
        if not t.endswith("]"):
            raise YamlError("%s: unterminated flow sequence" % where)
        return _split_flow(t[1:-1], where)
    return _scalar(t, where)


def loads(text, name="<yaml>"):
    lines = []
    for n, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw[:len(raw) - len(raw.lstrip())]:
            raise YamlError("%s:%d: tabs are not allowed for indentation" % (name, n))
        s = _strip_comment(raw)
        if s.strip() in ("", "---"):
            continue
        lines.append((n, len(s) - len(s.lstrip(" ")), s.strip()))
    pos = [0]

    def block(indent):
        if pos[0] >= len(lines):
            return None
        n, ind, s = lines[pos[0]]
        if ind != indent:
            raise YamlError("%s:%d: unexpected indentation" % (name, n))
        if s.startswith("- ") or s == "-":
            seq = []
            while pos[0] < len(lines):
                n, ind, s = lines[pos[0]]
                if ind < indent:
                    break
                if ind != indent or not (s.startswith("- ") or s == "-"):
                    raise YamlError("%s:%d: bad sequence item" % (name, n))
                item = s[1:].strip()
                if re.match(r"^[^\"'\[][^:]*:(\s|$)", item):
                    raise YamlError("%s:%d: sequences of mappings are not supported" % (name, n))
                seq.append(_value(item, "%s:%d" % (name, n)))
                pos[0] += 1
            return seq
        out = {}
        while pos[0] < len(lines):
            n, ind, s = lines[pos[0]]
            if ind < indent:
                break
            if ind != indent:
                raise YamlError("%s:%d: unexpected indentation" % (name, n))
            m = re.match(r"^([A-Za-z0-9_.\-]+|\"[^\"]+\"):(\s+(.*))?$", s)
            if not m:
                raise YamlError("%s:%d: expected 'key: value', got %r" % (name, n, s))
            key = m.group(1).strip('"')
            if key in out:
                raise YamlError("%s:%d: duplicate key %r" % (name, n, key))
            rest = (m.group(3) or "").strip()
            pos[0] += 1
            if rest:
                out[key] = _value(rest, "%s:%d" % (name, n))
            elif pos[0] < len(lines) and lines[pos[0]][1] > indent:
                out[key] = block(lines[pos[0]][1])
            elif (pos[0] < len(lines) and lines[pos[0]][1] == indent
                  and lines[pos[0]][2].startswith("- ")):
                out[key] = block(indent)
            else:
                out[key] = None
        return out

    if not lines:
        return {}
    result = block(lines[0][1])
    if pos[0] != len(lines):
        n = lines[pos[0]][0]
        raise YamlError("%s:%d: unexpected content" % (name, n))
    return result


def load(path):
    with open(path, encoding="utf-8") as f:
        return loads(f.read(), str(path))
