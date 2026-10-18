"""MCP stdio adapter (optional dependency ``mcp``; verified against mcp 2.3.0).

Adapter only: argument plumbing, error mapping, transport. Each tool returns
a ``CallToolResult`` with exactly one text block holding the compact JSON
response that the engine budgeted. The SDK passes a returned
``CallToolResult`` through unchanged, so no second structured copy doubles
what the client receives.

Engine errors from bad arguments are raised as ``ToolError``, so the
calling model sees an ``is_error`` result rather than a protocol error.
Tool handlers are synchronous; the SDK runs them in a worker thread.
"""

from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

from . import __version__
from .contracts import FaultlineConfig
from .evidence import EvidenceStore, expand
from .orchestrator import investigate
from .patch import check_patch
from .search import search_code as retrieve_code

# Kept short on purpose: server instructions and upfront tool descriptions are
# re-sent to the model on every turn of the agent's session.
INSTRUCTIONS = "Search Python code with bounded source context; investigate pytest failures when runtime evidence is needed."


DEFAULT_INVESTIGATE_BUDGET = 1200  # tokens (estimate); was 2000 before the token-saving pass


def _result(model) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=model.model_dump_json(exclude_none=True))])


def build_server(cfg: FaultlineConfig, force_planner: str | None = None) -> MCPServer:
    """``force_planner`` pins the planner regardless of the tool argument (used
    to hold an evaluation condition constant); responses report the planner used."""
    store = EvidenceStore(cfg)
    store.sweep()
    mcp = MCPServer("faultline", version=__version__, instructions=INSTRUCTIONS)

    def measure_result(text):
        result = CallToolResult(content=[TextContent(type="text", text=text)],
                                _meta={"io.modelcontextprotocol/serverInfo":
                                       {"name": "faultline", "version": __version__}})
        return len(result.model_dump_json(by_alias=True, exclude_none=True).encode())

    @mcp.tool(structured_output=False)
    def capture_failure(failing_test: str, variable: str | None = None, refresh: bool = False,
                        budget_tokens: int = 1200, timeout_seconds: int = 60) -> CallToolResult:
        """Run one pytest test and retain output plus bounded local-value history. Reuses an unchanged capture for 10 minutes; refresh forces a new run. Changes are observations, not causal proof."""
        from .capture import capture_failure as capture
        try:
            return _result(capture(cfg, failing_test, budget_tokens, timeout_seconds,
                                   variable, refresh, measure_result))
        except (ValueError, OSError) as e:
            raise ToolError(f"capture_error: {e}") from e

    @mcp.tool(structured_output=False)
    def read_capture(capture_id: str, section: Literal["trace", "report", "stdout", "stderr"] = "trace",
                     cursor: int = 0, budget_tokens: int = 1200, variable: str | None = None) -> CallToolResult:
        """Read a stored capture without rerunning pytest. Pages report workspace freshness; use next_cursor for more. Raw test output can contain sensitive data."""
        from .capture import read_capture as read
        try:
            return _result(read(cfg, capture_id, section, cursor, budget_tokens, measure_result, variable))
        except (ValueError, OSError) as e:
            raise ToolError(f"capture_error: {e}") from e

    # No forced upfront schemas: v3 trials paid overhead even without using tools.
    @mcp.tool(structured_output=False)
    def search_code(query: str, failing_test: str | None = None, budget_tokens: int = 1200,
                    seen_ids: list[str] | None = None) -> CallToolResult:
        """Find Python definitions and related code without running tests. Returns ranked source excerpts, not just paths. Use path.py:LINE for a traceback location (reads only that file). Supply a test node ID to follow static dependencies; pass returned IDs in seen_ids to skip unchanged excerpts."""
        try:
            def measure(text):
                # SDK 2.3 injects serverInfo into the delivered result.
                result = CallToolResult(content=[TextContent(type="text", text=text)],
                                        _meta={"io.modelcontextprotocol/serverInfo":
                                               {"name": "faultline", "version": __version__}})
                return len(result.model_dump_json(by_alias=True, exclude_none=True).encode())
            return _result(retrieve_code(cfg, query, failing_test, budget_tokens, seen_ids, measure))
        except (ValueError, KeyError) as e:
            raise ToolError(f"invalid_argument: {e}") from e

    @mcp.tool(structured_output=False)
    def investigate_failure(
        failing_test: str,
        budget_tokens: int = DEFAULT_INVESTIGATE_BUDGET,
        max_rounds: int = 3,
        timeout_seconds: int = 120,
        planner: Literal["deterministic", "local-model"] = "deterministic",
    ) -> CallToolResult:
        """Find suspect lines for a failing pytest test (node ID) and measure their values vs a passing test.

        Use when the cause is not obvious from the failure. Returns ranked suspects (ties marked), a code
        excerpt and differing values. Hints, not proof. Does not edit code."""
        try:
            return _result(investigate(cfg, store, failing_test, budget_tokens, max_rounds, timeout_seconds,
                                       force_planner or planner))
        except (ValueError, KeyError) as e:
            raise ToolError(f"invalid_argument: {e}") from e

    @mcp.tool(structured_output=False)
    def expand_evidence(investigation_id: str, evidence_id: str, budget_tokens: int = 1000,
                        cursor: str | None = None) -> CallToolResult:
        """Fetch an omitted evidence item by ID (no rerun). Labels stale/expired data; pass next_cursor for more."""
        try:
            return _result(expand(cfg, store, investigation_id, evidence_id, budget_tokens, cursor))
        except (ValueError, KeyError) as e:
            raise ToolError(f"invalid_argument: {e}") from e

    @mcp.tool(name="check_patch", structured_output=False)  # Python name avoids shadowing the engine
    def check_patch_tool(investigation_id: str, mode: Literal["full", "affected"] = "full",
                         timeout_seconds: int = 120, budget_tokens: int = 1500) -> CallToolResult:
        """Rerun tests on the current checkout after your fix. mode=full (default) runs the whole suite."""
        try:
            return _result(check_patch(cfg, store, investigation_id, mode, timeout_seconds, budget_tokens))
        except (ValueError, KeyError) as e:
            raise ToolError(f"invalid_argument: {e}") from e

    return mcp


def serve(cfg: FaultlineConfig, force_planner: str | None = None) -> None:
    build_server(cfg, force_planner).run(transport="stdio")
