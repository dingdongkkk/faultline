"""Capture once, inspect repeatedly. Stored outputs are local, bounded artifacts.

Freshness covers the workspace, interpreter, installed dependencies and declared
inputs; external services, time and undeclared environment remain untracked.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
import uuid

from .config import resolve_inside, state_dir
from .contracts import CapturePage, CapturePayload, CaptureResponse
from .execution import run_pytest
from .fingerprint import compute

VERSION = 'capture-v1.2'
TTL = 600


def _write(path, data):
    tmp = path.with_suffix('.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(data)
    os.replace(tmp, path)


def _root(cfg):
    root = state_dir(cfg) / 'captures'
    if root.resolve().is_relative_to(Path(cfg.repo_root)):
        raise ValueError('capture state must be outside the target repository')
    root.mkdir(mode=0o700, exist_ok=True)
    return root


def _sweep(root):
    # Bound persisted raw output across repeated captures (32 runs, at most one day).
    dirs = sorted((p for p in root.iterdir() if re.fullmatch(r'C[0-9a-f]{32}', p.name)
                   and p.is_dir() and not p.is_symlink()), key=lambda p: p.stat().st_mtime, reverse=True)
    for index, path in enumerate(dirs):
        if index >= 31 or time.time() - path.stat().st_mtime > 86400:
            shutil.rmtree(path)
    for path in root.glob('*.json'):
        if re.fullmatch(r'[0-9a-f]{64}\.json', path.name) and time.time() - path.stat().st_mtime > TTL:
            path.unlink()


def _size(model, measure):
    for _ in range(16):
        n = measure(model.model_dump_json(exclude_none=True))
        if n == model.response_bytes:
            return n
        object.__setattr__(model, 'response_bytes', n)
        object.__setattr__(model, 'tokens_estimate', math.ceil(n / 3))
    raise ValueError('size calculation did not converge')


def _budget(budget):
    if not 600 <= budget <= 8000:
        raise ValueError('budget_tokens must be in [600, 8000]')


def capture_failure(cfg, failing_test, budget_tokens=1200, timeout_seconds=60,
                    variable=None, refresh=False, measure=None):
    _budget(budget_tokens)
    if not 1 <= timeout_seconds <= 300:
        raise ValueError('timeout_seconds must be in [1, 300]')
    if len(failing_test) > 1000 or '::' not in failing_test:
        raise ValueError('failing_test must be a single pytest node ID')
    test_path = resolve_inside(cfg, failing_test.split('::', 1)[0])
    if not test_path.is_file() or test_path.suffix != '.py':
        raise ValueError('test path must be an existing Python file')
    failing_test = test_path.relative_to(Path(cfg.repo_root)).as_posix() + '::' + failing_test.split('::', 1)[1]
    if variable is not None and (not variable.isidentifier() or len(variable) > 100):
        raise ValueError('variable must be a Python identifier')
    root = _root(cfg)
    # Do not silently run a second test process for concurrent requests.
    with (root / 'capture.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('another capture is running; retry after it finishes') from exc
        _sweep(root)
        before = compute(cfg).fp
        request = dict(version=VERSION, fingerprint=before.fingerprint_id, test=failing_test,
                       variable=variable, config=cfg.model_dump(mode='json'))
        key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        index = root / (key + '.json')
        reused = False
        record = None
        if not refresh and not before.partial and index.exists():
            saved = json.loads(index.read_text())
            if time.time() - saved['created'] < TTL and (root / saved['capture_id'] / 'record.json').exists():
                directory = root / saved['capture_id']
                record = json.loads((directory / 'record.json').read_text())
                reused = True
        if record is None:
            cid = 'C' + uuid.uuid4().hex
            directory = root / cid
            directory.mkdir(mode=0o700)
            # Keep up to 4 MiB of each stream; existing supervisor kills process groups on timeout.
            limits = cfg.limits.model_copy(update={'diagnostic_output_max_bytes': 4 * 1024 * 1024})
            run_cfg = cfg.model_copy(update={'limits': limits,
                'pytest_args': [*cfg.pytest_args, '--tb=long', '--disable-warnings']})
            raw = run_pytest(run_cfg, plugin='capture_plugin', targets=[failing_test],
                extra_env={'FAULTLINE_CAPTURE_SPEC': json.dumps(dict(target=failing_test,
                           variable=variable, exclude_globs=cfg.exclude_globs))},
                timeout_s=timeout_seconds, out_cap=4 * 1024 * 1024, strip_selection=True)
            after = compute(cfg).fp
            payload = CapturePayload.model_validate(raw.payload) if raw.payload is not None else None
            limitations = list(payload.limitations) if payload else ['probe_output_unavailable']
            if raw.output_error:
                limitations.append(raw.output_error)
            if before.partial or after.partial:
                limitations.append('partial_fingerprint_no_reuse')
            changed = before.fingerprint_id != after.fingerprint_id
            phases = payload.reports if payload else []
            failed = any(p.outcome == 'failed' for p in phases)
            normal = len(phases) == 3 and {p.phase for p in phases} == {'setup', 'call', 'teardown'}
            normal = normal and all(p.xfail == 'none' for p in phases)
            status = ('timed_out' if raw.child.timed_out else 'workspace_changed' if changed else
                      'failed' if normal and failed and raw.child.returncode == 1 else
                      'passed' if normal and all(p.outcome == 'passed' for p in phases)
                      and raw.child.returncode == 0 else 'incomplete')
            for name, text in [('stdout', raw.child.stdout_tail), ('stderr', raw.child.stderr_tail)]:
                _write(directory / (name + '.txt'), text)
                if text.startswith('[...truncated...]'):
                    limitations.append(name + '_truncated_to_tail')
            _write(directory / 'report.txt', '\n\n'.join(p.report or '' for p in phases))
            _write(directory / 'trace.json', payload.model_dump_json(exclude_none=True) if payload else '{}')
            record = dict(capture_id=cid, created=time.time(), status=status, failing_test=failing_test,
                          fingerprint_id=before.fingerprint_id, partial=before.partial or after.partial,
                          limitations=limitations, variable=variable,
                          config_digest=hashlib.sha256(json.dumps(cfg.model_dump(mode='json'), sort_keys=True).encode()).hexdigest())
            _write(directory / 'record.json', json.dumps(record))
            if status in ('failed', 'passed') and not before.partial and not after.partial:
                _write(index, json.dumps({'capture_id': cid, 'created': record['created']}))
        return _summary(directory, record, reused, budget_tokens, measure)


def _summary(directory, record, reused, budget, measure):
    raw = json.loads((directory / 'trace.json').read_text())
    payload = CapturePayload.model_validate(raw) if raw else None
    phases = [p for p in payload.reports if p.outcome == 'failed'] if payload else []
    failure = next((p for p in phases if p.phase == 'call'), phases[0] if phases else None)
    frames = failure.frames[-1:] if failure else []
    frames = [f.model_copy(update={'values': dict(sorted(f.values.items(),
              key=lambda pair: (pair[0] != record.get('variable'), pair[1].kind != 'none'))[:4])}) for f in frames]
    history = list(payload.history) if payload else []
    variable = record.get('variable')
    # The caller may focus a value. Otherwise prioritize recent changes in failing frames.
    functions = {(f.path, f.function) for f in frames}
    relevant = [h for h in history if (h.variable == variable if variable else (h.path, h.function) in functions)]
    selection = 'focused_variable' if variable else 'recent_failing_frames'
    selected = relevant[-6:]
    if not variable and frames and any(v.kind == 'none' for v in frames[-1].values.values()):
        # Rank observed None introductions in the failing source file. This is a
        # hypothesis shortlist, NOT identity tracking or a proven producer chain.
        def none_count(value):
            obj = value.model_dump(exclude_none=True)
            def count(x):
                if isinstance(x, dict):
                    return int(x.get('kind') == 'none') + sum(count(v) for v in x.values())
                return sum(count(v) for v in x) if isinstance(x, list) else 0
            return count(obj)
        candidates = [h for h in history if h.path == frames[-1].path and h.after_line is not None
                      and h.before.kind != 'unavailable' and none_count(h.after) > none_count(h.before)]
        if candidates:
            selection = 'none_origin_candidates'
            candidate_ids = {h.seq for h in candidates[-4:]}
            selected = [h for h in relevant[-2:] if h.seq not in candidate_ids] + candidates[-4:]
    result = CaptureResponse(capture_id=record['capture_id'], status=record['status'], reused=reused,
        failing_test=record['failing_test'], fingerprint_id=record['fingerprint_id'],
        signature=failure.signature if failure else None, frames=frames, changes=selected,
        omitted_changes=len(history)-len(selected), selection=selection, artifact_dir=str(directory),
        limitations=record['limitations'] + ['external_state_and_undeclared_inputs_not_fingerprinted',
                    'reuse_is_a_previous_observation_not_a_new_test_run', 'reuse_ttl_600_seconds'],
        budget_scope='mcp_result' if measure else 'json_payload')
    measure = measure or (lambda s: len(s.encode()))
    while _size(result, measure) > budget * 3:
        if result.changes:
            result.changes.pop(0)
            object.__setattr__(result, 'omitted_changes', len(history)-len(result.changes))
        elif result.frames:
            result.frames.pop(0)
        else:
            raise ValueError('capture envelope exceeds budget; increase budget_tokens')
    return result


def read_capture(cfg, capture_id, section='trace', cursor=0, budget_tokens=1200, measure=None, variable=None):
    _budget(budget_tokens)
    if not re.fullmatch(r'C[0-9a-f]{32}', capture_id):
        raise ValueError('invalid capture_id')
    if section not in ('trace', 'report', 'stdout', 'stderr') or not isinstance(cursor, int) or cursor < 0:
        raise ValueError('invalid section or cursor')
    if variable is not None and (section != 'trace' or not variable.isidentifier() or len(variable) > 100):
        raise ValueError('variable filtering requires a Python identifier and section=trace')
    directory = _root(cfg) / capture_id
    record = json.loads((directory / 'record.json').read_text())
    fp = compute(cfg).fp
    config_digest = hashlib.sha256(json.dumps(cfg.model_dump(mode='json'), sort_keys=True).encode()).hexdigest()
    freshness = ('unknown' if record['partial'] or fp.partial or 'config_digest' not in record else
                 'stale' if record['fingerprint_id'] != fp.fingerprint_id or record['config_digest'] != config_digest else 'unchanged')
    text = (directory / (section + ('.json' if section == 'trace' else '.txt'))).read_text()
    if variable is not None:
        payload = json.loads(text)
        text = json.dumps([h for h in payload.get('history', []) if h['variable'] == variable], separators=(',', ':'))
    if cursor > len(text):
        raise ValueError('cursor exceeds section length')
    count = min(len(text)-cursor, budget_tokens * 3)
    result = CapturePage(capture_id=capture_id, section=section, variable=variable, freshness=freshness,
                        text=text[cursor:cursor+count], total_chars=len(text),
                        next_cursor=cursor+count if cursor+count < len(text) else None,
                        budget_scope='mcp_result' if measure else 'json_payload')
    measure = measure or (lambda s: len(s.encode()))
    while _size(result, measure) > budget_tokens * 3:
        count = int(count * .8)
        if not count:
            raise ValueError('page envelope exceeds budget')
        object.__setattr__(result, 'text', text[cursor:cursor+count])
        object.__setattr__(result, 'next_cursor', cursor+count)
    return result
