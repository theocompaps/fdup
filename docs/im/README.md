# fdup Implementation Manual

Version 1.0

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Module Structure](#module-structure)
3. [Data Structures](#data-structures)
4. [Core Algorithms](#core-algorithms)
5. [Compare Modes Implementation](#compare-modes-implementation)
6. [Find Modes Implementation](#find-modes-implementation)
7. [GUI Architecture](#gui-architecture)
8. [JSON Export](#json-export)
9. [Extending fdup](#extending-fdup)

---

## Architecture Overview

fdup follows a modular architecture with clear separation of concerns:

```
fdup/
├── bin/
│   ├── fdup.py          # CLI entry point
│   ├── fdupgui.py       # GUI entry point
│   └── cleanup.py       # Utility script
├── fdup/
│   ├── __init__.py      # Package init, version
│   └── fduplib.py       # Core library
├── docs/
│   ├── um/              # User manual
│   └── im/              # Implementation manual
└── tests/
    └── basic/           # Test data and scripts
```

### Design Principles

1. **Library-first**: Core functionality in `fduplib.py`, reusable by CLI and GUI
2. **Mode-based configuration**: Enums for compare/find/md5 modes
3. **Namespace args pattern**: Both CLI and GUI pass `argparse.Namespace` to library functions
4. **Streaming output**: Real-time progress via `print()` with `flush=True`

---

## Module Structure

### `fdup/__init__.py`

Defines the package version:

```python
__version__ = "v1.0"
```

### `fdup/fduplib.py`

Core library containing:

- **Enums**: `CompareMode`, `FindMode`, `MD5Mode`
- **File discovery**: `find_files()`, `find_files_default()`, `find_files_find()`
- **File info**: `get_file_info()`, `calculate_md5()`
- **Duplicate detection**: `find_duplicate_files()`
- **JSON export**: `save_duplicates_to_json()`, `save_uniques_to_json()`

### `bin/fdup.py`

CLI entry point:

- `configure_option_parser()`: Sets up argparse
- `main()`: Orchestrates scanning and output

### `bin/fdupgui.py`

PyQt5 GUI:

- `FdupGuiWindow`: Main window class
- `ScanWorker`: QThread for background scanning
- `QtLogStream`: Captures stdout for GUI output

---

## Data Structures

### Files Dictionary

Returned by `find_files()`:

```python
files = {
    "/path/to/root1": [
        {
            "path": "/path/to/root1/subdir",
            "filename": "photo.jpg",
            "size": 1234567,
            "md5": "abc123...",           # Only if MD5 mode
            "md5_read_size": 1234567      # Only if MD5 mode
        },
        # ... more file_info dicts
    ],
    "/path/to/root2": [
        # ... file_info dicts for root2
    ]
}
```

### Duplicate Files Dictionary

Returned by `find_duplicate_files()`:

```python
duplicate_files = {
    # Key depends on compare mode:
    # NAME: filename string
    # NAMESIZE: (filename, size) tuple
    # MD5: md5 hash string
    
    "photo.jpg": [                    # NAME mode key
        {"path": "...", "filename": "photo.jpg", "size": 1234},
        {"path": "...", "filename": "photo.jpg", "size": 1234}
    ],
    ("photo.jpg", 1234): [            # NAMESIZE mode key
        # ...
    ],
    "abc123def456...": [              # MD5 mode key
        # ...
    ]
}
```

### Args Namespace

Both CLI and GUI pass an `argparse.Namespace` with:

```python
args = Namespace(
    compare_mode=CompareMode.NAME,
    find_mode=FindMode.DEFAULT,
    md5_mode=MD5Mode.DEFAULT,
    md5_block_size=4096,
    md5_max_size=0,
    include_patterns=None,  # or ["pattern1", "pattern2"]
    iregex=False,
    directories=["dir1", "dir2"],
    # ... export options
)
```

---

## Core Algorithms

### File Discovery Algorithm

```
for each root_directory:
    if find_mode == FIND and has_gnu_find():
        use find_files_find()
    else:
        use find_files_default()
    
    for each file found:
        get_file_info(file)
        if compare_mode == MD5:
            calculate_md5(file)
```

### Duplicate Detection Algorithm

```
duplicate_files = {}

for each root_dir in files:
    for each file_info in files[root_dir]:
        key = generate_key(file_info, compare_mode)
        # NAME: filename
        # NAMESIZE: (filename, size)
        # MD5: md5_hash
        
        if key not in duplicate_files:
            duplicate_files[key] = []
        duplicate_files[key].append(file_info)

# Groups with len > 1 are duplicates
```

### MD5 Calculation

```python
def calculate_md5(args, file_path, file_size):
    if args.md5_mode == MD5Mode.DEFAULT:
        # Python hashlib
        md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            if args.md5_max_size > 0:
                # Read in chunks up to max_size
                for chunk in iter(lambda: f.read(block_size), b""):
                    md5.update(chunk)
                    if read_size > max_size:
                        break
            else:
                # Read entire file
                md5.update(f.read())
        return md5.hexdigest()
    
    elif args.md5_mode == MD5Mode.MD5SUM:
        # Shell out to md5sum
        result = subprocess.run(['md5sum', '-b', file_path], ...)
        return result.stdout.split()[0]
```

### MD5 Stability Check

When `--require-stable` is enabled, the `calculate_md5_with_stability_check()` function wraps MD5 calculation with file stability verification:

```python
def calculate_md5_with_stability_check(args, file_path, file_size) -> Tuple[str, int, bool, str]:
    """
    Returns (md5_hash, read_size, success, error_message)
    """
    if args.require_stable:
        # Get stats before hashing
        stat_before = os.stat(file_path)
        size_before, mtime_before = stat_before.st_size, stat_before.st_mtime
        
    md5_hash, read_size = calculate_md5(args, file_path, file_size)
    
    if args.require_stable:
        # Verify file didn't change during hashing
        stat_after = os.stat(file_path)
        if size_before != stat_after.st_size or mtime_before != stat_after.st_mtime:
            return ("", 0, False, "File changed during hashing")
    
    return (md5_hash, read_size, True, "")
```

The function includes retry logic (3 attempts with 0.5s delay) for handling transient file access errors.

### Threading Options

Two threading options control parallelism:

- **`--threads N`**: Controls threading for Phase 1 (file discovery and stat)
- **`--hash-threads N`**: Controls threading for Phase 2 (MD5 hashing only)

If `--hash-threads` is 0 (default), it uses the `--threads` value. This allows using different thread counts for discovery vs. hashing.

```python
# In _find_duplicate_files_md5_size_first():
hash_threads = getattr(args, 'hash_threads', 0) or 0
if hash_threads == 0:
    hash_threads = getattr(args, 'threads', 0) or 0

if hash_threads > 0:
    with ThreadPoolExecutor(max_workers=hash_threads) as executor:
        # Parallel MD5 computation
```

---

## Compare Modes Implementation

### NAME Mode

```python
fileid = file_info['filename']
```

Files grouped by filename only. Fast but may have collisions.

### NAMESIZE Mode

```python
fileid = (file_info['filename'], file_info['size'])
```

Files grouped by (filename, size) tuple. Reduces collisions.

### MD5 Mode

```python
fileid = file_info['md5']
```

Files grouped by MD5 hash. Most accurate, content-based.

---

## Find Modes Implementation

### DEFAULT Mode (`find_files_default`)

Uses `os.walk()`:

```python
for dir_path, _, file_names in os.walk(root_dir):
    for file_name in file_names:
        if matches_include_patterns(file_name):
            file_info = get_file_info(file_path)
            files[root_dir].append(file_info)
```

Pattern matching uses Python regex:

```python
normalized_pattern = pattern.replace(".", "\\.")
if re.search(normalized_pattern, filename):
    # match
```

### FIND Mode (`find_files_find`)

Uses GNU `find` command:

```python
if iregex:
    cmd = f"find {root_dir} -type f -iregex '{pattern}'"
else:
    cmd = f"find {root_dir} -type f -name '{pattern1}' -o -name '{pattern2}'"

result = subprocess.run(cmd, shell=True, capture_output=True)
for file_path in result.stdout.splitlines():
    file_info = get_file_info(file_path)
```

### GNU Find Detection

```python
def _has_gnu_find():
    find_path = shutil.which('find')
    if find_path is None:
        return False
    if sys.platform == 'win32':
        if 'system32' in find_path.lower():
            return False  # Windows find.exe is not GNU find
    return True
```

---

## GUI Architecture

### Main Window (`FdupGuiWindow`)

Inherits `QMainWindow`. Components:

- **Menu bar**: File → Export, Help → About
- **Config panel**: Left side with controls
- **Right panel**: Directories, Results tree, Output log

### Worker Thread (`ScanWorker`)

Runs scan in background to keep GUI responsive:

```python
class ScanWorker(QThread):
    results_ready = pyqtSignal(dict, list)
    error_occurred = pyqtSignal(str)
    log_message = pyqtSignal(str)
    
    def run(self):
        # Redirect stdout to capture log messages
        sys.stdout = QtLogStream()
        
        files = find_files(self.args, self.root_dirs)
        duplicates = find_duplicate_files(self.args, files)
        
        self.results_ready.emit(duplicates, self.root_dirs)
```

### Log Capture (`QtLogStream`)

Redirects stdout to GUI output panel:

```python
class QtLogStream(QObject):
    text_written = pyqtSignal(str)
    
    def write(self, text):
        self.text_written.emit(text)
```

---

## JSON Export

### Export Functions

```python
def save_duplicates_to_json(args, duplicate_files, filename, verbose=True):
    # Filter to groups with > 1 file
    real_duplicates = {k: v for k, v in duplicate_files.items() if len(v) > 1}
    
    json_data = {
        "cmdline": " ".join(sys.argv),
        "root_directories": args.directories,
        "duplicate_files": real_duplicates
    }
    
    with open(filename, 'w') as f:
        json.dump(json_data, f, indent=2)

def save_uniques_to_json(args, duplicate_files, filename, verbose=True):
    # Filter to groups with exactly 1 file
    real_uniques = {k: v for k, v in duplicate_files.items() if len(v) == 1}
    # ... similar structure
```

### Verbose Parameter

The `verbose` parameter controls stdout output:
- CLI uses `verbose=True` (default)
- GUI uses `verbose=False` to avoid duplicate output

---

## Extending fdup

### Adding a New Compare Mode

1. Add enum value in `fduplib.py`:

```python
class CompareMode(Enum):
    NAME = 'NAME'
    NAMESIZE = 'NAMESIZE'
    MD5 = 'MD5'
    SHA256 = 'SHA256'  # New mode
```

2. Update `get_file_info()` to calculate SHA256 when needed

3. Update `find_duplicate_files()` to generate key for new mode

4. Update CLI argparse choices

5. Update GUI dropdown

### Adding a New Output Format

1. Add new export function in `fduplib.py`:

```python
def save_duplicates_to_csv(args, duplicate_files, filename):
    # Implementation
```

2. Add CLI option in `configure_option_parser()`

3. Add GUI menu action

### Performance Optimization

Consider:
- **Parallel MD5 calculation**: Use `multiprocessing` or `concurrent.futures` (implemented via `--threads` and `--hash-threads`)
- **Streaming results**: Yield duplicates as found instead of collecting all
- **Pre-filtering by size**: Only calculate MD5 for files with matching sizes (implemented in MD5 mode)
- **Caching**: Store MD5 hashes for unchanged files
- **Stability checks**: Use `--require-stable` to skip files being modified during scan

### Size-First Optimization (MD5 Mode)

When using MD5 mode, fdup now uses a two-phase approach:

**Phase 1: Group by Size**
- Collect file metadata (path, filename, size) without computing MD5
- Group files by size across all root directories
- Files with unique sizes are immediately marked as non-duplicates

**Phase 2: Compute MD5 for Candidates**
- Only compute MD5 for files in size groups with >1 file
- This dramatically reduces the number of files that need to be hashed
- Especially beneficial for network shares where I/O is expensive

```
Example: 10,000 files scanned
- 8,500 have unique sizes -> skip MD5 (instant)
- 1,500 need MD5 computation -> hash only these
Result: 85% reduction in I/O
```
