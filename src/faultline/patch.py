"""check_patch: run tests against the *current* checkout (never applies edits).

Default mode is ``full`` (review decision for the first release). ``affected``
mode selects conservatively and escalates to the full configured suite on
any uncertainty. Pre-patch outcomes are never reused.
"""

from __future__ import annotations

import time

from . import fingerprint as fpmod
from .budget import Packer
from .config import is_test_path
from .contracts import (
    CheckPatchResponse,
    EffectiveScope,
    FaultlineConfig,
    Limitation,
    PatchMode,
)
from .evidence import EvidenceStore
from .execution import run_pytest

RESIDUAL_RISKS = Limitation(
    code="selection_residual_risk",
    detail="Affected selection uses pre-patch call-phase file coverage; cross-test state, reflection or "
           "string dispatch, data outside the fingerprint, and order dependence can still affect unselected tests.",
)


def escalation_reasons(cfg: FaultlineConfig, manifest: dict, d: fpmod.Diff) -> list[str]:
    reasons: list[str] = []
    if not manifest.get("baseline_supported"):
        reasons.append("baseline_incompatible")
    if d.partial:
        reasons.append("fingerprint_partial")
    reasons += [f"added:{p}" for p in d.added]
    reasons += [f"deleted:{p}" for p in d.deleted]
    reasons += [f"environment_changed:{c}" for c in d.components]
    cov = manifest.get("file_cov", {})
    for p in d.changed:
        name = p.rsplit("/", 1)[-1]
        if is_test_path(cfg, p) or name in fpmod.CONFIG_NAMES:
            reasons.append(f"test_or_config_changed:{p}")
        elif not p.endswith(".py") or p.startswith("@extra:"):
            reasons.append(f"non_python_changed:{p}")
        elif p not in cov:
            reasons.append(f"uncovered_change:{p}")
        else:
            info = cov[p]
            if info.get("unattributed"):
                reasons.append(f"import_time_coverage:{p}")
            if info.get("setup_teardown"):
                reasons.append(f"fixture_phase_coverage:{p}")
            if not info.get("call"):
                reasons.append(f"no_call_coverage:{p}")
    return reasons


def _outcome(phases: dict[str, dict]) -> str:
    for when in ("setup", "call", "teardown"):
        xf = phases.get(when, {}).get("xfail", "none")
        if xf == "xfail":
            return "xfailed"
        if xf == "xpass":
            return "xpassed"
    s, c, t = (phases.get(w, {}).get("outcome") for w in ("setup", "call", "teardown"))
    if s == "failed" or t == "failed":
        return "error"
    if c == "failed":
        return "failed"
    if "skipped" in (s, c):
        return "skipped"
    return "passed" if c == "passed" else "error"


def check_patch(cfg: FaultlineConfig, store: EvidenceStore, investigation_id: str, mode: str = "full",
                timeout_seconds: int = 120, budget_tokens: int = 1500) -> CheckPatchResponse:
    lim = cfg.limits
    mode_e = PatchMode(mode)
    budget_tokens = max(lim.budget_tokens_min, min(budget_tokens, lim.budget_tokens_cap))
    timeout = max(1, min(timeout_seconds, lim.timeout_seconds_cap))
    start = time.monotonic()
    manifest = store.load_manifest(investigation_id)
    expired = store.is_expired(manifest)
    limitations: list[Limitation] = []
    current = fpmod.compute(cfg)

    if expired or "files" not in manifest:
        d = fpmod.Diff([], [], [], [], True)
        reasons = ["baseline_expired"]
        changed: list[str] = []
    else:
        d = fpmod.diff(manifest["files"], manifest["components"], manifest["fingerprint"]["partial"], current)
        reasons = escalation_reasons(cfg, manifest, d)
        changed = d.changed + d.added + d.deleted

    tests = manifest.get("tests", {})
    previously_non_passing = sorted(n for n, t in tests.items() if t.get("klass") != "passing")
    selected: list[dict]
    if mode_e is PatchMode.FULL:
        scope = EffectiveScope.FULL
        targets: list[str] = []
    elif reasons:
        scope = EffectiveScope.AFFECTED_ESCALATED_TO_FULL
        targets = []
    else:
        scope = EffectiveScope.AFFECTED
        sel: dict[str, list[str]] = {n: ["previously_non_passing"] for n in previously_non_passing}
        for p in d.changed:
            for n in manifest["file_cov"][p]["call"]:
                sel.setdefault(n, []).append(f"covers_changed:{p}")
        targets = sorted(sel)
        selected = [{"nodeid": n, "reasons": sel[n]} for n in targets]

    if scope is EffectiveScope.AFFECTED and not targets:
        # Nothing changed and nothing failed: still run the previously failing set (empty) -> say so.
        limitations.append(Limitation(code="nothing_selected", detail="No changes and no previously non-passing tests."))
        raw = None
    else:
        raw = run_pytest(cfg, plugin="cov_plugin", targets=targets, extra_env={"FAULTLINE_COVERAGE": "0"},
                         timeout_s=timeout, out_cap=lim.baseline_output_max_bytes,
                         strip_selection=bool(targets))

    phases: dict[str, dict[str, dict]] = {}
    if raw is not None and raw.payload:
        for r in raw.payload.get("reports", []):
            phases.setdefault(r["nodeid"], {})[r["when"]] = r
    outcomes = {n: _outcome(ph) for n, ph in phases.items()}
    if scope is not EffectiveScope.AFFECTED:
        selected = [{"nodeid": n, "reasons": ["full_suite"]} for n in sorted(outcomes)]
    counts: dict[str, int] = {}
    for o in outcomes.values():
        counts[o] = counts.get(o, 0) + 1

    if raw is None:
        status = "passed"
    elif raw.child.timed_out:
        status = "timed_out"
    elif raw.payload is None or raw.payload.get("collect_errors") or raw.output_error:
        status = "execution_error"
    elif any(o in ("failed", "error") for o in outcomes.values()):
        status = "failed"
    elif scope is EffectiveScope.AFFECTED and set(targets) - set(outcomes):
        status = "execution_error"
        limitations.append(Limitation(code="selected_tests_missing",
                                      detail=f"{len(set(targets) - set(outcomes))} selected tests did not run"))
    else:
        status = "passed"

    after = fpmod.compute(cfg)
    if after.fp.fingerprint_id != current.fp.fingerprint_id:
        status = "execution_error"
        limitations.append(Limitation(code="workspace_changed_during_check",
                                      detail="The checkout changed while tests ran; outcomes do not correspond to one state."))
    full_ran = scope is not EffectiveScope.AFFECTED
    if scope is EffectiveScope.AFFECTED:
        limitations.append(Limitation(code="affected_scope_not_full_regression",
                                      detail="Only selected tests ran; this is not full regression verification."))
        limitations.append(RESIDUAL_RISKS)
    limitations.append(Limitation(code="configured_suite_only",
                                  detail="Covers the configured visible suite only; tests outside it are not run."))

    non_passing = [{"nodeid": n, "outcome": o} for n, o in sorted(outcomes.items())
                   if o in ("failed", "error")]
    prev = {n: outcomes.get(n, "not_run") for n in previously_non_passing}
    base = {
        "investigation_id": investigation_id, "mode_requested": mode_e.value, "effective_scope": scope.value,
        "escalation_reasons": (reasons[:20] if mode_e is PatchMode.AFFECTED else []),
        "changed_paths": changed[:30], "selected": [],
        "selected_count": len(selected), "outcome_counts": counts, "non_passing": [],
        "previously_failing_now": {}, "duration_ms": int((time.monotonic() - start) * 1000), "status": status,
        "full_regression_verified": bool(full_ran and status == "passed" and raw is not None),
        "limitations": [lim_.model_dump() for lim_ in limitations], "omissions": [],
        "metrics": {"response_bytes": 0, "response_tokens_estimate": 0, "budget_tokens": budget_tokens,
                    "wall_ms": int((time.monotonic() - start) * 1000), "rounds": 0, "planner_retries": 0,
                    "planner_fallbacks": 0},
    }
    if len(reasons) > 20 or len(changed) > 30:
        base["limitations"].append({"code": "lists_truncated",
                                    "detail": f"{len(reasons)} escalation reasons, {len(changed)} changed paths"})
    handle = None
    if not expired:
        handle = f"PC{int(time.time() * 1000) % 10**9}"
        store.put(investigation_id, handle, "patch_run",
                  {"selected": selected, "outcomes": outcomes, "reasons": reasons, "changed": changed},
                  sources=[], truncated_at_capture=False, fingerprint_id=current.fp.fingerprint_id)
    p = Packer(CheckPatchResponse, base, budget_tokens)
    for i, np_ in enumerate(non_passing):
        if not p.try_add(lambda d, x=np_: d["non_passing"].append(x), lambda d: d["non_passing"].pop()):
            p.omit("non_passing", len(non_passing) - i, [handle] if handle else [])
            break
    for i, (n, o) in enumerate(prev.items()):
        if not p.try_add(lambda d, n=n, o=o: d["previously_failing_now"].__setitem__(n, o),
                         lambda d, n=n: d["previously_failing_now"].pop(n)):
            p.omit("previously_failing_now", len(prev) - i, [handle] if handle else [])
            break
    # In full mode every test is selected for the same reason; the count says it all.
    for i, s in enumerate(selected if mode_e is PatchMode.AFFECTED else []):
        if not p.try_add(lambda d, x=s: d["selected"].append(x), lambda d: d["selected"].pop()):
            p.omit("selected_tests", len(selected) - i, [handle] if handle else [])
            break
    return p.finalize()
