# Faultline

**An MCP server that helps AI coding agents fix failing Python tests with fewer tokens.**

![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![Tests: 166 passing](https://img.shields.io/badge/tests-167%20passing-brightgreen)
![MCP](https://img.shields.io/badge/MCP-stdio-purple)

When a test fails, coding agents waste turns rerunning noisy output and hunting
through files. Every turn re-reads the whole conversation, so each wasted turn
costs tens of thousands of tokens. **Faultline hands the agent exactly what it
needs the moment a test fails** (a clean test command, the crash-site code, and
the line where the bad value was created) and stays silent when it can't help.

## Highlights

### 1. Saved 29.3% of tokens on Claude Code
On a real bug in a large codebase (youtube-dl: 586 files, 67k lines), Claude
Code with Faultline used **29.3% fewer tokens** than Claude Code alone. All 42
fixes were verified by tests.

| Claude model | Without Faultline | With Faultline | **Saved** | Sessions |
|---|---|---|---|---|
| Opus 5.5 | 219,559 tokens | 160,547 tokens | **26.9%** | 9 vs 9 |
| Sonnet 5.5 | 335,567 tokens | 233,311 tokens | **30.5%** | 12 vs 12 |
| **Both** | 285,849 tokens | 202,127 tokens | **29.3%** | 21 vs 21 |

### 2. Works with any open-source model through MCP
Faultline is a standard **MCP server**, so any MCP-compatible agent can use it.
It also ships an **open-model debugging agent** that receives Faultline's
context over MCP:
- **Offline:** any model [llama.cpp](https://github.com/ggml-org/llama.cpp)
  can run (Gemma, Qwen, Llama). Private, with no API cost.
- **API:** Gemma 4 through the Gemini API.

Tested end to end with **Gemma 4 12B running offline on a laptop**: Faultline
pointed it straight at the bug's real root cause.

---

## Quick start (3 steps)

```bash
uv tool install "faultline[mcp] @ git+https://github.com/dingdongkkk/faultline"
```
```bash
faultline install-claude --repo /path/to/your/project
```
Step 3: open Claude Code in that project and say *"fix the failing test"*.
Faultline now works automatically.

> No `uv`? Use `pipx install "faultline[mcp] @ git+https://github.com/dingdongkkk/faultline"`.
> Requirements: Python 3.12+, macOS or Linux, and `pytest` + `coverage` in your
> project's environment.

## Try it in 60 seconds (bundled example bug)

```bash
git clone https://github.com/dingdongkkk/faultline && cd faultline
```
```bash
uv venv -p 3.12 && uv pip install -e ".[mcp,dev]"
```
```bash
.venv/bin/faultline investigate --repo tests/fixtures/shop --python .venv/bin/python "tests/test_cart.py::test_bulk_threshold[10-1000]"
```
You'll get a compact JSON report:
- the suspect lines ranked, with ties shown honestly;
- the measured values of a failing vs a passing run (`qty` 10 vs 12);
- the source excerpt to fix.

---

## All features

### Automatic help for Claude Code (no tool calls needed)
- **One-command install.** `faultline install-claude` adds hooks and a skill
  to a project and keeps your existing settings.
- **Clean reproduction.** It suggests a compact pytest command (short
  traceback, no warning flood) so the agent doesn't rerun tests to see past
  noise.
- **Crash-site injection.** After a failing test, it injects the code at the
  deepest traceback frame in *your* code, not the test.
- **Root-cause candidate.** It reruns the failing test once with a safe tracer
  and shows where a bad `None` was *created* upstream, not just where it
  crashed.
- **Silence rules.** No output on small repos or bare test assertions, so
  there's no overhead where it can't help.
- **Hard size caps.** Every injection is at most 2 KB.

### MCP server: 7 tools for any MCP client
| Tool | What it does |
|---|---|
| `failure_context` | Get Faultline's context for a task or failing test output |
| `capture_failure` | Run a failing test once and record how values changed |
| `read_capture` | Read that recording page by page, without rerunning |
| `search_code` | Bounded code search (keywords + import/call links) instead of whole files |
| `investigate_failure` | Rank suspect lines (spectrum-based fault localization) and measure runtime values |
| `expand_evidence` | Fetch more detail on any evidence item, labelled fresh or stale |
| `check_patch` | Rerun tests after a fix (full suite by default) |

### Open-model debugging agent
- **Two providers:** local llama.cpp (any GGUF model) or the Gemini API
  (Gemma 4). Switch with `--provider`.
- **Context over MCP:** the agent calls Faultline's MCP server like any
  client would.
- **Safe tools:** list, search, read, edit non-test files, and run pytest.
  Everything is confined to the repo, with no shell access.
- **Robust:** grammar-constrained JSON (local), thinking control (Gemma),
  automatic retries for rate limits and server errors, a repetition guard,
  and helpful path suggestions.
- **Built-in A/B:** `--faultline on|off`, with per-step traces and exact
  token counts.

### Debugging engine
- **One-run coverage.** Per-test, per-phase (setup / call / teardown)
  coverage plus outcomes from a single pytest run.
- **Exact suspect ranking.** Target-focused Ochiai scoring with exact ties.
  No float rounding decides the order.
- **Failure signatures.** Exception type, crash location and message digest,
  used to check that a failure really reproduces.
- **Order-dependence detection.** It reruns the failing test alone and flags
  failures that only happen inside the suite.
- **Safe runtime snapshots.** It never calls your objects' `repr` or
  properties, and it redacts secrets (tokens, keys, passwords).
- **Failing vs passing comparison.** It picks the most similar passing test
  and shows the values that differ.
- **Freshness tracking.** Content hashes of code, dependencies, interpreter
  and settings mark old evidence as stale after edits.
- **Token budgets.** Every response fits a budget you set, with clear handles
  for anything omitted.
- **Supervised execution.** Timeouts, process-group cleanup (no orphan
  processes), path confinement and validated pytest options.

### Evaluation toolkit
- **Rigorous A/B harness:** fresh checkouts, hidden tests kept outside the
  agent's reach, leak audits and an independent judge.
- **100+ real recorded sessions,** exported to CSV with one command
  (`eval/harness/export_data.py`).
- **A real-bug benchmark case** (BugsInPy youtube-dl #8) plus 7 injected-bug
  cases.

---

## Setup guide

### Claude Code (recommended)
```bash
faultline install-claude --repo /path/to/your/project
```
Optional: also expose the MCP tools to Claude Code.
```bash
claude mcp add faultline -- faultline serve --repo /path/to/your/project --python /path/to/your/project/.venv/bin/python
```

### Any other MCP client
Register this stdio command in your client's MCP settings:
```
faultline serve --repo /path/to/your/project --python /path/to/your/project/.venv/bin/python
```

### Open-source model, offline (llama.cpp)
```bash
brew install llama.cpp
```
```bash
llama-server -m your-model.gguf --host 127.0.0.1 --port 8089 -c 16384 --jinja
```
```bash
faultline agent "tests/test_app.py::test_bug" --repo /path/to/project --python /path/to/project/.venv/bin/python --provider local
```
We tested Google's official **Gemma 4 12B** GGUF (`google/gemma-4-12B-it-qat-q4_0-gguf`, 6.98 GB).

### Gemma 4 through the Gemini API
Get a key from [Google AI Studio](https://aistudio.google.com), then:
```bash
export GEMINI_API_KEY=your-key
```
```bash
faultline agent "tests/test_app.py::test_bug" --repo /path/to/project --python /path/to/project/.venv/bin/python --provider gemini --model gemma-4-26b-a4b-it
```
The API option sends code excerpts to Google; the offline option keeps
everything on your machine.

---

## Results

### Large real-world bug (Claude Code): 29.3% fewer tokens
The case is youtube-dl (586 files, 67k lines), real bug
[BugsInPy](https://github.com/soarsmu/BugsInPy) #8. We compared **A: Claude
Code alone** with **H: Claude Code + Faultline**, across 4 independent batches
and 2 models (table above):
- **All 42 fixes were correct.**
- **Every batch saved tokens:** 26%–39% for Sonnet, 22%–36% for Opus.
- **Why:** sessions dropped from 6–11 turns to 5–8, because the agent got a
  clean traceback on the first try and the crash-site code arrived
  automatically.

### Small repositories: neutral by design
Silence rules mean 0 bytes injected (6 of 6 sessions). The only cost is about
500 tokens of setup.

### Open-source model (Gemma 4 12B, offline, context over MCP)
| Gemma 4 12B | Where it went | Tokens | Fixed? |
|---|---|---|---|
| Without Faultline | The crash site (the symptom) | 88,292 | No |
| With Faultline | **The real root cause** (line 961) | 99,155 | No |

- **What Faultline did:** it steered the open model from the symptom to the
  true cause.
- **Why there's no fix:** the 12B model couldn't produce an exact-match edit
  within 30 steps.
- **Next step:** larger open models, or a more forgiving edit tool.

### Lessons that shaped the design
- **Automatic delivery is what works.** Agents called optional tools 0 times
  in 26 sessions, which is why Faultline injects context automatically
  instead of waiting to be called.
- **Silence matters.** Early versions cost +25% to +77% on small repos; the
  silence rules fixed that.

Full report: [docs/EVALUATION.md](docs/EVALUATION.md). Raw data:
[eval/export/](eval/export/).

---

## Why Faultline (judging criteria)

**Usability: a real problem, solved simply.**
- **Who it's for:** anyone using AI coding agents on Python projects who pays
  per token or hits usage limits.
- **Setup:** one install and one command, then it works by itself.
- **AI where it helps:** an AI model is used only where it adds value; the
  hooks themselves need none.

**Creativity: right context at the right moment.**
- **Event-driven, not another tool:** most code-search and debugger MCP tools
  wait to be called. Faultline reacts to the failure itself.
- **Three signals in one:** it combines the traceback, an automatic
  value-history capture (where did this `None` come from?) and silence rules.

**Scalability: built for big codebases.**
- **Proven at scale:** tested on a 67k-line real project. The capture takes
  about 1.2 s, and all output is bounded.
- **Better as repos grow:** larger repos mean more hunting saved, and it
  switches itself off on tiny ones.
- **Path to growth:** more languages (only a traceback parser per test runner
  is needed), CI triage, and more benchmarks.

**Adaptability: plugs into existing workflows.**
- **Every entry point:** standard MCP, Claude Code hooks and skill, a CLI,
  and an agent with pluggable model providers.
- **Clear interfaces:** typed JSON contracts with published
  [schemas](schemas/), 167 tests, and the MIT license.

---

## Limitations
- **One large real bug:** the 29.3% saving comes from one bug (21 runs per
  side). More real-bug benchmarks are next.
- **Python and pytest only.**
- **Hints, not proof:** cause candidates point to likely causes.
- **Not a sandbox:** tests run with your permissions. See
  [docs/SECURITY.md](docs/SECURITY.md).

## Repository layout
```
src/faultline/        engine, hooks (claude.py), agent (agent.py), MCP server, CLI
src/faultline/_probe/ pytest plugins that run inside the target project
eval/                 harness, cases, per-session results, CSV export
docs/                 evaluation report, architecture, security, prior art
tests/                167 automated tests
```

## License
[MIT](LICENSE). Third-party and model attribution:
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
