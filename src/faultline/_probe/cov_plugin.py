"""Baseline pytest plugin: outcomes, xfail classes, failure signatures and
per-phase coverage contexts, all from the same process and run.

Environment:
  FAULTLINE_OUT       JSON output path (required)
  FAULTLINE_ROOT      repository root realpath (required)
  FAULTLINE_COVERAGE  "1" to collect coverage (default), "0" for outcomes only
  FAULTLINE_COV_DATA  coverage data file path (when coverage is on)
"""

from __future__ import annotations

import os
import sys
import time

import pytest

from .common import failure_signature, write_json, xfail_class

_ROOT = os.environ.get("FAULTLINE_ROOT", "")
_OUT = os.environ.get("FAULTLINE_OUT", "")
_WANT_COV = os.environ.get("FAULTLINE_COVERAGE", "1") == "1"

_state: dict = {
    "reports": [],
    "collect_errors": [],
    "unsupported": [],
    "trace_conflicts": [],
    "exitstatus": None,
    "coverage_error": None,
    "started": time.time(),
}
_cov = None
_tracer = None


def pytest_load_initial_conftests(early_config, parser, args):
    """Start coverage before conftest import and collection."""
    global _cov, _tracer
    if not _WANT_COV:
        return
    if sys.gettrace() is not None:
        _state["unsupported"].append("preexisting_tracer")
        return
    try:
        import coverage

        _cov = coverage.Coverage(
            data_file=os.environ["FAULTLINE_COV_DATA"],
            config_file=False,
            include=[_ROOT + "/*"],
            omit=[_ROOT + "/.venv/*", _ROOT + "/.git/*", "*/site-packages/*"],
        )
        # The sysmon core does not support dynamic contexts (coverage docs).
        _cov.set_option("run:core", "ctrace")
        _cov.start()
        _tracer = sys.gettrace()
    except Exception as e:  # noqa: BLE001
        _cov = None
        _state["coverage_error"] = f"{type(e).__name__}: {e}"[:500]


def pytest_configure(config):
    opt = config.option
    if os.environ.get("PYTEST_XDIST_WORKER") or getattr(opt, "numprocesses", None) or \
            getattr(opt, "dist", "no") not in ("no", None):
        _state["unsupported"].append("xdist")
    if getattr(opt, "reruns", 0):
        _state["unsupported"].append("rerunfailures")
    if getattr(opt, "cov_source", None):
        _state["unsupported"].append("pytest_cov_active")


def _phase_wrapper(phase):
    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def hook(item, *args):
        if _cov is not None:
            _cov.switch_context(f"{item.nodeid}|{phase}")
        try:
            return (yield)
        finally:
            if _cov is not None:
                if sys.gettrace() is not _tracer:
                    _state["trace_conflicts"].append([item.nodeid, phase])
                    sys.settrace(_tracer)  # restore so later tests are measured
                _cov.switch_context("")

    return hook


pytest_runtest_setup = _phase_wrapper("setup")
pytest_runtest_call = _phase_wrapper("call")
pytest_runtest_teardown = _phase_wrapper("teardown")


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    rep = yield
    entry = {
        "nodeid": rep.nodeid,
        "when": rep.when,
        "outcome": rep.outcome,
        "xfail": xfail_class(item, call, rep),
    }
    if rep.failed:
        try:
            entry["signature"] = failure_signature(item, call, rep, _ROOT)
        except Exception as e:  # noqa: BLE001
            entry["signature"] = {"message_excerpt": f"<signature error {type(e).__name__}>"}
    _state["reports"].append(entry)
    return rep


def pytest_collectreport(report):
    if report.failed:
        text = str(report.longrepr)[-800:] if report.longrepr is not None else ""
        _state["collect_errors"].append({"nodeid": report.nodeid, "detail": text})


def pytest_sessionfinish(session, exitstatus):
    _state["exitstatus"] = int(exitstatus)


def pytest_unconfigure(config):
    coverage_out = None
    if _cov is not None:
        try:
            _cov.stop()
            data = _cov.get_data()
            coverage_out = {}
            for f in data.measured_files():
                by_ctx: dict[str, list[int]] = {}
                for line, ctxs in data.contexts_by_lineno(f).items():
                    for ctx in ctxs:
                        by_ctx.setdefault(ctx, []).append(line)
                coverage_out[f] = by_ctx
        except Exception as e:  # noqa: BLE001
            _state["coverage_error"] = f"{type(e).__name__}: {e}"[:500]
    _state["coverage"] = coverage_out
    _state["duration_s"] = time.time() - _state["started"]
    if _OUT:
        write_json(_OUT, _state)
