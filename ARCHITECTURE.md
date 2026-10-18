> **Search redesign, 2026-10-18:** the investigation architecture below remains
> supported. The preferred initial route for broad source exploration is now
> `search_code`: bounded lexical/AST retrieval, static dependencies and callers,
> exact-symbol targeting, and caller-controlled seen-excerpt suppression.
> No coverage or inference is required for retrieval. See
> [SEARCH_REDESIGN.md](docs/SEARCH_REDESIGN.md) for the implemented search
> contract, limits, complete MCP-result budget and measurement scope.
> Runtime investigation is an optional escalation, not a prerequisite to search.

# Faultline architecture (contract version 0.2, as implemented through M5)

The design was reviewed by Astra with the verdict "proceed after changes".
Those changes are applied here; see section 12 for the review record and
acceptance cases. `BUILD_STATUS.md` says what is actually built and
verified. This document is the specification.

## 1. Purpose and non-goals

Faultline is an MCP server (stdio). Given one failing pytest test, it runs a
bounded investigation and returns compact, verifiable runtime evidence to a
main coding agent. The main agent writes the fix. Faultline never edits the
target application.

Central question: does local-model-guided observation choice improve repair
outcomes, or reduce main-agent work, beyond deterministic fault localization
plus fixed inspection rules? Everything except the planner is identical
between the two conditions.

Non-goals (MVP):
- token-saving claims;
- novelty claims for SBFL, runtime inspection, debugger MCPs or their
  combination;
- non-pytest runners;
- parallel or rerun execution;
- async, thread or subprocess observation;
- general trace alignment;
- cache reuse;
- fine-tuning, dashboards and cloud anything.

## 2. Components

| Module | Responsibility | Runs in |
|---|---|---|
| `contracts.py` | Typed models, enums, limits | Faultline |
| `config.py` | Repo root, target interpreter, globs, pytest-arg validation | Faultline |
| `procs.py` | Child processes: new session, deadline, cancel, killpg, reap, capped output | Faultline |
| `execution.py` + `_probe/cov_plugin.py` | One pytest run: outcomes, xfail class, failure signatures, per-phase coverage | target interpreter |
| `ranking.py` | Target-focused Ochiai, exact fraction ties | Faultline |
| `source.py` | AST functions/regions, candidate locals, bounded merged excerpts | Faultline |
| `worker.py` + `_probe/observe_plugin.py`, `_probe/snapshot.py` | Supervised observation run, frame-exit classification, safe snapshots, redaction | target interpreter |
| `fingerprint.py`, `evidence.py` | Full input fingerprint, evidence store, freshness | Faultline (+ target interpreter for env) |
| `planners.py` | Shared interface, validation, state-dependent deterministic planner, local-model adapter | Faultline |
| `comparison.py` | Comparator selection, count-aware alignment | Faultline |
| `orchestrator.py` | Round loop, deadlines, status decisions | Faultline |
| `budget.py` | Deterministic packing of the full serialized response | Faultline |
| `patch.py` | Test selection (default full), fresh execution | Faultline + child |
| `mcp_server.py`, `cli.py` | Adapters only | Faultline |

`_probe/` is copied into a temporary directory and put on the child's
`PYTHONPATH` as the package `faultline_probe`. That way the target
interpreter never sees Faultline's own environment. It depends only on the
stdlib, pytest and coverage.

There are two kinds of child process, both run with the target interpreter
and `start_new_session=True`:

1. **Baseline**: the full configured suite with coverage contexts.
2. **Observation**: one test, with the `sys.settrace` tracer and no
   coverage. The probe-less variant is the **isolated reproduction check**.

They are separate because coverage's per-test contexts need the `ctrace`
core. The coverage.py docs say the `sysmon` core "does not yet support
plugins, dynamic contexts". Two settrace users cannot share one process.

## 3. Investigation flow

```
investigate_failure(test, budget_tokens, max_rounds, timeout_seconds, planner)
 1. validate args (caps); fingerprint F0 (full content hash + environment)
 2. baseline run of the full configured suite
      collection error                       -> execution_error
      rerun/xdist/pytest-cov/trace conflict  -> unsupported
      target not collected / call passed     -> failure_not_reproduced
      target setup/teardown failure, any active xfail class -> unsupported
 3. fingerprint F1 != F0                     -> execution_error (workspace_changed)
 4. target-focused Ochiai (F = 1); no app line covered by target call -> insufficient_coverage
 5. isolated reproduction check (target alone, no probes) -> Reproduction
 6. AST regions for top tie groups; mint L*/F*/S*/t* IDs; pick comparators
 7. rounds while rounds remain and the deadline allows:
      action = planner(view) -> validate -> retry <= 2 -> deterministic fallback
      stop / no applicable action -> break
      execute: observation runs, or the engine-side comparison
      fingerprint content check after every child run
 8. status (section 9); pack to budget (section 10); persist evidence
```

Whenever the deadline ends the investigation, at any step, the status is
`timed_out`. Everything gathered so far (ranking, runs, observations) is kept
and returned.

## 4. Coverage attribution and ranking

Verified on this machine (coverage 7.16.2, pytest 9.1.1, Python 3.12.14):
- a module-scoped fixture body is recorded only under the first consumer's
  `|setup` context;
- import-time lines go to the `""` context;
- parametrized node IDs are preserved.

**Mechanism.** The plugin starts `coverage.Coverage(core="ctrace")` in
`pytest_load_initial_conftests`, before collection. Wrapper hooks call
`switch_context(f"{nodeid}|{phase}")` around setup, call and teardown. A
`pytest_runtest_makereport` wrapper records outcomes, the xfail class and
failure signatures in the same process. At `pytest_unconfigure` the plugin
writes `{file: {context: [lines]}}` plus the reports to one JSON file. That
file is the only join source, under one `run_id`.

**xfail classification** (explicit; `wasxfail` alone is insufficient). It
reads pytest's evaluated xfail state for the item (`_pytest.skipping.xfailed_key`
in the item stash, a private API checked against pytest 9.1.1). If that
state is unavailable, it falls back to the mark's presence.

| Situation | pytest reports | Faultline class |
|---|---|---|
| expected failure | skipped + `wasxfail` | `xfail` |
| non-strict unexpected pass | passed + `wasxfail` | `xpass` |
| strict unexpected pass | **failed**, longrepr `[XPASS(strict)]`, no `wasxfail` | `xpass_strict` |
| active xfail, `raises=` mismatch | failed, no `wasxfail` | `xfail_raises_mismatch` |
| mark present, state unknown | — | `xfail_marked_unknown` |
| imperative `pytest.xfail()` | skipped + `wasxfail` | `xfail` |

Every non-`none` class is excluded from ranking. A target in any non-`none`
class is `unsupported`.

**Eligibility.** A test is eligible when:
- setup passed and teardown passed;
- call passed or failed;
- its xfail class is `none`;
- it has exactly one report per phase;
- no trace conflict was detected.

The failing set is **only the target** (decision: target-focused Ochiai).
Other eligible failing tests are excluded as `unrelated_failure`, counted,
and sampled in the response. Target in setup/teardown failure →
`unsupported`. Any duplicate `(nodeid, when)` report, xdist, an active
pytest-cov, or an existing tracer at start → `unsupported`. Collection
errors → `execution_error`.

**Ranked coverage.** Only call-phase coverage of application files counts:
repo files minus `test_globs`, `exclude_globs` and site-packages.
Setup/teardown coverage is kept separately and used only for diagnostics
and patch-selection escalation. The `""` context is unattributed and never
ranked.

**Ochiai** over distinct eligible tests, with F = 1:
`score = ef / sqrt(F · (ef + ep))`.
- Only lines with ef = 1 are ranked; ef = 0 lines are counted, not ranked.
- ef + ep = 0 and F = 0 are guarded explicitly and produce no score.
- Ordering uses the exact `Fraction(ef², F·(ef+ep))`, which is equivalent to
  integer cross-multiplication. In general, distinct `(ef, ep)` pairs can tie,
  for example (1,0) and (2,2) when F > 1. Tie groups therefore record every
  `distinct_count_pairs`. Under F = 1, ties are exactly the lines with equal ep.
- The display score is rounded to 4 places. Within a tie the order is
  `(path, line)`, which is labelled meaningless.
- Scores are association measures, not probabilities. Generated
  expectations are never ground truth.

## 5. Observations

**Failure signature** (computed in-process, identically in baseline and
observation runs):
- exception type `module.QualName`, taken from type descriptors;
- crash path and line, from pytest's `reprcrash`;
- the line in the test function where the failure surfaced;
- the SHA-256 of the redacted message with `0x…` addresses normalized;
- a short excerpt.

**Reproduction** compares the run's signature with the baseline's:
- `reproduced`: type, crash location, test line and message digest all match;
- `partial_match`: type and crash location match, the message differs;
- `different_failure`: some other failure;
- `not_reproduced`: the call passed;
- `unknown`: the worker died first.

Only `reproduced` counts as reproduction. Runtime values from runs that did
not reproduce are kept but labelled, and they never support `completed`.

**Decision.** If the isolated check does not reproduce, the suite ranking is
preserved and investigation continues, but the status is at best
`inconclusive`. The limitation `isolated_reproduction_failed` names the
outcome.

**Tracer.**
- `sys.settrace` is installed in a `pytest_runtest_call` wrapper, so only
  the call phase is traced.
- The global trace function returns a local tracer only for code objects in
  probed files whose line span or `(co_qualname, co_firstlineno)` matches a
  probe. The match is cached per code object.
- If `sys.gettrace()` is already set, or is replaced during the call, the
  run reports `trace_conflict`.

**Events.**
- `before_line`: Python's `line` event fires **before** the line runs, so
  values are pre-state. This is labelled in every response.
- `call`: the arguments at entry.
- `exception`: a type name only; the exception value is never touched.
- **Frame exit** is classified per frame:
  - generator, coroutine or async-generator code → `exit_ambiguous`;
  - an `exception` event with no later `line` event in that frame, then
    `return` → `unwind` (the exception propagated);
  - otherwise → `return`, with `<return>` snapshotted.

  Python passes `None` to `return` in both the unwind and the normal case,
  which is why the classification needs the per-frame state.
- Unbound locals are recorded as `unavailable/unbound`.
- Candidate locals come from `symtable`: the frame-readable names of the
  enclosing function (locals, params and free variables), never globals.
  They are ordered: names on the line, then parameters, then other locals.
  At module scope the candidates are the names on the line.

**Counts.**
- Hits are counted per `(probe, event)` for the whole call phase. A key
  absent from `probe_hits` means zero hits, with the run's `counts_exact`. Snapshot
  caps (20 per probe, 400 per run) stop *snapshotting*, not counting, so the
  counts stay exact.
- Counts become **lower bounds** (`exact: false`, run `counts_exact: false`)
  when tracing stops early: callback budget, trace conflict, timeout or
  worker crash. Alignment never treats lower bounds as unambiguous (section 7).

**Snapshot rules** (`_probe/snapshot.py`):
- Only **exact** types are expanded: None, bool, int, float, str, bytes,
  list, tuple, dict, set, frozenset.
- Subclasses and all other objects become `opaque`. The type name is read
  via `type.__dict__['__qualname__'].__get__(cls)` (and the same for
  `__module__`) for every class in the MRO.
- Never called: repr/str/format, properties, custom iterators,
  `__eq__`/`__lt__`/`__hash__` of user types, copy or pickle. Set elements
  are sorted only when all of them are primitives.
- Bounds: depth 3, 16 items, 160 characters, 32-byte preview, ints longer
  than 40 digits are replaced by a bit-length note, and 4 KB per snapshot.
  Cycles become `cycle`. Truncation is flagged and the true length kept.
- Redaction happens in the worker before write, and again before model
  input. A name matching
  `(?i)pass(word|wd)?|secret|token|api_?key|auth|cookie|session|credential|private`
  is redacted by name. Secret-shaped strings (PEM, `AKIA…`, `ghp_…`, `sk-…`,
  `Bearer …`, JWT) are redacted by value.

**Limits.**
- Wall time: min(remaining deadline, per-run cap).
- Cumulative tracer time is capped at 2000 ms, after which tracing stops and
  counts become lower bounds.
- Output file 512 KB; stdout/stderr tail 16 KB.
- On timeout or cancel: `killpg(SIGTERM)`, 2 s grace, `killpg(SIGKILL)`,
  `waitpid`. Any surviving group members are killed after a normal exit
  too. This is **not a sandbox**.

**Detected and reported**, never claimed complete: `threads_started`,
`subprocess_spawned` (audit hook), `trace_conflict`, `generator_or_coroutine_frame`.

## 6. Planners

One interface: `plan(view) -> PlannerActionEnvelope`. The view holds only
engine-minted IDs and counts. It contains:
- excerpt summaries;
- allowed test aliases: `t0` is the target, `t1…` are comparators, if any;
- candidate locals per location (AST: params and names in the enclosing
  function);
- runs so far, with their reproduction and exactness;
- prior action keys, and the remaining rounds and time.

The action vocabulary is closed and pydantic-validated: `inspect_locations`,
`inspect_function`, `compare_observations`, `stop`.

Semantic validation checks that:
- IDs exist and locals are in the candidate set;
- test aliases are allowed and runs belong to this investigation;
- `compare_observations` needs one target run and one comparator run;
- source identities are unchanged;
- the normalized key does not repeat.

A rejected action is retried at most 2 times, and retries count against
time. After that the deterministic fallback acts, recorded with
`fallback_reason`.

**Deterministic planner** (state-dependent). Each round it takes the first
applicable rule that has not been done yet:
0. `stop(sufficient_evidence)` once any comparison has a first divergence;
1. `inspect_locations` for the top tie group (≤5 lines) on `t0` plus `t1`
   if a comparator exists. Locals (≤8) are taken round-robin from each
   location's candidate order, so names on the line come first, then
   parameters;
2. `compare_observations`, *if* a target run and a comparator run share
   probes;
3. `inspect_function` for the top line's function, *if it lies inside a
   function*;
4. `inspect_locations` for the next tie group;
5. `stop(no_useful_action)`.

Comparison comes before function inspection (changed in M5) so that a
comparison is available by round 2 under the default `max_rounds=3`. With
no comparator, rule 2 never applies and the response lists
`no_comparator`. With a module-level top line, rule 3 is skipped. A
randomized property test checks that no state yields an invalid action.

**Local-model planner** (implemented and live-verified at M6).
- **Runtime:** llama.cpp `llama-server` b11669 on `127.0.0.1` only (the
  client refuses non-local endpoints), using `/v1/chat/completions` with
  `response_format: json_schema`.
- **Model:** `Qwen3-4B-Q4_K_M.gguf` (sha256 `7485fe6f…fdf5`).
- **Settings:** thinking disabled via
  `chat_template_kwargs.enable_thinking=false` and server `--reasoning off`;
  temperature 0, seed 0, 256 output tokens, 4096 context.
- **Per-round schema** (`planners.view_schema`): ID fields are enums of
  exactly the IDs issued for this round. These cover locations, functions,
  test aliases, candidate locals, and target or comparator run IDs.
  Branches that cannot apply in the current state are removed. This was
  added after live gate attempt 1, where a static schema let the model
  invent IDs like `testing`. Engine validation still runs on every reply.
- **Prompt:** executed actions are listed as the same JSON the model emits,
  and a rejected repeat is quoted back in the retry feedback (added after
  attempt 2).
- **Untrusted input:** repository text goes in a `<data>` block after
  redaction.
- **Provenance:** `metrics.planner_model` records `<gguf>@<build>`. Each
  round records attempts, rejection codes, fallback reason, inference ms and
  token counts.

## 7. Comparisons

**Comparator selection** is deterministic among eligible passing tests:
1. the test's call covers the top line's function (or the top line);
2. highest exact Jaccard overlap of call-phase app lines with the target;
3. a parametrize sibling of the target (same test function) wins ties;
4. remaining ties broken by nodeid.

Before all of these (token-saving pass), comparators are ranked by how many
lines of the **top tie group** they cover. This makes probes on suspects
have a passing counterpart.

At most 2 comparators are picked, and each reason string records the
numbers.

**Alignment.** The key is `(probe_id, event, hit_ordinal)`. The label is:
- `incomplete`: either side's count is a lower bound;
- `unambiguous`: both counts are exact and equal 1;
- `ordinal`: both counts are exact, equal, and greater than 1;
- `ambiguous`: exact counts that differ. The first min(n) are compared and
  `hit_count_differences` is reported.

Values are compared structurally. Opaque, redacted or truncated values are
`incomparable`, unless their kinds or type names already differ. A
comparison lists only non-equal entries (`differs`, `incomparable`,
`missing`) plus an `equal_count`; full values remain expandable through the
observation handles. `first_divergence_index` considers only `unambiguous` and
`ordinal` entries, uses failing-run event order, and is labelled "not
evidence of causation".

## 8. Fingerprint, evidence, freshness, patch checking

**Fingerprint.** The full input fingerprint covers:
- the SHA-256 content hash of every in-scope file. The list comes from
  `git ls-files -co --exclude-standard` when available, otherwise a walk
  with `exclude_globs`, so uncommitted and untracked files count;
- `extra_inputs`;
- a config digest;
- the interpreter (executable, version, prefix);
- the dependencies, as distribution name and version plus `direct_url.json`
  editable locations;
- an HMAC of declared env vars. Values are never stored.

**No stat cache.** Content is fully rehashed at every correctness
boundary: before and after each child run, on `expand_evidence`, and on
`check_patch`.

**Partial fingerprints.** An editable distribution whose source lies
outside the repo marks the fingerprint `partial`
(`editable_outside_repo:<name>`). So does hitting the file or byte caps. A
partial fingerprint makes every freshness answer `unknown` and is reported.

**Evidence store.** Evidence lives in
`<state_dir>/<repo-hash>/<investigation_id>/`, outside the repo, capped at
8 MB. Retention is 24 h, after which a tombstone remains. Each item records
its source identities and whether it was truncated at capture. Reuse is
disabled.

**Runtime freshness on expand** compares the *whole* stored fingerprint
with the current one:
- any environment component changed (interpreter, dependencies, config,
  declared env) → `stale`, listed in `stale_components`;
- any referenced source changed → `stale` with `stale_paths`;
- either fingerprint partial → `unknown`;
- otherwise `fresh`.

**check_patch defaults to `mode="full"`** (decision for the first release).
`affected` mode escalates to the full configured suite when:
- a file was added or deleted;
- a test, conftest, config or non-Python file changed;
- any environment component changed (interpreter, dependencies, declared
  env, config);
- the fingerprint is partial;
- the baseline is expired or unsupported;
- a changed file has unattributed (import-time), setup or teardown coverage;
- a changed app file was uncovered.

Otherwise it selects the baseline's non-passing tests plus every test whose
call phase covered a changed file. Tests always run fresh.
`full_regression_verified` is true only when the full configured suite ran
and passed. Residual risks are always listed: cross-test state, reflection,
external data and order dependence.

## 9. Status decision (first match wins)

| Status | Condition |
|---|---|
| `timed_out` | the deadline ended the investigation at any point (partial evidence kept) |
| `execution_error` | collection error, worker or internal crash, workspace changed |
| `unsupported` | rerun/xdist/pytest-cov/trace conflict; target setup/teardown failure; target xfail class ≠ none |
| `failure_not_reproduced` | target's call phase did not fail in the baseline |
| `insufficient_coverage` | no application line covered by the target's call phase |
| `completed` | ranking exists, isolated check `reproduced`, ≥1 target observation run `reproduced` with ≥1 measured value at a ranked location |
| `inconclusive` | anything else with a ranking |

`completed` never means "root cause proven".

## 10. Response budgeting

- **Size** is the UTF-8 bytes of the **complete** compact response
  (`exclude_none`). Estimate = ceil(bytes / 3), labelled
  `utf8_bytes_div_3`. Byte cap = 3 × budget. Budgets run from a minimum of
  **800** to a cap of 8000. The minimum was raised from the M1 guess of
  600 after M5 measurement: at 600 the mandatory skeleton plus omissions did
  not reliably fit.
- **Skeleton**, always included: IDs, status, reason, reproduction,
  ranking counts, limitations, metrics.
- **Fixed priority** after the skeleton:
  1. the top tie group's rows (all of them, or the count plus handles with
     "N tied, M shown");
  2. comparisons;
  3. target observations not already represented in a comparison;
  4. the top excerpt;
  5. planner rounds;
  6. runs;
  7. the next tie groups;
  8. further excerpts and observations.
- An item is added only if the whole response still fits. Dropped items
  become omissions with handles. If the omissions themselves do not fit,
  packed items are removed last-in-first-out, each becoming a counted
  omission.
- **Last-resort compaction**, applied in order and recorded in
  `metrics.compacted`: shorten limitation details (codes are kept), drop
  the failure-message excerpt (the digest is kept), shorten unresolved
  notes. If the response still does not fit, that is a hard error.
- **De-duplication.** A run's signature is omitted when it equals the
  baseline signature. Observations from *either* run of a comparison are
  omitted with handles (`observation_in_comparison`). Divergences are
  referenced by index.
- **Metrics** come from fixed-point re-serialization. The illustrative
  example is 5,447 B, about 1,816 estimated tokens.
- Response size is not total session usage and is not a savings claim.

## 10b. Token footprint (token-saving pass)

The agent's dominant cost is turns: each turn re-reads the context. A tool
result also stays in context for every later turn. Therefore:
- `investigate_failure` carries `_meta["anthropic/alwaysLoad"]=true`, so it
  needs no ToolSearch turn. Its description stays under 300 characters and
  the server instructions are 72 characters.
- Default investigate budget: 1,200 tokens.
- **Packing order:**
  1. up to 5 rows of the top tie group;
  2. comparisons, trimmed if needed: values shrunk to ≤3 items / depth 2 /
     60 characters, entries in priority order;
  3. the top excerpt;
  4. target observations;
  5. the rest of the top group;
  6. other groups and excerpts;
  7. bookkeeping last.
- Bookkeeping omissions (runs, planner rounds, compared observations) are
  merged into `audit_records`. At most 3 handles are listed per omission;
  counts are always exact.

## 10a. MCP adapter (mcp 2.3.0, stdio)

- `faultline serve --repo R --python P [--model-endpoint URL]` exposes
  `investigate_failure`, `expand_evidence` and `check_patch` through
  `mcp.server.mcpserver.MCPServer` with `run(transport="stdio")`.
- **Tool loading:** `investigate_failure` loads upfront (`alwaysLoad`);
  `expand_evidence` and `check_patch` stay deferred.
- **One copy of the payload.** Each tool returns a `CallToolResult` with
  exactly one text block: the compact JSON the engine budgeted.
  `structured_output=False` and `structured_content` is not set, so the
  payload is not duplicated.
- **What the budget covers.** It covers that text block, which is what the
  agent's model reads. The JSON-RPC envelope plus string escaping on the
  wire measured about +18% (5,879 B content → 6,912 B `CallToolResult`
  JSON for the demo). That overhead is reported, not budgeted.
- **Errors.** Bad arguments and unknown IDs raise `ToolError`, so the
  client gets an `is_error` result the model can read. Protocol-level
  `MCPError` is not used for these.
- **Threading and cancellation.** Handlers are synchronous; the SDK runs
  them in a worker thread. MCP request cancellation is **not** propagated
  to the engine yet. Runs remain bounded by `timeout_seconds`.

## 11. Execution boundaries

- `pytest_args` is validated, and execution-changing options are rejected:
  `-n`, `--dist`, `--reruns`, `--cov*`, `-p` except `no:*`, `--pdb`,
  `--trace`, `-x`, `--maxfail`, `--lf`, `--ff`, `--sw`.
- Paths are `realpath`'d inside the repo root.
- Children get `PYTHONDONTWRITEBYTECODE=1` and `PYTHONHASHSEED=0` (so
  hash-ordered output, such as pytest dict diffs, is the same on every
  rerun), and run with the repo root as their cwd. `PYTEST_ADDOPTS`, `PYTEST_PLUGINS`, `COVERAGE_PROCESS_START`
  and `COVERAGE_CORE` are removed from their environment.
- Single-test runs (observation, isolated reproduction, affected selection)
  strip configured selection options (`-k`, `-m`, `--deselect`) so a
  filter cannot deselect the named test. The worker reports "target not
  collected" if it happens anyway.

## 12. Review record and acceptance cases (Astra, M1 → "proceed after changes")

Only the summarized findings and decisions were supplied, not the full
review text. The acceptance cases below are derived from that summary, and
each becomes a behavioral test at the milestone named.

| # | Finding / decision | Acceptance case | Milestone |
|---|---|---|---|
| R1 | strict XPASS explicit | fixture with `xfail(strict=True)` that passes → `xpass_strict`, excluded; as target → `unsupported`. Also non-strict xpass, `raises` mismatch, imperative xfail | M2 |
| R2 | failure signatures | same type at a different crash line → `different_failure`; same location with a different message → `partial_match`; neither counts as reproduced | M3/M5 |
| R3 | rehash + full-input freshness | edit that preserves size and mtime is detected; declared env change → expand `stale` (component) and affected check escalates; editable dist outside repo → `partial`/`unknown` | M4 |
| R4 | exact vs lower-bound counts | callback-budget exhaustion → `exact:false`; alignment with a lower bound is `incomplete`, never `unambiguous` | M3/M5 |
| R5 | normal vs exceptional exit | propagated exception → `unwind`; caught exception then return → `return`; generator → `exit_ambiguous` | M3 |
| R6 | state-dependent deterministic plan | no comparator → no compare action; module-level top line → no `inspect_function`; no invalid action is emitted in any state | M5 |
| R7 | timed_out on deadline | deadline during observation → `timed_out` with ranking and earlier runs present | M5 |
| D1 | F=1 target-focused | two unrelated failures do not change the target's ranking; reported as `unrelated_failing` | M2 |
| D2 | isolation failure keeps ranking | order-dependent fixture: suite fails, alone passes → ranking present, `inconclusive`, `isolated_reproduction_failed` | M5 |
| D3 | patch default full | `check_patch` without mode runs the full suite | M4 |
| D4 | report all D runs | evaluation doc: the primary analysis includes fallback episodes | docs |
| D5 | hidden tests private | evaluation doc: private manifest outside agent-visible paths | docs |
