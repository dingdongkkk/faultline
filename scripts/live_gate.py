"""M6 live planning gate (criteria in IMPLEMENTATION_PLAN.md). Requires a running
local llama-server. Writes raw per-run records to eval/live_gate/."""

import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from faultline.config import load_config  # noqa: E402
from faultline.contracts import InvestigateResponse  # noqa: E402
from faultline.evidence import EvidenceStore  # noqa: E402
from faultline.orchestrator import investigate  # noqa: E402

CASES = [
    ("shop", "tests/test_cart.py::test_bulk_threshold[10-1000]", []),
    ("money", "tests/test_money.py::test_small", []),
    ("registry", "tests/test_registry.py::test_b_lookup_default", []),
    ("misc", "tests/test_misc.py::test_lambda", ["-k", "not slow_under_observation"]),
    ("ochiai_basic", "tests/test_a.py::test_two", []),
]


def server_rss_mib():
    out = subprocess.run(["pgrep", "-f", "llama-server -m"], capture_output=True, text=True).stdout.split()
    if not out:
        return None
    rss = subprocess.run(["ps", "-o", "rss=", "-p", out[0]], capture_output=True, text=True).stdout.strip()
    return round(int(rss) / 1024) if rss else None


def pressure():
    out = subprocess.run(["memory_pressure"], capture_output=True, text=True).stdout.strip().splitlines()
    return out[-1] if out else None


def main(endpoint: str, repeats: int = 2) -> int:
    records = []
    for rep in range(repeats):
        for fixture, target, args in CASES:
            for planner in ("local-model", "deterministic"):
                tmp = Path(tempfile.mkdtemp(prefix="fl-gate-"))
                shutil.copytree(ROOT / "tests" / "fixtures" / fixture, tmp / fixture)
                cfg = load_config(str(tmp / fixture), sys.executable, pytest_args=args, state_dir=str(tmp / "state"),
                                  model_endpoint=endpoint)
                t = time.monotonic()
                err = None
                store = EvidenceStore(cfg)
                try:
                    r = investigate(cfg, store, target, planner=planner)
                    InvestigateResponse.model_validate_json(r.model_dump_json())
                    d = json.loads(r.model_dump_json(exclude_none=True))
                    # All rounds from the evidence store: the packed response may omit some under budget.
                    d["planner_rounds"] = [store.get(r.investigation_id, f"PR{i}")[0]["payload"]
                                           for i in range(1, r.metrics.rounds + 1)]
                except Exception as e:  # noqa: BLE001 - recorded, gate criterion 1
                    d, err = None, f"{type(e).__name__}: {e}"
                records.append({"repeat": rep, "fixture": fixture, "target": target, "planner": planner,
                                "wall_s": round(time.monotonic() - t, 2), "error": err,
                                "status": d and d["status"], "stopping_reason": d and d["stopping_reason"],
                                "metrics": d and d["metrics"], "rounds": d and d["planner_rounds"],
                                "server_rss_mib": server_rss_mib()})
                shutil.rmtree(tmp, ignore_errors=True)
                print(rep, fixture, planner, records[-1]["status"], records[-1]["wall_s"], err or "", flush=True)
    model_rounds = [rd for rec in records if rec["planner"] == "local-model" and rec["rounds"] for rd in rec["rounds"]]
    executed_model = [rd for rd in model_rounds if not rd["fallback_used"]]
    first_try = [rd for rd in model_rounds if rd["attempts"] == 1 and not rd["fallback_used"]]
    per_call = [rd["inference_ms"] / rd["attempts"] for rd in model_rounds if rd.get("inference_ms") and rd["attempts"]]
    summary = {
        "runs": len(records), "errors": sum(1 for r in records if r["error"]),
        "model_rounds": len(model_rounds), "model_action_rate": round(len(executed_model) / max(1, len(model_rounds)), 3),
        "first_attempt_valid_rate": round(len(first_try) / max(1, len(model_rounds)), 3),
        "fallback_reasons": sorted({rd.get("fallback_reason") for rd in model_rounds if rd["fallback_used"]} - {None}),
        "rejections": [rj for rd in model_rounds for rj in rd["rejected"]],
        "median_ms_per_call": statistics.median(per_call) if per_call else None,
        "max_ms_per_call": max(per_call) if per_call else None,
        "server_rss_mib_max": max((r["server_rss_mib"] or 0) for r in records),
        "memory_pressure_end": pressure(),
    }
    summary["gate"] = {
        "1_no_errors": summary["errors"] == 0,
        "2_model_action_rate>=0.7": summary["model_action_rate"] >= 0.7,
        "3_no_invalid_or_repeat_executed": True,  # verified below
        "4_median_call<=5s": summary["median_ms_per_call"] is not None and summary["median_ms_per_call"] <= 5000,
        "5_pressure_not_critical": "critical" not in (summary["memory_pressure_end"] or "").lower(),
    }
    keys = {}
    for rec in records:
        if rec["planner"] != "local-model" or not rec["rounds"]:
            continue
        seen = set()
        for rd in rec["rounds"]:
            k = json.dumps(rd["action"], sort_keys=True)
            if k in seen and rd["action"]["action"] != "stop":
                summary["gate"]["3_no_invalid_or_repeat_executed"] = False
            seen.add(k)
        keys.setdefault((rec["fixture"]), []).append([rd["action"]["action"] for rd in rec["rounds"]])
    summary["determinism_action_sequences"] = keys
    summary["passed"] = all(summary["gate"].values())
    out = ROOT / "eval" / "live_gate" / f"gate-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps({"summary": summary, "records": records}, indent=1))
    print(json.dumps(summary, indent=1))
    print("wrote", out)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8089"))
