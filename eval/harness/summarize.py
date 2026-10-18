"""Summarize trial records into a per-case x condition table.

Reports every valid trial (including local-model runs that fell back),
keeps per-trial outcomes visible, and prints missing metrics as 'n/a'.
No cost or savings arithmetic is performed."""

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def fmt(x):
    return "n/a" if x is None else (f"{x:.0f}" if isinstance(x, float) else str(x))


def main(results_dir: str) -> int:
    records = [json.loads(p.read_text()) for p in sorted(Path(results_dir).glob("*.json"))]
    recs = [r for r in records if "agent" in r and "condition" in r]
    real = [r for r in recs if not r.get("dry_run")]
    invalid = [r for r in real if not r["valid"]]
    cells = defaultdict(list)
    for r in real:
        if r["valid"]:
            cells[(r.get("protocol", "legacy"), r["case"], r["condition"])].append(r)
    print(f"records={len(recs)} real={len(real)} invalid(leak)={len(invalid)} dry_run={len(recs) - len(real)}")
    hdr = ["protocol", "case", "cond", "n", "correct", "per-trial", "med_turns", "med_out_tok", "med_in+cache_tok",
           "med_tool_calls", "fl_invest", "fl_statuses", "fl_fallbacks", "med_wall_s"]
    print(" | ".join(hdr))
    for (protocol, cid, cond), rs in sorted(cells.items()):
        u = [r["agent"].get("usage") or {} for r in rs]
        intot = [None if any(x.get(k) is None for k in ("input_tokens", "cache_creation_input_tokens",
                                                        "cache_read_input_tokens"))
                 else x["input_tokens"] + x["cache_creation_input_tokens"] + x["cache_read_input_tokens"] for x in u]
        fl = [r["faultline"] for r in rs]
        statuses = [i["status"] for f in fl if f for i in f["investigations"]]
        fallbacks = [((i.get("metrics") or {}).get("planner_fallbacks")) for f in fl if f for i in f["investigations"]]
        row = [protocol, cid, cond, len(rs), sum(r["judge"]["correct"] for r in rs),
               "".join("Y" if r["judge"]["correct"] else "N" for r in rs),
               fmt(med([r["agent"].get("num_turns") for r in rs])),
               fmt(med([x.get("output_tokens") for x in u])), fmt(med(intot)),
               fmt(med([r["agent"].get("tool_calls_total") for r in rs])),
               sum(len(f["investigations"]) for f in fl if f) if any(fl) else "n/a",
               ",".join(sorted(set(filter(None, statuses)))) or "n/a",
               sum(x for x in fallbacks if x is not None) if any(x is not None for x in fallbacks) else "n/a",
               fmt(med([r["harness_wall_s"] for r in rs]))]
        print(" | ".join(str(x) for x in row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[1] / "results")))
