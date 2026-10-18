import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Expose scripts/export_schemas.py as an importable module for the schema-sync test.
_spec = importlib.util.spec_from_file_location("scripts_export", ROOT / "scripts" / "export_schemas.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules["scripts_export"] = _mod

import shutil  # noqa: E402

import pytest  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture
def make_project(tmp_path):
    """Copy a fixture project into tmp and return a validated config for it."""
    from faultline.config import load_config

    def _make(name: str, **kwargs):
        dest = tmp_path / name
        shutil.copytree(FIXTURES / name, dest, ignore=shutil.ignore_patterns("__pycache__"))
        kwargs.setdefault("state_dir", str(tmp_path / "state"))
        return load_config(str(dest), sys.executable, **kwargs)

    return _make
