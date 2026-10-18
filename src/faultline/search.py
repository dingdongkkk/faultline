"""Bounded Python source retrieval. No test execution, inference or imports.

Lexical retrieval is combined with conservative, statically resolved imports
and calls. These links describe possible source relationships, not runtime
reachability or fault probabilities. Every request reads current contents.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import time
import warnings
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import is_excluded, is_test_path, resolve_inside
from .contracts import FaultlineConfig, SearchHit, SearchResponse

MAX_FILES = 2000
MAX_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024
MAX_ENTRIES = 20000
MAX_SECONDS = 5
_SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}
_STOP = {"the", "a", "an", "is", "in", "for", "of", "to", "and", "or", "with", "from", "find", "why"}


def terms(text: str) -> set[str]:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return {s for s in re.findall(r"[a-zA-Z0-9]+", text.lower()) if s not in _STOP}


@dataclass
class Chunk:
    path: str
    symbol: str
    start: int
    end: int
    lines: list[str]
    sha: str
    tokens: set[str]
    calls: set[str]
    names: set[str]
    kind: str = "function"

    @property
    def key(self):
        return (self.path, self.symbol)


def _module(path: str) -> str:
    p = path.removesuffix(".py").removesuffix("/__init__")
    return p.removeprefix("src/").replace("/", ".")


def _imports(tree: ast.Module, path: str) -> dict[str, tuple[str, str]]:
    """Only direct module imports. No guessing of wildcard or dynamic imports."""
    out = {}
    package = _module(path).split(".")
    if not path.endswith("/__init__.py"):
        package = package[:-1]
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            prefix = package[:len(package) - node.level + 1] if node.level else []
            module = ".".join(prefix + ([node.module] if node.module else []))
            for alias in node.names:
                if alias.name != "*":
                    out[alias.asname or alias.name] = (module, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out[alias.asname or alias.name.split(".")[0]] = (alias.name, "")
    return out


def _nodes(node):
    """Walk one definition, without absorbing nested definitions."""
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield from _nodes(child)


def _chunks(path: str, data: bytes):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(data, filename=path)
    lines = data.decode("utf-8", "replace").splitlines()
    sha = hashlib.sha256(data).hexdigest()
    chunks = []

    def add(symbol, start, end, nodes, kind="function"):
        calls, names = set(), set()
        for n in nodes:
            if isinstance(n, ast.Name):
                names.add(n.id)
            if isinstance(n, ast.Call):
                if isinstance(n.func, ast.Name):
                    calls.add(n.func.id)
                elif isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name):
                    calls.add(n.func.value.id + "." + n.func.attr)
        chunks.append(Chunk(path, symbol, start, end, lines, sha,
                            terms(path + " " + symbol + " " + "\n".join(lines[start-1:end])), calls, names, kind))

    def visit(body, prefix=""):
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + n.name
                start = min([n.lineno] + [d.lineno for d in n.decorator_list])
                # Class headers/attributes are separate from their methods.
                end = n.end_lineno
                if isinstance(n, ast.ClassDef):
                    children = [x.lineno for x in n.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
                    end = min(children) - 1 if children else end
                add(name, start, max(start, end), _nodes(n), "class" if isinstance(n, ast.ClassDef) else "function")
                visit(n.body, name + ".")
    visit(tree.body)
    # Top-level imports/constants are useful context, but never duplicate bodies.
    spans = [(n.lineno, n.end_lineno) for n in tree.body
             if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    for start, end in spans:
        for offset in range(start, end + 1, 24):
            add(f"<module:{offset}>", offset, min(offset + 23, end), (), "module")
    return chunks, _imports(tree, path)


def _scan(cfg):
    chunks, imports, modules, warnings = [], {}, {}, set()
    used = count = entries = 0
    deadline = time.monotonic() + MAX_SECONDS
    root = Path(cfg.repo_root)
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP
                         and not Path(directory, d).is_symlink()
                         and not is_excluded(cfg, Path(directory, d).relative_to(root).as_posix()))
        for name in sorted(files):
            entries += 1
            if entries > MAX_ENTRIES or time.monotonic() > deadline or count >= MAX_FILES or used >= MAX_BYTES:
                warnings.add("scan_limit: refine query in a smaller configured repository")
                return chunks, imports, modules, count, warnings
            path = Path(directory, name)
            rel = path.relative_to(root).as_posix()
            if not name.endswith(".py") or path.is_symlink() or is_excluded(cfg, rel):
                continue
            try:
                with resolve_inside(cfg, rel).open("rb") as f:
                    data = f.read(min(MAX_FILE_BYTES, MAX_BYTES - used) + 1)
                if len(data) > min(MAX_FILE_BYTES, MAX_BYTES - used):
                    warnings.add("oversized_files_skipped")
                    continue
                used += len(data)
                count += 1
                found, aliases = _chunks(rel, data)
            except (OSError, ValueError, SyntaxError, RecursionError):
                warnings.add("unreadable_or_unparseable_files_skipped")
                continue
            chunks.extend(found)
            imports[rel] = aliases
            modules.setdefault(_module(rel), []).append(rel)
    return chunks, imports, modules, count, warnings


def _links(chunks, imports, modules):
    by_key = {c.key: i for i, c in enumerate(chunks)}
    constants = {}
    for j, c in enumerate(chunks):
        if c.symbol.startswith("<module:"):
            name = c.lines[c.start-1].split("=", 1)[0].strip()
            if name.isidentifier():
                constants[(c.path, name)] = j
    edges = {i: set() for i in range(len(chunks))}
    for i, c in enumerate(chunks):
        aliases = imports[c.path]
        for call in c.calls:
            target = by_key.get((c.path, call))
            if target is not None:
                edges[i].add(target)
                initializer = by_key.get((c.path, call + ".__init__"))
                if initializer is not None:
                    edges[i].add(initializer)
            head, _, attr = call.partition(".")
            if head in aliases:
                mod, symbol = aliases[head]
                # Ambiguous module names are not resolved.
                paths = modules.get(mod, [])
                if len(paths) == 1:
                    target = by_key.get((paths[0], symbol or attr))
                    if target is not None:
                        edges[i].add(target)
        # Constants in the same module referenced by this definition.
        for name in c.names:
            j = constants.get((c.path, name))
            if j is not None:
                edges[i].add(j)
    return edges


def search_code(cfg: FaultlineConfig, query: str, failing_test: str | None = None,
                budget_tokens: int = 1200, seen_ids: list[str] | None = None,
                measure: Callable[[str], int] | None = None) -> SearchResponse:
    """Return original source, not a generated explanation. Budget is an estimate."""
    if not query.strip() or len(query) > 2000:
        raise ValueError("query must contain 1..2000 characters")
    if not 400 <= budget_tokens <= 8000:
        raise ValueError("budget_tokens must be in [400, 8000]")
    if seen_ids is not None and (len(seen_ids) > 100 or any(len(x) > 80 for x in seen_ids)):
        raise ValueError("seen_ids is limited to 100 excerpt IDs")
    target_path = target_symbol = None
    if failing_test:
        if len(failing_test) > 1000 or "::" not in failing_test:
            raise ValueError("failing_test must be a pytest node ID")
        target_path, *parts = failing_test.split("::")
        resolve_inside(cfg, target_path)
        target_symbol = ".".join(parts).split("[", 1)[0]
    # A traceback location is already a precise retrieval plan: avoid a repo scan.
    anchor = re.fullmatch(r"(.+\.py):(\d+)", query.strip())
    anchor_line = None
    if anchor:
        path = resolve_inside(cfg, anchor[1])
        rel = path.relative_to(Path(cfg.repo_root)).as_posix()
        if is_excluded(cfg, rel) or any(part in _SKIP for part in Path(rel).parts):
            raise ValueError("source location is excluded")
        try:
            with path.open("rb") as stream:
                data = stream.read(MAX_FILE_BYTES + 1)
        except OSError as exc:
            raise ValueError("source location cannot be read") from exc
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("source file exceeds retrieval limit")
        lines = data.decode("utf-8", "replace").splitlines()
        anchor_line = int(anchor[2])
        if not 1 <= anchor_line <= len(lines):
            raise ValueError("source line is outside file")
        chunks = [Chunk(rel, "<source-location>", 1, len(lines), lines,
                        hashlib.sha256(data).hexdigest(), terms(query), set(), set())]
        imports, modules, files, warnings = {rel: {}}, {}, 1, set()
    else:
        chunks, imports, modules, files, warnings = _scan(cfg)
    q = terms(query)
    frequencies = Counter(t for c in chunks for t in c.tokens)
    # Literal/identifier matches in module constants inform functions in that
    # module, even when those functions never spell the user's symptom (JPY).
    module_signal = {}
    for c in chunks:
        body_matches = q & terms("\n".join(c.lines[c.start-1:c.end]))
        module_signal[c.path] = max(module_signal.get(c.path, 0), len(body_matches))
    exact = [i for i, c in enumerate(chunks) if query.strip() in (c.symbol, c.path + "::" + c.symbol)]
    scores, reasons = {}, {}
    for i, c in enumerate(chunks):
        matched = q & c.tokens
        score = sum(math.log(1 + len(chunks) / (1 + frequencies[t])) for t in matched)
        score += 3 * len(q & terms(c.symbol)) + len(q & terms(c.path))
        if c.kind == "function":
            score += 2 * module_signal[c.path]
        else:
            score *= 0.25
        if is_test_path(cfg, c.path) and (c.path != target_path or c.symbol != target_symbol):
            score *= 0.25
        if matched:
            scores[i], reasons[i] = score, ["lexical:" + ",".join(sorted(matched)[:5])]
    if anchor_line is not None:
        scores, reasons = {0: 100}, {0: ["exact_source_line"]}
    seeds = [i for i, c in enumerate(chunks) if c.path == target_path and c.symbol == target_symbol]
    if failing_test and not seeds:
        warnings.add("test_symbol_not_found")
    if exact:
        seeds = exact
        scores = {i: 50 for i in exact}
        reasons = {i: ["exact_symbol"] for i in exact}
    elif not seeds:
        seeds = sorted(scores, key=lambda i: (-scores[i], chunks[i].key))[:2]
    edges = _links(chunks, imports, modules)
    if not failing_test and not exact:
        for i, destinations in edges.items():
            if set(seeds) & destinations:
                scores[i] = scores.get(i, 0) + 18
                reasons.setdefault(i, []).append("static_caller")
    queue = deque((i, 0) for i in seeds)
    visited = set()
    while queue:
        i, depth = queue.popleft()
        if i in visited:
            continue
        visited.add(i)
        if depth == 0 and failing_test and chunks[i].path == target_path:
            scores[i] = scores.get(i, 0) + 30
            reasons.setdefault(i, []).append("named_test")
        elif depth:
            boost = 12 / depth * (1 if chunks[i].kind == "function" else 0.25)
            scores[i] = scores.get(i, 0) + boost
            reasons.setdefault(i, []).append(f"static_dependency:{depth}")
        if depth < 5:
            queue.extend((j, depth + 1) for j in sorted(edges[i]))
    order = sorted(scores, key=lambda i: (-scores[i], chunks[i].path, chunks[i].start))
    seen = set(seen_ids or [])
    hits, suppressed = [], 0
    for i in order:
        c = chunks[i]
        # Large definitions get one relevant source window, not their entire body.
        focus = anchor_line or max(range(c.start, c.end + 1), key=lambda n: len(q & terms(c.lines[n-1])))
        start = c.start if c.end - c.start < 24 else max(c.start, min(focus - 8, c.end - 23))
        end = min(c.end, start + 23)
        excerpt = "\n".join(f"{n}|{c.lines[n-1][:240]}" for n in range(start, end + 1))
        eid = hashlib.sha256(f"{c.path}:{c.sha}:{start}:{end}".encode()).hexdigest()[:24]
        if eid in seen:
            suppressed += 1
            continue
        hits.append(SearchHit(id=eid, path=c.path, symbol=c.symbol, start=start, end=end,
                              reason=reasons[i], code=excerpt,
                              truncated=start != c.start or end != c.end or any(len(c.lines[n-1]) > 240 for n in range(start, end + 1))))
    response = SearchResponse(status="ok" if hits else ("no_new_context" if suppressed else "no_matches"),
                              hits=[], scanned_files=files, matched_regions=len(order), suppressed=suppressed,
                              omitted=len(hits), limitations=sorted(warnings) + ["static_links_are_not_runtime_evidence"],
                              budget_tokens=budget_tokens, budget_scope="mcp_result" if measure else "json_payload")
    measure = measure or (lambda text: len(text.encode()))

    def size():
        for _ in range(12):
            n = measure(response.model_dump_json(exclude_none=True))
            if n == response.response_bytes:
                return n
            object.__setattr__(response, "response_bytes", n)
            object.__setattr__(response, "tokens_estimate", math.ceil(n / 3))
        raise ValueError("response size did not converge")

    for hit in hits:
        if any(h.path == hit.path and h.start <= hit.end and hit.start <= h.end for h in response.hits):
            continue
        response.hits.append(hit)
        object.__setattr__(response, "omitted", len(hits) - len(response.hits))
        if size() > budget_tokens * 3:
            # Preserve the highest-ranked location with a shorter window before
            # filling its place with low-value, smaller snippets.
            original = hit.code.splitlines()
            if len(original) > 8:
                best = (anchor_line - hit.start) if anchor_line else max(range(len(original)), key=lambda n: len(q & terms(original[n])))
                offset = max(0, min(best - 3, len(original) - 8))
                smaller = hit.model_copy(update={"start": hit.start + offset,
                                                "end": hit.start + offset + 7,
                                                "code": "\n".join(original[offset:offset+8]), "truncated": True})
                new_id = hashlib.sha256((hit.id + f":{offset}:8").encode()).hexdigest()[:24]
                smaller = smaller.model_copy(update={"id": new_id})
                response.hits[-1] = smaller
                if new_id not in seen and size() <= budget_tokens * 3:
                    continue
            response.hits.pop()
    object.__setattr__(response, "omitted", len(hits) - len(response.hits))
    if hits and not response.hits:
        object.__setattr__(response, "status", "budget_too_small")
    if size() > budget_tokens * 3:
        raise ValueError("response envelope exceeds budget")
    return response
