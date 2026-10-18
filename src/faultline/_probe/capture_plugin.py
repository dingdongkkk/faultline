"""Single-test failure capture and bounded local-value history. Target stdlib + pytest."""
import collections
import fnmatch
import json
import os
import sys
import time

import pytest

from .common import failure_signature, redact_text, write_json, xfail_class
from .snapshot import Snapshotter

ROOT = os.environ['FAULTLINE_ROOT']
SPEC = json.loads(os.environ['FAULTLINE_CAPTURE_SPEC'])
REPORTS = []
LIMITS = set(['main_thread_call_phase_only', 'local_changes_are_not_causal_proof',
              'opaque_and_truncated_values_may_hide_changes'])
TRACE = None


class History:
    def __init__(self):
        self.events = collections.deque(maxlen=400)
        self.frames = {}
        self.sequence = 0
        self.calls = 0
        self.cpu = 0
        self.serial = 0
        self.snap = Snapshotter(max_depth=2, max_items=8, max_str=80, max_bytes=512)
        self.entry = self.trace

    def values(self, frame):
        names = list(frame.f_code.co_varnames) + list(frame.f_code.co_freevars)
        focus = SPEC.get('variable')
        if focus:
            names = [focus] + [n for n in names if n != focus]
        if len(names) > 16:
            LIMITS.add('locals_cap')
        return {n: self.snap.snapshot(frame.f_locals[n], n) for n in names[:16] if n in frame.f_locals}

    def trace(self, frame, event, arg):
        start = time.perf_counter_ns()
        try:
            self.calls += 1
            if self.calls > 100000 or self.cpu > 1_000_000_000:
                LIMITS.add('trace_budget_exhausted')
                sys.settrace(None)
                return None
            fid = id(frame)
            if event == 'call':
                filename = frame.f_code.co_filename
                if not filename.endswith('.py'):
                    return None
                path = os.path.realpath(filename)
                if not path.startswith(ROOT + os.sep):
                    return None
                rel = os.path.relpath(path, ROOT).replace(os.sep, '/')
                if any(fnmatch.fnmatchcase(rel, g) or (g.startswith('**/') and fnmatch.fnmatchcase(rel, g[3:]))
                       for g in SPEC['exclude_globs']):
                    return None
                if frame.f_code.co_flags & (0x20 | 0x80 | 0x200):
                    LIMITS.add('generator_coroutine_not_traced')
                    return None
                if len(self.frames) >= 256:
                    LIMITS.add('active_frames_cap')
                    return None
                self.serial += 1
                self.frames[fid] = [self.serial, rel, frame.f_code.co_qualname, None, {}]
            state = self.frames.get(fid)
            if state is None:
                return None
            if event in ('line', 'exception', 'return'):
                now = self.values(frame)
                for name in dict.fromkeys([*now, *state[4]]):
                    value = now.get(name, {'kind': 'unavailable', 'reason': 'unbound'})
                    old = state[4].get(name, {'kind': 'unavailable', 'reason': 'unbound'})
                    if old != value:
                        self.sequence += 1
                        if len(self.events) == self.events.maxlen:
                            LIMITS.add('history_ring_truncated')
                        self.events.append(dict(seq=self.sequence, frame=state[0], path=state[1],
                            function=state[2], after_line=state[3], observed_line=frame.f_lineno,
                            variable=name, before=old, after=value))
                state[4] = now
                if event == 'line':
                    state[3] = frame.f_lineno
                if event == 'return':
                    self.frames.pop(fid, None)
            return self.entry
        except Exception:
            LIMITS.add('trace_callback_error')
            sys.settrace(None)
            return None
        finally:
            self.cpu += time.perf_counter_ns() - start


def pytest_collection_finish(session):
    if len(session.items) != 1 or session.items[0].nodeid != SPEC['target']:
        pytest.exit('Faultline capture requires exactly one fully qualified test node ID', returncode=4)


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtest_call(item):
    global TRACE
    if item.nodeid != SPEC['target']:
        return (yield)
    TRACE = History()
    prior = sys.gettrace()
    if prior is not None:
        LIMITS.add('trace_conflict')
        return (yield)
    sys.settrace(TRACE.entry)
    try:
        return (yield)
    finally:
        if sys.gettrace() is not TRACE.entry and not LIMITS.intersection({'trace_budget_exhausted', 'trace_callback_error'}):
            LIMITS.add('trace_replaced')
        sys.settrace(prior)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    rep = yield
    if item.nodeid != SPEC['target']:
        return rep
    record = dict(nodeid=item.nodeid, phase=rep.when, outcome=rep.outcome,
                  xfail=xfail_class(item, call, rep), frames=[])
    if rep.failed:
        record['signature'] = failure_signature(item, call, rep, ROOT)
        text = redact_text(rep.longreprtext)
        record['report'] = text[:65536]
        if len(text) > 65536:
            LIMITS.add('failure_report_truncated')
        if call.excinfo is not None:
            tb = call.excinfo.tb
            frames = collections.deque(maxlen=16)
            while tb is not None:
                f = tb.tb_frame
                path = os.path.realpath(f.f_code.co_filename)
                if path.startswith(ROOT + os.sep):
                    rel = os.path.relpath(path, ROOT).replace(os.sep, '/')
                    if not any(fnmatch.fnmatchcase(rel, g) for g in SPEC['exclude_globs']):
                        snap = TRACE or History()
                        frames.append(dict(path=rel, line=tb.tb_lineno,
                                           function=f.f_code.co_qualname, values=snap.values(f)))
                tb = tb.tb_next
            record['frames'] = list(frames)
    REPORTS.append(record)
    return rep


def pytest_sessionfinish(session, exitstatus):
    write_json(os.environ['FAULTLINE_OUT'], dict(reports=REPORTS, exitstatus=int(exitstatus),
               history=list(TRACE.events) if TRACE else [], limitations=sorted(LIMITS)))
