"""M2: coverage/outcome joins, phase/xfail policy, target-focused Ochiai."""

from fractions import Fraction
from functools import partial

import pytest

from faultline.config import ConfigError, is_app_path, validate_pytest_args
from faultline.contracts import ExclusionReason, PhaseOutcome, TestClass, XfailClass
from faultline.execution import Baseline, run_baseline
from faultline.ranking import display_score, group_ties, LineStat, ochiai_squared, rank

PH = "tests/test_phases.py::"


# ---------------------------------------------------------------- unit: Ochiai


def test_ochiai_zero_denominators_are_undefined():
    assert ochiai_squared(0, 0, 1) is None  # line executed by no eligible test
    assert ochiai_squared(0, 0, 0) is None  # no failing tests at all
    assert ochiai_squared(0, 3, 1) == 0


def test_ochiai_exact_values():
    assert ochiai_squared(1, 0, 1) == 1
    assert ochiai_squared(1, 1, 1) == Fraction(1, 2)
    assert display_score(ochiai_squared(1, 1, 1)) == 0.7071
    with pytest.raises(ValueError):
        ochiai_squared(2, 0, 1)


def test_distinct_count_pairs_tie_exactly():
    # (1,0) and (2,2) with F=4: 1/sqrt(4*1) == 2/sqrt(4*4) == 0.5
    a, b = ochiai_squared(1, 0, 4), ochiai_squared(2, 2, 4)
    assert a == b
    groups = group_ties([LineStat("b.py", 1, 2, 2, b), LineStat("a.py", 9, 1, 0, a),
                         LineStat("a.py", 2, 1, 3, ochiai_squared(1, 3, 4))])
    assert [len(g.members) for g in groups] == [2, 1]
    assert [(m.path, m.line) for m in groups[0].members] == [("a.py", 9), ("b.py", 1)]


def test_float_near_ties_are_not_merged():
    # Scores differing by < 1e-12 must stay distinct groups.
    x, y = ochiai_squared(1, 10**6, 1), ochiai_squared(1, 10**6 + 1, 1)
    assert x != y and len(group_ties([LineStat("a", 1, 1, 10**6, x), LineStat("a", 2, 1, 10**6 + 1, y)])) == 2


def _baseline(records, coverage):
    return Baseline(run_id="R", records=records, coverage=coverage, unsupported=[], collect_errors=[],
                    duplicate_reports=[], trace_conflicts=[], exitstatus=1, duration_ms=0,
                    timed_out=False, cancelled=False, error=None, stdout_tail="", stderr_tail="")


def test_unrelated_failures_do_not_change_target_ranking():
    from faultline.execution import classify

    def rec(n, call):
        return classify(n, {"setup": {"outcome": "passed"}, "call": {"outcome": call},
                            "teardown": {"outcome": "passed"}}, target="t", duplicate=False, conflict=False)

    cov = {"m.py": {1: {("t", "call"), ("p", "call")}, 2: {("t", "call"), ("u1", "call"), ("u2", "call")},
                    3: {("u1", "call")}}}
    with_u = {"t": rec("t", "failed"), "p": rec("p", "passed"), "u1": rec("u1", "failed"), "u2": rec("u2", "failed")}
    without_u = {k: v for k, v in with_u.items() if k in ("t", "p")}
    r1 = rank(_baseline(with_u, cov), "t", lambda p: True)
    r2 = rank(_baseline(without_u, cov), "t", lambda p: True)
    assert [(s.line, s.ef, s.ep) for s in r1.lines] == [(s.line, s.ef, s.ep) for s in r2.lines] == [(2, 1, 0), (1, 1, 1)]
    assert r1.total_failing == 1 and r1.unrelated_failing == ["u1", "u2"]
    assert r1.excluded[ExclusionReason.UNRELATED_FAILURE] == 2


# ---------------------------------------------------------- integration: runs


def test_hand_checkable_fixture(make_project):
    cfg = make_project("ochiai_basic")
    target = "tests/test_a.py::test_two"
    b = run_baseline(cfg, target, timeout_s=60)
    assert b.error is None and not b.unsupported and b.exitstatus == 1
    assert set(b.records) == {"tests/test_a.py::test_one", target, "tests/test_a.py::test_p[1]", "tests/test_a.py::test_p[3]"}
    r = rank(b, target, partial(is_app_path, cfg))
    got = [(s.path, s.line, s.ef, s.ep, g.index) for g in r.groups for s in g.members]
    # app.py:10 (return a*2): target + test_p[3]; app.py:9 (if): target + 3 passing.
    assert got == [("app.py", 10, 1, 1, 1), ("app.py", 9, 1, 3, 2)]
    assert display_score(r.groups[0].members[0].sq) == 0.7071
    assert display_score(r.groups[1].members[0].sq) == 0.5
    # app.py:5 is covered only in test_one's *setup* (module fixture): never ranked or
    # attributed to other consumers; app.py:1,4,8 are import-time (unattributed).
    assert b.coverage["app.py"][5] == {("tests/test_a.py::test_one", "setup")}
    assert r.setup_teardown_only_line_count == 1
    assert r.unattributed_line_count == 3
    assert r.zero_ef_line_count == 1  # app.py:11


def test_phase_and_xfail_policy(make_project):
    cfg = make_project("phases")
    target = PH + "test_target"
    b = run_baseline(cfg, target, timeout_s=60)
    assert b.error is None and not b.unsupported
    R = b.records
    expect = {
        "test_ok": (TestClass.PASSING, None, XfailClass.NONE),
        "test_target": (TestClass.TARGET_FAILING, None, XfailClass.NONE),
        "test_unrelated": (TestClass.EXCLUDED, ExclusionReason.UNRELATED_FAILURE, XfailClass.NONE),
        "test_skip": (TestClass.EXCLUDED, ExclusionReason.SKIPPED, XfailClass.NONE),
        "test_xfail": (TestClass.EXCLUDED, ExclusionReason.XFAIL, XfailClass.XFAIL),
        "test_xpass": (TestClass.EXCLUDED, ExclusionReason.XPASS, XfailClass.XPASS),
        "test_xpass_strict": (TestClass.EXCLUDED, ExclusionReason.XPASS_STRICT, XfailClass.XPASS_STRICT),
        "test_xfail_raises_mismatch": (TestClass.EXCLUDED, ExclusionReason.XFAIL_RAISES_MISMATCH,
                                       XfailClass.XFAIL_RAISES_MISMATCH),
        "test_imperative_xfail": (TestClass.EXCLUDED, ExclusionReason.XFAIL, XfailClass.XFAIL),
        "test_setup_error": (TestClass.EXCLUDED, ExclusionReason.SETUP_FAILED, XfailClass.NONE),
        "test_teardown_error": (TestClass.EXCLUDED, ExclusionReason.TEARDOWN_FAILED, XfailClass.NONE),
        "test_param[zero]": (TestClass.PASSING, None, XfailClass.NONE),
        "test_param[five[x]]": (TestClass.PASSING, None, XfailClass.NONE),
    }
    for name, (klass, excl, xf) in expect.items():
        r = R[PH + name]
        assert (r.klass, r.exclusion, r.xfail) == (klass, excl, xf), name
    # strict XPASS is reported by pytest as a *failed* call without wasxfail
    assert R[PH + "test_xpass_strict"].call is PhaseOutcome.FAILED
    assert R[PH + "test_setup_error"].call is PhaseOutcome.NOT_RUN

    rk = rank(b, target, partial(is_app_path, cfg))
    by_line = {(s.path, s.line): (s.ef, s.ep) for s in rk.lines}
    # used_by_target body: target + test_ok + 2 params passing
    assert by_line[("app.py", 2)] == (1, 3)
    # Nothing from excluded tests or fixtures is ranked.
    ranked_lines = {ln for _, ln in by_line}
    assert ranked_lines == {2, 3}
    assert rk.total_failing == 1 and rk.total_passing == 3
    assert rk.unrelated_failing == [PH + "test_unrelated", PH + "test_unrelated_two"]
    # module-fixture and teardown code: setup/teardown-only, not ranked
    assert ("tests/test_phases.py::test_ok", "setup") in b.coverage["app.py"][19]
    assert any(ph == "teardown" for _, ph in b.coverage["app.py"][23])


def test_target_failure_signature_recorded(make_project):
    cfg = make_project("phases")
    b = run_baseline(cfg, PH + "test_target", timeout_s=60)
    sig = b.records[PH + "test_target"].signature
    assert sig.exception_type == "builtins.AssertionError"
    assert sig.crash_path == "tests/test_phases.py" and sig.test_line == sig.crash_line == 29
    assert sig.message_digest and "assert" in sig.message_excerpt


def test_collection_error_detected(make_project):
    cfg = make_project("collect_error")
    b = run_baseline(cfg, "tests/test_ok.py::test_f", timeout_s=60)
    assert b.collect_errors and b.collect_errors[0]["nodeid"].endswith("test_broken.py")
    assert b.exitstatus == 2


@pytest.mark.parametrize("bad", [["-n", "4"], ["-n4"], ["--reruns=2"], ["--cov=app"], ["-x"],
                                 ["--maxfail=1"], ["-p", "xdist"], ["-pxdist"], ["--lf"], ["--pdb"]])
def test_execution_changing_args_rejected(bad):
    with pytest.raises(ConfigError):
        validate_pytest_args(bad)


def test_benign_args_allowed():
    validate_pytest_args(["-p", "no:randomly", "-k", "not slow", "-m", "unit"])


def test_rerun_plugin_like_duplicates_are_unsupported(make_project):
    from faultline.execution import RawRun, parse_baseline
    from faultline.procs import ChildResult

    cfg = make_project("ochiai_basic")
    rep = {"nodeid": "t", "when": "call", "outcome": "failed", "xfail": "none"}
    raw = RawRun("R1", ChildResult(1, False, False, 1, "", "", 1),
                 {"reports": [{**rep, "when": "setup", "outcome": "passed"}, rep, rep,
                              {**rep, "when": "teardown", "outcome": "passed"}], "coverage": {}})
    b = parse_baseline(cfg, raw, "t")
    assert "duplicate_phase_reports" in b.unsupported
    assert b.records["t"].exclusion is ExclusionReason.DUPLICATE_REPORT


def test_selection_args_stripped_for_single_test_runs():
    from faultline.config import without_selection_args

    assert without_selection_args(["-k", "not slow", "-mfast", "--deselect", "a::b", "-q", "-o", "x=1",
                                   "--deselect=c::d", "-k=e"]) == ["-q", "-o", "x=1"]


def test_relative_python_path_is_accepted_without_leaving_the_venv(tmp_path, monkeypatch):
    import os
    import sys

    from faultline.config import load_config

    monkeypatch.chdir(os.path.dirname(os.path.dirname(sys.executable)))  # the venv root
    cfg = load_config(str(tmp_path), "bin/" + os.path.basename(sys.executable))
    assert cfg.python == os.path.abspath(sys.executable)  # symlink kept, not resolved
