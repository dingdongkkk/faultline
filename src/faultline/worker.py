"""Parent side of the observation worker.

Spawns one pytest child for one test with a probe spec, enforces the
deadline (process-group termination + reap, via procs), reads the bounded
output, and converts it into contract objects. Process isolation is not a
security sandbox.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass

from .config import resolve_inside, to_rel
from .contracts import (
    FailureSignature,
    FaultlineConfig,
    HitCount,
    Observation,
    ObservationEvent,
    ObservationRun,
    ObservationTiming,
    PhaseOutcome,
    Reproduction,
    SnapshotValue,
    SourceIdentity,
)
from .execution import run_pytest


@dataclass(frozen=True)
class LineProbe:
    probe_id: str
    path: str  # repo-relative
    lines: tuple[int, ...]
    locals: tuple[str, ...]


@dataclass(frozen=True)
class FunctionProbe:
    probe_id: str
    path: str
    qualname: str
    first_line: int


Probe = LineProbe | FunctionProbe


def match_signature(baseline: FailureSignature | None, call_outcome: PhaseOutcome,
                    sig: FailureSignature | None, setup_outcome: PhaseOutcome) -> Reproduction:
    """Compare a rerun's failure with the baseline target failure."""
    if setup_outcome is PhaseOutcome.FAILED:
        return Reproduction.DIFFERENT_FAILURE
    if call_outcome is PhaseOutcome.PASSED or setup_outcome is PhaseOutcome.SKIPPED:
        return Reproduction.NOT_REPRODUCED
    if call_outcome is not PhaseOutcome.FAILED or sig is None or baseline is None:
        return Reproduction.UNKNOWN if call_outcome is PhaseOutcome.NOT_RUN else Reproduction.DIFFERENT_FAILURE
    same_loc = (sig.exception_type == baseline.exception_type and sig.crash_path == baseline.crash_path
                and sig.crash_line == baseline.crash_line and sig.test_line == baseline.test_line)
    if not same_loc:
        return Reproduction.DIFFERENT_FAILURE
    if sig.message_digest == baseline.message_digest:
        return Reproduction.REPRODUCED
    return Reproduction.PARTIAL_MATCH


@dataclass
class WorkerResult:
    run: ObservationRun
    observations: list[dict]  # raw observation dicts (evidence ids assigned by the caller)
    error: str | None
    timed_out: bool
    cancelled: bool
    stderr_tail: str


def _spec_probe(cfg: FaultlineConfig, p: Probe) -> dict:
    path = str(resolve_inside(cfg, p.path))
    if isinstance(p, LineProbe):
        return {"probe_id": p.probe_id, "kind": "line", "path": path, "lines": list(p.lines), "locals": list(p.locals)}
    return {"probe_id": p.probe_id, "kind": "function", "path": path, "qualname": p.qualname,
            "first_line": p.first_line}


def run_observation(cfg: FaultlineConfig, *, nodeid: str, probes: list[Probe], role: str,
                    baseline_signature: FailureSignature | None, timeout_s: float, fingerprint_id: str,
                    sources: list[SourceIdentity], cancel: threading.Event | None = None) -> WorkerResult:
    lim = cfg.limits
    spec = {"target": nodeid, "probes": [_spec_probe(cfg, p) for p in probes], "limits": lim.model_dump()}
    with tempfile.TemporaryDirectory(prefix="faultline-spec-") as tmp:
        spec_path = os.path.join(tmp, "spec.json")
        with open(spec_path, "w", encoding="utf-8") as f:
            json.dump(spec, f)
        raw = run_pytest(cfg, plugin="observe_plugin", targets=[nodeid], extra_env={"FAULTLINE_SPEC": spec_path},
                         timeout_s=timeout_s, out_cap=lim.run_output_max_bytes, cancel=cancel,
                         pass_config_args=True, strip_selection=True)
    p = raw.payload or {}
    phases = p.get("phases", {})

    def outcome(when):
        o = phases.get(when, {}).get("outcome")
        return PhaseOutcome(o) if o in ("passed", "failed", "skipped") else PhaseOutcome.NOT_RUN

    setup, call = outcome("setup"), outcome("call")
    sig_raw = phases.get("call", {}).get("signature") or phases.get("setup", {}).get("signature")
    sig = FailureSignature(**sig_raw) if sig_raw else None
    error = raw.output_error
    if raw.payload is None and not (raw.child.timed_out or raw.child.cancelled):
        error = error or f"worker exited with {raw.child.returncode} without output"
    if raw.payload is not None and not p.get("collected"):
        error = error or "target test was not collected in the observation run"

    if raw.payload is None:
        reproduction = Reproduction.UNKNOWN
    elif role == "comparator":
        reproduction = Reproduction.NOT_APPLICABLE
    else:
        reproduction = match_signature(baseline_signature, call, sig, setup)

    stopped = p.get("trace_stopped")
    if raw.child.timed_out:
        stopped = "timeout"
    elif raw.child.cancelled:
        stopped = "cancelled"
    elif raw.payload is None:
        stopped = "worker_crash"
    exact = bool(p.get("counts_exact", False)) and stopped is None
    hits = {k: HitCount(count=v, exact=exact) for k, v in p.get("probe_hits", {}).items()}
    # Each probe's primary event is reported even with zero hits. Any key absent
    # from probe_hits means count 0 with the run's exactness (counts_exact).
    for pr in probes:
        hits.setdefault(f"{pr.probe_id}:{'before_line' if isinstance(pr, LineProbe) else 'call'}",
                        HitCount(count=0, exact=exact))

    run = ObservationRun(
        run_id=raw.run_id, test_nodeid=nodeid, role=role, reproduction=reproduction,
        signature=sig, call_outcome=call, probe_hits=hits, counts_exact=exact, trace_stopped=stopped,
        events_captured=int(p.get("events_captured", 0)), events_dropped=int(p.get("events_dropped", 0)),
        truncation=list(p.get("truncation", [])), unsupported_detected=list(p.get("unsupported_detected", [])),
        duration_ms=raw.child.duration_ms, fingerprint_id=fingerprint_id, sources=sources,
    )
    return WorkerResult(run=run, observations=list(p.get("observations", [])), error=error,
                        timed_out=raw.child.timed_out, cancelled=raw.child.cancelled,
                        stderr_tail=raw.child.stderr_tail)


def to_observation(cfg: FaultlineConfig, raw: dict, evidence_id: str, run_id: str) -> Observation:
    """Validate one raw worker observation into the contract (untrusted input)."""
    rel = to_rel(cfg, raw["path"]) or raw["path"]
    return Observation(
        evidence_id=evidence_id, run_id=run_id, probe_id=raw["probe_id"], path=rel, line=int(raw["line"]),
        event=ObservationEvent(raw["event"]),
        timing=ObservationTiming(event_seq=raw["event_seq"], hit_ordinal=raw["hit_ordinal"], t_ns=raw["t_ns"]),
        frame_qualname=raw["frame_qualname"], call_depth=raw["call_depth"],
        values={k: SnapshotValue.model_validate(v) for k, v in raw["values"].items()},
        exception_type=raw.get("exception_type"),
    )
