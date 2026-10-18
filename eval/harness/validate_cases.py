"""Validate the preselected cases without any agent or Faultline run.

For each case: the visible failing test fails and is the only visible failure;
hidden tests fail on the buggy code; the reference fix passes visible + hidden;
the regression trap (if any) passes visible but fails hidden.
Prints only verdicts and counts - never hidden test content."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PRIVATE, fresh_checkout, manifest, overlay, private_digest, run_pytest  # noqa: E402


def check(c: dict) -> dict:
    cdir = PRIVATE / "cases" / c["id"]
    res = {"id": c["id"], "category": c["category"]}
    with tempfile.TemporaryDirectory() as t:
        buggy = fresh_checkout(c["id"], Path(t) / "buggy")
        v = run_pytest(buggy)
        res["visible_only_target_fails"] = v["failed"] == [c["visible_failing"]]
        td = c.get("tests_dir", "tests")
        overlay(cdir / "hidden", buggy / td)
        h = run_pytest(buggy)
        has_hidden = any((cdir / "hidden").rglob("*.py"))
        res["hidden_fail_on_bug"] = any("hidden" in f for f in h["failed"]) if has_hidden else "n/a (no hidden tests)"
        fixed = fresh_checkout(c["id"], Path(t) / "fixed")
        overlay(cdir / "reference", fixed)
        overlay(cdir / "hidden", fixed / td)
        r = run_pytest(fixed)
        res["reference_passes_all"] = r["exit"] == 0 and not r["failed"]
        if "trap" in c:
            trap = fresh_checkout(c["id"], Path(t) / "trap")
            overlay(cdir / "trap", trap)
            tv = run_pytest(trap)
            overlay(cdir / "hidden", trap / td)
            th = run_pytest(trap)
            res["trap_passes_visible"] = tv["exit"] == 0
            res["trap_fails_hidden"] = bool(th["failed"])
    res["ok"] = all(v for k, v in res.items() if k not in ("id", "category"))
    return res


if __name__ == "__main__":
    results = [check(c) for c in manifest()["cases"]]
    for r in results:
        print(json.dumps(r))
    print("private_store_sha256", private_digest())
    sys.exit(0 if all(r["ok"] for r in results) else 1)
