"""One open-model agent trial: (case, A|H, trial) with a local or Gemini provider.

A = agent without Faultline context; H = agent with Faultline context (same code
path as the Claude Code hooks). Fresh git checkout per trial, the agent runs in a
subprocess, then the same independent hidden-test judge as run_trial.py.
Token counts come from the provider's own usage fields, summed over all calls."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PY, ROOT, case, fresh_checkout, private_digest, tests_digest  # noqa: E402
from run_trial import judge  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case_id")
    ap.add_argument("condition", choices=["A", "H"])
    ap.add_argument("trial", type=int)
    ap.add_argument("--provider", choices=["local", "gemini"], required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--endpoint", default=None)
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--out", default=str(ROOT / "eval" / "results" / "agent"))
    args = ap.parse_args()
    c = case(args.case_id)
    work = Path(tempfile.mkdtemp(prefix=f"fl-agent-{args.case_id}-{args.condition}-"))
    checkout = fresh_checkout(c["id"], work / "checkout")
    baseline_tests = tests_digest(checkout, c.get("tests_dir", "tests"))
    rec_path = work / "agent.json"
    cmd = [PY, "-m", "faultline.cli", "agent", c["visible_failing"], "--repo", str(checkout), "--python", PY,
           "--provider", args.provider, "--faultline", "on" if args.condition == "H" else "off",
           "--max-steps", str(args.max_steps), "--out", str(rec_path), "--quiet"]
    if args.model:
        cmd += ["--model", args.model]
    if args.endpoint:
        cmd += ["--endpoint", args.endpoint]
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = time.monotonic()
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=3600)
    agent = json.loads(rec_path.read_text()) if rec_path.exists() else {"status": "harness_error",
                                                                         "stderr": proc.stderr[-500:]}
    record = {
        "kind": "open_model_agent_trial", "case": c["id"], "category": c["category"], "condition": args.condition,
        "trial": args.trial, "provider": args.provider, "model_requested": args.model, "started_at": started,
        "harness_wall_s": round(time.monotonic() - t0, 1), "protocol": "agent-v1",
        "private_store_sha256_at_run": private_digest(), "agent": agent,
        "judge": judge(c, checkout, baseline_tests, work),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = f"{c['id']}-{args.condition}-t{args.trial}-{args.provider}.json"
    (out / name).write_text(json.dumps(record, indent=1))
    print(json.dumps({"case": c["id"], "condition": args.condition, "trial": args.trial, "status": agent.get("status"),
                      "correct": record["judge"]["correct"], "tokens": (agent.get("usage") or {}).get("total_tokens")}))
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
