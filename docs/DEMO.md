# New opening: bounded code search

The runtime demo below is a historical fixture transcript. The MCP server
subsequently passed a real Claude Code fixture session (BUILD_STATUS.md).
The new search route has protocol verification; its agent-token trial is pending.

Show `search_code("JPY invoice wrong total", failing_test="tests/test_invoice.py::test_invoice_jpy")`
on the invoicing fixture. It returns the named test and relevant currency
functions despite the old SBFL misranking. Show the source and reasons; do not
claim that retrieval has proven the root cause. For a precise request, search
`invoicing/currency.py::minor_units`. Pass returned IDs in seen_ids to request
new context, or leave the ID out to revisit an excerpt.

Then show an exact-symbol search in a larger file and compare serialized
response size with the recorded rg/read baseline. Include the tiny-file
control where Faultline is larger. Label all sizes as bytes/estimated tokens.
Escalate to investigate_failure only for unresolved runtime questions, let
the main agent edit, then run regression checks.

---

# Demo

Status: the **deterministic** slice runs end to end through the CLI on a
fixture project. The **local-model** planner is live-verified (M6). The
MCP transport and the real-agent fix are **not done yet** (M7). Every number below
comes from one run on 2026-10-18 on the development Mac (Apple M5, 16 GB,
Python 3.12.14). It is a fixture run, not a benchmark.

## Fixture: `tests/fixtures/shop`

`shop/cart.py` has a bulk-discount rule: discounts apply to orders of *more
than* 10 items. The bug is `if qty >= threshold:`.
`test_bulk_threshold[10-1000]` fails; the other four tests pass.

## 1. Investigate (deterministic planner)

```bash
faultline investigate --repo tests/fixtures/shop --python .venv/bin/python \
  "tests/test_cart.py::test_bulk_threshold[10-1000]"
```

Observed result: `status=completed`, `stopping_reason=planner_stopped`.
Wall time was 1,137 ms (coverage run 317 ms, observation runs 595 ms). The
response was 5,878 bytes, an estimated 1,960 tokens against the 2,000
budget.

- **Tie, shown explicitly.** T1 has 3 members with identical counts
  (ef=1, ep=2, score 0.5774):
  - `cart.py:12`, `rate = tiers[threshold]`
  - `cart.py:25`, `AUDIT.append(rate)`
  - `cart.py:36`, `log_discount(rate)`

  T2 has 13 members at ep=3; 2 are shown and 11 are listed as an omission
  with handle `T2`.
- **Comparator:** `test_bulk_threshold[12-1080]`, chosen as
  `jaccard=1.000; sibling=yes`.
- **Rounds:** `inspect_locations(L1,L2,L3)` on the target and the
  comparator, then `compare_observations`, then `stop(sufficient_evidence)`.
- **Measured before-line values at L1** (`rate = tiers[threshold]`):
  `qty` 10 in the failing run vs 12 in the passing run. The alignment is
  unambiguous. `threshold` was equal (10) and is counted in
  `equal_count=6`.
- **Excerpt** of `bulk_rate`, lines 8–13, including line 11
  `if qty >= threshold:`.
- **Labels:** `before_line_semantics` and `association_not_causation`. The
  first divergence is not presented as the cause.

## 2. Agent fix (done by hand here)

`if qty >= threshold:` → `if qty > threshold:`

## 3. Check the patch (default `mode="full"`)

```bash
faultline check-patch --repo tests/fixtures/shop --python .venv/bin/python <investigation_id>
```

Observed result:
- `effective_scope=full`, `status=passed`, 5 passed;
- `previously_failing_now` reports the target as `passed`;
- `full_regression_verified=true` (configured suite only);
- 278 ms, with a 1,181-byte response.

## Inconclusive case: `tests/fixtures/registry`

`test_b_lookup_default` fails only after `test_a_register` mutated module
state. The investigation keeps the suite ranking, but the isolated
reproduction check returns `not_reproduced`. The status is therefore
`inconclusive`, with the limitation `isolated_reproduction_failed` and an
unresolved note about possible order dependence. This is covered by
`tests/test_workflow.py::test_order_dependent_failure_is_inconclusive_with_ranking_kept`.

## Local-model choice (M6, live)

The same shop investigation was run with `planner="local-model"` against
llama-server and Qwen3-4B Q4_K_M, in the live gate (attempt 3). The model
chose these actions:
1. `inspect_locations`;
2. `compare_observations`;
3. a second `inspect_locations`. On one repeat this was model-chosen; on
   the other the model kept repeating itself and the deterministic fallback
   chose it.

The status was `completed`, in 7.2–12.1 s wall, against 1.1–1.3 s
deterministic. Raw records are in `eval/live_gate/gate-20261018T071636Z.json`.

## Through MCP (M7)

**Protocol level (done).** `tests/test_mcp_protocol.py` runs
`faultline serve` over stdio with the MCP SDK client: investigate, then
expand, then the fix, then `check_patch` (full, passed).

**Real agent (done once, 2026-10-18).** `scripts/client_check.sh` had Claude
Code (CLI 2.1.301) use only the Faultline tools plus Read/Edit.

- **Result:** it investigated, then changed `>=` to `>` in `bulk_rate`
  without touching the tests, then ran `check_patch`, which returned
  `passed` with `full_regression_verified: true`.
- **Independent pytest:** 5 passed.
- **Session:** 6 turns, 17.4 s.
- **Agent's explanation (excerpt):** it said comparing the failing run
  (qty=10) with the passing one (qty=12) showed that quantity was the only
  difference.
- **Record:** `eval/client_check/client-check-20261018.json`.

This is one session on a fixture, not a benchmark.

What the demo must **not** claim: root cause proven, token savings, or that
the model's choice beats the deterministic one. Comparing the two is the
evaluation's job.
