# fdup User Manual

Version 1.0

## Table of Contents

1. [Introduction](#introduction)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Command Line Interface](#command-line-interface)
5. [GUI Application](#gui-application)
6. [Compare Modes](#compare-modes)
7. [Find Modes](#find-modes)
8. [Include Patterns](#include-patterns)
9. [JSON Export](#json-export)
10. [Troubleshooting](#troubleshooting)

---

## Introduction

**fdup** is a duplicate file finder that scans one or more directories and identifies files that are duplicates based on configurable criteria. It can compare files by:

- Filename only
- Filename and size
- MD5 checksum (content-based)

The tool is available as:
- A command-line application (`bin/fdup.py`)
- A graphical user interface (`bin/fdupgui.py`)

## Installation

### Requirements

- Python 3.7 or higher
- PyQt5 (for GUI only)

### Optional Dependencies

- **GNU find**: For faster file discovery on Linux/macOS
- **md5sum**: For external MD5 calculation

### Setup

```bash
# Clone the repository
git clone https://github.com/theocomp/fdup.git
cd fdup

# Install GUI dependencies (optional)
pip install PyQt5
```

## Quick Start

### CLI Quick Start

Find duplicates by filename:

```bash
python bin/fdup.py /path/to/directory1 /path/to/directory2
```

Find duplicates by MD5 and export:

```bash
python bin/fdup.py -c MD5 --exportdup2json /path/to/photos
```

### GUI Quick Start

```bash
python bin/fdupgui.py
```

1. Click "Add" to add root directories
2. Configure compare mode and patterns
3. Click "Run"
4. View results in the tree view
5. Export via File → Export menu

---

## Command Line Interface

### Synopsis

```
python bin/fdup.py [OPTIONS] DIRECTORY [DIRECTORY ...]
```

### Options Reference

#### General Options

| Option | Description |
|--------|-------------|
| `-v, --version` | Show program version and exit |
| `-h, --help` | Show help message and exit |

#### Compare Mode Options

| Option | Description |
|--------|-------------|
| `-c, --compare_mode` | How to compare files: `NAME`, `NAMESIZE`, `MD5` |

#### Find Mode Options

| Option | Description |
|--------|-------------|
| `-f, --find_mode` | How to discover files: `DEFAULT`, `FIND` |

#### MD5 Options

| Option | Description |
|--------|-------------|
| `--md5_mode` | MD5 calculation method: `DEFAULT`, `MD5SUM` |
| `--md5_block_size` | Block size in bytes for reading files (default: 4096) |
| `--md5_max_size` | Maximum KB to read for MD5 (0 = full file) |
| `--hash-threads N` | Number of threads for MD5 hashing (0 = use --threads value) |
| `--require-stable` | Skip files that change during MD5 hashing (checks size/mtime) |

#### Pattern Options

| Option | Description |
|--------|-------------|
| `--include_patterns` | Comma-separated patterns to filter files |
| `-iregex` | Treat patterns as iregex (FIND mode only) |

#### Export Options

| Option | Description |
|--------|-------------|
| `--exportdup2json [FILE]` | Export duplicates to JSON (default: `fdup_duplicate_files.json`) |
| `--exportuni2json [FILE]` | Export unique files to JSON (default: `fdup_unique_files.json`) |
| `--exportcu2script [FILE]` | Export cleanup script (default: `fdup_cleanup.sh` or `.bat`) |
| `--script_type` | Script type: `BASH`, `BAT` (default: `BASH`) |
| `--load_configuration [FILE]` | Load configuration from JSON (default: `fdup_cfg.json`) |
| `--save_configuration [FILE]` | Save configuration to JSON (default: `fdup_cfg.json`) |

### CLI Examples

#### Basic Usage

```bash
# Scan a single directory
python bin/fdup.py ~/Photos

# Scan multiple directories
python bin/fdup.py ~/Photos ~/Backup/Photos ~/External/Photos
```

#### Using Compare Modes

```bash
# Compare by filename only (fastest, may have false positives)
python bin/fdup.py -c NAME ~/Photos

# Compare by filename and size (good balance)
python bin/fdup.py -c NAMESIZE ~/Photos

# Compare by MD5 (most accurate, slowest)
python bin/fdup.py -c MD5 ~/Photos
```

#### Filtering Files

```bash
# Only scan JPEG files (DEFAULT mode)
python bin/fdup.py --include_patterns ".jpg,.jpeg" ~/Photos

# Only scan JPEG files (FIND mode with glob)
python bin/fdup.py -f FIND --include_patterns "*.jpg,*.jpeg" ~/Photos

# Use iregex pattern (FIND mode only)
python bin/fdup.py -f FIND -iregex --include_patterns ".*\.(jpg|png|gif)$" ~/Photos
```

#### Exporting Results

```bash
# Export duplicates with default filename
python bin/fdup.py --exportdup2json ~/Photos

# Export duplicates with custom filename
python bin/fdup.py --exportdup2json my_duplicates.json ~/Photos

# Export both duplicates and uniques
python bin/fdup.py --exportdup2json --exportuni2json ~/Photos

# Generate a cleanup script (BASH) - put directories first when omitting filename
python bin/fdup.py -c MD5 ~/Photos ~/Backup --exportcu2script

# Or use '--' separator
python bin/fdup.py -c MD5 --exportcu2script -- ~/Photos ~/Backup

# With explicit filename (use = or place after flag)
python bin/fdup.py -c MD5 --exportcu2script=cleanup.sh ~/Photos ~/Backup

# Generate a Windows BAT cleanup script
python bin/fdup.py -c MD5 ~/Photos ~/Backup --exportcu2script --script_type BAT

# Save configuration for reuse
python bin/fdup.py -c MD5 --include_patterns ".jpg,.png" ~/Photos --save_configuration

# Load and run with saved configuration
python bin/fdup.py --load_configuration

# Load config, override compare mode, and save merged config
python bin/fdup.py --load_configuration -c NAMESIZE --save_configuration=my_config.json
```

---

## Configuration Files

Configuration files store scan settings in JSON format. The precedence order is:
1. **Defaults** - Program defaults
2. **Loaded configuration** - Values from `--load_configuration` file
3. **Command line options** - Explicit CLI arguments override loaded config

### Configuration File Format

```json
{
  "version": 1,
  "directories": ["/path/to/photos", "/path/to/backup"],
  "compare_mode": "MD5",
  "find_mode": "DEFAULT",
  "md5_mode": "DEFAULT",
  "md5_block_size": 4096,
  "md5_max_size": 0,
  "include_patterns": [".jpg", ".png"],
  "iregex": false,
  "script_type": "BASH"
}
```

### Using Both Options Together

When using `--load_configuration` and `--save_configuration` together:
- Configuration is loaded first
- CLI arguments override loaded values
- The **final merged configuration** is saved

---

## GUI Application

### Starting the GUI

```bash
python bin/fdupgui.py
```

### Interface Overview

The GUI window is divided into:

1. **Left Panel (Configuration)**
   - Compare Mode dropdown
   - MD5 Mode dropdown (enabled when Compare Mode is MD5)
   - MD5 Block Size spinner
   - MD5 Max Size spinner
   - Find Mode dropdown
   - Include Patterns list with Add/Edit/Delete buttons
   - iregex checkbox (enabled when Find Mode is FIND and GNU find is available)
   - Run, Clear, and Clear All buttons

2. **Right Panel**
   - **Root Directories**: List of directories to scan with Add/Delete buttons
   - **Results**: Tree view showing duplicate file groups
   - **Output**: Log panel showing scan progress and messages

### Menu Bar

- **File → Export**
  - **Duplicates2JSON**: Export duplicate files to JSON
  - **Uniques2JSON**: Export unique files to JSON
  - **Cleanup2Script**: Export checked files as BASH or BAT delete script
- **File → Configuration**
  - **Load**: Load configuration from JSON file
  - **Save**: Save current configuration to JSON file
  
- **Help → About**: Shows version, email, and company information

### Cleanup Checkbox Column

The Results tree includes a **Cleanup** checkbox column:
- **First file** in each duplicate group is **unchecked** (preserved)
- **Other duplicates** are **checked** by default (to be deleted)

You can toggle checkboxes to customize which files to delete. Use **File → Export → Cleanup2Script** to generate a script containing delete commands for all checked files.

### Script Type Setting

The **Script Type** dropdown in the Configuration panel controls the format of exported cleanup scripts:
- **BASH** (default on Linux/macOS): Generates `fdup_cleanup.sh` with `rm -f` commands
- **BAT** (default on Windows): Generates `fdup_cleanup.bat` with `del /F /Q` commands

### Workflow

1. **Add directories**: Click "Add" in Root Directories panel
2. **Configure options**: Set compare mode, patterns, etc.
3. **Run scan**: Click "Run" button
4. **Review results**: Expand groups in the Results tree
5. **Export if needed**: Use File → Export menu
6. **Clear for next scan**: Click "Clear" before running again

---

## Compare Modes

### NAME Mode

Compares files by filename only. Two files are considered duplicates if they have the same filename, regardless of content or size.

**Pros:**
- Fastest comparison
- Good for finding renamed copies

**Cons:**
- May report false positives (different files with same name)

### NAMESIZE Mode

Compares files by both filename and size. Two files are considered duplicates if they have the same filename AND the same file size.

**Pros:**
- Fast comparison
- Reduces false positives compared to NAME mode

**Cons:**
- May still have false positives for files with same size

### MD5 Mode

Compares files by MD5 checksum. Two files are considered duplicates if they have the same MD5 hash.

**Pros:**
- Most accurate (content-based)
- Catches identical files with different names

**Cons:**
- Slowest (must read file contents)
- Can be optimized with `--md5_max_size`

---

## Find Modes

### DEFAULT Mode

Uses Python's built-in `os.walk()` to traverse directories.

**Pros:**
- Works on all platforms
- No external dependencies

**Cons:**
- May be slower for very large directory trees

### FIND Mode

Uses the GNU `find` command to discover files.

**Pros:**
- Faster for large directory trees
- Supports iregex patterns

**Cons:**
- Requires GNU find (Linux/macOS)
- Not available on Windows by default

**Note:** If FIND mode is selected but GNU find is not available, the tool automatically falls back to DEFAULT mode.

---

## Include Patterns

### DEFAULT Mode Patterns

Patterns are treated as Python regex fragments. The pattern is searched anywhere in the filename.

Examples:
- `.jpg` - matches files containing ".jpg"
- `.jpg,.png` - matches files containing ".jpg" or ".png"

### FIND Mode Patterns (without -iregex)

Patterns are passed to `find -name`. Use glob syntax.

Examples:
- `*.jpg` - matches files ending in ".jpg"
- `*.jpg,*.png` - matches files ending in ".jpg" or ".png"

### FIND Mode Patterns (with -iregex)

Only one pattern allowed. Pattern is passed to `find -iregex`.

Examples:
- `.*\.(jpg|png|gif)$` - matches files ending in .jpg, .png, or .gif (case-insensitive)

---

## JSON Export

### Duplicates JSON Format

```json
{
  "cmdline": "python bin/fdup.py -c MD5 --exportdup2json /path/to/photos",
  "root_directories": ["/path/to/photos"],
  "duplicate_files": {
    "photo.jpg": [
      {
        "path": "/path/to/photos/vacation",
        "filename": "photo.jpg",
        "size": 1234567
      },
      {
        "path": "/path/to/photos/backup",
        "filename": "photo.jpg",
        "size": 1234567
      }
    ]
  }
}
```

### Uniques JSON Format

```json
{
  "cmdline": "python bin/fdup.py --exportuni2json /path/to/photos",
  "root_directories": ["/path/to/photos"],
  "unique_files": {
    "unique_photo.jpg": [
      {
        "path": "/path/to/photos",
        "filename": "unique_photo.jpg",
        "size": 987654
      }
    ]
  }
}
```

---

## Troubleshooting

### "GNU find not found" message

This appears when FIND mode is selected on Windows or when GNU find is not installed. The tool automatically falls back to DEFAULT mode.

**Solution:** Use DEFAULT mode, or install GNU find (e.g., via Git Bash, Cygwin, or WSL on Windows).

### Invalid include pattern error

This occurs when a pattern is not valid for the selected mode.

**Solutions:**
- For DEFAULT mode: Use regex-compatible patterns (e.g., `.jpg` not `*.jpg`)
- For FIND mode: Use glob patterns (e.g., `*.jpg`)
- For FIND with -iregex: Use a single regex pattern

### Slow MD5 scanning

MD5 mode reads file contents, which is slow for large files.

**Solutions:**
- Use `--md5_max_size` to limit how much of each file is read
- Use NAMESIZE mode as a pre-filter
- Use `--threads N` or `--hash-threads N` to parallelize file processing and hashing (useful for network shares)

### Files skipped due to instability

When using `--require-stable`, files that change during hashing are skipped.

**Cause:** A file's size or modification time changed between the start and end of hashing, indicating the file is being actively modified.

**Solutions:**
- Wait for file transfers or writes to complete before scanning
- Remove the `--require-stable` flag if you don't need stability checks

### GUI "Clear Required" message

The GUI requires you to click "Clear" before running a new scan.

**Solution:** Click the "Clear" button to reset results before running again.
