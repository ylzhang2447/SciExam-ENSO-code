"""Provider-neutral reading of allocation exhaustion and service conditions in agent output.

The harness pauses the eligible clock only for a limit the provider itself states, with a
reset the provider itself names. This module recognises such statements. It never decides
a pause length on its own: an exhaustion without a parseable reset is reported as
unbounded and is not credited.

Two channels establish allocation exhaustion: a structured field the provider emits (for
example codex_error_info = usage_limit_exceeded), or ordinary text that says an allowance
is spent ("usage limit", "quota", "session limit"). Throttling words ("rate limit",
"overloaded", a bare 429) never qualify.
"""
import datetime
import json
import os
import re

QUOTA_WAIT_MAX_S = 21600
QUOTA_WAIT_MIN_S = 5

_ALLOCATION_EXHAUSTED_PHRASES = (
    "quota reached", "quota exceeded", "quota exhausted", "out of quota",
    "quota limit reached", "insufficient quota",
    "resource_exhausted", "resource exhausted",
    "usage limit", "usage limit reached", "usage limit exceeded",
    "hit your usage limit", "exceeded your usage limit",
    "session limit", "hit your session limit", "weekly limit",
    "monthly limit", "message limit reached", "credit balance is too low",
    "plan limit reached", "allowance exhausted",
)

_STRUCTURED_EXHAUSTION = {
    "codex_error_info": {"usage_limit_exceeded", "quota_exceeded"},
    "error_code": {"usage_limit_exceeded", "rate_limit_exceeded_quota",
                   "insufficient_quota", "resource_exhausted"},
    "type": {"insufficient_quota"},
    "code": {"resource_exhausted", "insufficient_quota"},
    "reason": {"resource_exhausted", "quota_exceeded"},
    "stop_reason": {"quota_or_rate_limit"},
}
# Too broad to credit on its own (it merges a spent allowance with a throttle).
_STRUCTURED_AMBIGUOUS = {("stop_reason", "quota_or_rate_limit")}

_RESET_PATTERNS = (
    ("countdown", re.compile(r"reset[a-z]*\s+in\s+((?:\d+(?:\.\d+)?[hms])+)", re.I)),
    ("countdown", re.compile(
        r"(?:try again|retry|available again)\s+in\s+((?:\d+(?:\.\d+)?[hms])+)", re.I)),
    ("countdown", re.compile(r"limit(?:s)?\s+reset[a-z]*\s+in\s+"
                             r"((?:\d+(?:\.\d+)?[hms])+)", re.I)),
    ("retry_after_seconds", re.compile(
        r"retry[-_ ]?after[:=\s]+(\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?\b", re.I)),
    ("absolute", re.compile(
        r"reset[a-z]*\s+at\s+(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)", re.I)),
)

_STRUCTURED_RESET_KEYS = ("reset_at", "resets_at", "reset_time", "x-ratelimit-reset",
                          "retry_after", "retry_after_s", "reset_after_s")

_DUR_UNITS = {"h": 3600.0, "m": 60.0, "s": 1.0}

# A reset stated as a wall-clock time ("try again at 1:10 AM", "resets 9:20am (UTC)"). The
# zone is the one stated beside the time, else SCIEXAM_PROVIDER_TZ (default UTC). The
# interpretation is recorded with every parse.
_STATED_TZ = r"(?:\s*\(\s*([A-Za-z][A-Za-z0-9_+\-]*(?:/[A-Za-z0-9_+\-]+)*)\s*\))?"
_LOCAL_CLOCK_PATTERNS = (
    re.compile(r"(?:try again|retry|available again|resets?)\s+(?:at\s+)?"
               r"(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?[Mm]\.?" + _STATED_TZ, re.I),
    re.compile(r"(?:try again|retry|available again|resets?)\s+(?:at\s+)?"
               r"([01]?\d|2[0-3]):([0-5]\d)(?!\s*[AaPp])" + _STATED_TZ, re.I),
)


def provider_tz():
    return os.environ.get("SCIEXAM_PROVIDER_TZ", "UTC")


def _tzinfo(name):
    if name.upper() == "UTC":
        return datetime.timezone.utc
    try:
        import zoneinfo
        return zoneinfo.ZoneInfo(name)
    except Exception:
        return datetime.timezone.utc


def parse_local_clock_reset(text, now=None, tz_name=None):
    """A wall-clock reset, as the next occurrence of that time, in seconds from now."""
    declared = tz_name or provider_tz()
    base = now or datetime.datetime.now(datetime.timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=datetime.timezone.utc)
    for i, pat in enumerate(_LOCAL_CLOCK_PATTERNS):
        ms = list(pat.finditer(text))
        m = ms[-1] if ms else None          # the last stated reset is the current one
        if not m:
            continue
        try:
            if i == 0:
                hour = int(m.group(1))
                minute = int(m.group(2) or 0)
                if not (1 <= hour <= 12) or not (0 <= minute <= 59):
                    return None
                hour = (hour % 12) + (12 if m.group(3).lower() == "p" else 0)
            else:
                hour, minute = int(m.group(1)), int(m.group(2))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    return None
        except (TypeError, ValueError):
            return None
        stated = m.group(4) if i == 0 else m.group(3)
        tz_name, tz_source = declared, "declared"
        if stated:
            if stated.upper() in ("UTC", "GMT", "Z"):
                tz_name, tz_source = "UTC", "stated"
            else:
                try:
                    import zoneinfo
                    zoneinfo.ZoneInfo(stated)
                    tz_name, tz_source = stated, "stated"
                except Exception:
                    pass
        tz = _tzinfo(tz_name)
        local_now = base.astimezone(tz)
        target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= local_now:
            target += datetime.timedelta(days=1)
        return {"reset_text": m.group(0),
                "event_timestamp": base.astimezone(
                    datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "timezone_interpretation": tz_name,
                "timezone_source": tz_source,
                "parsed_reset_at": target.isoformat(),
                "reset_delay_s": round((target - local_now).total_seconds(), 3)}
    return None


_AUTH_PHRASES = ("unauthenticated", "unauthorized", "permission denied",
                 "invalid_grant", "forbidden", "token expired", "invalid api key")

_SERVICE_CONDITION_PHRASES = (
    "high traffic", "heavy traffic", "temporarily unavailable", "service unavailable",
    "currently unavailable", "temporarily overloaded", "overloaded", "over capacity",
    "at capacity", "server is busy", "servers are busy", "servers are experiencing",
    "service is busy", "try again in a", "please try again later", "try again later",
)
TRANSIENT_RETRY_SPACING_S = 30
TRANSIENT_RETRY_SPACING_MAX_S = 300


def _parse_go_duration(text):
    parts = re.findall(r"(\d+(?:\.\d+)?)([hms])", text, re.I)
    if not parts:
        return None
    total = 0.0
    for value, unit in parts:
        try:
            total += float(value) * _DUR_UNITS[unit.lower()]
        except (ValueError, KeyError):
            return None
    return total


def _lower_keys(d):
    return {str(k).lower(): v for k, v in (d or {}).items()}


def _structured_hits(structured):
    strong, ambiguous = [], []
    for k, v in _lower_keys(structured).items():
        if not isinstance(v, (str, int)):
            continue
        val = str(v).strip().lower()
        wanted = _STRUCTURED_EXHAUSTION.get(k)
        if wanted and val in wanted:
            (ambiguous if (k, val) in _STRUCTURED_AMBIGUOUS else strong).append(
                "%s=%s" % (k, val))
    return strong, ambiguous


def _parse_reset(text, structured, now):
    """A reset the provider stated: (seconds, source, raw, local_clock_evidence)."""
    base = now or datetime.datetime.now(datetime.timezone.utc)
    for key, raw in _lower_keys(structured).items():
        if key not in _STRUCTURED_RESET_KEYS or raw in (None, ""):
            continue
        try:
            if key in ("retry_after", "retry_after_s", "reset_after_s"):
                return float(raw), "structured_retry_after", str(raw), None
            num = float(raw)
            if num > 1e11:                         # epoch milliseconds
                num /= 1000.0
            return num - base.timestamp(), "structured_epoch", str(raw), None
        except (TypeError, ValueError):
            pass
        try:
            iso = str(raw).replace(" ", "T")
            if iso.endswith("Z"):
                iso = iso[:-1] + "+00:00"
            target = datetime.datetime.fromisoformat(iso)
            if target.tzinfo is None:
                target = target.replace(tzinfo=datetime.timezone.utc)
            return (target - base).total_seconds(), "structured_absolute", str(raw), None
        except (TypeError, ValueError):
            pass
    lc = parse_local_clock_reset(text, now=now)
    for kind, pat in _RESET_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        raw = m.group(1)
        if kind == "countdown":
            v = _parse_go_duration(raw)
            if v is not None:
                return v, "countdown", raw, None
        elif kind == "retry_after_seconds":
            try:
                return float(raw), "retry_after", raw, None
            except ValueError:
                pass
        elif kind == "absolute":
            try:
                iso = raw.replace(" ", "T")
                if iso.endswith("Z"):
                    iso = iso[:-1] + "+00:00"
                target = datetime.datetime.fromisoformat(iso)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=datetime.timezone.utc)
                return (target - base).total_seconds(), "absolute", raw, None
            except (ValueError, TypeError):
                pass
    if lc is not None:
        return lc["reset_delay_s"], "local_clock", lc["reset_text"], lc
    return None, None, None, None


def parse_quota_exhaustion(status="", err="", now=None, structured=None):
    """Explicit allocation exhaustion, or None. `bounded` says whether a pause may be credited."""
    text = ("%s %s" % (status, err)).strip()
    low = text.lower()
    if any(w in low for w in _AUTH_PHRASES):
        return None
    strong, ambiguous = _structured_hits(structured)
    phrase = next((p for p in _ALLOCATION_EXHAUSTED_PHRASES if p in low), None)
    has_code = ("resource_exhausted" in low or "resource exhausted" in low
                or re.search(r"\b429\b", low) is not None)
    if not strong and not phrase:
        return None
    seconds, source, raw, lc = _parse_reset(text, structured, now)
    bounded = False
    if seconds is not None:
        try:
            seconds = float(seconds)
            bounded = bool(seconds == seconds
                           and seconds not in (float("inf"), float("-inf"))
                           and QUOTA_WAIT_MIN_S <= seconds <= QUOTA_WAIT_MAX_S)
        except (TypeError, ValueError):
            bounded = False
    if not bounded:
        seconds, source, raw, lc = None, None, None, None
    lc = lc or {}
    return {
        "class": "allocation_exhausted",
        "bounded": bounded,
        "reset_delay_s": round(seconds, 3) if bounded else None,
        "reset_source": source,
        "reset_raw": raw,
        "reset_text": lc.get("reset_text"),
        "timezone_interpretation": lc.get("timezone_interpretation"),
        "timezone_source": lc.get("timezone_source"),
        "parsed_reset_at": lc.get("parsed_reset_at"),
        "code_token_present": has_code,
        "structured_evidence": strong,
        "structured_corroboration": ambiguous,
        "matched_phrase": phrase,
        "evidence_channel": ("structured" if strong and not phrase
                             else "textual" if phrase and not strong else "both"),
        "reason": ("explicit allocation exhaustion with a parseable reset" if bounded
                   else "explicit allocation exhaustion with no provider-stated reset"),
    }


def parse_transient_service(status="", err="", structured=None):
    """A temporary condition of the provider's own service. Never allocation, never auth."""
    if parse_quota_exhaustion(status, err, structured=structured) is not None:
        return None
    low = ("%s %s" % (status, err)).lower()
    if any(w in low for w in _AUTH_PHRASES):
        return None
    hit = next((ph for ph in _SERVICE_CONDITION_PHRASES if ph in low), None)
    if hit is None:
        return None
    spacing, source = TRANSIENT_RETRY_SPACING_S, "default"
    m = re.search(r"retry[-_ ]?after[:=\s]+(\d+(?:\.\d+)?)", low)
    if m:
        try:
            v = float(m.group(1))
            if 0 < v <= TRANSIENT_RETRY_SPACING_MAX_S:
                spacing, source = v, "retry_after"
        except ValueError:
            pass
    else:
        m2 = re.search(r"(?:try again|retry|available again)\s+in\s+"
                       r"((?:\d+(?:\.\d+)?[hms])+)", low)
        if m2:
            v = _parse_go_duration(m2.group(1))
            if v and 0 < v <= TRANSIENT_RETRY_SPACING_MAX_S:
                spacing, source = v, "stated_interval"
    return {"class": "provider_service", "matched_phrase": hit,
            "retry_spacing_s": round(spacing, 3), "spacing_source": source,
            "reason": "explicit temporary provider service condition"}


# ---- Codex output ----------------------------------------------------------------------

_INTERESTING = ("codex_error_info", "error_code", "type", "code", "reason",
                "retry_after", "retry_after_s", "reset_at", "resets_at", "x-ratelimit-reset")
_MESSAGE_KEYS = ("message", "error", "detail", "error_message", "text")
_KV = re.compile(r"\b(codex_error_info|error_code|error_type)\b\s*[:=]\s*"
                 r"['\"]?([A-Za-z0-9_\-]+)", re.I)


def _walk(obj, out_struct, out_msgs):
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in _INTERESTING and isinstance(v, (str, int, float)):
                out_struct.setdefault(lk, str(v))
            if lk in _MESSAGE_KEYS and isinstance(v, str) and v.strip():
                out_msgs.append(v.strip())
            _walk(v, out_struct, out_msgs)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, out_struct, out_msgs)


def scan_codex_text(text):
    structured, msgs = {}, []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line[0] in "{[":
            try:
                _walk(json.loads(line), structured, msgs)
                continue
            except Exception:
                pass
        m = re.search(r"(\{.*\})\s*$", line)
        if m:
            try:
                _walk(json.loads(m.group(1)), structured, msgs)
            except Exception:
                pass
        for k, v in _KV.findall(line):
            structured.setdefault(k.lower(), v)
        if "usage limit" in line.lower() or "quota" in line.lower():
            msgs.append(line)
    return structured, (msgs[-1] if msgs else "")


def tail_text(path, nbytes, marker=None):
    """The last `nbytes` of a log, cut at the last `marker` so only the latest turn is read."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            take = min(size, nbytes)
            fh.seek(size - take)
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
    if marker:
        cut = text.rfind(marker)
        if cut >= 0:
            text = text[cut:]
    return text


def classify_codex_log(path):
    structured, message = scan_codex_text(tail_text(path, 262144))
    q = parse_quota_exhaustion("ERROR", message, structured=structured)
    t = None if q is not None else parse_transient_service("ERROR", message,
                                                           structured=structured)
    return q, t, {"structured": structured, "message": message[:400]}
