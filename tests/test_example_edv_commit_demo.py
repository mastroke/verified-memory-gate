"""Smoke test for the runnable EDV commit example."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "edv_commit_demo.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("edv_commit_demo", EXAMPLE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_edv_commit_demo_main() -> None:
    demo = _load_demo()
    assert demo.main() == 0


def test_edv_commit_demo_subprocess() -> None:
    proc = subprocess.run(
        [sys.executable, str(EXAMPLE)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "COMMITTED" in proc.stdout
    assert "REJECTED" in proc.stdout
    assert "1 committed memory row" in proc.stdout
