"""Milestone-1 contract checks: examples validate, schemas are in sync,
the planner action vocabulary is closed, and status/phase vocabularies
match the specification."""

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from faultline import contracts as c

ROOT = Path(__file__).resolve().parent.parent
ACTION = TypeAdapter(c.PlannerActionEnvelope)


def _load(name):
    return json.loads((ROOT / "examples" / name).read_text())


def test_sample_observation_validates():
    obs = c.Observation.model_validate(_load("sample_observation.json"))
    assert obs.event is c.ObservationEvent.BEFORE_LINE
    assert obs.values["customer"].kind == "opaque"
    assert obs.values["api_token"].kind == "redacted"


def test_investigate_example_validates_and_metrics_match_payload():
    raw = _load("investigate_response.json")
    resp = c.InvestigateResponse.model_validate(raw)
    compact = resp.model_dump_json(exclude_none=True).encode()
    assert resp.metrics.response_bytes == len(compact)
    assert resp.metrics.response_tokens_estimate == -(-len(compact) // 3)
    assert resp.metrics.response_tokens_estimate <= resp.metrics.budget_tokens
    first = resp.comparisons[0]
    assert first.aligned[first.first_divergence_index].relation == "differs"


def test_exported_schemas_are_current():
    from scripts_export import MODELS  # noqa: F401  (see conftest)

    for name, model in MODELS.items():
        on_disk = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
        assert on_disk == model.model_json_schema(), f"run scripts/export_schemas.py ({name})"


def test_planner_example_is_valid():
    env = ACTION.validate_python(_load("planner_action.json"))
    assert env.next.action == "inspect_locations"


@pytest.mark.parametrize(
    "bad",
    [
        {"next": {"action": "run_shell", "cmd": "rm -rf /"}},
        {"next": {"action": "stop", "reason": "done", "extra": 1}},
        {"next": {"action": "stop", "reason": "because_i_said_so"}},
        {"next": {"action": "inspect_locations", "location_ids": [], "test_ids": ["t0"]}},
        {"next": {"action": "inspect_locations", "location_ids": ["L1"] * 6, "test_ids": ["t0"]}},
        {"next": {"action": "inspect_locations", "location_ids": ["../etc/passwd"], "test_ids": ["t0"]}},
        {"next": {"action": "inspect_locations", "location_ids": ["L1"], "locals": ["a.b"], "test_ids": ["t0"]}},
        {"next": {"action": "inspect_locations", "location_ids": ["L1"], "locals": ["__import__('os')"], "test_ids": ["t0"]}},
        {"next": {"action": "inspect_function", "function_id": "F1", "test_ids": ["t0", "t1", "t2"]}},
        {"next": {"action": "compare_observations", "failing_run_id": "R1"}},
    ],
)
def test_planner_vocabulary_is_closed(bad):
    with pytest.raises(ValidationError):
        ACTION.validate_python(bad)


def test_status_vocabulary_matches_spec():
    assert {s.value for s in c.InvestigationStatus} == {
        "completed", "inconclusive", "failure_not_reproduced", "insufficient_coverage",
        "unsupported", "timed_out", "execution_error",
    }


def test_contract_models_reject_unknown_fields():
    with pytest.raises(ValidationError):
        c.SnapshotValue(kind="int", value=1, repr="evil")


def test_limits_have_sane_relations():
    lim = c.ExecutionLimits()
    assert lim.budget_tokens_min <= 2000 <= lim.budget_tokens_cap
    assert lim.timeout_seconds_default <= lim.timeout_seconds_cap
    assert lim.max_probes_per_action == 5 and lim.max_tests_per_action == 2


def test_nullable_fields_default_to_none_so_compact_serialization_round_trips():
    import inspect
    import types
    import typing

    from pydantic import BaseModel

    offenders = []
    for name, model in inspect.getmembers(c, inspect.isclass):
        if not (issubclass(model, BaseModel) and model.__module__ == c.__name__):
            continue
        for field_name, field in model.model_fields.items():
            ann = field.annotation
            nullable = typing.get_origin(ann) in (typing.Union, types.UnionType) and type(None) in typing.get_args(ann)
            if nullable and field.is_required():
                offenders.append(f"{name}.{field_name}")
    assert offenders == []


def test_review_vocabulary_present():
    assert {x.value for x in c.XfailClass} >= {"xfail", "xpass", "xpass_strict", "xfail_raises_mismatch"}
    assert c.ExclusionReason.UNRELATED_FAILURE.value == "unrelated_failure"
    assert {"return", "unwind", "exit_ambiguous"} <= {e.value for e in c.ObservationEvent}
    assert "partial_match" in {r.value for r in c.Reproduction}
    assert "incomplete" in c.AlignedValue.model_fields["alignment"].annotation.__args__


def test_hit_counts_carry_exactness():
    with pytest.raises(ValidationError):
        c.HitCount(count=3)  # exactness is mandatory
    assert c.HitCount(count=3, exact=False).exact is False
