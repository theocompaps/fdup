import sys
import os
import argparse
import textwrap

# Add repo root to sys.path so we can import fdup package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fdup import __version__
from fdup.fduplib import (
    CompareMode,
    FindMode,
    MD5Mode,
    ScriptType,
    get_default_script_type,
    find_files,
    find_duplicate_files,
    save_duplicates_to_json,
    save_uniques_to_json,
    export_cleanup_to_script,
    DEFAULT_CONFIG_FILENAME,
    load_scan_config,
    save_scan_config,
    args_to_scan_config_dict,
    apply_scan_config_dict_to_args,
    ProgressEvent,
)


def list_of_strings(arg):
    return arg.split(',')


def configure_option_parser(argv=None):
    """Configure and parse command line options.

    Args:
        argv: Optional list of CLI args (without program name). If None,
              argparse will default to sys.argv[1:].

    Returns:
        argparse.Namespace: Parsed arguments.
    """
    # Phase A: Pre-parse to check for config file options
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--load_configuration", nargs='?', const=DEFAULT_CONFIG_FILENAME, default=None,
                            metavar="FILENAME")
    pre_parser.add_argument("--save_configuration", nargs='?', const=DEFAULT_CONFIG_FILENAME, default=None,
                            metavar="FILENAME")
    pre_args, remaining_argv = pre_parser.parse_known_args(argv)
    
    # Load configuration if specified
    loaded_config = None
    if pre_args.load_configuration:
        try:
            loaded_config = load_scan_config(pre_args.load_configuration)
            print(f"Loaded configuration from {pre_args.load_configuration}", flush=True)
        except FileNotFoundError:
            print(f"Error: Configuration file not found: {pre_args.load_configuration}", flush=True)
            sys.exit(1)
        except Exception as e:
            print(f"Error loading configuration: {e}", flush=True)
            sys.exit(1)
    
    # Phase B: Main parser
    parser = argparse.ArgumentParser(
        prog='fdup.py',
        description="Find duplicate files in specified root directories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent('''\
        additional information:
          Format for --include_patterns:

             INCLUDE_PATTERNS = '<pattern>,<pattern>,...,<pattern>'
 
            -f DEFAULT:
              <pattern> = Any extension or pattern include the '.', e.g. \'.jpg,.mp4'
 
            -f FIND - for iregex DISABLED:
              <pattern> = Input to the -name option for find, e.g. '*.jpg,*.mp4'
 
            -f FIND - for iregex ENABLED:
              <pattern> = Input to the -iregex option for find, e.g. '*\\.\\(jpg\\|gif\\|png\\|jpeg\\)$'
         ''')
    )

    parser.add_argument("-v", "--version", action="version", version=f"fdup {__version__}")
    # directories are optional if loaded from config
    parser.add_argument("directories", nargs='*', default=[], help="List of root directories to search for duplicate files")
    parser.add_argument("--exportdup2json", nargs='?', const="fdup_duplicate_files.json", default=None,
                        metavar="FILENAME",
                        help="Export duplicate files to JSON. Default filename: fdup_duplicate_files.json")
    parser.add_argument("--exportuni2json", nargs='?', const="fdup_unique_files.json", default=None,
                        metavar="FILENAME",
                        help="Export unique files to JSON. Default filename: fdup_unique_files.json")
    # DEPRECATED options (kept for backwards compatibility)
    parser.add_argument("--save2json", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--json_filename", default="duplicate_files.json", help=argparse.SUPPRESS)
    parser.add_argument("--save_unique", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--json_unique_filename", default="unique_files.json", help=argparse.SUPPRESS)
    parser.add_argument("-c", "--compare_mode", default="NAME", type=CompareMode, choices=list(CompareMode), help="Compare mode being used")
    parser.add_argument("-f", "--find_mode", default="DEFAULT", type=FindMode, choices=list(FindMode), help="Find mode being used")
    parser.add_argument("--md5_mode", default="DEFAULT", type=MD5Mode, choices=list(MD5Mode), help="MD5 mode being used")
    parser.add_argument("--md5_block_size", default=4096, type=int, help="Size when reading file in chunks (Bytes)")
    parser.add_argument("--md5_max_size", default=0, type=int, help="Max part of file being read ofr MD5 (KB)")
    parser.add_argument("--include_patterns", type=list_of_strings, help="List of include patterns")
    parser.add_argument('-iregex', action='store_true', help="--include_pattern interpreted as iregex for find command")
    # Determine platform-native default for script type
    default_script_type = get_default_script_type()
    default_script_filename = "fdup_cleanup.bat" if default_script_type == ScriptType.BAT else "fdup_cleanup.sh"
    
    parser.add_argument("--exportcu2script", nargs='?', const=default_script_filename, default=None,
                        metavar="FILENAME",
                        help=f"Export cleanup script to delete duplicates. Default filename: {default_script_filename}. NOTE: When omitting filename, place this flag AFTER directories or use '--' separator (e.g., 'fdup.py dir1 --exportcu2script' or 'fdup.py --exportcu2script -- dir1')")
    parser.add_argument("--script_type", default=str(default_script_type), type=ScriptType, choices=list(ScriptType),
                        help=f"Script type for --exportcu2script: BASH or BAT (default: {default_script_type})")
    
    # Configuration file options
    parser.add_argument("--load_configuration", nargs='?', const=DEFAULT_CONFIG_FILENAME, default=None,
                        metavar="FILENAME",
                        help=f"Load configuration from JSON file. Default filename: {DEFAULT_CONFIG_FILENAME}")
    parser.add_argument("--save_configuration", nargs='?', const=DEFAULT_CONFIG_FILENAME, default=None,
                        metavar="FILENAME",
                        help=f"Save configuration to JSON file. Default filename: {DEFAULT_CONFIG_FILENAME}")
    
    # Progress reporting option
    parser.add_argument("--progress", action="store_true",
                        help="Enable progress reporting (shows live counts during scan and duplicate detection)")
    
    # Threading option
    parser.add_argument("--threads", type=int, default=0, metavar="N",
                        help="Number of threads for file processing (0 = disabled, default: 0). Useful for network shares with MD5 mode.")

    args = parser.parse_args(argv)
    
    # Apply loaded configuration first, then CLI overrides
    if loaded_config:
        # Start with loaded config values
        apply_scan_config_dict_to_args(args, loaded_config)
        
        # Re-parse to apply CLI overrides on top of loaded config
        # We need to check which CLI args were explicitly provided
        cli_args = parser.parse_args(argv)
        
        # Override with explicitly provided CLI args
        # directories: if CLI provided any, use those instead
        if cli_args.directories:
            args.directories = cli_args.directories
    
    # Store config file options from pre-parser
    args.load_configuration = pre_args.load_configuration
    args.save_configuration = pre_args.save_configuration
    
    # Validate that we have directories
    if not args.directories:
        parser.error("directories are required (provide on command line or in configuration file)")
    
    return args


def _cli_progress_callback(event: ProgressEvent):
    """Progress callback for CLI that prints to stderr."""
    if event.stage == "scan":
        dirs = event.dirs_scanned if event.dirs_scanned is not None else 0
        files = event.files_scanned if event.files_scanned is not None else 0
        matched = event.files_matched if event.files_matched is not None else 0
        root = event.root_dir if event.root_dir else ""
        # Use carriage return to update in place
        print(f"\rScanning: dirs={dirs} files={files} matched={matched} ({root[:40]}...)", end="", file=sys.stderr, flush=True)
    elif event.stage == "dups":
        processed = event.processed if event.processed is not None else 0
        total = event.total if event.total is not None else 0
        if total > 0:
            pct = 100.0 * processed / total
            print(f"\rGrouping: {processed}/{total} ({pct:.1f}%)", end="", file=sys.stderr, flush=True)


def main():
    args = configure_option_parser()
    
    # Save configuration if requested (save final merged config)
    if args.save_configuration:
        cfg_dict = args_to_scan_config_dict(args)
        save_scan_config(args.save_configuration, cfg_dict)

    root_directories = args.directories
    
    # Setup progress callback if --progress was specified
    progress_cb = _cli_progress_callback if getattr(args, 'progress', False) else None

    files = find_files(args, root_directories, progress_cb)
    
    # Clear progress line before duplicate detection
    if progress_cb:
        print("", file=sys.stderr, flush=True)

    duplicate_files = find_duplicate_files(args, files, progress_cb)
    
    # Clear progress line after duplicate detection
    if progress_cb:
        print("", file=sys.stderr, flush=True)

    duplicate_cnt = 0

    if(len(duplicate_files.keys()) > 0):
        if args.md5_max_size > 0:
            md5_coverage_min = None
            md5_coverage_max = None


        for fileid in sorted(duplicate_files.keys()):
            if len(duplicate_files[fileid]) > 1:
                duplicate_cnt = duplicate_cnt + 1

                if args.compare_mode == CompareMode.NAME:
                    print("  File: " + fileid, flush=True)
                    for file_info in duplicate_files[fileid]:
                        print("    file: " + file_info['path'] + '/' + file_info['filename'] + ', size: ' + str(file_info['size']), flush=True)
                elif args.compare_mode == CompareMode.NAMESIZE:
                    (filename, size) = fileid
                    print("  File: " + filename, flush=True)
                    for file_info in duplicate_files[fileid]:
                        print("    file: " + file_info['path'] + '/' + file_info['filename'] + ', size: ' + str(file_info['size']), flush=True)
                elif args.compare_mode == CompareMode.MD5:
                    filename = duplicate_files[fileid][0]['filename']

                    print("  File: " + filename, flush=True)

                    for file_info in duplicate_files[fileid]:
                        if args.md5_max_size > 0:
                            if file_info['md5_read_size'] == 0 or file_info['md5_read_size'] == 0:
                                md5_coverage = 0
                            else:
                                md5_coverage = round(100.0*file_info['md5_read_size']/file_info['size'], 2)

                            if md5_coverage_min == None or md5_coverage < md5_coverage_min:
                                md5_coverage_min = md5_coverage

                            if md5_coverage_max == None or md5_coverage > md5_coverage_max:
                                md5_coverage_max = md5_coverage

                            print("    file: " + file_info['path'] + '/' + file_info['filename'] + ', size: ' + str(file_info['size']) + ', MD5 utilization: ' + str(md5_coverage), flush=True)
                        else:
                            print("    file: " + file_info['path'] + '/' + file_info['filename'] + ', size: ' + str(file_info['size']) + ', MD5: ' + str(file_info['md5']), flush=True)

        print("Found: " + str(duplicate_cnt) + " which had duplicates in total", flush=True)

        if args.compare_mode == CompareMode.MD5 and args.md5_max_size > 0:
            print("MD5 Utilization - Min: " + str(md5_coverage_min) + ' Max: ' + str(md5_coverage_max), flush=True)

        # Handle JSON export (new options take precedence over deprecated ones)
        if args.exportdup2json is not None:
            save_duplicates_to_json(args, duplicate_files, args.exportdup2json)
        elif args.save2json:
            # Deprecated option
            save_duplicates_to_json(args, duplicate_files, args.json_filename)
        
        if args.exportuni2json is not None:
            save_uniques_to_json(args, duplicate_files, args.exportuni2json)
        elif args.save_unique:
            # Deprecated option
            save_uniques_to_json(args, duplicate_files, args.json_unique_filename)
        
        # Handle cleanup script export
        if args.exportcu2script is not None:
            # Adjust default filename based on script type if user used default
            script_filename = args.exportcu2script
            if script_filename == "fdup_cleanup.sh" and args.script_type == ScriptType.BAT:
                script_filename = "fdup_cleanup.bat"
            export_cleanup_to_script(args, duplicate_files, script_filename, args.script_type)
    else:
        print("No duplicate files found.", flush=True)

if __name__ == "__main__":
    main()
