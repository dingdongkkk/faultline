"""Run the target pytest suite in a supervised child process and turn the
probe plugin's raw output into TestRecords and per-phase coverage.

Coverage and outcomes come from the same child process and the same run.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import procs
from .config import to_rel, without_selection_args
from .contracts import (
    ExclusionReason,
    FailureSignature,
    FaultlineConfig,
    PhaseOutcome,
    TestClass,
    TestRecord,
    XfailClass,
)

_PROBE_SRC = Path(__file__).resolve().parent / "_probe"
_probe_lock = threading.Lock()
_probe_dir: Path | None = None


def probe_path() -> Path:
    """Directory to prepend to the child's PYTHONPATH.

    The probe package is copied out as ``faultline_probe`` so the target
    interpreter never imports Faultline itself or its dependencies.
    """
    global _probe_dir
    with _probe_lock:
        if _probe_dir is None or not (_probe_dir / "faultline_probe").is_dir():
            d = Path(tempfile.mkdtemp(prefix="faultline-probe-"))
            shutil.copytree(_PROBE_SRC, d / "faultline_probe",
                            ignore=shutil.ignore_patterns("__pycache__"))
            _probe_dir = d
        return _probe_dir


def child_env(cfg: FaultlineConfig, extra: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    for k in ("COVERAGE_PROCESS_START", "COVERAGE_CORE", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        env.pop(k, None)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(probe_path()), env.get("PYTHONPATH", "")]))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # Same hash seed in every child (baseline, observation, patch check): set/dict-diff ordering in
    # failure messages and in the code under test is then consistent across reruns.
    env["PYTHONHASHSEED"] = "0"
    env["FAULTLINE_ROOT"] = cfg.repo_root
    env.update(extra)
    return env


@dataclass
class RawRun:
    run_id: str
    child: procs.ChildResult
    payload: dict | None  # None if the plugin produced no output
    output_error: str | None = None


def run_pytest(
    cfg: FaultlineConfig,
    *,
    plugin: str,
    targets: list[str],
    extra_env: dict[str, str],
    timeout_s: float,
    out_cap: int,
    cancel: threading.Event | None = None,
    pass_config_args: bool = True,
    strip_selection: bool = False,
) -> RawRun:
    run_id = "R" + uuid.uuid4().hex[:8]
    with tempfile.TemporaryDirectory(prefix="faultline-run-") as tmp:
        out = os.path.join(tmp, "out.json")
        env = child_env(cfg, {"FAULTLINE_OUT": out, "FAULTLINE_COV_DATA": os.path.join(tmp, "cov.db"), **extra_env})
        cmd = [cfg.python, "-m", "pytest", "-p", f"faultline_probe.{plugin}", "-p", "no:cacheprovider",
               "-q", "--tb=short", "-o", "console_output_style=classic"]
        if pass_config_args:
            cmd += without_selection_args(cfg.pytest_args) if strip_selection else list(cfg.pytest_args)
        cmd += ["--", *targets] if targets else []
        child = procs.run_child(cmd, cwd=cfg.repo_root, env=env, timeout_s=timeout_s,
                                grace_s=cfg.limits.terminate_grace_seconds,
                                tail_bytes=cfg.limits.diagnostic_output_max_bytes, cancel=cancel)
        payload, err = None, None
        if os.path.exists(out):
            size = os.path.getsize(out)
            if size > out_cap:
                err = f"probe output {size} bytes exceeds cap {out_cap}"
            else:
                try:
                    with open(out, encoding="utf-8") as f:
                        payload = json.load(f)
                except (OSError, ValueError) as e:
                    err = f"unreadable probe output: {e}"
        return RawRun(run_id=run_id, child=child, payload=payload, output_error=err)


# --------------------------------------------------------------------------
# Baseline parsing
# --------------------------------------------------------------------------


@dataclass
class Baseline:
    run_id: str
    records: dict[str, TestRecord]
    # rel path -> line -> set of (nodeid, phase); nodeid "" for unattributed
    coverage: dict[str, dict[int, set[tuple[str, str]]]]
    unsupported: list[str]
    collect_errors: list[dict]
    duplicate_reports: list[str]
    trace_conflicts: list[tuple[str, str]]
    exitstatus: int | None
    duration_ms: int
    timed_out: bool
    cancelled: bool
    error: str | None
    stdout_tail: str
    stderr_tail: str
    outside_root_files: int = 0
    notes: list[str] = field(default_factory=list)


def run_baseline(cfg: FaultlineConfig, target: str, timeout_s: float,
                 cancel: threading.Event | None = None) -> Baseline:
    raw = run_pytest(cfg, plugin="cov_plugin", targets=[], extra_env={"FAULTLINE_COVERAGE": "1"},
                     timeout_s=timeout_s, out_cap=cfg.limits.baseline_output_max_bytes, cancel=cancel)
    return parse_baseline(cfg, raw, target)


def _phase(outcome: str | None) -> PhaseOutcome:
    return PhaseOutcome(outcome) if outcome in ("passed", "failed", "skipped") else PhaseOutcome.NOT_RUN


def classify(nodeid: str, phases: dict[str, dict], target: str, duplicate: bool,
             conflict: bool) -> TestRecord:
    setup = _phase(phases.get("setup", {}).get("outcome"))
    call = _phase(phases.get("call", {}).get("outcome"))
    teardown = _phase(phases.get("teardown", {}).get("outcome"))
    xf = XfailClass.NONE
    for when in ("setup", "call", "teardown"):
        c = phases.get(when, {}).get("xfail", "none")
        if c != "none":
            xf = XfailClass(c)
            break
    sig = phases.get("call", {}).get("signature")
    signature = FailureSignature(**sig) if sig else None

    exclusion: ExclusionReason | None = None
    if duplicate:
        exclusion = ExclusionReason.DUPLICATE_REPORT
    elif conflict:
        exclusion = ExclusionReason.TRACE_CONFLICT
    elif xf is not XfailClass.NONE:
        exclusion = ExclusionReason(xf.value)
    elif PhaseOutcome.SKIPPED in (setup, call):
        exclusion = ExclusionReason.SKIPPED
    elif setup is PhaseOutcome.FAILED:
        exclusion = ExclusionReason.SETUP_FAILED
    elif teardown is PhaseOutcome.FAILED:
        exclusion = ExclusionReason.TEARDOWN_FAILED
    elif PhaseOutcome.NOT_RUN in (setup, call, teardown):
        exclusion = ExclusionReason.INCOMPLETE_PHASES
    elif call is PhaseOutcome.FAILED and nodeid != target:
        exclusion = ExclusionReason.UNRELATED_FAILURE

    if exclusion is not None:
        klass = TestClass.EXCLUDED
    elif call is PhaseOutcome.FAILED:
        klass = TestClass.TARGET_FAILING
    else:
        klass = TestClass.PASSING
    return TestRecord(nodeid=nodeid, setup=setup, call=call, teardown=teardown, xfail=xf,
                      klass=klass, exclusion=exclusion, signature=signature)


def parse_baseline(cfg: FaultlineConfig, raw: RawRun, target: str) -> Baseline:
    p = raw.payload or {}
    error = raw.output_error
    if raw.payload is None and error is None and not (raw.child.timed_out or raw.child.cancelled):
        error = f"pytest exited with {raw.child.returncode} without probe output"
    if p.get("coverage_error"):
        error = f"coverage: {p['coverage_error']}"

    grouped: dict[str, dict[str, dict]] = {}
    duplicates: set[str] = set()
    for r in p.get("reports", []):
        phases = grouped.setdefault(r["nodeid"], {})
        if r["when"] in phases:
            duplicates.add(r["nodeid"])
        phases[r["when"]] = r
    conflicts = [(n, ph) for n, ph in p.get("trace_conflicts", [])]
    conflicted = {n for n, _ in conflicts}
    records = {n: classify(n, ph, target, n in duplicates, n in conflicted) for n, ph in grouped.items()}

    coverage: dict[str, dict[int, set[tuple[str, str]]]] = {}
    outside = 0
    for abs_path, by_ctx in (p.get("coverage") or {}).items():
        rel = to_rel(cfg, abs_path)
        if rel is None:
            outside += 1
            continue
        lines = coverage.setdefault(rel, {})
        for ctx, nums in by_ctx.items():
            nodeid, _, phase = ctx.rpartition("|") if ctx else ("", "", "")
            key = (nodeid, phase) if phase in ("setup", "call", "teardown") else ("", "")
            for n in nums:
                lines.setdefault(n, set()).add(key)

    unsupported = list(p.get("unsupported", []))
    if duplicates:
        unsupported.append("duplicate_phase_reports")
    return Baseline(
        run_id=raw.run_id, records=records, coverage=coverage, unsupported=unsupported,
        collect_errors=p.get("collect_errors", []), duplicate_reports=sorted(duplicates),
        trace_conflicts=conflicts, exitstatus=p.get("exitstatus"), duration_ms=raw.child.duration_ms,
        timed_out=raw.child.timed_out, cancelled=raw.child.cancelled, error=error,
        stdout_tail=raw.child.stdout_tail, stderr_tail=raw.child.stderr_tail, outside_root_files=outside,
    )


def python_for_tests() -> str:
    """Interpreter used by Faultline's own tests for fixture projects."""
    return sys.executable
