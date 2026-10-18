# Automatic Claude retrieval

Optional MCP tools were connected but unused in the recorded v4 repair trials,
including the large youtube-dl case. Availability did not cause activation and
those trials did not demonstrate token savings.

Install automatic retrieval once per project, using the Python environment that
contains Faultline:

```sh
faultline install-claude --repo /absolute/path/to/project
# Source checkout alternative (run from Faultline):
PYTHONPATH=src .venv/bin/python -m faultline.cli install-claude --repo /absolute/path/to/project
```

Start a new Claude Code session in that project. The installer merges a
UserPromptSubmit and Bash PostToolUse/PostToolUseFailure command hooks into `.claude/settings.local.json` and installs
`.claude/skills/faultline/SKILL.md`. Existing unrelated settings/hooks are retained;
a user-owned skill at that path causes an error rather than being overwritten.
Reinstalling replaces the managed hook. No global settings or MCP registrations
are changed. Existing MCP setup remains necessary for runtime investigation tools.
The hook itself works without an MCP connection or a local model.

Default `--mode debug` inspects English debugging/test/review prompts or
`/faultline`. `--mode always` removes that keyword gate; it does not force
irrelevant excerpts into the context. Both modes retrieve only when the prompt
supplies a source location. A pytest node ID without a traceback receives a short
capture-once suggestion (`capture_failure`) with a compact pytest fallback instead of
speculative source hits. Other vague prompts produce no injected text.

The Bash result hooks inspect failure output and retrieve the last recognized
in-repository traceback frame. Warning locations, successful results, and missing
frames produce no injection. Both successful Bash tool completion (including
commands returning test failures as output) and tool-error events are handled.
These hooks do not rerun tests, rewrite commands, replace tool output or block
Claude. The agent makes and verifies edits; Faultline never edits the application.
Use `/faultline describe the failure` for the repair workflow.

The hook runs the same retrieval engine as `search_code` directly. Report this
as **hook/engine activation**, separately from MCP tool calls. A zero MCP-call
count no longer proves the engine was unused. Inspect Claude's debug log for
hook execution and additional-context delivery. If project hooks are disabled,
the executable moves, or a hook times out, automatic context is unavailable.
Restart after installation; test hook delivery in the actual Claude client.

Each successful hook injects at most 1,800 UTF-8 bytes (600 estimated tokens using
bytes/3, not an actual tokenizer count). It runs no inference or target tests.
Source search is capped; the hook has a 10-second client timeout. Malformed
input and retrieval errors fail open. The budget covers injected text, not
Claude's wrapper, loaded skill, subsequent reasoning, or total session tokens.
Broad prompts wait for evidence; use MCP search explicitly for exploratory symbol
search. Repeated failed tool executions may repeat context, so rerunning unchanged
tests still costs tokens. The hook does not remove the original tool output.

For traceback locations use `search_code(query="path/to/file.py:960")` or:

```sh
faultline search --repo /path/to/project --python /absolute/python \
  'path/to/file.py:960' --budget-tokens 500
```

This reads one bounded file instead of scanning the repo and preserves the
requested line even when the excerpt must shrink to fit the budget. Request
adjacent line numbers for omitted surrounding code. The hook recognizes Python
`File "path.py", line N` and `path.py:N` locations in the user prompt. Bash result hooks also see tracebacks generated later in the agent turn.
Truncated tool output can hide them; run a compact reproduction instead of piping
long pytest output through head/tail. Default lexical search still has heuristic ranking and may miss
bugs. A short source excerpt is not complete runtime evidence.

The original prompt-only hook was delivered in all three recorded v5 Sonnet
sessions, but gave the wrong excerpts and showed no saving (+1.8% median
input+cache). The revised hooks were verified by local subprocess tests and
offline replay of those sessions, not by a new paid Claude run. See
[session diagnosis](SESSION_DIAGNOSIS.md) for measurements and limitations.

For the next benchmark, use a distinct condition/protocol for automatic hooks;
keep optional-MCP v4 trials unchanged. Compare the same initial checkout, task,
model and test scope; record hook activation, MCP calls, entire-session input,
cache and output tokens, elapsed time, test results and repair correctness.
Include irrelevant prompts and failures without traceback locations. Claim a
saving only if the complete repair trial shows it. No system can guarantee
finding all bugs; the workflow verifies the configured test scope.

Hook format verified against the official Claude Code hooks reference:
https://code.claude.com/docs/en/hooks

The repair skill now recommends capture_failure for a known test and read_capture
for retained output/history. Hooks suggest this route; they do not silently run
tests or guarantee that the agent calls it. See FAILURE_CAPTURE.md.
