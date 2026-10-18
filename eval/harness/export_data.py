"""Export every real Claude Code session record to eval/export/ (CSV) and every
open-model agent trial to eval/export/agent_sessions.csv. Missing values stay blank."""

import csv
import glob
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval" / "export"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows, agent_rows = [], []
    for f in sorted(glob.glob(str(ROOT / "eval/results/**/*.json"), recursive=True)):
        try:
            r = json.load(open(f))
        except (ValueError, OSError):
            continue
        if not isinstance(r, dict) or r.get("dry_run"):
            continue
        rel = Path(f).relative_to(ROOT / "eval/results").as_posix()
        batch = rel.rsplit("/", 1)[0] if "/" in rel else "root"
        if r.get("kind") == "open_model_agent_trial":
            a, u = r["agent"], r["agent"].get("usage") or {}
            agent_rows.append({"batch": batch, "case": r["case"], "condition": r["condition"], "trial": r["trial"],
                               "provider": r["provider"], "model": a.get("model"), "status": a.get("status"),
                               "correct": r["judge"]["correct"], "steps": a.get("steps"),
                               "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
                               "thinking_tokens": u.get("thinking_tokens"), "total_tokens": u.get("total_tokens"),
                               "faultline_injections": a.get("faultline_injections"), "wall_seconds": a.get("wall_seconds"),
                               "file": rel})
            continue
        if "agent" not in r or "judge" not in r:
            continue
        a, u, h = r["agent"], r["agent"].get("usage") or {}, r["agent"].get("hooks") or {}
        tools = a.get("tool_calls") or {}
        keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        total = None if any(u.get(k) is None for k in keys) else sum(u[k] for k in keys)
        rows.append({"batch": batch, "started_at": r.get("started_at"), "case": r["case"], "category": r.get("category"),
                     "condition": r["condition"], "trial": r["trial"], "protocol": r.get("protocol"),
                     "model": (a.get("models") or [None])[0], "claude_version": r.get("claude_version"),
                     "valid": r.get("valid"), "correct": r["judge"]["correct"], "turns": a.get("num_turns"),
                     "input_tokens": u.get("input_tokens"), "cache_creation_tokens": u.get("cache_creation_input_tokens"),
                     "cache_read_tokens": u.get("cache_read_input_tokens"), "input_plus_cache_tokens": total,
                     "output_tokens": u.get("output_tokens"), "duration_ms": a.get("duration_ms"),
                     "faultline_mcp_calls": sum(v for k, v in tools.items() if k.startswith("mcp__")),
                     "hook_events": h.get("events"), "hook_context_bytes": h.get("context_bytes"),
                     "tool_calls_json": json.dumps(tools, sort_keys=True), "file": rel})
    with open(OUT / "all_sessions.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    cells = defaultdict(list)
    for r in rows:
        cells[(r["batch"], r["model"], r["case"], r["condition"], r["protocol"])].append(r)
    summ = []
    for (b, m, c, cond, p), xs in sorted(cells.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        tots = [x["input_plus_cache_tokens"] for x in xs if x["input_plus_cache_tokens"] is not None]
        summ.append({"batch": b, "model": m, "case": c, "condition": cond, "protocol": p, "n": len(xs),
                     "correct": sum(bool(x["correct"]) for x in xs),
                     "turns": " ".join(str(x["turns"]) for x in sorted(xs, key=lambda x: x["trial"])),
                     "mean_input_plus_cache": round(statistics.mean(tots)) if tots else None,
                     "median_input_plus_cache": statistics.median(tots) if tots else None,
                     "min": min(tots) if tots else None, "max": max(tots) if tots else None,
                     "faultline_mcp_calls": sum(x["faultline_mcp_calls"] for x in xs)})
    with open(OUT / "summary_by_cell.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summ[0]))
        w.writeheader()
        w.writerows(summ)
    if agent_rows:
        with open(OUT / "agent_sessions.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(agent_rows[0]))
            w.writeheader()
            w.writerows(agent_rows)
    print(f"{len(rows)} Claude sessions, {len(summ)} cells, {len(agent_rows)} open-model agent trials")


if __name__ == "__main__":
    main()
