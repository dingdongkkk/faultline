# Faultline evaluation data (exported 2026-10-18)

All numbers come from real runs on this Mac. Rebuild with `eval/harness/export_data.py`. Nothing is estimated or
invented. Missing values are blank, not 0.

## Files here

| File | What it is |
|---|---|
| `all_sessions.csv` | One row per real Claude Code repair session (100 rows): batch, case, condition, protocol, model, validity, correctness, turns, input / cache-creation / cache-read / output tokens, duration, tool calls, Faultline MCP calls, hook events and injected bytes |
| `agent_sessions.csv` | Open-model agent trials (Gemma 4 / local), written once such trials exist |
| `summary_by_cell.csv` | One row per batch × model × case × condition (36 cells): n, correct, turns per trial, median / mean / min / max input+cache tokens, median output, Faultline calls, injected hook bytes |

## Conditions and protocols

| Code | Meaning |
|---|---|
| A | ordinary tools only (Read, Edit, Glob, Grep, pytest via Bash) |
| C | A + Faultline MCP tools, offered optionally (deterministic planner) |
| H | A + Faultline MCP + automatic hooks + skill (Astra) |
| pilot | excluded protocol pilots (v1 neutral, v2 "call Faultline first") |
| v3 | neutral prompt, `investigate_failure` loaded upfront |
| v4 | neutral prompt, all tools deferred, `search_code` added (Codex) |
| v5 | prompt hook with lexical retrieval |
| v6 | evidence hooks: compact pytest command + post-run traceback excerpt |
| v7 | v6 + silence rules (small repo ≤64 KiB; crash frame in a test file) |

## Batches (folders in `eval/results/`)

| Folder | Sessions | Model | Cases | Comparison |
|---|---|---|---|---|
| `pilot/` | 2 | Opus 5.5 | e2 | protocol pilots (excluded) |
| `v3/` | 12 | Opus 5.5 | e6, e7 | A vs C |
| `v4/` | 8 | Opus 5.5 | e6, e7 | A (drift check) vs C with `search_code` |
| `e8/` | 6 | Opus 5.5 | e8 (real youtube-dl bug) | A vs C |
| `sonnet/` | 6 | Sonnet 5.5 | e8 | A vs H (v5) |
| `sonnet-v6/` | 6 | Sonnet 5.5 | e8 | A vs H (v6) |
| `v6-confirm/` | 24 | Sonnet 5.5 + Opus 5.5 | e6, e7, e8 | A vs H (v6) |
| `v7-silence/` | 12 | Sonnet 5.5 | e6, e7 | A vs H (v7) |
| `v8-capture/` | 12 | Sonnet 5.5 + Opus 5.5 | e8 | A vs H (v8, capture offered) |
| `v9-auto-capture/` | 12 | Sonnet 5.5 + Opus 5.5 | e8 | A vs H (v9, hook runs capture) |

Each session also has a raw `*.events.jsonl` log next to its JSON record,
except the v3 batch and the first pilot, whose logs were not kept (fixed
afterwards).

## Offline data (no Claude usage)

| File | What it is |
|---|---|
| `eval/live_gate/gate-*.json` | Local-model planning gate (Qwen3-4B Q4_K_M): 3 attempts; the first two failed and the third passed |
| `eval/results/engine-only-*.json` | Faultline engine on the cases: status, faulty-line rank, timing (the first C/D file was lost; disclosed in docs/EVALUATION.md) |
| `eval/results/search-v1-development-0{1..4}.json` | Codex's search benchmark (needs `rg`; not reproducible here) |
| `eval/results/search-v1-heldout-claude-01.json` | Independent search check on e1–e7 |
| `eval/results/hook-v6-offline-replay-01.json` | Astra's hook replay on the saved logs |
| `eval/client_check/client-check-20261018.json` | First real Claude Code + MCP session (M7 gate) |

The case definitions are in `eval/cases/` (e1–e7) and
`~/.faultline-eval-cases/e8_ytdl`. The hidden tests and reference fixes are
private, in `~/.faultline-eval-private/`, and are not exported. Write-ups
with caveats are in `docs/EVALUATION.md`.
