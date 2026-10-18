# Search and context-budget redesign — 2026-10-18

## Objective and diagnosis

Reduce source context received by the main agent and search/read steps,
while preserving repair correctness.

Previous v3 trials found no saving: six C sessions never used Faultline.
The cases were readable wholesale. Coverage also ranked discounts above
faulty currency code in e6. Compressing a tracing report cannot fix either
problem. Unconditional model calls would add unproven overhead.

Static source retrieval is now the first layer. Coverage/tracing is a
separate escalation layer, never the only filter on searchable code.

## Implemented contract

`search_code(query, failing_test=None, budget_tokens=1200, seen_ids=None)`
returns `SearchResponse` with independent `search_version=1`:

- Original source with file, qualified symbol and numbered lines.
- Exact-symbol priority; otherwise identifier splitting, inverse-frequency
  lexical weights, module context and explicit static relationships.
- Optional named test seed; imports/aliases, local calls and module constants
  provide dependency traversal capped at five edges.
- Direct callers of general-query seeds are considered. Dynamic dispatch,
  wildcard imports, arbitrary instance-method inference and ambiguous module
  names are unresolved. This is not a complete call graph or data-flow slice.
- Normal windows have at most 24 lines, each capped at 240 characters.
  An eight-line fallback preserves higher-ranked context under tight budgets.
  Overlapping returned windows are suppressed. Truncation is explicit.
- Content-derived IDs make identical excerpts skippable via `seen_ids`.
  This is caller-controlled: send only IDs still available in the conversation.
  A different window may overlap an earlier one. Edits change IDs.
- `omitted` counts remaining candidates. Refine the query or pass seen IDs
  for further candidates. Runtime evidence expansion remains separate.
- Status: ok, no_matches, no_new_context, budget_too_small.
- Scan limits: 2000 Python files, 256 KiB/file, 16 MiB total, 20,000 encountered
  file entries and a five-second cooperative scan deadline. Parsing a bounded
  file is not preempted. No repository execution or following symlinks.
- Each call scans current source. No persistent index or execution cache.
  Large-repository latency is a future measurement, not a scalability claim.
- Source content is untrusted. Results are retrieval, not measured runtime facts.

Minimum budget: 400 estimated units. The complete `CallToolResult`, including
escaping and SDK serverInfo, fits `3 * budget_tokens` bytes. CLI scope is its
JSON payload. Bytes/3 is an estimate, not a main-model tokenizer guarantee.
Client wrappers, tool definitions and discovery are counted in session trials.

## Development measurements

Run:
`PYTHONPATH=src .venv/bin/python eval/harness/search_benchmark.py --output NEW_PATH.json`

The script refuses to overwrite records. No model, subscription, private store
or hidden tests are used. Runs 01–04 are retained. Rankings changed in response
to these cases, so run 04 is a development check, not held-out validation.

Source: `eval/results/search-v1-development-04.json`.

| Case | rg + read matching files, bytes | rg with 8 context lines, bytes | Faultline MCP bytes | Target in first result |
|---|---:|---:|---:|---|
| Tiny shop control | 1,272 | 2,031 | 3,308 | yes |
| Invoicing | 2,851 | 4,644 | 3,575 | yes |
| Sessions | 3,947 | 6,650 | 3,589 | no |
| Faultline source search | 146,039 | 74,451 | 3,454 | yes |
| Exact symbol control | 4,326 | 1,844 | 1,207 | yes |
| Synthetic 200 functions | 20,207 | 731 | 797 | yes |

Sessions requires follow-up context; count its extra calls and bytes. All six
selected targets appear within three requests. Target presence does not prove
sufficient repair context. Large reductions against broad OR-term searches can
overstate benefits versus a skilled agent's narrower query. The exact-symbol
baseline keeps exact identifiers; rg wins on the synthetic case. The tiny
control is 160% larger with Faultline. Keep these losses in every report.

## Usage policy

Use direct Read/rg for a known small file or exact line. Use search_code when
broad matches or large files would flood context. It combines ranking and
reading into one call, but turn reduction requires agent measurement. Refine
or inspect a named symbol, then investigate only unresolved runtime questions.

Forced alwaysLoad is removed because v3 paid for an unused definition. Actual
deferral is client-dependent and discovery can itself cost a call. Count both.

## Open-model role and next gates

The existing local model still selects runtime observations. It does not
currently improve source search. The next optional experiment is a bounded
local reranker: given candidate IDs, short signatures and the query, select a
subset or one search refinement. The engine validates IDs and returns original
source. Exact-symbol and tiny queries bypass inference; invalid output falls
back. This reranker is NOT implemented or established as useful.

Before claiming savings:
1. Freeze unseen real repositories/tasks, small-file controls and no-match
   cases. Keep all outcomes and versions. Label injected bugs.
2. Compare ordinary rg/read, deterministic search, and the same search with
   optional local reranking. Compare runtime investigation separately.
3. Measure target-definition recall at fixed budgets, source lines exposed,
   follow-up calls and p50/p95 latency. Record omissions and no-match results.
4. Run equal-budget repair sessions with the same main model/settings and
   independent hidden tests. Include tool non-use and fallback in primary results.
5. Suggested preregistered gate: at least 25% lower median total main-agent
   input/cache/output tokens on the selected search-heavy set with no observed
   correctness loss. Report categories separately, paired per-case outcomes
   and uncertainty. This is an acceptance target, not a result.

If only retrieval size improves, describe bounded source retrieval. If local
reranking adds no benefit, keep it optional and reconsider the strength of the
open-model contribution rather than forcing usage for the hackathon.

## Automatic activation follow-up (2026-10-18)

The subsequent v4 large-repository trials still made zero Faultline calls.
See [Claude integration](CLAUDE_INTEGRATION.md) for the opt-in project hook and
repair skill. `search_code` now accepts `path.py:LINE` to bypass whole-repository
ranking and retain the exact requested line. Hooks run retrieval directly;
measure engine activation separately from MCP-call counts. Whole-session savings
for the hook treatment remain unverified.
