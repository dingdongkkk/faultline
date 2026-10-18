# Instructions for coding agents working on Faultline

Ownership: Claude Code is the usual implementation owner. On 2026-10-18 the
user explicitly authorized Codex to redesign and implement search/token
optimization. That authorization includes code, contracts, tests and docs.
Coordinate through BUILD_STATUS.md; avoid simultaneous edits by two tools.
Do not launch sub-agents or assume paid API credits.

## Ground rules
- Never claim verification that was not performed. Update `BUILD_STATUS.md`
  in the same change as the work it describes, using its six levels.
- Mocks never establish live-model, MCP-client or repair-benchmark status.
- Faultline never edits the target application. `check_patch` checks the
  current checkout; it does not apply edits.
- Verify changing third-party APIs (MCP SDK, coverage.py, llama.cpp, model
  cards) against primary documentation and record the version checked.
- Do not download models, push, publish or submit anything without the
  user's explicit instruction.
- No unmeasured claims of token savings or novelty for SBFL / runtime
  inspection / debugger MCPs or their combination. State retrieval-byte
  reductions separately from measured main-agent token savings.

## Code conventions
- Python ≥ 3.12, standard library first; pydantic for contracts only.
- `src/faultline/_probe/` runs inside the *target* interpreter: stdlib,
  pytest and coverage only; no pydantic.
- Contracts live in `src/faultline/contracts.py`. After changing them run
  `scripts/export_schemas.py` and `scripts/build_examples.py`.
- Nullable fields must default to `None` (compact serialization round-trip;
  enforced by a test).
- Ordering/ties come from integer counts, never from display floats.

## Commands
```
uv venv -p python3.12 .venv && uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python scripts/export_schemas.py
PYTHONPATH=src .venv/bin/python scripts/build_examples.py
# live model (after the approved download):
llama-server -m ~/.cache/faultline-models/qwen3-4b-bc64014/Qwen3-4B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 8089 -c 4096 -np 1 --no-webui --reasoning off --jinja
FAULTLINE_MODEL_ENDPOINT=http://127.0.0.1:8089 .venv/bin/python -m pytest -q tests/test_live_model.py
.venv/bin/python scripts/live_gate.py http://127.0.0.1:8089
```

## Test tiers (keep separate; markers in pyproject)
1. Unit/fixture tests (default run).
2. Protocol smoke tests (in-process MCP; not client verification).
3. `live_model` — needs a running local llama-server.
4. `mcp_client` — a real MCP client session.
5. Repair benchmarks — manual protocol in `docs/EVALUATION.md`.
