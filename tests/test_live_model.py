"""Live local-model tests. Skipped unless FAULTLINE_MODEL_ENDPOINT points at a
running llama-server (e.g. http://127.0.0.1:8089). Mocks never stand in here."""

import os

import pytest

from faultline.evidence import EvidenceStore
from faultline.orchestrator import investigate

ENDPOINT = os.environ.get("FAULTLINE_MODEL_ENDPOINT")
pytestmark = [pytest.mark.live_model,
              pytest.mark.skipif(not ENDPOINT, reason="FAULTLINE_MODEL_ENDPOINT not set")]


def test_live_model_plans_valid_actions_on_shop(make_project):
    cfg = make_project("shop", model_endpoint=ENDPOINT)
    store = EvidenceStore(cfg)
    r = investigate(cfg, store, "tests/test_cart.py::test_bulk_threshold[10-1000]", planner="local-model")
    rounds = [store.get(r.investigation_id, f"PR{i}")[0]["payload"] for i in range(1, r.metrics.rounds + 1)]
    assert rounds and rounds[0]["planner"] == "local-model"
    assert r.metrics.planner_model and r.metrics.planner_model.startswith("Qwen3-4B-Q4_K_M.gguf@")
    assert any(not rd["fallback_used"] for rd in rounds)  # at least one model-chosen action executed
    assert r.status.value in ("completed", "inconclusive")
    # Every executed action was validated by the engine; rationale kept separate.
    assert all(rd["action"].get("rationale", "") == "" for rd in rounds)
