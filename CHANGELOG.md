## Unreleased — source search redesign (2026-10-18)

- Add search_code MCP tool and search CLI command with bounded AST source
  retrieval, static dependencies/callers, exact-symbol lookup and seen IDs.
- Budget the complete search MCP result and remove forced upfront schemas.
- Add retrieval measurements, retain negative controls and version future
  repair trials as v4; prevent raw-record overwrites and mixed-protocol summaries.
- 123 tests pass; new total-session token savings remain unmeasured.

# Changelog

## 0.0.1 — unreleased (updated 2026-10-18)

- Automatic Claude Code hooks: compact reproduction suggestion, crash-site
  injection, auto-captured None-origin cause candidate, and silence rules for
  small repos and test-file crashes. Measured at 29.3% fewer tokens on one
  large real bug (21 runs per side).
- `faultline agent`: an open-model debugging agent (Gemma 4 via the Gemini API,
  or local llama.cpp) with Faultline context; results pending.
- `capture_failure` / `read_capture`, `search_code`.

## 0.0.1 — first prototype (prepared 2026-10-18, not published)

First prototype. See `BUILD_STATUS.md` for verification levels.

- Engine: per-phase coverage + outcomes from one pytest run; explicit xfail
  classes; target-focused Ochiai with exact ties; AST/symtable source index;
  supervised settrace observation worker with before-line semantics,
  frame-exit classification, exact vs lower-bound counts; safe snapshots and
  redaction; fingerprinting with full rehash; evidence store with freshness;
  deterministic packing of complete responses (minimum 800 tokens).
- Planners: state-dependent deterministic planner; local-model planner via
  llama.cpp `llama-server` with per-round enum JSON schema, validation,
  retries and deterministic fallback.
- Tools: `investigate_failure`, `expand_evidence`, `check_patch` (default
  full) via CLI and MCP stdio (mcp 2.3.0).
- Evaluation: five pre-registered injected-bug cases, private hidden tests,
  trial harness for conditions A/C/D with leak audit and independent judge,
  engine-only measurements. No repair-benchmark results yet.

### Claude activation follow-up (2026-10-18)
- Add `install-claude --repo ... [--mode debug|always]`, a project command hook,
  and `/faultline` repair skill; bounded retrieval before agent reasoning.
- Add `path.py:LINE` retrieval without a repository scan; retain the anchor when
  shrinking excerpts. Automatic hook parsing recognizes user-supplied tracebacks.
- Preserve unrelated Claude settings and user-owned skills; no paid-token claim.

### Session-driven hook correction (2026-10-18)
- Defer vague prompt retrieval; suggest compact reproduction for a supplied test.
- Retrieve traceback locations on Bash completion/failure; ignore warning paths.
- Suppress source-parser SyntaxWarnings and separate hook output/context metrics.
- Add saved-session replay and v6 benchmark label; preserve v5 result records.

### Failure capture milestone (2026-10-18)
- Add capture_failure/read_capture MCP tools and capture/read-capture CLI commands.
- Retain bounded test output and safe local-value transitions in private local artifacts.
- Add None-origin candidate summaries, variable-filtered reads, fingerprinted reuse,
  stale-page labels, timeouts and retention limits. No complete causal-proof claim.
- Update Claude guidance and v8 harness labels; retain historical measurements.
