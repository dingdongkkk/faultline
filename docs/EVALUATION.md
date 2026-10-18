# Current evaluation amendment — v4 source retrieval

The current server exposes search_code and no longer forces upfront schemas.
New repair runs are tagged `v4-search-neutral-deferred`, use a fresh v4 output
directory, and cannot overwrite earlier trials. The summarizer groups by
protocol. The historical v3 driver is disabled to prevent accidental mixing.
No v4 repair sessions have been run in this redesign.

Retrieval development runs 01–04 are in `eval/results/search-v1-development-*`.
See [SEARCH_REDESIGN.md](SEARCH_REDESIGN.md) for all baselines and losses.
Five of six selected definitions appeared in the first response; all six
within three calls. These are tuned development cases, not independent
validation. Follow-up bytes must be counted. Response bytes/3 are estimates,
not actual main-agent token savings.

For independent tests, freeze real repositories and tasks before tuning.
Retain small cases where direct reading wins. Compare both source retrieval
quality and complete repair-session usage, including tool definitions,
discovery, input/cache/output, failed searches and runtime escalation.
A no-use outcome belongs in the primary result. D currently differs from C
only if runtime investigation invokes the model; model-guided search remains
proposed and must receive its own ablation before claiming an AI benefit.

The sections below are chronological historical records. Earlier statements
such as “not started” refer to those checkpoints, not the current state.

---

# Evaluation plan

**Status: cases pre-registered, harness built and self-tested, engine-only measurements taken. No repair trials have been run.** Never fill this with invented numbers.

## Question
Does local-model-guided investigation (D) improve repair outcomes or reduce
main-agent work beyond deterministic Faultline (C)? C vs D is the essential
comparison. A and B give context.

| Condition | Main agent tools |
|---|---|
| A | ordinary tools only |
| B | a maintained debugger MCP (if one can be set up locally) |
| C | Faultline, `planner="deterministic"` |
| D | Faultline, `planner="local-model"` |

Held constant across C/D: engine, action vocabulary, visible tests,
`budget_tokens`, `max_rounds`, timeouts, main agent model/version/settings,
repair criteria, prompt text (except the tool's presence/planner arg).

## Cases (preselected before any run; never removed afterwards)
Target 3–5, covering:
1. Useful SBFL (single clear top location).
2. Ties (≥2 locations with identical counts).
3. Same execution path, wrong value (coverage cannot separate; values can).
4. Inconclusive evidence (e.g. failure depends on state not observed).
5. Regression risk (plausible fix that breaks another test).

Prefer real reproducible bugs (e.g. from public bug datasets or project
histories); injected mutations are labelled as such.

Hidden tests and the private manifest live **outside every agent-visible
path** (see "Pre-registered case set" above). Only their SHA-256 is public.

## Pre-registered case set (frozen 2026-10-18, before any Faultline or agent run on it)

| ID | Category | Visible failing test | Provenance |
|---|---|---|---|
| e1_textstats | useful SBFL | `tests/test_core.py::test_top_words` | injected |
| e2_shipping | ties (bug masked when base fee == surcharge) | `tests/test_fees.py::test_express_international` | injected |
| e3_split | same path, wrong value | `tests/test_split.py::test_six_people` | injected |
| e4_config | inconclusive (order-dependent shared state) | `tests/test_settings.py::test_default_currency` | injected |
| e5_slug | regression risk (tempting fix breaks hidden callers) | `tests/test_text.py::test_slug_strips_punctuation` | injected |

**Provenance.** All five bugs were *authored* by the implementation agent.
None is a real-world bug. They are distinct from every fixture used during
development and the M6 live gate. Real bugs (for example from BugsInPy)
would need a separate, approved download and are not included.

**Private store.** The hidden tests, reference fixes, an E5 regression-trap
fix and the manifest live in `~/.faultline-eval-private/` (mode 0700). That
is outside this repository and outside every trial checkout.
- SHA-256 over all its file paths and contents:
  `94939a8503b663263d012b270d224da898998e19006470708cd312137ab93829`.
- `eval/harness/validate_cases.py` recomputes the hash. It also checks
  that:
  - each visible failing test is the only visible failure;
  - hidden tests fail on the bug;
  - reference fixes pass everything;
  - the trap passes visible tests but fails hidden ones.

  All five cases passed validation on 2026-10-18.

## Protocol
- Fresh checkout and fresh agent session per (case, condition, trial).
- Hidden evaluation tests are never visible to Faultline or the repairing
  agent; Faultline sees only the configured visible suite.
- Repair is correct iff visible suite and hidden tests pass on an
  independent run in a clean environment, judged by script.
- Trials per cell: ≥3 where feasible; report all trials.
- Cold and warm model runs recorded separately.

## Metrics
Correct repairs; main-agent input / cached-input / output tokens *as exposed
by the client's final, deduplicated usage records*; tool calls; wall time;
coverage-run overhead; local inference tokens and time; rounds; retries;
fallbacks; failures; timeouts; peak memory of llama-server.

Primary analysis of D includes **every** local-model run, including rounds
where the deterministic fallback acted (review decision); the fallback rate
is reported alongside, and fallback-free episodes may be shown only as a
secondary breakdown.

Rules: missing metrics are **unavailable**, never zero. API-equivalent cost
estimates are labelled as estimates and kept separate from actual spending.
Never infer subscription credits or dollars saved from token counts.

## If authenticated repair runs are not possible
Publish this protocol, the case set, and engine-only measurements (ranking,
observation choice, response size, latency); mark repair results **pending**.

## Harness (built 2026-10-18)

| File | Purpose |
|---|---|
| `eval/harness/validate_cases.py` | pytest-only case validation and private-store hash |
| `eval/harness/run_trial.py CASE {A,C,D} TRIAL` | one trial: fresh git checkout, one headless `claude -p` session, leak audit, independent judge |
| `eval/harness/summarize.py` | per case × condition table; per-trial outcomes; missing metrics shown as `n/a` |
| `eval/harness/engine_only.py [ENDPOINT]` | Faultline-only measurements, no agent |
| `tests/test_eval_harness.py` | harness self-tests with scripted "agents" (no model usage) |

**Prompt.** It is identical across conditions:
"The test {test} fails … Find and fix the bug in the application code …
Do not modify any test files. Use the tools available to you."

**Tools.**
- A: Read, Edit, Glob, Grep, `Bash(python -m pytest *)` and
  `Bash(pytest *)`.
- C and D: the same tools plus the three Faultline MCP tools, with the
  planner pinned server-side through `serve --force-planner`. C is
  deterministic and D is local-model.
- B is not implemented.

**Isolation.**
- Hidden tests are never copied into the agent checkout.
- `--disallowedTools` deny rules cover the private store and this
  repository.
- `--strict-mcp-config` is used.
- The full stream-json event log is audited for the private path, the
  repository path and the hidden test file name. Any hit marks the trial
  invalid; invalid trials are reported, not dropped.

  Deny rules do not stop arbitrary subprocesses (per the Claude Code
  docs), so the audit is the backstop.

**Judge.** A copy of the final checkout gets the hidden tests overlaid and
runs in a separate pytest process. A repair counts as correct only if the
test files are unchanged and the visible and hidden tests all pass.

**Metrics recorded per trial:**
- from the final `result` event (deduplicated): turns, wall and API time,
  input/cache-creation/cache-read/output tokens;
- tool calls by name;
- Faultline investigation statuses and metrics, and patch checks;
- the llama-server state (cold or warm, passed by the operator).

**Planned run size:** 5 cases × {C, D} × 3 trials = 30 sessions, plus A
for context if usage allows. Each session uses the operator's Claude plan.
**Not started; needs explicit approval.**

## Engine-only measurements (2026-10-18; no agent, no Claude usage)

These are single runs per cell on the frozen cases, so they are descriptive
only. **Raw record lost:** `eval/results/engine-only-20261018T074048Z.json`
was deleted by the implementation agent while regenerating results during
the token-saving pass. The numbers below were copied from it before
deletion. They also predate the engine changes in that pass, so they are
superseded by the section below and kept only as history.
Model: Qwen3-4B Q4_K_M on llama-server b11669.

| Case | C status / time | D status / time / fallbacks | Faulty line (tie group, size) | Faulty line observed (C / D) |
|---|---|---|---|---|
| e1_textstats | completed / 1.6 s | completed / 9.9 s / 0 | 1st, 3 | yes / yes |
| e2_shipping | completed / 2.1 s | completed / 12.3 s / 1 | 1st, 4 | yes / yes |
| e3_split | completed / 1.5 s | completed / 11.3 s / 1 | 1st, 5 | yes / yes |
| e4_config | inconclusive / 1.7 s | inconclusive / 7.7 s / 1 | not ranked | no / no |
| e5_slug | completed / 1.6 s | completed / 8.8 s / 0 | 1st, 1 | yes / yes |

Observations:
- On these five cases, D matched C on status and on whether the faulty line
  was observed. It cost 5–7× the wall time, and 3 of its 15 rounds fell
  back to the deterministic planner.
- In e4 the target test never executes the buggy line (a different test
  does), so target-focused SBFL cannot rank it. Faultline reports
  `inconclusive` with `isolated_reproduction_failed`.
- Whether any of this changes repair outcomes is exactly what the pending
  trials measure.

## Protocol pilot (2026-10-18): excluded from analysis

One real trial was run to test the harness end to end: e2_shipping,
condition C, trial 0. Claude Code 2.1.302 with `claude-opus-5-5`. The
record is `eval/results/pilot/e2_shipping-C-t0.json`.

- **Harness:** worked end to end.
  - The trial was valid, with no leak-audit hits.
  - The judge marked it correct: tests unchanged, visible and hidden tests
    passed, and the diff was `fees.py` with 1 line changed.
  - 5 turns, 15.8 s session; tokens: input 8, cache-creation 39,849,
    cache-read 116,304, output 849.
- **Finding:** the agent **did not call any Faultline tool** (Bash 2,
  Read 1, Edit 1; the server recorded 0 investigations). The bug was
  findable by reading one short file whose docstring names the missing
  constant.
- **Consequence:** under the neutral prompt, C and D collapse to A on cases
  this small, so the C-vs-D comparison would measure nothing.
- **Harness fix after the pilot:** keep the event log and record the
  session's init MCP status and offered tools. This is a measurement
  completeness fix.
- **Decision (user, 2026-10-18; protocol v2, fixed before any counted
  trial):** C and D append to the neutral prompt: "Before editing any
  file, call the investigate_failure tool on the failing test and use its
  evidence."
  - A keeps the neutral prompt.
  - C vs D therefore differ only in the server-pinned planner. A vs C now
    also differs by prompt, so A is context only.
  - Every record carries a `protocol` field.
  - This pilot is not counted in any results.

## Protocol-v2 pilot (2026-10-18): excluded from analysis

e2_shipping, condition C, trial 1. The record and event log are in
`eval/results/pilot/e2_shipping-C-t1.*`.

- **Session:** the Faultline MCP server was `connected`, and all three tools
  were offered.
- **Tool sequence:**
  1. `ToolSearch` (Claude Code loading the deferred MCP tools);
  2. `investigate_failure`, which returned `completed` in 2.4 s and 5,771 B;
  3. `Read` ×2 (`fees.py`, the tests);
  4. `Edit`;
  5. `check_patch` (full).
- **Outcome:** valid, no leak hits. Judged correct (tests unchanged, visible
  and hidden tests pass).
- **Session cost:** 7 turns, 28.7 s; tokens: input 10, cache-creation
  44,255, cache-read 163,230, output 1,053.
- **Agent's explanation:** it cited measured values ("4000 before that line
  ran and 8000 after").

Notes for the counted runs:
- `ToolSearch` appears in tool counts because Claude Code defers MCP tool
  schemas. It is reported, not removed.
- `check_patch` in `full` mode still lists `escalation_reasons`. They are
  informational there, but this could confuse readers; it is a candidate
  wording fix before counted runs.
- n = 1 per pilot: nothing here compares conditions.


## Token-saving pass (2026-10-18, before any counted trial)

**Why.** The protocol-v2 pilot used *more* agent tokens with Faultline:
7 turns vs 5, and 163k vs 116k cache-read tokens. Most agent cost is turns,
since every turn re-reads the context, so Faultline must remove turns to
save anything.

**Changes:**
- `investigate_failure` is marked `anthropic/alwaysLoad` (per Claude Code's
  MCP docs), so no `ToolSearch` turn is needed; the other tools stay
  deferred.
- Tool descriptions and server instructions are shortened (instructions
  458 → 72 characters; the upfront tool definition is 916 characters).
- The default investigate budget is 1,200 tokens (was 2,000).
- Responses are slimmer:
  - no `truncated:false`;
  - no digest;
  - short limitation details;
  - bookkeeping omissions merged into `audit_records`;
  - at most 3 handles per omission;
  - comparisons that don't fit are trimmed (values shrunk, highest-priority
    entries kept) instead of dropped;
  - up to 5 tied rows are listed before measured values, the rest after.
- `check_patch` in full mode returns no per-test list and no escalation
  reasons.
- **Engine fixes found on the new cases:**
  - child runs pin `PYTHONHASHSEED=0`, because dict-diff ordering made
    reruns look like different failures;
  - comparators are ranked by how many top-tie-group lines they cover;
  - the generator limitation is only flagged for function probes.

**Measured Faultline footprint** (engine, no agent; e1–e5):

| | Before | After |
|---|---|---|
| investigate response | 5,187–5,873 B (~1,730–1,960 tok) | 3,108–3,523 B (~1,040–1,170 tok) |
| check_patch response | 1,068–1,226 B | 795–823 B |
| tool-search turn | yes (pilot) | removed via alwaysLoad (not yet verified in a real session) |

These numbers are Faultline's output size only. Whether the *agent* uses
fewer tokens overall is what the A-vs-C trials measure.

**Cases added** (amendment, before any counted trial; only the two excluded
e2 pilots had run):

| ID | Category | Visible failing test | Provenance |
|---|---|---|---|
| e6_invoicing | multi-module, misleading symptom (8 modules) | `tests/test_invoice.py::test_invoice_jpy` | injected |
| e7_sessions | multi-module, misleading symptom (6 modules) | `tests/test_report.py::test_session_across_midnight` | injected |

- New private-store SHA-256:
  `3cd4188e57d6f8b533b29db698f39ad0f769c66c4a810112d74ab738c92db8a1`. All 7
  cases pass `validate_cases.py`.
- The e6 trap (patching the formatter where the symptom shows) passes the
  visible tests and fails the hidden ones. An e7 trap was not plausible and
  was dropped.

**Engine-only after the pass** (deterministic; raw record
`eval/results/engine-only-20261018T081220Z.json`):
- **e1, e2, e3, e5:** faulty line in the top tie group and observed.
- **e4:** `inconclusive` (by design).
- **e7:** faulty region in the top tie group (9 lines), with comparator
  values at the parser. The decisive `12:10 AM` hit is ambiguous-aligned
  and ranked low.
- **e6:** Faultline's top suspect is **wrong** (`discounts.py`). The buggy
  line runs for every currency, so SBFL cannot single it out. On e6,
  Faultline may cost the agent tokens.

**Protocol v3** (fixed before any counted trial): the same neutral prompt
for A, C and D, with no "call Faultline first" instruction. Every record has
`protocol: v3-neutral-alwaysload`.

**Primary token question:** A vs C on the same cases. Report per-case
medians of turns, output tokens and input + cache tokens, with the
correctness of every trial. An increase is reported as an increase.

## First counted trials: A vs C, protocol v3 (2026-10-18)

- **Setup:** e6_invoicing and e7_sessions × {A, C} × 3 trials = 12 sessions.
  Order was interleaved, and which condition ran first alternated per
  trial.
- **Environment:** Claude Code 2.1.302, `claude-opus-5-5`.
- **Records:** `eval/results/v3/` (JSON plus event logs); driver
  `eval/harness/run_ac_v3.sh`. All 12 are valid (no leak hits). A first
  launch attempt failed on argument parsing before any session started, so
  it consumed no usage and produced no records.

| Case | Cond | Correct | Turns (median) | Output tok (median) | Input+cache tok (median) | Tool calls (median) | Faultline calls |
|---|---|---|---|---|---|---|---|
| e6_invoicing | A | 3/3 | 5 | 976 | 158,436 | 4 | n/a |
| e6_invoicing | C | 3/3 | 5 | 985 | 160,725 | 4 | **0** |
| e7_sessions | A | 3/3 | 5 | 876 | 157,294 | 4 | n/a |
| e7_sessions | C | 3/3 | 5 | 905 | 159,797 | 4 | **0** |

**Result: no token saving.**
- In all 6 C sessions the agent was offered Faultline (loaded upfront) and
  **never called it**.
- It solved both cases in 5 turns. It ran `git ls-files`, ran the failing
  test, then read the *whole package* with one `cat pkg/*.py` (Bash
  read-only commands are allowed without approval), edited, and reran the
  tests.
- C cost about 2.3–2.5k more input+cache tokens per session (~1.5%), from
  the upfront tool definition. One C trial (e7 t1) took 6 turns.
- **Interpretation:** these multi-module cases are still small enough
  (~60–150 lines) to read in one command, so localization adds nothing. A
  saving can only appear where the codebase is too large to read
  wholesale. This was not tested.
- n=3 per cell; differences this small are within run-to-run noise except
  the systematic upfront-definition overhead.

## Independent check of the search redesign (Codex `search_code`), 2026-10-18

Verified by Claude Code. The suite passes: 123 tests, 1 live-model test
skipped.

**Codex benchmark not reproducible here.**
`eval/harness/search_benchmark.py` shells out to `rg`, which is not
installed on this machine, so its development records (runs 01–04) could
not be re-run.

**Offline search check on the 7 frozen cases** (no model, no Claude usage;
`eval/results/search-v1-heldout-claude-01.json`):
- **Query:** words from the failing test's name, with and without the test
  as a seed.
- **Ground truth:** the functions changed by the private reference fixes.
- **Comparison:** the bytes of `cat` over every app module, which is what
  the agent actually did in the v3 trials.

| Case | Buggy function's rank (with seed) | search_code bytes | cat bytes |
|---|---|---|---|
| e1_textstats | 2 of 8 | 2,468 | 579 |
| e2_shipping | 2 of 11 | 3,230 | 650 |
| e3_split | 2 of 3 | 1,327 | 385 |
| e4_config | not returned | 1,582 | 266 |
| e5_slug | 2 of 5 | 1,509 | 270 |
| e6_invoicing | 7 of 9 | 3,559 | 2,843 |
| e7_sessions | **not returned** (the parser is missing) | 3,540 | 2,503 |

On these repositories `search_code` returns more bytes than reading
everything, and it misses the bug in 2 of 7 cases. This is consistent with
Codex's own note that tiny repositories lose. (Rank 1 is usually the
failing test itself.)

**Session check, protocol v4** (`search_code` offered, tools deferred;
`eval/results/v4/`, driver `eval/harness/run_v4_check.sh`):
- **Sessions:** 8 in total: C ×3 and A ×1 on each of e6 and e7, with the
  A runs as a drift check against v3.
- **Validity:** all 8 valid and correct. Faultline was `connected` with
  all 4 tools offered in every C session, and was **called 0 times**.

| Case | A in+cache (v3 median; v4 single) | C v4 in+cache (median, n=3) | C v4 turns |
|---|---|---|---|
| e6_invoicing | 158,436; 158,386 | 159,437 | 5, 5, 5 |
| e7_sessions | 157,294; 157,736 | 196,985 | 5, 6, 8 |

- **Overhead:** deferring the tools cut the unused-tool overhead from
  ~2.3k to ~0.6–1.1k tokens per session.
- **e7 extra turns:** the 6- and 8-turn sessions involved no Faultline
  call. That is ordinary agent variance (one session made two edits), not
  a tool effect, and n=3 cannot separate it from noise.
- **Result: no token saving.** The search tool was never used, and on these
  repositories it would have returned more text than the agent's own `cat`.

## Real bug in a large codebase: e8_ytdl (2026-10-18, user-requested)

**Case.**
- BugsInPy youtube-dl bug #8: `ytdl-org/youtube-dl` buggy commit
  `cf2ac6df`, fixed `f5f4a27a`, with the test file taken from the fixed
  commit per the BugsInPy procedure.
- Size: 586 Python files; the `youtube_dl` package is 67,103 lines, and
  `YoutubeDL.py` alone is 2,000.
- Download: two GitHub tarballs (~0.7 MB each; sha256 `1b3c89d4…`,
  `22b748bd…`), approved by the user.
- The case lives outside the repository (`~/.faultline-eval-cases/e8_ytdl`).
- The configured suite is 9 offline test modules. `test_execution` is
  excluded because it fails on this Python for an unrelated
  environment-specific (umlaut) reason.
- No hidden tests: the judge is the configured suite plus a test-file
  integrity check. Validation passes: only the target test fails on the
  bug, and the upstream fix passes everything.
- **Not pre-registered.** It was added after the v3/v4 trials. Opus may
  also have seen this public 2015 code in training, which would favour
  condition A.

**Offline (no Claude usage):**
- `investigate_failure` took 3.7 s and returned `completed`. Its top tie
  group of 43 lines, executed only by the failing test, contains the buggy
  region, narrowing 67k lines to one nested function. No differing values
  were observed (43 tied lines, only 5 probed).
- `search_code` returned the right nested function
  (`_parse_format_selection`) as its 2nd hit, but its 24-line window ends
  at line 957, just before the buggy lines.

**Sessions** (protocol v4; A ×3, C ×3, interleaved; `eval/results/e8/`;
`eval/harness/run_e8.sh`):

| Cond | Correct | Turns | Input+cache tokens | Output tokens | Faultline calls |
|---|---|---|---|---|---|
| A | 3/3 | 7, 6, 6 | 250,100 / 205,109 / 203,967 (median 205,109) | median 1,518 | n/a |
| C | 3/3 | 8, 6, 6 | 292,806 / 206,228 / 206,241 (median 206,241) | median 1,509 | **0** |

**Result: no token saving, and no tool use.**
- The agent ran the failing test, read the traceback (which names the
  frames in `YoutubeDL.py`), opened the file at around line 900, fixed it,
  and reran the tests: 6 turns.
- The traceback gave localization for free, so Faultline was never needed.
- The C median is +1.1k tokens, from the deferred tool overhead; the
  first-trial outliers (7 and 8 turns) appear in both conditions.

## e8 with Sonnet 5.5: automatic-retrieval hook (Astra) vs ordinary tools (2026-10-18)

**What Astra added.** `faultline install-claude` installs a
`UserPromptSubmit` hook and a `faultline` skill. The hook injects at most
1,800 bytes of `search_code` results before the agent starts; the skill
describes the Faultline workflow. Tests: 132 passed, 1 skipped.

**New condition H** (protocol `v5-hook-auto`):
- `install-claude` is run in the trial checkout.
- Faultline MCP is configured (deterministic planner), with `Skill`
  allowed.
- `--include-hook-events` is passed so hook delivery is logged.

A uses the same ordinary tools as before. Both conditions use
`--model claude-sonnet-5-5` (recorded model: `claude-sonnet-5-5`).
Records are in `eval/results/sonnet/`; drivers: the first H trial was run
alone as a delivery check, then `eval/harness/run_e8_sonnet.sh`.

**Audit fix (rev 2).** The first H trial was flagged by the rev-1 leak
audit only because the hook's own injected text names the Faultline repo
path, in its suggested CLI command. The agent never accessed the repo or
the private store. Rev 2 ignores the repo path inside hook events only;
private-store needles are still checked everywhere. Trial H1 was re-audited
from its saved log and marked `reaudited`.

**Offline prediction, made before the sessions.** Simulating the hook on
the exact trial prompt injected `youtube_dl/options.py` and
`YoutubeDL.py:636-643` for e8, not the bug at around line 960. The prompt
has no traceback, so the hook can only do lexical search on the prompt
text. (On e6 and e7 it also injected the wrong module.)

| Cond | Correct | Turns | Input+cache tokens | Median input+cache | Median output | Hook delivered | Faultline MCP calls |
|---|---|---|---|---|---|---|---|
| A (Sonnet) | 3/3 | 9, 8, 9 | 338,697 / 289,632 / 330,318 | 330,318 | 1,689 | n/a | n/a |
| H (Sonnet) | 3/3 | 9, 9, 10 | 336,275 / 336,247 / 380,518 | 336,275 | 1,652 | 3/3 | **0** |

**Result: no token saving** (+1.8% median input+cache, same median turns).
- The hook context arrived every time, but it pointed at the wrong code.
- Sonnet localized the bug the same way Opus did: run the test, read the
  traceback, open the file.
- Sonnet needed 8–10 turns vs Opus's 6, but Faultline did not shorten that.
- n=3 per condition; one case; not pre-registered.

### v6 follow-up: evidence-timed hooks (offline verification only)

Session inspection found unrelated initial excerpts, parser warning output, and
repeated pytest executions to expose the traceback. See
[the detailed diagnosis](SESSION_DIAGNOSIS.md). New H runs use `v6-hook-evidence`;
the saved Sonnet v5 runs are unchanged. Offline replay returns the real crash
location in all three saved H sessions, 624 injected bytes each. This does not
measure repair speed or token savings. No new paid session was run.

## e8 with Sonnet 5.5: Astra v6 evidence hooks (2026-10-18): first measured saving

**What changed (Astra).** The prompt hook no longer does speculative
lexical retrieval. For a test node ID it suggests a compact pytest command
(`-q --tb=short --disable-warnings`). New `PostToolUse` and
`PostToolUseFailure` Bash hooks inject up to 1,800 bytes of source around
the last local traceback frame *after* a test run. AST SyntaxWarnings are
suppressed, and hook byte accounting is fixed. Protocol is
`v6-hook-evidence`.

**Verification before sessions.** 139 tests passed, 1 skipped. Astra's
offline replay was reproduced: 624 bytes, `YoutubeDL.py:991-998`, the
crash site. The causal lines are at about 960. The post-tool hook also
fired live in the implementing Claude Code session on a failed command.

**Sessions.** Fresh, interleaved, `--model claude-sonnet-5-5`;
`eval/results/sonnet-v6/`; driver `eval/harness/run_e8_sonnet_v6.sh`. All
6 valid (no leak hits) and correct.

| Cond | Turns | Input+cache tokens | Median input+cache | Median output | Hook events | Injected context |
|---|---|---|---|---|---|---|
| A | 10, 10, 9 | 379,113 / 380,400 / 336,192 | 379,113 | 1,994 | 0 | n/a |
| H (v6) | 5, 8, 6 | 162,804 / 298,597 / 211,796 | **211,796** | 2,036 | 6–12 | 964 B each |

**Effect.**
- H used 44% less median input+cache than this batch's A.
- Against all 6 Sonnet A runs on e8 (v5 and v6 batches; median about
  337k), it used about 37% less.
- Every H run used fewer tokens than every A run in this batch. One H run
  (298,597) exceeds the cheapest earlier A run (289,632).
- Output tokens were similar.

**Mechanism, from the event logs.**
- **A** reran the failing test 3–4 times to get past a flood of
  SyntaxWarnings (2015 code on Python 3.12), then dumped two large regions
  with `sed`.
- **H** followed the hook's compact pytest command and got a clean
  traceback on the first run. The post-tool hook then injected the
  crash-site excerpt; the agent read one region (830–1000), fixed the bug,
  and verified.
- Most of the saving comes from avoiding noisy reruns. The excerpt aims the
  read but shows the crash site, not the cause.

**Caveats.**
- One case and n=3 per arm; this case was not pre-registered.
- Earlier batches show high run-to-run variance (Sonnet A ranged 289k–380k).
- The warning flood is specific to this old codebase on modern Python, so
  repositories with clean test output may gain less.
- Opus did not have this problem (A: 6 turns, about 205k), so H vs A with
  Opus is untested.
- This is a saving in total session tokens for one model on one task. It is
  not a general claim, and not a dollar figure.

## v6 confirmation run (2026-10-18): 24 sessions, mixed result

**Design.**
- Sonnet 5.5 on e6, e7 and e8, plus Opus 5.5 on e8; A vs H (v6 evidence
  hooks); 3 trials per arm.
- Interleaved by trial, with A/H order alternating by trial and cell.
- `eval/harness/run_v6_confirm.sh`; records in `eval/results/v6-confirm/`.
- All 24 valid (no leak hits) and correct. Faultline MCP calls: 0 in every
  session. The hook delivered context in every H session.

| Model | Case | A turns | A input+cache (median) | H turns | H input+cache (median) | Change |
|---|---|---|---|---|---|---|
| Opus 5.5 | e8 (real, 67k lines) | 6, 6, 6 | 205,128 / 202,388 / 205,037 (205,037) | 5, 5, 5 | 160,479 / 160,689 / 159,982 (160,479) | **−22%** |
| Sonnet 5.5 | e8 | 8, 8, 10 | 293,323 / 286,048 / 385,575 (293,323) | 7, 7, 6 | 247,361 / 251,803 / 211,996 (247,361) | **−16%** |
| Sonnet 5.5 | e6 (small, multi-module) | 9, 7, 9 | 158,267 / 156,949 / 158,012 (158,012) | 7, 6, 7 | 237,731 / 197,066 / 196,848 (197,066) | **+25%** |
| Sonnet 5.5 | e7 (small, multi-module) | 9, 10, 6 | 156,903 / 197,062 / 155,997 (156,903) | 10, 6, 10 | 277,239 / 197,586 / 277,335 (277,239) | **+77%** |

**Pooled Sonnet e8 across both v6 batches** (n=6 per arm): median A
357,652 vs H 229,679 (−36%). Opus e8 v6 is tight and consistent (−22%,
with every H run below every A run).

**Why the effect reverses** (from event logs):
- **e8:** the failure crashes inside application code (`YoutubeDL.py:994`).
  The post-run hook injects that region, and the compact pytest command
  avoids warning-flood reruns. The agent reads one region and fixes.
- **e6/e7:** the failure is a plain assertion in the test file, with no
  application frame. The post-run excerpt can only show the test's
  assertion line. The agent still explores (`cat *.py`, several Reads), so
  the hook adds context without removing exploration. Per-turn context is
  larger in H (for example e6 t2: 6 turns and 180k cache-read for H vs 7
  turns and 139k for A).

**Conclusion.**
- v6 hooks reduced total session tokens when the traceback points into
  application code in a large, noisy repository: −16% to −36% for Sonnet,
  −22% for Opus.
- They increased tokens (+25%, +77%) on small repositories where the
  failure is a bare test assertion.
- There is no across-the-board saving. A sensible next change: inject
  nothing (and suggest nothing) when the last traceback frame is in a test
  file, or when the repository is small enough to read in one command.
  Re-measure afterwards.
- n=3 per cell, high run-to-run variance on Sonnet, injected cases (e6/e7)
  plus one real case (e8); no cell was pre-registered for v6.

## v7 silence rules (2026-10-18): cost on small repositories back to near zero

**Change** (`src/faultline/claude.py`, protocol `v7-hook-silence`):
1. **Small repository:** all hooks stay silent, including the pytest
   suggestion, when non-test Python source is ≤ 64 KiB.
   `FAULTLINE_SMALL_REPO_BYTES` overrides this, and 0 disables the rule.
2. **Test-file frame:** the post-run hook injects nothing when the deepest
   traceback frame is in a test file (a bare assertion).

Tests: 142 passed, 1 skipped (3 new silence-rule tests).

**Offline replay of the saved v6 logs** through the new code:
- e6: 0 injections out of 17 tool results; the prompt hook is silent.
- e7: 0 out of 23; silent.
- e8 (large): the prompt suggestion and its 3 app-frame injections are
  unchanged.

**Sessions.** Sonnet 5.5, e6/e7, A vs H, 3 each, interleaved;
`eval/results/v7-silence/`; `eval/harness/run_v7_silence.sh`. All 12 valid
and correct. Injected context in H: **0 bytes in 6/6** (hooks ran, 4–6
events, and returned nothing).

| Case | A turns | A input+cache | H turns | H input+cache |
|---|---|---|---|---|
| e6 | 6, 11, 8 | 156,038 / 235,197 / 196,469 (median 196,469) | 7, 9, 7 | 158,168 / 158,474 / 158,316 (median 158,316) |
| e7 | 7, 7, 6 | 156,418 / 156,047 / 196,968 (median 156,418) | 9, 10, 11 | 157,664 / 197,598 / 199,158 (median 197,598) |

**Reading.**
- Because H injected nothing, the per-case differences (−19% on e6, +26% on
  e7) reflect Sonnet's turn-count variance (6–11 turns at about 20k tokens
  each), not Faultline content.
- Pooled means: A 182,856 vs H 171,563.
- The remaining systematic cost is the installed skill plus MCP tool names:
  cache creation is about +500 tokens per session (H ≈17.7–18.7k vs A
  ≈17.0–18.2k).
- On these small repositories the v6 penalty (+25% / +77%) is removed in
  content terms. Proving "exactly zero" would need many more runs than n=3,
  given this variance.
- The v6 e8 saving should be unaffected, since e8 is a large repo with an
  app-frame crash. It was not re-run under v7.

## Capture milestone: development verification (2026-10-18)

New v8 treatment exposes capture_failure/read_capture and guidance to retain a
single failing run. Existing v7 silence behavior is preserved. All earlier
records remain unchanged. See FAILURE_CAPTURE.md for semantics and limits.

The engine-only known e8 run in capture-v1-e8-development-02.json required no
variable hint: the None-origin candidate summary includes line 961, plus the
subsequent selector-list change before the crash at 994. CLI summary 2,721 bytes;
wall time 1.2329 s; unchanged capture reuse 0.0635 s. A variable-filtered read
retrieved the transition without another test execution. This is a development
case used for tuning, not a held-out discovery or agent repair trial. No new
paid Claude sessions were run, and prior v6 token savings cannot be attributed
to the new capture tools. New tools also add discovery overhead.

## v8 capture (Astra `capture_failure` / `read_capture`), e8, 2026-10-18

**Verification.**
- 153 tests passed, 1 skipped.
- Independent CLI capture on a fresh e8 checkout: 1.26 s, 2,742 bytes. The
  change list includes `current_selector` at line 962 and `selectors` at
  957, the buggy region (cause ≈961, crash at 994). This reproduces Astra's
  development record. Not blind: the feature was developed on this case.

**Sessions.**
- e8, A vs H (`v8-capture-hook`), Sonnet 5.5 and Opus 5.5, 3 each,
  interleaved.
- `eval/results/v8-capture/`; `eval/harness/run_v8_capture.sh`.
- All 12 valid and correct.

| Model | A turns | A input+cache (mean) | H turns | H input+cache (mean) | Saved |
|---|---|---|---|---|---|
| Opus 5.5 | 8, 7, 6 | 292,570 / 250,146 / 205,958 (249,558) | 5, 5, 5 | 161,045 / 161,095 / 160,246 (160,795) | 35.6% |
| Sonnet 5.5 | 11, 8, 9 | 375,554 / 285,452 / 330,389 (330,465) | 6, 6, 8 | 203,648 / 211,268 / 297,565 (237,494) | 28.1% |

**`capture_failure` / `read_capture` calls: 0 in 6/6 H sessions.** The
prompt hook offered `capture_failure` or the compact pytest command; Claude
chose the pytest command every time. The post-run hook then injected the
crash-site excerpt (`YoutubeDL.py:991-998`), and the agent read one region
and fixed it.

So this batch re-measures the **v6 hook mechanism**, not capture. H totals
match v6 (Opus H mean 160,795 vs 160,383 in v6). Capture's value is still
**unmeasured in agent sessions**.

**Pooled e8 hook results** (v6 + v8, A vs H, n=15 per arm across both
models): mean input+cache 294,218 → 204,025, **30.7% saved**. That is Opus
29.2% (n=6) and Sonnet 31.3% (n=9). All correct.

The hooks were the same in v6 and v8 apart from the capture suggestion in
the prompt text. One real bug, not pre-registered.

## v9 auto-capture: hook runs the capture and injects the cause candidate (2026-10-18)

**Change** (`src/faultline/claude.py`, protocol `v9-auto-capture`). On an
app-code crash in a large repository (the silence rules still apply
first), the post-run hook:
- finds the failing node in pytest's summary;
- runs `capture_failure` (7 s limit, 10-minute reuse);
- injects the crash-site block plus the latest None-origin candidate.

Candidate rule: prefer the most recent direct None assignment *outside*
the crashing function (the upstream producer), then a direct None
anywhere, then any candidate. The first version picked line 987 (`s`
taking the None out of a list inside the crashing function), which is why
this rule was added. Injected text is capped at 2,000 bytes.

**Offline check on e8.** 1.20 s (0.08 s reused), 1,285 bytes: the crash
site `YoutubeDL.py:994` plus the candidate `YoutubeDL.py:961`
(`current_selector = None`), whose block shows lines 958–965 including
the upstream fix lines. Tests: 156 passed, 1 skipped (3 new). Not blind:
e8 informed the rule.

**Sessions.** e8, A vs H, Sonnet 5.5 and Opus 5.5, 3 each, interleaved;
`eval/results/v9-auto-capture/`; `eval/harness/run_v9_auto_capture.sh`.
All 12 valid and correct. The cause block reached the agent in 6/6 H
sessions; agent-initiated Faultline tool calls: 0.

| Model | A input+cache | A mean | H input+cache | H mean | Saved |
|---|---|---|---|---|---|
| Opus 5.5 | 204,895 / 204,907 / 205,001 | 204,934 | 160,379 / 160,682 / 160,326 | 160,462 | 21.7% |
| Sonnet 5.5 | 297,848 / 385,648 / 291,265 | 324,920 | 252,861 / 204,686 / 245,351 | 234,299 | 27.9% |

**Against earlier hook versions** (H means on e8): Opus is 160,383 (v6) /
160,795 (v8) / 160,462 (v9); Sonnet is 230,726 / 237,494 / 234,299. **The
cause candidate added no measurable saving on e8.**
- Opus is already at a 5-turn floor (run, read, edit, verify, answer).
- The cause (961) is 33 lines from the crash (994), so the one region the
  agent reads already contains both.

A benefit would require cases where the cause is far from the crash (other
function or file, or beyond a single read window); none are in the case
set yet.


## Open-model agent: Gemma 4 12B local and Gemma 4 API attempts (2026-10-18)

**Gemma 4 via the Gemini API** (`gemma-4-26b-a4b-it`, thinking `minimal`):
- Attempt 1 (`eval/results/agent-gemini-attempt1-http500/`): 7 of 8 trials
  ended on HTTP 500 INTERNAL.
- Attempt 2 (`agent-gemini-attempt2-slow/`): stopped after the first trial
  ran for more than 8 minutes in rate-limit and server-error waits.
- These are **not results.** One completed attempt-1 trial (A t3) "fixed" e8
  with a None guard at the crash site. That is a symptom patch, which passed
  because e8 has no hidden tests.

**Gemma 4 12B local** (`google/gemma-4-12B-it-qat-q4_0-gguf`, sha256
`93567e57…538b`, 6.98 GB, llama.cpp b11669): `eval/results/agent-local/`.
Faultline context was delivered via the MCP `failure_context` tool over
stdio.
- Temperature 0 with a fixed seed made repeats identical (H t1 = H t2 step
  for step), so the run was stopped after A t1, H t1 and H t2.
- **A:** 30 steps (max), 88,292 tokens, not fixed. It read the crash site
  980–1010 and repeatedly edited around `if current_selector:`.
- **H:** 30 steps (max), 99,155 tokens, not fixed. After the injected
  context it read 950–1010 and repeatedly attempted `current_selector = None`
  (line 961, the real cause). Its edits never matched the file text exactly.
- **Reading:** Faultline redirected the open model from the symptom to the
  root cause, but the 12B model could not produce a valid exact-match edit.
  There was no fix and no token saving.
