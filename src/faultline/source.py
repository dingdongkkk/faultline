"""AST-aware source indexing and bounded, merged excerpts."""

from __future__ import annotations

import ast
import hashlib
import symtable
from dataclasses import dataclass, field

from .config import resolve_inside
from .contracts import FaultlineConfig, LineRange, SourceExcerpt, SourceIdentity

_MAX_LINE_CHARS = 200


@dataclass(frozen=True)
class FunctionInfo:
    qualname: str  # matches the runtime code object's co_qualname
    start: int  # first decorator line == co_firstlineno
    def_line: int
    end: int
    params: tuple[str, ...]
    names: frozenset[str]  # readable frame locals: locals + params + free vars (symtable)
    is_generator: bool
    is_async: bool


@dataclass
class SourceIndex:
    path: str
    identity: SourceIdentity
    lines: list[str]
    functions: list[FunctionInfo]
    line_names: dict[int, set[str]] = field(default_factory=dict)

    def innermost_function(self, line: int) -> FunctionInfo | None:
        best = None
        for fn in self.functions:
            if fn.start <= line <= fn.end and (best is None or fn.start >= best.start):
                best = fn
        return best

    def candidate_locals(self, line: int, cap: int = 16) -> list[str]:
        """Frame-readable names for a line, ordered: names on the line, then the
        function's parameters, then its other locals (module scope: names on the line)."""
        on_line = self.line_names.get(line, set())
        fn = self.innermost_function(line)
        if fn is None:
            return sorted(on_line)[:cap]
        out = sorted(on_line & fn.names)
        out += [p for p in fn.params if p not in out]
        out += sorted(n for n in fn.names if n not in out)
        return out[:cap]


def identity_of(data: bytes, rel: str) -> SourceIdentity:
    return SourceIdentity(path=rel, sha256=hashlib.sha256(data).hexdigest(), size=len(data))


def _scopes(text: str, filename: str) -> dict[tuple[str, int], frozenset[str]]:
    """(function name, def line) -> names readable from its frame's f_locals."""
    out: dict[tuple[str, int], frozenset[str]] = {}
    todo = [symtable.symtable(text, filename, "exec")]
    while todo:
        t = todo.pop()
        if str(t.get_type()).lower().endswith("function"):  # str on 3.12, enum on 3.13+
            out[(t.get_name(), t.get_lineno())] = frozenset(t.get_locals()) | frozenset(t.get_frees())
        todo.extend(t.get_children())
    return out


class _Indexer(ast.NodeVisitor):
    def __init__(self, scopes: dict[tuple[str, int], frozenset[str]]) -> None:
        self.scopes = scopes
        self.stack: list[tuple[str, bool]] = []  # (name, is_function)
        self.functions: list[FunctionInfo] = []
        self.line_names: dict[int, set[str]] = {}

    def _qual(self, name: str) -> str:
        parts = []
        for n, is_fn in self.stack:
            parts.append(n)
            if is_fn:
                parts.append("<locals>")
        return ".".join(parts + [name])

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for d in node.decorator_list:
            self.visit(d)
        self.stack.append((node.name, False))
        for stmt in node.body:
            self.visit(stmt)
        self.stack.pop()

    def _function(self, node, is_async: bool) -> None:
        for d in node.decorator_list:
            self.visit(d)
        a = node.args
        params = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
        if a.vararg:
            params.append(a.vararg.arg)
        if a.kwarg:
            params.append(a.kwarg.arg)
        names = set(params) | set(self.scopes.get((node.name, node.lineno), ()))
        gen = any(isinstance(sub, (ast.Yield, ast.YieldFrom)) for sub in _walk_scope(node))
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        self.functions.append(FunctionInfo(
            qualname=self._qual(node.name), start=start, def_line=node.lineno, end=node.end_lineno or node.lineno,
            params=tuple(params), names=frozenset(names), is_generator=gen, is_async=is_async))
        self.stack.append((node.name, True))
        for stmt in node.body:
            self.visit(stmt)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node, False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node, True)

    def visit_Name(self, node: ast.Name) -> None:
        self.line_names.setdefault(node.lineno, set()).add(node.id)


def _walk_scope(fn):
    """Walk a function body without descending into nested function/class scopes."""
    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
    todo = [n for n in fn.body if not isinstance(n, nested)]
    while todo:
        node = todo.pop()
        yield node
        todo.extend(c for c in ast.iter_child_nodes(node) if not isinstance(c, nested))


def index_source(rel: str, data: bytes) -> SourceIndex:
    text = data.decode("utf-8", "replace")
    tree = ast.parse(text, filename=rel)
    ix = _Indexer(_scopes(text, rel))
    ix.visit(tree)
    return SourceIndex(path=rel, identity=identity_of(data, rel), lines=text.splitlines(),
                       functions=sorted(ix.functions, key=lambda f: (f.start, f.end)), line_names=ix.line_names)


def index_file(cfg: FaultlineConfig, rel: str) -> SourceIndex:
    return index_source(rel, resolve_inside(cfg, rel).read_bytes())


def merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping or adjacent inclusive ranges."""
    out: list[tuple[int, int]] = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def build_excerpt(idx: SourceIndex, excerpt_id: str, focus_lines: list[int], *, function_id: str | None,
                  max_lines: int, context: int) -> SourceExcerpt:
    fn = idx.innermost_function(focus_lines[0]) if focus_lines else None
    n = len(idx.lines)
    if fn is not None:
        region = (fn.start, min(fn.end, n))
    else:
        lo, hi = min(focus_lines), max(focus_lines)
        region = (max(1, lo - context), min(n, hi + context))
    truncated = False
    if region[1] - region[0] + 1 <= max_lines:
        shown = [region]
    else:
        header = (region[0], min(region[1], (fn.def_line if fn else region[0]) + 1))
        wanted = [header] + [(max(region[0], ln - context), min(region[1], ln + context))
                             for ln in sorted(set(focus_lines)) if region[0] <= ln <= region[1]]
        shown, used = [], 0
        for s, e in merge_ranges(wanted):
            take = min(e - s + 1, max_lines - used)
            if take <= 0:
                truncated = True
                break
            if take < e - s + 1:
                truncated = True
            shown.append((s, s + take - 1))
            used += take
        shown = merge_ranges(shown)
    omitted, cursor = [], region[0]
    for s, e in shown:
        if s > cursor:
            omitted.append((cursor, s - 1))
        cursor = e + 1
    if cursor <= region[1]:
        omitted.append((cursor, region[1]))
    text_lines = []
    for s, e in shown:
        for ln in range(s, e + 1):
            src = idx.lines[ln - 1] if ln - 1 < n else ""
            if len(src) > _MAX_LINE_CHARS:
                src, truncated = src[:_MAX_LINE_CHARS] + "…", True
            text_lines.append(f"{ln:4d}| {src}")
    return SourceExcerpt(
        excerpt_id=excerpt_id, source=idx.identity, function_id=function_id,
        qualname=fn.qualname if fn else None, region=LineRange(start=region[0], end=region[1]),
        shown=[LineRange(start=s, end=e) for s, e in shown],
        omitted=[LineRange(start=s, end=e) for s, e in omitted],
        text="\n".join(text_lines), truncated=truncated,
    )
