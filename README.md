# fdup - Duplicate File Finder

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Python tool to find duplicate files across multiple directories. Available as both a command-line tool and a PyQt5 GUI application.

## Features

- **Multiple compare modes:**
  - `NAME` - Compare files by filename only
  - `NAMESIZE` - Compare files by filename and size
  - `MD5` - Compare files by MD5 checksum (most accurate)

- **Flexible file discovery:**
  - `DEFAULT` - Native Python file walker
  - `FIND` - Use GNU `find` command (faster for large directory trees)

- **Include patterns:** Filter files by extension or regex patterns

- **JSON export:** Export duplicate and unique file lists to JSON

- **Cleanup script export:** Generate BASH or BAT scripts to delete duplicates while preserving one copy

- **GUI application:** PyQt5-based graphical interface

## Requirements

- Python 3.7+
- PyQt5 (for GUI only)
- Optional: GNU `find` (for FIND mode on Linux/macOS)
- Optional: `md5sum` (for MD5SUM mode)

## Installation

Clone the repository:

```bash
git clone https://github.com/theocomp/fdup.git
cd fdup
```

Install PyQt5 for the GUI (optional):

```bash
pip install PyQt5
```

## Usage

### Command Line

```bash
python bin/fdup.py [OPTIONS] DIRECTORY [DIRECTORY ...]
```

#### Options

| Option | Description |
|--------|-------------|
| `-v, --version` | Show version and exit |
| `-c, --compare_mode` | Compare mode: `NAME`, `NAMESIZE`, `MD5` (default: `NAME`) |
| `-f, --find_mode` | Find mode: `DEFAULT`, `FIND` (default: `DEFAULT`) |
| `--md5_mode` | MD5 mode: `DEFAULT`, `MD5SUM` (default: `DEFAULT`) |
| `--md5_block_size` | Block size for MD5 calculation in bytes (default: 4096) |
| `--md5_max_size` | Max file size to read for MD5 in KB, 0=full file (default: 0) |
| `--include_patterns` | Comma-separated list of include patterns |
| `-iregex` | Interpret include patterns as iregex for find command |
| `--exportdup2json` | Export duplicates to JSON (default: `fdup_duplicate_files.json`) |
| `--exportuni2json` | Export unique files to JSON (default: `fdup_unique_files.json`) |
| `--exportcu2script` | Export cleanup script to delete duplicates (default: `fdup_cleanup.sh` or `.bat`) |
| `--script_type` | Script type for cleanup export: `BASH`, `BAT` (default: `BASH`) |
| `--load_configuration` | Load configuration from JSON file (default: `fdup_cfg.json`) |
| `--save_configuration` | Save configuration to JSON file (default: `fdup_cfg.json`) |

#### Examples

Find duplicates by filename in two directories:

```bash
python bin/fdup.py ~/Photos ~/Backup/Photos
```

Find duplicates by MD5 checksum and export to JSON:

```bash
python bin/fdup.py -c MD5 --exportdup2json ~/Photos ~/Backup
```

Filter to only JPEG files:

```bash
python bin/fdup.py --include_patterns ".jpg,.jpeg" ~/Photos
```

Use GNU find with glob patterns:

```bash
python bin/fdup.py -f FIND --include_patterns "*.jpg,*.png" ~/Photos
```

Generate a cleanup script to delete duplicates (BASH):

```bash
# Put directories first, then the flag (when omitting filename)
python bin/fdup.py -c MD5 ~/Photos ~/Backup --exportcu2script

# Or use '--' separator
python bin/fdup.py -c MD5 --exportcu2script -- ~/Photos ~/Backup

# With explicit filename (use = or place after flag)
python bin/fdup.py -c MD5 --exportcu2script=cleanup.sh ~/Photos ~/Backup
```

Generate a Windows BAT cleanup script:

```bash
python bin/fdup.py -c MD5 ~/Photos ~/Backup --exportcu2script --script_type BAT
```

Save configuration for reuse:

```bash
python bin/fdup.py -c MD5 --include_patterns ".jpg,.png" ~/Photos --save_configuration
```

Load and run with saved configuration:

```bash
python bin/fdup.py --load_configuration
```

### GUI Application

```bash
python bin/fdupgui.py
```

The GUI provides:
- Directory management (add/remove root directories)
- Configuration panel for compare mode, find mode, patterns, and script type
- Results tree view showing duplicate file groups with **Cleanup checkboxes**
  - First file in each group is unchecked (preserved)
  - Other duplicates are checked by default (to be deleted)
- Output log panel
- File → Export menu:
  - **Duplicates2JSON** - Export duplicate files to JSON
  - **Uniques2JSON** - Export unique files to JSON
  - **Cleanup2Script** - Export checked files as BASH or BAT delete script
- Help → About dialog

## Output

### Console Output

Duplicates are printed grouped by their comparison key (filename, filename+size, or MD5):

```
  File: photo.jpg
    file: /path/to/dir1/photo.jpg, size: 1234567
    file: /path/to/dir2/photo.jpg, size: 1234567
Found: 5 which had duplicates in total
```

### JSON Export

Duplicates JSON structure:

```json
{
  "cmdline": "python bin/fdup.py ...",
  "root_directories": ["/path/to/dir1", "/path/to/dir2"],
  "duplicate_files": {
    "filename.jpg": [
      {"path": "/path/to/dir1", "filename": "filename.jpg", "size": 1234}
    ]
  }
}
```

## Documentation

- [User Manual](docs/um/README.md) - Complete usage guide
- [Implementation Manual](docs/im/README.md) - Architecture and internals

## Platform Notes

- **Windows:** GNU `find` is not available by default. The tool will automatically fall back to DEFAULT mode if FIND mode is selected but GNU find is not found.
- **Linux/macOS:** Both DEFAULT and FIND modes work. FIND mode may be faster for very large directory trees.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Author

- **TheoComp ApS**
- Email: jacob@theocomp.dk

## Version

v1.0
