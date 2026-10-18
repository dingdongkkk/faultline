# Why the recorded sessions did not save tokens

Inspected on 2026-10-18: `eval/results/sonnet/e8_ytdl-H-t{1,2,3}.events.jsonl`,
associated A/H result records, earlier e8 C records, and the harness. These are
existing Claude Code 2.1.302 sessions; no paid agent session was started here.

## Findings

1. Optional MCP availability was insufficient: v4 e8 C sessions connected all
   four tools but used none. Ordinary tools successfully repaired the selected
   bug. It would be incorrect to describe those sessions as failed repairs.
2. The v5 prompt hook did fire in 3/3 Sonnet H sessions. Its lexical search used
   the neutral repair instructions before failure evidence existed and injected
   `options.py:157–164` and `YoutubeDL.py:636–643`, unrelated to the selected bug.
   Forcing activation did not make those excerpts useful.
3. Each H hook response log contained **45,689 UTF-8 bytes**, including AST
   SyntaxWarnings while parsing old Python source. The 1,800-byte cap applied
   only to additionalContext, not diagnostic stderr. These are logged output
   bytes, not proof that every warning byte reached the model context.
4. In H1/H2, Claude ran the failing test four times before editing: tail showed
   warnings, a grep command returned no output, then head and sed exposed the
   failure. H3 also repeated the test with different output filters. The real
   traceback reports `YoutubeDL.py:994`, where `selector` is None. That identifies
   the crash site; the causal parser mutation is around 960–962.
5. H1/H2 then read 1040–1130 and 905–985 before fixing the parser. The first hook
   never saw the later traceback, so it could not help at that decision point.
6. Recorded Sonnet H median input+cache was 336,275 versus A's 330,318 (+1.8%).
   Both repaired 3/3, median nine turns. This is one case with three runs per arm,
   not evidence of a broad effect. Cache tokens are not equivalent to uncached
   billing cost. MCP calls remained zero.
7. The harness's `hooks.context_bytes` counted an entire serialized event,
   including warnings and escaped JSON. It did not measure additionalContext.

## Changes

- Prompt hooks retrieve only explicit source locations. A test node without a
  traceback gets a compact pytest command suggestion; vague prompts stay quiet.
  This intentionally removes speculative automatic lexical retrieval. Explicit
  MCP/CLI search remains available.
- Bash PostToolUse and PostToolUseFailure hooks retrieve the last recognized
  local traceback frame after evidence arrives, with the existing 1,800-byte
  injected-text cap. They do not execute tests or replace output.
- Warning-only paths are excluded from traceback parsing. AST SyntaxWarnings
  are suppressed around source parsing without changing target pytest behavior.
- Hook measurements now count additionalContext separately from raw hook output.
  New H runs are protocol `v6-hook-evidence`; old v5 records remain untouched.
- Installer updated in this checkout. Reinstall in other projects and start a
  new Claude session to load the new event hooks.

## Verification and remaining limits

`eval/harness/replay_hooks.py` replays saved Bash results through the current
hook, using the existing external youtube-dl checkout. The new record is
`eval/results/hook-v6-offline-replay-01.json`. All three logs produce a 624-byte
excerpt of `YoutubeDL.py:991–998` when the traceback appears. Warning-only
results inject nothing. No historical record was rewritten.

This is a replay with known source and saved outputs, not a counterfactual
agent repair or client delivery test. It does not prove Claude will choose the
compact pytest command, stop rerunning tests, use the excerpt, find the causal
mutation faster, or save total tokens. The causal parser region remains outside
the first crash-site excerpt; follow-up search/runtime evidence is still needed.
A hook cannot recover a traceback that head/tail already removed. Larger logs
above the input cap fail open. Repeated failed executions can repeat excerpts.

Local regression coverage checks generated hook commands and event names,
settings preservation, quiet success/warning outputs, source boundaries,
line retention, parser-warning suppression, neutral-prompt deferral and accurate
hook byte accounting. No new live-model or live Claude verification is claimed.

Next measurement: run the existing A/H harness into a fresh output directory
with v6, preserving model/task/test scope, and compare full-session usage and
repair correctness. Keep v4, v5 and v6 separate. Do not infer savings from
activation count or excerpt size alone.

Hook schema checked against the official reference:
https://code.claude.com/docs/en/hooks
