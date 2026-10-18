"""Open-model agent loop: scripted providers only (no network, no model).
Mocks here do not establish live provider behavior."""

import json
import sys

import pytest

from faultline import agent as ag


class Scripted:
    name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def model_id(self):
        return "scripted"

    def complete(self, system, messages, usage, timeout):
        self.seen.append(messages[-1]["content"])
        usage.add(100, 10)
        return self.replies.pop(0)


def act(tool, **args):
    return json.dumps({"tool": tool, "args": args})


@pytest.fixture
def proj(make_project):
    return make_project("shop")


TARGET = "tests/test_cart.py::test_bulk_threshold[10-1000]"


def test_parse_action_tolerates_prose_and_rejects_unknown_tools():
    assert ag.parse_action('Sure.\n{"tool": "read_file", "args": {"path": "a.py"}} done') == \
        {"tool": "read_file", "args": {"path": "a.py"}}
    assert ag.parse_action('{"tool": "rm_rf", "args": {}}') is None
    assert ag.parse_action("no json here") is None


def test_agent_fixes_bug_with_scripted_model(proj):
    p = Scripted([
        act("run_tests", target=TARGET),
        act("read_file", path="shop/cart.py", start=8, end=14),
        act("edit_file", path="shop/cart.py", old="if qty >= threshold:", new="if qty > threshold:"),
        act("run_tests", target=""),
        act("finish", summary="threshold is exclusive"),
    ])
    rec = ag.run_agent(proj.repo_root, sys.executable, TARGET, p, use_faultline=False)
    assert rec["status"] == "finished" and rec["edits"] == ["shop/cart.py"]
    assert rec["tool_calls"] == {"run_tests": 2, "read_file": 1, "edit_file": 1, "finish": 1}
    assert rec["usage"]["model_calls"] == 5 and rec["usage"]["total_tokens"] == 550
    assert "exit code 0" in p.seen[4]  # the suite passed before finish


def test_tools_are_confined_and_tests_are_read_only(proj):
    ws = ag.Workspace(__import__("pathlib").Path(proj.repo_root), sys.executable)
    with pytest.raises(Exception):
        ws.read_file("../../etc/passwd")
    assert ws.edit_file("tests/test_cart.py", "assert", "pass").startswith("refused: test files")
    assert ws.edit_file("shop/cart.py", "def", "def").startswith("refused: `old` must match exactly once")
    assert ws.run_tests("--version")[0].startswith("refused")


def test_invalid_replies_stop_the_loop(proj):
    rec = ag.run_agent(proj.repo_root, sys.executable, TARGET, Scripted(["nope"] * 5), use_faultline=False)
    assert rec["status"] == "invalid_replies" and rec["invalid_replies"] == 5


def test_faultline_context_reaches_the_model_only_when_on(make_project, monkeypatch):
    # The shop fixture is tiny, so disable the small-repo silence rule to exercise injection.
    monkeypatch.setenv("FAULTLINE_SMALL_REPO_BYTES", "0")
    cfg = make_project("shop")
    on = Scripted([act("run_tests", target=TARGET), act("finish", summary="x")])
    rec = ag.run_agent(cfg.repo_root, sys.executable, TARGET, on, use_faultline=True)
    assert rec["faultline_injections"] >= 1
    assert "Faultline" in on.seen[0]  # prompt-time context in the task
    off = Scripted([act("run_tests", target=TARGET), act("finish", summary="x")])
    rec2 = ag.run_agent(cfg.repo_root, sys.executable, TARGET, off, use_faultline=False)
    assert rec2["faultline_injections"] == 0 and "Faultline" not in off.seen[0]


def test_gemini_request_shape(monkeypatch):
    sent = {}

    def fake_post(url, body, headers, timeout):
        sent.update(url=url, body=body, headers=headers)
        return {"candidates": [{"content": {"parts": [{"text": act("finish", summary="ok")}]}}],
                "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 3, "thoughtsTokenCount": 5}}

    monkeypatch.setattr(ag, "_post", fake_post)
    g = ag.GeminiProvider(api_key="test-key")
    u = ag.Usage()
    out = g.complete("sys", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "a"}], u, 10)
    assert json.loads(out)["tool"] == "finish"
    assert sent["url"].endswith("/models/gemma-4-26b-a4b-it:generateContent")
    assert sent["headers"]["x-goog-api-key"] == "test-key"
    assert [c["role"] for c in sent["body"]["contents"]] == ["user", "model"]
    assert sent["body"]["systemInstruction"]["parts"][0]["text"] == "sys"
    assert (u.prompt_tokens, u.completion_tokens, u.thinking_tokens) == (12, 3, 5)


def test_gemini_requires_key_and_local_refuses_remote_endpoints(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(ag, "KEY_FILE", __import__("pathlib").Path("/nonexistent/faultline/key"))
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        ag.GeminiProvider()
    with pytest.raises(ValueError):
        ag.LocalProvider(endpoint="https://example.com")


def test_missing_test_path_suggests_closest(proj):
    ws = ag.Workspace(__import__("pathlib").Path(proj.repo_root), sys.executable)
    obs, raw = ws.run_tests("test/test_cart.py::test_small_order")
    assert obs.startswith("no such test path: test/test_cart.py") and "tests/test_cart.py" in obs and raw == ""
