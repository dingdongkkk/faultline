# Build status

Last updated: 2026-10-18 · Milestone: **Failure capture and bounded value-history milestone implemented; capture-specific agent benchmark pending.**

## Latest: capture once and inspect local-value history

Implemented capture_failure/read_capture MCP tools and CLI equivalents. One
fully qualified pytest test produces protected local output artifacts plus a
bounded history of safe local-value changes. Reads paginate/filter without test
reruns. Identical completed captures reuse full matching fingerprints for ten
minutes; edits, configuration changes, partial fingerprints and timeouts receive
explicit handling. Retention is bounded. None-origin candidate summaries show
observed transitions, not proven dataflow. Existing v7 silence rules are retained.

**Impl:** yes (narrow None/wrong-value milestone; general causal slicing and
passing-run alignment remain unimplemented). **Auto:** 153 passed, 1 live-model
test skipped in 39.74 s; includes generated schemas, actual pytest captures,
reuse/edit invalidation, safe snapshots, timeouts, pagination, retention,
trace replacement, candidate summaries, and new real-stdio MCP budget checks.
**Live:** n/a for deterministic capture; no new model run. **Client:** SDK stdio
protocol tested; no fresh Claude capture-tool session. **Bench:** known e8 case,
no variable supplied: 1.2329 s capture, 0.0635 s reuse, 2,721-byte CLI summary,
including None introduced after line 961 and a later list change before the
line-994 crash. This case informed development; it is not held-out causal-proof
or agent-token evidence. Capture-specific total-token savings unmeasured.
**Rel:** not rebuilt. **Pub:** no. Docs: docs/FAILURE_CAPTURE.md.

New H harness records use v8-capture-hook and C/D use v8-capture-optional, keeping
existing v6/v7 records and their results separate. The earlier v6 measurements
below apply to that treatment, not these new tools. New engine-only records:
eval/results/capture-v1-e8-development-01.json and -02.json. No paid agent run.

## Latest: session diagnosis and evidence-timed hooks

Inspected the three Sonnet H raw sessions and A/H metrics. The previous hook
activated but injected unrelated excerpts; each hook output log also contained
45,689 bytes including AST SyntaxWarnings. The agent repeatedly ran pytest to
expose its traceback. Recorded v5 showed no saving (+1.8% median input+cache).
The initial activation fix was insufficient; see docs/SESSION_DIAGNOSIS.md.

**Impl:** prompt retrieval now waits for an explicit source location; test-only
prompts receive a compact reproduction suggestion. Bash PostToolUse and
PostToolUseFailure hooks retrieve actual traceback frames, ignoring warnings.
AST parser warnings are suppressed. Hook context/output metrics are separated;
new H trials use v6, historical records preserved. Reinstalled in this checkout.
**Auto:** 139 passed, 1 skipped in 34.32 s. Generated subprocess hook outputs,
neutral-prompt deferral, warning suppression, boundaries and metrics tested.
Exact large-case initial prompt: 427 bytes stdout, zero stderr, no source guesses.
**Live:** no new inference run. **Client:** prior v5 delivery verified by Claude;
v6 actual client delivery pending (subprocess tests only). **Bench:** offline
replay of saved H logs retrieves the reported crash region in 3/3, 624 bytes per
excerpt; no v6 repair or token benchmark run. **Rel:** not rebuilt. **Pub:** no.

## Latest: automatic Claude activation and precise source locations

User reported that Claude never called Faultline on the large codebase. Recorded
v4 trials confirm zero calls and no demonstrated saving. Implemented project-local
`install-claude`, a UserPromptSubmit hook (debug or always mode), and `/faultline`
repair skill. The hook calls the retrieval engine before agent reasoning and caps
injected text at 1,800 bytes. It is installed in this Faultline checkout; other
projects require their own installation. Existing unrelated settings are retained.
Added `path.py:LINE` retrieval that reads only that file and retains the requested
line even when shrinking the response. No contracts changed.

**Impl:** yes. **Auto:** 132 passed, 1 live-model test skipped in 34.11 s;
includes installed-command subprocess tests, activation, settings preservation,
source boundaries and exact-line retention. **Live:** n/a for source hook;
no new model verification. **Client:** actual Claude hook delivery not verified;
no paid session run. **Bench:** known-location hook check on youtube-dl returned
957–964 around requested line 960, 958 injected bytes, 0.0061 s; this is not a
repair trial or blind discovery. Integrated whole-session token saving remains
unverified. **Rel:** not rebuilt for this change. **Pub:** not published.

See docs/CLAUDE_INTEGRATION.md for installation, limitations and a separate future
hook-treatment benchmark. Historical v4 records and harness protocol are unchanged.
Older status sections below describe earlier milestones, not current test counts.

## Latest: source-search redesign

User explicitly authorized Codex to redesign for search and token efficiency.
Implemented `search_code` + CLI search, lexical/AST ranking, static dependencies
and callers, exact-symbol targeting, current-content excerpt IDs, seen-ID
suppression, bounded source windows and complete MCP-result budgeting.
Removed forced upfront investigate schema loading. Added a search schema,
retrieval tests, stdio search tests, and a retrieval benchmark that preserves
all runs. Historical trials and raw records were not deleted.

Final verification: **123 tests passed, 1 live-model test skipped** in 33.82 s
(`.venv/bin/python -m pytest -q`). Includes retrieval quality/boundary tests,
exact-symbol selectivity, caller discovery, schema checks and actual stdio
search response-budget/suppression verification. No paid agent sessions ran.
Search has no live-model dependency. Existing local inference verification
belongs to the older runtime planner, not the new search route.

Measured development results (run 04): target definition in 5/6 first responses,
6/6 within three calls. Exact-symbol MCP output 1,207 B vs 4,326 B for matching
file reads and 1,844 B for rg with context. Tiny control loses (3,308 vs 1,272 B).
These cases informed tuning. They do not prove generalization or total session
savings. New agent repair/token trials: pending; none launched here.

The harness now records v4 and refuses overwrites. Summaries separate protocols.
See docs/SEARCH_REDESIGN.md for current behavior, limits and the next Claude
handoff. Previously built dist artifacts predate search and must be rebuilt
before release. Publication remains pending.


Levels (each implies nothing about the ones to its right):
**Impl** implemented · **Auto** automatically tested · **Live** live-model
verified · **Client** verified with a real MCP client · **Bench**
repair-benchmarked · **Rel** release-prepared · **Pub** published.

| Area | Impl | Auto | Live | Client | Bench | Rel | Pub |
|---|---|---|---|---|---|---|---|
| Typed contracts (v0.2) + JSON schemas | yes | yes | n/a | no | no | no | no |
| Baseline run: outcomes, per-phase coverage, xfail classes, failure signatures | yes | yes (fixtures) | n/a | no | no | no | no |
| Target-focused Ochiai (F=1), exact fraction ties | yes | yes | n/a | no | no | no | no |
| AST index (symtable locals) + bounded excerpts | yes | yes | n/a | no | no | no | no |
| Observation worker: before-line, frame exits, exact/lower-bound counts | yes | yes (fixtures) | n/a | no | no | no | no |
| Safe snapshots + redaction | yes | yes (hostile objects) | n/a | no | no | no | no |
| Process-group timeout/cleanup | yes | yes (grandchild reaped) | n/a | no | no | no | no |
| Fingerprint / evidence store / freshness / expand | yes | yes | n/a | no | no | no | no |
| Comparisons (count-aware alignment) | yes | yes | n/a | no | no | no | no |
| Deterministic planner (state-dependent) | yes | yes (incl. property test) | n/a | no | no | no | no |
| Planner validation / retries / repeat prevention / fallback | yes | yes (scripted fake model) | **yes** (live gate) | no | no | no | no |
| Local-model adapter (llama-server, per-round enum schema) | yes | yes (schema unit) | **yes** (gate + `live_model` test) | no | no | no | no |
| Response packing (complete response, min 800 tokens) | yes | yes | n/a | no | no | no | no |
| check_patch (default full; affected + escalation) | yes | yes (fixtures) | n/a | no | no | no | no |
| Orchestrator, all 7 statuses reachable | yes | yes (fixtures) | n/a | no | no | no | no |
| CLI (`investigate`, `expand`, `check-patch`, `serve`) | yes | yes (subprocess test) | n/a | n/a | no | no | no |
| MCP adapter (stdio, 3 tools) | yes | yes (stdio protocol tests via SDK Client) | n/a | **yes, one session** (Claude Code CLI 2.1.301, shop fixture) | no | no | no |
| Evaluation harness (A/C/D trials, judge, leak audit) | yes | yes (scripted-agent self-tests) | n/a | n/a | **12 A-vs-C trials (e6, e7): no saving; Faultline never called** | yes | no |
| Docs / license / attribution / packaging | yes | wheel build + clean-venv smoke | n/a | n/a | n/a | **yes (not published)** | no |

**Tests:** 101 pass and 1 is skipped (`.venv/bin/python -m pytest -q`, about
41 s). The skipped one is the `live_model` test, which needs
`FAULTLINE_MODEL_ENDPOINT`; it **passed** against the real server on
2026-10-18. The default tests are fixture and unit tests. They also
include 3 stdio protocol tests, which run the real `faultline serve` process
driven by the MCP SDK's own `Client`. That is protocol verification only:
it does not establish compatibility with a real agent client, or repair
outcomes.

## Review acceptance cases (Astra, M1)

| Case | Status |
|---|---|
| R1 strict XPASS etc. | passing: `test_phase_and_xfail_policy`, `test_status_matrix[...strict_xpass]` |
| R2 failure signatures | passing: `test_reproduction_requires_full_signature`, `test_match_signature_unit` |
| R3 rehash + full-input freshness, editable deps | passing: `test_edit_preserving_size_and_mtime_is_detected`, `test_expand_fresh_then_stale_on_source_and_environment`, `test_affected_escalates_to_full[env]`, `test_editable_dependency_outside_repo_marks_partial` |
| R4 exact vs lower-bound counts | passing: `test_callback_budget_makes_counts_lower_bounds`, `test_lower_bound_counts_never_align_unambiguously` |
| R5 normal vs exceptional exit | passing: `test_frame_exit_classification` |
| R6 state-dependent deterministic plan | passing: `test_deterministic_planner_never_emits_invalid_actions_in_any_state`, `test_module_level_top_line_gets_no_inspect_function` |
| R7 timed_out keeps partial evidence | passing: `test_deadline_during_observation_is_timed_out_with_partial_evidence` |
| D1 F=1 | passing: `test_unrelated_failures_do_not_change_target_ranking` |
| D2 isolation failure → inconclusive, ranking kept | passing: `test_order_dependent_failure_is_inconclusive_with_ranking_kept` |
| D3 patch default full | passing: `test_patch_default_is_full_and_fresh` |
| D4/D5 evaluation reporting / private hidden tests | documented in `docs/EVALUATION.md`; not exercised (no evaluation yet) |

Only the summarized review was supplied, not the full Astra text. These
cases are derived from that summary.

## M6: live model (approved, downloaded, verified)

**Artifact.**
- `Qwen/Qwen3-4B-GGUF@bc640142c66e1fdd12af0bd68f40445458f3869b`, file
  `Qwen3-4B-Q4_K_M.gguf`.
- Download verified: 2,497,280,256 bytes, sha256
  `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`
  (matches the HF LFS oid).
- Stored at
  `~/.cache/faultline-models/qwen3-4b-bc64014/`, outside the repo.

**Runtime.** Homebrew llama.cpp 0.7.0, `llama-server` build b11669 (commit
620d2225c).
- Flags: `--host 127.0.0.1 --port 8089 -c 4096 -np 1 --no-webui
  --reasoning off --jinja`.
- Requests: temperature 0, seed 0, `max_tokens` 256,
  `chat_template_kwargs.enable_thinking=false`,
  `response_format: json_schema` (per-round enum schema).
- **Side effect of the install:** Homebrew also installed `openssl@4` and
  unlinked `openssl@3`. Nothing in Faultline depends on either.

**Verified API behavior** (by experiment on this build):
- the pydantic planner schema (`oneOf` + `discriminator` + `$ref`) and the
  `anyOf`/`enum`/`const` per-round schema are both accepted;
- adversarial prompts still produce schema-shaped JSON;
- no thinking content is emitted.

**Measured on this Mac** (Apple M5, 16 GB):

| Metric | Value |
|---|---|
| first-ever load to healthy (model read from disk) | 15.0 s |
| restart with warm page cache | 0.6 s |
| first request after load | 2.31 s (224 prompt / 33 completion tokens) |
| steady-state request, cached prompt | 1.44 s median |
| live gate median / max per call | 1.55 s / 2.71 s |
| llama-server RSS | 3.0–3.4 GiB |
| system "memory free" (memory_pressure) during the gate | 26–30% |
| swap in use when measured | 9.0 GB of 10 GB. The pre-server baseline was not measured, so this is **not attributed** to the model |
| local-model investigation wall time (gate, 3 rounds) | 6–13 s, vs 1–2 s deterministic |

**Live planning gate.** Criteria were fixed before the first run (see
`IMPLEMENTATION_PLAN.md`); raw records are in `eval/live_gate/`.
- **Attempt 1 failed**: model action rate 0.50; invalid invented IDs.
- **Attempt 2 failed**: 0.58; repeats.
- **Attempt 3 passed**:
  - action rate 0.833 and first-attempt validity 0.733;
  - 0 invalid or repeated actions executed and 0 errors;
  - median 1.55 s per call;
  - action sequences identical across the two repeats.
- The adapter and prompt changed between attempts, on the same 5 fixtures,
  so the pass shows feasibility on these cases, not generalization.
- Statuses matched the deterministic planner on every case. No claim is
  made that model choices are better.

## M7: MCP adapter

**Verified API** (mcp 2.3.0 on PyPI, docs and the installed source):
- `mcp.server.mcpserver.MCPServer`, `tool(name=, structured_output=)` and
  `run(transport="stdio")`;
- `ToolError` produces an `is_error` result;
- sync handlers run in a worker thread;
- the client side is `mcp.Client(StdioServerParameters(...))`.

**Protocol tests** (`tests/test_mcp_protocol.py`, all passing):
- the tool list and argument defaults/enums match the contract;
- investigate → expand → (fix) → check_patch works over stdio;
- the budgeted payload equals the delivered content (5,879 B; the
  `CallToolResult` JSON is 6,912 B);
- bad arguments and unknown IDs come back as `is_error`.

**Real-client check: passed (one session).** On 2026-10-18 the user logged
in the CLI and `scripts/client_check.sh` ran Claude Code CLI 2.1.301
headless, model `claude-opus-5-5`.

- **Setup:** a fresh copy of the shop fixture; tools restricted to the
  Faultline tools plus Read/Edit; `--strict-mcp-config`.
- **Agent outcome:** it changed `if qty >= threshold:` to
  `if qty > threshold:` in `shop/cart.py` and left the tests unchanged. It
  reported that `check_patch` returned `passed` with
  `full_regression_verified: true`.
- **Independent check:** a separate pytest run (not via Faultline) gave 5
  passed.
- **Server side:** the evidence store shows one investigation (status
  `completed`) and one patch run, so `investigate_failure` and
  `check_patch` were really called. Use of `expand_evidence` cannot be
  determined, because expansion writes nothing.
- **CLI-reported session record:**
  - 6 turns, 17.4 s wall (13.3 s API);
  - input 10 tokens, cache-creation 21,014, cache-read 177,920, output 856;
  - 0 permission denials.

  The raw record is `eval/client_check/client-check-20261018.json`.
- **Not a benchmark:** this is one session on one injected-bug fixture with
  no comparison condition. It shows the client integration works, not that
  Faultline improves repair or reduces usage.

## M8: evaluation preparation and release prep

**Cases.** Five injected-bug cases, authored and labelled as such, were
pre-registered. The private store (`~/.faultline-eval-private/`, sha256
`94939a85…3829`) holds the hidden tests, the reference fixes and the E5
trap. All five pass `validate_cases.py`.

**Harness.**
- `run_trial.py` supports A/C/D, pins the planner with
  `serve --force-planner`, applies deny rules and the event-log leak audit,
  and runs an independent judge.
- `summarize.py` produces the per-cell table.
- 9 harness self-tests pass using scripted agents.
- **No real repair trials have been run** (30 planned sessions need
  approval).

**Engine-only** (no agent; see `docs/EVALUATION.md`):
- Statuses matched the pre-registered expectations in 5 of 5 cases.
- The faulty line was in the top tie group in 4 of 5 (e4 is not rankable by
  design).
- D matched C on every case, at 5–7× the wall time with 3 of 15 rounds
  falling back.

**Release prep** (`docs/RELEASE.md`, `CHANGELOG.md`):
- Licenses were checked from installed metadata.
- The wheel and sdist build, the wheel works from a clean venv, and the
  sdist is clean.
- PRIOR_ART entries were checked at the arXiv-abstract level.
- Remaining before any publish: git init, authors/URLs in `pyproject.toml`,
  and a security contact.

## Environment (observed)

Apple M5, 16 GB unified memory, macOS (Darwin 25.4.0), arm64. Python 3.12.14
(Homebrew) in `.venv` via uv 0.12.21. Installed: pydantic 2.14.1, pytest
9.1.1, coverage 7.16.2. Installed for M7: mcp 2.3.0. Installed for M6: llama.cpp 0.7.0
(b11669). Not a git repository.

## Primary-source checks

- coverage.py docs: `sysmon` core lacks dynamic contexts → `ctrace` forced.
- pytest 9.1.1 source (`_pytest/skipping.py`): a strict XPASS is reported as
  failed with `[XPASS(strict)]` and no `wasxfail`; `xfailed_key` is private.
- Python 3.12.14, verified by experiment: a decorated function's
  `co_firstlineno` is the first decorator line; an `exception` event followed
  by `return(None)` means the frame unwound; `symtable.SymbolTableType` does
  not exist on 3.12.
- PyPI `mcp` 2.3.0: `mcp.server.MCPServer`; stdio run API **not yet verified**.
- HF API: the artifact metadata above.
- llama.cpp server README: `json_schema`, `response_format`,
  `chat_template_kwargs`, `--reasoning`, `--reasoning-budget`. The supported
  schema features were **not** confirmed.

## Known limitations (current)

- Thread start detection only sees threads alive at the end of the call.
  Coroutine and async-test observation is unsupported (it is reported).
- The fingerprint includes the environment probe, so each child-run boundary
  costs one extra interpreter start.
- The token estimate is bytes/3, not the agent's tokenizer.
- Affected selection is file-level and conservative; residual risks are
  listed in every affected response.

## Log

- 2026-10-18 **M1**: contracts, schemas, examples, policy docs, Astra
  packet.
- 2026-10-18 **Review applied** (Astra: "proceed after changes"), contract
  0.2:
  - xfail classes, failure signatures, HitCount exactness,
    unwind/exit_ambiguous, partial_match;
  - F=1 policy, patch default full, timed_out on any deadline.
- 2026-10-18 **M2 gate**: baseline plugin, execution, ranking. 41 tests.
- 2026-10-18 **M3 gate**: AST index, excerpts, snapshotter, tracer,
  worker. 59 tests. Bugs found by the tests:
  - bound-method identity made every run look like a trace conflict;
  - a configured `-k` deselected the target in single-test runs;
  - nested defs leaked into enclosing-scope locals.
- 2026-10-18 **M4 gate**: fingerprint, evidence store, expand, packer,
  check_patch. 77 tests. Bugs: the packer added `omissions` to models
  without that field; chunk sizing was off by one wall_ms digit.
- 2026-10-18 **M5 gate**: comparison, planners, orchestrator, CLI. 97
  tests. Changes driven by measurement:
  - comparisons list only non-equal entries;
  - observations of compared runs are de-duplicated;
  - candidate locals come from `symtable` (line names, then params), since
    names on the line alone missed the diverging input;
  - comparison comes before function inspection in the deterministic rules;
  - the packer converges through LIFO drops and labelled compaction;
  - the **minimum budget was raised 600 → 800 tokens** after 600 failed to
    fit reliably.
- 2026-10-18 **M6 gate**: llama-server adapter, per-round enum schema,
  prompt shows executed actions, `metrics.planner_model`, a `live_model`
  test, and the live gate script.
  - Gate results: attempt 1 failed, attempt 2 failed, attempt 3 passed.
  - 98 tests pass and 1 live test is skipped by default (it passes live).
- 2026-10-18 **M7**: MCP stdio adapter (single text block, ToolError
  mapping), `faultline serve`, and 3 stdio protocol tests. 101 tests pass
  and 1 is skipped. The real-client check is blocked on CLI login; the
  ready-to-run script is `scripts/client_check.sh`.
- 2026-10-18 **M7 gate**: real-client check passed (one Claude Code CLI
  session; independent pytest 5 passed).
- 2026-10-18 **M8 prep**: 5 cases pre-registered with a private store,
  validator, trial harness and summarizer, plus engine-only measurements,
  `--force-planner`, persisted investigation metrics, the release docs and
  a build check. No repair trials yet.
- 2026-10-18 **Token-saving pass**:
  - Changes: `alwaysLoad` on `investigate_failure`, terse descriptions,
    default budget 1200, slimmer and reordered packing (trimmed
    comparisons), compact check_patch.
  - Investigate responses went from ~1.9k to ~1.1k tokens; check_patch
    from ~400 to ~270.
  - Engine fixes: `PYTHONHASHSEED=0`, suspect-covering comparators.
  - Added e6 and e7 multi-module cases (new private hash `3cd4188e…`);
    protocol v3 uses a neutral prompt for all conditions.
  - 113 tests pass and 1 is skipped.
  - The agent-level saving is **not yet measured**. The e6 engine-only
    result shows a wrong top suspect.
  - The raw engine-only file from the first C/D measurement was deleted by
    mistake (disclosed in EVALUATION.md).
- 2026-10-18 **First counted trials** (protocol v3, A vs C, e6 and e7, 3
  each):
  - All 12 correct and valid.
  - Faultline was offered but **never called** in any of the 6 C sessions;
    the agent read the whole package with one `cat`.
  - C cost ~1.5% more input+cache tokens (upfront tool definition), with
    the same turn count. **No token saving demonstrated.**

- 2026-10-18 **Search redesign final gate**: 123 passed / 1 live-model skip;
  retrieval development runs 01–04 preserved. v4 agent-token evaluation pending.
- 2026-10-18 **Independent check of Codex `search_code`**:
  - Tests pass (123). Codex's `rg`-based benchmark is not reproducible
    here (`rg` not installed).
  - Offline: the buggy function was in the results for 5 of 7 cases
    (rank 2 on e1/e2/e3/e5, 7 of 9 on e6); missed e4 and e7. The search
    response was larger than `cat`-ing all code on 7 of 7.
  - Sessions (v4, 8 total): all correct; `search_code` offered and called
    **0 times**.
  - Unused-tool overhead is now ~0.6–1.1k tokens (deferred). **No token
    saving.**
- 2026-10-18 **Real large-codebase test (e8, youtube-dl BugsInPy #8, 67k
  lines)**:
  - Offline, Faultline's top tie group contains the real bug region, and
    search finds the right function (its window stops just short of the
    bug).
  - 6 sessions (A/C ×3): all correct; Faultline called **0 times**. The
    agent localized from the pytest traceback in 6 turns.
  - Median tokens: A 205,109, C 206,241. **No token saving.**
- 2026-10-18 **Astra auto-retrieval hook + Sonnet 5.5 rerun (e8)**:
  - 132 tests pass. The hook fired and delivered context in 3/3 H
    sessions, but injected the wrong region (predicted offline).
  - Faultline MCP calls: 0.
  - Median input+cache: A 330,318 vs H 336,275 (+1.8%); turns 9 vs 9. All
    6 correct. **No token saving.**
  - Leak audit rev 2 (hook text false positive) is recorded.
- 2026-10-18 **Astra v6 evidence hooks, Sonnet 5.5, e8**:
  - 139 tests pass; replay reproduced (crash-site excerpt).
  - 6 sessions, all correct and valid. Median input+cache: A 379,113 vs H
    211,796 (−44%); turns 10/10/9 vs 5/8/6.
  - **First measured token saving.** The mechanism is a compact pytest
    command (avoiding noisy reruns) plus a post-run traceback excerpt.
  - Caveats: one case, n=3, not pre-registered, warning-heavy legacy repo;
    Opus not tested with v6.
- 2026-10-18 **v6 confirmation (24 sessions; all valid and correct)**:
  - Opus e8: −22%; Sonnet e8: −16% (pooled n=6: −36%); Sonnet e6: +25%;
    Sonnet e7: +77%.
  - The saving holds only when the traceback points into app code in a
    large, noisy repo. Bare test assertions in small repos cost more.
  - Hook delivered context 12/12; MCP calls 0.
- 2026-10-18 **v7 silence rules** (small repo ≤64 KiB → silent;
  test-file crash frame → silent):
  - 142 tests pass. Replay: e6/e7 have 0 injections; e8 is unchanged.
  - Sonnet e6/e7 A vs H (12 sessions): all correct; **0 bytes injected in
    6/6 H**.
  - Totals differ only within turn variance (pooled means A 182,856 vs H
    171,563). The constant overhead is about +500 tokens (skill + MCP
    names).
- 2026-10-18 **v8 capture verification + 12 e8 sessions**:
  - 153 tests pass; the independent capture shows the cause region (962/957).
  - Sessions all correct. `capture_failure` was called **0 times** (Claude
    chose the suggested compact pytest command).
  - Saving 35.6% Opus / 28.1% Sonnet, from the v6 hook mechanism. Pooled
    e8 hooks (n=15/arm): **−30.7%**.
  - Capture's own agent value is unmeasured.
- 2026-10-18 **v9 auto-capture** (the hook runs the capture and injects the
  cause candidate next to the crash):
  - 156 tests pass. The e8 offline check injects line 961 (the real cause)
    next to 994.
  - 12 sessions, all correct; cause injected 6/6.
  - Saving vs A: Opus 21.7%, Sonnet 27.9% (25.5% overall). This is **no
    extra saving vs v6/v8**: the H means are unchanged, because the cause
    is within the same read window as the crash.
- 2026-10-18 **Open-model agent (Gemma 4 local or Gemini API)**:
  - `faultline agent` adds a repository-confined tool loop (list, search,
    read, edit non-test files, run pytest). It uses a plain-JSON action
    protocol and injects the same Faultline context as the Claude hooks.
    Providers: `local` (llama.cpp, grammar-constrained) and `gemini`
    (generateContent; Gemma 4 IDs `gemma-4-26b-a4b-it` / `gemma-4-31b-it`
    verified in Google's docs).
  - 8 agent tests (scripted providers; not live provider verification).
  - Live local smoke run with Qwen3-4B on e8: the loop works (20–25 calls,
    55–80k tokens, about 25 s), but the 4B model never fixed the bug (wrong
    test path, then wandering), with or without Faultline.
  - Gemma 4 runs are pending the user's API key, or approval for a 6.98 GB
    local Gemma 4 12B download.
  - Eval runner: `eval/harness/run_agent_trial.py`; driver
    `run_agent_gemma.sh`.
- 2026-10-18 **Publishing prep**:
  - README rewritten. Headline numbers pooled over every current-design run
    on e8: **29.3%** (21/arm, 42/42 correct).
  - `eval/harness/export_data.py` exports 100 Claude sessions.
  - Raw event logs and `.claude/` are excluded from git (local plugin lists,
    memory paths, session IDs). Home path scrubbed from 5 JSON records.
  - `git init` with a local first commit; **not pushed**.
