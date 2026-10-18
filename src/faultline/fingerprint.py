"""Workspace fingerprinting.

Content is fully rehashed at every call (no stat cache): this is used at
correctness boundaries (before/after child runs, expand_evidence,
check_patch), where size/mtime-preserving edits must still be detected.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import is_excluded, state_dir
from .contracts import FaultlineConfig, WorkspaceFingerprint

CONFIG_NAMES = {"pyproject.toml", "setup.cfg", "setup.py", "pytest.ini", "tox.ini", "conftest.py"}
ENV_COMPONENTS = ("config", "interpreter", "dependencies", "declared_env")

_ENV_SCRIPT = r"""
import json, sys, importlib.metadata as md
dists = []
for d in md.distributions():
    try:
        name = d.metadata["Name"] or "?"
    except Exception:
        name = "?"
    editable = None
    try:
        raw = d.read_text("direct_url.json")
        if raw:
            info = json.loads(raw)
            if (info.get("dir_info") or {}).get("editable"):
                editable = info.get("url", "")
    except Exception:
        pass
    dists.append([name, d.version, editable])
dists.sort(key=lambda x: (str(x[0]).lower(), str(x[1])))
print(json.dumps({"executable": sys.executable, "version": sys.version, "prefix": sys.prefix,
                  "dists": dists}))
"""


@dataclass
class Snapshot:
    """A fingerprint plus the per-file hashes it was computed from."""

    fp: WorkspaceFingerprint
    files: dict[str, str]  # rel -> sha256
    components: dict[str, str]  # component -> digest


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def list_files(cfg: FaultlineConfig) -> list[str]:
    root = cfg.repo_root
    rels: list[str] | None = None
    if (Path(root) / ".git").exists():
        try:
            out = subprocess.run(["git", "-C", root, "ls-files", "-co", "--exclude-standard", "-z"],
                                 capture_output=True, timeout=30, check=True).stdout
            rels = [p for p in out.decode("utf-8", "replace").split("\0") if p]
        except (OSError, subprocess.SubprocessError):
            rels = None
    if rels is None:
        rels = []
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            rel_dir = "" if rel_dir == "." else Path(rel_dir).as_posix() + "/"
            dirnames[:] = [d for d in dirnames if not is_excluded(cfg, rel_dir + d + "/x")
                           and not os.path.islink(os.path.join(dirpath, d))]
            rels.extend(rel_dir + f for f in filenames)
    return sorted(r for r in rels if not is_excluded(cfg, r))


def _hmac_key(cfg: FaultlineConfig) -> bytes:
    p = state_dir(cfg) / "hmac.key"
    if not p.exists():
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(secrets.token_bytes(32))
    return p.read_bytes()


def env_info(cfg: FaultlineConfig) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONSTARTUP",)}
    try:
        out = subprocess.run([cfg.python, "-c", _ENV_SCRIPT], capture_output=True, timeout=60,
                             cwd=cfg.repo_root, env=env, check=True).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return {"error": f"{type(e).__name__}"}


def compute(cfg: FaultlineConfig) -> Snapshot:
    lim = cfg.limits
    partial: list[str] = []
    files: dict[str, str] = {}
    total = 0
    rels = list_files(cfg)
    if len(rels) > lim.fingerprint_max_files:
        partial.append(f"file_cap:{len(rels)}>{lim.fingerprint_max_files}")
        rels = rels[: lim.fingerprint_max_files]
    for rel in rels:
        path = os.path.join(cfg.repo_root, rel)
        if os.path.islink(path) and not os.path.realpath(path).startswith(cfg.repo_root + os.sep):
            files[rel] = "symlink-outside:" + _sha(os.readlink(path).encode())
            continue
        try:
            data = Path(path).read_bytes()
        except FileNotFoundError:
            continue  # deleted between listing and hashing; absent from the map
        except OSError as e:
            files[rel] = f"unreadable:{type(e).__name__}"
            partial.append(f"unreadable:{rel}")
            continue
        total += len(data)
        if total > lim.fingerprint_max_total_bytes:
            partial.append("byte_cap")
            break
        files[rel] = _sha(data)
    for extra in cfg.extra_inputs:
        p = Path(extra).expanduser()
        try:
            files["@extra:" + str(p)] = _sha(p.read_bytes())
        except OSError:
            files["@extra:" + str(p)] = "missing"

    config_items = sorted((r, h) for r, h in files.items() if r.rsplit("/", 1)[-1] in CONFIG_NAMES)
    info = env_info(cfg)
    if "error" in info:
        partial.append("environment_unreadable")
    editable_outside = []
    for name, _ver, url in info.get("dists", []):
        if url:
            loc = url[7:] if url.startswith("file://") else url
            real = os.path.realpath(loc)
            if not (real == cfg.repo_root or real.startswith(cfg.repo_root + os.sep)):
                editable_outside.append(str(name))
    if editable_outside:
        partial.extend(f"editable_outside_repo:{n}" for n in editable_outside)

    key = _hmac_key(cfg)
    declared = json.dumps(sorted((n, os.environ.get(n)) for n in cfg.declared_env))
    components = {
        "files": _sha(json.dumps(sorted(files.items())).encode()),
        "config": _sha(json.dumps(config_items).encode()),
        "interpreter": _sha(json.dumps([info.get("executable"), info.get("version"), info.get("prefix")]).encode()),
        "dependencies": _sha(json.dumps(info.get("dists")).encode()),
        "declared_env": hmac.new(key, declared.encode(), hashlib.sha256).hexdigest(),
    }
    fp_id = "fp_" + _sha(json.dumps(components, sort_keys=True).encode())[:16]
    fp = WorkspaceFingerprint(
        fingerprint_id=fp_id, files_digest=components["files"], file_count=len(files),
        config_digest=components["config"], interpreter_digest=components["interpreter"],
        dependencies_digest=components["dependencies"], declared_env_digest=components["declared_env"],
        editable_outside_repo=editable_outside, partial=bool(partial), partial_reasons=partial,
        captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    return Snapshot(fp=fp, files=files, components=components)


@dataclass(frozen=True)
class Diff:
    changed: list[str]
    added: list[str]
    deleted: list[str]
    components: list[str]  # environment components that changed
    partial: bool

    @property
    def any(self) -> bool:
        return bool(self.changed or self.added or self.deleted or self.components)


def diff(old_files: dict[str, str], old_components: dict[str, str], old_partial: bool, new: Snapshot) -> Diff:
    changed = sorted(p for p in old_files.keys() & new.files.keys() if old_files[p] != new.files[p])
    added = sorted(new.files.keys() - old_files.keys())
    deleted = sorted(old_files.keys() - new.files.keys())
    comps = [c for c in ENV_COMPONENTS if old_components.get(c) != new.components.get(c)]
    return Diff(changed, added, deleted, comps, old_partial or new.fp.partial)
