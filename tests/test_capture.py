import json
from pathlib import Path
import sys

import pytest

from faultline.capture import capture_failure, read_capture
from faultline.config import load_config


def project(tmp_path, body='value = 10\n    value = None\n    return value.real'):
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'app.py').write_text('def broken():\n    ' + body + '\n')
    (root / 'test_app.py').write_text('from app import broken\ndef test_bug():\n    assert broken() == 10\n')
    return load_config(str(root), sys.executable, state_dir=str(tmp_path / 'state'))


def test_none_origin_reuse_and_staleness(tmp_path, monkeypatch):
    cfg = project(tmp_path)
    r = capture_failure(cfg, 'test_app.py::test_bug', variable='value')
    assert r.status == 'failed' and not r.reused
    transition = next(c for c in r.changes if c.before.kind == 'int' and c.after.kind == 'none')
    assert transition.path == 'app.py' and transition.after_line == 3 and transition.observed_line == 4
    assert r.signature.crash_line == 4
    assert all(not c.path.startswith('<') for c in r.changes)
    assert r.response_bytes == len(r.model_dump_json(exclude_none=True).encode()) <= 3600
    import faultline.capture as module
    original = module.run_pytest
    monkeypatch.setattr(module, 'run_pytest', lambda *a, **k: pytest.fail('unchanged capture reran pytest'))
    again = capture_failure(cfg, 'test_app.py::test_bug', variable='value')
    assert again.reused and again.capture_id == r.capture_id
    report = read_capture(cfg, r.capture_id, 'report')
    assert report.freshness == 'unchanged' and 'AttributeError' in report.text
    path = Path(cfg.repo_root, 'app.py')
    path.write_text('def broken():\n    return 10\n')
    assert read_capture(cfg, r.capture_id).freshness == 'stale'
    monkeypatch.setattr(module, 'run_pytest', original)
    fixed = capture_failure(cfg, 'test_app.py::test_bug', variable='value')
    assert fixed.status == 'passed' and not fixed.reused and fixed.capture_id != r.capture_id
    forced = capture_failure(cfg, 'test_app.py::test_bug', variable='value', refresh=True)
    assert not forced.reused and forced.capture_id != fixed.capture_id


def test_wrong_value_transition_and_artifact_pagination(tmp_path):
    cfg = project(tmp_path, 'value = 10\n    value = 11\n    return value')
    r = capture_failure(cfg, 'test_app.py::test_bug', variable='value')
    assert r.status == 'failed'
    assert any(c.before.value == 10 and c.after.value == 11 and c.after_line == 3 for c in r.changes)
    directory = Path(r.artifact_dir)
    assert directory.stat().st_mode & 0o077 == 0
    for p in directory.iterdir():
        assert p.stat().st_mode & 0o077 == 0
    expected = (directory / 'trace.json').read_text()
    parts, cursor = [], 0
    while True:
        page = read_capture(cfg, r.capture_id, cursor=cursor, budget_tokens=600)
        assert page.response_bytes <= 1800
        parts.append(page.text)
        if page.next_cursor is None:
            break
        assert page.next_cursor > cursor
        cursor = page.next_cursor
    assert ''.join(parts) == expected


def test_timeout_and_collection_failure_not_cached_as_passed(tmp_path):
    cfg = project(tmp_path, 'while True:\n        pass')
    r = capture_failure(cfg, 'test_app.py::test_bug', timeout_seconds=1)
    assert r.status == 'timed_out'
    Path(cfg.repo_root, 'test_app.py').write_text('this is not valid Python!!!')
    r = capture_failure(cfg, 'test_app.py::test_bug')
    assert r.status == 'incomplete'
    assert 'SyntaxError' in read_capture(cfg, r.capture_id, 'stdout', budget_tokens=8000).text


def test_capture_does_not_call_user_repr_and_redacts_locals(tmp_path):
    cfg = project(tmp_path)
    Path(cfg.repo_root, 'app.py').write_text('''class Hostile:
    def __repr__(self):
        raise RuntimeError("repr invoked")
def broken():
    password = "must_not_leak"
    obj = Hostile()
    value = None
    return value.real
''')
    r = capture_failure(cfg, 'test_app.py::test_bug')
    payload = json.loads(Path(r.artifact_dir, 'trace.json').read_text())
    assert r.status == 'failed'
    assert 'must_not_leak' not in json.dumps(payload['history'])
    assert any(e['after']['kind'] == 'opaque' for e in payload['history'])
    assert r.signature.exception_type == 'builtins.AttributeError'


def test_invalid_capture_requests(tmp_path):
    cfg = project(tmp_path)
    with pytest.raises(ValueError):
        capture_failure(cfg, '../outside.py::test_bad')
    with pytest.raises(ValueError):
        read_capture(cfg, '../../escape')
    with pytest.raises(ValueError):
        capture_failure(cfg, 'test_app.py::test_bug', variable='x.y')


def test_none_candidate_across_producer_consumer_and_filtered_read(tmp_path, monkeypatch):
    cfg = project(tmp_path)
    Path(cfg.repo_root, 'app.py').write_text('''def produce():
    item = 10
    item = None
    items = []
    items.append(item)
    return items
def consume(item):
    return item.real
def broken():
    return consume(produce()[0])
''')
    r = capture_failure(cfg, 'test_app.py::test_bug')
    assert r.selection == 'none_origin_candidates'
    assert any(c.variable == 'item' and c.after_line == 3 for c in r.changes)
    assert any(c.variable == 'items' and c.after_line == 5 for c in r.changes)
    import faultline.capture as module
    monkeypatch.setattr(module, 'run_pytest', lambda *a, **k: pytest.fail('read reran tests'))
    page = read_capture(cfg, r.capture_id, variable='item', budget_tokens=8000)
    assert all(e['variable'] == 'item' for e in json.loads(page.text))
    assert page.variable == 'item'


def test_multi_test_selection_is_rejected_before_running(tmp_path):
    cfg = project(tmp_path)
    Path(cfg.repo_root, 'test_app.py').write_text('''import pytest
@pytest.mark.parametrize('x', [1, 2])
def test_bug(x):
    raise RuntimeError('should_not_execute')
''')
    r = capture_failure(cfg, 'test_app.py::test_bug')
    assert r.status == 'incomplete'
    payload = json.loads(Path(r.artifact_dir, 'trace.json').read_text())
    assert payload['reports'] == [] and payload['history'] == []


def test_changed_during_run_and_partial_fingerprint_prevent_reuse(tmp_path):
    cfg = project(tmp_path)
    Path(cfg.repo_root, 'app.py').write_text('''def broken():
    from pathlib import Path
    Path('modified.txt').write_text('changed')
    return 10
''')
    r = capture_failure(cfg, 'test_app.py::test_bug')
    assert r.status == 'workspace_changed'
    small = cfg.model_copy(update={'limits': cfg.limits.model_copy(update={'fingerprint_max_files': 1})})
    r1 = capture_failure(small, 'test_app.py::test_bug')
    r2 = capture_failure(small, 'test_app.py::test_bug')
    assert not r2.reused and r1.capture_id != r2.capture_id
    assert read_capture(small, r1.capture_id).freshness == 'unknown'


def test_removed_tracer_is_reported_and_config_changes_are_stale(tmp_path):
    cfg = project(tmp_path, 'import sys\n    sys.settrace(None)\n    value = None\n    return value.real')
    r = capture_failure(cfg, 'test_app.py::test_bug')
    assert 'trace_replaced' in r.limitations and r.status == 'failed'
    changed = cfg.model_copy(update={'pytest_args': ['--strict-markers']})
    assert read_capture(changed, r.capture_id).freshness == 'stale'


def test_expired_capture_runs_again_and_retention_is_bounded(tmp_path):
    import time
    from faultline.capture import _root, _sweep
    cfg = project(tmp_path)
    r = capture_failure(cfg, 'test_app.py::test_bug')
    root = _root(cfg)
    index = next(root.glob('*.json'))
    value = json.loads(index.read_text())
    value['created'] = time.time() - 601
    index.write_text(json.dumps(value))
    fresh = capture_failure(cfg, 'test_app.py::test_bug')
    assert not fresh.reused and fresh.capture_id != r.capture_id
    for n in range(35):
        (root / ('C' + f'{n:032x}')).mkdir()
    _sweep(root)
    assert len([p for p in root.iterdir() if p.is_dir()]) <= 31
