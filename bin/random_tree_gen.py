#!/usr/bin/env python3
"""
random_tree_gen.py

Adds:
- --dup-percent 0..99 : percent of files that duplicate some other file's contents
- --dup-same-name-percent 0..100 : among duplicates, percent that try to reuse the original basename
  (same name allowed only if in a different directory; if collision in same dir, fallback to random name)

Other features:
- Per-type max size: --max-txt-bytes, --max-bin-bytes
- Global max total bytes: --max-total-bytes
- Biased file sizes: --size-bias {uniform,small_heavy} and --size-skew
- Manifest JSON: --manifest (defaults to <root>/manifest.json)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import string
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


SizeBias = Literal["uniform", "small_heavy"]


@dataclass
class ManifestEntry:
    path: str
    relpath: str
    kind: str               # "txt" or "bin"
    filename: str
    size_bytes: int
    sha256: str
    is_duplicate: bool
    duplicate_of_sha256: str | None
    duplicate_of_name: str | None


def rand_name(rng: random.Random, prefix: str, n: int = 8) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return f"{prefix}_{''.join(rng.choice(alphabet) for _ in range(n))}"


def sample_size(rng: random.Random, limit: int, bias: SizeBias, skew: float) -> int:
    if limit <= 0:
        return 0
    u = rng.random()
    if bias == "uniform":
        frac = u
    elif bias == "small_heavy":
        if skew <= 0:
            skew = 3.0
        frac = u ** skew
    else:
        frac = u
    return max(1, int(frac * limit)) if limit > 1 else 1


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_txt_bytes(rng: random.Random, size: int) -> bytes:
    alphabet = (string.ascii_letters + string.digits + " .,:;_-+*/()[]{}!\n").encode("ascii")
    return bytes(rng.choice(alphabet) for _ in range(size))


def make_bin_bytes(size: int) -> bytes:
    return os.urandom(size)


def choose_unique_filename(
    d: Path,
    rng: random.Random,
    ext: str,
    preferred: str | None,
) -> str:
    """
    If preferred is given, use it if it doesn't already exist in this directory.
    Otherwise generate a random file name.
    """
    if preferred is not None:
        candidate = preferred + ext
        if not (d / candidate).exists():
            return candidate

    # fallback random
    for _ in range(100):
        candidate = rand_name(rng, "file") + ext
        if not (d / candidate).exists():
            return candidate

    # extremely unlikely; final fallback
    return rand_name(rng, "file") + ext


def create_tree(
    root: Path,
    depth: int,
    max_files_total: int,
    max_dirs_per_dir: int,
    max_files_per_dir: int,
    max_txt_bytes: int,
    max_bin_bytes: int,
    max_total_bytes: int,
    txt_ratio: float,
    size_bias: SizeBias,
    size_skew: float,
    dup_percent: int,
    dup_same_name_percent: int,
    rng: random.Random,
) -> tuple[dict, dict, list[ManifestEntry]]:
    root.mkdir(parents=True, exist_ok=True)
    dirs: list[tuple[Path, int]] = [(root, 0)]

    entries: list[ManifestEntry] = []
    files_created = 0
    bytes_created = 0
    dirs_created = 1

    target_dups = (max_files_total * dup_percent) // 100
    dup_created = 0

    # Pools store: (sha, data, original_basename_no_ext)
    pool_txt: list[tuple[str, bytes, str]] = []
    pool_bin: list[tuple[str, bytes, str]] = []

    def remaining_files() -> int:
        return max_files_total - files_created

    def remaining_bytes() -> int:
        return max_total_bytes - bytes_created

    while dirs and remaining_files() > 0 and remaining_bytes() > 0:
        d, level = dirs.pop(0)

        files_here = rng.randint(0, min(max_files_per_dir, remaining_files()))
        for _ in range(files_here):
            if remaining_files() <= 0 or remaining_bytes() <= 0:
                break

            is_txt = (rng.random() < txt_ratio)
            kind = "txt" if is_txt else "bin"
            ext = ".txt" if is_txt else ".bin"

            # Decide duplicate intent
            make_dup = False
            if dup_percent > 0 and dup_created < target_dups:
                if is_txt and pool_txt:
                    make_dup = True
                elif (not is_txt) and pool_bin:
                    make_dup = True

            # Nudge if behind on duplicates
            if not make_dup and dup_percent > 0 and dup_created < target_dups and target_dups > 0:
                behind = (target_dups - dup_created) / target_dups
                if rng.random() < behind:
                    if is_txt and pool_txt:
                        make_dup = True
                    elif (not is_txt) and pool_bin:
                        make_dup = True

            if make_dup:
                if is_txt:
                    src_sha, data, src_base = rng.choice(pool_txt)
                else:
                    src_sha, data, src_base = rng.choice(pool_bin)

                if len(data) > remaining_bytes():
                    make_dup = False
                else:
                    dup_created += 1
                    data_sha = src_sha
                    is_duplicate = True
                    dup_of_sha = src_sha

                    # decide whether to reuse the source basename
                    reuse_name = (rng.randint(1, 100) <= dup_same_name_percent)
                    preferred_base = src_base if reuse_name else None
                    filename = choose_unique_filename(d, rng, ext, preferred_base)
                    dup_of_name = src_base + ext if reuse_name else None

            if not make_dup:
                per_type_limit = max_txt_bytes if is_txt else max_bin_bytes
                effective_limit = min(per_type_limit, remaining_bytes())
                if effective_limit <= 0:
                    break

                size = sample_size(rng, effective_limit, size_bias, size_skew)
                size = max(1, min(size, effective_limit))

                data = make_txt_bytes(rng, size) if is_txt else make_bin_bytes(size)
                data_sha = sha256_bytes(data)
                is_duplicate = False
                dup_of_sha = None
                dup_of_name = None

                # Create a new basename and ensure unique in this directory
                base = rand_name(rng, "file")
                filename = choose_unique_filename(d, rng, ext, base)
                base_no_ext = Path(filename).stem

                # Add to pool for future duplicates
                if is_txt:
                    pool_txt.append((data_sha, data, base_no_ext))
                else:
                    pool_bin.append((data_sha, data, base_no_ext))

            fpath = d / filename
            fpath.write_bytes(data)

            rel = str(fpath.relative_to(root))
            entries.append(
                ManifestEntry(
                    path=str(fpath.resolve()),
                    relpath=rel,
                    kind=kind,
                    filename=filename,
                    size_bytes=len(data),
                    sha256=data_sha,
                    is_duplicate=is_duplicate,
                    duplicate_of_sha256=dup_of_sha,
                    duplicate_of_name=dup_of_name,
                )
            )

            files_created += 1
            bytes_created += len(data)

            if remaining_files() <= 0 or remaining_bytes() <= 0:
                break

        if remaining_files() <= 0 or remaining_bytes() <= 0:
            break

        if level < depth:
            subdirs = rng.randint(0, max_dirs_per_dir)
            for _ in range(subdirs):
                subname = rand_name(rng, "dir")
                subpath = d / subname
                if not subpath.exists():
                    subpath.mkdir(parents=False, exist_ok=True)
                    dirs_created += 1
                dirs.append((subpath, level + 1))

    settings = dict(
        depth=depth,
        max_files=max_files_total,
        max_dirs_per_dir=max_dirs_per_dir,
        max_files_per_dir=max_files_per_dir,
        max_txt_bytes=max_txt_bytes,
        max_bin_bytes=max_bin_bytes,
        max_total_bytes=max_total_bytes,
        txt_ratio=txt_ratio,
        size_bias=size_bias,
        size_skew=size_skew,
        dup_percent=dup_percent,
        dup_same_name_percent=dup_same_name_percent,
    )

    totals = dict(
        files_created=files_created,
        dirs_created=dirs_created,
        bytes_created=bytes_created,
        bytes_remaining=max_total_bytes - bytes_created,
        files_remaining=max_files_total - files_created,
        duplicates_target=target_dups,
        duplicates_created=dup_created,
    )

    return settings, totals, entries


def main() -> int:
    p = argparse.ArgumentParser(description="Generate a random directory tree with random txt/bin files.")
    p.add_argument("--root", type=Path, required=True, help="Root output directory (created if missing).")
    p.add_argument("--depth", type=int, default=3, help="Maximum directory depth below root (default: 3).")
    p.add_argument("--max-files", type=int, default=100, help="Maximum total files to create (default: 100).")
    p.add_argument("--max-dirs-per-dir", type=int, default=4, help="Max subdirectories per directory (default: 4).")
    p.add_argument("--max-files-per-dir", type=int, default=8, help="Max files per directory (default: 8).")

    p.add_argument("--max-txt-bytes", type=int, default=4096, help="Max size of a single .txt file (default: 4096).")
    p.add_argument("--max-bin-bytes", type=int, default=4096, help="Max size of a single .bin file (default: 4096).")
    p.add_argument("--max-total-bytes", type=int, default=1_000_000, help="Max total bytes across all files.")

    p.add_argument("--txt-ratio", type=float, default=0.5, help="Probability a file is .txt (0..1). Default: 0.5")
    p.add_argument("--size-bias", choices=["uniform", "small_heavy"], default="small_heavy")
    p.add_argument("--size-skew", type=float, default=3.0, help="Skew for small_heavy (>1 => more small). Default: 3.0")

    p.add_argument("--dup-percent", type=int, default=0, help="Percent of files that duplicate another's contents (0..99).")
    p.add_argument(
        "--dup-same-name-percent",
        type=int,
        default=0,
        help="Among duplicates, percent that try to reuse original basename (0..100).",
    )

    p.add_argument("--manifest", type=Path, default=None, help="Manifest JSON path. Default: <root>/manifest.json")
    p.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility.")
    args = p.parse_args()

    # Validate
    if args.depth < 0:
        raise SystemExit("--depth must be >= 0")
    if args.max_files < 0:
        raise SystemExit("--max-files must be >= 0")
    if args.max_dirs_per_dir < 0 or args.max_files_per_dir < 0:
        raise SystemExit("--max-dirs-per-dir/--max-files-per-dir must be >= 0")
    if args.max_txt_bytes < 0 or args.max_bin_bytes < 0:
        raise SystemExit("--max-txt-bytes/--max-bin-bytes must be >= 0")
    if args.max_total_bytes < 0:
        raise SystemExit("--max-total-bytes must be >= 0")
    if not (0.0 <= args.txt_ratio <= 1.0):
        raise SystemExit("--txt-ratio must be between 0 and 1")
    if args.size_bias == "small_heavy" and args.size_skew <= 0:
        raise SystemExit("--size-skew must be > 0 (recommended > 1)")
    if not (0 <= args.dup_percent <= 99):
        raise SystemExit("--dup-percent must be between 0 and 99")
    if not (0 <= args.dup_same_name_percent <= 100):
        raise SystemExit("--dup-same-name-percent must be between 0 and 100")

    rng = random.Random(args.seed)

    settings, totals, entries = create_tree(
        root=args.root,
        depth=args.depth,
        max_files_total=args.max_files,
        max_dirs_per_dir=args.max_dirs_per_dir,
        max_files_per_dir=args.max_files_per_dir,
        max_txt_bytes=args.max_txt_bytes,
        max_bin_bytes=args.max_bin_bytes,
        max_total_bytes=args.max_total_bytes,
        txt_ratio=args.txt_ratio,
        size_bias=args.size_bias,
        size_skew=args.size_skew,
        dup_percent=args.dup_percent,
        dup_same_name_percent=args.dup_same_name_percent,
        rng=rng,
    )

    manifest_path = args.manifest if args.manifest is not None else (args.root / "manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    out = {
        "root": str(args.root.resolve()),
        "seed": args.seed,
        "settings": settings,
        "totals": totals,
        "entries": [asdict(e) for e in entries],
    }
    manifest_path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Created {totals['files_created']} file(s), {totals['dirs_created']} dir(s)")
    print(f"Total bytes written: {totals['bytes_created']} (limit {args.max_total_bytes})")
    if args.dup_percent > 0:
        print(f"Duplicates: {totals['duplicates_created']} (target ~{totals['duplicates_target']})")
        print(f"Duplicate same-name attempts: {args.dup_same_name_percent}%")
    print(f"Manifest: {manifest_path.resolve()}")
    print(f"Root: {args.root.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
