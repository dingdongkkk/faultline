"""Engine-only measurements on the frozen cases (no repairing agent, no Claude usage).

For each case and planner: investigation status, rounds, retries/fallbacks,
wall time, response size, and where the ground-truth faulty line(s) rank
(derived from the private reference fix: lines of the buggy file it changes).
Ranks are reported as (tie-group index, group size) because order within a
tie group is meaningless."""

import difflib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from common import PRIVATE, PY, ROOT, case_source, fresh_checkout, manifest, private_digest  # noqa: E402

from faultline.config import load_config  # noqa: E402
from faultline.evidence import EvidenceStore  # noqa: E402
from faultline.orchestrator import investigate  # noqa: E402


def faulty_lines(c) -> set[tuple[str, int]]:
    ref = PRIVATE / "cases" / c["id"] / "reference"
    out = set()
    for p in ref.rglob("*.py"):
        rel = p.relative_to(ref).as_posix()
        old = (case_source(c["id"]) / rel).read_text().splitlines()
        new = p.read_text().splitlines()
        for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, old, new).get_opcodes():
            if tag in ("replace", "delete"):
                out |= {(rel, ln) for ln in range(i1 + 1, i2 + 1)}
            elif tag == "insert":  # missing code: the lines around the insertion point
                out |= {(rel, ln) for ln in (i1, i1 + 1) if 1 <= ln <= len(old)}
    return out


def main(endpoint: str | None) -> int:
    rows = []
    for c in manifest()["cases"]:
        truth = faulty_lines(c)
        for planner in ["deterministic"] + (["local-model"] if endpoint else []):
            with tempfile.TemporaryDirectory() as t:
                co = fresh_checkout(c["id"], Path(t) / "co")
                cfg = load_config(str(co), PY, state_dir=str(Path(t) / "state"), model_endpoint=endpoint)
                store = EvidenceStore(cfg)
                r = investigate(cfg, store, c["visible_failing"], planner=planner)
                rk = store.get(r.investigation_id, "RK")[0]["payload"] if r.ranking else None
                rank = None
                if rk:
                    for gi, g in enumerate(rk["groups"], 1):
                        if any((path, line) in truth for path, line, _, _ in g):
                            rank = [gi, len(g)]
                            break
                rounds = [store.get(r.investigation_id, f"PR{i}")[0]["payload"] for i in range(1, r.metrics.rounds + 1)]
                observed_truth = any(
                    (o["path"], o["line"]) in truth
                    for f in (Path(t) / "state").glob("*/inv/*/items/O*.json")
                    for o in [json.loads(f.read_text())["payload"]])
                rows.append({
                    "case": c["id"], "category": c["category"], "planner": planner, "status": r.status.value,
                    "stopping_reason": r.stopping_reason.value, "faulty_line_rank": rank,
                    "faulty_line_observed": observed_truth,
                    "actions": [rd["action"]["action"] for rd in rounds],
                    "retries": r.metrics.planner_retries, "fallbacks": r.metrics.planner_fallbacks,
                    "wall_ms": r.metrics.wall_ms, "response_bytes": r.metrics.response_bytes,
                    "planner_model": r.metrics.planner_model,
                })
                print(json.dumps(rows[-1]), flush=True)
    out = ROOT / "eval" / "results" / f"engine-only-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"private_store_sha256": private_digest(), "rows": rows}, indent=1))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
