"""
Pytest tests for fdup using randomly generated directory trees.

For each run (0..9):
1. Generate a random directory tree with duplicates using random_tree_gen.py
2. Run fdup.py with -c MD5 --exportdup2json to find duplicates
3. Compare manifest.json vs fdup output and assert they match
"""

from __future__ import annotations

import random
import shutil
from pathlib import Path

import pytest

from tests.conftest import run_script
from tests.compare_duplicates import compare_manifest_vs_fdup


@pytest.mark.fdup_all
@pytest.mark.parametrize("run_idx", range(10))
def test_random_generated_default(run_idx: int, repo_root: Path, work_root: Path) -> None:
    """
    Test fdup against a randomly generated directory tree.
    
    Args:
        run_idx: Run index 0..9, used as the seed
        repo_root: Repository root directory (fixture)
        work_root: tests/tests.work directory (fixture)
    """
    # Determine dup_percent deterministically from seed (15..40)
    rng = random.Random(run_idx)
    dup_percent = rng.randint(15, 40)
    
    # Setup paths
    run_root = work_root / "generated" / "default" / f"run{run_idx}"
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
        "--seed", str(run_idx),
        "--dup-percent", str(dup_percent),
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
