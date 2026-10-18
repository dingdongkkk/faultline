# Active redesign checkpoint — source retrieval

User-authorized implementation on 2026-10-18 supersedes the earlier runtime-first
product route. M1–M8 below remain historical engine milestones.

| Step | Acceptance | Status |
|---|---|---|
| S1 Search API | Original source, static links, exact-symbol lookup, bounded scan, versioned excerpt IDs | implemented |
| S2 MCP/CLI | search_code, search command, actual MCP-result budget, no forced alwaysLoad | implemented and protocol-tested |
| S3 Development measurements | rg/read and rg-context baselines, target recall, losses retained, no overwrite | recorded; tuned on these cases |
| S4 Independent validation | Freeze unseen real search tasks and small controls before running | pending |
| S5 Agent tokens | v4 neutral sessions, whole-session usage and correctness, no-use counted | pending; no agent sessions launched for redesign |
| S6 Local reranking | Same search engine with/without bounded local model; reject added overhead without benefit | proposed, not implemented |

See [SEARCH_REDESIGN.md](docs/SEARCH_REDESIGN.md). Do not label S3 as S5.
Next Claude task: freeze independent cases, then run approved v4 sessions;
retain the exact-symbol and tiny-file controls and report all misses.

---

# Implementation plan

Checkpoints are gates: each ends with tests passing and `BUILD_STATUS.md`
updated. Order follows the brief; one adjustment is noted.

| # | Checkpoint | Exit criteria | State |
|---|---|---|---|
| M1 | Contracts + review packet (this) | contracts, schemas, examples, policy docs, contract tests; Astra packet; **stop for review** | done |
| M2 | Baseline run + Ochiai | `_probe/cov_plugin`, `execution.py`, `ranking.py`; hand-checkable fixtures: ties across distinct (ef,ep), zero denominators, module/session fixtures, xfail/xpass/skip, setup/teardown errors, parametrized IDs, collection error, rerun/xdist rejection | done |
| M3 | AST extraction + safe tracing | `source.py` (nested functions, decorators, lambdas, overlap merge); `snapshot.py` (exact-type expansion, opaque subclasses, hostile `__repr__`/properties/`__iter__` never invoked, cycles, bounds, redaction); `worker.py` (timeout → killpg → reap, verified no orphan); before-line timing test | done |
| M4 | Evidence, freshness, packing, patch check | fingerprint incl. untracked/uncommitted edits; stale/expired/truncated expansion; packer fits complete response at 600/2000/8000; patch escalation rules each tested | done |
| M5 | Deterministic planner + full workflow | end-to-end on fixtures: tied case, same-path wrong value, inconclusive case; every status reachable by a fixture | done |
| M6 | Local-model adapter + live gate | **ask user to approve exact artifact + size**; llama.cpp build/version recorded; schema-constrained output; retries/fallback; measure RSS/memory pressure and cold/warm latency on this Mac; gate: valid action rate and non-repeat on representative fixtures | done (gate passed on attempt 3; see below) |
| M7 | MCP + CLI | MCP SDK v2 `MCPServer` (re-verify API); stdio smoke test; then a real client session (Claude Code) recorded separately | done (protocol tests + one real-client session) |
| M8 | Evaluation, demo, docs, release prep | 3–5 preselected cases; conditions C vs D at minimum; manual protocol for authenticated runs; LICENSE/NOTICE/attribution; no publishing without instruction | prepared; repair trials pending approval |

Adjustment: the evidence store/fingerprint (M4) is started minimally inside M2
(run IDs + source identities on every record) so ranking output never exists
without provenance; this avoids retrofitting IDs later.

One-day vertical slice target (after M1 approval): failing fixture → tied
ranking → one real local-model observation choice → measured values →
compact MCP response → agent fix → full test check, plus one inconclusive
case. If the model or a correctness gate fails, report the prototype as-is.

Deferred: cache reuse, sophisticated trace alignment, async/thread/subprocess
observation, non-pytest runners, model sweeps, dashboards.

## M6 live planning gate: criteria fixed 2026-10-18, before the first live run

Model: `Qwen3-4B-Q4_K_M.gguf` (sha256 `7485fe6f…fdf5`) on llama-server
b11669. Settings: temperature 0, seed 0, max_tokens 256, ctx 4096, thinking
disabled, schema-constrained output.

**Cases** (5, fixed in advance), each run twice with
`planner="local-model"` and default budgets and rounds:
- shop `test_bulk_threshold[10-1000]`
- money `test_small`
- registry `test_b_lookup_default` (expected inconclusive)
- misc `test_lambda` (module-level top line)
- ochiai_basic `test_two`

**Pass criteria.** The gate passes only if all of these hold:
1. No crash or unhandled exception, and every response validates against
   the contract.
2. At least 70% of model-planned rounds execute a model-chosen action, i.e.
   no deterministic fallback. Retries are allowed.
3. Zero executed actions that failed validation or repeated an earlier
   action (checked from the round records).
4. Median warm inference wall time is at most 5 s per call.
5. The llama-server RSS and system memory pressure are recorded, and
   pressure is not "critical".

**Reported but not gating:** first-attempt validity, retry and fallback
reasons, determinism across the two runs, and statuses compared with the
deterministic planner.

The gate checks feasibility only. It says nothing about whether model
choices are better; that is the C-vs-D evaluation.

### Gate attempts (all recorded in `eval/live_gate/`)

| Attempt | Change before it | Model action rate | First-attempt valid | Median s/call | Result |
|---|---|---|---|---|---|
| 1 | none (static pydantic schema) | 0.500 | 0.192 | 2.40 | **failed** criterion 2 |
| 2 | per-round enum schema | 0.583 | 0.500 | 2.38 | **failed** criterion 2. The gate script also missed rounds dropped from packed responses |
| 3 | executed actions shown as JSON, repeat quoted in feedback; script reads rounds from the evidence store | 0.833 | 0.733 | 1.55 | **passed** all 5 |

Caveat: all three attempts used the same five fixture cases, and the
adapter was changed between attempts. The pass therefore shows feasibility
on these fixtures, not generalization. The evaluation must use different,
preselected cases.
