"""M3: before-line timing, immediate snapshots, safe serialization, frame-exit
classification, exact vs lower-bound counts, limits, cleanup, reproduction."""

import os
import time

import pytest

from faultline.contracts import FailureSignature, HitCount, PhaseOutcome, Reproduction
from faultline.execution import run_baseline
from faultline.source import index_file
from faultline.worker import FunctionProbe, LineProbe, match_signature, run_observation, to_observation

T = "tests/test_obs.py::"


def line_of(cfg, marker):
    idx = index_file(cfg, "app.py")
    return next(i + 1 for i, s in enumerate(idx.lines) if f"@mark:{marker}" in s)


def fn_probe(cfg, pid, qualname):
    fn = next(f for f in index_file(cfg, "app.py").functions if f.qualname == qualname)
    return FunctionProbe(pid, "app.py", qualname, fn.start)


def observe(cfg, test, probes, role="target", baseline=None, timeout=60):
    r = run_observation(cfg, nodeid=T + test, probes=probes, role=role, baseline_signature=baseline,
                        timeout_s=timeout, fingerprint_id="fp", sources=[])
    assert r.error is None or r.timed_out, (r.error, r.stderr_tail)
    return r


@pytest.fixture
def cfg(make_project):
    # The sleeper test would hold a full-suite baseline for 60 s; exclude it there.
    return make_project("observe", pytest_args=["-k", "not sleeper"])


def test_before_line_values_are_pre_state_and_copied_immediately(cfg):
    a, s = line_of(cfg, "append"), line_of(cfg, "sum")
    r = observe(cfg, "test_mutate", [LineProbe("L1", "app.py", (a,), ("items", "total")),
                                     LineProbe("L2", "app.py", (s,), ("items", "total"))], role="comparator")
    obs = {o["probe_id"]: o for o in r.observations}
    # Before the append line runs, items has not been mutated yet - and the snapshot
    # was copied then, so the later append does not leak into it.
    assert [i["value"] for i in obs["L1"]["values"]["items"]["items"]] == [1, 2]
    assert [i["value"] for i in obs["L2"]["values"]["items"]["items"]] == [1, 2, 99]
    # Before line `total = sum(items)`, total still holds the pre-state 0.
    assert obs["L2"]["values"]["total"] == {"kind": "int", "value": 0}
    assert obs["L1"]["event"] == "before_line" and obs["L1"]["event_seq"] < obs["L2"]["event_seq"]
    assert r.run.counts_exact and r.run.probe_hits["L1:before_line"] == HitCount(count=1, exact=True)
    o = to_observation(cfg, r.observations[0], "O1", r.run.run_id)
    assert o.path == "app.py" and o.call_depth == 1


def test_hostile_objects_are_opaque_and_no_user_code_runs(cfg):
    h = line_of(cfg, "hostile")
    r = observe(cfg, "test_hostile", [LineProbe("L1", "app.py", (h,), ("h", "d", "w", "x"))], role="comparator")
    # The fixture test asserts that no hook (repr/str/property/iter/len/eq/lt/
    # getattr/metaclass __getattribute__/dict-subclass items) was invoked.
    assert r.run.call_outcome is PhaseOutcome.PASSED
    v = r.observations[0]["values"]
    assert v["h"] == {"kind": "opaque", "type_name": "app.Hostile"}
    assert v["d"] == {"kind": "opaque", "type_name": "app.MyDict"}  # builtin subclass -> opaque
    assert v["w"] == {"kind": "opaque", "type_name": "app.WithMeta"}
    x = v["x"]
    assert x["kind"] == "list" and x["length"] == 4
    assert x["items"][3]["kind"] == "set" and x["items"][3]["reason"] == "iteration_order"


def test_frame_exit_classification(cfg):
    probes = [fn_probe(cfg, "F1", "catches"), fn_probe(cfg, "F2", "propagates"), fn_probe(cfg, "F3", "gen")]
    r = observe(cfg, "test_exits", probes, role="comparator")
    ev = [(o["probe_id"], o["event"]) for o in r.observations]
    assert ("F1", "exception") in ev and ("F1", "return") in ev and ("F1", "unwind") not in ev
    assert ("F2", "exception") in ev and ("F2", "unwind") in ev and ("F2", "return") not in ev
    assert ("F3", "exit_ambiguous") in ev and ("F3", "return") not in ev
    ret = next(o for o in r.observations if o["probe_id"] == "F1" and o["event"] == "return")
    assert ret["values"]["<return>"] == {"kind": "int", "value": 1}
    unwind = next(o for o in r.observations if o["event"] == "unwind")
    assert unwind["exception_type"] == "builtins.ValueError"
    assert "generator_or_coroutine_frame" in r.run.unsupported_detected
    call = next(o for o in r.observations if o["probe_id"] == "F2" and o["event"] == "call")
    assert call["values"] == {"v": {"kind": "int", "value": 2}}


def test_redaction_by_name_and_value(cfg):
    ln = line_of(cfg, "secrets")
    r = observe(cfg, "test_secrets", [LineProbe("L1", "app.py", (ln,), ("password", "data", "blob", "note"))],
                role="comparator")
    v = r.observations[0]["values"]
    assert v["password"] == {"kind": "redacted", "reason": "name_pattern"}
    assert v["blob"] == {"kind": "redacted", "reason": "value_pattern"}
    assert v["note"]["value"] == "safe"
    entries = {e[0]["value"]: e[1] for e in v["data"]["entries"]}
    assert entries["api_key"] == {"kind": "redacted", "reason": "name_pattern"} and entries["ok"]["value"] == 1


def test_value_bounds_and_truncation_flags(cfg):
    ln = line_of(cfg, "limits")
    r = observe(cfg, "test_limits", [LineProbe("L1", "app.py", (ln,),
                                               ("nested", "big", "s", "huge", "cyc", "unordered"))], role="comparator")
    v = r.observations[0]["values"]
    assert v["nested"]["items"][0]["items"][0]["items"][0]["kind"] == "depth_limit"
    assert v["big"]["length"] == 100 and len(v["big"]["items"]) == 16 and v["big"]["truncated"]
    assert v["s"]["length"] == 1000 and len(v["s"]["value"]) == 160 and v["s"]["truncated"]
    assert v["huge"]["kind"] == "int" and v["huge"]["truncated"] and "value" not in v["huge"]
    assert v["cyc"]["items"][0]["kind"] == "cycle"
    assert [i["value"] for i in v["unordered"]["items"]] == [1, 2, 3]


def test_snapshot_caps_keep_counts_exact(cfg):
    ln = line_of(cfg, "spin")
    r = observe(cfg, "test_spin_small", [LineProbe("L1", "app.py", (ln,), ("i",))], role="comparator")
    assert r.run.probe_hits["L1:before_line"] == HitCount(count=50, exact=True)
    assert len(r.observations) == 20 and r.run.events_dropped == 30
    assert "max_hits_per_probe:L1" in r.run.truncation


def test_callback_budget_makes_counts_lower_bounds(cfg):
    ln = line_of(cfg, "spin")
    cfg = cfg.model_copy(update={"limits": cfg.limits.model_copy(update={"callback_cpu_budget_ms": 5})})
    r = observe(cfg, "test_spin_big", [LineProbe("L1", "app.py", (ln,), ("i",))], role="comparator")
    assert r.run.trace_stopped == "callback_budget" and not r.run.counts_exact
    hc = r.run.probe_hits["L1:before_line"]
    assert hc.exact is False and 0 < hc.count < 300000
    assert r.run.call_outcome is PhaseOutcome.PASSED  # the test itself still ran to completion


def test_timeout_kills_and_reaps_process_group(cfg, tmp_path):
    pidfile = tmp_path / "child.pid"
    os.environ["FL_TEST_PIDFILE"] = str(pidfile)
    try:
        t0 = time.monotonic()
        r = observe(cfg, "test_sleeper", [], timeout=3)
    finally:
        del os.environ["FL_TEST_PIDFILE"]
    assert r.timed_out and time.monotonic() - t0 < 15
    assert r.run.reproduction is Reproduction.UNKNOWN and r.run.trace_stopped == "timeout"
    assert not r.run.counts_exact
    pid = int(pidfile.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"grandchild {pid} survived process-group cleanup")


def test_threads_and_subprocesses_detected(cfg):
    ln = line_of(cfg, "bulk")
    r = observe(cfg, "test_thread_and_subprocess", [LineProbe("L1", "app.py", (ln,), ("qty",))], role="comparator")
    assert {"subprocess_spawned"} <= set(r.run.unsupported_detected)
    # threads_started is only detectable while the thread is alive at call end;
    # the fixture joins it, so absence here is the documented limitation.


def test_reproduction_requires_full_signature(cfg):
    b = run_baseline(cfg, T + "test_bulk_target", timeout_s=60)
    base = b.records[T + "test_bulk_target"].signature
    ln = line_of(cfg, "bulk")
    r = observe(cfg, "test_bulk_target", [LineProbe("L1", "app.py", (ln,), ("qty",))], baseline=base)
    assert r.run.reproduction is Reproduction.REPRODUCED
    assert r.observations[0]["values"]["qty"]["value"] == 10
    # Same type, same location, different message -> partial_match, not reproduced.
    flaky = b.records[T + "test_flaky_message"].signature
    os.environ["FL_EXPECT"] = "7"
    try:
        r2 = observe(cfg, "test_flaky_message", [], baseline=flaky)
    finally:
        del os.environ["FL_EXPECT"]
    assert r2.run.reproduction is Reproduction.PARTIAL_MATCH
    # A different test failing elsewhere -> different_failure
    r3 = observe(cfg, "test_flaky_message", [], baseline=base)
    assert r3.run.reproduction is Reproduction.DIFFERENT_FAILURE


def test_match_signature_unit():
    base = FailureSignature(exception_type="builtins.AssertionError", crash_path="t.py", crash_line=3,
                            test_line=3, message_digest="a")
    same = base.model_copy()
    other_line = base.model_copy(update={"crash_line": 4})
    other_type = base.model_copy(update={"exception_type": "builtins.KeyError"})
    msg = base.model_copy(update={"message_digest": "b"})
    P, F, N = PhaseOutcome.PASSED, PhaseOutcome.FAILED, PhaseOutcome.NOT_RUN
    assert match_signature(base, F, same, P) is Reproduction.REPRODUCED
    assert match_signature(base, F, msg, P) is Reproduction.PARTIAL_MATCH
    assert match_signature(base, F, other_line, P) is Reproduction.DIFFERENT_FAILURE
    assert match_signature(base, F, other_type, P) is Reproduction.DIFFERENT_FAILURE
    assert match_signature(base, P, None, P) is Reproduction.NOT_REPRODUCED
    assert match_signature(base, N, None, F) is Reproduction.DIFFERENT_FAILURE
    assert match_signature(base, N, None, P) is Reproduction.UNKNOWN
