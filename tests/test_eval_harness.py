"""Harness self-tests with scripted 'agents' (no model usage). Skipped when the
private evaluation store is absent (e.g. on other machines / CI)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
H = ROOT / "eval" / "harness"
sys.path.insert(0, str(H))
common = pytest.importorskip("common")
if not (common.PRIVATE / "manifest.json").exists():
    pytest.skip("private evaluation store not present", allow_module_level=True)


def trial(tmp_path, case_id, fix):
    out = subprocess.run([sys.executable, str(H / "run_trial.py"), case_id, "C", "0", "--dry-run-fix", fix,
                          "--out", str(tmp_path)], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr
    return json.loads(next(tmp_path.glob(f"{case_id}-C-t0-dry.json")).read_text())


@pytest.mark.parametrize("case_id", ["e1_textstats", "e2_shipping", "e3_split", "e4_config", "e5_slug",
                                     "e6_invoicing", "e7_sessions"])
def test_reference_fix_judged_correct(tmp_path, case_id):
    r = trial(tmp_path, case_id, "reference")
    assert r["judge"]["correct"] and r["judge"]["tests_unchanged"] and r["valid"]


def test_no_fix_judged_incorrect(tmp_path):
    r = trial(tmp_path, "e1_textstats", "none")
    assert not r["judge"]["correct"] and not r["judge"]["visible_passed"]


def test_regression_trap_passes_visible_but_judged_incorrect(tmp_path):
    r = trial(tmp_path, "e5_slug", "trap")
    j = r["judge"]
    assert j["visible_passed"] and not j["visible_and_hidden_passed"] and j["hidden_failures"] >= 1
    assert not j["correct"]


def test_event_parsing_and_leak_audit(tmp_path):
    import run_trial

    ev = tmp_path / "e.jsonl"
    ev.write_text("\n".join(json.dumps(x) for x in [
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"},
                                                      {"type": "tool_use", "name": "mcp__faultline__investigate_failure"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "x"}, {"type": "tool_use", "name": "Read"}]}},
        {"type": "result", "subtype": "success", "is_error": False, "num_turns": 3, "duration_ms": 10,
         "usage": {"input_tokens": 5, "output_tokens": 7}, "result": "done"},
    ]))
    p = run_trial.parse_events(ev)
    assert p["tool_calls"] == {"Read": 2, "mcp__faultline__investigate_failure": 1} and p["num_turns"] == 3
    assert p["usage"]["cache_read_input_tokens"] is None  # missing stays missing, never 0
    c = common.case("e1_textstats")
    assert run_trial.leak_audit(ev, c) == []
    ev.write_text(ev.read_text() + "\n" + json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": str(common.PRIVATE / "manifest.json")}}]}}))
    assert run_trial.leak_audit(ev, c)


def test_deny_rules_cover_private_store_and_repo():
    import run_trial

    rules = run_trial.deny_rules()
    priv = str(common.PRIVATE.resolve())
    assert f"Read(/{priv}/**)" in rules and f"Edit(/{priv}/**)" in rules
    assert any(str(ROOT) in r for r in rules)
    assert all(r.startswith(("Read(//", "Edit(//", "Bash(")) for r in rules)


def test_e6_formatting_trap_judged_incorrect(tmp_path):
    r = trial(tmp_path, "e6_invoicing", "trap")
    assert r["judge"]["visible_passed"] and not r["judge"]["correct"]


def test_hook_metrics_separate_context_from_warning_output(tmp_path):
    import run_trial
    text = 'Faultline source: café'
    output = 'SyntaxWarning: noisy source\n' + json.dumps({'hookSpecificOutput': {'additionalContext': text}})
    path = tmp_path / 'hooks.jsonl'
    path.write_text(json.dumps({'type': 'system', 'subtype': 'hook_response', 'output': output}))
    hooks = run_trial.parse_events(path)['hooks']
    assert hooks['context_bytes'] == len(text.encode())
    assert hooks['output_bytes'] == len(output.encode())
