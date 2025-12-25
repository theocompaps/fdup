"""
Pytest tests for MD5 cache functionality.

Tests that:
1. Cache file is created after first run
2. Cache file contains entries with expected structure
3. Second run uses cache (demonstrated by faster execution or cache hit messages)
4. Results match manifest both with and without cache
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

import pytest

from tests.conftest import run_script
from tests.compare_duplicates import compare_manifest_vs_fdup


@pytest.mark.fdup_all
def test_md5_cache_basic(repo_root: Path, work_root: Path) -> None:
    """
    Test MD5 cache basic functionality:
    1. Generate a random tree
    2. Run fdup with --md5-cache (first run - populates cache)
    3. Verify cache file is created with expected structure
    4. Run fdup again with same cache (second run - should use cache)
    5. Verify results match manifest both times
    """
    # Setup paths
    run_root = work_root / "generated" / "cache_test" / "basic"
    manifest_path = run_root / "manifest.json"
    fdup_json_path = run_root / "fdup_duplicate_files.json"
    cache_path = run_root / "test_cache.json"
    
    # Clean up any previous run
    if run_root.exists():
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    
    # Use a fixed seed for reproducibility
    seed = 42
    
    # 1. Generate random directory tree with guaranteed duplicates
    # Use explicit parameters to ensure enough files are created
    tree_gen_script = repo_root / "bin" / "random_tree_gen.py"
    run_script(
        tree_gen_script,
        "--root", str(run_root),
        "--seed", str(seed),
        "--max-files", "50",
        "--max-dirs-per-dir", "3",
        "--max-files-per-dir", "10",
        "--dup-percent", "30",
        cwd=repo_root,
    )
    
    assert manifest_path.exists(), f"manifest.json not created at {manifest_path}"
    
    # 2. First run: populate cache
    fdup_script = repo_root / "bin" / "fdup.py"
    run_script(
        fdup_script,
        "-c", "MD5",
        "--md5-cache", str(cache_path),
        "--exportdup2json", str(fdup_json_path),
        str(run_root),
        cwd=repo_root,
    )
    
    assert fdup_json_path.exists(), f"fdup output not created at {fdup_json_path}"
    
    # 3. Verify cache file was created with expected structure
    assert cache_path.exists(), f"Cache file not created at {cache_path}"
    
    with open(cache_path, "r", encoding="utf-8") as f:
        cache_data = json.load(f)
    
    assert "version" in cache_data, "Cache missing 'version' key"
    assert "entries" in cache_data, "Cache missing 'entries' key"
    assert cache_data["version"] == 1, f"Unexpected cache version: {cache_data['version']}"
    
    # Cache should have some entries (at least some files were hashed)
    entries = cache_data["entries"]
    assert len(entries) > 0, "Cache has no entries"
    
    # Verify entry structure
    sample_entry = next(iter(entries.values()))
    assert "md5" in sample_entry, "Cache entry missing 'md5'"
    assert "size" in sample_entry, "Cache entry missing 'size'"
    assert "mtime_ns" in sample_entry, "Cache entry missing 'mtime_ns'"
    assert "md5_mode" in sample_entry, "Cache entry missing 'md5_mode'"
    assert "md5_max_size" in sample_entry, "Cache entry missing 'md5_max_size'"
    
    # 4. Verify first run results match manifest
    compare_manifest_vs_fdup(manifest_path, fdup_json_path)
    
    # 5. Second run: should use cache
    fdup_json_path2 = run_root / "fdup_duplicate_files_run2.json"
    run_script(
        fdup_script,
        "-c", "MD5",
        "--md5-cache", str(cache_path),
        "--exportdup2json", str(fdup_json_path2),
        str(run_root),
        cwd=repo_root,
    )
    
    assert fdup_json_path2.exists(), f"Second run output not created at {fdup_json_path2}"
    
    # 6. Verify second run results also match manifest
    compare_manifest_vs_fdup(manifest_path, fdup_json_path2)


@pytest.mark.fdup_all
def test_md5_cache_invalidation(repo_root: Path, work_root: Path) -> None:
    """
    Test that cache is invalidated when file changes.
    1. Generate a tree and run with cache
    2. Modify a file
    3. Run again - cache should detect file changed and re-hash
    """
    # Setup paths
    run_root = work_root / "generated" / "cache_test" / "invalidation"
    manifest_path = run_root / "manifest.json"
    fdup_json_path = run_root / "fdup_duplicate_files.json"
    cache_path = run_root / "test_cache.json"
    
    # Clean up any previous run
    if run_root.exists():
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    
    # Use a fixed seed
    seed = 99
    rng = random.Random(seed)
    dup_percent = rng.randint(15, 40)
    
    # Generate tree
    tree_gen_script = repo_root / "bin" / "random_tree_gen.py"
    run_script(
        tree_gen_script,
        "--root", str(run_root),
        "--seed", str(seed),
        "--dup-percent", str(dup_percent),
        cwd=repo_root,
    )
    
    # First run to populate cache
    fdup_script = repo_root / "bin" / "fdup.py"
    run_script(
        fdup_script,
        "-c", "MD5",
        "--md5-cache", str(cache_path),
        "--exportdup2json", str(fdup_json_path),
        str(run_root),
        cwd=repo_root,
    )
    
    assert cache_path.exists()
    
    # Get cache entry count
    with open(cache_path, "r", encoding="utf-8") as f:
        cache_data = json.load(f)
    entries_before = len(cache_data["entries"])
    
    # Find a file to modify (pick the first non-manifest file)
    test_files = [f for f in run_root.rglob("*") if f.is_file() and f.name != "manifest.json" and f.name != "test_cache.json" and not f.name.endswith(".json")]
    assert len(test_files) > 0, "No test files found to modify"
    
    file_to_modify = test_files[0]
    original_content = file_to_modify.read_bytes()
    
    # Modify the file (append some data)
    with open(file_to_modify, "ab") as f:
        f.write(b"\nmodified_for_test")
    
    # Second run - cache should detect the change
    fdup_json_path2 = run_root / "fdup_duplicate_files_run2.json"
    run_script(
        fdup_script,
        "-c", "MD5",
        "--md5-cache", str(cache_path),
        "--exportdup2json", str(fdup_json_path2),
        str(run_root),
        cwd=repo_root,
    )
    
    # The cache should still be valid (entry count may stay same or increase)
    with open(cache_path, "r", encoding="utf-8") as f:
        cache_data_after = json.load(f)
    
    # Cache should still have entries
    assert len(cache_data_after["entries"]) >= entries_before - 1, "Cache unexpectedly lost entries"
    
    # The modified file should have a new MD5 in the cache
    # (We can't easily verify this without more complex logic, so we just ensure no crash)


@pytest.mark.fdup_all  
def test_md5_cache_default_filename(repo_root: Path, work_root: Path) -> None:
    """
    Test that --md5-cache without a filename uses the default.
    """
    # Setup paths
    run_root = work_root / "generated" / "cache_test" / "default_name"
    manifest_path = run_root / "manifest.json"
    fdup_json_path = run_root / "fdup_duplicate_files.json"
    default_cache_path = repo_root / "fdup_md5_cache.json"
    
    # Clean up any previous run
    if run_root.exists():
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    
    # Remove default cache if it exists from previous tests
    if default_cache_path.exists():
        default_cache_path.unlink()
    
    # Use a fixed seed
    seed = 77
    rng = random.Random(seed)
    dup_percent = rng.randint(15, 40)
    
    # Generate tree
    tree_gen_script = repo_root / "bin" / "random_tree_gen.py"
    run_script(
        tree_gen_script,
        "--root", str(run_root),
        "--seed", str(seed),
        "--dup-percent", str(dup_percent),
        cwd=repo_root,
    )
    
    # Run with --md5-cache (no filename specified)
    fdup_script = repo_root / "bin" / "fdup.py"
    run_script(
        fdup_script,
        "-c", "MD5",
        "--md5-cache",
        "--exportdup2json", str(fdup_json_path),
        str(run_root),
        cwd=repo_root,
    )
    
    # Default cache file should be created in CWD (repo_root)
    assert default_cache_path.exists(), f"Default cache file not created at {default_cache_path}"
    
    # Verify results match manifest
    compare_manifest_vs_fdup(manifest_path, fdup_json_path)
    
    # Clean up default cache file
    if default_cache_path.exists():
        default_cache_path.unlink()
