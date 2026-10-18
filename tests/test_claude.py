import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from faultline.claude import context, install_project
from faultline.config import load_config
from faultline.search import search_code


def event(root, prompt):
    return {'cwd': str(root), 'hook_event_name': 'UserPromptSubmit', 'prompt': prompt}


@pytest.fixture(autouse=True)
def _treat_repos_as_large(monkeypatch, request):
    """Most tests use one-file repos to check injection; disable the small-repo
    silence rule for them (subprocess hooks inherit the env). Silence-rule tests opt out."""
    if "silence" not in request.node.name:
        monkeypatch.setenv("FAULTLINE_SMALL_REPO_BYTES", "0")


def test_installed_command_runs_and_preserves_settings(tmp_path):
    root = tmp_path / 'repo with spaces'
    root.mkdir()
    (root / 'calc.py').write_text('def wrong_total():\n    return 1\n')
    settings = root / '.claude/settings.local.json'
    settings.parent.mkdir()
    settings.write_text(json.dumps({'permissions': {'allow': ['Read']}, 'hooks': {
        'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': 'echo existing'}]}]}}))
    install_project(str(root))
    install_project(str(root))
    data = json.loads(settings.read_text())
    assert data['permissions'] == {'allow': ['Read']}
    groups = data['hooks']['UserPromptSubmit']
    assert len(groups) == 2 and groups[0]['hooks'][0]['command'] == 'echo existing'
    command = groups[1]['hooks'][0]['command']
    proc = subprocess.run(command, shell=True, cwd='/tmp', input=json.dumps(event(root, 'fix calc.py:2')),
                          capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stderr
    text = json.loads(proc.stdout)['hookSpecificOutput']['additionalContext']
    assert 'return 1' in text
    assert len(text.encode()) <= 1800
    bad = subprocess.run(command, shell=True, input='not JSON', capture_output=True, text=True)
    assert bad.returncode == 0 and not bad.stdout


@pytest.mark.parametrize('prompt', ['fix wrong_total', 'tests failed', '/faultline wrong_total', 'review calc.py', 'debug this error'])
def test_debug_activation(tmp_path, prompt):
    (tmp_path / 'calc.py').write_text('def wrong_total():\n    return 1\n')
    assert context(str(tmp_path), event(tmp_path, prompt + ' calc.py:2'))


def test_unrelated_and_outside_prompts(tmp_path):
    assert context(str(tmp_path), event(tmp_path, 'hello')) is None
    assert context(str(tmp_path), event(tmp_path.parent, 'fix bug'), 'always') is None
    assert context(str(tmp_path), event(tmp_path, 'hello'), 'always') is None


def test_user_skill_is_preserved(tmp_path):
    skill = tmp_path / '.claude/skills/faultline/SKILL.md'
    skill.parent.mkdir(parents=True)
    skill.write_text('user content')
    with pytest.raises(ValueError, match='user-owned'):
        install_project(str(tmp_path))
    assert skill.read_text() == 'user content'
    assert not (tmp_path / '.claude/settings.local.json').exists()


def test_line_anchor_bypasses_scan_and_preserves_focus(tmp_path, monkeypatch):
    source = ['def long_function():'] + [f'    value_{i} = {i}' for i in range(100)]
    source[70] = '    raise ValueError("ACTUAL_BUG")'
    (tmp_path / 'long.py').write_text('\n'.join(source))
    import faultline.search as module
    monkeypatch.setattr(module, '_scan', lambda cfg: pytest.fail('precise lookup scanned repository'))
    cfg = load_config(str(tmp_path), sys.executable)
    for budget in (400, 500, 1200):
        result = search_code(cfg, 'long.py:71', budget_tokens=budget)
        assert result.scanned_files == 1
        assert result.hits[0].start <= 71 <= result.hits[0].end
        assert 'ACTUAL_BUG' in result.hits[0].code
    text = context(str(tmp_path), event(tmp_path, 'fix traceback File "long.py", line 71'))
    assert 'ACTUAL_BUG' in text
    with pytest.raises(ValueError):
        search_code(cfg, '../outside.py:1')
    with pytest.raises(ValueError):
        search_code(cfg, 'long.py:999')


def test_neutral_prompt_defers_without_scanning(tmp_path, monkeypatch):
    import faultline.claude as module
    monkeypatch.setattr(module, 'search_code', lambda *a, **k: pytest.fail('should wait for evidence'))
    text = context(str(tmp_path), event(tmp_path, 'The test test/foo.py::TestCase::test_bug fails. Fix it.'))
    assert '--tb=short' in text and '--disable-warnings' in text
    assert 'source retrieval deferred' in text
    assert context(str(tmp_path), event(tmp_path, 'fix the bug')) is None


@pytest.mark.parametrize('name', ['PostToolUse', 'PostToolUseFailure'])
def test_failure_output_fetches_source_not_warning(tmp_path, name):
    (tmp_path / 'bug.py').write_text('def run():\n    return 1 / 0\n')
    (tmp_path / 'noise.py').write_text('x = 1\n')
    output = 'bug.py:2: in run\nE   ZeroDivisionError: division by zero\nnoise.py:1: SyntaxWarning: noise\n1 failed'
    e = dict(cwd=str(tmp_path), hook_event_name=name, tool_name='Bash')
    if name == 'PostToolUse':
        e['tool_response'] = {'stdout': output, 'stderr': ''}
    else:
        e['error'] = output
    text = context(str(tmp_path), e)
    assert 'return 1 / 0' in text and 'noise.py' not in text
    assert len(text.encode()) <= 1800
    e['tool_name'] = 'Read'
    assert context(str(tmp_path), e) is None


def test_success_and_warning_only_output_is_quiet(tmp_path):
    (tmp_path / 'app.py').write_text('x = 1')
    for output in ['1 passed', 'app.py:1: SyntaxWarning: invalid escape', 'app.py:1\n app.py:1: SyntaxWarning: noise\n1 failed', 'FAILED test/foo.py::test_bug']:
        e = dict(cwd=str(tmp_path), hook_event_name='PostToolUse', tool_name='Bash', tool_response={'stdout': output})
        assert context(str(tmp_path), e) is None


def test_search_does_not_emit_parser_warnings(tmp_path):
    import warnings
    (tmp_path / 'old.py').write_text('PATTERN = "\\d"\ndef lookup():\n    return PATTERN\n')
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        search_code(load_config(str(tmp_path), sys.executable), 'lookup')
    assert not caught


def test_installed_posttool_hook_event_and_clean_channels(tmp_path):
    (tmp_path / 'bug.py').write_text('def run():\n    return 1 / 0\n')
    install_project(str(tmp_path))
    settings = json.loads((tmp_path / '.claude/settings.local.json').read_text())
    for name in ('PostToolUse', 'PostToolUseFailure'):
        hook = settings['hooks'][name][-1]
        assert hook['matcher'] == 'Bash'
        e = dict(cwd=str(tmp_path), hook_event_name=name, tool_name='Bash')
        output = 'bug.py:2: in run\nE   ZeroDivisionError: division by zero\n1 failed'
        if name == 'PostToolUse':
            e['tool_response'] = {'stdout': output, 'stderr': ''}
        else:
            e['error'] = output
        proc = subprocess.run(hook['hooks'][0]['command'], shell=True, input=json.dumps(e),
                              capture_output=True, text=True, timeout=15)
        assert proc.returncode == 0 and not proc.stderr
        result = json.loads(proc.stdout)['hookSpecificOutput']
        assert result['hookEventName'] == name and 'return 1 / 0' in result['additionalContext']



def _big_package(root, kib=80):
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    body = "\n".join(f"def f{i}(x):\n    return x + {i}\n" for i in range(kib * 40))
    (pkg / "bulk.py").write_text(body)
    (pkg / "core.py").write_text("def run():\n    return 1 / 0\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_core.py").write_text("from pkg.core import run\n\ndef test_run():\n    assert run() == 1\n")


def _post(root, out, name="PostToolUseFailure"):
    return dict(cwd=str(root), hook_event_name=name, tool_name="Bash", tool_response={"stdout": out, "stderr": ""})


def test_silence_small_repo_injects_nothing(tmp_path):
    (tmp_path / "calc.py").write_text("def total():\n    return 1 / 0\n")
    tb = f'Traceback (most recent call last):\n  File "{tmp_path}/calc.py", line 2, in total\nZeroDivisionError: division by zero\nFAILED t.py::x\n'
    assert context(str(tmp_path), _post(tmp_path, tb)) is None
    assert context(str(tmp_path), event(tmp_path, "The test tests/test_x.py::test_a fails. Fix it.")) is None
    assert context(str(tmp_path), event(tmp_path, 'fix traceback File "calc.py", line 2')) is None


def test_silence_test_file_frame_in_large_repo(tmp_path):
    _big_package(tmp_path)
    tb = ("tests/test_core.py:4: in test_run\n    assert run() == 1\n"
          "E   AssertionError: assert 0 == 1\nFAILED tests/test_core.py::test_run - AssertionError\n1 failed\n")
    assert context(str(tmp_path), _post(tmp_path, tb)) is None


def test_silence_rules_keep_app_frame_injection_in_large_repo(tmp_path):
    _big_package(tmp_path)
    tb = ("tests/test_core.py:4: in test_run\n    assert run() == 1\n"
          "pkg/core.py:2: in run\n    return 1 / 0\nE   ZeroDivisionError: division by zero\n"
          "FAILED tests/test_core.py::test_run - ZeroDivisionError\n1 failed\n")
    text = context(str(tmp_path), _post(tmp_path, tb))
    assert text and "pkg/core.py:" in text and "1 / 0" in text
    # prompt suggestion still offered for large repositories
    assert "pytest" in context(str(tmp_path), event(tmp_path, "The test tests/test_core.py::test_run fails. Fix it."))


def _none_origin_repo(root):
    _big_package(root)
    (root / "pkg" / "core.py").write_text(
        "def make(flag):\n    sel = 'x'\n    if flag:\n        sel = None\n    return sel\n\n\n"
        "def run():\n    s = make(True)\n    return s.upper()\n")
    (root / "tests" / "test_core.py").write_text(
        "from pkg.core import run\n\n\ndef test_run():\n    assert run() == 'X'\n")


def _pytest_output(root, node):
    import os
    import subprocess
    out = subprocess.run([sys.executable, "-m", "pytest", node, "-q", "--tb=short", "--disable-warnings",
                          "-p", "no:cacheprovider"], cwd=root, capture_output=True, text=True,
                         env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    return out.stdout + out.stderr


def test_auto_capture_injects_upstream_cause_next_to_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # capture store stays in tmp
    repo = tmp_path / "repo"
    repo.mkdir()
    _none_origin_repo(repo)
    text = context(str(repo), _post(repo, _pytest_output(repo, "tests/test_core.py::test_run")))
    assert text and "Crash site (deepest traceback frame): pkg/core.py:10" in text
    # The None was produced in make() (line 4), upstream of the crashing run(): that is the candidate.
    assert "Cause candidate" in text and "pkg/core.py:4" in text and "sel = None" in text
    assert len(text.encode()) <= 2000


def test_auto_capture_never_runs_when_silenced(tmp_path, monkeypatch):
    import faultline.capture as cap_mod
    calls = []
    monkeypatch.setattr(cap_mod, "capture_failure", lambda *a, **k: calls.append(1))
    # silence rule 1 (small repo) and rule 2 (test-file frame) must short-circuit before any capture
    monkeypatch.setenv("FAULTLINE_SMALL_REPO_BYTES", str(64 * 1024))
    small = tmp_path / "small"
    small.mkdir()
    (small / "calc.py").write_text("def total():\n    return None.upper()\n")
    tb = f'Traceback (most recent call last):\n  File "{small}/calc.py", line 2, in total\nAttributeError: x\nFAILED t.py::x\n'
    assert context(str(small), _post(small, tb)) is None
    big = tmp_path / "big"
    big.mkdir()
    _big_package(big)
    tb2 = ("tests/test_core.py:4: in test_run\n    assert run() == 1\nE   AssertionError: assert 0 == 1\n"
           "FAILED tests/test_core.py::test_run - AssertionError\n1 failed\n")
    assert context(str(big), _post(big, tb2)) is None
    assert calls == []


def test_failing_node_parsing(tmp_path):
    from faultline.claude import _failing_node
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("")
    out = "FAILED tests/test_a.py::TestX::test_y[1-2] - AssertionError\nFAILED missing.py::t - E\n"
    assert _failing_node(tmp_path, out) == "tests/test_a.py::TestX::test_y[1-2]"
    assert _failing_node(tmp_path, "no summary") is None
