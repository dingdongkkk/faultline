"""Export JSON Schemas for the public contracts into schemas/."""

import json
from pathlib import Path

from faultline import contracts as c

OUT = Path(__file__).resolve().parent.parent / "schemas"
MODELS = {
    "capture_response": c.CaptureResponse,
    "capture_page": c.CapturePage,
    "capture_payload": c.CapturePayload,
    "search_response": c.SearchResponse,
    "investigate_response": c.InvestigateResponse,
    "expand_response": c.ExpandResponse,
    "check_patch_response": c.CheckPatchResponse,
    "planner_action": c.PlannerActionEnvelope,
    "observation": c.Observation,
    "config": c.FaultlineConfig,
}

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, model in MODELS.items():
        (OUT / f"{name}.schema.json").write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")
        print("wrote", name)
