"""
Compare duplicates found by random_tree_gen.py manifest vs fdup.py output.

This module provides:
- compare_manifest_vs_fdup(): assertion helper for pytest
- CLI: python -m tests.compare_duplicates <manifest.json> <fdup_json>
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Set, FrozenSet


def _normalize_path(path_str: str) -> str:
    """Normalize a path to resolved absolute form for comparison."""
    return str(Path(path_str).resolve())


def _load_manifest_groups(manifest_path: Path) -> Set[FrozenSet[str]]:
    """
    Load manifest.json and return duplicate groups as sets of absolute paths.
    
    Groups files by sha256; returns only groups with >1 file.
    """
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Group entries by sha256
    sha_groups: dict[str, list[str]] = {}
    for entry in data.get("entries", []):
        sha = entry["sha256"]
        # Use the absolute path from the manifest
        abs_path = _normalize_path(entry["path"])
        sha_groups.setdefault(sha, []).append(abs_path)
    
    # Keep only duplicates (groups with more than 1 file)
    result: Set[FrozenSet[str]] = set()
    for paths in sha_groups.values():
        if len(paths) > 1:
            result.add(frozenset(paths))
    
    return result


def _compute_md5(file_path: Path) -> str:
    """Compute MD5 hash of a file."""
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        md5.update(f.read())
    return md5.hexdigest()


def _load_fdup_groups(fdup_json_path: Path, validate_md5: bool = True) -> Set[FrozenSet[str]]:
    """
    Load fdup_duplicate_files.json and return duplicate groups as sets of absolute paths.
    
    Each key in duplicate_files is an MD5; each value is a list of file info dicts.
    
    Args:
        fdup_json_path: Path to the fdup JSON output
        validate_md5: If True, compute MD5 of each file and verify it matches the JSON
        
    Raises:
        AssertionError: If MD5 validation fails
    """
    with open(fdup_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    result: Set[FrozenSet[str]] = set()
    md5_errors: list[str] = []
    
    for group_md5, file_list in data.get("duplicate_files", {}).items():
        if len(file_list) > 1:
            paths = []
            for fi in file_list:
                full = Path(fi["path"]) / fi["filename"]
                full_path = _normalize_path(str(full))
                paths.append(full_path)
                
                if validate_md5:
                    # Validate that the entry's md5 matches the group key
                    entry_md5 = fi.get("md5", "")
                    if entry_md5 != group_md5:
                        md5_errors.append(
                            f"Entry MD5 mismatch for {fi['filename']}: "
                            f"entry md5={entry_md5!r} != group key={group_md5!r}"
                        )
                    
                    # Validate that the computed MD5 matches the entry's md5
                    computed_md5 = _compute_md5(Path(full_path))
                    if computed_md5 != entry_md5:
                        md5_errors.append(
                            f"Computed MD5 mismatch for {fi['filename']}: "
                            f"computed={computed_md5!r} != entry md5={entry_md5!r}"
                        )
            
            result.add(frozenset(paths))
    
    if md5_errors:
        raise AssertionError("MD5 validation failed:\n  " + "\n  ".join(md5_errors))
    
    return result


def compare_manifest_vs_fdup(manifest_path: Path, fdup_json_path: Path) -> None:
    """
    Compare duplicates from manifest.json (ground truth) vs fdup output.
    
    Raises AssertionError with details if they don't match.
    """
    manifest_groups = _load_manifest_groups(manifest_path)
    fdup_groups = _load_fdup_groups(fdup_json_path)
    
    missing = manifest_groups - fdup_groups  # in manifest but not found by fdup
    extra = fdup_groups - manifest_groups    # found by fdup but not in manifest
    
    if missing or extra:
        lines = ["Duplicate groups mismatch!"]
        if missing:
            lines.append(f"\nMissing from fdup ({len(missing)} group(s)):")
            for grp in sorted(missing, key=lambda g: sorted(g)[0]):
                lines.append(f"  {sorted(grp)}")
        if extra:
            lines.append(f"\nExtra in fdup ({len(extra)} group(s)):")
            for grp in sorted(extra, key=lambda g: sorted(g)[0]):
                lines.append(f"  {sorted(grp)}")
        raise AssertionError("\n".join(lines))


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: python -m tests.compare_duplicates <manifest.json> <fdup_json>", file=sys.stderr)
        return 1
    
    manifest_path = Path(sys.argv[1])
    fdup_json_path = Path(sys.argv[2])
    
    if not manifest_path.exists():
        print(f"Error: manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    if not fdup_json_path.exists():
        print(f"Error: fdup json not found: {fdup_json_path}", file=sys.stderr)
        return 1
    
    try:
        compare_manifest_vs_fdup(manifest_path, fdup_json_path)
        print("OK: Duplicate groups match.")
        return 0
    except AssertionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
