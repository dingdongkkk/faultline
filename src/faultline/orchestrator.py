"""Bounded investigation: baseline -> rank -> isolated reproduction ->
planner/observe rounds -> status -> packed response (+ persisted evidence)."""

from __future__ import annotations

import json
import secrets
import threading
import time
from functools import partial

from . import fingerprint as fpmod
from .budget import InvestigationParts, pack_investigation
from .comparison import align, select_comparators
from .config import is_app_path
from .contracts import (
    CompareObservations,
    ExclusionReason,
    FaultlineConfig,
    InspectFunction,
    InspectLocations,
    InvestigateResponse,
    InvestigationStatus,
    Limitation,
    Observation,
    PlannerKind,
    Reproduction,
    StoppingReason,
    Stop,
    TestClass,
)
from .evidence import EvidenceStore, baseline_manifest
from .execution import Baseline, run_baseline
from .planners import Completion, FuncView, LocView, PlannerView, RunView, normalized_key, plan_round
from .ranking import Ranking, call_coverage_by_test, display_score, rank
from .source import SourceIndex, build_excerpt, index_file
from .worker import FunctionProbe, LineProbe, WorkerResult, run_observation, to_observation

MAX_LOCATION_IDS = 50
MAX_EXCERPTS = 4
_XFAIL_EXCLUSIONS = {ExclusionReason.XFAIL, ExclusionReason.XPASS, ExclusionReason.XPASS_STRICT,
                     ExclusionReason.XFAIL_RAISES_MISMATCH, ExclusionReason.XFAIL_MARKED_UNKNOWN}

BASE_LIMITATIONS = [
    Limitation(code="before_line_semantics", detail="values are before the line runs"),
    Limitation(code="association_not_causation", detail="scores/divergences are hints, not proof"),
]


class _Deadline(Exception):
    pass


class _WorkspaceChanged(Exception):
    pass


class Investigation:
    def __init__(self, cfg: FaultlineConfig, store: EvidenceStore, failing_test: str, budget_tokens: int,
                 max_rounds: int, timeout_seconds: int, planner: str, completion: Completion | None,
                 cancel: threading.Event | None):
        lim = cfg.limits
        if not lim.budget_tokens_min <= budget_tokens <= lim.budget_tokens_cap:
            raise ValueError(f"budget_tokens must be in [{lim.budget_tokens_min}, {lim.budget_tokens_cap}]")
        if not 1 <= max_rounds <= lim.max_rounds_cap:
            raise ValueError(f"max_rounds must be in [1, {lim.max_rounds_cap}]")
        if not 1 <= timeout_seconds <= lim.timeout_seconds_cap:
            raise ValueError(f"timeout_seconds must be in [1, {lim.timeout_seconds_cap}]")
        self.cfg, self.store, self.target = cfg, store, failing_test
        self.budget, self.max_rounds = budget_tokens, max_rounds
        self.planner = PlannerKind(planner)
        self.cancel = cancel
        self.model_id: str | None = None
        if completion is None and self.planner is PlannerKind.LOCAL_MODEL and cfg.model_endpoint:
            from .llama import LlamaServerCompletion

            completion = LlamaServerCompletion(cfg.model_endpoint, max_tokens=lim.planner_max_output_tokens)
        self.completion = completion
        self.t0 = time.monotonic()
        self.deadline = self.t0 + timeout_seconds
        self.id = "inv_" + secrets.token_hex(5)
        self.is_app = partial(is_app_path, cfg)
        self.limitations: list[Limitation] = list(BASE_LIMITATIONS)
        self.unresolved: list[str] = []
        self.runs: list[WorkerResult] = []
        self.run_roles: dict[str, str] = {}  # run_id -> alias
        self.observations: dict[str, list[Observation]] = {}  # run_id -> observations
        self.comparisons = []
        self.rounds = []
        self.excerpts = []
        self.done_keys: set[str] = set()
        self.done_actions: list[str] = []
        self.next_obs = 1
        self.coverage_ms = None
        self.observation_ms = 0
        self.planner_ms = 0
        self.timed_out = False
        self.baseline: Baseline | None = None
        self.ranking: Ranking | None = None
        self.loc_ids: dict[tuple[str, int], str] = {}
        self.locs: dict[str, LocView] = {}
        self.funcs: dict[str, FuncView] = {}
        self.func_info: dict[str, tuple[str, str, int]] = {}  # F id -> (path, qualname, start)
        self.indexes: dict[str, SourceIndex] = {}
        self.tests: dict[str, str] = {}
        self.comparator_reasons: dict[str, str] = {}
        self.f0: fpmod.Snapshot | None = None

    # -- helpers -----------------------------------------------------------------
    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def _check_time(self, need: float = 0.5) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise _Deadline("cancelled")
        if self.remaining() < need:
            raise _Deadline("deadline")

    def _check_workspace(self) -> None:
        now = fpmod.compute(self.cfg)
        if now.fp.fingerprint_id != self.f0.fp.fingerprint_id:
            d = fpmod.diff(self.f0.files, self.f0.components, False, now)
            self.limitations.append(Limitation(
                code="workspace_changed",
                detail="Checkout changed during the investigation: " + ", ".join(
                    (d.changed + d.added + d.deleted)[:5] + d.components)))
            raise _WorkspaceChanged()

    def _put(self, eid: str, kind: str, payload: dict, sources=(), truncated=False) -> None:
        ok = self.store.put(self.id, eid, kind, payload, sources=list(sources), truncated_at_capture=truncated,
                            fingerprint_id=self.f0.fp.fingerprint_id)
        if not ok and not any(lim.code == "evidence_store_cap" for lim in self.limitations):
            self.limitations.append(Limitation(code="evidence_store_cap",
                                               detail="Store cap reached; later evidence is not expandable."))

    # -- main ------------------------------------------------------------------------
    def run(self) -> InvestigateResponse:
        status, reason = InvestigationStatus.EXECUTION_ERROR, StoppingReason.INTERNAL_ERROR
        try:
            status, reason = self._run()
        except _Deadline as e:
            self.timed_out = True
            status = InvestigationStatus.TIMED_OUT
            reason = StoppingReason.CANCELLED if str(e) == "cancelled" else StoppingReason.TIME_BUDGET_EXHAUSTED
        except _WorkspaceChanged:
            status, reason = InvestigationStatus.EXECUTION_ERROR, StoppingReason.WORKSPACE_CHANGED
        if self.timed_out and status is not InvestigationStatus.EXECUTION_ERROR:
            status = InvestigationStatus.TIMED_OUT
        return self._respond(status, reason)

    def _run(self):
        S, R = InvestigationStatus, StoppingReason
        self.f0 = fpmod.compute(self.cfg)
        if self.f0.fp.partial:
            self.limitations.append(Limitation(code="fingerprint_partial",
                                               detail="; ".join(self.f0.fp.partial_reasons[:5])))
        self._check_time()
        b = self.baseline = run_baseline(self.cfg, self.target, timeout_s=self.remaining(), cancel=self.cancel)
        self.coverage_ms = b.duration_ms
        supported = not (b.unsupported or b.collect_errors or b.error or b.timed_out)
        self.store.create(self.id, baseline_manifest(self.id, self.target, b, self.f0, supported))
        if b.timed_out or b.cancelled:
            raise _Deadline("cancelled" if b.cancelled else "deadline")
        self._check_workspace()
        if b.collect_errors:
            self.limitations.append(Limitation(code="collection_error",
                                               detail=f"{len(b.collect_errors)} collection error(s): "
                                                      + b.collect_errors[0]["nodeid"]))
            return S.EXECUTION_ERROR, R.COLLECTION_ERROR
        if b.error:
            self.limitations.append(Limitation(code="baseline_error", detail=b.error[:300]))
            return S.EXECUTION_ERROR, R.WORKER_FAILURE
        if b.unsupported:
            self.limitations.append(Limitation(code="unsupported_execution", detail=", ".join(b.unsupported)))
            return S.UNSUPPORTED, R.UNSUPPORTED_EXECUTION
        rec = b.records.get(self.target)
        if rec is None:
            self.limitations.append(Limitation(code="target_not_collected", detail=self.target))
            return S.FAILURE_NOT_REPRODUCED, R.BASELINE_NOT_FAILING
        if rec.exclusion in _XFAIL_EXCLUSIONS or rec.exclusion in (
                ExclusionReason.SETUP_FAILED, ExclusionReason.TEARDOWN_FAILED, ExclusionReason.TRACE_CONFLICT,
                ExclusionReason.INCOMPLETE_PHASES):
            self.limitations.append(Limitation(code="target_unsupported", detail=f"target {rec.exclusion.value}"))
            return S.UNSUPPORTED, R.UNSUPPORTED_EXECUTION
        if rec.klass is not TestClass.TARGET_FAILING:
            return S.FAILURE_NOT_REPRODUCED, R.BASELINE_NOT_FAILING

        rk = self.ranking = rank(b, self.target, self.is_app)
        if rk.unrelated_failing:
            self.limitations.append(Limitation(
                code="target_focused_ranking",
                detail=f"F=1: {len(rk.unrelated_failing)} other failing test(s) excluded from ranking."))
        self._put("RK", "ranking", {"groups": [[[m.path, m.line, m.ef, m.ep] for m in g.members] for g in rk.groups],
                                    "excluded": {k.value: v for k, v in rk.excluded.items()},
                                    "unrelated_failing": rk.unrelated_failing})
        if not rk.groups:
            return S.INSUFFICIENT_COVERAGE, R.NO_RANKABLE_LINES
        self._mint_ids()
        self._make_excerpts()
        self._pick_comparators()

        # Isolated reproduction check (target alone, no probes).
        self._check_time()
        iso = self._observe(self.target, [], role="reproduction_check")
        self.isolated = iso.run.reproduction
        if self.isolated is not Reproduction.REPRODUCED:
            self.limitations.append(Limitation(
                code="isolated_reproduction_failed",
                detail=f"Target alone: {self.isolated.value}. Suite ranking kept; runtime values may not "
                       f"reflect the failing state."))
            self.unresolved.append(f"failure does not reproduce in isolation ({self.isolated.value}); "
                                   f"possible order dependence or shared state")

        reason = R.MAX_ROUNDS
        for r in range(1, self.max_rounds + 1):
            self._check_time()
            view = self._view(rounds_left=self.max_rounds - r + 1)
            res = plan_round(self.planner, view, r, completion=self._bounded_completion() if self.completion else None,
                             max_retries=self.cfg.limits.planner_max_retries, deadline=self.remaining)
            self.planner_ms += res.elapsed_ms
            self.rounds.append(res.record)
            self._put(f"PR{r}", "planner_round", res.record.model_dump(mode="json"))
            a = res.action
            if isinstance(a, Stop):
                reason = R.PLANNER_STOPPED if a.reason != "no_useful_action" else R.NO_NEW_ACTIONS
                break
            self.done_keys.add(normalized_key(a))
            self.done_actions.append(json.dumps(a.model_dump(exclude={"rationale"}), sort_keys=True,
                                                separators=(",", ":")))
            self._execute(a)
        return self._decide(), reason

    def _bounded_completion(self):
        """Bind the HTTP timeout of a real model client to the remaining deadline."""
        from .llama import LlamaServerCompletion
        from .planners import ModelUnavailable

        c = self.completion
        if not isinstance(c, LlamaServerCompletion):
            return c
        if self.model_id is None:
            try:
                self.model_id = c.model_id(timeout=min(5.0, max(1.0, self.remaining())))
            except ModelUnavailable:
                pass
        return lambda prompt, schema: c(prompt, schema, timeout=max(1.0, self.remaining()))

    # -- setup steps ---------------------------------------------------------------------
    def _index(self, path: str) -> SourceIndex | None:
        if path not in self.indexes:
            try:
                self.indexes[path] = index_file(self.cfg, path)
            except (OSError, SyntaxError, ValueError):
                self.indexes[path] = None
        return self.indexes[path]

    def _mint_ids(self) -> None:
        n = 0
        for g in self.ranking.groups:
            for m in g.members:
                if n >= MAX_LOCATION_IDS:
                    return
                n += 1
                lid = f"L{n}"
                self.loc_ids[(m.path, m.line)] = lid
                idx = self._index(m.path)
                fid = None
                cands: tuple[str, ...] = ()
                src = ""
                if idx is not None:
                    fn = idx.innermost_function(m.line)
                    cands = tuple(idx.candidate_locals(m.line))[:16]
                    src = idx.lines[m.line - 1] if m.line - 1 < len(idx.lines) else ""
                    if fn is not None:
                        key = (m.path, fn.qualname, fn.start)
                        fid = next((f for f, v in self.func_info.items() if v == key), None)
                        if fid is None:
                            fid = f"F{len(self.func_info) + 1}"
                            self.func_info[fid] = key
                            self.funcs[fid] = FuncView(fid, m.path, fn.qualname)
                self.locs[lid] = LocView(lid, m.path, m.line, fid, f"T{g.index}", m.ef, m.ep, cands, src)

    def _make_excerpts(self) -> None:
        lim = self.cfg.limits
        groups: list[tuple[str, str | None, list[int]]] = []  # (path, function id, lines)
        for g in self.ranking.groups:
            for m in g.members:
                lid = self.loc_ids.get((m.path, m.line))
                if lid is None:
                    continue
                fid = self.locs[lid].function_id
                for i, (p, f, lines) in enumerate(groups):
                    if p == m.path and f == fid and (fid is not None or abs(lines[-1] - m.line) <= 6):
                        lines.append(m.line)
                        break
                else:
                    if len(groups) < MAX_EXCERPTS:
                        groups.append((m.path, fid, [m.line]))
        for i, (path, fid, lines) in enumerate(groups, 1):
            idx = self._index(path)
            if idx is None:
                continue
            ex = build_excerpt(idx, f"S{i}", lines, function_id=fid, max_lines=lim.excerpt_max_lines,
                               context=lim.excerpt_context_lines)
            self.excerpts.append(ex)
            self._put(ex.excerpt_id, "excerpt", ex.model_dump(mode="json"),
                      sources=[ex.source.model_dump()], truncated=ex.truncated)

    def _pick_comparators(self) -> None:
        top = self.ranking.groups[0].members[0]
        lid = self.loc_ids[(top.path, top.line)]
        fid = self.locs[lid].function_id
        focus = {(top.path, top.line)}
        if fid is not None:
            path, _, start = self.func_info[fid]
            fn = next(f for f in self._index(path).functions if f.start == start)
            focus = {(path, ln) for ln in range(fn.start, fn.end + 1)}
        call_cov = call_coverage_by_test(self.baseline, self.is_app)
        suspects = {(m.path, m.line) for m in self.ranking.groups[0].members}
        self.tests = {"t0": self.target}
        for i, (nodeid, why) in enumerate(select_comparators(self.baseline, self.target, call_cov, focus,
                                                             suspects=suspects), 1):
            self.tests[f"t{i}"] = nodeid
            self.comparator_reasons[nodeid] = why
        if len(self.tests) == 1:
            self.limitations.append(Limitation(code="no_comparator",
                                               detail="No eligible passing test covers the top-ranked function."))
            self.unresolved.append("no passing comparator covers the top-ranked function")

    # -- execution ---------------------------------------------------------------------------
    def _observe(self, nodeid: str, probes, role: str) -> WorkerResult:
        sources = []
        for p in {pr.path for pr in probes}:
            idx = self._index(p)
            if idx is not None:
                sources.append(idx.identity)
        base_sig = self.baseline.records[self.target].signature
        res = run_observation(self.cfg, nodeid=nodeid, probes=probes, role=role, baseline_signature=base_sig,
                              timeout_s=self.remaining(), fingerprint_id=self.f0.fp.fingerprint_id,
                              sources=sources, cancel=self.cancel)
        self.observation_ms += res.run.duration_ms
        self.runs.append(res)
        obs: list[Observation] = []
        bad = 0
        for raw in res.observations:
            try:
                obs.append(to_observation(self.cfg, raw, f"O{self.next_obs}", res.run.run_id))
                self.next_obs += 1
            except (KeyError, TypeError, ValueError):
                bad += 1
        if bad:
            self.limitations.append(Limitation(code="invalid_worker_records", detail=f"{bad} dropped"))
        self.observations[res.run.run_id] = obs
        self._put(res.run.run_id, "run", res.run.model_dump(mode="json"),
                  sources=[s.model_dump() for s in res.run.sources])
        for o in obs:
            self._put(o.evidence_id, "observation", o.model_dump(mode="json"),
                      sources=[s.model_dump() for s in res.run.sources],
                      truncated=any(v.truncated for v in o.values.values()))
        if res.timed_out or res.cancelled:
            raise _Deadline("cancelled" if res.cancelled else "deadline")
        if res.error:
            self.limitations.append(Limitation(code="worker_error", detail=f"{res.run.run_id}: {res.error[:200]}"))
        for u in res.run.unsupported_detected:
            code = f"detected_{u}"
            if not any(lim.code == code for lim in self.limitations):
                self.limitations.append(Limitation(code=code, detail=f"{u} during {res.run.run_id}; "
                                                                     f"observations may be incomplete"))
        self._check_workspace()
        return res

    def _execute(self, a) -> None:
        if isinstance(a, CompareObservations):
            runs = {r.run.run_id: r.run for r in self.runs}
            f, p = runs[a.failing_run_id], runs[a.passing_run_id]
            cid = f"C{len(self.comparisons) + 1}"
            c = align(cid, f, self.observations[f.run_id], p, self.observations[p.run_id],
                      self.comparator_reasons.get(p.test_nodeid, "comparator"))
            self.comparisons.append(c)
            self._put(cid, "comparison", c.model_dump(mode="json"))
            return
        if isinstance(a, InspectLocations):
            probes = []
            for lid in a.location_ids:
                loc = self.locs[lid]
                names = tuple(n for n in a.locals if n in loc.candidate_locals)
                probes.append(LineProbe(lid, loc.path, (loc.line,), names))
        else:  # InspectFunction
            path, qual, start = self.func_info[a.function_id]
            probes = [FunctionProbe(a.function_id, path, qual, start)]
        for alias in a.test_ids:
            self._check_time()
            role = "target" if alias == "t0" else "comparator"
            res = self._observe(self.tests[alias], probes, role)
            self.run_roles[res.run.run_id] = alias

    def _view(self, rounds_left: int) -> PlannerView:
        lim = self.cfg.limits
        groups = []
        for g in self.ranking.groups[:5]:
            ids = [self.loc_ids[(m.path, m.line)] for m in g.members if (m.path, m.line) in self.loc_ids]
            if ids:
                groups.append(ids)
        runs = []
        for r in self.runs:
            if r.run.role == "reproduction_check":
                continue
            probes = frozenset(k.split(":", 1)[0] for k, v in r.run.probe_hits.items() if v.count > 0)
            runs.append(RunView(r.run.run_id, self.run_roles.get(r.run.run_id, "?"), r.run.role,
                                r.run.reproduction.value, r.run.counts_exact, probes))
        return PlannerView(
            target=self.target, locations=self.locs, tie_groups=groups, functions=self.funcs, tests=self.tests,
            runs=runs, comparisons=[(c.evidence_id, c.first_divergence_index is not None) for c in self.comparisons],
            done_keys=set(self.done_keys), done_actions=list(self.done_actions), rounds_left=rounds_left, seconds_left=self.remaining(),
            max_locations=lim.max_probes_per_action, max_locals=lim.max_locals_per_probe)

    # -- status and response ------------------------------------------------------------------
    def _decide(self) -> InvestigationStatus:
        ranked_probes = set(self.locs) | set(self.funcs)
        measured = any(
            o.probe_id in ranked_probes
            for r in self.runs if r.run.role == "target" and r.run.reproduction is Reproduction.REPRODUCED
            for o in self.observations.get(r.run.run_id, []))
        if self.isolated is Reproduction.REPRODUCED and measured:
            return InvestigationStatus.COMPLETED
        if not measured:
            self.unresolved.append("no measured value from a reproducing target run at a ranked location")
        return InvestigationStatus.INCONCLUSIVE

    def _respond(self, status: InvestigationStatus, reason: StoppingReason) -> InvestigateResponse:
        b, rk = self.baseline, self.ranking
        rec = b.records.get(self.target) if b else None
        reproduced = None
        if rec is not None and rec.signature is not None and rec.klass is TestClass.TARGET_FAILING:
            reproduced = {"test_nodeid": self.target, "baseline_run_id": b.run_id,
                          "signature": rec.signature.model_dump(exclude_none=True, exclude={"message_digest"}),
                          "isolated": getattr(self, "isolated", Reproduction.UNKNOWN).value}
        ranking = None
        groups = []
        if rk is not None:
            ranking = {"total_failing": rk.total_failing, "total_passing": rk.total_passing,
                       "unrelated_failing": len(rk.unrelated_failing),
                       "unrelated_failing_sample": rk.unrelated_failing[:3],
                       "excluded": {k.value: v for k, v in rk.excluded.items()},
                       "ranked_line_count": len(rk.lines), "unattributed_line_count": rk.unattributed_line_count,
                       "setup_teardown_only_line_count": rk.setup_teardown_only_line_count,
                       "tie_groups": [], "locations": []}
            for g in rk.groups:
                locs = []
                for m in g.members:
                    lid = self.loc_ids.get((m.path, m.line))
                    if lid is None:
                        continue
                    locs.append({"location_id": lid, "path": m.path, "line": m.line,
                                 "function_id": self.locs[lid].function_id, "ef": m.ef, "ep": m.ep,
                                 "score": display_score(m.sq),
                                 "tie_group": f"T{g.index}"})
                if not locs:
                    break
                tg = {"tie_group": f"T{g.index}", "rank": g.index, "size": len(g.members), "shown": 0,
                      "member_location_ids": [],
                      "distinct_count_pairs": sorted({(m.ef, m.ep) for m in g.members})}
                groups.append((tg, locs))
                if len(g.members) > 1:
                    self._put(f"T{g.index}", "tie_group", {"members": [[m.path, m.line, m.ef, m.ep]
                                                                       for m in g.members]})
            if groups and groups[0][0]["size"] > 1:
                distinguished = {a.probe_id for c in self.comparisons for a in c.aligned if a.relation == "differs"}
                undist = [loc["location_id"] for loc in groups[0][1] if loc["location_id"] not in distinguished]
                if undist:
                    self.unresolved.append(f"T1: {len(undist)} of {groups[0][0]['size']} tied locations show no "
                                           f"differing value ({', '.join(undist[:5])})")

        # De-duplicate: signatures equal to baseline; comparator observations shown in comparisons.
        base_sig = rec.signature if rec else None
        runs = []
        for r in self.runs:
            d = r.run.model_dump(mode="json", exclude_none=True)
            if base_sig is not None and r.run.signature == base_sig:
                d.pop("signature", None)
            runs.append(d)
        in_comparison = {c.passing_run_id for c in self.comparisons} | {c.failing_run_id for c in self.comparisons}
        target_obs, other_obs, pre = [], [], []
        hidden = []
        for r in self.runs:
            for o in self.observations.get(r.run.run_id, []):
                d = o.model_dump(mode="json", exclude_none=True)
                if r.run.run_id in in_comparison:
                    hidden.append(o.evidence_id)
                elif r.run.role == "target":
                    target_obs.append(d)
                else:
                    other_obs.append(d)
        if hidden:
            pre.append({"kind": "observation_in_comparison", "count": len(hidden), "evidence_ids": hidden[:10]})

        retries = sum(max(0, r.attempts - 1) for r in self.rounds)
        fallbacks = sum(1 for r in self.rounds if r.fallback_used)
        if status is InvestigationStatus.COMPLETED:
            self.unresolved = [u for u in self.unresolved if not u.startswith("no measured")]
        base = {
            "investigation_id": self.id, "status": status.value, "stopping_reason": reason.value,
            "planner_requested": self.planner.value,
            "fingerprint_id": self.f0.fp.fingerprint_id if self.f0 else "none",
            "reproduced": reproduced, "ranking": ranking, "excerpts": [], "observation_runs": [],
            "observations": [], "comparisons": [], "unresolved": self.unresolved[:6],
            "planner_rounds": [], "limitations": [lim.model_dump() for lim in self.limitations], "omissions": [],
            "metrics": {"response_bytes": 0, "response_tokens_estimate": 0, "budget_tokens": self.budget,
                        "wall_ms": int((time.monotonic() - self.t0) * 1000), "coverage_run_ms": self.coverage_ms,
                        "observation_ms": self.observation_ms or None, "planner_ms": self.planner_ms or None,
                        "rounds": len(self.rounds), "planner_retries": retries, "planner_fallbacks": fallbacks,
                        "planner_model": self.model_id},
        }
        parts = InvestigationParts(
            base=base, groups=groups, comparisons=[c.model_dump(mode="json", exclude_none=True)
                                                   for c in self.comparisons],
            target_observations=target_obs, other_observations=other_obs,
            excerpts=[e.model_dump(mode="json", exclude_none=True) for e in self.excerpts], runs=runs,
            planner_rounds=[r.model_dump(mode="json", exclude_none=True) for r in self.rounds], pre_omissions=pre)
        resp = pack_investigation(InvestigateResponse, parts, self.budget)
        try:
            self.store.update_manifest(self.id, status=resp.status.value,
                                       metrics=resp.metrics.model_dump(mode="json"))
        except KeyError:
            pass
        return resp


def investigate(cfg: FaultlineConfig, store: EvidenceStore, failing_test: str, budget_tokens: int = 1200,
                max_rounds: int = 3, timeout_seconds: int = 120, planner: str = "deterministic",
                completion: Completion | None = None, cancel: threading.Event | None = None) -> InvestigateResponse:
    return Investigation(cfg, store, failing_test, budget_tokens, max_rounds, timeout_seconds, planner,
                         completion, cancel).run()
