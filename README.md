# Faultline

**Automatic failing-test context for AI coding agents: fix the same bugs with ~29% fewer tokens.**

When a test fails, coding agents burn turns rerunning noisy test output and
hunting through files for the crash. Every turn re-reads the whole conversation,
so each wasted turn costs tens of thousands of tokens. Faultline watches for the
failure and **hands the agent exactly what it needs at that moment**:
- a clean test command;
- the crash-site code;
- the line where the bad value was created.

It stays silent when it can't help. Faultline never edits your code.

| | |
|---|---|
| **Works with** | Claude Code (automatic hooks) · any MCP client · open-weight models (**Gemma 4** via the Gemini API, or fully local via llama.cpp) |
| **Measured** | **29.3% fewer tokens** across 42 real Claude Code sessions on a large real-world bug, with every fix verified by tests |
| **Setup** | One install command plus one command per project |
| **Language** | Python + pytest (v0.0.1, research prototype) |

---

## Features

### 1. Automatic hooks for Claude Code (the part that saves tokens)
Installed with one command; no tool calls needed.
- **Clean reproduction.** When you ask to fix a failing test, Faultline suggests
  a compact pytest command (short traceback, no warning flood), so the agent
  doesn't rerun tests to see past noise.
- **Crash-site code.** When a test run fails, Faultline reads the deepest
  traceback frame in *your application code* and injects those exact lines.
- **Cause candidate.** On large repos it reruns the failing test once with a
  safe tracer and shows where a `None` was *introduced* upstream. In our real
  bug: `current_selector = None` at line 961, before the crash at line 994.
  This is labelled a candidate, never proof.
- **Silence rules.** No injection on small repos (≤ 64 KiB of source; agents
  read those whole) or when a test fails on its own `assert`. This keeps the
  overhead about neutral where it can't help.

### 2. Open-model debugging agent (Gemma 4: API or local)
`faultline agent` turns an open-weight model into a bug-fixer that gets the
same Faultline context.
- **Gemini API:** `gemma-4-26b-a4b-it` / `gemma-4-31b-it`. No download needed.
- **Fully local:** llama.cpp, for example Gemma 4 12B. Private and free; code
  never leaves your machine.
- **Safe tools:** list, search, read, edit non-test files, run pytest. They are
  confined to the repository, with no arbitrary shell.
- `--faultline on|off` gives a built-in A/B comparison.

### 3. MCP tools (optional, for any MCP client)
- `capture_failure` / `read_capture`: run a failing test **once** and keep a
  bounded history of how values changed; read it page by page without
  rerunning.
- `search_code`: bounded source retrieval (keywords plus static import/call
  links) instead of reading whole files.
- `investigate_failure` / `expand_evidence`: spectrum-based fault localization
  (target-focused Ochiai) plus safe runtime value snapshots.
- `check_patch`: rerun tests after a fix (full suite by default).

### 4. A reproducible evaluation harness
- A/B trials with fresh checkouts and **hidden tests** the agent never sees.
- An independent judge, event-log leak audits, and per-session records.
- One-command CSV export of every session ([`eval/export/`](eval/export/)).

---

## Setup

**Requirements:** Python ≥ 3.12, macOS or Linux. The project you debug needs
`pytest` and `coverage` in its environment.

```bash
uv tool install "faultline[mcp] @ git+https://github.com/dingdongkkk/faultline"
```

`pipx install "faultline[mcp] @ git+https://github.com/dingdongkkk/faultline"` also works.

### Claude Code: automatic mode (recommended)
```bash
faultline install-claude --repo /path/to/your/project
```
Open a new Claude Code session in that project and ask it to fix a failing
test. Faultline fires automatically. To also expose the MCP tools:
```bash
claude mcp add faultline -- faultline serve --repo /path/to/your/project --python /path/to/your/project/.venv/bin/python
```

### Open model: Gemma 4 through the Gemini API
Create a key in [Google AI Studio](https://aistudio.google.com), then store it
privately (either option works):
```bash
export GEMINI_API_KEY=your-key
```
```bash
mkdir -p ~/.config/faultline && read -rs KEY && printf %s "$KEY" > ~/.config/faultline/gemini_api_key && chmod 600 ~/.config/faultline/gemini_api_key
```
Run the agent:
```bash
faultline agent "tests/test_app.py::test_bug" --repo /path/to/project --python /path/to/project/.venv/bin/python --provider gemini --model gemma-4-26b-a4b-it
```
The gemini provider sends code excerpts and test output to Google; it prints
this notice when it starts.

### Open model: fully local (llama.cpp)
```bash
brew install llama.cpp
```
```bash
llama-server -m gemma-4-12b-it-qat-q4_0.gguf --host 127.0.0.1 --port 8089 -c 16384 --jinja
```
```bash
faultline agent "tests/test_app.py::test_bug" --repo /path/to/project --python /path/to/project/.venv/bin/python --provider local
```
The official Gemma 4 12B QAT GGUF is 6.98 GB (`google/gemma-4-12B-it-qat-q4_0-gguf`, Apache-2.0).

---

## Results

Main agent: **Claude Code**, with every fix judged by tests it never saw.

### Large real-world bug: ~29% fewer tokens
The case is youtube-dl (586 files, 67k lines), real bug
[BugsInPy](https://github.com/soarsmu/BugsInPy) #8. We compared **A: Claude
Code alone** with **H: Claude Code + Faultline hooks**, across 4 independent
batches and 2 models:

| Main agent | A: tokens per session (avg) | H: with Faultline (avg) | **Saved** | Sessions |
|---|---|---|---|---|
| Claude Opus 5.5 | 219,559 | 160,547 | **26.9%** | 9 vs 9 |
| Claude Sonnet 5.5 | 335,567 | 233,311 | **30.5%** | 12 vs 12 |
| **Both** | 285,849 | 202,127 | **29.3%** | 21 vs 21 |

- **All 42 fixes were correct.** Tokens are input + cache tokens per session,
  as reported by Claude Code.
- **Per batch (averages), the saving was always positive:** 26%–39% for
  Sonnet (4 batches), 22%–36% for Opus (3 batches).
- **Why it works:** sessions dropped from 6–11 turns to 5–8, because the agent
  got a clean traceback on the first run and the crash-site code arrived
  automatically.

### Small repositories: neutral by design
On small injected-bug projects, early versions *cost* tokens (+25% to +77%),
because agents just read the whole repo. The silence rules fixed this:
- 0 bytes injected in 6 of 6 sessions;
- the only remaining cost is about 500 tokens of setup.

### What we learned (and what didn't work)
- **Optional tools go unused.** Claude called Faultline's MCP tools **0 times
  in 26 sessions** where they were offered. Automatic delivery is what works,
  which shaped the design.
- **Keyword search on the prompt saved nothing** (v5, before the crash-site
  design).
- **A small local model (Qwen3-4B) could not fix the large bug,** with or
  without Faultline.
- **Gemma 4 agent results are pending** and will be added here.

**100 real sessions recorded** in total. See the full report in
[docs/EVALUATION.md](docs/EVALUATION.md) and the raw data in
[eval/export/](eval/export/).

---

## Why it matters (judging criteria)

**Usability: a real, measured problem.**
- **Who it's for:** developers who let AI agents fix failing tests, and pay
  per token or hit usage limits.
- **The problem:** each extra turn re-reads the whole context. We measured the
  waste (repeated noisy test runs, file hunting) and cut it.
- **Low friction:** one command to turn on. AI is used only where it removes
  work; the hooks themselves need no model.

**Creativity: delivery at the right moment, not one more tool.**
- **Not another optional tool:** most code-search and debugger MCPs (Serena,
  Claude Context, debugger MCPs) wait for the agent to call them. Our data
  shows agents usually don't.
- **Event-driven instead:** Faultline reacts to the failure itself, combining
  the traceback, an automatic value-history capture (where did this `None`
  come from?) and silence rules.
- **Open models get the same context,** so the approach isn't tied to one
  vendor.

**Scalability: built for big codebases.**
- **Proven at scale:** tested on a 586-file, 67k-line real project. The capture
  takes about 1.2 s (0.08 s when reused); source scans and outputs are bounded
  and budgeted.
- **Gets more useful as repos grow:** the larger the codebase, the more hunting
  it removes, and on tiny repos it switches itself off.
- **Path to growth:** more languages (it only needs a traceback parser per
  test runner), CI failure triage, and more real-bug benchmarks.

**Adaptability: fits existing workflows.**
- **Works with what you use:** standard MCP over stdio for any MCP client,
  Claude Code hooks and skill, a CLI, and an agent with pluggable model
  providers (local llama.cpp or Gemini).
- **Configurable:** `FAULTLINE_SMALL_REPO_BYTES`, `--faultline on|off`,
  `--provider`, `--model`, and budgets on every tool.
- **Clear interfaces:** typed JSON contracts with published schemas
  ([`schemas/`](schemas/)), 164 automated tests, and Apache-2.0.

---

## Limitations
- **One large real bug so far:** the ~29% comes from one case. More real-bug
  benchmarks are the next step.
- **Python and pytest only;** tracing covers the main thread and the test
  body.
- **Cause candidates are hints, not proof.** They help most when the cause is
  far from the crash.
- **Not a sandbox:** tests run with your permissions. See
  [docs/SECURITY.md](docs/SECURITY.md).

## Repository layout
```
src/faultline/        engine, hooks (claude.py), agent (agent.py), MCP server, CLI
src/faultline/_probe/ pytest plugins that run inside the target project
eval/                 harness, case definitions, per-session results, CSV export
docs/                 evaluation report, architecture, security, prior art
tests/                164 automated tests
```

## License
Apache-2.0. Third-party and model attribution:
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Prior art:
[docs/PRIOR_ART.md](docs/PRIOR_ART.md).
