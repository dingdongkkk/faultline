# Faultline — architecture/correctness review packet (M1)

You are reviewing a design before implementation. You cannot see the repo;
everything you need is below. Do **not** propose a rewrite.

## What to return
Ranked findings, most severe first. For each finding:
- **severity**: blocker / major / minor
- **failure scenario**: concrete inputs or state → wrong output or unsafe behavior
- **minimum required change**
- **acceptance check**: a test or observation that proves it's fixed

Prioritize: (1) coverage attribution, (2) trace/observation semantics,
(3) stale evidence, (4) execution boundaries, (5) test-selection safety,
(6) evaluation validity. Answer the 5 open questions briefly. End with one
verdict: **proceed**, **proceed after changes**, or **blocked**.

## Project
Faultline is an open-source MCP server (stdio). It takes one failing pytest
test, runs a bounded investigation locally and returns compact, verifiable
runtime evidence to a main coding agent, which writes the fix. Faultline
never edits the target app.

Research question: does a small local model (Qwen3-4B Q4_K_M via llama.cpp)
choosing *which* observations to make beat fixed deterministic rules, with
the engine, vocabulary, budgets and tests held constant? There are no
novelty claims and no token-savings claims.

Constraints: Apple M5 with 16 GB, local inference only, Python ≥ 3.12,
pytest only, synchronous single-process tests, no fine-tuning, small MVP.

Tools:
- `investigate_failure(failing_test, budget_tokens=2000, max_rounds=3, timeout_seconds=120, planner="deterministic"|"local-model")`
- `expand_evidence(investigation_id, evidence_id, budget_tokens=1000, cursor=None)` never reruns tests.
- `check_patch(investigation_id, mode="affected"|"full", timeout_seconds=120, budget_tokens=1500)` checks the current checkout.

Statuses: completed, inconclusive, failure_not_reproduced,
insufficient_coverage, unsupported, timed_out, execution_error.

## Status table (truthful as of M1)
Implemented and auto-tested: pydantic contracts, JSON schemas, the closed
planner vocabulary, 18 contract tests. Not implemented: everything else.
Nothing is live-model, MCP-client or benchmark verified.

A spike on the target machine (coverage 7.16.2, pytest 9.1.1, Python 3.12.14)
confirmed four things:
- `ctrace` + `switch_context("nodeid|phase")` works;
- a module-scoped fixture body is attributed only to the first consumer's `|setup`;
- import-time lines go to context `""`;
- parametrized IDs are preserved.

Coverage docs say the `sysmon` core does not support dynamic contexts, so
`ctrace` is forced.

## Process model
There are two child-process kinds, both in the target interpreter and both
in a new process group:
- **Baseline**: the full configured suite with the Faultline pytest plugin.
  Coverage starts in `pytest_load_initial_conftests`. Wrapper hooks on
  setup/call/teardown switch the context. `pytest_runtest_logreport` records
  outcomes in the same process and run.
- **Observation**: one test, `sys.settrace` installed only around the call
  phase, no coverage. A JSON probe spec goes in; a bounded JSON result file
  comes out.

On timeout or cancel: `killpg(SIGTERM)`, 2 s grace, `killpg(SIGKILL)`,
`waitpid`. This is explicitly not a sandbox.

## Coverage and ranking policy
- Ranked: call-phase coverage of application files only (repo minus test
  globs, venvs and site-packages).
- Setup/teardown coverage is kept for diagnostics and patch selection only.
- `""` context (import, collection, between tests) is unattributed and never
  ranked.
- Eligible test: setup passed, teardown passed, call passed or failed, not
  xfail/xpass/skip, and exactly one report per phase.
- Target failing in setup or teardown, or target xfail → unsupported.
- Duplicate phase reports (rerun), xdist, pytest-cov active, or a
  pre-existing `sys.gettrace()` → unsupported.
- Collection error → execution_error.
- Ochiai over distinct eligible tests: `score = ef / sqrt(F·(ef+ep))`.
  F = all eligible failing tests in the run.
  - ef+ep = 0: not ranked.
  - ef = 0: not ranked, only counted.
  - Order and ties are decided by integers: compare `ef_a²·(ef_b+ep_b)` with
    `ef_b²·(ef_a+ep_a)`. Distinct pairs can tie, e.g. (1,0) and (2,2).
  - The display score is rounded and never used for order. Within-tie order
    is by (path, line) and is labelled meaningless.

## Observation semantics
- `before_line`: the Python `line` trace event, so locals are the
  **pre-execution** state.
- `call`, `return` and `exception` events for an `inspect_function` probe.
- Unbound locals are recorded as `unavailable`.
- `hit_ordinal` is per probe per run. The first 20 hits are kept and the true
  total is always reported. `event_seq` is the global order.
- Snapshots are copied inside the callback into primitives.
  - Only **exact** builtin types are expanded: None, bool, int, float, str,
    bytes, list, tuple, dict, set, frozenset. Subclasses and other objects
    become `opaque` with a type name read through type descriptors.
  - Never called on application objects: repr/str, properties, custom
    iterators, `__eq__`/`__lt__` (no sorting of non-primitive sets), copy or
    pickle.
  - Bounds: depth 3, 16 items, 160 characters per string, 40-digit ints,
    4 KB per snapshot. Truncation is flagged and the true length is kept.
    Cycles are marked.
- Redaction by name pattern and secret-value pattern happens in the worker
  before write, and again before model input.
- Limits: 2 s cumulative tracer time (then tracing stops and is flagged),
  400 events per run, 512 KB output, 16 KB stdout/stderr tail.
- Reproduction: `reproduced` means the call phase failed with the same
  exception type qualname as the baseline. Otherwise
  `different_failure`/`not_reproduced`.
- Detected (never claimed complete): threads started, subprocess spawned
  (audit hook), trace conflict, coroutine/generator frames.

## Planner contract
Actions (closed, pydantic-validated, all IDs engine-minted):
```json
{"next":{"action":"inspect_locations","location_ids":["L1","L2"],"locals":["qty","tiers"],"test_ids":["t0","t1"],"rationale":"<=300 chars"}}
{"next":{"action":"inspect_function","function_id":"F2","test_ids":["t0","t1"]}}
{"next":{"action":"compare_observations","failing_run_id":"R1","passing_run_id":"R2"}}
{"next":{"action":"stop","reason":"sufficient_evidence|no_useful_action|evidence_contradictory"}}
```
Limits: ≤5 locations, ≤8 locals, ≤2 tests. Locals must come from the AST
candidate set (params plus names in the enclosing function). Tests are
aliases (t0 = target, t1.. = comparators). Source identities must still
match. A repeated normalized action is rejected. Up to 2 retries count
against time; after that the deterministic planner is used and the fallback
is recorded. Model rationale is stored separately as
`rationale_untrusted`.

Deterministic planner, which is also the fallback:
- round 1: inspect the top tie group on t0 and t1, with the locals read on
  those lines;
- round 2: `inspect_function` of the top line's function;
- round 3: compare;
- then stop.

Comparators are eligible passing tests whose call covers the top function.
They are ranked by Jaccard overlap of covered lines, then nodeid, up to 2.
Alignment key is (probe, event, hit_ordinal):
- **unambiguous**: both runs hit once;
- **ordinal**: equal counts greater than 1;
- **ambiguous**: counts differ (the first min(n) are compared and the counts
  reported).

`first_divergence_index` is labelled "not evidence of causation".

## Freshness and evidence
The fingerprint covers:
- the SHA-256 of every in-scope file (`git ls-files -co --exclude-standard`,
  or a walk), so uncommitted and untracked files are included;
- a config digest (pyproject/setup.cfg/pytest.ini/tox.ini/conftest);
- the interpreter (path, version, prefix);
- installed distributions;
- HMAC of declared env vars. Values are never stored. Git commits are never
  the key.

A (size, mtime_ns, inode) stat cache skips rehashing. Hitting the file or
byte caps makes the fingerprint `partial`: all freshness is then `unknown`
and affected-mode checks escalate to full. The fingerprint is recomputed
after every child run, and a change aborts with
`execution_error/workspace_changed`.

Evidence is stored outside the repo, with 24 h retention and then a
tombstone (`expired`). Each item lists the source identities it depends on.
On expand, those paths are rehashed: `fresh`, `stale` (with paths) or
`unknown`. Items truncated at capture are flagged `irrecoverably_truncated`.
Cache reuse is disabled.

## Patch selection (`affected`)
Escalate to the full configured suite if any of these hold:
- a file was added or deleted;
- a test, conftest, config or non-Python file changed;
- the dependency or interpreter digest changed;
- the fingerprint is partial;
- the baseline is expired or unsupported;
- a changed file had any import-time, setup or teardown coverage;
- a changed app file was uncovered.

Otherwise run the previously non-passing tests plus every test whose **call
phase** covered a changed file. Everything runs fresh, with no reuse.
`full_regression_verified` is true only for a passing full-suite run. Residual
risks are always listed: cross-test state, reflection, external data, order
dependence.

## Status decision
- execution_error: collection error, crash, or workspace changed.
- unsupported: see above.
- failure_not_reproduced: the baseline call did not fail.
- insufficient_coverage: no line with ef > 0.
- timed_out: the deadline hit before a ranking existed.
- completed: a ranking exists, at least one target observation run
  reproduced, and at least one measured value at a ranked location.
- inconclusive: everything else with a ranking, including a deadline hit
  after ranking.

## Budgeting
- Budget = ceil(UTF-8 bytes / 3) of the **complete** compact JSON response
  (wrappers, limitations, omissions and metrics included). There is also a
  byte cap of 3 × budget. The minimum budget is 600 and the cap 8000.
- Priority order:
  1. skeleton (IDs, status, reproduction, counts, limitations, metrics);
  2. **all** top tie-group rows, or the count plus handles with "N tied,
     M shown";
  3. comparison;
  4. target observations not already shown in a comparison;
  5. top excerpt;
  6. the rest.
- Dropped items become omissions with handles.
- Metrics are computed by fixed-point re-serialization.
- The illustrative two-location example is 5,649 B, an estimated 1,883
  tokens.

## Sample observation (contract-valid)
```json
{"evidence_id":"O3","run_id":"R1","probe_id":"L1","path":"shop/cart.py","line":15,
 "event":"before_line","timing":{"event_seq":4,"hit_ordinal":1,"t_ns":182340},
 "frame_qualname":"bulk_rate","call_depth":2,
 "values":{"qty":{"kind":"int","value":10},
  "tiers":{"kind":"dict","length":2,"entries":[[{"kind":"int","value":10},{"kind":"int","value":10}],[{"kind":"int","value":50},{"kind":"int","value":20}]]},
  "customer":{"kind":"opaque","type_name":"shop.models.Customer"},
  "api_token":{"kind":"redacted","reason":"name_pattern"}}}
```

## Evaluation design
There are four conditions, all with the same main agent:
- A: ordinary tools;
- B: a debugger MCP;
- C: deterministic Faultline;
- D: local-model Faultline.

C vs D is primary. Engine, vocabulary, visible tests, budgets and repair
criteria are held constant. There are 3–5 preselected cases, covering
useful SBFL, ties, same-path wrong value, inconclusive, and regression risk.
Real bugs are preferred, and mutations are labelled. Cases are never removed
after the results are in.

Each run uses a fresh checkout and a fresh session. Hidden tests are never
shown to Faultline or to the agent. Correctness is judged by an independent
scripted run. Missing metrics are reported as unavailable, never as zero.

## Open questions
1. **Multi-failure F.** F counts *all* eligible failing tests, so unrelated
   failures dilute and mix faults. Should ranking use F restricted to the
   target (F=1, other failures excluded and reported), or all failures?
2. **Isolation.** The baseline is the full suite, but observations rerun the
   target alone. Order-dependent failures will show `not_reproduced`. Should
   an isolated reproduction run be required before ranking, with order
   dependence → unsupported?
3. **Selection vs cross-test state.** A test can depend on a changed file
   only via state left by another test (memoization, mutated module
   globals), with no coverage of its own. Is "listed residual risk" enough
   for affected mode, or what cheap escalation rule should apply?
4. **Stat-cache freshness.** Is a (size, mtime_ns, inode) cache acceptable
   for detecting edits (tools that preserve mtime and size would evade it),
   or must evidence and patch checks always rehash referenced files fully?
5. **C vs D validity.** With 3–5 cases and ≥3 trials, and D falling back to
   the deterministic planner on invalid output, how should results be
   reported so fallback doesn't blur the contrast? For example: per-case
   paired outcomes, fallback rate, and D episodes with zero fallbacks
   reported separately.
