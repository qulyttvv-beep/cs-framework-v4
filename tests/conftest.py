"""Shared pytest fixtures and import shims for the CS Framework test suite.

Importing ``cs`` runs module-level setup (it resolves a data directory and
creates it), so we pin ``CS_HOME`` to a throwaway temp dir *before* the import
and disable ANSI color for stable output.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Repo root on sys.path so `import cs` works from anywhere.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Isolate the framework's data dir and turn off color BEFORE cs is imported.
_TEST_HOME = Path(tempfile.mkdtemp(prefix="cs-tests-"))
os.environ.setdefault("CS_HOME", str(_TEST_HOME))
os.environ.setdefault("CS_NO_COLOR", "1")
# no network from background warm-ups (free-model probe, catalog refresh)
os.environ.setdefault("SPARKX_OFFLINE", "1")

import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def cs_script(repo_root: Path) -> Path:
    return repo_root / "cs.py"


@pytest.fixture
def run_cli(cs_script: Path, tmp_path: Path):
    """Run `python cs.py <args>` in an isolated CS_HOME, headless (no TTY)."""
    def _run(*args: str, timeout: int = 120, home: Path | None = None):
        env = dict(os.environ)
        env["CS_HOME"] = str(home or (tmp_path / "home"))
        env["CS_NO_COLOR"] = "1"
        return subprocess.run(
            [sys.executable, str(cs_script), *args],
            capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL, env=env,
        )
    return _run
