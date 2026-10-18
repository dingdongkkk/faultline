"""Open-model debugging agent with Faultline context.

An open-weight model is the main bug-fixer. It runs either locally through
llama.cpp ``llama-server`` (provider ``local``) or remotely through the Gemini
API (provider ``gemini``, e.g. ``gemma-4-26b-a4b-it``). Both providers use the
same loop, tools and plain-JSON action protocol, so results are comparable.

Tools are confined to the repository root. There is no arbitrary shell: the
model can list, search, read, edit non-test files, and run pytest. With
``faultline=True`` the same context the Claude Code hooks inject is added to
the task and to failing test output (``faultline.claude.context``).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .config import ConfigError, is_test_path, load_config, resolve_inside

TOOLS = {
    "list_files": "List files under a directory. args: {\"path\": \".\"}",
    "search": "Regex search in .py files. args: {\"pattern\": \"...\", \"path\": \".\"}",
    "read_file": "Read numbered lines. args: {\"path\": \"pkg/x.py\", \"start\": 1, \"end\": 120}",
    "edit_file": "Replace exactly one occurrence of old with new in a non-test file. "
                 "args: {\"path\": \"pkg/x.py\", \"old\": \"...\", \"new\": \"...\"}",
    "run_tests": "Run pytest. args: {\"target\": \"tests/test_x.py::test_y\"} (empty target = whole suite)",
    "finish": "Stop when the failing test and the suite pass. args: {\"summary\": \"what you changed\"}",
}

SYSTEM = (
    "You are a careful Python debugging agent working in a repository. Fix the bug in the "
    "application code so the failing test passes; never edit test files. Reply with exactly ONE "
    "JSON object and nothing else: {\"tool\": <name>, \"args\": {...}}.\n"
    "Tools:\n" + "\n".join(f"- {k}: {v}" for k, v in TOOLS.items()) + "\n"
    "Work in small steps: reproduce, inspect the relevant code, edit, rerun tests, then finish."
)

ACTION_SCHEMA = {
    "type": "object",
    "properties": {"tool": {"type": "string", "enum": list(TOOLS)}, "args": {"type": "object"}},
    "required": ["tool", "args"],
}

MAX_OBS_CHARS = 6000
MAX_LIST = 200
MAX_MATCHES = 60
MAX_READ_LINES = 200


class ProviderError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------


def _post(url: str, body: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read()[:4000].decode("utf-8", "replace")
        err = ProviderError(f"HTTP {e.code}: {detail[:300]}")
        err.status, err.detail = e.code, detail
        raise err from e
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
        raise ProviderError(f"{type(e).__name__}: {e}"[:300]) from e


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    thinking_tokens: int = 0

    def add(self, prompt: int | None, completion: int | None, thinking: int | None = None) -> None:
        self.calls += 1
        self.prompt_tokens += prompt or 0
        self.completion_tokens += completion or 0
        self.thinking_tokens += thinking or 0


class LocalProvider:
    """llama.cpp llama-server on localhost (OpenAI-style chat endpoint, grammar-constrained JSON)."""

    name = "local"

    def __init__(self, endpoint: str = "http://127.0.0.1:8089", max_tokens: int = 1024, temperature: float = 0.0):
        if not endpoint.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]")):
            raise ValueError("local provider endpoint must be on this machine (http://127.0.0.1:PORT)")
        self.endpoint = endpoint.rstrip("/")
        self.max_tokens = max_tokens
        self.temperature = temperature

    def model_id(self) -> str:
        try:
            req = urllib.request.Request(self.endpoint + "/props")
            with urllib.request.urlopen(req, timeout=5) as r:
                p = json.load(r)
            return f"{str(p.get('model_path', '?')).rsplit('/', 1)[-1]}@{p.get('build_info', '?')}"
        except Exception:  # noqa: BLE001
            return "local-unknown"

    def complete(self, system: str, messages: list[dict], usage: Usage, timeout: float) -> str:
        body = {"messages": [{"role": "system", "content": system}] + messages,
                "temperature": self.temperature, "seed": 0, "max_tokens": self.max_tokens,
                "response_format": {"type": "json_schema", "json_schema": {"name": "action", "schema": ACTION_SCHEMA}},
                "chat_template_kwargs": {"enable_thinking": False}}
        r = _post(self.endpoint + "/v1/chat/completions", body, {}, timeout)
        u = r.get("usage") or {}
        usage.add(u.get("prompt_tokens"), u.get("completion_tokens"))
        try:
            return r["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError) as e:
            raise ProviderError(f"malformed response: {e}") from e


KEY_FILE = Path.home() / ".config" / "faultline" / "gemini_api_key"


def _key_file() -> str | None:
    """Key stored by the user in a private file (never logged or echoed)."""
    try:
        if KEY_FILE.exists() and KEY_FILE.stat().st_mode & 0o077 == 0:
            return KEY_FILE.read_text().strip() or None
    except OSError:
        return None
    return None


class GeminiProvider:
    """Gemini API generateContent (e.g. Gemma 4: gemma-4-26b-a4b-it, gemma-4-31b-it).

    Sends the task, file excerpts and test output to Google. Opt-in only."""

    name = "gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, model: str = "gemma-4-26b-a4b-it", api_key: str | None = None,
                 max_tokens: int = 1024, temperature: float = 0.0, thinking: str = "minimal"):
        self.model = model
        # Gemma 4 thinks by default (~940 thinking tokens and ~20 s for a trivial reply, measured);
        # "minimal" disables it. "default" sends no thinking config.
        self.thinking = thinking
        self.max_rate_retries = 12
        self.rate_limit_waits = 0
        self.rate_limit_seconds = 0.0
        self.server_error_retries = 0
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or _key_file()
        if not self.api_key:
            raise ValueError("set GEMINI_API_KEY or write the key to ~/.config/faultline/gemini_api_key "
                             "(create a key in Google AI Studio) to use the gemini provider")
        self.max_tokens = max_tokens
        self.temperature = temperature

    def model_id(self) -> str:
        return f"gemini-api:{self.model}:thinking={self.thinking}"

    def complete(self, system: str, messages: list[dict], usage: Usage, timeout: float) -> str:
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                    for m in messages]
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                "generationConfig": {"temperature": self.temperature, "maxOutputTokens": self.max_tokens}}
        if self.thinking != "default":
            body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": self.thinking}
        r = None
        for attempt in range(self.max_rate_retries + 1):
            try:
                r = _post(self.URL.format(model=self.model), body, {"x-goog-api-key": self.api_key}, timeout)
                break
            except ProviderError as e:
                status = getattr(e, "status", None)
                if status not in (429, 500, 502, 503, 504) or attempt == self.max_rate_retries:
                    raise
                if status == 429:
                    # Free-tier rate limit: wait as instructed (retryDelay). No tokens are used.
                    m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', getattr(e, "detail", ""))
                    delay = min(90.0, float(m.group(1)) + 1 if m else 10.0 * (attempt + 1))
                    self.rate_limit_waits += 1
                    self.rate_limit_seconds += delay
                else:
                    # Transient server error (observed: HTTP 500 INTERNAL from the Gemma endpoint).
                    delay = min(60.0, 5.0 * (attempt + 1))
                    self.server_error_retries += 1
                time.sleep(delay)
        u = r.get("usageMetadata") or {}
        usage.add(u.get("promptTokenCount"), u.get("candidatesTokenCount"), u.get("thoughtsTokenCount"))
        try:
            parts = r["candidates"][0]["content"].get("parts") or []
        except (KeyError, IndexError) as e:
            raise ProviderError(f"no candidate in response: {str(r)[:200]}") from e
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def make_provider(name: str, **kw):
    if name == "local":
        return LocalProvider(**{k: v for k, v in kw.items() if k in ("endpoint", "max_tokens", "temperature") and v is not None})
    if name == "gemini":
        return GeminiProvider(**{k: v for k, v in kw.items()
                                 if k in ("model", "max_tokens", "temperature", "thinking") and v is not None})
    raise ValueError(f"unknown provider: {name}")


# --------------------------------------------------------------------------
# Tools (repository-confined)
# --------------------------------------------------------------------------


@dataclass
class Workspace:
    root: Path
    python: str
    test_timeout: int = 120
    edits: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.cfg = load_config(str(self.root), self.python)

    def _path(self, rel: str) -> Path:
        return resolve_inside(self.cfg, rel or ".") if rel not in ("", ".") else Path(self.cfg.repo_root)

    def list_files(self, path: str = ".") -> str:
        base = self._path(path)
        out = []
        for p in sorted(base.rglob("*")):
            parts = p.relative_to(self.cfg.repo_root).parts
            if any(x.startswith(".") or x in ("__pycache__", "venv", "node_modules") for x in parts):
                continue
            if p.is_file():
                out.append(p.relative_to(self.cfg.repo_root).as_posix())
            if len(out) >= MAX_LIST:
                out.append(f"... (truncated at {MAX_LIST})")
                break
        return "\n".join(out) or "(no files)"

    def search(self, pattern: str, path: str = ".") -> str:
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return f"invalid regex: {e}"
        base = self._path(path)
        hits = []
        files = [base] if base.is_file() else sorted(base.rglob("*.py"))
        for p in files:
            rel = p.relative_to(self.cfg.repo_root).as_posix()
            if any(x.startswith(".") for x in Path(rel).parts):
                continue
            try:
                for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                    if rx.search(line):
                        hits.append(f"{rel}:{i}: {line.strip()[:200]}")
                        if len(hits) >= MAX_MATCHES:
                            return "\n".join(hits) + f"\n... (truncated at {MAX_MATCHES})"
            except OSError:
                continue
        return "\n".join(hits) or "(no matches)"

    def read_file(self, path: str, start: int = 1, end: int | None = None) -> str:
        p = self._path(path)
        lines = p.read_text(errors="replace").splitlines()
        start = max(1, int(start))
        end = min(len(lines), int(end) if end else start + MAX_READ_LINES - 1, start + MAX_READ_LINES - 1)
        body = "\n".join(f"{i:5d}| {lines[i - 1]}" for i in range(start, end + 1))
        return body + (f"\n... ({len(lines)} lines total)" if end < len(lines) else "")

    def edit_file(self, path: str, old: str, new: str) -> str:
        rel = self._path(path).relative_to(self.cfg.repo_root).as_posix()
        if is_test_path(self.cfg, rel):
            return "refused: test files must not be edited"
        p = self._path(path)
        text = p.read_text()
        n = text.count(old) if old else 0
        if n != 1:
            return f"refused: `old` must match exactly once (found {n} matches)"
        p.write_text(text.replace(old, new, 1))
        self.edits.append(rel)
        return f"edited {rel}"

    def run_tests(self, target: str = "") -> tuple[str, str]:
        args = [self.python, "-m", "pytest", "-q", "--tb=short", "--disable-warnings", "-p", "no:cacheprovider"]
        if target:
            if target.startswith("-"):
                return "refused: target must be a test path or node ID", ""
            path = self._path(target.split("::", 1)[0])  # must stay inside the repo
            if not path.exists():
                import difflib

                rels = [p.relative_to(self.cfg.repo_root).as_posix() for p in Path(self.cfg.repo_root).rglob("test*.py")
                        if not any(x.startswith(".") for x in p.relative_to(self.cfg.repo_root).parts)]
                near = difflib.get_close_matches(target.split("::", 1)[0], rels, n=3, cutoff=0.5)
                return (f"no such test path: {target.split('::', 1)[0]}"
                        + (f"; did you mean: {', '.join(near)}" if near else "")), ""
            args.append(target)
        env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS")}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            r = subprocess.run(args, cwd=self.cfg.repo_root, capture_output=True, text=True,
                               timeout=self.test_timeout, env=env, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return "tests timed out", ""
        raw = r.stdout + r.stderr
        return f"exit code {r.returncode}\n" + _tail(raw, MAX_OBS_CHARS), raw


def _tail(text: str, n: int) -> str:
    return text if len(text) <= n else "[...truncated...]\n" + text[-n:]


# --------------------------------------------------------------------------
# Loop
# --------------------------------------------------------------------------


def parse_action(text: str) -> dict | None:
    """First JSON object in the reply with a known tool and an args object."""
    text = text.strip()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[m.start():])
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("tool") in TOOLS and isinstance(obj.get("args", {}), dict):
            obj.setdefault("args", {})
            return obj
    return None


TRANSPORT = {"used": None}


def _context_via_mcp(root: Path, python: str, kind: str, text: str) -> str | None:
    """Call Faultline's `failure_context` MCP tool over stdio, like any MCP client."""
    import asyncio

    from mcp import Client, StdioServerParameters

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "faultline.cli", "serve", "--repo", str(root), "--python", python],
        env={**{k: v for k, v in os.environ.items()
                if k in ("PATH", "HOME", "PYTHONPATH", "LANG") or k.startswith("FAULTLINE_")},
             "PYTHONPATH": os.pathsep.join(filter(None, [str(Path(__file__).resolve().parents[1]),
                                                         os.environ.get("PYTHONPATH", "")]))})

    async def go():
        async with Client(params) as client:
            r = await client.call_tool("failure_context", {"kind": kind, "text": text})
            return "".join(getattr(c, "text", "") for c in r.content) if not r.is_error else ""

    return asyncio.run(go()) or None


def faultline_context(root: Path, event: dict, python: str = sys.executable) -> str | None:
    """Faultline context for the agent, obtained through the MCP server (falls back to a
    direct call only if the MCP SDK is unavailable; the record says which was used)."""
    kind = "task" if event.get("hook_event_name") == "UserPromptSubmit" else "test_output"
    text = event.get("prompt", "") if kind == "task" else (event.get("tool_response") or {}).get("stdout", "")
    try:
        out = _context_via_mcp(root, python, kind, text)
        TRANSPORT["used"] = "mcp-stdio"
        return out
    except ImportError:
        from .claude import context

        TRANSPORT["used"] = "direct"
        try:
            return context(str(root), dict(event, cwd=str(root)))
        except (OSError, ValueError, TypeError, AttributeError):
            return None
    except Exception:  # noqa: BLE001 - never break the agent loop on context errors
        return None


def run_agent(repo: str, python: str, failing_test: str, provider, *, use_faultline: bool,
              max_steps: int = 30, wall_seconds: int = 900, log=None) -> dict:
    root = Path(repo).resolve()
    ws = Workspace(root, python)
    usage = Usage()
    task = (f"The test {failing_test} fails in this repository. Find and fix the bug in the application code "
            f"so the intended behavior holds. Do not modify any test files.")
    injected: list[int] = []
    if use_faultline:
        ctx = faultline_context(root, {"hook_event_name": "UserPromptSubmit", "prompt": task}, python)
        if ctx:
            task += "\n\n" + ctx
            injected.append(len(ctx.encode()))
    messages = [{"role": "user", "content": task}]
    tool_counts: dict[str, int] = {}
    trace: list[dict] = []
    status, summary, invalid = "max_steps", "", 0
    last_key, repeats = None, 0
    t0 = time.monotonic()
    for step in range(1, max_steps + 1):
        if time.monotonic() - t0 > wall_seconds:
            status = "timeout"
            break
        try:
            reply = provider.complete(SYSTEM, messages, usage, timeout=max(10.0, wall_seconds - (time.monotonic() - t0)))
        except ProviderError as e:
            status, summary = "provider_error", str(e)
            break
        messages.append({"role": "assistant", "content": reply})
        action = parse_action(reply)
        if action is None:
            invalid += 1
            obs = 'Invalid reply. Respond with ONE JSON object: {"tool": "...", "args": {...}}.'
            if invalid >= 5:
                status = "invalid_replies"
                break
        else:
            tool, args = action["tool"], action["args"]
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
            key = json.dumps(action, sort_keys=True)
            repeats = repeats + 1 if key == last_key else 1
            last_key = key
            entry = {"step": step, "tool": tool, "args": json.dumps(args)[:200], "injected_bytes": 0}
            trace.append(entry)
            if log:
                log(f"step {step}: {tool} {json.dumps(args)[:160]}")
            if repeats >= 3 and tool != "finish":
                # Same guard with and without Faultline: break greedy-decoding loops.
                messages.append({"role": "user", "content": "Result:\nYou have repeated this exact action "
                                 f"{repeats} times with the same result. Choose a different action."})
                continue
            if tool == "finish":
                status, summary = "finished", str(args.get("summary", ""))[:1000]
                break
            try:
                if tool == "run_tests":
                    obs, raw = ws.run_tests(str(args.get("target", "")))
                    if use_faultline and "exit code 0" not in obs.splitlines()[0]:
                        ctx = faultline_context(root, {"hook_event_name": "PostToolUseFailure", "tool_name": "Bash",
                                                       "tool_response": {"stdout": raw, "stderr": ""}}, python)
                        if ctx:
                            obs += "\n\n" + ctx
                            injected.append(len(ctx.encode()))
                            entry["injected_bytes"] = len(ctx.encode())
                elif tool == "list_files":
                    obs = ws.list_files(str(args.get("path", ".")))
                elif tool == "search":
                    obs = ws.search(str(args.get("pattern", "")), str(args.get("path", ".")))
                elif tool == "read_file":
                    obs = ws.read_file(str(args.get("path", "")), args.get("start", 1), args.get("end"))
                else:  # edit_file
                    obs = ws.edit_file(str(args.get("path", "")), str(args.get("old", "")), str(args.get("new", "")))
            except (ConfigError, OSError, ValueError, TypeError) as e:
                obs = f"error: {type(e).__name__}: {str(e)[:200]}"
        messages.append({"role": "user", "content": "Result:\n" + _tail(obs, MAX_OBS_CHARS)})
    return {
        "status": status, "summary": summary, "steps": len([m for m in messages if m["role"] == "assistant"]),
        "invalid_replies": invalid, "tool_calls": tool_counts, "edits": ws.edits,
        "faultline": use_faultline, "faultline_transport": TRANSPORT["used"] if use_faultline else None,
        "faultline_injections": len(injected), "faultline_injected_bytes": sum(injected),
        "provider": provider.name, "model": provider.model_id(),
        "usage": {"model_calls": usage.calls, "prompt_tokens": usage.prompt_tokens,
                  "completion_tokens": usage.completion_tokens, "thinking_tokens": usage.thinking_tokens,
                  "total_tokens": usage.prompt_tokens + usage.completion_tokens + usage.thinking_tokens},
        "wall_seconds": round(time.monotonic() - t0, 1),
        "rate_limit_waits": getattr(provider, "rate_limit_waits", 0),
        "rate_limit_wait_seconds": round(getattr(provider, "rate_limit_seconds", 0.0), 1),
        "server_error_retries": getattr(provider, "server_error_retries", 0),
        "trace": trace,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="faultline agent")
    ap.add_argument("failing_test")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--python", required=True, help="interpreter with pytest for the target project")
    ap.add_argument("--provider", choices=["local", "gemini"], required=True)
    ap.add_argument("--model", default=None, help="gemini model id (default gemma-4-26b-a4b-it)")
    ap.add_argument("--endpoint", default=None, help="local llama-server URL (default http://127.0.0.1:8089)")
    ap.add_argument("--faultline", choices=["on", "off"], default="on")
    ap.add_argument("--thinking", choices=["minimal", "low", "medium", "high", "default"], default=None,
                    help="gemini provider thinking level (default minimal)")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--wall-seconds", type=int, default=900)
    ap.add_argument("--out", default=None, help="write the JSON record here")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    provider = make_provider(args.provider, model=args.model, endpoint=args.endpoint, thinking=args.thinking)
    if args.provider == "gemini" and not args.quiet:
        print("Note: the gemini provider sends task text, code excerpts and test output to Google.", file=sys.stderr)
    log = None if args.quiet else (lambda s: print(s, file=sys.stderr))
    rec = run_agent(args.repo, args.python, args.failing_test, provider, use_faultline=args.faultline == "on",
                    max_steps=args.max_steps, wall_seconds=args.wall_seconds, log=log)
    text = json.dumps(rec, indent=1)
    if args.out:
        Path(args.out).write_text(text)
    print(text)
    return 0 if rec["status"] == "finished" else 1


if __name__ == "__main__":
    raise SystemExit(main())
