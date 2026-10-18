"""Helpers shared by the probe plugins. Standard library + pytest only.

Runs inside the target interpreter, so it must never invoke user-defined
code paths beyond what pytest itself already does.
"""

from __future__ import annotations

import hashlib
import json
import os
import re

_TYPE_QUALNAME = type.__dict__["__qualname__"]
_TYPE_MODULE = type.__dict__["__module__"]

NAME_PATTERN = re.compile(
    r"(?i)pass(word|wd)?|secret|token|api_?key|auth|cookie|session|credential|private"
)
VALUE_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-~+/]{12,}=*"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
]
_ADDR = re.compile(r"0x[0-9a-fA-F]+")


def type_name(cls: type) -> str:
    """'module.QualName' read through type descriptors (no metaclass hooks)."""
    try:
        q = _TYPE_QUALNAME.__get__(cls)
        m = _TYPE_MODULE.__get__(cls)
        if type(q) is str and type(m) is str:
            return f"{m}.{q}"
    except Exception:  # noqa: BLE001 - defensive: never propagate from a probe
        pass
    return "<unknown>"


def redact_text(text: str) -> str:
    for pat in VALUE_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


def name_is_sensitive(name: str) -> bool:
    return bool(NAME_PATTERN.search(name))


def failure_signature(item, call, rep, repo_root: str) -> dict:
    """Signature of a failed report. Uses data pytest already computed."""
    sig: dict = {}
    excinfo = getattr(call, "excinfo", None)
    if excinfo is not None:
        sig["exception_type"] = type_name(excinfo.type)
        item_path = os.path.realpath(str(getattr(item, "path", "")))
        test_line = None
        try:
            for entry in excinfo.traceback:
                if os.path.realpath(str(entry.path)) == item_path:
                    test_line = entry.lineno + 1
        except Exception:  # noqa: BLE001
            pass
        sig["test_line"] = test_line
    message = None
    longrepr = rep.longrepr
    crash = getattr(longrepr, "reprcrash", None)
    if crash is not None:
        sig["crash_path"] = _rel(str(crash.path), repo_root)
        sig["crash_line"] = int(crash.lineno)
        message = crash.message
    elif isinstance(longrepr, str):
        message = longrepr
    elif isinstance(longrepr, tuple) and len(longrepr) == 3:  # skip-style (path, line, msg)
        message = str(longrepr[2])
    if message is not None:
        normalized = redact_text(_ADDR.sub("0x?", message[:4000])).strip()
        sig["message_digest"] = hashlib.sha256(normalized.encode()).hexdigest()[:16]
        sig["message_excerpt"] = normalized[:300]
    return sig


def _rel(path: str, root: str) -> str:
    real = os.path.realpath(path)
    if real.startswith(root + os.sep):
        return os.path.relpath(real, root).replace(os.sep, "/")
    return real


def xfail_class(item, call, rep) -> str:
    """Explicit xfail classification (see contracts.XfailClass)."""
    if getattr(item.config.option, "runxfail", False):
        return "none"
    if hasattr(rep, "wasxfail"):
        if rep.skipped:
            return "xfail"
        if rep.passed:
            return "xpass"
    try:
        from _pytest.skipping import xfailed_key  # private; verified on pytest 9.1.1

        xf = item.stash.get(xfailed_key, None)
        known = True
    except Exception:  # noqa: BLE001
        xf, known = None, False
    if xf is not None and rep.failed:
        if call.excinfo is None and call.when == "call":
            return "xpass_strict"
        if call.excinfo is not None:
            return "xfail_raises_mismatch"
    if isinstance(rep.longrepr, str) and rep.longrepr.startswith("[XPASS(strict)]"):
        return "xpass_strict"
    if not known and item.get_closest_marker("xfail") is not None:
        return "xfail_marked_unknown"
    return "none"


def write_json(path: str, payload: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    os.replace(tmp, path)
