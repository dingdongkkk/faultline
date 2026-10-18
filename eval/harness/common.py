"""Shared helpers for the evaluation harness. The private store path comes from
FAULTLINE_EVAL_PRIVATE (default ~/.faultline-eval-private) and is never copied
into the repository or into an agent-visible checkout."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "eval" / "cases"
PRIVATE = Path(os.environ.get("FAULTLINE_EVAL_PRIVATE", Path.home() / ".faultline-eval-private"))
PY = sys.executable


def manifest() -> dict:
    return json.loads((PRIVATE / "manifest.json").read_text())


def case(case_id: str) -> dict:
    return next(c for c in manifest()["cases"] if c["id"] == case_id)


def private_digest() -> str:
    """SHA-256 over every file in the private store (paths + contents), for public pre-registration."""
    h = hashlib.sha256()
    for p in sorted(PRIVATE.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(PRIVATE)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def case_source(case_id: str) -> Path:
    """Visible project for a case: eval/cases/<id>, or an external case_dir (large real repos)."""
    try:
        c = case(case_id)
    except (StopIteration, FileNotFoundError):
        return CASES / case_id
    return Path(c["case_dir"]) if c.get("case_dir") else CASES / case_id


def fresh_checkout(case_id: str, dest: Path) -> Path:
    shutil.copytree(case_source(case_id), dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    git = ["git", "-C", str(dest), "-c", "user.email=eval@local", "-c", "user.name=eval"]
    subprocess.run(["git", "init", "-q", str(dest)], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-qm", "case baseline"], check=True)
    return dest


def overlay(src_dir: Path, dest: Path) -> None:
    for p in src_dir.rglob("*"):
        if p.is_file():
            t = dest / p.relative_to(src_dir)
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, t)


def run_pytest(project: Path, extra: list[str] | None = None) -> dict:
    """Run pytest in a separate process; returns counts and failing node ids."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    out = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf", *(extra or [])],
                         cwd=project, capture_output=True, text=True, timeout=300, env=env)
    failed = [ln.split(" ", 2)[1] for ln in out.stdout.splitlines() if ln.startswith("FAILED ")]
    tail = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
    return {"exit": out.returncode, "failed": failed, "summary": tail}


def tests_digest(project: Path, tests_dir: str = "tests") -> str:
    h = hashlib.sha256()
    for p in sorted((project / tests_dir).rglob("*.py")):
        h.update(str(p.relative_to(project)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()
