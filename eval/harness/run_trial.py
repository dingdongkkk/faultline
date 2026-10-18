"""Run ONE evaluation trial: (case, condition, trial index) -> one JSON record.

Conditions (EVALUATION.md):
  A  ordinary tools only
  C  ordinary tools + Faultline (planner forced to deterministic)
  D  ordinary tools + Faultline (planner forced to local-model; llama-server must be running)
  B  (debugger MCP) is not implemented.

Each trial: fresh git checkout of the visible case -> one headless `claude -p`
session with an identical prompt -> event-log leak audit -> independent judge in
a separate copy with hidden tests overlaid. Hidden tests never enter the agent's
checkout. Missing metrics are recorded as null, never 0.

--dry-run-fix {reference,trap,none} replaces the agent with a scripted edit
(no model usage) to test the harness itself; such records are marked dry_run.
"""

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
from common import PRIVATE, PY, ROOT, case, fresh_checkout, overlay, run_pytest, tests_digest  # noqa: E402

PROMPT = ("The test {test} fails in this repository. Find and fix the bug in the application code so the "
          "intended behavior holds. Do not modify any test files. Use the tools available to you. "
          "When you are done, state briefly what you changed.")
# Protocol v4: same neutral prompt, new search tool, no forced upfront schemas.
# Historical v3 results are retained and must not be pooled with v4.
ORDINARY_TOOLS = ["Read", "Edit", "Glob", "Grep", "Bash(python -m pytest *)", "Bash(pytest *)"]
FAULTLINE_TOOLS = ["mcp__faultline__capture_failure", "mcp__faultline__read_capture", "mcp__faultline__search_code", "mcp__faultline__investigate_failure", "mcp__faultline__expand_evidence",
                   "mcp__faultline__check_patch"]


def deny_rules() -> list[str]:
    priv, repo = str(PRIVATE.resolve()), str(ROOT)
    rules = []
    for path in (priv, repo):
        rules += [f"Read(/{path}/**)", f"Edit(/{path}/**)", f"Bash(*{path}*)"]
    rules += ["Bash(*faultline-eval-private*)"]
    return rules


def mcp_config(work: Path, checkout: Path, planner: str, endpoint: str | None) -> Path:
    args = ["-m", "faultline.cli", "serve", "--repo", str(checkout), "--python", PY,
            "--state-dir", str(work / "state"), "--force-planner", planner]
    if endpoint:
        args += ["--model-endpoint", endpoint]
    cfg = {"mcpServers": {"faultline": {"command": PY, "args": args, "env": {"PYTHONPATH": str(ROOT / "src")}}}}
    p = work / "mcp.json"
    p.write_text(json.dumps(cfg))
    return p


def parse_events(path: Path) -> dict:
    tools: dict[str, int] = {}
    final = None
    init = None
    hooks = {"events": 0, "context_bytes": 0, "output_bytes": 0, "context_excerpt": None}
    n = 0
    for line in path.read_text().splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        n += 1
        if "hook" in str(ev.get("subtype", "")) or "hook" in str(ev.get("type", "")):
            hooks["events"] += 1
            output = ev.get("output", "")
            if isinstance(output, str):
                hooks["output_bytes"] += len(output.encode())
                start = output.find('{"hookSpecificOutput"')
                if start >= 0:
                    try:
                        payload, _ = json.JSONDecoder().raw_decode(output[start:])
                        text = payload.get("hookSpecificOutput", {}).get("additionalContext", "")
                        if isinstance(text, str) and text.startswith("Faultline"):
                            hooks["context_bytes"] += len(text.encode())
                            hooks["context_excerpt"] = text[:300]
                    except (ValueError, AttributeError):
                        pass
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            init = {"mcp_servers": ev.get("mcp_servers"),
                    "faultline_tools_offered": sorted(t for t in (ev.get("tools") or []) if "faultline" in t)}
        if ev.get("type") == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tools[block.get("name", "?")] = tools.get(block.get("name", "?"), 0) + 1
        elif ev.get("type") == "result":
            final = ev  # the final result record carries the deduplicated session usage
    out = {"events": n, "init": init, "hooks": hooks, "tool_calls": tools, "tool_calls_total": sum(tools.values())}
    if final is None:
        out.update(result_record=False)
        return out
    u = final.get("usage") or {}
    out.update(result_record=True, is_error=final.get("is_error"), subtype=final.get("subtype"),
               num_turns=final.get("num_turns"), duration_ms=final.get("duration_ms"),
               duration_api_ms=final.get("duration_api_ms"), models=sorted((final.get("modelUsage") or {})),
               permission_denials=len(final.get("permission_denials") or []),
               usage={k: u.get(k) for k in ("input_tokens", "cache_creation_input_tokens",
                                            "cache_read_input_tokens", "output_tokens")},
               final_text=(final.get("result") or "")[:600])
    return out


def leak_audit(path: Path, c: dict) -> list[str]:
    """Private-store needles are checked in every event. The Faultline repo path is checked
    everywhere except hook events (rev 2): the automatic-retrieval hook's own injected text
    names the CLI command, which is not an agent access."""
    if not path.exists():
        return []
    strict = [str(PRIVATE), "faultline-eval-private", Path(c["hidden"]).name]
    hits: set[str] = set()
    for line in path.read_text().splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            ev = {}
        hits |= {n for n in strict if n and n in line}
        if str(ROOT) in line and not str(ev.get("subtype", "")).startswith("hook_"):
            hits.add(str(ROOT))
    return sorted(hits)


def faultline_metrics(work: Path) -> dict | None:
    inv_root = None
    for p in (work / "state").glob("*/inv"):
        inv_root = p
    if inv_root is None:
        return None
    invs, patches = [], 0
    for d in sorted(inv_root.iterdir()):
        m = json.loads((d / "manifest.json").read_text())
        invs.append({"status": m.get("status"), "target": m.get("target"), "metrics": m.get("metrics")})
        patches += len(list((d / "items").glob("PC*.json"))) if (d / "items").exists() else 0
    return {"investigations": invs, "patch_checks": patches}


def judge(c: dict, checkout: Path, baseline_tests: str, work: Path) -> dict:
    jdir = work / "judge"
    shutil.copytree(checkout, jdir, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    td = c.get("tests_dir", "tests")
    unchanged = tests_digest(jdir, td) == baseline_tests
    visible = run_pytest(jdir)
    overlay(PRIVATE / "cases" / c["id"] / "hidden", jdir / td)
    full = run_pytest(jdir)
    diff = subprocess.run(["git", "-C", str(checkout), "diff", "--stat"], capture_output=True, text=True).stdout
    return {"tests_unchanged": unchanged, "visible_passed": visible["exit"] == 0,
            "visible_and_hidden_passed": full["exit"] == 0,
            "hidden_failures": sum(1 for f in full["failed"] if "hidden" in f),
            "correct": bool(unchanged and full["exit"] == 0), "diff_stat": diff.strip()[-400:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case_id")
    ap.add_argument("condition", choices=["A", "C", "D", "H"])
    ap.add_argument("trial", type=int)
    ap.add_argument("--model-endpoint", default=None)
    ap.add_argument("--model", default=None, help="main agent model passed to claude --model (recorded)")
    ap.add_argument("--llama-state", choices=["cold", "warm", "n/a"], default="n/a")
    ap.add_argument("--out", default=str(ROOT / "eval" / "results" / "v4"))
    ap.add_argument("--dry-run-fix", choices=["reference", "trap", "none"], default=None)
    args = ap.parse_args()
    if args.condition == "D" and not (args.model_endpoint or args.dry_run_fix):
        ap.error("condition D needs --model-endpoint (running llama-server)")
    c = case(args.case_id)
    out = Path(args.out)
    name = f"{c['id']}-{args.condition}-t{args.trial}{'-dry' if args.dry_run_fix else ''}.json"
    if (out / name).exists() or (out / name.replace(".json", ".events.jsonl")).exists():
        ap.error("refusing to overwrite a prior trial; choose a new trial index or output directory")
    work = Path(tempfile.mkdtemp(prefix=f"fl-trial-{args.case_id}-{args.condition}-"))
    checkout = fresh_checkout(c["id"], work / "checkout")
    baseline_tests = tests_digest(checkout, c.get("tests_dir", "tests"))
    events = work / "events.jsonl"
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = time.monotonic()
    claude_version = None
    if args.dry_run_fix:
        if args.dry_run_fix != "none":
            overlay(PRIVATE / "cases" / c["id"] / args.dry_run_fix, checkout)
        events.write_text(json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 0,
                                      "duration_ms": 0, "usage": {}, "result": "dry run"}) + "\n")
    else:
        claude_version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
        tools = ORDINARY_TOOLS + (FAULTLINE_TOOLS if args.condition in ("C", "D", "H") else [])
        if args.condition == "H":  # Astra's automatic retrieval: project hook + skill, plus MCP
            tools = tools + ["Skill"]
            inst = subprocess.run([PY, "-m", "faultline.cli", "install-claude", "--repo", str(checkout)],
                                  capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=str(ROOT / "src")))
            if inst.returncode != 0:
                raise SystemExit(f"install-claude failed: {inst.stderr[-300:]}")
        prompt = PROMPT.format(test=c["visible_failing"])
        cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--include-hook-events",
               "--verbose", "--allowedTools", *tools, "--disallowedTools", *deny_rules(), "--strict-mcp-config"]
        if args.model:
            cmd += ["--model", args.model]
        if args.condition in ("C", "D", "H"):
            planner = "local-model" if args.condition == "D" else "deterministic"
            cmd += ["--mcp-config", str(mcp_config(work, checkout, planner, args.model_endpoint))]
        env = dict(os.environ, PATH=f"{Path(PY).parent}:{os.environ.get('PATH', '')}")
        with open(events, "w") as f:
            subprocess.run(cmd, cwd=checkout, stdout=f, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                           env=env, timeout=1800)
    wall = round(time.monotonic() - t0, 2)
    leaks = leak_audit(events, c)
    record = {
        "case": c["id"], "category": c["category"], "condition": args.condition, "trial": args.trial,
        "dry_run": args.dry_run_fix, "started_at": started, "harness_wall_s": wall,
        "claude_version": claude_version, "llama_state": args.llama_state,
        "private_store_sha256_at_run": __import__("common").private_digest(),
        "protocol": "v9-auto-capture" if args.condition == "H" else "v8-capture-optional" if args.condition in ("C", "D") else "v4-search-neutral-deferred",
        "model_requested": args.model,
        "agent": parse_events(events), "faultline": faultline_metrics(work),
        "leak_audit_hits": leaks, "leak_audit_rev": 2, "valid": not leaks,
        "judge": judge(c, checkout, baseline_tests, work),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(record, indent=1))
    # Keep the raw event log for audit (it passed the leak audit; hidden tests never enter the checkout).
    shutil.copy2(events, out / name.replace(".json", ".events.jsonl"))
    print(json.dumps({k: record[k] for k in ("case", "condition", "trial", "valid")} | {"correct": record["judge"]["correct"]}))
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
