"""Safe, bounded snapshots of runtime values. Standard library only.

Only *exact* built-in types are expanded (``type(v) is T``); every other
object, including subclasses of built-ins, is recorded as ``opaque`` with a
type name read through type descriptors. Nothing here calls repr/str/
format, properties, ``__len__``/``__iter__``/``__eq__``/``__lt__``/
``__hash__`` of user types, copy or pickle.

Output is plain JSON-compatible dicts matching ``contracts.SnapshotValue``.
"""

from __future__ import annotations

import math

from .common import VALUE_PATTERNS, name_is_sensitive, type_name

_SCALAR_SORTABLE = (bool, int, float, str, bytes)
_CONTAINERS = {list: "list", tuple: "tuple", dict: "dict", set: "set", frozenset: "frozenset"}


class Snapshotter:
    def __init__(self, *, max_depth=3, max_items=16, max_str=160, max_bytes_preview=32,
                 max_int_digits=40, max_bytes=4096):
        self.max_depth = max_depth
        self.max_items = max_items
        self.max_str = max_str
        self.max_bytes_preview = max_bytes_preview
        self.max_int_bits = int(max_int_digits * 3.33)  # ~bits for N decimal digits
        self.max_bytes = max_bytes
        self._budget = 0
        self._path: set[int] = set()

    def snapshot(self, value, name: str | None = None) -> dict:
        """Snapshot one value (``name`` is used for name-based redaction)."""
        self._budget = self.max_bytes
        self._path = set()
        if name is not None and name_is_sensitive(name):
            return {"kind": "redacted", "reason": "name_pattern"}
        return self._snap(value, 0)

    def _charge(self, n: int) -> bool:
        self._budget -= n
        return self._budget > 0

    def _snap(self, v, depth: int) -> dict:
        t = type(v)
        self._charge(16)
        if v is None:
            return {"kind": "none"}
        if t is bool:
            return {"kind": "bool", "value": v}
        if t is int:
            bits = v.bit_length()
            if bits > self.max_int_bits:
                return {"kind": "int", "truncated": True, "reason": f"bit_length={bits}"}
            return {"kind": "int", "value": v}
        if t is float:
            if math.isnan(v):
                return {"kind": "float", "value": "nan"}
            if math.isinf(v):
                return {"kind": "float", "value": "inf" if v > 0 else "-inf"}
            return {"kind": "float", "value": v}
        if t is str:
            probe = v[:4096]
            for pat in VALUE_PATTERNS:
                if pat.search(probe):
                    return {"kind": "redacted", "reason": "value_pattern"}
            limit = max(0, min(self.max_str, self._budget))
            out = {"kind": "str", "value": v[:limit], "length": len(v)}
            self._charge(min(len(v), limit))
            if len(v) > limit:
                out["truncated"] = True
            return out
        if t is bytes:
            n = min(self.max_bytes_preview, len(v))
            self._charge(2 * n)
            out = {"kind": "bytes", "value": v[:n].hex(), "length": len(v)}
            if len(v) > n:
                out["truncated"] = True
            return out
        kind = _CONTAINERS.get(t)
        if kind is None:
            return {"kind": "opaque", "type_name": type_name(t)}
        if id(v) in self._path:
            return {"kind": "cycle", "type_name": kind}
        length = len(v)  # exact builtin container: C-level length
        if depth >= self.max_depth:
            return {"kind": "depth_limit", "type_name": kind, "length": length}
        self._path.add(id(v))
        try:
            if kind == "dict":
                return self._dict(v, depth, length)
            seq = v
            ordered_note = None
            if kind in ("set", "frozenset"):
                seq, ordered_note = self._set_order(v)
            items, truncated = [], False
            for i, item in enumerate(seq):
                if i >= self.max_items or self._budget <= 0:
                    truncated = True
                    break
                items.append(self._snap(item, depth + 1))
            out = {"kind": kind, "length": length, "items": items}
            if truncated:
                out["truncated"] = True
            if ordered_note:
                out["reason"] = ordered_note
            return out
        finally:
            self._path.discard(id(v))

    def _dict(self, d: dict, depth: int, length: int) -> dict:
        entries, truncated = [], False
        for i, (k, val) in enumerate(d.items()):
            if i >= self.max_items or self._budget <= 0:
                truncated = True
                break
            ks = self._snap(k, depth + 1)
            if type(k) is str and name_is_sensitive(k):
                vs = {"kind": "redacted", "reason": "name_pattern"}
            else:
                vs = self._snap(val, depth + 1)
            entries.append([ks, vs])
        out = {"kind": "dict", "length": length, "entries": entries}
        if truncated:
            out["truncated"] = True
        return out

    @staticmethod
    def _set_order(s):
        """Sort only when every element is an exact primitive (no user __lt__)."""
        elems = list(s)  # iteration of an exact set calls no user code
        if all(type(e) in _SCALAR_SORTABLE for e in elems):
            try:
                return sorted(elems, key=lambda e: (type(e).__name__, e)), None
            except TypeError:  # e.g. nan comparisons are fine; mixed bytes/str keyed by type
                pass
        return elems, "iteration_order"
