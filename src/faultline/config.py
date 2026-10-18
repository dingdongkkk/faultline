"""Load and validate FaultlineConfig; path and glob helpers shared by modules."""

from __future__ import annotations

import fnmatch
import hashlib
import os
from pathlib import Path

from .contracts import FaultlineConfig

# Options that change execution semantics in ways the attribution policy
# cannot account for (parallelism, reruns, competing coverage, early exit,
# test reordering by history, interactive debuggers).
_REJECTED_EXACT = {"-x", "--exitfirst", "--pdb", "--trace", "--lf", "--last-failed", "--ff",
                   "--failed-first", "--sw", "--stepwise", "--runxfail"}
_REJECTED_PREFIX = ("-n", "--numprocesses", "--dist", "--reruns", "--cov", "--maxfail", "--tx")


class ConfigError(ValueError):
    pass


def validate_pytest_args(args: list[str]) -> None:
    for i, a in enumerate(args):
        if a in _REJECTED_EXACT or any(a == p or a.startswith(p + "=") or (p == "-n" and a.startswith("-n"))
                                       for p in _REJECTED_PREFIX):
            raise ConfigError(f"pytest option not supported: {a}")
        if a == "-p" or a.startswith("-p"):
            value = args[i + 1] if a == "-p" and i + 1 < len(args) else a[2:]
            if not value.startswith("no:"):
                raise ConfigError(f"loading extra plugins via -p is not supported: {a} {value}".strip())


_SELECTION_WITH_VALUE = ("-k", "-m", "--deselect")


def without_selection_args(args: list[str]) -> list[str]:
    """Drop test-selection options for runs that name their test explicitly
    (observation / reproduction runs), so configured filters cannot deselect
    the target."""
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a in _SELECTION_WITH_VALUE:
            skip = True
            continue
        if any(a.startswith(p + "=") or (p in ("-k", "-m") and a.startswith(p) and len(a) > 2)
               for p in _SELECTION_WITH_VALUE):
            continue
        out.append(a)
    return out


def load_config(repo_root: str, python: str, **kwargs) -> FaultlineConfig:
    root = Path(repo_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ConfigError(f"repo_root is not a directory: {root}")
    py = Path(python).expanduser()
    if not py.is_absolute():
        if os.sep not in python:  # bare name such as "python3": look it up on PATH
            import shutil

            found = shutil.which(python)
            if not found:
                raise ConfigError(f"python interpreter not found on PATH: {python}")
            py = Path(found)
        else:
            # Relative to the current directory. abspath (not resolve) keeps a virtualenv's
            # python symlink, so the venv's packages stay visible.
            py = Path(os.path.abspath(py))
    if not os.access(py, os.X_OK):
        raise ConfigError(f"python is not executable: {py}")
    cfg = FaultlineConfig(repo_root=str(root), python=str(py), **kwargs)
    validate_pytest_args(cfg.pytest_args)
    return cfg


def state_dir(cfg: FaultlineConfig) -> Path:
    base = Path(cfg.state_dir) if cfg.state_dir else Path.home() / "Library" / "Caches" / "faultline"
    if not cfg.state_dir and os.name != "posix":  # pragma: no cover
        base = Path.home() / ".cache" / "faultline"
    elif not cfg.state_dir and not (Path.home() / "Library").is_dir():
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "faultline"
    repo_hash = hashlib.sha256(cfg.repo_root.encode()).hexdigest()[:16]
    d = base / repo_hash
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def match_glob(rel: str, pattern: str) -> bool:
    """fnmatch where a leading ``**/`` may also match zero directories.

    ``*`` crosses ``/`` (fnmatch semantics); that only makes exclusion more
    inclusive, which is the conservative direction for these globs.
    """
    if fnmatch.fnmatchcase(rel, pattern):
        return True
    if pattern.startswith("**/") and fnmatch.fnmatchcase(rel, pattern[3:]):
        return True
    if pattern.endswith("/**") and (rel == pattern[:-3] or rel.startswith(pattern[:-2])):
        return True
    return False


def is_excluded(cfg: FaultlineConfig, rel: str) -> bool:
    return any(match_glob(rel, p) for p in cfg.exclude_globs)


def is_test_path(cfg: FaultlineConfig, rel: str) -> bool:
    return any(match_glob(rel, p) for p in cfg.test_globs)


def is_app_path(cfg: FaultlineConfig, rel: str) -> bool:
    return rel.endswith(".py") and not is_excluded(cfg, rel) and not is_test_path(cfg, rel)


def to_rel(cfg: FaultlineConfig, path: str) -> str | None:
    """Repo-relative POSIX path for an absolute path, or None if outside the root.

    Uses realpath so symlinks that escape the root are treated as outside.
    """
    try:
        real = os.path.realpath(path)
    except OSError:
        return None
    root = cfg.repo_root
    if real == root or not real.startswith(root + os.sep):
        return None
    return Path(os.path.relpath(real, root)).as_posix()


def resolve_inside(cfg: FaultlineConfig, rel: str) -> Path:
    """Absolute path for a repo-relative path; raises if it escapes the root."""
    p = os.path.realpath(os.path.join(cfg.repo_root, rel))
    if not p.startswith(cfg.repo_root + os.sep):
        raise ConfigError(f"path escapes repository root: {rel}")
    return Path(p)
