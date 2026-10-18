"""Search quality, repeated-context suppression and repository boundaries."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from faultline.config import load_config
from faultline.search import search_code

ROOT = Path(__file__).resolve().parents[1]


def config(root):
    return load_config(str(root), sys.executable)


def test_test_import_alias_and_same_module_calls_are_followed(tmp_path):
    (tmp_path / "test_flow.py").write_text("from api import handle as h\ndef test_flow():\n    assert h(3) == 7\n")
    (tmp_path / "api.py").write_text("from calc import convert as c\ndef handle(n):\n    return c(n)\n")
    (tmp_path / "calc.py").write_text("def adjust(n):\n    return n + 1\ndef convert(n):\n    return adjust(n) * 2\n")
    r = search_code(config(tmp_path), "flow failure", "test_flow.py::test_flow", 2000)
    hit = next(h for h in r.hits if h.symbol == "adjust")
    assert "static_dependency:3" in hit.reason
    assert "return n + 1" in hit.code
    assert r.hits[0].symbol == "test_flow"


def test_invoicing_search_finds_currency_region_without_sbfl(tmp_path):
    shutil.copytree(ROOT / "eval/cases/e6_invoicing", tmp_path / "case")
    r = search_code(config(tmp_path / "case"), "JPY invoice wrong total", "tests/test_invoice.py::test_invoice_jpy", 1200)
    assert any(h.path == "invoicing/currency.py" for h in r.hits)
    assert r.response_bytes == len(r.model_dump_json(exclude_none=True).encode()) <= 3600


def test_seen_ids_suppress_unchanged_but_not_changed_source(tmp_path):
    path = tmp_path / "calc.py"
    path.write_text("def convert(amount):\n    return amount * 10\n")
    cfg = config(tmp_path)
    first = search_code(cfg, "convert")
    ids = [h.id for h in first.hits]
    again = search_code(cfg, "convert", seen_ids=ids)
    assert again.status == "no_new_context" and not again.hits
    assert again.response_bytes < first.response_bytes
    path.write_text(path.read_text().replace("10", "20"))
    changed = search_code(cfg, "convert", seen_ids=ids)
    assert changed.hits and changed.hits[0].id not in ids
    assert "20" in changed.hits[0].code


def test_search_does_not_execute_and_does_not_follow_symlinks(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "safe.py").write_text("raise RuntimeError('must not execute')\ndef lookup():\n    return 1\n")
    private = tmp_path / "outside.py"
    private.write_text("def lookup_secret():\n    return 'hidden'\n")
    (root / "escape.py").symlink_to(private)
    r = search_code(config(root), "lookup")
    assert all(h.path != "escape.py" for h in r.hits)
    with pytest.raises(ValueError, match="escapes"):
        search_code(config(root), "lookup", "../outside.py::lookup_secret")


def test_budget_includes_escaping_and_large_context_is_labelled(tmp_path):
    (tmp_path / "big.py").write_text("def lookup():\n" + "    text = '\"quoted\\\\path'\n" * 100 + "    return text\n")
    r = search_code(config(tmp_path), "lookup", budget_tokens=400)
    assert r.response_bytes <= 1200
    assert all(h.truncated for h in r.hits)
    assert r.status in {"ok", "budget_too_small"}
    assert not r.hits or len(r.hits[0].code.splitlines()) <= 24


def test_syntax_errors_no_matches_and_input_limits(tmp_path):
    (tmp_path / "bad.py").write_text("def broken(\n")
    r = search_code(config(tmp_path), "unknown")
    assert r.status == "no_matches"
    assert "unreadable_or_unparseable_files_skipped" in r.limitations
    for kwargs in ({"budget_tokens": 10}, {"seen_ids": ["x"] * 101}):
        with pytest.raises(ValueError):
            search_code(config(tmp_path), "unknown", **kwargs)


def test_cli_search_returns_context(make_project):
    cfg = make_project("shop")
    p = subprocess.run([sys.executable, "-m", "faultline.cli", "search", "bulk threshold",
                        "--repo", cfg.repo_root, "--python", sys.executable], capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["hits"]


def test_exact_symbol_avoids_similarly_named_noise(tmp_path):
    (tmp_path / "records.py").write_text("\n".join(
        f"def normalize_record_{i}(x):\n    return x + {i}\n" for i in range(50)))
    r = search_code(config(tmp_path), "records.py::normalize_record_17")
    assert [h.symbol for h in r.hits] == ["normalize_record_17"]
    assert r.response_bytes < (tmp_path / "records.py").stat().st_size


def test_general_search_includes_callers_of_constructor(tmp_path):
    (tmp_path / "service.py").write_text(
        "class Encoder:\n"
        "    def __init__(self, payload):\n"
        "        self.payload = payload\n"
        "def dispatch(value):\n"
        "    return Encoder(value)\n")
    r = search_code(config(tmp_path), "payload", budget_tokens=2000)
    caller = next(h for h in r.hits if h.symbol == "dispatch")
    assert "static_caller" in caller.reason
