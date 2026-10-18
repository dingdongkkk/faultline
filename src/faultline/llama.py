"""llama.cpp ``llama-server`` client for the local-model planner.

Verified against llama-server build b11669 (Homebrew llama.cpp 0.7.0) on
2026-10-18: ``/v1/chat/completions`` accepts ``response_format`` of type
``json_schema`` with the pydantic-generated planner schema (``oneOf`` +
``discriminator`` + ``$ref``), and ``chat_template_kwargs.enable_thinking``
disables Qwen3 thinking. Output is still validated by the engine.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .planners import ModelUnavailable

SYSTEM = ("You are a planning component inside a debugging tool. You only choose which bounded observation "
          "to make next, as one JSON object. You never see or write code to execute.")


class LlamaServerCompletion:
    def __init__(self, endpoint: str, *, max_tokens: int = 256, seed: int = 0, temperature: float = 0.0):
        if not endpoint.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]")):
            raise ValueError("model endpoint must be a local llama-server (http://127.0.0.1:PORT)")
        self.endpoint = endpoint.rstrip("/")
        self.max_tokens = max_tokens
        self.seed = seed
        self.temperature = temperature
        self._model_id: str | None = None

    def _request(self, path: str, body: dict | None, timeout: float) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.endpoint + path, data, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=max(1.0, timeout)) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
            raise ModelUnavailable(f"{type(e).__name__}: {e}"[:120]) from e

    def model_id(self, timeout: float = 5.0) -> str:
        """Provenance: model file name + server build (from /props)."""
        if self._model_id is None:
            p = self._request("/props", None, timeout)
            name = str(p.get("model_path", "?")).rsplit("/", 1)[-1]
            self._model_id = f"{name}@{p.get('build_info', '?')}"
        return self._model_id

    def __call__(self, prompt: str, schema: dict, timeout: float = 60.0) -> tuple[str, dict]:
        body = {
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "planner_action", "schema": schema}},
            "temperature": self.temperature, "seed": self.seed, "max_tokens": self.max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        t = time.monotonic()
        r = self._request("/v1/chat/completions", body, timeout)
        try:
            msg = r["choices"][0]["message"]
            text = msg.get("content") or ""
        except (KeyError, IndexError, TypeError) as e:
            raise ModelUnavailable(f"malformed response: {e}") from e
        usage = r.get("usage") or {}
        timings = r.get("timings") or {}
        return text, {
            "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
            "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
            "wall_ms": int((time.monotonic() - t) * 1000), "prompt_ms": timings.get("prompt_ms"),
            "predicted_ms": timings.get("predicted_ms"), "finish_reason": r["choices"][0].get("finish_reason"),
        }
