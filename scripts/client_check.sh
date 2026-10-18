#!/usr/bin/env bash
# M7 real-client check: one headless Claude Code session against a fresh copy of
# the demo fixture, using only Faultline's MCP tools plus Read/Edit.
# Requires: `claude` CLI logged in (run `claude` then `/login` yourself first).
# Does not modify your persistent MCP configuration (--strict-mcp-config).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
W="${1:-$(mktemp -d -t faultline-client-check)}"
rm -rf "$W/shop" && mkdir -p "$W" && cp -R "$ROOT/tests/fixtures/shop" "$W/shop"
cat > "$W/mcp.json" <<JSON
{"mcpServers": {"faultline": {"command": "$ROOT/.venv/bin/python",
  "args": ["-m", "faultline.cli", "serve", "--repo", "$W/shop", "--python", "$ROOT/.venv/bin/python",
           "--state-dir", "$W/state"],
  "env": {"PYTHONPATH": "$ROOT/src"}}}}
JSON
cd "$W/shop"
claude -p "The test tests/test_cart.py::test_bulk_threshold[10-1000] fails in this repository. Use the faultline MCP tools: call investigate_failure for that test, use the returned evidence, fix the bug in the application code (do not edit tests), then call check_patch for the investigation and report its status and full_regression_verified. Keep your final answer brief." \
  --strict-mcp-config --mcp-config "$W/mcp.json" \
  --allowedTools "mcp__faultline__investigate_failure" "mcp__faultline__expand_evidence" "mcp__faultline__check_patch" "Read" "Edit" \
  --output-format json < /dev/null > "$W/result.json"
echo "workdir: $W"
echo "--- diff of application code:"
diff "$ROOT/tests/fixtures/shop/shop/cart.py" "$W/shop/shop/cart.py" || true
diff -r "$ROOT/tests/fixtures/shop/tests" "$W/shop/tests" >/dev/null && echo "tests unchanged"
echo "--- independent full test run (not via Faultline):"
"$ROOT/.venv/bin/python" -m pytest -q -p no:cacheprovider "$W/shop" | tail -1
"$ROOT/.venv/bin/python" -c "import json,sys; d=json.load(open('$W/result.json')); print({k:d.get(k) for k in ('is_error','num_turns','duration_ms')}); print(d.get('result'))"
