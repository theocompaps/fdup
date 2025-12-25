"""
Pytest tests for fdup using randomly generated directory trees.

Suites:
- small: 10 tests, 500-1000 files, smaller file sizes
- medium: 10 tests, 2000-4000 files, larger file sizes (marked slow)
- large: 10 tests, 5000-10000 files, largest file sizes (marked slow)

Each test:
1. Generates a random directory tree with duplicates using random_tree_gen.py
2. Runs fdup.py with -c MD5 --exportdup2json to find duplicates
3. Compares manifest.json vs fdup output and asserts they match
"""

from __future__ import annotations

import os
import random
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import pytest

from tests.conftest import run_script
from tests.compare_duplicates import compare_manifest_vs_fdup


# Base seed for reproducibility (can be overridden via environment variable)
BASE_SEED = int(os.environ.get("FDUP_TEST_SEED", "12345"))


@dataclass
class SuiteConfig:
    """Configuration for a test suite."""
    name: str
    max_files_range: Tuple[int, int]
    max_dirs_per_dir_range: Tuple[int, int]
    max_files_per_dir_range: Tuple[int, int]
    max_txt_bytes_range: Tuple[int, int]
    max_bin_bytes_range: Tuple[int, int]
    txt_ratio: float
    dup_percent_range: Tuple[int, int]
    dup_same_name_percent_range: Tuple[int, int]


SMALL_CONFIG = SuiteConfig(
    name="small",
    max_files_range=(500, 1000),
    max_dirs_per_dir_range=(1, 10),
    max_files_per_dir_range=(1, 10),
    max_txt_bytes_range=(128, 3145728),
    max_bin_bytes_range=(128, 3145728),
    txt_ratio=0.6,
    dup_percent_range=(5, 30),
    dup_same_name_percent_range=(5, 10),
)

MEDIUM_CONFIG = SuiteConfig(
    name="medium",
    max_files_range=(2000, 4000),
    max_dirs_per_dir_range=(5, 20),
    max_files_per_dir_range=(5, 20),
    max_txt_bytes_range=(1024, 10485760),
    max_bin_bytes_range=(1024, 10485760),
    txt_ratio=0.6,
    dup_percent_range=(10, 40),
    dup_same_name_percent_range=(5, 10),
)

LARGE_CONFIG = SuiteConfig(
    name="large",
    max_files_range=(5000, 10000),
    max_dirs_per_dir_range=(10, 30),
    max_files_per_dir_range=(10, 30),
    max_txt_bytes_range=(4096, 10485760),
    max_bin_bytes_range=(4096, 10485760),
    txt_ratio=0.6,
    dup_percent_range=(30, 50),
    dup_same_name_percent_range=(5, 10),
)


def _get_reproducible_seed(suite_name: str, run_idx: int) -> int:
    """Generate a reproducible seed for a test run."""
    return hash((suite_name, run_idx, BASE_SEED)) & 0x7FFFFFFF


def _run_suite_test(
    config: SuiteConfig,
    run_idx: int,
    repo_root: Path,
    work_root: Path,
) -> None:
    """
    Run a single test from a suite.
    
    Args:
        config: Suite configuration
        run_idx: Run index (0..9)
        repo_root: Repository root directory
        work_root: tests/tests.work directory
    """
    # Get reproducible seed and RNG
    seed = _get_reproducible_seed(config.name, run_idx)
    rng = random.Random(seed)
    
    # Generate all "random" parameters from RNG
    max_files = rng.randint(*config.max_files_range)
    max_dirs_per_dir = rng.randint(*config.max_dirs_per_dir_range)
    max_files_per_dir = rng.randint(*config.max_files_per_dir_range)
    max_txt_bytes = rng.randint(*config.max_txt_bytes_range)
    max_bin_bytes = rng.randint(*config.max_bin_bytes_range)
    dup_percent = rng.randint(*config.dup_percent_range)
    dup_same_name_percent = rng.randint(*config.dup_same_name_percent_range)
    
    # Setup paths
    run_root = work_root / "generated" / config.name / f"run{run_idx}"
    manifest_path = run_root / "manifest.json"
    fdup_json_path = run_root / "fdup_duplicate_files.json"
    
    # Clean up any previous run
    if run_root.exists():
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    
    # 1. Generate random directory tree
    tree_gen_script = repo_root / "bin" / "random_tree_gen.py"
    run_script(
        tree_gen_script,
        "--root", str(run_root),
        "--seed", str(seed),
        "--max-files", str(max_files),
        "--max-dirs-per-dir", str(max_dirs_per_dir),
        "--max-files-per-dir", str(max_files_per_dir),
        "--max-txt-bytes", str(max_txt_bytes),
        "--max-bin-bytes", str(max_bin_bytes),
        "--txt-ratio", str(config.txt_ratio),
        "--dup-percent", str(dup_percent),
        "--dup-same-name-percent", str(dup_same_name_percent),
        cwd=repo_root,
    )
    
    # Verify manifest was created
    assert manifest_path.exists(), f"manifest.json not created at {manifest_path}"
    
    # 2. Run fdup to find duplicates
    fdup_script = repo_root / "bin" / "fdup.py"
    run_script(
        fdup_script,
        "-c", "MD5",
        "--exportdup2json", str(fdup_json_path),
        str(run_root),
        cwd=repo_root,
    )
    
    # Verify fdup output was created
    assert fdup_json_path.exists(), f"fdup output not created at {fdup_json_path}"
    
    # 3. Compare manifest vs fdup output
    compare_manifest_vs_fdup(manifest_path, fdup_json_path)


# ============================================================================
# Small suite tests
# ============================================================================

@pytest.mark.fdup_all
@pytest.mark.parametrize("run_idx", range(10))
def test_random_generated_small(run_idx: int, repo_root: Path, work_root: Path) -> None:
    """
    Test fdup against a randomly generated 'small' directory tree.
    
    Parameters:
        - max-files: 500-1000
        - max-dirs-per-dir: 1-10
        - max-files-per-dir: 1-10
        - max-txt-bytes: 128-3145728
        - max-bin-bytes: 128-3145728
        - txt-ratio: 0.6
        - dup-percent: 5-30
        - dup-same-name-percent: 5-10
    """
    _run_suite_test(SMALL_CONFIG, run_idx, repo_root, work_root)


# ============================================================================
# Medium suite tests (slow)
# ============================================================================

@pytest.mark.fdup_all
@pytest.mark.slow
@pytest.mark.parametrize("run_idx", range(10))
def test_random_generated_medium(run_idx: int, repo_root: Path, work_root: Path) -> None:
    """
    Test fdup against a randomly generated 'medium' directory tree.
    
    Parameters:
        - max-files: 2000-4000
        - max-dirs-per-dir: 5-20
        - max-files-per-dir: 5-20
        - max-txt-bytes: 1024-10485760
        - max-bin-bytes: 1024-10485760
        - txt-ratio: 0.6
        - dup-percent: 10-40
        - dup-same-name-percent: 5-10
    """
    _run_suite_test(MEDIUM_CONFIG, run_idx, repo_root, work_root)


# ============================================================================
# Large suite tests (slow)
# ============================================================================

@pytest.mark.fdup_all
@pytest.mark.slow
@pytest.mark.parametrize("run_idx", range(10))
def test_random_generated_large(run_idx: int, repo_root: Path, work_root: Path) -> None:
    """
    Test fdup against a randomly generated 'large' directory tree.
    
    Parameters:
        - max-files: 5000-10000
        - max-dirs-per-dir: 10-30
        - max-files-per-dir: 10-30
        - max-txt-bytes: 4096-10485760
        - max-bin-bytes: 4096-10485760
        - txt-ratio: 0.6
        - dup-percent: 30-50
        - dup-same-name-percent: 5-10
    """
    _run_suite_test(LARGE_CONFIG, run_idx, repo_root, work_root)
