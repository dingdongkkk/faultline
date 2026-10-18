"""Deterministic response packing against a token estimate and byte cap.

Size is measured on the *complete* compact serialized response
(``exclude_none``), wrappers, limitations, omissions and metrics included.
Estimate = ceil(bytes / 3) ("utf8_bytes_div_3"); hard cap = 3 * budget bytes.

While packing, metrics hold their maximum possible values (cap bytes /
budget tokens), so the final, smaller numbers can only shrink the payload.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel

BYTES_PER_TOKEN = 3
MAX_HANDLES = 3  # expandable IDs listed per omission kind; the count is always exact
TOP_ROWS_FIRST = 5  # tied rows listed before measured values; the rest follow if they fit
# Evaluation bookkeeping the agent rarely needs; reported as one omission kind.
AUDIT_KINDS = {"run", "planner_round", "observation_in_comparison"}


def serialized_size(model_cls: type[BaseModel], d: dict) -> int:
    return len(model_cls.model_validate(d).model_dump_json(exclude_none=True).encode())


def estimate_tokens(n_bytes: int) -> int:
    return -(-n_bytes // BYTES_PER_TOKEN)


class BudgetError(ValueError):
    pass


class Packer:
    def __init__(self, model_cls: type[BaseModel], base: dict, budget_tokens: int, reserve: int | None = None,
                 compactors: list[Callable[[dict], None]] | None = None):
        self.model_cls = model_cls
        self.budget = budget_tokens
        self.cap = budget_tokens * BYTES_PER_TOKEN
        self.d = copy.deepcopy(base)
        self.d["metrics"]["response_bytes"] = self.cap
        self.d["metrics"]["response_tokens_estimate"] = budget_tokens
        self.pending_omissions: list[dict] = []
        self.stack: list[tuple[Callable[[dict], None], str, str]] = []  # (undo, omission kind, handle)
        # Space kept free for the omission records added at the end.
        self.reserve = min(400, self.cap // 8) if reserve is None else reserve
        # Last-resort, lossy-but-labelled shrinking of mandatory fields, applied in order.
        self.compactors = list(compactors or [])
        self.compacted: list[str] = []
        while self.size() > self.cap - self.reserve and self.compactors:
            self._compact_once()
        if self.size() > self.cap - self.reserve:
            raise BudgetError(f"skeleton ({self.size()} B) does not fit budget {budget_tokens} tokens")

    def size(self) -> int:
        return serialized_size(self.model_cls, self.d)

    def try_add(self, apply: Callable[[dict], None], undo: Callable[[dict], None],
                kind: str = "item", handle: str = "") -> bool:
        apply(self.d)
        if self.size() <= self.cap - self.reserve:
            self.stack.append((undo, kind, handle))
            return True
        undo(self.d)
        return False

    def _compact_once(self) -> None:
        fn = self.compactors.pop(0)
        fn(self.d)
        self.compacted.append(getattr(fn, "__name__", "compactor"))
        self.d["metrics"]["compacted"] = list(self.compacted)

    def omit(self, kind: str, count: int, evidence_ids: list[str]) -> None:
        if count <= 0:
            return
        if kind in AUDIT_KINDS:
            kind = "audit_records"
        for o in self.pending_omissions:
            if o["kind"] == kind:
                o["count"] += count
                o["evidence_ids"] = list(dict.fromkeys(o["evidence_ids"] + evidence_ids))[:MAX_HANDLES]
                return
        self.pending_omissions.append({"kind": kind, "count": count, "evidence_ids": list(evidence_ids)[:MAX_HANDLES]})

    def finalize(self) -> BaseModel:
        has_omissions = "omissions" in self.model_cls.model_fields
        if not has_omissions and self.pending_omissions:
            raise BudgetError(f"{self.model_cls.__name__} cannot carry omissions")
        while True:
            if has_omissions:
                self.d["omissions"] = [dict(o) for o in self.pending_omissions]
            if self.size() <= self.cap:
                break
            if self.stack:  # drop the lowest-priority packed item; it becomes an omission
                undo, kind, handle = self.stack.pop()
                undo(self.d)
                self.omit(kind, 1, [handle] if handle else [])
                continue
            if self.compactors:
                self._compact_once()
                continue
            if any(len(o["evidence_ids"]) > 1 for o in self.pending_omissions):
                for o in self.pending_omissions:  # shorten handle lists
                    o["evidence_ids"] = o["evidence_ids"][:1]
                continue
            raise BudgetError("response skeleton plus omissions exceed the budget")
        m = self.d["metrics"]
        for _ in range(4):  # fixed point: metrics describe the final payload, metrics included
            n = self.size()
            m["response_bytes"], m["response_tokens_estimate"] = n, estimate_tokens(n)
        model = self.model_cls.model_validate(self.d)
        final = len(model.model_dump_json(exclude_none=True).encode())
        assert final == m["response_bytes"] and final <= self.cap, (final, self.cap)
        return model


# --------------------------------------------------------------------------
# investigate_failure packing
# --------------------------------------------------------------------------


@dataclass
class InvestigationParts:
    base: dict  # every scalar/skeleton field; lists below start empty in base
    groups: list[tuple[dict, list[dict]]] = field(default_factory=list)  # (tie group, its locations) by rank
    comparisons: list[dict] = field(default_factory=list)
    target_observations: list[dict] = field(default_factory=list)
    other_observations: list[dict] = field(default_factory=list)
    excerpts: list[dict] = field(default_factory=list)  # [0] = top excerpt
    runs: list[dict] = field(default_factory=list)
    planner_rounds: list[dict] = field(default_factory=list)
    pre_omissions: list[dict] = field(default_factory=list)  # decided by the caller (e.g. dedup)


def _append(key: str, item: dict):
    return (lambda d: d[key].append(item)), (lambda d: d[key].pop())


def _add_group(p: Packer, group: dict, locs: list[dict], limit: int | None = None) -> dict | None:
    """Add a tie group header and up to ``limit`` member rows. Returns the group entry
    (for a later ``_extend_group``) or None if even the header did not fit."""
    ranking = p.d["ranking"]
    g = dict(group, shown=0, member_location_ids=[])
    if not p.try_add(lambda d: ranking["tie_groups"].append(g), lambda d: ranking["tie_groups"].pop(),
                     "tie_group", group["tie_group"]):
        p.omit("tie_group", group["size"], [group["tie_group"]])
        return None
    _extend_group(p, g, locs[: limit if limit is not None else len(locs)])
    return g


def _extend_group(p: Packer, g: dict, locs: list[dict]) -> None:
    ranking = p.d["ranking"]
    for loc in locs:
        def apply(d, loc=loc):
            ranking["locations"].append(loc)
            g["member_location_ids"].append(loc["location_id"])
            g["shown"] += 1

        def undo(d):
            ranking["locations"].pop()
            g["member_location_ids"].pop()
            g["shown"] -= 1

        if not p.try_add(apply, undo, "tie_group_members", g["tie_group"]):
            break


def _close_group(p: Packer, g: dict | None, size: int) -> None:
    if g is not None and g["shown"] < size:
        p.omit("tie_group_members", size - g["shown"], [g["tie_group"]])


def _add_each(p: Packer, key: str, items: list[dict], kind: str, id_key: str) -> None:
    for i, item in enumerate(items):
        handle = str(item[id_key]) if kind != "planner_round" else f"PR{item[id_key]}"
        if not p.try_add(*_append(key, item), kind, handle):
            rest = items[i:]
            ids = [f"PR{x[id_key]}" if kind == "planner_round" else str(x[id_key]) for x in rest]
            p.omit(kind, len(rest), ids[:MAX_HANDLES])
            return


def shorten_limitation_details(d: dict) -> None:
    for lim in d.get("limitations", []):
        if len(lim["detail"]) > 60:
            lim["detail"] = lim["detail"][:57] + "..."


def drop_message_excerpt(d: dict) -> None:
    if d.get("reproduced") and d["reproduced"].get("signature"):
        d["reproduced"]["signature"].pop("message_excerpt", None)


def shorten_unresolved(d: dict) -> None:
    d["unresolved"] = [u[:80] for u in d.get("unresolved", [])][:3]


INVESTIGATION_COMPACTORS = [shorten_limitation_details, drop_message_excerpt, shorten_unresolved]


def _aligned_priority(c: dict) -> list[dict]:
    """First divergence, other differences, failing-only values, then the rest."""
    first = c.get("first_divergence_index")
    rank = {"differs": 1, "missing": 2, "incomparable": 3}
    entries = list(enumerate(c["aligned"]))
    entries.sort(key=lambda ie: (0 if ie[0] == first else rank.get(ie[1]["relation"], 4), ie[0]))
    return [e for _, e in entries]


def shrink_value(v: dict | None, depth: int = 0) -> dict | None:
    """Response-only compaction of a SnapshotValue: <=3 items, depth <=2, strings <=60 chars.
    The full value stays in the evidence store; shrunk values are marked truncated."""
    if v is None:
        return None
    out = dict(v)
    if isinstance(out.get("value"), str) and len(out["value"]) > 60:
        out["value"], out["truncated"] = out["value"][:60], True
    for key in ("items", "entries"):
        seq = out.get(key)
        if seq is None:
            continue
        if depth >= 1:
            out.pop(key)
            out["truncated"] = True
            continue
        if len(seq) > 3:
            seq, out["truncated"] = seq[:3], True
        if key == "items":
            out[key] = [shrink_value(x, depth + 1) for x in seq]
        else:
            out[key] = [[shrink_value(a, depth + 1), shrink_value(b, depth + 1)] for a, b in seq]
    return out


def _add_comparison(p: Packer, c: dict) -> None:
    if p.try_add(*_append("comparisons", c), "comparison", c["evidence_id"]):
        return
    ordered = [dict(a, failing=shrink_value(a.get("failing")), passing=shrink_value(a.get("passing")))
               for a in _aligned_priority(c)]
    for a in ordered:
        for side in ("failing", "passing"):
            if a.get(side) is None:
                a.pop(side, None)
    for k in range(len(ordered), 0, -1):  # largest prefix that fits (values already shrunk)
        part = dict(c, aligned=ordered[:k])
        part["first_divergence_index"] = next(
            (i for i, a in enumerate(part["aligned"])
             if a["relation"] == "differs" and a["alignment"] in ("unambiguous", "ordinal")), None)
        if part["first_divergence_index"] is None:
            part.pop("first_divergence_index")
        if p.try_add(*_append("comparisons", part), "comparison", c["evidence_id"]):
            p.omit("comparison_values", len(ordered) - k, [c["evidence_id"]])
            return
    p.omit("comparison", 1, [c["evidence_id"]])


def pack_investigation(model_cls: type[BaseModel], parts: InvestigationParts, budget_tokens: int) -> BaseModel:
    p = Packer(model_cls, parts.base, budget_tokens, compactors=INVESTIGATION_COMPACTORS)
    for o in parts.pre_omissions:
        p.omit(o["kind"], o["count"], o["evidence_ids"])
    ranked = p.d.get("ranking") is not None and parts.groups
    top = None
    if ranked:  # at most TOP_ROWS_FIRST tied rows before the measured values
        top = _add_group(p, parts.groups[0][0], parts.groups[0][1], limit=TOP_ROWS_FIRST)
    for c in parts.comparisons:
        _add_comparison(p, c)
    _add_each(p, "excerpts", parts.excerpts[:1], "excerpt", "excerpt_id")
    _add_each(p, "observations", parts.target_observations, "observation", "evidence_id")
    if top is not None:  # then the rest of the top tie group
        _extend_group(p, top, parts.groups[0][1][top["shown"]:])
        _close_group(p, top, parts.groups[0][0]["size"])
    for g, locs in parts.groups[1:] if ranked else []:
        if g["rank"] > 2 and parts.excerpts[1:]:
            _add_each(p, "excerpts", parts.excerpts[1:], "excerpt", "excerpt_id")
            parts.excerpts = parts.excerpts[:1]
        _close_group(p, _add_group(p, g, locs), g["size"])
    _add_each(p, "excerpts", parts.excerpts[1:], "excerpt", "excerpt_id")
    _add_each(p, "observations", parts.other_observations, "observation", "evidence_id")
    _add_each(p, "planner_rounds", parts.planner_rounds, "planner_round", "round")
    _add_each(p, "observation_runs", parts.runs, "run", "run_id")
    return p.finalize()
