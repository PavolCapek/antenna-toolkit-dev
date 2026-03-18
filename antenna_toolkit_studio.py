#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QByteArray, Signal
from PySide6.QtGui import QColor, QPalette, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QAbstractItemView,
    QAbstractSpinBox,
    QComboBox, QColorDialog,
    QCheckBox,
    QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QProgressBar,
    QFormLayout, QFrame, QSplitter, QSizePolicy, QStyleFactory, QMessageBox, QInputDialog,
    QDialog, QDialogButtonBox
)

from antenna_toolkit_qt import (
    THIS_DIR, SCRIPT_BEAM, SCRIPT_EXTRACT, SCRIPT_PLOT, SCRIPT_VSWR,
    PRESET_STORE_KEY, ACTIVE_PRESET_KEY,
    suggest_preset_name, normalize_preset_payload,
    DEFAULT_GRID_COLOR, DEFAULT_LINE_COLORS, Persist, Proc,
    which_python, open_in_file_manager, resolve_workspace_path,
    display_workspace_path, deduce_project_name, normalized_project_stem,
)
from project_store import (
    ProjectRecord, ProjectStore, resolve_project_path, sanitize_project_slug,
    serialize_workspace_path,
)

APP_TITLE = "Antenna Toolkit Studio"
STATE_FILE = THIS_DIR / ".nova_qt_studio_state.json"
GREY_COLOR_OPTIONS = [
    ("Charcoal", "#4b5563"),
    ("Slate", "#6b7280"),
    ("Steel", "#858c96"),
    ("Silver", "#a1a1aa"),
    ("Mist", "#c4c7cf"),
]


def project_key(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def guess_touchstone_path(project: str, ffs_paths: list[str]) -> str:
    project = project.strip()
    if not project or project == "results":
        return ""
    key = project_key(project)

    preferred_exts = [".s1p", ".s2p"] if len(ffs_paths) <= 1 else [".s2p", ".s1p"]
    search_dirs: list[Path] = []
    for path in ffs_paths:
        parent = resolve_workspace_path(path).parent
        if parent not in search_dirs:
            search_dirs.append(parent)

    for extra in (THIS_DIR / "Input data", THIS_DIR):
        if extra not in search_dirs:
            search_dirs.append(extra)

    for directory in search_dirs:
        for ext in preferred_exts:
            candidate = (directory / f"{project}{ext}").resolve()
            if candidate.exists():
                return str(candidate)
            matches = sorted(
                (
                    p.resolve()
                    for p in directory.glob(f"*{ext}")
                    if project_key(normalized_project_stem(p.stem)) == key
                ),
                key=lambda p: (len(p.stem), p.name.lower()),
            )
            if matches:
                return str(matches[0])
    return ""


def apply_tooltip(widget: QWidget, text: str) -> None:
    widget.setToolTip(text)
    if isinstance(widget, StepperField):
        widget.spinbox.setToolTip(text)
        widget.minus.setToolTip(text)
        widget.plus.setToolTip(text)
    elif isinstance(widget, StudioColorSelector):
        widget.combo.setToolTip(text)
        widget.prev_btn.setToolTip(text)
        widget.next_btn.setToolTip(text)
        widget.pick.setToolTip(text)
        widget.swatch.setToolTip(text)


def add_form_row(form: QFormLayout, label: str, field: QWidget, tooltip: str) -> None:
    form.addRow(label, field)
    apply_tooltip(field, tooltip)
    label_widget = form.labelForField(field)
    if label_widget:
        label_widget.setToolTip(tooltip)


class Card(QFrame):
    def __init__(self, title: str, eyebrow: str = ""):
        super().__init__()
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(8)
        if eyebrow:
            brow = QLabel(eyebrow.upper())
            brow.setObjectName("eyebrow")
            outer.addWidget(brow)
        ttl = QLabel(title)
        ttl.setObjectName("cardTitle")
        outer.addWidget(ttl)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body, 1)


class DropList(QListWidget):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)

    def dragEnterEvent(self, e):
        if any(u.toLocalFile().lower().endswith(".ffs") for u in e.mimeData().urls()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith(".ffs")]
        if files:
            self.callback(files)
            e.acceptProposedAction()
        else:
            e.ignore()


class ProjectDialog(QDialog):
    def __init__(self, parent: QWidget, name: str = "", ffs_files: list[str] | None = None, touchstone_file: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Project")
        self.resize(760, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        form = QFormLayout()
        self.name_field = QLineEdit(name)
        self.name_field.setPlaceholderText("Project name")
        form.addRow("Name", self.name_field)
        layout.addLayout(form)

        layout.addWidget(QLabel("Far-field files (.ffs)"))
        self.ffs_list = DropList(self._add_ffs_files)
        self.ffs_list.setMinimumHeight(220)
        self.ffs_list.setToolTip("Files saved as part of the project definition.")
        layout.addWidget(self.ffs_list, 1)

        ffs_actions = QHBoxLayout()
        add_button = QPushButton("Add .ffs")
        add_button.clicked.connect(self.add_ffs)
        remove_button = QPushButton("Remove selected")
        remove_button.clicked.connect(self.remove_ffs)
        clear_button = QPushButton("Clear list")
        clear_button.clicked.connect(self.clear_ffs)
        ffs_actions.addWidget(add_button)
        ffs_actions.addWidget(remove_button)
        ffs_actions.addWidget(clear_button)
        ffs_actions.addStretch(1)
        layout.addLayout(ffs_actions)

        layout.addWidget(QLabel("Touchstone (.s1p/.s2p)"))
        touchstone_row = QHBoxLayout()
        self.touchstone_field = QLineEdit(display_workspace_path(touchstone_file))
        self.touchstone_field.setReadOnly(True)
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self.browse_touchstone)
        clear_touchstone = QPushButton("Clear")
        clear_touchstone.clicked.connect(self.clear_touchstone)
        touchstone_row.addWidget(self.touchstone_field, 1)
        touchstone_row.addWidget(browse_button)
        touchstone_row.addWidget(clear_touchstone)
        layout.addLayout(touchstone_row)

        note = QLabel("Processing controls and chart styles stay on the main screen and are saved into the selected project automatically.")
        note.setWordWrap(True)
        note.setObjectName("helper")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._add_ffs_files(ffs_files or [])

    def _item_path(self, item: QListWidgetItem) -> str:
        return item.data(Qt.UserRole) or str(resolve_workspace_path(item.text()))

    def _add_ffs_files(self, files: list[str]) -> None:
        existing = {self._item_path(self.ffs_list.item(i)) for i in range(self.ffs_list.count())}
        for path in files:
            actual = str(resolve_workspace_path(path))
            if actual.lower().endswith(".ffs") and actual not in existing:
                item = QListWidgetItem(display_workspace_path(actual))
                item.setData(Qt.UserRole, actual)
                self.ffs_list.addItem(item)
                existing.add(actual)

    def add_ffs(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Add .ffs", str(THIS_DIR), "CST Farfield (*.ffs)")
        if files:
            self._add_ffs_files(files)

    def remove_ffs(self) -> None:
        for item in list(self.ffs_list.selectedItems()):
            self.ffs_list.takeItem(self.ffs_list.row(item))

    def clear_ffs(self) -> None:
        self.ffs_list.clear()

    def browse_touchstone(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Touchstone", str(THIS_DIR), "Touchstone (*.s1p *.s2p)")
        if path:
            self.touchstone_field.setText(display_workspace_path(path))

    def clear_touchstone(self) -> None:
        self.touchstone_field.clear()

    def project_name(self) -> str:
        return self.name_field.text().strip()

    def ffs_files(self) -> list[str]:
        return [self._item_path(self.ffs_list.item(i)) for i in range(self.ffs_list.count())]

    def touchstone_file(self) -> str:
        value = self.touchstone_field.text().strip()
        return str(resolve_workspace_path(value)) if value else ""


class NoWheelSpinBox(QSpinBox):
    def __init__(self):
        super().__init__()
        self.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
        self.setAccelerated(True)

    def wheelEvent(self, event):
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def __init__(self):
        super().__init__()
        self.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
        self.setAccelerated(True)

    def wheelEvent(self, event):
        event.ignore()


class TrimmedDoubleSpinBox(NoWheelDoubleSpinBox):
    def textFromValue(self, value):
        text = f"{float(value):.6f}".rstrip("0").rstrip(".")
        return text if text else "0"


class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class StepperField(QWidget):
    def __init__(self, spinbox: QAbstractSpinBox):
        super().__init__()
        self.spinbox = spinbox
        self.spinbox.setButtonSymbols(QAbstractSpinBox.NoButtons)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.minus = QPushButton("-")
        self.minus.setObjectName("stepButton")
        self.minus.setFixedWidth(30)
        self.minus.clicked.connect(lambda: self.spinbox.stepBy(-1))

        self.plus = QPushButton("+")
        self.plus.setObjectName("stepButton")
        self.plus.setFixedWidth(30)
        self.plus.clicked.connect(lambda: self.spinbox.stepBy(1))

        lay.addWidget(self.minus)
        lay.addWidget(self.spinbox, 1)
        lay.addWidget(self.plus)


class StudioColorSelector(QWidget):
    colorChanged = Signal(str)

    def __init__(self, store: Persist, key: str, default: str, presets: list[tuple[str, str]] | None = None):
        super().__init__()
        self.store = store
        self.key = key
        self.default = default
        self.presets = presets or DEFAULT_LINE_COLORS
        self.preset_colors = [value for _, value in self.presets]
        self.custom_color = self._normalize(store.get(key, default), default)
        self.current_color = self.custom_color

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.prev_btn = QPushButton("<")
        self.prev_btn.setObjectName("stepButton")
        self.prev_btn.setFixedWidth(34)
        self.prev_btn.clicked.connect(lambda: self.step_preset(-1))

        self.combo = NoWheelComboBox()
        for name, value in self.presets:
            self.combo.addItem(f"{name} ({value})", value)
        self.combo.addItem("Custom", "__custom__")
        self.combo.currentIndexChanged.connect(self._on_combo_changed)

        self.next_btn = QPushButton(">")
        self.next_btn.setObjectName("stepButton")
        self.next_btn.setFixedWidth(34)
        self.next_btn.clicked.connect(lambda: self.step_preset(1))

        self.swatch = QFrame()
        self.swatch.setFixedSize(18, 18)
        self.swatch.setFrameShape(QFrame.StyledPanel)

        self.pick = QPushButton()
        self.pick.setObjectName("ghostButton")
        self.pick.setFixedWidth(90)
        self.pick.clicked.connect(self.pick_color)

        lay.addWidget(self.prev_btn)
        lay.addWidget(self.combo, 1)
        lay.addWidget(self.next_btn)
        lay.addWidget(self.swatch)
        lay.addWidget(self.pick)
        self.set_color(self.custom_color, persist=False)

    def _normalize(self, value: str | None, fallback: str) -> str:
        color = QColor(value or fallback)
        return color.name() if color.isValid() else QColor(fallback).name()

    def color(self) -> str:
        return self.current_color

    def set_color(self, value: str, persist: bool = True):
        color = self._normalize(value, self.default)
        self.current_color = color
        self.custom_color = color

        match_index = -1
        for i in range(self.combo.count() - 1):
            if str(self.combo.itemData(i)).lower() == color.lower():
                match_index = i
                break

        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(match_index if match_index >= 0 else self.combo.count() - 1)
        self.combo.blockSignals(False)
        self.pick.setText(color.upper())
        self.swatch.setStyleSheet(f"background:{color}; border:1px solid #6f7a81; border-radius:3px;")
        if persist:
            self.store.set(self.key, color)
        self.colorChanged.emit(color)

    def _on_combo_changed(self):
        value = self.combo.currentData()
        if value == "__custom__":
            self.set_color(self.custom_color)
            return
        self.set_color(str(value))

    def step_preset(self, delta: int):
        presets = [str(self.combo.itemData(i)) for i in range(self.combo.count() - 1)]
        current = self.current_color.lower()
        try:
            index = next(i for i, value in enumerate(presets) if value.lower() == current)
        except StopIteration:
            index = 0 if delta >= 0 else len(presets) - 1
        else:
            index = (index + delta) % len(presets)
        self.set_color(presets[index])

    def pick_color(self):
        color = QColorDialog.getColor(QColor(self.current_color), self, "Select color")
        if color.isValid():
            self.set_color(color.name())


class ConsoleWindow(QWidget):
    def __init__(self, owner: "ModernMainWindow", store: Persist):
        super().__init__(None, Qt.Window)
        self.owner = owner
        self.store = store
        self.setWindowTitle(f"{APP_TITLE} Console")
        self.resize(980, 320)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(5000)
        font = self.console.font()
        font.setFamily("Consolas")
        font.setPointSize(max(font.pointSize(), 10))
        self.console.setFont(font)
        lay.addWidget(self.console, 1)
        self._restore_geometry()

    def _restore_geometry(self):
        geo = self.store.get("console_geometry", None)
        if geo:
            try:
                ba = QByteArray.fromBase64(geo.encode("ascii"))
                self.restoreGeometry(ba)
            except Exception:
                pass

    def _save_geometry(self):
        try:
            ba = self.saveGeometry().toBase64().data().decode("ascii")
            self.store.set("console_geometry", ba)
        except Exception:
            pass

    def closeEvent(self, event):
        self._save_geometry()
        self.owner.on_console_popup_closed()
        super().closeEvent(event)


class ModernMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1460, 920)
        self.store = Persist(STATE_FILE)
        self.project_store = ProjectStore(THIS_DIR)
        self.proc = Proc(self)
        self._closing_app = False
        self._loading_project = False
        self.active_project_slug = str(self.store.get("active_project", "")).strip()
        self.active_project_name = ""
        self.theme = str(self.store.get("theme", "light")).lower()
        if self.theme not in {"light", "dark"}:
            self.theme = "light"
        self._build_ui()
        self._apply_style()
        self.refresh_project_list(select_slug=self.active_project_slug)
        self.store.set("theme", self.theme)
        self._restore_geometry()

    def _build_ui(self):
        root = QWidget()
        root_lay = QVBoxLayout(root)
        root_lay.setContentsMargins(16, 16, 16, 16)
        root_lay.setSpacing(12)

        hero = QFrame()
        hero.setObjectName("hero")
        hero.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        hero_lay = QHBoxLayout(hero)
        hero_lay.setContentsMargins(20, 18, 20, 18)
        hero_lay.setSpacing(14)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        self.hero_title = QLabel("Antenna Toolkit Studio")
        self.hero_title.setObjectName("heroTitle")
        self.project_badge = QLabel("Project: results")
        self.project_badge.setObjectName("badge")
        self.count_badge = QLabel("0 far-field files")
        self.count_badge.setObjectName("badge")
        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.setSpacing(8)
        badge_row.addWidget(self.project_badge)
        badge_row.addWidget(self.count_badge)
        badge_row.addStretch(1)
        title_col.addWidget(self.hero_title)
        title_col.addLayout(badge_row)
        hero_lay.addLayout(title_col, 1)

        action_col = QVBoxLayout()
        action_col.setSpacing(8)
        run_row = QHBoxLayout()
        run_row.setContentsMargins(0, 0, 0, 0)
        run_row.setSpacing(8)
        self.btn_full = QPushButton("Run Full Pipeline")
        self.btn_full.setObjectName("primaryButton")
        self.btn_full.clicked.connect(self.run_full)
        self.btn_beam = QPushButton("Workbook Only")
        self.btn_beam.clicked.connect(self.run_beam)
        self.btn_extract = QPushButton("Extract Data")
        self.btn_extract.clicked.connect(self.run_extract)
        self.btn_plot = QPushButton("Plots Only")
        self.btn_plot.clicked.connect(self.run_plot)
        self.btn_vswr = QPushButton("VSWR Only")
        self.btn_vswr.clicked.connect(self.run_vswr)
        self.console_toggle = QPushButton()
        self.console_toggle.setObjectName("ghostButton")
        self.console_toggle.setCheckable(True)
        self.console_toggle.clicked.connect(self.toggle_console)
        self.theme_toggle = QPushButton()
        self.theme_toggle.setObjectName("themeToggle")
        self.theme_toggle.setCheckable(True)
        self.theme_toggle.clicked.connect(self.toggle_theme)
        self.btn_full.setToolTip("Run workbook generation, chart generation, and VSWR generation in sequence.")
        self.btn_beam.setToolTip("Generate only the Excel workbook from the selected far-field files.")
        self.btn_extract.setToolTip("Generate a separate Excel workbook with extracted gain, beamwidth, VSWR, impedance, and front-to-back metrics.")
        self.btn_plot.setToolTip("Generate only the plots that are based on the derived workbook.")
        self.btn_vswr.setToolTip("Generate only the VSWR plot from the current Touchstone file.")
        self.console_toggle.setToolTip("Show or hide the separate output console window.")
        self.theme_toggle.setToolTip("Switch between the light and dark studio themes.")
        run_row.addWidget(self.btn_full)
        run_row.addWidget(self.btn_beam)
        run_row.addWidget(self.btn_extract)
        run_row.addWidget(self.btn_plot)
        run_row.addWidget(self.btn_vswr)
        run_row.addWidget(self.console_toggle)
        run_row.addWidget(self.theme_toggle)
        self.run_info = QLabel("Idle")
        self.run_info.setObjectName("runInfo")
        self.busy = QProgressBar()
        self.busy.setVisible(False)
        self.busy.setRange(0, 0)
        self.busy.setFixedWidth(220)
        info_row = QHBoxLayout()
        info_row.setContentsMargins(0, 0, 0, 0)
        info_row.setSpacing(10)
        info_row.addWidget(self.run_info, 1)
        info_row.addWidget(self.busy)
        action_col.addLayout(run_row)
        action_col.addLayout(info_row)
        hero_lay.addLayout(action_col)
        root_lay.addWidget(hero, 0)
        self._sync_theme_toggle()
        self._sync_console_toggle()

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        left = QWidget()
        left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(12)

        summary = Card("Project workspace", "Project")
        summary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        project_help = QLabel("Each project stores its own far-field files, Touchstone file, UI settings, and generated outputs under Projects/<name>/.")
        project_help.setWordWrap(True)
        project_help.setObjectName("helper")
        summary.body.addWidget(project_help)
        project_row = QHBoxLayout()
        project_row.setContentsMargins(0, 0, 0, 0)
        project_row.setSpacing(8)
        self.project_combo = QComboBox()
        self.project_combo.currentIndexChanged.connect(self.on_project_selected)
        self.project_combo.setToolTip("Select the active project.")
        self.project_new_button = QPushButton("New")
        self.project_new_button.clicked.connect(self.create_project)
        self.project_edit_button = QPushButton("Edit")
        self.project_edit_button.clicked.connect(self.edit_project)
        self.project_delete_button = QPushButton("Delete")
        self.project_delete_button.clicked.connect(self.delete_project)
        project_row.addWidget(self.project_combo, 1)
        project_row.addWidget(self.project_new_button)
        project_row.addWidget(self.project_edit_button)
        project_row.addWidget(self.project_delete_button)
        summary.body.addLayout(project_row)
        self.project_name = QLabel("No project selected")
        self.project_name.setObjectName("projectName")
        summary.body.addWidget(self.project_name)
        self.workbook_field = QLineEdit(); self.workbook_field.setReadOnly(True)
        self.extract_field = QLineEdit(); self.extract_field.setReadOnly(True)
        self.results_field = QLineEdit(); self.results_field.setReadOnly(True)
        self.vswr_field = QLineEdit(); self.vswr_field.setReadOnly(True)
        self.workbook_field.setToolTip("Workbook stored inside the selected project directory.")
        self.extract_field.setToolTip("Extracted-data workbook stored inside the selected project directory.")
        self.results_field.setToolTip("Project directory containing metadata and generated outputs.")
        self.vswr_field.setToolTip("VSWR plot stored inside the selected project directory.")
        form = QFormLayout()
        form.addRow("Workbook", self._path_row(self.workbook_field))
        form.addRow("Extract workbook", self._path_row(self.extract_field))
        form.addRow("Project folder", self._path_row(self.results_field))
        form.addRow("VSWR output", self._path_row(self.vswr_field))
        summary.body.addLayout(form)
        left_lay.addWidget(summary)

        preset_card = Card("Presets", "Workflow")
        preset_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        preset_help = QLabel("Save reusable control/range/style presets for product lines. Presets do not change the currently selected input files.")
        preset_help.setWordWrap(True)
        preset_help.setObjectName("helper")
        preset_card.body.addWidget(preset_help)
        self.preset_combo = QComboBox()
        self.preset_combo.currentTextChanged.connect(self.on_preset_selected)
        self.preset_combo.setToolTip("Choose a saved preset to apply its control, range, and style settings.")
        preset_card.body.addWidget(self.preset_combo)
        preset_row = QHBoxLayout()
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.setSpacing(8)
        preset_new = QPushButton("New"); preset_new.clicked.connect(self.create_preset)
        preset_save = QPushButton("Save"); preset_save.clicked.connect(self.save_preset)
        preset_rename = QPushButton("Rename"); preset_rename.clicked.connect(self.rename_preset)
        preset_delete = QPushButton("Delete"); preset_delete.clicked.connect(self.delete_preset)
        preset_new.setToolTip("Create a new preset from the current GUI settings.")
        preset_save.setToolTip("Overwrite the selected preset with the current GUI settings.")
        preset_rename.setToolTip("Rename the selected preset without changing its settings.")
        preset_delete.setToolTip("Delete the selected preset.")
        preset_row.addWidget(preset_new)
        preset_row.addWidget(preset_save)
        preset_row.addWidget(preset_rename)
        preset_row.addWidget(preset_delete)
        preset_row.addStretch(1)
        preset_card.body.addLayout(preset_row)
        io_row = QHBoxLayout()
        io_row.setContentsMargins(0, 0, 0, 0)
        io_row.setSpacing(8)
        preset_import = QPushButton("Import"); preset_import.clicked.connect(self.import_presets)
        preset_export = QPushButton("Export"); preset_export.clicked.connect(self.export_presets)
        preset_import.setToolTip("Import presets from a JSON file and merge them into the current list.")
        preset_export.setToolTip("Export all saved presets to a JSON file.")
        io_row.addWidget(preset_import)
        io_row.addWidget(preset_export)
        io_row.addStretch(1)
        preset_card.body.addLayout(io_row)
        left_lay.addWidget(preset_card)

        ffs_card = Card("Far-field exports", "Inputs")
        ffs_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        helper = QLabel("Drop .ffs files here or add them manually. Changes are saved into the active project.")
        helper.setWordWrap(True)
        helper.setObjectName("helper")
        ffs_card.body.addWidget(helper)
        self.ffs_list = DropList(self._add_ffs_files)
        self.ffs_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ffs_list.setMinimumHeight(230)
        self.ffs_list.setToolTip("Add one or more CST far-field export files (.ffs). Their names drive project-name deduction.")
        ffs_card.body.addWidget(self.ffs_list, 1)
        ffs_row = QHBoxLayout()
        ffs_row.setContentsMargins(0, 0, 0, 0)
        ffs_row.setSpacing(8)
        addb = QPushButton("Add .ffs"); addb.clicked.connect(self.add_ffs)
        remb = QPushButton("Remove selected"); remb.clicked.connect(self.remove_ffs)
        clearb = QPushButton("Clear list"); clearb.clicked.connect(self.clear_ffs)
        addb.setToolTip("Browse for CST far-field export files to include in this project.")
        remb.setToolTip("Remove the highlighted far-field files from the current project.")
        clearb.setToolTip("Clear the full far-field file list.")
        ffs_row.addWidget(addb); ffs_row.addWidget(remb); ffs_row.addWidget(clearb); ffs_row.addStretch(1)
        ffs_card.body.addLayout(ffs_row)
        left_lay.addWidget(ffs_card, 1)

        s2p_card = Card("Touchstone", "Inputs")
        s2p_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        s2p_row = QHBoxLayout()
        self.s2p_field = QLineEdit("")
        self.s2p_field.setReadOnly(True)
        self.s2p_field.setToolTip("Detected or manually selected Touchstone file used for the VSWR plot (.s1p or .s2p).")
        s2p_row.addWidget(self.s2p_field, 1)
        sel = QPushButton("Select Touchstone"); sel.clicked.connect(self.browse_s2p)
        clr = QPushButton("Clear"); clr.clicked.connect(self.clear_s2p)
        opn = QPushButton("Open"); opn.clicked.connect(lambda: open_in_file_manager(resolve_workspace_path(self.s2p_field.text())))
        sel.setToolTip("Choose a Touchstone file manually if the automatic project match is not the one you want.")
        clr.setToolTip("Clear the current Touchstone selection and let deduction run again.")
        opn.setToolTip("Open the selected Touchstone file in File Explorer.")
        s2p_row.addWidget(sel); s2p_row.addWidget(clr); s2p_row.addWidget(opn)
        s2p_card.body.addLayout(s2p_row)
        left_lay.addWidget(s2p_card)
        left_lay.setStretch(0, 0)
        left_lay.setStretch(1, 0)
        left_lay.setStretch(2, 1)
        left_lay.setStretch(3, 0)

        split.addWidget(left)

        right = QWidget()
        right.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        right_lay = QHBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(12)
        right_lay.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        proc_card = Card("Processing controls", "Workflow")
        proc_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        proc_card.setMaximumWidth(400)
        self.beam_smooth = NoWheelSpinBox(); self.beam_smooth.setRange(1, 99); self.beam_smooth.setValue(int(self.store.get("smooth", 5))); self.beam_smooth.valueChanged.connect(lambda v: self.store.set("smooth", int(v)))
        self.theta_window = TrimmedDoubleSpinBox(); self.theta_window.setRange(0.0, 90.0); self.theta_window.setDecimals(6); self.theta_window.setSingleStep(0.5); self.theta_window.setValue(float(self.store.get("theta", 8.0))); self.theta_window.valueChanged.connect(lambda v: self.store.set("theta", float(v)))
        self.plot_smooth = NoWheelSpinBox(); self.plot_smooth.setRange(1, 99); self.plot_smooth.setValue(int(self.store.get("smooth2", 5))); self.plot_smooth.valueChanged.connect(lambda v: self.store.set("smooth2", int(v)))
        shared_xstep = self.store.get("shared_xstep", self.store.get("xstep", self.store.get("vswr_xstep", 0.2)))
        shared_fmin = self.store.get("shared_fmin", self.store.get("plot_fmin", self.store.get("vswr_fmin", 0.0)))
        shared_fmax = self.store.get("shared_fmax", self.store.get("plot_fmax", self.store.get("vswr_fmax", 0.0)))
        shared_xlog = self.store.get("shared_xlog", self.store.get("plot_xlog", self.store.get("vswr_xlog", False)))
        self.shared_xstep = TrimmedDoubleSpinBox(); self.shared_xstep.setRange(0.01, 10.0); self.shared_xstep.setDecimals(6); self.shared_xstep.setSingleStep(0.1); self.shared_xstep.setValue(float(shared_xstep)); self.shared_xstep.valueChanged.connect(lambda v: self.store.set("shared_xstep", float(v)))
        self.shared_fmin = TrimmedDoubleSpinBox(); self.shared_fmin.setRange(0.0, 1000.0); self.shared_fmin.setDecimals(6); self.shared_fmin.setSingleStep(0.1); self.shared_fmin.setValue(float(shared_fmin)); self.shared_fmin.valueChanged.connect(lambda v: self.store.set("shared_fmin", float(v)))
        self.shared_fmax = TrimmedDoubleSpinBox(); self.shared_fmax.setRange(0.0, 1000.0); self.shared_fmax.setDecimals(6); self.shared_fmax.setSingleStep(0.1); self.shared_fmax.setValue(float(shared_fmax)); self.shared_fmax.valueChanged.connect(lambda v: self.store.set("shared_fmax", float(v)))
        self.shared_xlog = QCheckBox("Log scale"); self.shared_xlog.setObjectName("pillCheck"); self.shared_xlog.setChecked(bool(shared_xlog)); self.shared_xlog.toggled.connect(lambda v: self.store.set("shared_xlog", bool(v)))
        self.gain_ymin = TrimmedDoubleSpinBox(); self.gain_ymin.setRange(-1000.0, 1000.0); self.gain_ymin.setDecimals(6); self.gain_ymin.setValue(float(self.store.get("gain_ymin", 0.0))); self.gain_ymin.valueChanged.connect(lambda v: self.store.set("gain_ymin", float(v)))
        self.gain_ymax = TrimmedDoubleSpinBox(); self.gain_ymax.setRange(-1000.0, 1000.0); self.gain_ymax.setDecimals(6); self.gain_ymax.setValue(float(self.store.get("gain_ymax", 0.0))); self.gain_ymax.valueChanged.connect(lambda v: self.store.set("gain_ymax", float(v)))
        self.gain_y_step = TrimmedDoubleSpinBox(); self.gain_y_step.setRange(0.0, 1000.0); self.gain_y_step.setDecimals(6); self.gain_y_step.setSingleStep(0.5); self.gain_y_step.setValue(float(self.store.get("gain_y_step", 0.0))); self.gain_y_step.valueChanged.connect(lambda v: self.store.set("gain_y_step", float(v)))
        self.beamwidth_ymin = TrimmedDoubleSpinBox(); self.beamwidth_ymin.setRange(-1000.0, 1000.0); self.beamwidth_ymin.setDecimals(6); self.beamwidth_ymin.setValue(float(self.store.get("beamwidth_ymin", 0.0))); self.beamwidth_ymin.valueChanged.connect(lambda v: self.store.set("beamwidth_ymin", float(v)))
        self.beamwidth_ymax = TrimmedDoubleSpinBox(); self.beamwidth_ymax.setRange(-1000.0, 1000.0); self.beamwidth_ymax.setDecimals(6); self.beamwidth_ymax.setValue(float(self.store.get("beamwidth_ymax", 0.0))); self.beamwidth_ymax.valueChanged.connect(lambda v: self.store.set("beamwidth_ymax", float(v)))
        self.beamwidth_y_step = TrimmedDoubleSpinBox(); self.beamwidth_y_step.setRange(0.0, 1000.0); self.beamwidth_y_step.setDecimals(6); self.beamwidth_y_step.setSingleStep(0.5); self.beamwidth_y_step.setValue(float(self.store.get("beamwidth_y_step", 0.0))); self.beamwidth_y_step.valueChanged.connect(lambda v: self.store.set("beamwidth_y_step", float(v)))
        self.beam_eff_ymin = TrimmedDoubleSpinBox(); self.beam_eff_ymin.setRange(-1000.0, 1000.0); self.beam_eff_ymin.setDecimals(6); self.beam_eff_ymin.setValue(float(self.store.get("beam_eff_ymin", 0.0))); self.beam_eff_ymin.valueChanged.connect(lambda v: self.store.set("beam_eff_ymin", float(v)))
        self.beam_eff_ymax = TrimmedDoubleSpinBox(); self.beam_eff_ymax.setRange(-1000.0, 1000.0); self.beam_eff_ymax.setDecimals(6); self.beam_eff_ymax.setValue(float(self.store.get("beam_eff_ymax", 0.0))); self.beam_eff_ymax.valueChanged.connect(lambda v: self.store.set("beam_eff_ymax", float(v)))
        self.beam_eff_y_step = TrimmedDoubleSpinBox(); self.beam_eff_y_step.setRange(0.0, 1000.0); self.beam_eff_y_step.setDecimals(6); self.beam_eff_y_step.setSingleStep(0.5); self.beam_eff_y_step.setValue(float(self.store.get("beam_eff_y_step", 0.0))); self.beam_eff_y_step.valueChanged.connect(lambda v: self.store.set("beam_eff_y_step", float(v)))
        self.vswr_ymin = TrimmedDoubleSpinBox(); self.vswr_ymin.setRange(0.0, 1000.0); self.vswr_ymin.setDecimals(6); self.vswr_ymin.setValue(float(self.store.get("vswr_ymin", 1.0))); self.vswr_ymin.valueChanged.connect(lambda v: self.store.set("vswr_ymin", float(v)))
        self.vswr_ymax = TrimmedDoubleSpinBox(); self.vswr_ymax.setRange(0.0, 1000.0); self.vswr_ymax.setDecimals(6); self.vswr_ymax.setValue(float(self.store.get("vswr_ymax", 10.0))); self.vswr_ymax.valueChanged.connect(lambda v: self.store.set("vswr_ymax", float(v)))
        self.vswr_ystep = TrimmedDoubleSpinBox(); self.vswr_ystep.setRange(0.01, 100.0); self.vswr_ystep.setDecimals(6); self.vswr_ystep.setValue(float(self.store.get("vswr_ystep", 1.0))); self.vswr_ystep.valueChanged.connect(lambda v: self.store.set("vswr_ystep", float(v)))
        self.vswr_smooth = NoWheelSpinBox(); self.vswr_smooth.setRange(1, 99); self.vswr_smooth.setValue(int(self.store.get("vswr_smooth", 5))); self.vswr_smooth.valueChanged.connect(lambda v: self.store.set("vswr_smooth", int(v)))
        proc_form = QFormLayout()
        proc_form.setContentsMargins(0, 0, 0, 0)
        proc_form.setHorizontalSpacing(10)
        proc_form.setVerticalSpacing(8)
        proc_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        proc_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_form_row(proc_form, "Beam smooth", StepperField(self.beam_smooth), "Smoothing window used while creating the workbook from the far-field files. Higher values smooth more aggressively.")
        add_form_row(proc_form, "Theta window", StepperField(self.theta_window), "Angular window in degrees used for the beamwidth calculation around the main lobe.")
        add_form_row(proc_form, "Plot smooth", StepperField(self.plot_smooth), "Smoothing window applied to the workbook-based line plots.")
        add_form_row(proc_form, "Shared x tick", StepperField(self.shared_xstep), "Spacing between x-axis tick labels used by both workbook plots and the VSWR plot, in GHz.")
        add_form_row(proc_form, "Shared fmin", StepperField(self.shared_fmin), "Lower frequency bound used by both workbook plots and the VSWR plot, in GHz. Use 0 to keep the full range.")
        add_form_row(proc_form, "Shared fmax", StepperField(self.shared_fmax), "Upper frequency bound used by both workbook plots and the VSWR plot, in GHz. Use 0 to keep the full range.")
        add_form_row(proc_form, "Shared x axis", self.shared_xlog, "Switch both workbook plots and the VSWR plot between linear and logarithmic x-axis scaling.")
        add_form_row(proc_form, "VSWR smooth", StepperField(self.vswr_smooth), "Smoothing window applied to the VSWR traces.")
        proc_card.body.addLayout(proc_form)
        right_lay.addWidget(proc_card, 0, Qt.AlignTop)

        range_card = Card("Y-Axis Ranges", "Charts")
        range_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        range_card.setMaximumWidth(400)
        range_form = QFormLayout()
        range_form.setContentsMargins(0, 0, 0, 0)
        range_form.setHorizontalSpacing(10)
        range_form.setVerticalSpacing(8)
        range_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        range_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_form_row(range_form, "Gain y min", StepperField(self.gain_ymin), "Lower limit override for the gain plot. Use 0 to keep the default automatic minimum.")
        add_form_row(range_form, "Gain y max", StepperField(self.gain_ymax), "Upper limit override for the gain plot. Use 0 to keep the default automatic maximum.")
        add_form_row(range_form, "Gain y tick", StepperField(self.gain_y_step), "Y-axis tick spacing override for the gain plot. Use 0 to keep the default tick spacing.")
        add_form_row(range_form, "Beamwidth y min", StepperField(self.beamwidth_ymin), "Lower limit override for the beamwidth plot. Use 0 to keep the default automatic minimum.")
        add_form_row(range_form, "Beamwidth y max", StepperField(self.beamwidth_ymax), "Upper limit override for the beamwidth plot. Use 0 to keep the default automatic maximum.")
        add_form_row(range_form, "Beamwidth y tick", StepperField(self.beamwidth_y_step), "Y-axis tick spacing override for the beamwidth plot. Use 0 to keep the default tick spacing.")
        add_form_row(range_form, "Beam eff y min", StepperField(self.beam_eff_ymin), "Lower limit override for the beam efficiency plot. Use 0 to keep the default automatic minimum.")
        add_form_row(range_form, "Beam eff y max", StepperField(self.beam_eff_ymax), "Upper limit override for the beam efficiency plot. Use 0 to keep the default automatic maximum.")
        add_form_row(range_form, "Beam eff y tick", StepperField(self.beam_eff_y_step), "Y-axis tick spacing override for the beam efficiency plot. Use 0 to keep the default tick spacing.")
        add_form_row(range_form, "VSWR y min", StepperField(self.vswr_ymin), "Lower limit of the VSWR y-axis.")
        add_form_row(range_form, "VSWR y max", StepperField(self.vswr_ymax), "Upper limit of the VSWR y-axis.")
        add_form_row(range_form, "VSWR y tick", StepperField(self.vswr_ystep), "Spacing between VSWR y-axis tick labels.")
        range_card.body.addLayout(range_form)
        right_lay.addWidget(range_card, 0, Qt.AlignTop)

        style_card = Card("Visual style", "Charts")
        style_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        style_card.setMaximumWidth(500)
        self.plot_grid = StudioColorSelector(self.store, "grid_color", DEFAULT_GRID_COLOR, presets=GREY_COLOR_OPTIONS)
        self.plot_line1 = StudioColorSelector(self.store, "plot_line_1", DEFAULT_LINE_COLORS[0][1])
        self.plot_line2 = StudioColorSelector(self.store, "plot_line_2", DEFAULT_LINE_COLORS[1][1])
        self.rings = QLineEdit(self.store.get("rings", "0,-7.5,-15,-22.5,-30")); self.rings.textChanged.connect(lambda v: self.store.set("rings", v))
        self.angle_step = NoWheelSpinBox(); self.angle_step.setRange(5, 90); self.angle_step.setSingleStep(5); self.angle_step.setValue(int(self.store.get("angle", 30))); self.angle_step.valueChanged.connect(lambda v: self.store.set("angle", int(v)))
        self.clip_db = TrimmedDoubleSpinBox(); self.clip_db.setRange(-120.0, 0.0); self.clip_db.setDecimals(6); self.clip_db.setSingleStep(0.5); self.clip_db.setValue(float(self.store.get("clip", -30.0))); self.clip_db.valueChanged.connect(lambda v: self.store.set("clip", float(v)))
        self.vswr_grid = StudioColorSelector(self.store, "vswr_grid", DEFAULT_GRID_COLOR, presets=GREY_COLOR_OPTIONS)
        self.vswr_line1 = StudioColorSelector(self.store, "vswr_line_1", DEFAULT_LINE_COLORS[0][1])
        self.vswr_line2 = StudioColorSelector(self.store, "vswr_line_2", DEFAULT_LINE_COLORS[1][1])
        self.rings.setToolTip("Comma-separated dB ring values used on the polar plots.")
        style_form = QFormLayout()
        style_form.setContentsMargins(0, 0, 0, 0)
        style_form.setHorizontalSpacing(10)
        style_form.setVerticalSpacing(8)
        style_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        style_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_form_row(style_form, "Plot grid color", self.plot_grid, "Grid and axis color for the workbook-based cartesian plots. Presets are neutral greys, with a custom color option.")
        add_form_row(style_form, "Plot line color 1", self.plot_line1, "Primary line color for the first workbook-based plot trace.")
        add_form_row(style_form, "Plot line color 2", self.plot_line2, "Secondary line color for the second workbook-based plot trace.")
        add_form_row(style_form, "Polar rings", self.rings, "Comma-separated dB ring values used on the polar plots.")
        add_form_row(style_form, "Polar angle step", StepperField(self.angle_step), "Angle spacing, in degrees, for polar plot annotations.")
        add_form_row(style_form, "Polar clip below", StepperField(self.clip_db), "Clip polar-plot values below this dB level to keep the chart readable.")
        add_form_row(style_form, "VSWR grid color", self.vswr_grid, "Grid and axis color for the VSWR plot. Presets are neutral greys, with a custom color option.")
        add_form_row(style_form, "VSWR line color 1", self.vswr_line1, "Primary line color for the first VSWR trace.")
        add_form_row(style_form, "VSWR line color 2", self.vswr_line2, "Secondary line color for the second VSWR trace.")
        style_card.body.addLayout(style_form)
        right_lay.addWidget(style_card, 0, Qt.AlignTop)

        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes(self.store.get("studio_split_sizes", [500, 980]))
        root_lay.addWidget(split, 1)
        self.setCentralWidget(root)
        self._body_split = split

        self.console_window = ConsoleWindow(self, self.store)
        self.console = self.console_window.console
        self._set_console_visible(bool(self.store.get("console_visible", False)), persist=False)

        self._bind_project_persistence()
        self.refresh_preset_list(select_name=str(self.store.get(ACTIVE_PRESET_KEY, "")))

    def _path_row(self, field: QLineEdit) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(field, 1)
        btn = QPushButton("Open")
        btn.setToolTip("Open this location in File Explorer.")
        btn.clicked.connect(lambda: open_in_file_manager(resolve_workspace_path(field.text())))
        lay.addWidget(btn)
        return row

    def _apply_style(self):
        QApplication.setStyle(QStyleFactory.create("Fusion"))
        pal = QPalette()
        if self.theme == "dark":
            pal.setColor(QPalette.Window, QColor("#0b1220"))
            pal.setColor(QPalette.WindowText, QColor("#e5eef7"))
            pal.setColor(QPalette.Base, QColor("#131c2b"))
            pal.setColor(QPalette.Text, QColor("#e5eef7"))
            pal.setColor(QPalette.Highlight, QColor("#38bdf8"))
            pal.setColor(QPalette.HighlightedText, QColor("#08111d"))
            window_bg = "#0b1220"
            hero_bg = "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #020617, stop:0.55 #172554, stop:1 #0f766e)"
            hero_subtle = "rgba(226,232,240,0.82)"
            card_bg = "rgba(15,23,42,0.96)"
            card_border = "#22304a"
            title_color = "#f8fafc"
            text_color = "#d7e3ef"
            input_bg = "#131c2b"
            input_border = "#2a3a56"
            button_bg = "#162234"
            button_hover = "#1b2a41"
            list_selected = "#18324a"
            primary_bg = "#22c55e"
            primary_hover = "#16a34a"
            progress_bg = "rgba(255,255,255,0.08)"
            ghost_bg = "#1e293b"
            ghost_hover = "#273449"
            step_bg = "#0f172a"
            step_hover = "#172033"
            step_border = "#314158"
            helper_color = "#9eb5cb"
        else:
            pal.setColor(QPalette.Window, QColor("#edf3f8"))
            pal.setColor(QPalette.WindowText, QColor("#0c1d2c"))
            pal.setColor(QPalette.Base, QColor("#ffffff"))
            pal.setColor(QPalette.Text, QColor("#102336"))
            pal.setColor(QPalette.Highlight, QColor("#0ea5e9"))
            pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
            window_bg = "#edf3f8"
            hero_bg = "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #0f172a, stop:0.55 #123455, stop:1 #0ea5e9)"
            hero_subtle = "rgba(255,255,255,0.82)"
            card_bg = "rgba(255,255,255,0.95)"
            card_border = "#d6e1ea"
            title_color = "#102336"
            text_color = "#21374a"
            input_bg = "#f8fbfd"
            input_border = "#d4e0ea"
            button_bg = "#ffffff"
            button_hover = "#f7fbfe"
            list_selected = "#d9f1ff"
            primary_bg = "#f97316"
            primary_hover = "#ea580c"
            progress_bg = "rgba(255,255,255,0.16)"
            ghost_bg = "#eef6fb"
            ghost_hover = "#e4f0f8"
            step_bg = "#f1f7fb"
            step_hover = "#e5f1f8"
            step_border = "#bfd4e3"
            helper_color = "#597185"
        QApplication.setPalette(pal)
        app = QApplication.instance()
        if app:
            app.setStyleSheet("""
                QWidget { font-family: "Segoe UI"; font-size: 10.5pt; }
                QMainWindow { background: %(window_bg)s; }
                #hero { border-radius: 24px; background: %(hero_bg)s; }
                #heroTitle { color: white; font-size: 20pt; font-weight: 700; }
                #runInfo { color: %(hero_subtle)s; }
                #badge { background: rgba(255,255,255,0.12); color: white; border: 1px solid rgba(255,255,255,0.14); border-radius: 12px; padding: 5px 10px; font-size: 8.75pt; font-weight: 600; }
                #card { background: %(card_bg)s; border: 1px solid %(card_border)s; border-radius: 20px; }
                #cardTitle { color: %(title_color)s; font-size: 13pt; font-weight: 700; }
                #eyebrow { color: #38bdf8; font-size: 8.5pt; font-weight: 700; }
                #projectName { color: %(title_color)s; font-size: 17pt; font-weight: 700; }
                QLabel { color: %(text_color)s; }
                #helper { color: %(helper_color)s; }
                QLineEdit, QSpinBox, QDoubleSpinBox, QListWidget, QPlainTextEdit { background: %(input_bg)s; border: 1px solid %(input_border)s; border-radius: 14px; padding: 8px 11px; color: %(title_color)s; }
                QListWidget::item { padding: 7px 10px; border-radius: 10px; margin: 1px 0; }
                QListWidget::item:selected { background: %(list_selected)s; color: %(title_color)s; }
                QPushButton { background: %(button_bg)s; border: 1px solid %(input_border)s; border-radius: 14px; padding: 9px 13px; color: %(title_color)s; font-weight: 600; }
                QPushButton:hover { border-color: #7fb2cf; background: %(button_hover)s; }
                QPushButton#primaryButton { background: %(primary_bg)s; color: white; border: none; padding: 10px 16px; }
                QPushButton#primaryButton:hover { background: %(primary_hover)s; }
                QPushButton#themeToggle { min-width: 108px; }
                QPushButton#ghostButton { background: %(ghost_bg)s; }
                QPushButton#ghostButton:hover { background: %(ghost_hover)s; }
                QPushButton#stepButton { background: %(step_bg)s; border: 1px solid %(step_border)s; border-radius: 12px; padding: 6px 0; font-size: 11pt; font-weight: 700; min-width: 30px; }
                QPushButton#stepButton:hover { background: %(step_hover)s; border-color: #7fb2cf; }
                QCheckBox#pillCheck { spacing: 8px; padding: 7px 10px; border: 1px solid %(input_border)s; border-radius: 12px; background: %(ghost_bg)s; color: %(title_color)s; font-weight: 600; }
                QCheckBox#pillCheck:hover { border-color: #7fb2cf; background: %(ghost_hover)s; }
                QCheckBox#pillCheck::indicator { width: 16px; height: 16px; border-radius: 8px; border: 1px solid %(step_border)s; background: transparent; }
                QCheckBox#pillCheck::indicator:checked { background: %(primary_bg)s; border-color: %(primary_bg)s; }
                QProgressBar { background: %(progress_bg)s; border: 1px solid rgba(255,255,255,0.18); border-radius: 10px; color: white; min-height: 18px; }
                QProgressBar::chunk { background: %(primary_bg)s; border-radius: 8px; }
            """ % {
                "window_bg": window_bg,
                "hero_bg": hero_bg,
                "hero_subtle": hero_subtle,
                "card_bg": card_bg,
                "card_border": card_border,
                "title_color": title_color,
                "text_color": text_color,
                "input_bg": input_bg,
                "input_border": input_border,
                "button_bg": button_bg,
                "button_hover": button_hover,
                "list_selected": list_selected,
                "primary_bg": primary_bg,
                "primary_hover": primary_hover,
                "progress_bg": progress_bg,
                "ghost_bg": ghost_bg,
                "ghost_hover": ghost_hover,
                "step_bg": step_bg,
                "step_hover": step_hover,
                "step_border": step_border,
                "helper_color": helper_color,
            })

    def _sync_theme_toggle(self):
        dark = self.theme == "dark"
        self.theme_toggle.setChecked(dark)
        self.theme_toggle.setText("Light Theme" if dark else "Dark Theme")

    def _sync_console_toggle(self):
        visible = self.console_window.isVisible() if hasattr(self, "console_window") else bool(self.store.get("console_visible", False))
        self.console_toggle.setChecked(visible)
        self.console_toggle.setText("Hide Console" if visible else "Show Console")

    def _set_console_visible(self, visible: bool, persist: bool = True):
        if visible:
            self.console_window.show()
            self.console_window.raise_()
            self.console_window.activateWindow()
        else:
            self.console_window._save_geometry()
            self.console_window.hide()
        self.console_toggle.setChecked(visible)
        self.console_toggle.setText("Hide Console" if visible else "Show Console")
        if persist:
            self.store.set("console_visible", visible)

    def on_console_popup_closed(self):
        if self._closing_app:
            return
        self.console_toggle.setChecked(False)
        self.console_toggle.setText("Show Console")
        self.store.set("console_visible", False)

    def toggle_theme(self, checked: bool = False):
        self.theme = "dark" if checked else "light"
        self.store.set("theme", self.theme)
        self._sync_theme_toggle()
        self._apply_style()

    def toggle_console(self, checked: bool = False):
        self._set_console_visible(checked)

    def _bind_project_persistence(self) -> None:
        tracked_signals = [
            self.beam_smooth.valueChanged,
            self.theta_window.valueChanged,
            self.plot_smooth.valueChanged,
            self.shared_xstep.valueChanged,
            self.shared_fmin.valueChanged,
            self.shared_fmax.valueChanged,
            self.shared_xlog.toggled,
            self.gain_ymin.valueChanged,
            self.gain_ymax.valueChanged,
            self.gain_y_step.valueChanged,
            self.beamwidth_ymin.valueChanged,
            self.beamwidth_ymax.valueChanged,
            self.beamwidth_y_step.valueChanged,
            self.beam_eff_ymin.valueChanged,
            self.beam_eff_ymax.valueChanged,
            self.beam_eff_y_step.valueChanged,
            self.vswr_ymin.valueChanged,
            self.vswr_ymax.valueChanged,
            self.vswr_ystep.valueChanged,
            self.vswr_smooth.valueChanged,
            self.plot_grid.colorChanged,
            self.plot_line1.colorChanged,
            self.plot_line2.colorChanged,
            self.rings.textChanged,
            self.angle_step.valueChanged,
            self.clip_db.valueChanged,
            self.vswr_grid.colorChanged,
            self.vswr_line1.colorChanged,
            self.vswr_line2.colorChanged,
        ]
        for signal in tracked_signals:
            signal.connect(self.on_project_configuration_changed)

    def on_project_configuration_changed(self, *_args) -> None:
        self.save_active_project()

    def selected_ffs(self) -> list[str]:
        return [self._item_path(self.ffs_list.item(i)) for i in range(self.ffs_list.count())]

    def selected_s2p(self) -> str:
        value = self.s2p_field.text().strip()
        return str(resolve_workspace_path(value)) if value else ""

    def current_project(self) -> ProjectRecord | None:
        if not self.active_project_slug:
            return None
        return ProjectRecord(
            name=self.active_project_name or self.active_project_slug,
            slug=self.active_project_slug,
            ffs_files=[serialize_workspace_path(THIS_DIR, path) for path in self.selected_ffs()],
            touchstone_file=serialize_workspace_path(THIS_DIR, self.selected_s2p()),
            settings=self.collect_preset_values(),
        )

    def project_results_dir(self) -> Path:
        project = self.current_project()
        return project.project_dir(THIS_DIR) if project else (self.project_store.projects_dir / "unassigned")

    def deduced_beam_output(self) -> Path:
        project = self.current_project()
        return project.workbook_path(THIS_DIR) if project else (self.project_results_dir() / "project.xlsx")

    def deduced_extract_output(self) -> Path:
        project = self.current_project()
        return project.extract_path(THIS_DIR) if project else (self.project_results_dir() / "project_extracted_data.xlsx")

    def deduced_vswr_output(self) -> Path:
        project = self.current_project()
        return project.vswr_path(THIS_DIR) if project else (self.project_results_dir() / "project_vswr.svg")

    def refresh_derived_paths(self) -> None:
        if self.active_project_slug:
            project_label = self.active_project_name or self.active_project_slug
            self.project_name.setText(project_label)
            self.project_badge.setText(f"Project: {project_label}")
            self.workbook_field.setText(display_workspace_path(self.deduced_beam_output()))
            self.extract_field.setText(display_workspace_path(self.deduced_extract_output()))
            self.results_field.setText(display_workspace_path(self.project_results_dir()))
            self.vswr_field.setText(display_workspace_path(self.deduced_vswr_output()))
        else:
            self.project_name.setText("No project selected")
            self.project_badge.setText("Project: none")
            self.workbook_field.clear()
            self.extract_field.clear()
            self.results_field.clear()
            self.vswr_field.clear()
        count = len(self.selected_ffs())
        self.count_badge.setText(f"{count} far-field file{'s' if count != 1 else ''}")
        self._update_project_action_state()

    def _update_project_action_state(self) -> None:
        has_project = bool(self.active_project_slug)
        self.project_edit_button.setEnabled(has_project)
        self.project_delete_button.setEnabled(has_project)
        for widget in (
            self.btn_full,
            self.btn_beam,
            self.btn_extract,
            self.btn_plot,
            self.btn_vswr,
            self.ffs_list,
            self.s2p_field,
        ):
            widget.setEnabled(has_project)

    def refresh_project_list(self, select_slug: str = "") -> None:
        projects = self.project_store.list_projects()
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItem("Select a project", "")
        for project in projects:
            self.project_combo.addItem(project.name, project.slug)
        index = self.project_combo.findData(select_slug)
        if index < 0 and projects:
            index = 1
        self.project_combo.setCurrentIndex(max(0, index))
        self.project_combo.blockSignals(False)
        self.on_project_selected(self.project_combo.currentIndex())

    def on_project_selected(self, _index: int) -> None:
        slug = str(self.project_combo.currentData() or "")
        if not slug:
            self.active_project_slug = ""
            self.active_project_name = ""
            self._loading_project = True
            self.ffs_list.clear()
            self.s2p_field.clear()
            self._loading_project = False
            self.store.set("active_project", "")
            self.refresh_derived_paths()
            return
        project = self.project_store.load_project(slug)
        self._apply_project(project)

    def _apply_project(self, project: ProjectRecord) -> None:
        self._loading_project = True
        self.active_project_slug = project.slug
        self.active_project_name = project.name
        self.store.set("active_project", project.slug)
        self.ffs_list.clear()
        self._add_ffs_files([resolve_project_path(THIS_DIR, path) for path in project.ffs_files], save=False)
        touchstone = resolve_project_path(THIS_DIR, project.touchstone_file)
        if not touchstone and project.name:
            guessed = guess_touchstone_path(project.name, self.selected_ffs())
            touchstone = guessed
        self.s2p_field.setText(display_workspace_path(touchstone))
        self.apply_preset_values(project.settings)
        self.store.set("beam_ffs", self.selected_ffs())
        self.store.set("vswr_s2p", touchstone)
        self._loading_project = False
        self.refresh_derived_paths()

    def save_active_project(self) -> None:
        if self._loading_project or not self.active_project_slug:
            self.refresh_derived_paths()
            return
        project = self.current_project()
        if not project:
            self.refresh_derived_paths()
            return
        self.project_store.save_project(project)
        self.store.set("active_project", project.slug)
        self.store.set("beam_ffs", self.selected_ffs())
        self.store.set("vswr_s2p", self.selected_s2p())
        self.refresh_derived_paths()

    def create_project(self) -> None:
        suggested_name = deduce_project_name(self.selected_ffs() or [self.selected_s2p()]) if (self.selected_ffs() or self.selected_s2p()) else "New project"
        dialog = ProjectDialog(self, name=suggested_name, ffs_files=self.selected_ffs(), touchstone_file=self.selected_s2p())
        if dialog.exec() != QDialog.Accepted:
            return
        name = dialog.project_name()
        if not name:
            QMessageBox.information(self, "Project Name Required", "Enter a project name.")
            return
        slug = sanitize_project_slug(name)
        if self.project_combo.findData(slug) >= 0:
            QMessageBox.information(self, "Project Exists", f"A project named '{name}' already exists.")
            return
        touchstone = dialog.touchstone_file() or guess_touchstone_path(name, dialog.ffs_files())
        project = ProjectRecord(
            name=name,
            slug=slug,
            ffs_files=[serialize_workspace_path(THIS_DIR, path) for path in dialog.ffs_files()],
            touchstone_file=serialize_workspace_path(THIS_DIR, touchstone),
            settings=self.collect_preset_values(),
        )
        self.project_store.save_project(project)
        self.refresh_project_list(select_slug=project.slug)

    def edit_project(self) -> None:
        if not self.active_project_slug:
            QMessageBox.information(self, "No Project Selected", "Select a project to edit.")
            return
        dialog = ProjectDialog(
            self,
            name=self.active_project_name,
            ffs_files=self.selected_ffs(),
            touchstone_file=self.selected_s2p(),
        )
        if dialog.exec() != QDialog.Accepted:
            return
        name = dialog.project_name()
        if not name:
            QMessageBox.information(self, "Project Name Required", "Enter a project name.")
            return
        new_slug = sanitize_project_slug(name)
        current_slug = self.active_project_slug
        if new_slug != current_slug and self.project_combo.findData(new_slug) >= 0:
            QMessageBox.information(self, "Project Exists", f"A project named '{name}' already exists.")
            return
        touchstone = dialog.touchstone_file() or guess_touchstone_path(name, dialog.ffs_files())
        project = ProjectRecord(
            name=name,
            slug=new_slug,
            ffs_files=[serialize_workspace_path(THIS_DIR, path) for path in dialog.ffs_files()],
            touchstone_file=serialize_workspace_path(THIS_DIR, touchstone),
            settings=self.collect_preset_values(),
        )
        self.project_store.save_project(project, previous_slug=current_slug)
        self.refresh_project_list(select_slug=project.slug)

    def delete_project(self) -> None:
        if not self.active_project_slug:
            QMessageBox.information(self, "No Project Selected", "Select a project to delete.")
            return
        name = self.active_project_name or self.active_project_slug
        answer = QMessageBox.question(
            self,
            "Delete Project",
            f"Delete project '{name}' and everything in its project directory?",
        )
        if answer != QMessageBox.Yes:
            return
        deleted_slug = self.active_project_slug
        self.project_store.delete_project(deleted_slug)
        self.active_project_slug = ""
        self.active_project_name = ""
        self.refresh_project_list(select_slug="")

    def _set_touchstone(self, path: str) -> None:
        resolved = str(resolve_workspace_path(path)) if path else ""
        self.s2p_field.setText(display_workspace_path(resolved))
        self.store.set("vswr_s2p", resolved)
        self.save_active_project()

    def preset_names(self) -> list[str]:
        presets = self.store.get(PRESET_STORE_KEY, {}) or {}
        return sorted(str(name) for name in presets.keys())

    def current_preset_name(self) -> str:
        if not hasattr(self, "preset_combo"):
            return ""
        name = self.preset_combo.currentData()
        return str(name or "")

    def refresh_preset_list(self, select_name: str = "") -> None:
        if not hasattr(self, "preset_combo"):
            return
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("No preset", "")
        for name in self.preset_names():
            self.preset_combo.addItem(name, name)
        index = max(0, self.preset_combo.findData(select_name))
        self.preset_combo.setCurrentIndex(index)
        self.preset_combo.blockSignals(False)

    def collect_preset_values(self) -> dict[str, object]:
        return {
            "smooth": int(self.beam_smooth.value()),
            "theta": float(self.theta_window.value()),
            "smooth2": int(self.plot_smooth.value()),
            "shared_xstep": float(self.shared_xstep.value()),
            "shared_fmin": float(self.shared_fmin.value()),
            "shared_fmax": float(self.shared_fmax.value()),
            "shared_xlog": bool(self.shared_xlog.isChecked()),
            "gain_ymin": float(self.gain_ymin.value()),
            "gain_ymax": float(self.gain_ymax.value()),
            "gain_y_step": float(self.gain_y_step.value()),
            "beamwidth_ymin": float(self.beamwidth_ymin.value()),
            "beamwidth_ymax": float(self.beamwidth_ymax.value()),
            "beamwidth_y_step": float(self.beamwidth_y_step.value()),
            "beam_eff_ymin": float(self.beam_eff_ymin.value()),
            "beam_eff_ymax": float(self.beam_eff_ymax.value()),
            "beam_eff_y_step": float(self.beam_eff_y_step.value()),
            "vswr_ymin": float(self.vswr_ymin.value()),
            "vswr_ymax": float(self.vswr_ymax.value()),
            "vswr_ystep": float(self.vswr_ystep.value()),
            "vswr_smooth": int(self.vswr_smooth.value()),
            "grid_color": self.plot_grid.color(),
            "plot_line_1": self.plot_line1.color(),
            "plot_line_2": self.plot_line2.color(),
            "rings": self.rings.text().strip(),
            "angle": int(self.angle_step.value()),
            "clip": float(self.clip_db.value()),
            "vswr_grid": self.vswr_grid.color(),
            "vswr_line_1": self.vswr_line1.color(),
            "vswr_line_2": self.vswr_line2.color(),
        }

    def apply_preset_values(self, values: dict[str, object]) -> None:
        if not values:
            return
        if "smooth" in values: self.beam_smooth.setValue(int(values["smooth"]))
        if "theta" in values: self.theta_window.setValue(float(values["theta"]))
        if "smooth2" in values: self.plot_smooth.setValue(int(values["smooth2"]))
        if "shared_xstep" in values: self.shared_xstep.setValue(float(values["shared_xstep"]))
        if "shared_fmin" in values: self.shared_fmin.setValue(float(values["shared_fmin"]))
        if "shared_fmax" in values: self.shared_fmax.setValue(float(values["shared_fmax"]))
        if "shared_xlog" in values: self.shared_xlog.setChecked(bool(values["shared_xlog"]))
        if "gain_ymin" in values: self.gain_ymin.setValue(float(values["gain_ymin"]))
        if "gain_ymax" in values: self.gain_ymax.setValue(float(values["gain_ymax"]))
        if "gain_y_step" in values: self.gain_y_step.setValue(float(values["gain_y_step"]))
        if "beamwidth_ymin" in values: self.beamwidth_ymin.setValue(float(values["beamwidth_ymin"]))
        if "beamwidth_ymax" in values: self.beamwidth_ymax.setValue(float(values["beamwidth_ymax"]))
        if "beamwidth_y_step" in values: self.beamwidth_y_step.setValue(float(values["beamwidth_y_step"]))
        if "beam_eff_ymin" in values: self.beam_eff_ymin.setValue(float(values["beam_eff_ymin"]))
        if "beam_eff_ymax" in values: self.beam_eff_ymax.setValue(float(values["beam_eff_ymax"]))
        if "beam_eff_y_step" in values: self.beam_eff_y_step.setValue(float(values["beam_eff_y_step"]))
        if "vswr_ymin" in values: self.vswr_ymin.setValue(float(values["vswr_ymin"]))
        if "vswr_ymax" in values: self.vswr_ymax.setValue(float(values["vswr_ymax"]))
        if "vswr_ystep" in values: self.vswr_ystep.setValue(float(values["vswr_ystep"]))
        if "vswr_smooth" in values: self.vswr_smooth.setValue(int(values["vswr_smooth"]))
        if "grid_color" in values: self.plot_grid.set_color(str(values["grid_color"]))
        if "plot_line_1" in values: self.plot_line1.set_color(str(values["plot_line_1"]))
        if "plot_line_2" in values: self.plot_line2.set_color(str(values["plot_line_2"]))
        if "rings" in values: self.rings.setText(str(values["rings"]))
        if "angle" in values: self.angle_step.setValue(int(values["angle"]))
        if "clip" in values: self.clip_db.setValue(float(values["clip"]))
        if "vswr_grid" in values: self.vswr_grid.set_color(str(values["vswr_grid"]))
        if "vswr_line_1" in values: self.vswr_line1.set_color(str(values["vswr_line_1"]))
        if "vswr_line_2" in values: self.vswr_line2.set_color(str(values["vswr_line_2"]))

    def on_preset_selected(self, _text: str) -> None:
        name = self.current_preset_name()
        self.store.set(ACTIVE_PRESET_KEY, name)
        if not name:
            return
        presets = self.store.get(PRESET_STORE_KEY, {}) or {}
        values = presets.get(name, {})
        if isinstance(values, dict):
            self.apply_preset_values(values)

    def create_preset(self) -> None:
        suggested = suggest_preset_name(self.preset_names(), self.active_project_name or "Preset")
        name, ok = QInputDialog.getText(self, "Create Preset", "Preset name:", text=suggested)
        name = name.strip()
        if not ok or not name:
            return
        presets = self.store.get(PRESET_STORE_KEY, {}) or {}
        if name in presets:
            QMessageBox.information(self, "Preset Exists", f"A preset named '{name}' already exists.")
            return
        presets[name] = self.collect_preset_values()
        self.store.set(PRESET_STORE_KEY, presets)
        self.store.set(ACTIVE_PRESET_KEY, name)
        self.refresh_preset_list(select_name=name)

    def save_preset(self) -> None:
        name = self.current_preset_name()
        if not name:
            self.create_preset()
            return
        presets = self.store.get(PRESET_STORE_KEY, {}) or {}
        presets[name] = self.collect_preset_values()
        self.store.set(PRESET_STORE_KEY, presets)
        self.store.set(ACTIVE_PRESET_KEY, name)
        self.refresh_preset_list(select_name=name)

    def rename_preset(self) -> None:
        name = self.current_preset_name()
        if not name:
            QMessageBox.information(self, "No Preset Selected", "Select a preset to rename.")
            return
        new_name, ok = QInputDialog.getText(self, "Rename Preset", "New preset name:", text=name)
        new_name = new_name.strip()
        if not ok or not new_name or new_name == name:
            return
        presets = self.store.get(PRESET_STORE_KEY, {}) or {}
        if new_name in presets:
            QMessageBox.information(self, "Preset Exists", f"A preset named '{new_name}' already exists.")
            return
        presets[new_name] = presets.pop(name)
        self.store.set(PRESET_STORE_KEY, presets)
        self.store.set(ACTIVE_PRESET_KEY, new_name)
        self.refresh_preset_list(select_name=new_name)

    def delete_preset(self) -> None:
        name = self.current_preset_name()
        if not name:
            QMessageBox.information(self, "No Preset Selected", "Select a preset to delete.")
            return
        if QMessageBox.question(self, "Delete Preset", f"Delete preset '{name}'?") != QMessageBox.Yes:
            return
        presets = self.store.get(PRESET_STORE_KEY, {}) or {}
        presets.pop(name, None)
        self.store.set(PRESET_STORE_KEY, presets)
        self.store.set(ACTIVE_PRESET_KEY, "")
        self.refresh_preset_list(select_name="")

    def import_presets(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Presets", str(self.project_results_dir()), "JSON (*.json)")
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.warning(self, "Import Failed", f"Could not read presets:\n{exc}")
            return
        imported = normalize_preset_payload(payload)
        if not imported:
            QMessageBox.information(self, "No Presets Imported", "The selected file did not contain any valid presets.")
            return
        presets = self.store.get(PRESET_STORE_KEY, {}) or {}
        presets.update(imported)
        self.store.set(PRESET_STORE_KEY, presets)
        self.refresh_preset_list(select_name=self.current_preset_name())
        QMessageBox.information(self, "Presets Imported", f"Imported {len(imported)} preset(s).")

    def export_presets(self) -> None:
        presets = self.store.get(PRESET_STORE_KEY, {}) or {}
        if not presets:
            QMessageBox.information(self, "No Presets", "There are no presets to export.")
            return
        suggested = str((self.project_results_dir() / "antenna_toolkit_presets.json").resolve())
        path, _ = QFileDialog.getSaveFileName(self, "Export Presets", suggested, "JSON (*.json)")
        if not path:
            return
        out_path = Path(path)
        if out_path.suffix.lower() != ".json":
            out_path = out_path.with_suffix(".json")
        out_path.write_text(json.dumps({"presets": presets}, indent=2), encoding="utf-8")
        QMessageBox.information(self, "Presets Exported", f"Exported {len(presets)} preset(s) to:\n{out_path}")

    def _item_path(self, item: QListWidgetItem) -> str:
        return item.data(Qt.UserRole) or str(resolve_workspace_path(item.text()))

    def _add_ffs_files(self, files: list[str], save: bool = True):
        existing = {self._item_path(self.ffs_list.item(i)) for i in range(self.ffs_list.count())}
        for path in files:
            actual = str(resolve_workspace_path(path))
            if actual.lower().endswith(".ffs") and actual not in existing:
                item = QListWidgetItem(display_workspace_path(actual))
                item.setData(Qt.UserRole, actual)
                self.ffs_list.addItem(item)
                existing.add(actual)
        if save:
            self.store.set("beam_ffs", self.selected_ffs())
            self.save_active_project()

    def add_ffs(self):
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Add .ffs", str(THIS_DIR), "CST Farfield (*.ffs)")
        if files:
            self._add_ffs_files(files)

    def remove_ffs(self):
        for item in list(self.ffs_list.selectedItems()):
            self.ffs_list.takeItem(self.ffs_list.row(item))
        self.store.set("beam_ffs", self.selected_ffs())
        self.save_active_project()

    def clear_ffs(self):
        self.ffs_list.clear()
        self.store.set("beam_ffs", [])
        self.save_active_project()

    def browse_s2p(self):
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        fn, _ = QFileDialog.getOpenFileName(self, "Select Touchstone", str(THIS_DIR), "Touchstone (*.s1p *.s2p)")
        if fn:
            self._set_touchstone(fn)

    def clear_s2p(self):
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        self._set_touchstone("")

    def set_busy(self, on: bool):
        self.busy.setVisible(on)
        if on:
            self.busy.setRange(0, 0)
        else:
            self.busy.setRange(0, 100)
            self.busy.setValue(0)

    def set_progress(self, value: int | None):
        if value is None:
            self.busy.setRange(0, 0)
        else:
            if self.busy.maximum() != 100:
                self.busy.setRange(0, 100)
            self.busy.setValue(value)

    def log(self, text: str, color: str | None = None, channel: str | None = None):
        if color:
            safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            self.console.appendHtml(f'<pre style="color:{color}; margin:0">{safe}</pre>')
        else:
            self.console.appendPlainText(text)
        self.console.moveCursor(QTextCursor.End)
        if channel:
            self._line_count = getattr(self, "_line_count", 0) + text.count("\n")
            self._update_run_info()

    def status(self, msg: str):
        self.statusBar().showMessage(msg, 4500)

    def on_proc_started(self, cmd: str):
        self._line_count = 0
        self._started_ts = time.time()
        if not hasattr(self, "_tick"):
            self._tick = QTimer(self)
            self._tick.timeout.connect(self._update_run_info)
        self._tick.start(250)
        self._update_run_info()

    def on_proc_finished(self):
        if hasattr(self, "_tick"):
            self._tick.stop()
        self.run_info.setText("Idle")

    def _update_run_info(self):
        elapsed = int(time.time() - getattr(self, "_started_ts", time.time()))
        mm, ss = divmod(elapsed, 60)
        hh, mm = divmod(mm, 60)
        self.run_info.setText(f"Running | {getattr(self, '_line_count', 0)} lines | {hh:02d}:{mm:02d}:{ss:02d}")

    def run_beam(self):
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        out = str(self.deduced_beam_output())
        ffs = self.selected_ffs()
        if not ffs:
            self.status("Add at least one .ffs file")
            return
        args = [which_python(), "-u", SCRIPT_BEAM, out] + ffs + [
            "--smooth", str(self.beam_smooth.value()),
            "--theta-window", str(self.theta_window.value())
        ]
        self.proc.enqueue(args)

    def build_extract_args(self) -> list[str] | None:
        if not self.active_project_slug:
            return None
        ffs = self.selected_ffs()
        s2p = self.selected_s2p()
        if not ffs and not s2p:
            return None
        args = [which_python(), "-u", SCRIPT_EXTRACT, str(self.deduced_extract_output())]
        args += ffs
        args += [
            "--smooth", str(self.beam_smooth.value()),
            "--theta-window", str(self.theta_window.value())
        ]
        if ffs:
            args += ["--beam-workbook", str(self.deduced_beam_output())]
        if s2p:
            args += ["--touchstone", s2p]
        if self.shared_fmin.value() > 0 and self.shared_fmax.value() > self.shared_fmin.value():
            args += ["--ffs-fmin", f"{self.shared_fmin.value()}", "--ffs-fmax", f"{self.shared_fmax.value()}"]
            args += ["--touchstone-fmin", f"{self.shared_fmin.value()}", "--touchstone-fmax", f"{self.shared_fmax.value()}"]
        return args

    def run_extract(self):
        args = self.build_extract_args()
        if not args:
            self.status("Add at least one .ffs file or select a Touchstone file")
            return
        self.proc.enqueue(args)

    def run_plot(self):
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        xlsx = self.deduced_beam_output()
        if not xlsx.exists():
            self.status("Generate the workbook first")
            return
        args = [which_python(), "-u", SCRIPT_PLOT, str(xlsx),
                "--out-dir", str(self.project_results_dir()),
                "--grid-color", self.plot_grid.color(),
                "--line-colors", ",".join([self.plot_line1.color(), self.plot_line2.color()]),
                "--rings", self.rings.text().strip(),
                "--angle-step", str(self.angle_step.value()),
                "--clip-db", str(self.clip_db.value()),
                "--smooth-window", str(self.plot_smooth.value()),
                "--x-step", str(self.shared_xstep.value())]
        if self.gain_ymin.value() != 0:
            args += ["--gain-ymin", f"{self.gain_ymin.value()}"]
        if self.gain_ymax.value() != 0:
            args += ["--gain-ymax", f"{self.gain_ymax.value()}"]
        if self.gain_y_step.value() != 0:
            args += ["--gain-y-step", f"{self.gain_y_step.value()}"]
        if self.beamwidth_ymin.value() != 0:
            args += ["--beamwidth-ymin", f"{self.beamwidth_ymin.value()}"]
        if self.beamwidth_ymax.value() != 0:
            args += ["--beamwidth-ymax", f"{self.beamwidth_ymax.value()}"]
        if self.beamwidth_y_step.value() != 0:
            args += ["--beamwidth-y-step", f"{self.beamwidth_y_step.value()}"]
        if self.beam_eff_ymin.value() != 0:
            args += ["--beam-eff-ymin", f"{self.beam_eff_ymin.value()}"]
        if self.beam_eff_ymax.value() != 0:
            args += ["--beam-eff-ymax", f"{self.beam_eff_ymax.value()}"]
        if self.beam_eff_y_step.value() != 0:
            args += ["--beam-eff-y-step", f"{self.beam_eff_y_step.value()}"]
        if self.shared_xlog.isChecked():
            args.append("--x-log")
        if self.shared_fmin.value() > 0 and self.shared_fmax.value() > self.shared_fmin.value():
            args += ["--fmin", f"{self.shared_fmin.value()}", "--fmax", f"{self.shared_fmax.value()}"]
        self.proc.enqueue(args)

    def run_vswr(self):
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        s2p = self.selected_s2p()
        if not s2p:
            self.status("Select a .s1p or .s2p file")
            return
        args = [which_python(), "-u", SCRIPT_VSWR, s2p,
                "--output", str(self.deduced_vswr_output()),
                "--grid-color", self.vswr_grid.color(),
                "--line-colors", ",".join([self.vswr_line1.color(), self.vswr_line2.color()]),
                "--x-step", str(self.shared_xstep.value()),
                "--ymin", str(self.vswr_ymin.value()),
                "--ymax", str(self.vswr_ymax.value()),
                "--y-step", str(self.vswr_ystep.value()),
                "--smooth-window", str(self.vswr_smooth.value())]
        if self.shared_xlog.isChecked():
            args.append("--x-log")
        if self.shared_fmin.value() > 0 and self.shared_fmax.value() > self.shared_fmin.value():
            args += ["--fmin", f"{self.shared_fmin.value()}", "--fmax", f"{self.shared_fmax.value()}"]
        self.proc.enqueue(args)

    def run_full(self):
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        out = str(self.deduced_beam_output())
        ffs = self.selected_ffs()
        if not ffs:
            self.status("Add at least one .ffs file")
            return

        args_beam = [which_python(), "-u", SCRIPT_BEAM, out] + ffs + [
            "--smooth", str(self.beam_smooth.value()),
            "--theta-window", str(self.theta_window.value())
        ]
        self.proc.enqueue(args_beam)

        args_extract = self.build_extract_args()
        if args_extract:
            self.proc.enqueue(args_extract)

        args_plot = [which_python(), "-u", SCRIPT_PLOT, out,
                "--out-dir", str(self.project_results_dir()),
                "--grid-color", self.plot_grid.color(),
                "--line-colors", ",".join([self.plot_line1.color(), self.plot_line2.color()]),
                "--rings", self.rings.text().strip(),
                "--angle-step", str(self.angle_step.value()),
                "--clip-db", str(self.clip_db.value()),
                "--smooth-window", str(self.plot_smooth.value()),
                "--x-step", str(self.shared_xstep.value())]
        if self.gain_ymin.value() != 0:
            args_plot += ["--gain-ymin", f"{self.gain_ymin.value()}"]
        if self.gain_ymax.value() != 0:
            args_plot += ["--gain-ymax", f"{self.gain_ymax.value()}"]
        if self.gain_y_step.value() != 0:
            args_plot += ["--gain-y-step", f"{self.gain_y_step.value()}"]
        if self.beamwidth_ymin.value() != 0:
            args_plot += ["--beamwidth-ymin", f"{self.beamwidth_ymin.value()}"]
        if self.beamwidth_ymax.value() != 0:
            args_plot += ["--beamwidth-ymax", f"{self.beamwidth_ymax.value()}"]
        if self.beamwidth_y_step.value() != 0:
            args_plot += ["--beamwidth-y-step", f"{self.beamwidth_y_step.value()}"]
        if self.beam_eff_ymin.value() != 0:
            args_plot += ["--beam-eff-ymin", f"{self.beam_eff_ymin.value()}"]
        if self.beam_eff_ymax.value() != 0:
            args_plot += ["--beam-eff-ymax", f"{self.beam_eff_ymax.value()}"]
        if self.beam_eff_y_step.value() != 0:
            args_plot += ["--beam-eff-y-step", f"{self.beam_eff_y_step.value()}"]
        if self.shared_xlog.isChecked():
            args_plot.append("--x-log")
        if self.shared_fmin.value() > 0 and self.shared_fmax.value() > self.shared_fmin.value():
            args_plot += ["--fmin", f"{self.shared_fmin.value()}", "--fmax", f"{self.shared_fmax.value()}"]
        self.proc.enqueue(args_plot)

        s2p = self.selected_s2p()
        if s2p:
            args_vswr = [which_python(), "-u", SCRIPT_VSWR, s2p,
                    "--output", str(self.deduced_vswr_output()),
                    "--grid-color", self.vswr_grid.color(),
                    "--line-colors", ",".join([self.vswr_line1.color(), self.vswr_line2.color()]),
                    "--x-step", str(self.shared_xstep.value()),
                    "--ymin", str(self.vswr_ymin.value()),
                    "--ymax", str(self.vswr_ymax.value()),
                    "--y-step", str(self.vswr_ystep.value()),
                    "--smooth-window", str(self.vswr_smooth.value())]
            if self.shared_xlog.isChecked():
                args_vswr.append("--x-log")
            if self.shared_fmin.value() > 0 and self.shared_fmax.value() > self.shared_fmin.value():
                args_vswr += ["--fmin", f"{self.shared_fmin.value()}", "--fmax", f"{self.shared_fmax.value()}"]
            self.proc.enqueue(args_vswr)

    def _restore_geometry(self):
        geo = self.store.get("geometry", None)
        if geo:
            try:
                ba = QByteArray.fromBase64(geo.encode("ascii"))
                self.restoreGeometry(ba)
            except Exception:
                pass

    def _save_geometry(self):
        try:
            ba = self.saveGeometry().toBase64().data().decode("ascii")
            self.store.set("geometry", ba)
            self.store.set("studio_split_sizes", self._body_split.sizes())
            if hasattr(self, "console_window"):
                self.console_window._save_geometry()
        except Exception:
            pass

    def closeEvent(self, e):
        self._closing_app = True
        self.store.set("console_visible", bool(hasattr(self, "console_window") and self.console_window.isVisible()))
        self._save_geometry()
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    win = ModernMainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
