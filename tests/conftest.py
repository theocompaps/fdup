"""
Pytest configuration and shared fixtures for fdup tests.
"""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Return the repository root directory."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def work_root(repo_root: Path) -> Path:
    """Return the tests.work directory (created if missing)."""
    work = repo_root / "tests" / "tests.work"
    work.mkdir(parents=True, exist_ok=True)
    return work


def run_script(script_path: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """
    Run a Python script using the current interpreter.
    
    Args:
        script_path: Path to the .py script
        *args: Command-line arguments to pass
        cwd: Working directory (defaults to repo root)
    
    Returns:
        subprocess.CompletedProcess with stdout/stderr captured
    
    Raises:
        subprocess.CalledProcessError on non-zero exit
    """
    cmd = [sys.executable, str(script_path), *args]
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            cmd,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result
