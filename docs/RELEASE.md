# Release preparation (nothing published)

Status as of 2026-10-18. Publishing, pushing, tagging or submitting requires
the maintainer's explicit instruction.

| Item | State |
|---|---|
| License | MIT (`LICENSE`); switched from Apache-2.0 on 2026-10-18 at the maintainer's request |
| Third-party / model attribution | `THIRD_PARTY_NOTICES.md`; direct dependency licenses checked from installed metadata |
| Wheel + sdist build | `uv build` OK; wheel installs into a clean venv, CLI runs, `_probe` package present, an investigation completes |
| sdist hygiene | no venv, caches, model weights or private evaluation files (checked by listing) |
| Tests | default suite passes; live-model and harness tests documented separately |
| Version | 0.0.1 (prototype) |
| Git repository | **not initialized** — needed before publishing |
| Project metadata | authors / URLs not set in `pyproject.toml` (maintainer to decide) |
| PyPI name availability | not checked |
| Security contact | placeholder in `docs/SECURITY.md` |
| Repair benchmark results | **pending** (harness ready; trials consume Claude usage and need approval) |

## Before publishing (checklist)
1. `git init`, review `.gitignore`, first commit.
2. Fill `pyproject.toml` authors/urls; choose a public security contact.
3. Re-run `.venv/bin/python -m pytest -q`, `scripts/export_schemas.py`,
   `scripts/build_examples.py`; confirm no diff.
4. Re-verify MCP SDK and llama.cpp versions if upgraded.
5. Decide whether to include evaluation results; never include hidden tests
   or the private manifest.
6. Build with `uv build`; inspect artifacts; publish only on instruction.
