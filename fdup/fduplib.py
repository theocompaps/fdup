"""
fduplib - Library module for fdup duplicate file finder.

Contains enums for configuration modes and core functions for:
- File discovery
- MD5 checksum calculation
- Duplicate detection
- JSON output
"""

import sys
import os
import hashlib
import json
import re
import subprocess
import shlex
import shutil
import time
from enum import Enum
from dataclasses import dataclass
from typing import Callable, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed


class CompareMode(Enum):
    NAME = 'NAME'
    NAMESIZE = 'NAMESIZE'
    MD5 = 'MD5'

    def __str__(self):
        return self.value


class FindMode(Enum):
    DEFAULT = 'DEFAULT'
    FIND = 'FIND'

    def __str__(self):
        return self.value


class MD5Mode(Enum):
    DEFAULT = 'DEFAULT'
    MD5SUM = 'MD5SUM'

    def __str__(self):
        return self.value


class ScriptType(Enum):
    BASH = 'BASH'
    BAT = 'BAT'

    def __str__(self):
        return self.value


def get_default_script_type():
    """Get the platform-native default script type.
    
    Returns:
        ScriptType.BAT on Windows, ScriptType.BASH on Linux/macOS.
    """
    if sys.platform == 'win32':
        return ScriptType.BAT
    return ScriptType.BASH


# Progress reporting support
@dataclass
class ProgressEvent:
    """Progress event for scan and duplicate detection stages."""
    stage: str  # "scan" | "dups"
    root_dir: Optional[str] = None
    dirs_scanned: Optional[int] = None
    files_scanned: Optional[int] = None
    files_matched: Optional[int] = None
    processed: Optional[int] = None
    total: Optional[int] = None


ProgressCallback = Callable[[ProgressEvent], None]


# Configuration file support
CONFIG_VERSION = 1
DEFAULT_CONFIG_FILENAME = "fdup_cfg.json"
DEFAULT_MD5_CACHE_FILENAME = "fdup_md5_cache.json"

# Keys that are part of scan configuration (not export actions)
SCAN_CONFIG_KEYS = [
    'directories',
    'compare_mode',
    'find_mode',
    'md5_mode',
    'md5_block_size',
    'md5_max_size',
    'include_patterns',
    'iregex',
    'script_type',
    'threads',
    'hash_threads',
    'require_stable',
    'md5_cache',
]


# MD5 cache support
def load_md5_cache(cache_path: str) -> dict:
    """
    Load MD5 cache from a JSON file.
    
    Returns:
        dict: Cache dictionary with absolute paths as keys.
              Each entry contains: md5, md5_read_size, size, mtime_ns, md5_mode, md5_max_size
    """
    if not os.path.exists(cache_path):
        return {}
    
    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Return the entries dict (or empty if missing)
        return data.get('entries', {})
    except (json.JSONDecodeError, IOError, OSError) as e:
        print(f"Warning: Failed to load MD5 cache from {cache_path}: {e}", flush=True)
        return {}


def save_md5_cache(cache_path: str, cache_entries: dict, verbose: bool = True) -> None:
    """
    Save MD5 cache to a JSON file.
    
    Args:
        cache_path: Path to cache file
        cache_entries: Dictionary of cache entries (path -> entry dict)
        verbose: If True, print status message
    """
    data = {
        'version': 1,
        'cached_at': time.time(),
        'entries': cache_entries,
    }
    
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        if verbose:
            print(f"MD5 cache saved to {cache_path} ({len(cache_entries)} entries)", flush=True)
    except (IOError, OSError) as e:
        print(f"Warning: Failed to save MD5 cache to {cache_path}: {e}", flush=True)


def _get_cache_key(file_path: str) -> str:
    """Get normalized absolute path for cache key."""
    return os.path.normcase(os.path.abspath(file_path))


def _is_cache_hit(cache_entry: dict, file_stat, args) -> bool:
    """
    Check if a cache entry is valid for the given file and settings.
    
    A cache hit requires:
    - Same file size
    - Same mtime_ns (or mtime if ns not available)
    - Same md5_mode
    - Same md5_max_size
    """
    # Check size
    if cache_entry.get('size') != file_stat.st_size:
        return False
    
    # Check mtime (use mtime_ns if available, otherwise mtime)
    cached_mtime_ns = cache_entry.get('mtime_ns')
    if cached_mtime_ns is not None:
        # Compare nanosecond-precision mtime
        current_mtime_ns = getattr(file_stat, 'st_mtime_ns', int(file_stat.st_mtime * 1e9))
        if cached_mtime_ns != current_mtime_ns:
            return False
    else:
        # Fallback to second-precision mtime
        if cache_entry.get('mtime') != file_stat.st_mtime:
            return False
    
    # Check md5_mode
    md5_mode_str = str(getattr(args, 'md5_mode', MD5Mode.DEFAULT))
    if cache_entry.get('md5_mode') != md5_mode_str:
        return False
    
    # Check md5_max_size
    md5_max_size = getattr(args, 'md5_max_size', 0) or 0
    if cache_entry.get('md5_max_size', 0) != md5_max_size:
        return False
    
    return True


def args_to_scan_config_dict(args):
    """Convert args namespace to a scan configuration dictionary.
    
    Args:
        args: argparse.Namespace with scan configuration
        
    Returns:
        dict: Configuration dictionary suitable for JSON serialization
    """
    config = {
        'version': CONFIG_VERSION,
    }
    
    # Extract scan configuration keys
    if hasattr(args, 'directories') and args.directories:
        config['directories'] = args.directories
    
    if hasattr(args, 'compare_mode') and args.compare_mode:
        config['compare_mode'] = str(args.compare_mode)
    
    if hasattr(args, 'find_mode') and args.find_mode:
        config['find_mode'] = str(args.find_mode)
    
    if hasattr(args, 'md5_mode') and args.md5_mode:
        config['md5_mode'] = str(args.md5_mode)
    
    if hasattr(args, 'md5_block_size'):
        config['md5_block_size'] = args.md5_block_size
    
    if hasattr(args, 'md5_max_size'):
        config['md5_max_size'] = args.md5_max_size
    
    if hasattr(args, 'include_patterns'):
        config['include_patterns'] = args.include_patterns
    
    if hasattr(args, 'iregex'):
        config['iregex'] = args.iregex
    
    if hasattr(args, 'script_type') and args.script_type:
        config['script_type'] = str(args.script_type)
    
    if hasattr(args, 'threads'):
        config['threads'] = args.threads
    
    if hasattr(args, 'hash_threads'):
        config['hash_threads'] = args.hash_threads
    
    if hasattr(args, 'require_stable'):
        config['require_stable'] = args.require_stable
    
    if hasattr(args, 'md5_cache') and args.md5_cache:
        config['md5_cache'] = args.md5_cache
    
    return config


def apply_scan_config_dict_to_args(args, cfg_dict):
    """Apply configuration dictionary values to args namespace.
    
    Only applies values that are present in cfg_dict.
    
    Args:
        args: argparse.Namespace to modify
        cfg_dict: Configuration dictionary
        
    Returns:
        argparse.Namespace: Modified args
    """
    if 'directories' in cfg_dict and cfg_dict['directories']:
        args.directories = cfg_dict['directories']
    
    if 'compare_mode' in cfg_dict:
        args.compare_mode = CompareMode[cfg_dict['compare_mode']]
    
    if 'find_mode' in cfg_dict:
        args.find_mode = FindMode[cfg_dict['find_mode']]
    
    if 'md5_mode' in cfg_dict:
        args.md5_mode = MD5Mode[cfg_dict['md5_mode']]
    
    if 'md5_block_size' in cfg_dict:
        args.md5_block_size = cfg_dict['md5_block_size']
    
    if 'md5_max_size' in cfg_dict:
        args.md5_max_size = cfg_dict['md5_max_size']
    
    if 'include_patterns' in cfg_dict:
        args.include_patterns = cfg_dict['include_patterns']
    
    if 'iregex' in cfg_dict:
        args.iregex = cfg_dict['iregex']
    
    if 'script_type' in cfg_dict:
        args.script_type = ScriptType[cfg_dict['script_type']]
    
    if 'threads' in cfg_dict:
        args.threads = cfg_dict['threads']
    
    if 'hash_threads' in cfg_dict:
        args.hash_threads = cfg_dict['hash_threads']
    
    if 'require_stable' in cfg_dict:
        args.require_stable = cfg_dict['require_stable']
    
    if 'md5_cache' in cfg_dict:
        args.md5_cache = cfg_dict['md5_cache']
    
    return args


def load_scan_config(filename):
    """Load scan configuration from a JSON file.
    
    Args:
        filename: Path to JSON configuration file
        
    Returns:
        dict: Configuration dictionary
        
    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file is not valid JSON
    """
    with open(filename, 'r') as f:
        cfg = json.load(f)
    return cfg


def save_scan_config(filename, cfg_dict, verbose=True):
    """Save scan configuration to a JSON file.
    
    Args:
        filename: Path to JSON configuration file
        cfg_dict: Configuration dictionary
        verbose: If True, print status message
    """
    with open(filename, 'w') as f:
        json.dump(cfg_dict, f, indent=2)
    
    if verbose:
        print(f"Configuration saved to {filename}", flush=True)


def get_file_info(args, dir_path, file_path, skip_md5: bool = False):
    """
    Get file information: filename, size, and optionally MD5 checksum.
    
    Args:
        args: Parsed arguments
        dir_path: Directory containing the file
        file_path: Full path to the file
        skip_md5: If True, skip MD5 computation even in MD5 mode (for size-first optimization)
    """
    file_info = {
        'path': dir_path,
        'filename': os.path.basename(file_path),
        'size': os.path.getsize(file_path)
    }

    if args.compare_mode == CompareMode.MD5 and not skip_md5:
        (md5sum, read_size) = calculate_md5(args, file_path, os.path.getsize(file_path))

        file_info['md5'] = md5sum
        file_info['md5_read_size'] = read_size

    return file_info


def get_file_info_metadata_only(dir_path, file_path):
    """
    Get file metadata only (path, filename, size) without any hashing.
    
    Used for the first phase of size-first duplicate detection.
    """
    return {
        'path': dir_path,
        'filename': os.path.basename(file_path),
        'size': os.path.getsize(file_path),
        'full_path': file_path,  # Store for later MD5 computation
    }


def calculate_md5_with_stability_check(args, file_path, file_size) -> Tuple[str, int, bool, str]:
    """
    Calculate MD5 checksum for a file with optional stability check and retry logic.
    
    Args:
        args: Parsed arguments
        file_path: Path to file
        file_size: Expected file size
        
    Returns:
        Tuple of (md5_hash, read_size, success, error_message)
        - success is False if file changed during hashing (when require_stable is True)
        - error_message contains details if success is False
    """
    require_stable = getattr(args, 'require_stable', False)
    max_retries = 3
    retry_delay = 0.5  # seconds
    
    for attempt in range(max_retries):
        try:
            # Get initial stats for stability check
            if require_stable:
                try:
                    stat_before = os.stat(file_path)
                    size_before = stat_before.st_size
                    mtime_before = stat_before.st_mtime
                except OSError as e:
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    return ("", 0, False, f"Failed to stat file: {e}")
            
            # Calculate MD5
            md5_hash, read_size = calculate_md5(args, file_path, file_size)
            
            # Check stability after hashing
            if require_stable:
                try:
                    stat_after = os.stat(file_path)
                    size_after = stat_after.st_size
                    mtime_after = stat_after.st_mtime
                    
                    if size_before != size_after or mtime_before != mtime_after:
                        return ("", 0, False, f"File changed during hashing (size: {size_before}->{size_after}, mtime: {mtime_before}->{mtime_after})")
                except OSError as e:
                    return ("", 0, False, f"Failed to verify file stability: {e}")
            
            return (md5_hash, read_size, True, "")
            
        except (OSError, IOError) as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            return ("", 0, False, f"Failed to read file after {max_retries} attempts: {e}")
    
    return ("", 0, False, "Unexpected error in MD5 calculation")


def calculate_md5(args, file_path, file_size):
    """
    Calculate MD5 checksum for a file.
    
    Always uses chunked reads to avoid loading entire file into RAM.
    """

    if args.md5_mode == MD5Mode.DEFAULT:
        read_size = 0
        block_size = getattr(args, 'md5_block_size', 4096) or 4096
        max_size_bytes = (getattr(args, 'md5_max_size', 0) or 0) * 1024

        md5 = hashlib.md5()
        with open(file_path, 'rb') as file:
            for chunk in iter(lambda: file.read(block_size), b""):
                md5.update(chunk)
                read_size += len(chunk)

                # Stop after md5_max_size if enabled
                if max_size_bytes > 0 and read_size >= max_size_bytes:
                    break

        return (md5.hexdigest(), read_size)
    elif args.md5_mode == MD5Mode.MD5SUM:

        cmd = 'md5sum -b  \'' + file_path + '\''

        result = subprocess.run([cmd], shell=True, capture_output=True, text=True)

        try:
            result.check_returncode()
        except subprocess.CalledProcessError as grepexc:
            print("Error code", grepexc.returncode, grepexc.output, flush=True)

        md5sum_result = result.stdout.split(' ')

        return (md5sum_result[0], file_size)
    else:
        sys.exit("MD5Mode: " + str(args.md5_mode) + " Not supported")


def _has_gnu_find():
    """
    Check if GNU find is available on the system.
    Returns False on Windows if only System32\\find.exe is found (which is not GNU find).
    """
    find_path = shutil.which('find')
    if find_path is None:
        return False
    # On Windows, System32\find.exe is a text search tool, not GNU find
    if sys.platform == 'win32':
        # Check if find.exe is in System32 (Windows built-in)
        if 'system32' in find_path.lower():
            return False
    return True


def find_files(args, root_directories, progress_cb: Optional[ProgressCallback] = None):
    """
    Find files in the specified root directories.
    
    Args:
        args: Parsed arguments
        root_directories: List of root directories to scan
        progress_cb: Optional callback for progress reporting
    """
    if args.find_mode == FindMode.DEFAULT:
        (files, total_count_files, total_count_directories) = find_files_default(args, root_directories, progress_cb)
    elif args.find_mode == FindMode.FIND:
        if _has_gnu_find():
            (files, total_count_files, total_count_directories) = find_files_find(args, root_directories, progress_cb)
        else:
            print("Using find_mode: FIND but GNU find is not available on the system, thus reverting to DEFAULT", flush=True)
            # Validate include patterns for DEFAULT mode (they must be valid Python regex)
            if args.include_patterns is not None:
                for pattern in args.include_patterns:
                    # Normalize pattern the same way find_files_default does
                    normalized = pattern.replace(r".", r"\.")
                    try:
                        re.compile(normalized)
                    except re.error as e:
                        print(f"Invalid include pattern '{pattern}' for DEFAULT mode (Python regex).", flush=True)
                        print(f"You used -f FIND but GNU find is not available and the program reverted to DEFAULT.", flush=True)
                        print(f"Please change the pattern (e.g. '*.jpg' -> '.jpg') or install GNU find.", flush=True)
                        sys.exit(1)
            (files, total_count_files, total_count_directories) = find_files_default(args, root_directories, progress_cb)
    else:
        sys.exit("FindMode: " + str(args.find_mode) + " Not supported")

    return files


def find_files_default(args, root_directories, progress_cb: Optional[ProgressCallback] = None):
    """
    Find files in the specified root directories using a native Python algorithm
    
    Args:
        args: Parsed arguments
        root_directories: List of root directories to scan
        progress_cb: Optional callback for progress reporting
    """
    files = dict()
    total_count_files = 0
    total_count_directories = 0
    total_matched_files = 0
    
    # Get thread count (0 = off)
    num_threads = getattr(args, 'threads', 0) or 0

    for root_dir in root_directories:
        print(f"Scanning root dir: {root_dir} to get all files", flush=True)

        files[root_dir] = list()

        count_files = 0
        count_directories = 0
        count_matched = 0
        
        # Collect candidate file paths first (for threaded mode)
        candidate_paths = []

        for dir_path, _, file_names in os.walk(root_dir):
            count_directories += 1

            for file_name in file_names:
                found = False

                if args.include_patterns != None:
                    normalized_ips = list(map(lambda s: s.replace(r".", r"\."), args.include_patterns)) 

                    for nip in normalized_ips:
                        m = re.search(nip, file_name)

                        if m != None:
                            found = True
                            break

                if args.include_patterns == None or found == True:
                    file_path = os.path.join(dir_path, file_name)
                    candidate_paths.append((dir_path, file_path))

                count_files += 1

                # Print status every 1000 files during discovery
                if count_files % 1000 == 0:
                    print(f"  Status: Directories scanned: {count_directories}, Files discovered: {count_files}", flush=True)
        
        print(f"Discovery complete: {count_directories} dirs, {len(candidate_paths)} matching files", flush=True)
        
        # For MD5 mode, skip MD5 computation during scan (size-first optimization)
        skip_md5_in_scan = (args.compare_mode == CompareMode.MD5)
        
        # Process file info (stat + optional MD5) - threaded or sequential
        if num_threads > 0 and len(candidate_paths) > 0:
            print(f"Processing file info with {num_threads} threads...", flush=True)
            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                # Submit all tasks
                future_to_path = {
                    executor.submit(get_file_info, args, dir_path, file_path, skip_md5_in_scan): (dir_path, file_path)
                    for dir_path, file_path in candidate_paths
                }
                
                # Collect results as they complete
                for future in as_completed(future_to_path):
                    try:
                        file_info = future.result()
                        # Store full_path for later MD5 computation in MD5 mode
                        if skip_md5_in_scan:
                            dir_path, file_path = future_to_path[future]
                            file_info['full_path'] = file_path
                        files[root_dir].append(file_info)
                        count_matched += 1
                        
                        # Emit progress every 250 completed files
                        if progress_cb and count_matched % 250 == 0:
                            progress_cb(ProgressEvent(
                                stage="scan",
                                root_dir=root_dir,
                                dirs_scanned=count_directories,
                                files_scanned=count_matched,
                                files_matched=count_matched
                            ))
                        
                        # Print status every 1000 files
                        if count_matched % 1000 == 0:
                            print(f"  Status: Files processed: {count_matched}/{len(candidate_paths)}", flush=True)
                    except Exception as e:
                        path = future_to_path[future]
                        print(f"  Warning: Failed to process {path[1]}: {e}", flush=True)
        else:
            # Sequential processing (original behavior)
            for dir_path, file_path in candidate_paths:
                try:
                    file_info = get_file_info(args, dir_path, file_path, skip_md5_in_scan)
                    # Store full_path for later MD5 computation in MD5 mode
                    if skip_md5_in_scan:
                        file_info['full_path'] = file_path
                    files[root_dir].append(file_info)
                    count_matched += 1
                    
                    # Emit progress every 250 files
                    if progress_cb and count_matched % 250 == 0:
                        progress_cb(ProgressEvent(
                            stage="scan",
                            root_dir=root_dir,
                            dirs_scanned=count_directories,
                            files_scanned=count_matched,
                            files_matched=count_matched
                        ))
                    
                    # Print status every 1000 files
                    if count_matched % 1000 == 0:
                        print(f"  Status: Files processed: {count_matched}/{len(candidate_paths)}", flush=True)
                except Exception as e:
                    print(f"  Warning: Failed to process {file_path}: {e}", flush=True)

        total_count_files = total_count_files + count_files
        total_count_directories = total_count_directories + count_directories
        total_matched_files = total_matched_files + count_matched
        print(f"Status: Total directories scanned: {total_count_directories}, Total files processed: {total_matched_files}", flush=True)
        
        # Final progress for this root
        if progress_cb:
            progress_cb(ProgressEvent(
                stage="scan",
                root_dir=root_dir,
                dirs_scanned=total_count_directories,
                files_scanned=total_matched_files,
                files_matched=total_matched_files
            ))

    return (files, total_count_files, total_count_directories)


def find_files_find(args, root_directories, progress_cb: Optional[ProgressCallback] = None):
    """
    Find files in the specified root directories using the command line find tool
    with streaming progress support.
    
    Args:
        args: Parsed arguments
        root_directories: List of root directories to scan
        progress_cb: Optional callback for progress reporting
    """
    files = dict()
    total_count_files = 0
    total_count_directories = 0
    
    # Get thread count (0 = off)
    num_threads = getattr(args, 'threads', 0) or 0

    for root_dir in root_directories:
        print(f"Scanning root dir: {root_dir} to get all files", flush=True)

        files[root_dir] = list()

        count_files = 0
        count_directories = 0      

        # Get number of dirs
        cmd = 'tree -d ' + root_dir

        result = subprocess.run([cmd], shell=True, capture_output=True, text=True)

        try:
            result.check_returncode()
        except subprocess.CalledProcessError as grepexc:
            print("Error code", grepexc.returncode, grepexc.output, flush=True)

        result_lines = result.stdout.splitlines()
  
        for line in result_lines:
            m = re.search(r'^(\d+)\s+director', line)

            if m != None:
                count_directories = int(m.group(1))

        # Setup include patterns and run find command
        if args.include_patterns == None:
            cmd = 'find ' + root_dir + ' -type f'
        else:
            if args.iregex == False:
                find_args = ' -o '.join(map(lambda s: '-name "' + s + '"', args.include_patterns))
            else:
                if len(args.include_patterns) != 1:
                    print('Only one include pattern can be specified when -iregex is in use', flush=True)
                    sys.exit(1)
                else:
                    find_args = '-iregex \'' + args.include_patterns[0] + '\''
    
            cmd = 'find ' + root_dir + ' -type f ' + find_args

        # Use Popen for streaming progress
        process = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        
        file_paths = []
        files_found = 0
        
        # Read lines as they come for progress reporting
        for line in process.stdout:
            file_path = line.rstrip('\n\r')
            if file_path:
                file_paths.append(file_path)
                files_found += 1
                
                # Emit progress every 250 files during discovery
                if progress_cb and files_found % 250 == 0:
                    progress_cb(ProgressEvent(
                        stage="scan",
                        root_dir=root_dir,
                        dirs_scanned=count_directories,
                        files_scanned=files_found,
                        files_matched=files_found
                    ))
        
        process.wait()
        
        if process.returncode != 0:
            stderr_output = process.stderr.read()
            print(f"Error code {process.returncode}: {stderr_output}", flush=True)

        print('Find found: ' + str(len(file_paths)) + ' files and ' + str(count_directories) + ' directories', flush=True)
        print('Getting file info and optionally computing the MD5 for each file', flush=True)

        # For MD5 mode, skip MD5 computation during scan (size-first optimization)
        skip_md5_in_scan = (args.compare_mode == CompareMode.MD5)

        # Process file info (stat + optional MD5) - threaded or sequential
        if num_threads > 0 and len(file_paths) > 0:
            print(f"Processing file info with {num_threads} threads...", flush=True)
            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                # Submit all tasks
                future_to_path = {
                    executor.submit(get_file_info, args, os.path.dirname(fp), fp, skip_md5_in_scan): fp
                    for fp in file_paths
                }
                
                # Collect results as they complete
                for future in as_completed(future_to_path):
                    try:
                        file_info = future.result()
                        # Store full_path for later MD5 computation in MD5 mode
                        if skip_md5_in_scan:
                            file_info['full_path'] = future_to_path[future]
                        files[root_dir].append(file_info)
                        count_files += 1
                        
                        # Emit progress every 250 completed files
                        if progress_cb and count_files % 250 == 0:
                            progress_cb(ProgressEvent(
                                stage="scan",
                                root_dir=root_dir,
                                dirs_scanned=count_directories,
                                files_scanned=count_files,
                                files_matched=count_files
                            ))
                        
                        # Print status every 1000 files
                        if count_files % 1000 == 0:
                            print(f"  Status: Files processed: {count_files}/{len(file_paths)}", flush=True)
                    except Exception as e:
                        fp = future_to_path[future]
                        print(f"  Warning: Failed to process {fp}: {e}", flush=True)
        else:
            # Sequential processing (original behavior)
            for file_path in file_paths:
                try:
                    (dir_path, file_name) = os.path.split(file_path)
                    file_info = get_file_info(args, dir_path, file_path, skip_md5_in_scan)
                    # Store full_path for later MD5 computation in MD5 mode
                    if skip_md5_in_scan:
                        file_info['full_path'] = file_path
                    files[root_dir].append(file_info)
                    count_files += 1

                    # Emit progress every 250 files during file info gathering
                    if progress_cb and count_files % 250 == 0:
                        progress_cb(ProgressEvent(
                            stage="scan",
                            root_dir=root_dir,
                            dirs_scanned=count_directories,
                            files_scanned=count_files,
                            files_matched=count_files
                        ))

                    # Print status every 1000 files
                    if count_files % 1000 == 0:
                        print(f"  Status: Files scanned: {count_files}", flush=True)
                except Exception as e:
                    print(f"  Warning: Failed to process {file_path}: {e}", flush=True)

        total_count_files = total_count_files + count_files
        total_count_directories = total_count_directories + count_directories
        print(f"Status: Total directories scanned: {total_count_directories}, Total files processed: {total_count_files}", flush=True)
        
        # Final progress for this root
        if progress_cb:
            progress_cb(ProgressEvent(
                stage="scan",
                root_dir=root_dir,
                dirs_scanned=total_count_directories,
                files_scanned=total_count_files,
                files_matched=total_count_files
            ))

    return (files, total_count_files, total_count_directories)


# Merges files which compare positive into a single key in the dict.
# A file has duplicates if there are more than one element in the list.
def find_duplicate_files(args, files, progress_cb: Optional[ProgressCallback] = None):
    """
    Find duplicate files by grouping them based on compare mode.
    
    For MD5 mode, uses size-first optimization:
    1. Group all files by size globally
    2. Only compute MD5 for files in size groups with >1 file
    3. Group by MD5 to find true duplicates
    
    Args:
        args: Parsed arguments
        files: Dictionary of root_dir -> list of file_info dicts
        progress_cb: Optional callback for progress reporting
    """
    # Calculate total for progress reporting
    total_files = sum(len(files[root_dir]) for root_dir in files)
    
    # For MD5 mode, use size-first optimization
    if args.compare_mode == CompareMode.MD5:
        return _find_duplicate_files_md5_size_first(args, files, total_files, progress_cb)
    
    # For NAME and NAMESIZE modes, use original algorithm
    duplicate_files = dict()
    processed = 0

    for root_dir in files:
        print("Looking in: " + root_dir + " to find duplets", flush=True)

        for file_info in files[root_dir]:
            if args.compare_mode == CompareMode.NAME:
                fileid = file_info['filename']
            elif args.compare_mode == CompareMode.NAMESIZE:
                fileid = (file_info['filename'], file_info['size'])
            else:
                print("Cannot handle compare mode:" + str(args.compare_mode), flush=True)
                continue

            if fileid not in duplicate_files:
                duplicate_files[fileid] = list()

            duplicate_files[fileid].append(file_info)
            processed += 1
            
            # Emit progress every 250 files
            if progress_cb and processed % 250 == 0:
                progress_cb(ProgressEvent(
                    stage="dups",
                    processed=processed,
                    total=total_files
                ))
    
    # Final progress
    if progress_cb:
        progress_cb(ProgressEvent(
            stage="dups",
            processed=total_files,
            total=total_files
        ))

    return duplicate_files


def _find_duplicate_files_md5_size_first(args, files, total_files, progress_cb: Optional[ProgressCallback] = None):
    """
    Find duplicate files using size-first MD5 optimization.
    
    1. Group all files by size globally across all roots
    2. Filter to only size groups with >1 file (potential duplicates)
    3. Compute MD5 only for those candidate files (with optional caching)
    4. Group by MD5 to find true duplicates
    
    This dramatically reduces the number of files that need to be hashed,
    especially useful for network shares where reading is expensive.
    """
    print("MD5 mode: Using size-first optimization", flush=True)
    
    # Load MD5 cache if enabled
    cache_path = getattr(args, 'md5_cache', None)
    cache_entries = {}
    cache_hits = 0
    cache_misses = 0
    if cache_path:
        print(f"  MD5 cache enabled: {cache_path}", flush=True)
        cache_entries = load_md5_cache(cache_path)
        if cache_entries:
            print(f"  Loaded {len(cache_entries)} cached entries", flush=True)
    
    # Phase 1: Group all files by size globally
    print("Phase 1: Grouping files by size...", flush=True)
    size_groups: dict[int, list] = {}
    
    for root_dir in files:
        for file_info in files[root_dir]:
            size = file_info['size']
            if size not in size_groups:
                size_groups[size] = []
            size_groups[size].append(file_info)
    
    # Filter to only size groups with potential duplicates (>1 file)
    candidate_groups = {size: group for size, group in size_groups.items() if len(group) > 1}
    
    # Count files that need hashing
    files_to_hash = sum(len(group) for group in candidate_groups.values())
    unique_by_size = total_files - files_to_hash
    
    print(f"  {len(size_groups)} unique sizes, {len(candidate_groups)} sizes with potential duplicates", flush=True)
    print(f"  {unique_by_size} files unique by size (skipping MD5)", flush=True)
    print(f"  {files_to_hash} files need MD5 computation", flush=True)
    
    # Phase 2: Compute MD5 only for candidate files
    print("Phase 2: Computing MD5 for candidate files...", flush=True)
    duplicate_files: dict[str, list] = {}
    skipped_files: list = []  # Track files that failed or changed during hashing
    processed = 0
    hashed = 0
    
    # Get thread count for MD5 computation (hash_threads takes precedence over threads)
    hash_threads = getattr(args, 'hash_threads', 0) or 0
    if hash_threads == 0:
        hash_threads = getattr(args, 'threads', 0) or 0
    
    require_stable = getattr(args, 'require_stable', False)
    if require_stable:
        print("  Stability check enabled: files that change during hashing will be skipped", flush=True)
    if hash_threads > 0:
        print(f"  Using {hash_threads} threads for hashing", flush=True)
    
    # Flatten all candidate files for batch processing
    all_files_to_process = []
    files_needing_hash = []
    
    for size, group in candidate_groups.items():
        for file_info in group:
            full_path = file_info.get('full_path')
            if not full_path:
                full_path = os.path.join(file_info['path'], file_info['filename'])
            
            # Check cache first if enabled
            if cache_path:
                cache_key = _get_cache_key(full_path)
                cached = cache_entries.get(cache_key)
                if cached:
                    try:
                        file_stat = os.stat(full_path)
                        if _is_cache_hit(cached, file_stat, args):
                            # Cache hit - use cached MD5
                            file_info['md5'] = cached['md5']
                            file_info['md5_read_size'] = cached.get('md5_read_size', file_info['size'])
                            
                            # Group by MD5
                            md5sum = cached['md5']
                            if md5sum not in duplicate_files:
                                duplicate_files[md5sum] = []
                            duplicate_files[md5sum].append(file_info)
                            
                            cache_hits += 1
                            hashed += 1
                            processed += 1
                            continue
                    except OSError:
                        pass  # File not accessible, will try to hash it
                
                cache_misses += 1
            
            files_needing_hash.append((file_info, full_path))
    
    if cache_path:
        print(f"  Cache: {cache_hits} hits, {cache_misses} misses", flush=True)
    
    # Update count of files to hash
    files_to_hash = len(files_needing_hash)
    if cache_hits > 0:
        print(f"  {files_to_hash} files still need MD5 computation after cache lookup", flush=True)
    
    # Compute MD5 (threaded or sequential)
    if hash_threads > 0 and len(files_needing_hash) > 1:
        with ThreadPoolExecutor(max_workers=hash_threads) as executor:
            future_to_info = {
                executor.submit(calculate_md5_with_stability_check, args, fp, fi['size']): (fi, fp)
                for fi, fp in files_needing_hash
            }
            
            for future in as_completed(future_to_info):
                file_info, full_path = future_to_info[future]
                try:
                    md5sum, read_size, success, error_msg = future.result()
                    
                    if success:
                        file_info['md5'] = md5sum
                        file_info['md5_read_size'] = read_size
                        
                        # Update cache if enabled
                        if cache_path:
                            try:
                                file_stat = os.stat(full_path)
                                cache_key = _get_cache_key(full_path)
                                cache_entries[cache_key] = {
                                    'md5': md5sum,
                                    'md5_read_size': read_size,
                                    'size': file_stat.st_size,
                                    'mtime_ns': getattr(file_stat, 'st_mtime_ns', int(file_stat.st_mtime * 1e9)),
                                    'md5_mode': str(getattr(args, 'md5_mode', MD5Mode.DEFAULT)),
                                    'md5_max_size': getattr(args, 'md5_max_size', 0) or 0,
                                }
                            except OSError:
                                pass  # Could not stat file for cache
                        
                        # Group by MD5
                        if md5sum not in duplicate_files:
                            duplicate_files[md5sum] = []
                        duplicate_files[md5sum].append(file_info)
                        
                        hashed += 1
                    else:
                        skipped_files.append({
                            'path': file_info['path'],
                            'filename': file_info['filename'],
                            'reason': error_msg
                        })
                        print(f"  Skipped: {file_info['filename']}: {error_msg}", flush=True)
                    
                    processed += 1
                    
                    if progress_cb and processed % 250 == 0:
                        progress_cb(ProgressEvent(
                            stage="dups",
                            processed=processed + unique_by_size,
                            total=total_files
                        ))
                except Exception as e:
                    skipped_files.append({
                        'path': file_info['path'],
                        'filename': file_info['filename'],
                        'reason': str(e)
                    })
                    print(f"  Warning: Failed to hash {file_info['filename']}: {e}", flush=True)
                    processed += 1
    else:
        # Sequential processing
        for file_info, full_path in files_needing_hash:
            md5sum, read_size, success, error_msg = calculate_md5_with_stability_check(args, full_path, file_info['size'])
            
            if success:
                file_info['md5'] = md5sum
                file_info['md5_read_size'] = read_size
                
                # Update cache if enabled
                if cache_path:
                    try:
                        file_stat = os.stat(full_path)
                        cache_key = _get_cache_key(full_path)
                        cache_entries[cache_key] = {
                            'md5': md5sum,
                            'md5_read_size': read_size,
                            'size': file_stat.st_size,
                            'mtime_ns': getattr(file_stat, 'st_mtime_ns', int(file_stat.st_mtime * 1e9)),
                            'md5_mode': str(getattr(args, 'md5_mode', MD5Mode.DEFAULT)),
                            'md5_max_size': getattr(args, 'md5_max_size', 0) or 0,
                        }
                    except OSError:
                        pass  # Could not stat file for cache
                
                # Group by MD5
                if md5sum not in duplicate_files:
                    duplicate_files[md5sum] = []
                duplicate_files[md5sum].append(file_info)
                
                hashed += 1
            else:
                skipped_files.append({
                    'path': file_info['path'],
                    'filename': file_info['filename'],
                    'reason': error_msg
                })
                print(f"  Skipped: {file_info['filename']}: {error_msg}", flush=True)
            
            processed += 1
            
            if progress_cb and processed % 250 == 0:
                progress_cb(ProgressEvent(
                    stage="dups",
                    processed=processed + unique_by_size,
                    total=total_files
                ))
            
            if processed % 1000 == 0:
                print(f"  Status: Processed {processed}/{files_to_hash} files", flush=True)
    
    if skipped_files:
        print(f"  Warning: {len(skipped_files)} files were skipped due to errors or instability", flush=True)
    
    print(f"  Hashed {hashed} files, found {sum(1 for g in duplicate_files.values() if len(g) > 1)} duplicate groups", flush=True)
    
    # Save updated cache if enabled (always write when cache option is used, even if empty)
    if cache_path:
        save_md5_cache(cache_path, cache_entries)
    
    # Final progress
    if progress_cb:
        progress_cb(ProgressEvent(
            stage="dups",
            processed=total_files,
            total=total_files
        ))
    
    return duplicate_files


def save_duplicates_to_json(args, duplicate_files, filename, verbose=True):
    """
    Save duplicate files information to JSON.
    
    Args:
        args: Parsed arguments containing directories list
        duplicate_files: Dictionary of file groups
        filename: Output JSON filename
        verbose: If True, print status message to stdout
    """
    # Remove singles - only keep groups with more than 1 file
    real_duplicates = {item: duplicate_files[item] for item in duplicate_files.keys() if len(duplicate_files[item]) > 1}

    json_data = dict()

    # Store the command line
    json_data['cmdline'] = (" ".join(shlex.quote(arg) if " " in arg else arg for arg in sys.argv))

    # Store the root directories
    json_data['root_directories'] = args.directories

    # Store the duplicate file list
    json_data['duplicate_files'] = real_duplicates

    with open(filename, 'w') as json_file:
        json.dump(json_data, json_file, indent=2)

    if verbose:
        print(f"Duplicate files information saved to {filename}", flush=True)


def save_uniques_to_json(args, duplicate_files, filename, verbose=True):
    """
    Save unique files information to JSON.
    
    Args:
        args: Parsed arguments containing directories list
        duplicate_files: Dictionary of file groups
        filename: Output JSON filename
        verbose: If True, print status messages to stdout
    """
    # Only keep groups with exactly 1 file (unique files)
    real_uniques = {item: duplicate_files[item] for item in duplicate_files.keys() if len(duplicate_files[item]) == 1}

    if real_uniques is not None and len(real_uniques.keys()) > 0:
        json_unique_data = dict()

        # Store the command line
        json_unique_data['cmdline'] = (" ".join(shlex.quote(arg) if " " in arg else arg for arg in sys.argv))

        # Store the root directories
        json_unique_data['root_directories'] = args.directories

        # Store the unique file list
        json_unique_data['unique_files'] = real_uniques

        with open(filename, 'w') as json_file:
            json.dump(json_unique_data, json_file, indent=2)

        if verbose:
            print(f"Unique files information saved to {filename}", flush=True)
    else:
        if verbose:
            print(f"No unique files found. Nothing saved to {filename}", flush=True)


def save_to_json(args, duplicate_files):
    """
    Save duplicate files information to JSON (legacy wrapper).
    
    DEPRECATED: Use save_duplicates_to_json() and save_uniques_to_json() instead.
    """
    # Export duplicates
    save_duplicates_to_json(args, duplicate_files, args.json_filename)
    
    # Optionally export uniques
    if args.save_unique == True:
        save_uniques_to_json(args, duplicate_files, args.json_unique_filename)


def export_cleanup_to_script(args, duplicate_files, filename, script_type=None, verbose=True):
    """
    Export a cleanup script that deletes duplicate files while preserving one copy.
    
    Args:
        args: Parsed arguments containing directories list
        duplicate_files: Dictionary of file groups
        filename: Output script filename
        script_type: ScriptType.BASH or ScriptType.BAT (default: BASH)
        verbose: If True, print status message to stdout
    """
    if script_type is None:
        script_type = ScriptType.BASH
    
    # Filter to only real duplicates (groups with more than 1 file)
    real_duplicates = {k: v for k, v in duplicate_files.items() if len(v) > 1}
    
    if not real_duplicates:
        if verbose:
            print(f"No duplicates found. Nothing saved to {filename}", flush=True)
        return
    
    with open(filename, 'w', newline=('\r\n' if script_type == ScriptType.BAT else '\n')) as f:
        # Write header
        if script_type == ScriptType.BASH:
            f.write("#!/usr/bin/env bash\n")
            f.write("set -euo pipefail\n")
            f.write("IFS=$'\\n\\t'\n")
            f.write("\n")
            f.write("# Cleanup script generated by fdup\n")
            f.write("# WARNING: Review this script before running!\n")
            f.write("# The first file in each duplicate group is commented out to preserve at least one copy.\n")
            f.write("\n")
            comment_prefix = "# "
        else:  # BAT
            f.write("@echo off\n")
            f.write("setlocal enableextensions\n")
            f.write("\n")
            f.write("REM Cleanup script generated by fdup\n")
            f.write("REM WARNING: Review this script before running!\n")
            f.write("REM The first file in each duplicate group is commented out to preserve at least one copy.\n")
            f.write("\n")
            comment_prefix = "REM "
        
        # Write delete commands for each duplicate group
        for group_key, file_list in real_duplicates.items():
            # Write group header comment
            if isinstance(group_key, tuple):
                # NAMESIZE mode: (filename, size)
                group_label = f"{group_key[0]} (size: {group_key[1]})"
            else:
                # NAME or MD5 mode
                group_label = str(group_key)
            
            if script_type == ScriptType.BASH:
                f.write(f"# Duplicate group: {group_label} ({len(file_list)} files)\n")
            else:
                f.write(f"REM Duplicate group: {group_label} ({len(file_list)} files)\n")
            
            # Write delete commands (first one commented out for safety)
            for i, file_info in enumerate(file_list):
                if script_type == ScriptType.BASH:
                    # Use forward slashes for BASH (normalize Windows backslashes)
                    full_path = file_info['path'].replace('\\', '/') + '/' + file_info['filename']
                    # Escape single quotes in path for bash
                    escaped_path = full_path.replace("'", "'\\''")
                    delete_cmd = f"rm -f -- '{escaped_path}'"
                else:  # BAT
                    # Use backslashes for BAT (normalize forward slashes)
                    full_path = file_info['path'].replace('/', '\\') + '\\' + file_info['filename']
                    # Escape special characters for BAT (double quotes)
                    delete_cmd = f'del /F /Q "{full_path}"'
                
                if i == 0:
                    # Comment out the first file to preserve at least one copy
                    f.write(f"{comment_prefix}{delete_cmd}\n")
                else:
                    f.write(f"{delete_cmd}\n")
            
            f.write("\n")
    
    if verbose:
        print(f"Cleanup script saved to {filename}", flush=True)


def export_selected_files_to_script(selected_files, filename, script_type=None, verbose=True):
    """
    Export a cleanup script for a list of selected files (GUI use case).
    
    Unlike export_cleanup_to_script(), this function does NOT comment out any files -
    all selected files become active delete commands.
    
    Args:
        selected_files: List of dicts with 'path' and 'filename' keys, or list of full paths
        filename: Output script filename
        script_type: ScriptType.BASH or ScriptType.BAT (default: platform-native)
        verbose: If True, print status message to stdout
    """
    if script_type is None:
        script_type = get_default_script_type()
    
    if not selected_files:
        if verbose:
            print(f"No files selected. Nothing saved to {filename}", flush=True)
        return
    
    with open(filename, 'w', newline=('\r\n' if script_type == ScriptType.BAT else '\n')) as f:
        # Write header
        if script_type == ScriptType.BASH:
            f.write("#!/usr/bin/env bash\n")
            f.write("set -euo pipefail\n")
            f.write("IFS=$'\\n\\t'\n")
            f.write("\n")
            f.write("# Cleanup script generated by fdup GUI\n")
            f.write("# WARNING: Review this script before running!\n")
            f.write(f"# This script will delete {len(selected_files)} file(s).\n")
            f.write("\n")
        else:  # BAT
            f.write("@echo off\n")
            f.write("setlocal enableextensions\n")
            f.write("\n")
            f.write("REM Cleanup script generated by fdup GUI\n")
            f.write("REM WARNING: Review this script before running!\n")
            f.write(f"REM This script will delete {len(selected_files)} file(s).\n")
            f.write("\n")
        
        # Write delete commands for each selected file
        for file_entry in selected_files:
            # Handle both dict format and string format
            if isinstance(file_entry, dict):
                full_path = os.path.join(file_entry['path'], file_entry['filename'])
            else:
                full_path = file_entry
            
            if script_type == ScriptType.BASH:
                # Use forward slashes for BASH (normalize Windows backslashes)
                full_path = full_path.replace('\\', '/')
                # Escape single quotes in path for bash
                escaped_path = full_path.replace("'", "'\\''")
                delete_cmd = f"rm -f -- '{escaped_path}'"
            else:  # BAT
                # Use backslashes for BAT (normalize forward slashes)
                full_path = full_path.replace('/', '\\')
                delete_cmd = f'del /F /Q "{full_path}"'
            
            f.write(f"{delete_cmd}\n")
    
    if verbose:
        print(f"Cleanup script saved to {filename}", flush=True)
