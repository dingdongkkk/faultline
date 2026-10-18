"""M7 protocol smoke tests: the real `faultline serve` process over stdio,
driven by the MCP SDK's own Client. This verifies the protocol path; it is
not a real-client (agent) verification."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")
from mcp import Client, StdioServerParameters  # noqa: E402

from faultline.contracts import CheckPatchResponse, ExpandResponse, InvestigateResponse, SearchResponse  # noqa: E402

SRC = str(Path(__file__).resolve().parent.parent / "src")
TARGET = "tests/test_cart.py::test_bulk_threshold[10-1000]"


def _server(cfg):
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "faultline.cli", "serve", "--repo", cfg.repo_root, "--python", cfg.python,
              "--state-dir", cfg.state_dir],
        env={"PYTHONPATH": SRC},
    )


def _text(result):
    assert len(result.content) == 1 and result.content[0].type == "text"
    assert result.structured_content is None  # no second copy of the payload
    return result.content[0].text


def test_tools_listed_with_contract_arguments(make_project):
    cfg = make_project("shop")

    async def go():
        async with Client(_server(cfg)) as client:
            return await client.list_tools()

    tools = {t.name: t for t in asyncio.run(go()).tools}
    assert set(tools) == {"search_code", "investigate_failure", "expand_evidence", "check_patch", "capture_failure", "read_capture"}
    inv = tools["investigate_failure"].input_schema["properties"]
    assert inv["budget_tokens"]["default"] == 1200 and inv["max_rounds"]["default"] == 3
    assert inv["timeout_seconds"]["default"] == 120
    assert set(inv["planner"]["enum"]) == {"deterministic", "local-model"} and inv["planner"]["default"] == "deterministic"
    cp = tools["check_patch"].input_schema["properties"]
    assert cp["mode"]["default"] == "full" and set(cp["mode"]["enum"]) == {"full", "affected"}
    assert tools["expand_evidence"].input_schema["required"] == ["investigation_id", "evidence_id"]
    # No forced schema overhead for clients that support tool deferral.
    assert all(not (t.meta or {}).get("anthropic/alwaysLoad") for t in tools.values())
    assert all(len(t.description) < 300 for t in tools.values())


def test_search_wire_budget_and_seen_context_over_stdio(make_project):
    cfg = make_project("shop")

    async def go():
        async with Client(_server(cfg)) as client:
            first = await client.call_tool("search_code", {"query": "bulk threshold", "budget_tokens": 800})
            payload = SearchResponse.model_validate_json(_text(first))
            second = await client.call_tool("search_code", {"query": "bulk threshold", "budget_tokens": 800,
                                                           "seen_ids": [h.id for h in payload.hits]})
            return first, payload, SearchResponse.model_validate_json(_text(second))

    first, payload, second = asyncio.run(go())
    assert not first.is_error and payload.hits
    wire = len(first.model_dump_json(by_alias=True, exclude_none=True).encode())
    assert wire == payload.response_bytes <= 2400
    assert payload.budget_scope == "mcp_result"
    assert {h.id for h in payload.hits}.isdisjoint(h.id for h in second.hits)


def test_full_tool_flow_over_stdio(make_project):
    cfg = make_project("shop")
    cart = Path(cfg.repo_root, "shop", "cart.py")

    async def go():
        async with Client(_server(cfg)) as client:
            r1 = await client.call_tool("investigate_failure", {"failing_test": TARGET})
            inv = InvestigateResponse.model_validate_json(_text(r1))
            r2 = await client.call_tool("expand_evidence", {"investigation_id": inv.investigation_id,
                                                            "evidence_id": inv.comparisons[0].evidence_id,
                                                            "budget_tokens": 4000})
            cart.write_text(cart.read_text().replace("if qty >= threshold:", "if qty > threshold:"))
            r3 = await client.call_tool("check_patch", {"investigation_id": inv.investigation_id})
            bad = await client.call_tool("investigate_failure", {"failing_test": TARGET, "budget_tokens": 100})
            return r1, inv, r2, r3, bad

    r1, inv, r2, r3, bad = asyncio.run(go())
    text = _text(r1)
    assert not r1.is_error and inv.status.value == "completed"
    # The budgeted payload is exactly what the client receives as content.
    assert inv.metrics.response_bytes == len(text.encode()) <= 1200 * 3
    wire = len(r1.model_dump_json(by_alias=True, exclude_none=True).encode())
    print(f"\ncontent bytes={len(text.encode())} CallToolResult JSON bytes={wire}")
    assert wire - len(text.encode()) < len(text.encode()) * 0.25  # envelope + string escaping only
    exp = ExpandResponse.model_validate_json(_text(r2))
    assert exp.freshness.value == "fresh" and exp.content["evidence_id"] == inv.comparisons[0].evidence_id
    chk = CheckPatchResponse.model_validate_json(_text(r3))
    assert chk.effective_scope.value == "full" and chk.status == "passed" and chk.full_regression_verified
    assert bad.is_error and "invalid_argument" in bad.content[0].text


def test_unknown_investigation_is_tool_error(make_project):
    cfg = make_project("shop")

    async def go():
        async with Client(_server(cfg)) as client:
            return await client.call_tool("expand_evidence", {"investigation_id": "inv_nope", "evidence_id": "O1"})

    r = asyncio.run(go())
    assert r.is_error and "unknown investigation" in r.content[0].text


def test_capture_wire_budget_reuse_and_read_over_stdio(make_project):
    cfg = make_project('shop')

    async def go():
        async with Client(_server(cfg)) as client:
            r1 = await client.call_tool('capture_failure', {'failing_test': TARGET})
            payload = json.loads(_text(r1))
            r2 = await client.call_tool('capture_failure', {'failing_test': TARGET})
            page = await client.call_tool('read_capture', {'capture_id': payload['capture_id'], 'section': 'report'})
            return r1, payload, json.loads(_text(r2)), page

    r1, payload, again, page = asyncio.run(go())
    assert not r1.is_error and payload['status'] == 'failed'
    assert payload['response_bytes'] == len(r1.model_dump_json(by_alias=True, exclude_none=True).encode()) <= 3600
    assert again['reused'] and again['capture_id'] == payload['capture_id']
    p = json.loads(_text(page))
    assert p['freshness'] == 'unchanged' and 'AssertionError' in p['text']
    assert p['response_bytes'] == len(page.model_dump_json(by_alias=True, exclude_none=True).encode()) <= 3600
