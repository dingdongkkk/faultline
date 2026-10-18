"""Evidence storage with provenance, retention and freshness.

Layout: <state_dir>/<repo-hash>/inv/<investigation_id>/{manifest.json, items/<evidence_id>.json}
The store lives outside the repository. Cache reuse is disabled: nothing
here is ever used to skip a run.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import fingerprint as fpmod
from .config import resolve_inside, state_dir
from .contracts import FaultlineConfig, Freshness

_ID = re.compile(r"^[A-Za-z0-9_]{1,40}$")
RUNTIME_KINDS = {"observation", "run", "comparison", "ranking", "tie_group", "patch_run", "baseline"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceStore:
    def __init__(self, cfg: FaultlineConfig):
        self.cfg = cfg
        self.root = state_dir(cfg) / "inv"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _dir(self, inv_id: str) -> Path:
        if not _ID.match(inv_id):
            raise KeyError(f"invalid investigation id: {inv_id!r}")
        return self.root / inv_id

    # -- writing -------------------------------------------------------------
    def create(self, inv_id: str, manifest: dict) -> None:
        d = self._dir(inv_id)
        (d / "items").mkdir(parents=True, exist_ok=False, mode=0o700)
        manifest = dict(manifest)
        manifest["created_at"] = _now().isoformat(timespec="seconds")
        manifest["expires_at"] = (_now() + timedelta(hours=self.cfg.limits.evidence_retention_hours)).isoformat(
            timespec="seconds")
        manifest["stored_bytes"] = 0
        self._write(d / "manifest.json", manifest)

    def update_manifest(self, inv_id: str, **fields) -> None:
        m = self.load_manifest(inv_id)
        m.update(fields)
        self._write(self._dir(inv_id) / "manifest.json", m)

    def put(self, inv_id: str, evidence_id: str, kind: str, payload: dict, *,
            sources: list[dict], truncated_at_capture: bool, fingerprint_id: str) -> bool:
        """Persist one item. Returns False (not retained) if the store cap is hit."""
        if not _ID.match(evidence_id):
            raise KeyError(f"invalid evidence id: {evidence_id!r}")
        item = {"evidence_id": evidence_id, "kind": kind, "fingerprint_id": fingerprint_id,
                "sources": sources, "truncated_at_capture": truncated_at_capture,
                "captured_at": _now().isoformat(timespec="seconds"), "payload": payload}
        data = json.dumps(item, separators=(",", ":")).encode()
        m = self.load_manifest(inv_id)
        if m["stored_bytes"] + len(data) > self.cfg.limits.investigation_store_max_bytes:
            return False
        path = self._dir(inv_id) / "items" / f"{evidence_id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        m["stored_bytes"] += len(data)
        self._write(self._dir(inv_id) / "manifest.json", m)
        return True

    @staticmethod
    def _write(path: Path, obj: dict) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, separators=(",", ":")))
        os.replace(tmp, path)

    # -- reading -------------------------------------------------------------
    def load_manifest(self, inv_id: str) -> dict:
        p = self._dir(inv_id) / "manifest.json"
        if not p.exists():
            raise KeyError(f"unknown investigation: {inv_id}")
        return json.loads(p.read_text())

    def is_expired(self, manifest: dict) -> bool:
        return manifest.get("expired", False) or datetime.fromisoformat(manifest["expires_at"]) <= _now()

    def expire(self, inv_id: str) -> None:
        """Delete payloads, keep a tombstone manifest."""
        d = self._dir(inv_id)
        m = self.load_manifest(inv_id)
        shutil.rmtree(d / "items", ignore_errors=True)
        tomb = {k: m.get(k) for k in ("investigation_id", "target", "created_at", "expires_at")}
        tomb["fingerprint_id"] = (m.get("fingerprint") or {}).get("fingerprint_id")
        tomb["expired"] = True
        tomb["stored_bytes"] = 0
        self._write(d / "manifest.json", tomb)

    def sweep(self) -> int:
        n = 0
        for d in self.root.iterdir():
            try:
                m = self.load_manifest(d.name)
            except (KeyError, ValueError, OSError):
                continue
            if not m.get("expired") and self.is_expired(m):
                self.expire(d.name)
                n += 1
        return n

    def get(self, inv_id: str, evidence_id: str) -> tuple[dict | None, dict]:
        """Return (item or None if expired, manifest). Raises KeyError if unknown."""
        m = self.load_manifest(inv_id)
        if self.is_expired(m):
            if not m.get("expired"):
                self.expire(inv_id)
                m = self.load_manifest(inv_id)
            return None, m
        if not _ID.match(evidence_id):
            raise KeyError(f"invalid evidence id: {evidence_id!r}")
        p = self._dir(inv_id) / "items" / f"{evidence_id}.json"
        if not p.exists():
            raise KeyError(f"unknown evidence id: {evidence_id}")
        return json.loads(p.read_text()), m


def freshness(cfg: FaultlineConfig, manifest: dict, item: dict,
              current: fpmod.Snapshot) -> tuple[Freshness, list[str], list[str]]:
    """Freshness of one item against the current checkout.

    Runtime evidence depends on everything that executed, so it is compared
    against the *full* stored input fingerprint (all files + environment).
    Source excerpts depend on their referenced sources plus the environment
    components that change how source maps to lines (none) - so only the
    referenced files are compared for them, plus a full component check.
    """
    stored_fp = manifest["fingerprint"]
    d = fpmod.diff(manifest["files"], manifest["components"], stored_fp["partial"], current)
    if stored_fp["partial"] or current.fp.partial:
        return Freshness.UNKNOWN, (d.changed + d.added + d.deleted)[:20], d.components
    if item["kind"] in RUNTIME_KINDS:
        paths = d.changed + d.added + d.deleted
    else:
        paths = []
        for s in item.get("sources", []):
            rel = s["path"]
            try:
                now = current.files.get(rel) or (resolve_inside(cfg, rel).exists() and "present-untracked")
            except Exception:  # noqa: BLE001
                now = None
            if now != s["sha256"]:
                paths.append(rel)
    if paths or d.components:
        return Freshness.STALE, paths[:20], d.components
    return Freshness.FRESH, [], []


def expand(cfg: FaultlineConfig, store: EvidenceStore, investigation_id: str, evidence_id: str,
           budget_tokens: int = 1000, cursor: str | None = None):
    """Return retained evidence without rerunning anything."""
    from .budget import Packer, serialized_size
    from .contracts import ExpandResponse

    lim = cfg.limits
    budget_tokens = max(lim.expand_budget_tokens_min, min(budget_tokens, lim.budget_tokens_cap))
    start = _now()
    item, manifest = store.get(investigation_id, evidence_id)
    base = {
        "investigation_id": investigation_id, "evidence_id": evidence_id, "freshness": Freshness.EXPIRED.value,
        "stale_paths": [], "stale_components": [], "irrecoverably_truncated": False, "content": None,
        "metrics": {"response_bytes": 0, "response_tokens_estimate": 0, "budget_tokens": budget_tokens,
                    "wall_ms": 0, "rounds": 0, "planner_retries": 0, "planner_fallbacks": 0},
    }
    if item is not None:
        current = fpmod.compute(cfg)
        fr, paths, comps = freshness(cfg, manifest, item, current)
        base.update(kind=item["kind"], freshness=fr.value, stale_paths=paths, stale_components=comps,
                    irrecoverably_truncated=bool(item.get("truncated_at_capture")))
        payload = item["payload"]
        offset = 0
        if cursor is not None:
            if not cursor.startswith("o:") or not cursor[2:].isdigit():
                raise KeyError(f"invalid cursor: {cursor!r}")
            offset = int(cursor[2:])
        whole = dict(base, content=payload)
        if offset == 0 and serialized_size(ExpandResponse, dict(whole, metrics=dict(
                base["metrics"], response_bytes=budget_tokens * 3, response_tokens_estimate=budget_tokens,
                wall_ms=10**8))) \
                <= budget_tokens * 3:
            base = whole
        else:
            text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
            # Largest chunk that fits: binary search on length.
            lo, hi = 0, len(text) - offset
            def fits(n):
                d = dict(base, content={"chunk": text[offset:offset + n], "offset": offset, "total_bytes": len(text)},
                         next_cursor=f"o:{offset + n}" if offset + n < len(text) else None)
                d["metrics"] = dict(d["metrics"], response_bytes=budget_tokens * 3,
                                    response_tokens_estimate=budget_tokens, wall_ms=10**8)
                return serialized_size(ExpandResponse, d) <= budget_tokens * 3
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if fits(mid):
                    lo = mid
                else:
                    hi = mid - 1
            if lo == 0 and offset < len(text):
                raise ValueError("budget too small to return any content")
            base = dict(base, content={"chunk": text[offset:offset + lo], "offset": offset, "total_bytes": len(text)},
                        next_cursor=f"o:{offset + lo}" if offset + lo < len(text) else None)
    base["metrics"]["wall_ms"] = int((_now() - start).total_seconds() * 1000)
    return Packer(ExpandResponse, base, budget_tokens, reserve=0).finalize()


def baseline_manifest(investigation_id: str, target: str, baseline, snapshot: fpmod.Snapshot,
                      supported: bool) -> dict:
    """Manifest content needed later by expand_evidence and check_patch."""
    tests = {n: {"klass": r.klass.value, "call": r.call.value,
                 "exclusion": r.exclusion.value if r.exclusion else None}
             for n, r in baseline.records.items()}
    file_cov: dict[str, dict] = {}
    for path, lines in baseline.coverage.items():
        info = file_cov.setdefault(path, {"call": set(), "setup_teardown": False, "unattributed": False})
        for ctxs in lines.values():
            for n, ph in ctxs:
                if ph == "call":
                    info["call"].add(n)
                elif ph in ("setup", "teardown"):
                    info["setup_teardown"] = True
                else:
                    info["unattributed"] = True
    for info in file_cov.values():
        info["call"] = sorted(info["call"])
    return {
        "investigation_id": investigation_id, "target": target, "baseline_run_id": baseline.run_id,
        "baseline_supported": supported, "fingerprint": snapshot.fp.model_dump(), "files": snapshot.files,
        "components": snapshot.components, "tests": tests, "file_cov": file_cov,
    }
