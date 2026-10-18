# Capture a failure once and inspect its value history

This milestone adds `capture_failure` and `read_capture` to the MCP server,
with CLI equivalents `capture` and `read-capture`. It runs one fully qualified
pytest node in the configured interpreter, retaining diagnostics and a bounded
history of local-value changes. It does not edit the application or use a model.

```python
capture_failure(failing_test="tests/test_app.py::test_bug")
# Response includes capture_id, failure signature, failing frame and changes.
read_capture(capture_id="C...", section="report")
read_capture(capture_id="C...", section="trace", variable="current_selector")
# Continue a page with its next_cursor; keep the same section/variable.
```

```sh
PYTHONPATH=src .venv/bin/python -m faultline.cli capture \
  --repo /absolute/project --python /absolute/project/.venv/bin/python \
  'tests/test_app.py::test_bug'
PYTHONPATH=src .venv/bin/python -m faultline.cli read-capture \
  --repo /absolute/project --python /absolute/project/.venv/bin/python \
  C... --section trace --variable value
```

A parameterized test must include its parameter ID. Selecting several tests
aborts before executing their test bodies. Setup/collection errors, skips, xfail,
timeouts and changed workspaces are not reported as a verified passing run.
Capture supports setup/teardown reports, but traces the call phase only.

## What the evidence means

A change records the frame number, function, variable, before/after snapshots,
last executed line (`after_line`) and line where the change became observable
(`observed_line`). An initial binding has no `after_line`. Line tracing observes
state at boundaries: a call, nested mutation or multi-statement line can occur
between observations. This is not instruction-level assignment attribution.

For a None-bearing failing frame, the summary prioritizes recent observed None
introductions and container changes in the same source file. These are explicitly
`none_origin_candidates`, not proven dataflow edges or a causal diagnosis. An
unrelated None transition can appear. Passing `variable` to capture prioritizes
that name in each frame's snapshot; this changes the capture request and may
rerun the test. Filtering `read_capture(..., variable=...)` never reruns it.

For other failures, the summary shows recent failing-frame changes; focus a
variable when necessary. Cross-file producer chains, object-field histories,
identity tracking, automatic passing-run alignment and general backward slicing
are not implemented. The complete retained trace can expose more than the summary.

Snapshots use the existing exact-built-in-type snapshotter. User repr, equality,
properties and iteration methods are not invoked by the tracer. Sensitive names
and recognized token formats are redacted in value snapshots. Opaque objects and
truncated containers can hide changes. **Raw stdout/stderr and pytest-rendered
reports can contain sensitive application data or source literals.** They remain
in protected local files; raw sections are sent to the agent only when requested.

## Reuse and freshness

An identical request reuses a completed capture for up to ten minutes when full
workspace/interpreter/dependency/declared-input fingerprints match. It is labeled
`reused=true`: that is a previous observation, not another test pass. Source,
test, configuration and declared-environment changes invalidate reuse. Partial
fingerprints and changes during execution disable reuse. Use `refresh=true`
after external state changes or when checking flakiness. Untracked environment,
services, clocks and randomness cannot be validated by a source fingerprint.

Reading an old capture never reruns tests. Its page says `unchanged`, `stale` or
`unknown` for the tracked workspace; `unchanged` does not guarantee current
external state. Fix the application in the main agent, then capture again to
verify the original test and run the appropriate broader regression suite.
Capture IDs are separate from investigation IDs used by `check_patch`.

## Resource limits

- At most 400 recent change events; at most 16 local names per frame and 256
  active frames. The response reports truncation and omitted changes.
- Main-thread call-phase tracing only. Generator/coroutine frames are skipped.
  Subprocess/thread execution and setup provenance are not traced.
- Trace callback accounting stops at 100,000 callbacks or approximately one
  second of callback CPU time. The supervised pytest process has its own timeout.
- Up to 4 MiB retained per stdout/stderr stream (tail if exceeded), 64 KiB per
  failure report and bounded structured frames. This is complete retained output
  only within those caps, not an unlimited recording.
- Captures live outside the target repo, directories mode 0700 and files 0600.
  New capture requests prune old runs to at most 32 stored captures and one day.
  Reuse index expiry is ten minutes. Expired artifacts may be unavailable.
- Responses/pages default to 1,200 estimated tokens; budgets are 600–8,000. MCP
  budgeting includes its serialized result envelope. UTF-8 bytes/3 is an estimate,
  not a provider token count. Reading pages does not execute tests, but freshness
  checks inspect installed-package metadata with the configured interpreter.

## Verification and interpretation

Automated checks cover local None/wrong-value transitions, producer/consumer
candidates, safe snapshots, reuse without another pytest process, edits and
partial fingerprints, retained-output pagination, permissions, timeout,
collection/multiple-test handling, and MCP wire budgets.

The known youtube-dl development case was also run without supplying a variable.
The summary recovered the line-961 None transition and the selector-list change
before the line-994 crash. This case informed development, so it is not a blind
held-out result, a complete causal proof or a measured agent-token saving.
A new paid Claude repair benchmark has not been run. The harness now labels new
H runs `v8-capture-hook` and C/D runs `v8-capture-optional`; historical records are
unchanged. Capture reuse saves test executions by construction; whether the agent
uses it and saves total tokens must be measured in fresh complete repair trials.

Pytest hook behavior was checked against the official API/reference and the
installed pytest 9.1.1; trace behavior against Python's sys.settrace documentation
and Python 3.12.14. MCP behavior uses the existing SDK 2.3.0 adapter with a new
real-stdio protocol test (not a live coding-agent session).

The pre-existing v7 small-repository and test-frame silence rules are preserved.
New tools and skill guidance add discovery overhead, so v6/v7 token results do
not establish savings for this new capture treatment. Known-case development
record: eval/results/capture-v1-e8-development-02.json (1.2329 s capture, 0.0635 s
reuse, 2,721-byte CLI summary; no variable supplied to capture).
