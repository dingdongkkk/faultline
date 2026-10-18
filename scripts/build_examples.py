"""Regenerate examples/investigate_response.json from the contracts.

The example is illustrative (hand-written values, not a real run). It is
serialized exactly as the packer will serialize responses: compact JSON with
None fields excluded, so its size metrics are honest for that payload.
"""

import json
from pathlib import Path

from faultline import contracts as c

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"


def dump(model) -> str:
    return model.model_dump_json(exclude_none=True)


def main() -> None:
    obs = c.Observation.model_validate_json((EX / "sample_observation.json").read_text())
    obs2 = obs.model_copy(update={
        "evidence_id": "O4", "run_id": "R2",
        "timing": c.ObservationTiming(event_seq=4, hit_ordinal=1, t_ns=170020),
        "values": {**obs.values, "qty": c.SnapshotValue(kind="int", value=12)},
    })

    def loc(i, line, fn, ef, ep, score, tie):
        return c.RankedLocation(location_id=i, path="shop/cart.py", line=line, function_id=fn,
                                ef=ef, ep=ep, total_failing=1, score=score, tie_group=tie)

    src = c.SourceIdentity(path="shop/cart.py", sha256="9f2c" + "0" * 60, size=812)
    hits = {"L1:before_line": c.HitCount(count=1, exact=True), "L2:before_line": c.HitCount(count=1, exact=True)}
    run = dict(probe_hits=hits, counts_exact=True, events_captured=2, events_dropped=0,
               truncation=[], unsupported_detected=[], fingerprint_id="fp_3b1e", sources=[src])
    sig = c.FailureSignature(exception_type="builtins.AssertionError", crash_path="tests/test_cart.py",
                             crash_line=14, test_line=14, message_digest="5be1c0d29a4f7e10",
                             message_excerpt="AssertionError: assert 1000 == 900")
    resp = c.InvestigateResponse(
        investigation_id="inv_7Q2K", status="completed", stopping_reason="planner_stopped",
        planner_requested="local-model", fingerprint_id="fp_3b1e",
        reproduced=c.ReproducedFailure(test_nodeid="tests/test_cart.py::test_bulk_threshold[10]",
                                       baseline_run_id="B1", signature=sig, isolated="reproduced"),
        ranking=c.RankingSummary(
            total_failing=1, total_passing=7, unrelated_failing=0, excluded={"skipped": 1}, ranked_line_count=9,
            unattributed_line_count=14, setup_teardown_only_line_count=2,
            tie_groups=[
                c.TieGroup(tie_group="T1", rank=1, size=2, shown=2, member_location_ids=["L1", "L2"],
                           distinct_count_pairs=[(1, 1)]),
                c.TieGroup(tie_group="T2", rank=2, size=4, shown=1, member_location_ids=["L3"],
                           distinct_count_pairs=[(1, 3)]),
            ],
            locations=[loc("L1", 15, "F2", 1, 1, 0.7071, "T1"), loc("L2", 19, "F3", 1, 1, 0.7071, "T1"),
                       loc("L3", 22, "F4", 1, 3, 0.5, "T2")]),
        excerpts=[c.SourceExcerpt(
            excerpt_id="S1", source=src, function_id="F2", qualname="bulk_rate",
            region=c.LineRange(start=13, end=16), shown=[c.LineRange(start=13, end=16)], omitted=[],
            text="  13| def bulk_rate(qty, tiers=TIERS):\n  14|     if qty >= min(tiers):\n"
                 "  15|         return tiers[min(tiers)]\n  16|     return 0",
            truncated=False)],
        observation_runs=[
            c.ObservationRun(run_id="R1", test_nodeid="tests/test_cart.py::test_bulk_threshold[10]",
                             role="target", reproduction="reproduced", call_outcome="failed",
                             duration_ms=410, **run),  # signature omitted: equals baseline
            c.ObservationRun(run_id="R2", test_nodeid="tests/test_cart.py::test_bulk_threshold[12]",
                             role="comparator", reproduction="not_applicable", call_outcome="passed",
                             duration_ms=395, **run),
        ],
        observations=[obs],  # O4 (comparator) is represented in C1 -> omitted with a handle
        comparisons=[c.Comparison(
            evidence_id="C1", failing_run_id="R1", passing_run_id="R2",
            comparator_reason="covers_F2;jaccard=0.91;nodeid_order",
            aligned=[c.AlignedValue(probe_id="L1", event="before_line", hit_ordinal=1,
                                    alignment="unambiguous", name="qty",
                                    failing=c.SnapshotValue(kind="int", value=10),
                                    passing=c.SnapshotValue(kind="int", value=12), relation="differs")],
            hit_count_differences={}, first_divergence_index=0)],
        unresolved=["T1 member L2 (shop/cart.py:19) not distinguished by observations"],
        planner_rounds=[
            c.PlannerRound(round=1, planner="local-model", attempts=2, rejected=["unknown_local:discount"],
                           fallback_used=False,
                           action=c.InspectLocations(action="inspect_locations", location_ids=["L1", "L2"],
                                                     locals=["qty", "tiers", "customer", "api_token"],
                                                     test_ids=["t0", "t1"]),
                           rationale_untrusted="Both tied lines are on the bulk path; check qty at the threshold.",
                           inference_ms=1840, prompt_tokens=1210, completion_tokens=61),
            c.PlannerRound(round=2, planner="local-model", attempts=1, rejected=[], fallback_used=False,
                           action=c.Stop(action="stop", reason="sufficient_evidence"),
                           inference_ms=640, prompt_tokens=1490, completion_tokens=14),
        ],
        limitations=[
            c.Limitation(code="before_line_semantics", detail="Line observations show locals before the line executes."),
            c.Limitation(code="association_not_causation",
                         detail="Ochiai scores and divergences are associations, not proof of the root cause."),
        ],
        omissions=[c.Omission(kind="tie_group_members", count=3, evidence_ids=["T2"]),
                   c.Omission(kind="excerpt", count=1, evidence_ids=["S2"]),
                   c.Omission(kind="observation_in_comparison", count=1, evidence_ids=[obs2.evidence_id])],
        metrics=c.ResponseMetrics(response_bytes=0, response_tokens_estimate=0,
                                  budget_tokens=2000, wall_ms=6120,
                                  coverage_run_ms=1980, observation_ms=805, planner_ms=2480, rounds=2,
                                  planner_retries=1, planner_fallbacks=0))

    # Fixed point: the metrics describe the final serialized payload, metrics included.
    for _ in range(3):
        n = len(dump(resp).encode())
        resp = resp.model_copy(update={"metrics": resp.metrics.model_copy(
            update={"response_bytes": n, "response_tokens_estimate": -(-n // 3)})})
    assert len(dump(resp).encode()) == resp.metrics.response_bytes
    (EX / "investigate_response.json").write_text(json.dumps(json.loads(dump(resp)), indent=1) + "\n")
    (EX / "planner_action.json").write_text(json.dumps({"next": {
        "action": "inspect_locations", "location_ids": ["L1", "L2"], "locals": ["qty", "tiers"],
        "test_ids": ["t0", "t1"], "rationale": "Tied lines on the bulk path."}}, indent=1) + "\n")
    print(f"compact bytes={resp.metrics.response_bytes} est_tokens={resp.metrics.response_tokens_estimate}")


if __name__ == "__main__":
    main()
