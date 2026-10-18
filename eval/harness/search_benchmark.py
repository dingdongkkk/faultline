"""Retrieval-only benchmark; no model, subscription, hidden tests or repairs.

Cases and queries below are development checks, not a held-out benchmark.
Compare actual serialized MCP result bytes against two explicit rg baselines.
Keep losses and target misses. Never equate bytes/3 with actual session usage.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from mcp.types import CallToolResult, TextContent
from faultline import __version__
from faultline.config import load_config
from faultline.search import search_code, terms

CASES = [
    ("tiny_control", "tests/fixtures/shop", "bulk threshold", "tests/test_cart.py::test_bulk_threshold", "shop/cart.py", "bulk_rate"),
    ("invoicing", "eval/cases/e6_invoicing", "JPY invoice wrong total", "tests/test_invoice.py::test_invoice_jpy", "invoicing/currency.py", "minor_units"),
    ("sessions", "eval/cases/e7_sessions", "session across midnight AM", "tests/test_report.py::test_session_across_midnight", "activity/timeparse.py", "parse_12h"),
    ("project_search", "src/faultline", "response budget omissions", None, "budget.py", "pack_investigation"),
    ("exact_symbol_control", "src/faultline", "ochiai_squared", None, "ranking.py", "ochiai_squared"),
]


def measure(text):
    return len(CallToolResult(content=[TextContent(type="text", text=text)],
                              _meta={"io.modelcontextprotocol/serverInfo":
                                     {"name": "faultline", "version": __version__}})
               .model_dump_json(by_alias=True, exclude_none=True).encode())


def run(case, root, query, test, target_path, target_symbol):
    cfg = load_config(str(root), sys.executable)
    # A capable user may use one exact identifier; retain that advantage.
    words = [query] if re.fullmatch(r"[A-Za-z_]\w*", query) else sorted(terms(query))
    pattern = "|".join(re.escape(t) for t in words)
    common = ["rg", "-i", "-e", pattern, "-g", "*.py"]
    listing = subprocess.run(common + ["-l", "."], cwd=root, capture_output=True, check=False)
    context = subprocess.run(common + ["-n", "-C", "8", "."], cwd=root, capture_output=True, check=False)
    if listing.returncode not in (0, 1) or context.returncode not in (0, 1):
        raise RuntimeError("rg failed")
    paths = sorted(listing.stdout.decode().splitlines())
    whole = listing.stdout + b"\n".join(p.encode() + b"\n" + (root / p).read_bytes() for p in paths)
    start = time.monotonic()
    result = search_code(cfg, query, test, 1200, measure=measure)
    elapsed = round((time.monotonic() - start) * 1000, 2)
    again = search_code(cfg, query, test, 1200, [h.id for h in result.hits], measure)
    accumulated = result.hits + again.hits
    third = search_code(cfg, query, test, 1200, [h.id for h in accumulated], measure)
    accumulated += third.hits
    hit = any(h.path == target_path and h.symbol == target_symbol for h in result.hits)
    tree = hashlib.sha256()
    for p in sorted(root.rglob("*.py")):
        tree.update(p.relative_to(root).as_posix().encode() + p.read_bytes())
    return {"case": case, "query": query, "test": test, "source_sha256": tree.hexdigest(),
            "target": target_path + "::" + target_symbol, "target_returned": hit,
            "rg_context_mentions_target": target_symbol.encode() in context.stdout,
            "rg_read_files_bytes": len(whole), "rg_context_8_bytes": len(context.stdout),
            "faultline_mcp_bytes": result.response_bytes, "faultline_est_tokens": result.tokens_estimate,
            "reduction_vs_read_files_pct": round(100 * (1 - result.response_bytes / max(1, len(whole))), 1),
            "reduction_vs_rg_context_pct": round(100 * (1 - result.response_bytes / max(1, len(context.stdout))), 1),
            "search_ms": elapsed, "files_scanned": result.scanned_files,
            "followup_bytes": again.response_bytes, "followup_suppressed": again.suppressed,
            "three_calls_bytes": result.response_bytes + again.response_bytes + third.response_bytes,
            "target_within_three_calls": any(h.path == target_path and h.symbol == target_symbol for h in accumulated),
            "followup_repeated_ids": len({h.id for h in result.hits} & {h.id for h in again.hits}),
            "returned": [h.path + "::" + h.symbol for h in result.hits]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists():
        raise SystemExit("Refusing to overwrite prior measurements; choose a new output path")
    rows = [run(name, ROOT / path, query, test, target, symbol) for name, path, query, test, target, symbol in CASES]
    # Explicit synthetic scale check: many independently callable functions,
    # not blank padding; all share domain words, one exact symbol is requested.
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        source = "\n".join(f"def normalize_record_{i}(record):\n    value = record.get('amount', 0)\n    return max(0, value) * {i+1}\n"
                           for i in range(200))
        (p / "records.py").write_text(source)
        rows.append(run("synthetic_200_functions", p, "normalize_record_137", None, "records.py", "normalize_record_137"))
    report = {"protocol": "search-v1-development", "scope": "retrieval bytes only; no agent token or repair claims",
              "budget": "1200 estimated units, UTF-8 bytes / 3; complete MCP result",
              "baselines": "rg OR query terms + read matched files; rg same pattern -C 8; no MCP overhead charged to baselines",
              "cases": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for r in rows:
        print(r["case"], "target=", r["target_returned"], "bytes=", r["faultline_mcp_bytes"],
              "vs files=", r["reduction_vs_read_files_pct"], "vs rg=", r["reduction_vs_rg_context_pct"])


if __name__ == "__main__":
    main()
