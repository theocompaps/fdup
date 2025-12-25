"""
fdupgui - PyQt5 GUI wrapper for fdup duplicate file finder.

Run with: python ./bin/fdupgui.py
"""

import sys
import os
import re
import shutil
import argparse

# Add repo root to sys.path so we can import fdup package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QComboBox, QPushButton, QListWidget, QTreeWidget,
    QTreeWidgetItem, QSplitter, QFileDialog, QGroupBox, QMessageBox,
    QHeaderView, QPlainTextEdit, QSpinBox, QInputDialog, QCheckBox,
    QLabel, QMenuBar, QMenu, QAction, QProgressBar
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QFont

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
    export_selected_files_to_script,
    DEFAULT_CONFIG_FILENAME,
    load_scan_config,
    save_scan_config,
    ProgressEvent,
)


class QtLogStream(QObject):
    """Stream-like object that emits text via a Qt signal."""
    
    text_written = pyqtSignal(str)
    
    def write(self, text):
        if text:
            self.text_written.emit(text)
    
    def flush(self):
        pass


class ScanWorker(QThread):
    """Worker thread for running the duplicate scan without blocking the GUI."""
    
    results_ready = pyqtSignal(dict, list)  # (duplicate_files, root_dirs)
    error_occurred = pyqtSignal(str)
    log_message = pyqtSignal(str)  # For streaming log output
    progress = pyqtSignal(object)  # For progress events
    
    def __init__(self, args, root_dirs, enable_progress=False):
        super().__init__()
        self.args = args
        self.root_dirs = root_dirs
        self.enable_progress = enable_progress
    
    def _progress_callback(self, event: ProgressEvent):
        """Callback to emit progress events to the GUI."""
        self.progress.emit(event)
    
    def run(self):
        # Redirect stdout/stderr to capture log messages
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        log_stream = QtLogStream()
        log_stream.text_written.connect(self.log_message.emit)
        
        try:
            sys.stdout = log_stream
            sys.stderr = log_stream
            
            # Use progress callback if enabled
            progress_cb = self._progress_callback if self.enable_progress else None
            
            files = find_files(self.args, self.root_dirs, progress_cb)
            
            # Annotate each file_info with its root_dir for table rendering
            for root_dir, infos in files.items():
                for info in infos:
                    info['root_dir'] = root_dir
            
            duplicates = find_duplicate_files(self.args, files, progress_cb)
            self.results_ready.emit(duplicates, self.root_dirs)
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            # Always restore original stdout/stderr
            sys.stdout = old_stdout
            sys.stderr = old_stderr


class FdupGuiWindow(QMainWindow):
    """Main window for the fdup GUI."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("fdup - Duplicate File Finder")
        self.setMinimumSize(900, 600)
        
        self.worker = None
        self.has_run = False  # Track if a scan has been run (requires Clear before next run)
        self.last_duplicates = None  # Store last scan results for export
        self.last_args = None  # Store last args for export
        
        self._setup_ui()
        self._setup_menu()
    
    def _setup_ui(self):
        """Set up the user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        
        # Left column: configuration
        left_widget = self._create_config_panel()
        main_layout.addWidget(left_widget, stretch=1)
        
        # Right column: directories and results
        right_widget = self._create_right_panel()
        main_layout.addWidget(right_widget, stretch=3)
    
    def _setup_menu(self):
        """Set up the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        
        # Export submenu
        export_menu = QMenu("Export", self)
        file_menu.addMenu(export_menu)
        
        self.export_dup_action = QAction("Duplicates2JSON", self)
        self.export_dup_action.triggered.connect(self.on_export_duplicates)
        self.export_dup_action.setEnabled(False)
        export_menu.addAction(self.export_dup_action)
        
        self.export_uni_action = QAction("Uniques2JSON", self)
        self.export_uni_action.triggered.connect(self.on_export_uniques)
        self.export_uni_action.setEnabled(False)
        export_menu.addAction(self.export_uni_action)
        
        self.export_cleanup_action = QAction("Cleanup2Script", self)
        self.export_cleanup_action.triggered.connect(self.on_export_cleanup_script)
        self.export_cleanup_action.setEnabled(False)
        export_menu.addAction(self.export_cleanup_action)
        
        # Configuration submenu
        config_menu = QMenu("Configuration", self)
        file_menu.addMenu(config_menu)
        
        load_config_action = QAction("Load", self)
        load_config_action.triggered.connect(self.on_load_configuration)
        config_menu.addAction(load_config_action)
        
        save_config_action = QAction("Save", self)
        save_config_action.triggered.connect(self.on_save_configuration)
        config_menu.addAction(save_config_action)
        
        # Help menu
        help_menu = menubar.addMenu("Help")
        
        about_action = QAction("About", self)
        about_action.triggered.connect(self.on_about)
        help_menu.addAction(about_action)
    
    def on_export_duplicates(self):
        """Export duplicates to JSON file."""
        if self.last_duplicates is None or self.last_args is None:
            QMessageBox.warning(self, "No Data", "No scan results available to export.")
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Duplicates to JSON", "fdup_duplicate_files.json",
            "JSON Files (*.json);;All Files (*)"
        )
        if filename:
            try:
                save_duplicates_to_json(self.last_args, self.last_duplicates, filename, verbose=False)
                self.output_text.appendPlainText(f"Duplicates exported to {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export: {e}")
    
    def on_export_uniques(self):
        """Export unique files to JSON file."""
        if self.last_duplicates is None or self.last_args is None:
            QMessageBox.warning(self, "No Data", "No scan results available to export.")
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Uniques to JSON", "fdup_unique_files.json",
            "JSON Files (*.json);;All Files (*)"
        )
        if filename:
            try:
                save_uniques_to_json(self.last_args, self.last_duplicates, filename, verbose=False)
                self.output_text.appendPlainText(f"Uniques exported to {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export: {e}")
    
    def on_about(self):
        """Show About dialog."""
        QMessageBox.about(
            self,
            "About fdup",
            f"fdup {__version__}\n\n"
            f"Email: jacob@theocomp.dk\n"
            f"Company: TheoComp ApS"
        )
    
    def _create_config_panel(self):
        """Create the left configuration panel."""
        group = QGroupBox("Configuration")
        layout = QVBoxLayout(group)
        
        # Form layout for dropdowns
        form_layout = QFormLayout()
        
        # Compare mode dropdown
        self.compare_combo = QComboBox()
        self.compare_combo.addItems(["NAME", "NAMESIZE", "MD5"])
        self.compare_combo.currentTextChanged.connect(self._update_md5_controls_enabled)
        form_layout.addRow("Compare Mode:", self.compare_combo)
        
        # MD5 Mode dropdown (only active when compare_mode == MD5)
        self.md5_mode_combo = QComboBox()
        self.md5_mode_combo.addItems(["DEFAULT", "MD5SUM"])
        form_layout.addRow("MD5 Mode:", self.md5_mode_combo)
        
        # MD5 Block Size (bytes)
        self.md5_block_size_spin = QSpinBox()
        self.md5_block_size_spin.setRange(512, 1048576)
        self.md5_block_size_spin.setValue(4096)
        self.md5_block_size_spin.setSingleStep(512)
        form_layout.addRow("MD5 Block Size:", self.md5_block_size_spin)
        
        # MD5 Max Size (KB, 0 = full file)
        self.md5_max_size_spin = QSpinBox()
        self.md5_max_size_spin.setRange(0, 1048576)
        self.md5_max_size_spin.setValue(0)
        self.md5_max_size_spin.setSpecialValueText("Full file")
        form_layout.addRow("MD5 Max Size (KB):", self.md5_max_size_spin)
        
        # Find mode dropdown
        self.find_combo = QComboBox()
        self.find_combo.addItems(["DEFAULT", "FIND"])
        self.find_combo.currentTextChanged.connect(self._update_iregex_enabled)
        form_layout.addRow("Find Mode:", self.find_combo)
        
        layout.addLayout(form_layout)
        
        # Include Patterns panel
        patterns_label = QLabel("Include Patterns:")
        layout.addWidget(patterns_label)
        
        self.patterns_list = QListWidget()
        self.patterns_list.setMaximumHeight(80)
        layout.addWidget(self.patterns_list)
        
        # Pattern buttons
        pattern_btn_layout = QHBoxLayout()
        self.add_pattern_button = QPushButton("Add")
        self.add_pattern_button.clicked.connect(self.on_add_pattern)
        pattern_btn_layout.addWidget(self.add_pattern_button)
        
        self.edit_pattern_button = QPushButton("Edit")
        self.edit_pattern_button.clicked.connect(self.on_edit_pattern)
        pattern_btn_layout.addWidget(self.edit_pattern_button)
        
        self.delete_pattern_button = QPushButton("Delete")
        self.delete_pattern_button.clicked.connect(self.on_delete_pattern)
        pattern_btn_layout.addWidget(self.delete_pattern_button)
        layout.addLayout(pattern_btn_layout)
        
        # iregex checkbox (only enabled when find_mode == FIND)
        self.iregex_checkbox = QCheckBox("Use -iregex (FIND mode only)")
        layout.addWidget(self.iregex_checkbox)
        
        # Progress checkbox
        self.progress_checkbox = QCheckBox("Show progress")
        self.progress_checkbox.setChecked(True)  # Default enabled
        layout.addWidget(self.progress_checkbox)
        
        # Threads spinbox
        threads_form = QFormLayout()
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, 32)
        self.threads_spin.setValue(0)  # Default: off
        self.threads_spin.setSpecialValueText("Off")
        threads_form.addRow("Threads:", self.threads_spin)
        layout.addLayout(threads_form)
        
        # Script Type dropdown (for cleanup export)
        script_form = QFormLayout()
        self.script_type_combo = QComboBox()
        self.script_type_combo.addItems(["BASH", "BAT"])
        # Set platform-native default
        default_script_type = get_default_script_type()
        self.script_type_combo.setCurrentText(str(default_script_type))
        script_form.addRow("Script Type:", self.script_type_combo)
        layout.addLayout(script_form)
        
        # Set initial MD5 controls state
        self._update_md5_controls_enabled()
        self._update_iregex_enabled()
        
        # Spacer
        layout.addStretch()
        
        # Run button
        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self.on_run)
        layout.addWidget(self.run_button)
        
        # Clear button - clears results only
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.on_clear)
        layout.addWidget(self.clear_button)
        
        # Clear All button - clears root directories and results
        self.clear_all_button = QPushButton("Clear All")
        self.clear_all_button.clicked.connect(self.on_clear_all)
        layout.addWidget(self.clear_all_button)
        
        return group
    
    def _create_right_panel(self):
        """Create the right panel with directories, results, and output."""
        splitter = QSplitter(Qt.Vertical)
        
        # Upper pane: root directories
        upper_widget = self._create_directories_panel()
        splitter.addWidget(upper_widget)
        
        # Middle pane: results tree
        middle_widget = self._create_results_panel()
        splitter.addWidget(middle_widget)
        
        # Lower pane: output log
        lower_widget = self._create_output_panel()
        splitter.addWidget(lower_widget)
        
        # Set initial sizes (directories smaller, results larger, output medium)
        splitter.setSizes([150, 300, 150])
        
        return splitter
    
    def _create_directories_panel(self):
        """Create the root directories management panel."""
        group = QGroupBox("Root Directories")
        layout = QHBoxLayout(group)
        
        # List widget
        self.dir_list = QListWidget()
        layout.addWidget(self.dir_list, stretch=1)
        
        # Buttons
        button_layout = QVBoxLayout()
        
        self.add_button = QPushButton("Add")
        self.add_button.clicked.connect(self.on_add_dir)
        button_layout.addWidget(self.add_button)
        
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.on_delete_dir)
        button_layout.addWidget(self.delete_button)
        
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
        return group
    
    def _create_results_panel(self):
        """Create the results tree panel."""
        group = QGroupBox("Results")
        layout = QVBoxLayout(group)
        
        self.results_tree = QTreeWidget()
        self.results_tree.setHeaderLabels(["Item", "Size", "Cleanup"])
        self.results_tree.setColumnCount(3)
        header = self.results_tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        layout.addWidget(self.results_tree)
        
        return group
    
    def _create_output_panel(self):
        """Create the output log panel."""
        group = QGroupBox("Output")
        layout = QVBoxLayout(group)
        
        # Progress bars section
        progress_layout = QHBoxLayout()
        
        # Scan progress (indeterminate with counts)
        scan_layout = QVBoxLayout()
        self.scan_label = QLabel("Scanning: -")
        self.scan_label.setVisible(False)
        scan_layout.addWidget(self.scan_label)
        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 0)  # Indeterminate
        self.scan_progress.setVisible(False)
        scan_layout.addWidget(self.scan_progress)
        progress_layout.addLayout(scan_layout)
        
        # Duplicate grouping progress (determinate with percentage)
        dups_layout = QVBoxLayout()
        self.dups_label = QLabel("Grouping: -")
        self.dups_label.setVisible(False)
        dups_layout.addWidget(self.dups_label)
        self.dups_progress = QProgressBar()
        self.dups_progress.setRange(0, 100)
        self.dups_progress.setVisible(False)
        dups_layout.addWidget(self.dups_progress)
        progress_layout.addLayout(dups_layout)
        
        layout.addLayout(progress_layout)
        
        self.output_text = QPlainTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFont(QFont("Consolas", 9))
        self.output_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self.output_text)
        
        return group
    
    def on_add_dir(self):
        """Handle Add button click - open directory picker."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Root Directory",
            "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        
        if directory:
            # Check for duplicates
            existing = [self.dir_list.item(i).text() for i in range(self.dir_list.count())]
            if directory not in existing:
                self.dir_list.addItem(directory)
    
    def on_delete_dir(self):
        """Handle Delete button click - remove selected directory."""
        current_row = self.dir_list.currentRow()
        if current_row >= 0:
            self.dir_list.takeItem(current_row)
    
    def on_add_pattern(self):
        """Handle Add pattern button click - prompt for pattern string."""
        text, ok = QInputDialog.getText(self, "Add Include Pattern", "Pattern:")
        if ok and text:
            # Check for duplicates
            existing = [self.patterns_list.item(i).text() for i in range(self.patterns_list.count())]
            if text not in existing:
                self.patterns_list.addItem(text)
    
    def on_delete_pattern(self):
        """Handle Delete pattern button click - remove selected pattern."""
        current_row = self.patterns_list.currentRow()
        if current_row >= 0:
            self.patterns_list.takeItem(current_row)
    
    def on_edit_pattern(self):
        """Handle Edit pattern button click - edit selected pattern."""
        current_row = self.patterns_list.currentRow()
        if current_row >= 0:
            current_item = self.patterns_list.item(current_row)
            current_text = current_item.text()
            text, ok = QInputDialog.getText(self, "Edit Include Pattern", "Pattern:", text=current_text)
            if ok and text:
                current_item.setText(text)
    
    def _has_gnu_find(self):
        """Check if GNU find is available on the system."""
        find_path = shutil.which('find')
        if find_path is None:
            return False
        if sys.platform == 'win32':
            if 'system32' in find_path.lower():
                return False
        return True
    
    def _validate_include_patterns(self, patterns, find_mode, iregex):
        """Validate include patterns for the selected mode.
        
        Returns (is_valid, error_message).
        """
        if not patterns:
            return (True, None)
        
        # Check iregex constraint: only 1 pattern allowed
        if iregex and len(patterns) > 1:
            return (False, "Only one include pattern can be specified when -iregex is enabled.")
        
        # If FIND mode and GNU find is available, patterns are OK as-is (glob or iregex)
        if find_mode == FindMode.FIND and self._has_gnu_find():
            return (True, None)
        
        # Otherwise patterns must be valid Python regex (DEFAULT mode or FIND fallback)
        for pattern in patterns:
            normalized = pattern.replace(r".", r"\.")
            try:
                re.compile(normalized)
            except re.error as e:
                return (False, f"The include pattern \"{pattern}\" is malformed (invalid regex).\nPlease correct it.")
        
        return (True, None)
    
    def on_run(self):
        """Handle Run button click - start duplicate scan."""
        # Check if we need to clear first
        if self.has_run:
            QMessageBox.warning(self, "Clear Required", "Please press Clear before running again")
            return
        
        # Get root directories
        root_dirs = [self.dir_list.item(i).text() for i in range(self.dir_list.count())]
        
        if not root_dirs:
            QMessageBox.warning(self, "No Directories", "Please add at least one root directory")
            return
        
        # Validate directories exist
        for d in root_dirs:
            if not os.path.isdir(d):
                QMessageBox.warning(self, "Invalid Directory", f"Directory does not exist: {d}")
                return
        
        # Get include patterns (None if empty list)
        patterns = [self.patterns_list.item(i).text() for i in range(self.patterns_list.count())]
        include_patterns = patterns if patterns else None
        
        # Validate include patterns before starting scan
        find_mode = FindMode[self.find_combo.currentText()]
        iregex = self.iregex_checkbox.isChecked()
        is_valid, error_msg = self._validate_include_patterns(patterns, find_mode, iregex)
        if not is_valid:
            QMessageBox.warning(self, "Invalid Include Pattern", error_msg)
            return
        
        # Build args object
        args = argparse.Namespace(
            compare_mode=CompareMode[self.compare_combo.currentText()],
            find_mode=FindMode[self.find_combo.currentText()],
            md5_mode=MD5Mode[self.md5_mode_combo.currentText()],
            md5_block_size=self.md5_block_size_spin.value(),
            md5_max_size=self.md5_max_size_spin.value(),
            include_patterns=include_patterns,
            iregex=self.iregex_checkbox.isChecked(),
            directories=root_dirs,
            threads=self.threads_spin.value(),
            save2json=False,
            save_unique=False,
            json_filename="duplicate_files.json",
            json_unique_filename="unique_files.json",
        )
        
        # Store args for export
        self.last_args = args
        
        # Disable controls while running
        self._set_controls_enabled(False)
        self.run_button.setText("Running...")
        
        # Clear previous results
        self.results_tree.clear()
        
        # Show/hide progress bars based on checkbox
        enable_progress = self.progress_checkbox.isChecked()
        self.scan_label.setVisible(enable_progress)
        self.scan_progress.setVisible(enable_progress)
        self.dups_label.setVisible(enable_progress)
        self.dups_progress.setVisible(enable_progress)
        if enable_progress:
            self.scan_label.setText("Scanning: -")
            self.dups_label.setText("Grouping: -")
            self.dups_progress.setValue(0)
        
        # Start worker thread
        self.worker = ScanWorker(args, root_dirs, enable_progress)
        self.worker.results_ready.connect(self._on_results_ready)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.log_message.connect(self._on_log_message)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_scan_finished)
        self.worker.start()
    
    def _update_md5_controls_enabled(self):
        """Enable or disable MD5 controls based on compare mode."""
        is_md5 = self.compare_combo.currentText() == "MD5"
        self.md5_mode_combo.setEnabled(is_md5)
        self.md5_block_size_spin.setEnabled(is_md5)
        self.md5_max_size_spin.setEnabled(is_md5)
    
    def _update_iregex_enabled(self):
        """Enable or disable iregex checkbox based on find mode and GNU find availability."""
        is_find = self.find_combo.currentText() == "FIND"
        has_gnu_find = self._has_gnu_find()
        
        # iregex only works with actual GNU find
        enable_iregex = is_find and has_gnu_find
        self.iregex_checkbox.setEnabled(enable_iregex)
        if not enable_iregex:
            self.iregex_checkbox.setChecked(False)
        
        # Show info message if FIND mode selected but no GNU find
        if is_find and not has_gnu_find:
            self.output_text.appendPlainText("GNU find not found; -iregex disabled (FIND will revert to DEFAULT)")
    
    def _set_controls_enabled(self, enabled):
        """Enable or disable controls during scan."""
        self.run_button.setEnabled(enabled)
        self.add_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        self.compare_combo.setEnabled(enabled)
        self.find_combo.setEnabled(enabled)
        self.add_pattern_button.setEnabled(enabled)
        self.edit_pattern_button.setEnabled(enabled)
        self.delete_pattern_button.setEnabled(enabled)
        self.patterns_list.setEnabled(enabled)
        if enabled:
            self._update_md5_controls_enabled()
            self._update_iregex_enabled()
        else:
            self.md5_mode_combo.setEnabled(False)
            self.md5_block_size_spin.setEnabled(False)
            self.md5_max_size_spin.setEnabled(False)
            self.iregex_checkbox.setEnabled(False)
    
    def _on_results_ready(self, duplicates, root_dirs):
        """Handle scan results - populate tree view."""
        # Store results for export
        self.last_duplicates = duplicates
        
        # Filter to only groups with duplicates
        groups = [(key, items) for key, items in duplicates.items() if len(items) > 1]
        
        self.results_tree.clear()
        
        if len(groups) == 0:
            self.output_text.appendPlainText("No duplicate files found.")
            return
        
        for group_key, items in groups:
            # Count total occurrences and unique roots
            total_occurrences = len(items)
            
            # Determine group label based on compare mode
            if isinstance(group_key, tuple):
                # NAMESIZE mode: (filename, size)
                group_label = f"{group_key[0]} ({total_occurrences} occurrences)"
            else:
                # NAME or MD5 mode
                group_label = f"{group_key} ({total_occurrences} occurrences)"
            
            # Create group node
            group_item = QTreeWidgetItem([group_label, "", ""])
            self.results_tree.addTopLevelItem(group_item)
            
            # Build mapping: root_dir -> list of file_info dicts
            root_to_files = {}
            for info in items:
                root_dir = info.get('root_dir', '')
                if root_dir not in root_to_files:
                    root_to_files[root_dir] = []
                root_to_files[root_dir].append(info)
            
            # Track file index within this duplicate group (to determine first file)
            file_index_in_group = 0
            
            # Add root dir children
            for root_dir, file_list in root_to_files.items():
                root_item = QTreeWidgetItem([f"{root_dir} ({len(file_list)})", "", ""])
                group_item.addChild(root_item)
                
                # Add file children with checkboxes
                for info in file_list:
                    rel_dir = os.path.relpath(info['path'], root_dir)
                    if rel_dir == '.':
                        rel_path = info['filename']
                    else:
                        rel_path = os.path.join(rel_dir, info['filename'])
                    
                    file_item = QTreeWidgetItem([rel_path, str(info.get('size', 0)), ""])
                    
                    # Store full path data for export (using UserRole on column 0)
                    full_path = os.path.join(info['path'], info['filename'])
                    file_item.setData(0, Qt.UserRole, full_path)
                    
                    # Make column 2 checkable - first file unchecked, rest checked
                    if file_index_in_group == 0:
                        file_item.setCheckState(2, Qt.Unchecked)
                    else:
                        file_item.setCheckState(2, Qt.Checked)
                    
                    root_item.addChild(file_item)
                    file_index_in_group += 1
            
            # Expand the group by default
            group_item.setExpanded(True)
        
        # Auto-size Size column to fit largest value
        self.results_tree.resizeColumnToContents(1)
        self.results_tree.resizeColumnToContents(2)
    
    def _on_progress(self, event):
        """Handle progress event from scan worker."""
        if event.stage == "scan":
            dirs = event.dirs_scanned if event.dirs_scanned is not None else 0
            files = event.files_scanned if event.files_scanned is not None else 0
            matched = event.files_matched if event.files_matched is not None else 0
            self.scan_label.setText(f"Scanning: dirs={dirs} files={files} matched={matched}")
        elif event.stage == "dups":
            processed = event.processed if event.processed is not None else 0
            total = event.total if event.total is not None else 0
            if total > 0:
                pct = int(100.0 * processed / total)
                self.dups_progress.setValue(pct)
                self.dups_label.setText(f"Grouping: {processed}/{total} ({pct}%)")
    
    def _on_log_message(self, text):
        """Handle log message from scan worker."""
        self.output_text.moveCursor(self.output_text.textCursor().End)
        self.output_text.insertPlainText(text)
        self.output_text.moveCursor(self.output_text.textCursor().End)
    
    def _on_error(self, error_msg):
        """Handle scan error."""
        QMessageBox.critical(self, "Scan Error", f"An error occurred during scan:\n{error_msg}")
    
    def _on_scan_finished(self):
        """Handle scan completion."""
        self._set_controls_enabled(True)
        self.run_button.setText("Run")
        self.worker = None
        self.has_run = True  # Mark that a scan has been completed
        # Enable export menu items
        self.export_dup_action.setEnabled(True)
        self.export_uni_action.setEnabled(True)
        self.export_cleanup_action.setEnabled(True)
        # Hide progress bars
        self.scan_label.setVisible(False)
        self.scan_progress.setVisible(False)
        self.dups_label.setVisible(False)
        self.dups_progress.setVisible(False)
    
    def on_export_cleanup_script(self):
        """Export cleanup script for checked files."""
        # Collect all checked file items
        selected_files = []
        
        def collect_checked_items(item):
            # Check if this is a file item (has UserRole data)
            full_path = item.data(0, Qt.UserRole)
            if full_path is not None:
                if item.checkState(2) == Qt.Checked:
                    selected_files.append(full_path)
            # Recurse into children
            for i in range(item.childCount()):
                collect_checked_items(item.child(i))
        
        # Iterate through all top-level items
        for i in range(self.results_tree.topLevelItemCount()):
            collect_checked_items(self.results_tree.topLevelItem(i))
        
        if not selected_files:
            QMessageBox.warning(self, "No Files Selected", "No files are checked for cleanup.")
            return
        
        # Determine script type and default filename
        script_type = ScriptType[self.script_type_combo.currentText()]
        if script_type == ScriptType.BAT:
            default_name = "fdup_cleanup.bat"
            file_filter = "Batch Files (*.bat);;All Files (*)"
        else:
            default_name = "fdup_cleanup.sh"
            file_filter = "Shell Scripts (*.sh);;All Files (*)"
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Cleanup Script", default_name, file_filter
        )
        
        if filename:
            try:
                export_selected_files_to_script(selected_files, filename, script_type, verbose=False)
                self.output_text.appendPlainText(f"Cleanup script exported to {filename} ({len(selected_files)} files)")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export: {e}")
    
    def on_clear(self):
        """Handle Clear button click - clear results and output."""
        self.results_tree.clear()
        self.output_text.clear()
        self.has_run = False
        self.last_duplicates = None
        self.last_args = None
        # Disable export menu items
        self.export_dup_action.setEnabled(False)
        self.export_uni_action.setEnabled(False)
        self.export_cleanup_action.setEnabled(False)
    
    def on_clear_all(self):
        """Handle Clear All button click - clear directories and results."""
        self.on_clear()
        self.dir_list.clear()
    
    def on_load_configuration(self):
        """Load configuration from JSON file via file dialog."""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Load Configuration", DEFAULT_CONFIG_FILENAME,
            "JSON Files (*.json);;All Files (*)"
        )
        if filename:
            self.load_configuration_file(filename)
    
    def load_configuration_file(self, filename):
        """Load configuration from specified file and populate UI."""
        try:
            cfg = load_scan_config(filename)
            
            # Clear current state
            self.on_clear_all()
            
            # Populate directories
            if 'directories' in cfg and cfg['directories']:
                for d in cfg['directories']:
                    self.dir_list.addItem(d)
            
            # Populate compare mode
            if 'compare_mode' in cfg:
                index = self.compare_combo.findText(cfg['compare_mode'])
                if index >= 0:
                    self.compare_combo.setCurrentIndex(index)
            
            # Populate find mode
            if 'find_mode' in cfg:
                index = self.find_combo.findText(cfg['find_mode'])
                if index >= 0:
                    self.find_combo.setCurrentIndex(index)
            
            # Populate MD5 mode
            if 'md5_mode' in cfg:
                index = self.md5_mode_combo.findText(cfg['md5_mode'])
                if index >= 0:
                    self.md5_mode_combo.setCurrentIndex(index)
            
            # Populate MD5 block size
            if 'md5_block_size' in cfg:
                self.md5_block_size_spin.setValue(cfg['md5_block_size'])
            
            # Populate MD5 max size
            if 'md5_max_size' in cfg:
                self.md5_max_size_spin.setValue(cfg['md5_max_size'])
            
            # Populate include patterns
            if 'include_patterns' in cfg and cfg['include_patterns']:
                for pattern in cfg['include_patterns']:
                    self.patterns_list.addItem(pattern)
            
            # Populate iregex
            if 'iregex' in cfg:
                self.iregex_checkbox.setChecked(cfg['iregex'])
            
            # Populate script type
            if 'script_type' in cfg:
                index = self.script_type_combo.findText(cfg['script_type'])
                if index >= 0:
                    self.script_type_combo.setCurrentIndex(index)
            
            # Populate progress checkbox
            if 'progress' in cfg:
                self.progress_checkbox.setChecked(cfg['progress'])
            
            # Populate threads
            if 'threads' in cfg:
                self.threads_spin.setValue(cfg['threads'])
            
            self.output_text.appendPlainText(f"Configuration loaded from {filename}")
            
        except FileNotFoundError:
            QMessageBox.critical(self, "Error", f"Configuration file not found: {filename}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load configuration: {e}")
    
    def on_save_configuration(self):
        """Save current configuration to JSON file via file dialog."""
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Configuration", DEFAULT_CONFIG_FILENAME,
            "JSON Files (*.json);;All Files (*)"
        )
        if filename:
            try:
                cfg = self._get_current_config_dict()
                save_scan_config(filename, cfg, verbose=False)
                self.output_text.appendPlainText(f"Configuration saved to {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save configuration: {e}")
    
    def _get_current_config_dict(self):
        """Get current UI configuration as a dictionary."""
        from fdup.fduplib import CONFIG_VERSION
        
        cfg = {
            'version': CONFIG_VERSION,
        }
        
        # Directories
        directories = [self.dir_list.item(i).text() for i in range(self.dir_list.count())]
        if directories:
            cfg['directories'] = directories
        
        # Compare mode
        cfg['compare_mode'] = self.compare_combo.currentText()
        
        # Find mode
        cfg['find_mode'] = self.find_combo.currentText()
        
        # MD5 mode
        cfg['md5_mode'] = self.md5_mode_combo.currentText()
        
        # MD5 block size
        cfg['md5_block_size'] = self.md5_block_size_spin.value()
        
        # MD5 max size
        cfg['md5_max_size'] = self.md5_max_size_spin.value()
        
        # Include patterns
        patterns = [self.patterns_list.item(i).text() for i in range(self.patterns_list.count())]
        cfg['include_patterns'] = patterns if patterns else None
        
        # iregex
        cfg['iregex'] = self.iregex_checkbox.isChecked()
        
        # Script type
        cfg['script_type'] = self.script_type_combo.currentText()
        
        # Progress
        cfg['progress'] = self.progress_checkbox.isChecked()
        
        # Threads
        cfg['threads'] = self.threads_spin.value()
        
        return cfg


def main():
    # Parse GUI command line options
    parser = argparse.ArgumentParser(
        prog='fdupgui.py',
        description='PyQt5 GUI for fdup duplicate file finder.'
    )
    parser.add_argument("--load_configuration", nargs='?', const=DEFAULT_CONFIG_FILENAME, default=None,
                        metavar="FILENAME",
                        help=f"Load configuration from JSON file. Default filename: {DEFAULT_CONFIG_FILENAME}")
    args, _ = parser.parse_known_args()
    
    app = QApplication(sys.argv)
    window = FdupGuiWindow()
    
    # Load configuration if specified on command line
    if args.load_configuration:
        window.load_configuration_file(args.load_configuration)
    
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
