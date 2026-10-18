"""Observation pytest plugin: traces only the target test's call phase.

Environment:
  FAULTLINE_OUT   JSON output path
  FAULTLINE_ROOT  repository root realpath
  FAULTLINE_SPEC  JSON probe spec path:
    {"target": nodeid,
     "probes": [{"probe_id", "kind": "line", "path": abs, "lines": [..], "locals": [..]}
              | {"probe_id", "kind": "function", "path": abs, "qualname", "first_line"}],
     "limits": {...}}

Semantics (see ARCHITECTURE.md section 5):
- ``before_line`` snapshots come from the ``line`` trace event, which fires
  before the line executes.
- Frame exit: generator/coroutine code -> exit_ambiguous; an ``exception``
  event not followed by a ``line`` event in the same frame, then ``return``
  -> unwind; otherwise -> return (value snapshotted).
- Snapshot caps stop snapshotting, not counting. Counts are exact unless
  tracing stopped early (callback budget, trace conflict), in which case
  ``counts_exact`` is false and every count is a lower bound.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

import pytest

from .common import failure_signature, type_name, write_json, xfail_class
from .snapshot import Snapshotter

_GEN_FLAGS = 0x20 | 0x80 | 0x200  # CO_GENERATOR | CO_COROUTINE | CO_ASYNC_GENERATOR
_ROOT = os.environ.get("FAULTLINE_ROOT", "")
_OUT = os.environ.get("FAULTLINE_OUT", "")
_SPEC = json.load(open(os.environ["FAULTLINE_SPEC"], encoding="utf-8")) if os.environ.get("FAULTLINE_SPEC") else {}
_LIM = _SPEC.get("limits", {})

_phases: dict[str, dict] = {}
_unsupported: list[str] = []
_audit = {"active": False, "subprocess": False}


def _audit_hook(event, args):
    if _audit["active"] and (event in ("subprocess.Popen", "os.system", "os.posix_spawn", "os.fork",
                                       "os.forkpty") or event.startswith(("os.exec", "os.spawn"))):
        _audit["subprocess"] = True


sys.addaudithook(_audit_hook)


class _Plan:
    __slots__ = ("lines", "func", "is_gen")

    def __init__(self, lines, func, is_gen):
        self.lines = lines  # line -> [probe]
        self.func = func  # probe or None
        self.is_gen = is_gen


class Tracer:
    def __init__(self, spec: dict, test_code):
        self.snap = Snapshotter(
            max_depth=_LIM.get("value_max_depth", 3), max_items=_LIM.get("value_max_items", 16),
            max_str=_LIM.get("value_max_str_chars", 160), max_bytes_preview=_LIM.get("value_max_bytes_preview", 32),
            max_int_digits=_LIM.get("value_max_int_digits", 40), max_bytes=_LIM.get("snapshot_max_bytes", 4096))
        self.max_hits = _LIM.get("max_hits_per_probe", 20)
        self.max_events = _LIM.get("max_events_per_run", 400)
        self.budget_ns = _LIM.get("callback_cpu_budget_ms", 2000) * 1_000_000
        self.by_file: dict[str, list[dict]] = {}
        for p in spec.get("probes", []):
            self.by_file.setdefault(os.path.realpath(p["path"]), []).append(p)
        self.test_code = test_code
        self.real_cache: dict[str, str] = {}
        self.plans: dict = {}
        self.hits: dict[str, int] = {}
        self.snapped_per_probe: dict[str, int] = {}
        self.observations: list[dict] = []
        self.captured = 0
        self.dropped = 0
        self.truncation: set[str] = set()
        self.pending_exc: dict[int, str] = {}
        self.cpu_ns = 0
        self.stopped: str | None = None
        self.seq = 0
        self.t0 = 0
        self.gen_seen = False
        # Bound methods are new objects on each attribute access; keep the exact
        # object handed to sys.settrace so identity checks against gettrace() work.
        self.entry = self.global_trace

    # -- planning -------------------------------------------------------------
    def plan_for(self, code):
        try:
            return self.plans[code]
        except KeyError:
            pass
        fn = code.co_filename
        real = self.real_cache.get(fn)
        if real is None:
            real = self.real_cache[fn] = os.path.realpath(fn)
        plan = None
        probes = self.by_file.get(real)
        if probes:
            code_lines = {ln for _, _, ln in code.co_lines() if ln is not None}
            lines: dict[int, list[dict]] = {}
            func = None
            for p in probes:
                if p["kind"] == "line":
                    for ln in p["lines"]:
                        if ln in code_lines:
                            lines.setdefault(ln, []).append(p)
                elif p["qualname"] == code.co_qualname and p["first_line"] == code.co_firstlineno:
                    func = p
            if lines or func:
                plan = _Plan(lines, func, bool(code.co_flags & _GEN_FLAGS))
                if plan.is_gen and func is not None:
                    self.gen_seen = True
        self.plans[code] = plan
        return plan

    # -- recording ------------------------------------------------------------
    def _depth(self, frame) -> int:
        d, f = 0, frame
        while f is not None and d < 256:
            if f.f_code is self.test_code:
                return d
            f = f.f_back
            d += 1
        return -1

    def _record(self, probe, event, frame, values_fn, exc=None):
        key = f"{probe['probe_id']}:{event}"
        n = self.hits[key] = self.hits.get(key, 0) + 1
        pid = probe["probe_id"]
        if self.snapped_per_probe.get(pid, 0) >= self.max_hits:
            self.dropped += 1
            self.truncation.add(f"max_hits_per_probe:{pid}")
            return
        if self.captured >= self.max_events:
            self.dropped += 1
            self.truncation.add("max_events_per_run")
            return
        self.snapped_per_probe[pid] = self.snapped_per_probe.get(pid, 0) + 1
        self.captured += 1
        self.seq += 1
        obs = {
            "probe_id": pid, "path": frame.f_code.co_filename, "line": frame.f_lineno, "event": event,
            "event_seq": self.seq, "hit_ordinal": n, "t_ns": time.perf_counter_ns() - self.t0,
            "frame_qualname": frame.f_code.co_qualname, "call_depth": self._depth(frame),
            "values": values_fn(),
        }
        if exc is not None:
            obs["exception_type"] = exc
        self.observations.append(obs)

    def _locals(self, frame, names):
        f_locals = frame.f_locals  # 3.12: a dict snapshot of the frame; no user code runs
        out = {}
        for name in names:
            if name in f_locals:
                out[name] = self.snap.snapshot(f_locals[name], name)
            else:
                out[name] = {"kind": "unavailable", "reason": "unbound"}
        return out

    def _account(self, start):
        self.cpu_ns += time.perf_counter_ns() - start
        if self.cpu_ns > self.budget_ns and self.stopped is None:
            self.stop("callback_budget")

    def stop(self, reason: str):
        self.stopped = reason
        sys.settrace(None)

    # -- trace functions --------------------------------------------------------
    def global_trace(self, frame, event, arg):
        if self.stopped:
            return None
        start = time.perf_counter_ns()
        plan = self.plan_for(frame.f_code)
        if plan is None:
            self._account(start)
            return None
        if plan.func is not None:
            p = plan.func
            code = frame.f_code
            nargs = code.co_argcount + code.co_kwonlyargcount + bool(code.co_flags & 0x04) + bool(code.co_flags & 0x08)
            self._record(p, "call", frame, lambda: self._locals(frame, code.co_varnames[:nargs]))
        self._account(start)
        return self.local_trace

    def local_trace(self, frame, event, arg):
        if self.stopped:
            frame.f_trace = None
            return None
        start = time.perf_counter_ns()
        plan = self.plans.get(frame.f_code)
        if plan is None:
            return None
        fid = id(frame)
        if event == "line":
            self.pending_exc.pop(fid, None)  # execution continues here: exception was handled
            for p in plan.lines.get(frame.f_lineno, ()):
                self._record(p, "before_line", frame, lambda p=p: self._locals(frame, p.get("locals", [])))
        elif event == "exception":
            name = type_name(arg[0])
            self.pending_exc[fid] = name
            if plan.func is not None:
                self._record(plan.func, "exception", frame, dict, exc=name)
        elif event == "return":
            exc = self.pending_exc.pop(fid, None)
            if plan.func is not None:
                if plan.is_gen:
                    self._record(plan.func, "exit_ambiguous", frame, dict)
                elif exc is not None:
                    self._record(plan.func, "unwind", frame, dict, exc=exc)
                else:
                    self._record(plan.func, "return", frame, lambda: {"<return>": self.snap.snapshot(arg)})
        self._account(start)
        return self.local_trace


_tracer: Tracer | None = None


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtest_call(item):
    global _tracer
    if item.nodeid != _SPEC.get("target") or not _SPEC.get("probes"):
        return (yield)
    test_code = getattr(getattr(item, "obj", None), "__code__", None)
    tracer = _tracer = Tracer(_SPEC, test_code)
    threads_before = {t.ident for t in threading.enumerate()}
    if sys.gettrace() is not None:
        tracer.stopped = "trace_conflict"
        _unsupported.append("trace_conflict")
        return (yield)
    _audit["active"] = True
    tracer.t0 = time.perf_counter_ns()
    sys.settrace(tracer.entry)
    try:
        return (yield)
    finally:
        current = sys.gettrace()
        sys.settrace(None)
        _audit["active"] = False
        if tracer.stopped is None and current is not tracer.entry:
            tracer.stopped = "trace_conflict"
        if tracer.stopped == "trace_conflict":
            _unsupported.append("trace_conflict")
        if {t.ident for t in threading.enumerate()} - threads_before:
            _unsupported.append("threads_started")


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    rep = yield
    if item.nodeid == _SPEC.get("target"):
        entry = {"outcome": rep.outcome, "xfail": xfail_class(item, call, rep)}
        if rep.failed:
            try:
                entry["signature"] = failure_signature(item, call, rep, _ROOT)
            except Exception as e:  # noqa: BLE001
                entry["signature"] = {"message_excerpt": f"<signature error {type(e).__name__}>"}
        _phases[rep.when] = entry
    return rep


def pytest_unconfigure(config):
    t = _tracer
    unsupported = set(_unsupported)
    if _audit["subprocess"]:
        unsupported.add("subprocess_spawned")
    if t is not None and t.gen_seen:
        unsupported.add("generator_or_coroutine_frame")
    out = {
        "target": _SPEC.get("target"),
        "collected": bool(_phases),
        "phases": _phases,
        "probe_hits": t.hits if t else {},
        "counts_exact": (t.stopped is None) if t else True,
        "trace_stopped": t.stopped if t else None,
        "observations": t.observations if t else [],
        "events_captured": t.captured if t else 0,
        "events_dropped": t.dropped if t else 0,
        "truncation": sorted(t.truncation) if t else [],
        "unsupported_detected": sorted(unsupported),
    }
    cap = int(_LIM.get("run_output_max_bytes", 512 * 1024))
    while len(json.dumps(out, separators=(",", ":"))) > cap and out["observations"]:
        drop = max(1, len(out["observations"]) // 4)
        del out["observations"][-drop:]
        out["truncation"] = sorted(set(out["truncation"]) | {"run_output_cap"})
    if _OUT:
        write_json(_OUT, out)
