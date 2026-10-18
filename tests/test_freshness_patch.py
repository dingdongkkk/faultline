"""M4: fingerprint/rehash, freshness of evidence, expiry, truncation labels,
response packing at the minimum budget, conservative patch checking."""

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from faultline import fingerprint as fpmod
from faultline.budget import BudgetError, Packer
from faultline.contracts import CheckPatchResponse, EffectiveScope, ExpandResponse, Freshness
from faultline.evidence import EvidenceStore, baseline_manifest, expand
from faultline.execution import run_baseline
from faultline.patch import check_patch

TARGET = "tests/test_a.py::test_two"


def _investigation(cfg, inv="inv_t1"):
    store = EvidenceStore(cfg)
    snap = fpmod.compute(cfg)
    b = run_baseline(cfg, TARGET, timeout_s=60)
    store.create(inv, baseline_manifest(inv, TARGET, b, snap, supported=True))
    return store, snap, b


# ------------------------------------------------------------- fingerprint


def test_edit_preserving_size_and_mtime_is_detected(make_project):
    cfg = make_project("ochiai_basic")
    before = fpmod.compute(cfg)
    app = Path(cfg.repo_root) / "app.py"
    st = app.stat()
    src = app.read_text()
    app.write_text(src.replace("a * 2", "a * 3"))  # same length
    os.utime(app, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert app.stat().st_size == st.st_size and app.stat().st_mtime_ns == st.st_mtime_ns
    after = fpmod.compute(cfg)
    d = fpmod.diff(before.files, before.components, False, after)
    assert d.changed == ["app.py"] and before.fp.fingerprint_id != after.fp.fingerprint_id


def test_git_uncommitted_and_untracked_files_count_but_ignored_do_not(make_project):
    cfg = make_project("ochiai_basic")
    root = cfg.repo_root
    git = ["git", "-C", root, "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", root], check=True)
    Path(root, ".gitignore").write_text("ignored.dat\n")
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-qm", "x"], check=True)
    a = fpmod.compute(cfg)
    Path(root, "app.py").write_text(Path(root, "app.py").read_text() + "\n# uncommitted\n")
    Path(root, "new_module.py").write_text("y = 1\n")
    Path(root, "ignored.dat").write_text("z")
    b = fpmod.compute(cfg)
    d = fpmod.diff(a.files, a.components, False, b)
    assert d.changed == ["app.py"] and d.added == ["new_module.py"]
    assert "ignored.dat" not in b.files


def test_declared_env_is_fingerprinted_without_storing_values(make_project, monkeypatch):
    monkeypatch.setenv("FL_SECRET_SETTING", "s3cr3t-value")
    cfg = make_project("ochiai_basic", declared_env=["FL_SECRET_SETTING"])
    a = fpmod.compute(cfg)
    assert "s3cr3t-value" not in json.dumps(a.fp.model_dump()) + json.dumps(a.components)
    monkeypatch.setenv("FL_SECRET_SETTING", "other")
    b = fpmod.compute(cfg)
    assert fpmod.diff(a.files, a.components, False, b).components == ["declared_env"]


def test_editable_dependency_outside_repo_marks_partial(make_project, tmp_path, monkeypatch):
    site = tmp_path / "fake_site"
    dist = site / "outside_pkg-1.0.dist-info"
    dist.mkdir(parents=True)
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: outside-pkg\nVersion: 1.0\n")
    (dist / "direct_url.json").write_text(json.dumps({"url": f"file://{tmp_path}/elsewhere",
                                                      "dir_info": {"editable": True}}))
    monkeypatch.setenv("PYTHONPATH", str(site))
    cfg = make_project("ochiai_basic")
    s = fpmod.compute(cfg)
    assert s.fp.partial and "editable_outside_repo:outside-pkg" in s.fp.partial_reasons


# ------------------------------------------------------------- evidence


def test_expand_fresh_then_stale_on_source_and_environment(make_project, monkeypatch):
    monkeypatch.setenv("FL_MODE", "a")
    cfg = make_project("ochiai_basic", declared_env=["FL_MODE"])
    store, snap, _ = _investigation(cfg)
    store.put("inv_t1", "S1", "excerpt", {"text": "x"},
              sources=[{"path": "app.py", "sha256": snap.files["app.py"], "size": 1}],
              truncated_at_capture=False, fingerprint_id=snap.fp.fingerprint_id)
    store.put("inv_t1", "O1", "observation", {"v": 1}, sources=[], truncated_at_capture=True,
              fingerprint_id=snap.fp.fingerprint_id)
    r = expand(cfg, store, "inv_t1", "S1")
    assert r.freshness is Freshness.FRESH and r.content == {"text": "x"}
    # An unrelated file change makes *runtime* evidence stale but not the excerpt.
    Path(cfg.repo_root, "tests", "test_a.py").write_text(Path(cfg.repo_root, "tests", "test_a.py").read_text() + "\n")
    assert expand(cfg, store, "inv_t1", "S1").freshness is Freshness.FRESH
    o = expand(cfg, store, "inv_t1", "O1")
    assert o.freshness is Freshness.STALE and o.stale_paths == ["tests/test_a.py"] and o.irrecoverably_truncated
    # Environment component change makes everything stale.
    monkeypatch.setenv("FL_MODE", "b")
    s = expand(cfg, store, "inv_t1", "S1")
    assert s.freshness is Freshness.STALE and s.stale_components == ["declared_env"]


def test_expired_evidence_is_labelled_and_tombstoned(make_project):
    cfg = make_project("ochiai_basic")
    store, snap, _ = _investigation(cfg)
    store.put("inv_t1", "O1", "observation", {"v": 1}, sources=[], truncated_at_capture=False,
              fingerprint_id=snap.fp.fingerprint_id)
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="seconds")
    store.update_manifest("inv_t1", expires_at=past)
    r = expand(cfg, store, "inv_t1", "O1")
    assert r.freshness is Freshness.EXPIRED and r.content is None
    m = store.load_manifest("inv_t1")
    assert m["expired"] and "files" not in m


def test_expand_chunks_large_items_with_cursor(make_project):
    cfg = make_project("ochiai_basic")
    store, snap, _ = _investigation(cfg)
    payload = {"values": ["v" * 50 for _ in range(200)]}
    store.put("inv_t1", "O9", "observation", payload, sources=[], truncated_at_capture=False,
              fingerprint_id=snap.fp.fingerprint_id)
    chunks, cursor = [], None
    for _ in range(50):
        r = expand(cfg, store, "inv_t1", "O9", budget_tokens=300, cursor=cursor)
        assert r.metrics.response_bytes <= 900
        chunks.append(r.content["chunk"])
        cursor = r.next_cursor
        if cursor is None:
            break
    assert json.loads("".join(chunks)) == payload and len(chunks) > 1


def test_store_cap_refuses_items(make_project):
    cfg = make_project("ochiai_basic")
    cfg = cfg.model_copy(update={"limits": cfg.limits.model_copy(update={"investigation_store_max_bytes": 600})})
    store = EvidenceStore(cfg)
    store.create("inv_c", {"x": 1})
    assert store.put("inv_c", "A1", "observation", {"a": "x" * 100}, sources=[], truncated_at_capture=False,
                     fingerprint_id="f")
    assert not store.put("inv_c", "A2", "observation", {"a": "x" * 600}, sources=[], truncated_at_capture=False,
                         fingerprint_id="f")


def test_ids_cannot_traverse_paths(make_project):
    store = EvidenceStore(make_project("ochiai_basic"))
    with pytest.raises(KeyError):
        store.load_manifest("../../etc")


# ------------------------------------------------------------- packing


def test_packer_rejects_oversized_skeleton_and_respects_cap():
    base = {"investigation_id": "i", "evidence_id": "e", "freshness": "fresh", "stale_paths": ["p" * 3000],
            "stale_components": [], "irrecoverably_truncated": False,
            "metrics": {"response_bytes": 0, "response_tokens_estimate": 0, "budget_tokens": 600, "wall_ms": 0,
                        "rounds": 0, "planner_retries": 0, "planner_fallbacks": 0}}
    with pytest.raises(BudgetError):
        Packer(ExpandResponse, base, 600)
    base["stale_paths"] = []
    out = Packer(ExpandResponse, base, 600).finalize()
    assert out.metrics.response_bytes == len(out.model_dump_json(exclude_none=True).encode()) <= 1800


# ------------------------------------------------------------- patch checking


def test_patch_default_is_full_and_fresh(make_project):
    cfg = make_project("ochiai_basic")
    store, _, _ = _investigation(cfg)
    r = check_patch(cfg, store, "inv_t1")
    assert r.mode_requested.value == "full" and r.effective_scope is EffectiveScope.FULL
    assert r.status == "failed" and r.previously_failing_now == {TARGET: "failed"}
    assert not r.full_regression_verified and r.selected_count == 4
    # fix the bug -> full suite passes -> full regression verified (configured suite only)
    app = Path(cfg.repo_root, "app.py")
    app.write_text(app.read_text().replace("return a * 2", "return a + 2"))
    r2 = check_patch(cfg, store, "inv_t1")
    assert r2.status == "passed" and r2.full_regression_verified
    assert r2.previously_failing_now == {TARGET: "passed"}
    assert any(lim.code == "configured_suite_only" for lim in r2.limitations)
    assert r2.metrics.response_bytes <= 1500 * 3


def test_affected_selects_call_coverage_and_never_claims_full(make_project):
    cfg = make_project("ochiai_basic")
    store, _, _ = _investigation(cfg)
    m = store.load_manifest("inv_t1")
    # Make app.py look call-only (the fixture also has import-time lines, which escalate).
    m["file_cov"]["app.py"]["unattributed"] = False
    m["file_cov"]["app.py"]["setup_teardown"] = False
    store.update_manifest("inv_t1", file_cov=m["file_cov"])
    app = Path(cfg.repo_root, "app.py")
    app.write_text(app.read_text().replace("return a * 2", "return a + 2"))
    r = check_patch(cfg, store, "inv_t1", mode="affected")
    assert r.effective_scope is EffectiveScope.AFFECTED and r.escalation_reasons == []
    sel = {s.nodeid: s.reasons for s in r.selected}
    assert sel[TARGET][0] == "previously_non_passing" and "covers_changed:app.py" in sel[TARGET]
    assert set(sel) == {TARGET, "tests/test_a.py::test_one", "tests/test_a.py::test_p[1]", "tests/test_a.py::test_p[3]"}
    assert r.status == "passed" and not r.full_regression_verified
    assert {lim.code for lim in r.limitations} >= {"affected_scope_not_full_regression", "selection_residual_risk"}


@pytest.mark.parametrize("change, reason_prefix", [
    ("import_time", "import_time_coverage:app.py"),
    ("new_file", "added:extra.py"),
    ("config", "test_or_config_changed:pytest.ini"),
    ("test", "test_or_config_changed:tests/test_a.py"),
    ("env", "environment_changed:declared_env"),
])
def test_affected_escalates_to_full(make_project, monkeypatch, change, reason_prefix):
    monkeypatch.setenv("FL_MODE", "a")
    cfg = make_project("ochiai_basic", declared_env=["FL_MODE"])
    store, _, _ = _investigation(cfg)
    root = Path(cfg.repo_root)
    if change == "import_time":
        (root / "app.py").write_text((root / "app.py").read_text().replace("return a * 2", "return a + 2"))
    elif change == "new_file":
        (root / "extra.py").write_text("x = 1\n")
    elif change == "config":
        (root / "pytest.ini").write_text((root / "pytest.ini").read_text() + "\n")
    elif change == "test":
        (root / "tests" / "test_a.py").write_text((root / "tests" / "test_a.py").read_text() + "\n")
    elif change == "env":
        monkeypatch.setenv("FL_MODE", "b")
    r = check_patch(cfg, store, "inv_t1", mode="affected")
    assert r.effective_scope is EffectiveScope.AFFECTED_ESCALATED_TO_FULL
    assert reason_prefix in r.escalation_reasons
    assert r.selected_count == 4


def test_patch_on_expired_baseline_runs_full(make_project):
    cfg = make_project("ochiai_basic")
    store, _, _ = _investigation(cfg)
    store.expire("inv_t1")
    r = check_patch(cfg, store, "inv_t1", mode="affected")
    assert r.effective_scope is EffectiveScope.AFFECTED_ESCALATED_TO_FULL and "baseline_expired" in r.escalation_reasons
    assert isinstance(r, CheckPatchResponse)
