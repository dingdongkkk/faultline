"""M3: AST boundaries match runtime code objects; excerpt bounding and merging."""

import textwrap

from faultline.source import build_excerpt, index_source, merge_ranges

SRC = textwrap.dedent('''\
    import functools


    def deco(f):
        return f


    @deco
    @functools.lru_cache
    def cached(x):
        return x


    class Cart:
        def total(self, items):
            subtotal = sum(items)

            def fee(n):
                return n + subtotal

            return fee(1)

        async def fetch(self):
            return 1


    def outer():
        def inner(y):
            z = y * 2
            return z
        return inner


    def gen(n):
        yield from range(n)


    MODULE_VALUE = cached(3)
''')


def _runtime_codes():
    code = compile(SRC, "m.py", "exec")
    out, todo = {}, [code]
    while todo:
        c = todo.pop()
        out[c.co_qualname] = c.co_firstlineno
        todo.extend(k for k in c.co_consts if hasattr(k, "co_qualname"))
    return out


def test_ast_qualnames_and_first_lines_match_runtime_code_objects():
    idx = index_source("m.py", SRC.encode())
    runtime = _runtime_codes()
    for fn in idx.functions:
        assert fn.qualname in runtime, fn.qualname
        assert runtime[fn.qualname] == fn.start, fn.qualname  # decorated: first decorator line
    names = {f.qualname for f in idx.functions}
    assert {"Cart.total", "Cart.total.<locals>.fee", "outer.<locals>.inner", "Cart.fetch", "gen", "cached"} <= names
    gen = next(f for f in idx.functions if f.qualname == "gen")
    assert gen.is_generator and next(f for f in idx.functions if f.qualname == "Cart.fetch").is_async


def test_innermost_function_and_candidate_locals():
    idx = index_source("m.py", SRC.encode())
    ln = next(i + 1 for i, s in enumerate(idx.lines) if "return n + subtotal" in s)
    assert idx.innermost_function(ln).qualname == "Cart.total.<locals>.fee"
    assert idx.candidate_locals(ln) == ["n", "subtotal"]
    ln_total = next(i + 1 for i, s in enumerate(idx.lines) if "subtotal = sum(items)" in s)
    # nested function bodies are not part of the enclosing scope's names
    total = idx.innermost_function(ln_total)
    assert "n" not in total.names and {"items", "subtotal", "self"} <= total.names
    mod = next(i + 1 for i, s in enumerate(idx.lines) if s.startswith("MODULE_VALUE"))
    assert idx.innermost_function(mod) is None and idx.candidate_locals(mod) == ["MODULE_VALUE", "cached"]


def test_merge_ranges():
    assert merge_ranges([(5, 7), (1, 2), (3, 4), (10, 12), (11, 20)]) == [(1, 7), (10, 20)]


def test_small_function_excerpt_is_whole_region():
    idx = index_source("m.py", SRC.encode())
    fn = next(f for f in idx.functions if f.qualname == "outer.<locals>.inner")
    ex = build_excerpt(idx, "S1", [fn.start + 1], function_id="F1", max_lines=60, context=3)
    assert (ex.region.start, ex.region.end) == (fn.start, fn.end)
    assert ex.omitted == [] and not ex.truncated
    assert ex.text.splitlines()[0] == f"{fn.start:4d}|     def inner(y):"


def test_large_function_excerpt_bounded_with_omitted_ranges_and_dedup():
    body = "\n".join(f"    v{i} = {i}" for i in range(200))
    src = f"def big():\n{body}\n    return v0\n"
    idx = index_source("b.py", src.encode())
    ex = build_excerpt(idx, "S1", [50, 52, 150, 50], function_id="F1", max_lines=20, context=3)
    shown = [(r.start, r.end) for r in ex.shown]
    assert shown == [(1, 2), (47, 55), (147, 153)]  # header + merged overlapping windows
    total_shown = sum(e - s + 1 for s, e in shown)
    assert total_shown <= 20 and len(ex.text.splitlines()) == total_shown
    omitted = [(r.start, r.end) for r in ex.omitted]
    assert omitted == [(3, 46), (56, 146), (154, 202)]
    assert not ex.truncated


def test_excerpt_truncated_when_windows_exceed_budget():
    body = "\n".join(f"    v{i} = {i}" for i in range(200))
    idx = index_source("b.py", f"def big():\n{body}\n".encode())
    ex = build_excerpt(idx, "S1", [20, 60, 100, 140, 180], function_id=None, max_lines=12, context=3)
    assert ex.truncated and sum(r.end - r.start + 1 for r in ex.shown) == 12
