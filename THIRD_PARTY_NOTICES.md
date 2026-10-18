# Third-party software and model attribution

Faultline's own code is licensed under Apache-2.0 (`LICENSE`). The
components below are separate works under their own licenses; they are not
vendored. Licenses below were read from installed package metadata on
2026-10-18 (pydantic 2.14.1, mcp 2.3.0, pytest 9.1.1, coverage 7.16.2).

## Runtime dependencies
| Component | Use | License (to verify at release) |
|---|---|---|
| pydantic (+ pydantic-core) | contracts/validation | MIT |
| mcp (Python SDK) 2.3.0 | optional MCP adapter | MIT |
| pytest | target test runner (in target env) | MIT |
| coverage.py | per-test coverage (in target env) | Apache-2.0 |

The `mcp` extra pulls transitive dependencies including anyio (MIT),
starlette, uvicorn and sse-starlette (BSD-3-Clause), python-multipart
(Apache-2.0) and jsonschema (MIT). Generate a complete transitive license
report at release time.

## Local inference (not bundled)
| Component | Use | License |
|---|---|---|
| llama.cpp (`llama-server`), Homebrew 0.7.0, build b11669 (commit 620d2225c) | local inference runtime | MIT (Homebrew formula metadata) |
| Qwen3-4B GGUF Q4_K_M: `Qwen/Qwen3-4B-GGUF@bc640142c66e1fdd12af0bd68f40445458f3869b`, `Qwen3-4B-Q4_K_M.gguf`, 2,497,280,256 bytes, sha256 `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` | planner model, downloaded 2026-10-18 to `~/.cache/faultline-models/` (outside the repo) | Apache-2.0 per model card metadata |

Model weights are downloaded by the user and never committed to or
redistributed by this repository.
