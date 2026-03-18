#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
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
    QFormLayout, QFrame, QSizePolicy, QStyleFactory, QMessageBox, QInputDialog,
    QDialog, QDialogButtonBox, QScrollArea, QGridLayout, QTabWidget
)

from antenna_toolkit_qt import (
    THIS_DIR, SCRIPT_BEAM, SCRIPT_EXTRACT, SCRIPT_PLOT, SCRIPT_VSWR,
    suggest_preset_name, normalize_preset_payload,
    DEFAULT_GRID_COLOR, DEFAULT_LINE_COLORS, Persist, Proc,
    which_python, open_in_file_manager, resolve_workspace_path,
    display_workspace_path, deduce_project_name, normalized_project_stem,
)
from project_store import (
    CURRENT_PROJECT_SCHEMA_VERSION, ProjectRecord, ProjectStore, resolve_project_path,
    sanitize_project_slug, serialize_workspace_path, utc_now_iso,
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
STAGE_DEFINITIONS = [
    ("beam", "Workbook"),
    ("extract", "Extract"),
    ("plot", "Plots"),
    ("vswr", "VSWR"),
]
STAGE_LABELS = dict(STAGE_DEFINITIONS)


def format_timestamp(value: str | None) -> str:
    if not value:
        return "Never"
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return str(value)
    return stamp.astimezone().strftime("%Y-%m-%d %H:%M")


def clean_run_state(run_state: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(run_state, dict):
        return {}
    cleaned: dict[str, object] = {}
    for key, value in run_state.items():
        if key == "history":
            if isinstance(value, list) and value:
                cleaned[key] = value
        elif key == "stages":
            if isinstance(value, dict):
                stage_map = {
                    stage_key: stage_value
                    for stage_key, stage_value in value.items()
                    if isinstance(stage_value, dict) and stage_value
                }
                if stage_map:
                    cleaned[key] = stage_map
        elif value not in ({}, [], "", None):
            cleaned[key] = value
    return cleaned


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


class ResponsiveCardPanel(QWidget):
    def __init__(
        self,
        max_columns: int = 3,
        min_card_width: int = 360,
        column_orders: dict[int, list[int]] | None = None,
    ):
        super().__init__()
        self.max_columns = max(1, max_columns)
        self.min_card_width = max(220, min_card_width)
        self.column_orders = column_orders or {}
        self._cards: list[QWidget] = []
        self._columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(12)

    def set_cards(self, cards: list[QWidget]) -> None:
        self._cards = cards
        self.refresh_layout(force=True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.refresh_layout()

    def _desired_columns(self) -> int:
        if not self._cards:
            return 1
        width = max(0, self.width())
        max_columns = min(self.max_columns, len(self._cards))
        gap = max(0, self.grid.horizontalSpacing())
        for columns in range(max_columns, 0, -1):
            required_width = (columns * self.min_card_width) + ((columns - 1) * gap)
            if width >= required_width:
                return columns
        return 1

    def _ordered_cards(self, columns: int) -> list[QWidget]:
        order = self.column_orders.get(columns)
        if not order:
            return list(self._cards)
        seen: set[int] = set()
        ordered_cards: list[QWidget] = []
        for index in order:
            if 0 <= index < len(self._cards) and index not in seen:
                ordered_cards.append(self._cards[index])
                seen.add(index)
        for index, card in enumerate(self._cards):
            if index not in seen:
                ordered_cards.append(card)
        return ordered_cards

    def refresh_layout(self, force: bool = False) -> None:
        columns = self._desired_columns()
        if not force and columns == self._columns:
            return
        self._columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)
        for index, card in enumerate(self._ordered_cards(columns)):
            row = index // columns
            column = index % columns
            self.grid.addWidget(card, row, column)


class ResponsiveButtonPanel(QWidget):
    def __init__(self, max_columns: int = 4, min_button_width: int = 140):
        super().__init__()
        self.max_columns = max(1, max_columns)
        self.min_button_width = max(80, min_button_width)
        self._buttons: list[QWidget] = []
        self._columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)

    def set_buttons(self, buttons: list[QWidget]) -> None:
        self._buttons = buttons
        self.refresh_layout(force=True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.refresh_layout()

    def _desired_columns(self) -> int:
        if not self._buttons:
            return 1
        width = max(self.width(), self.min_button_width)
        max_columns = min(self.max_columns, len(self._buttons))
        gap = max(0, self.grid.horizontalSpacing())
        for columns in range(max_columns, 0, -1):
            required_width = (columns * self.min_button_width) + ((columns - 1) * gap)
            if width >= required_width:
                return columns
        return 1

    def refresh_layout(self, force: bool = False) -> None:
        columns = self._desired_columns()
        if not force and columns == self._columns:
            return
        self._columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)
        for index, button in enumerate(self._buttons):
            row = index // columns
            column = index % columns
            self.grid.addWidget(button, row, column)


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
        self.setFocusProxy(self.spinbox)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.minus = QPushButton("-")
        self.minus.setObjectName("stepButton")
        self.minus.setFixedWidth(30)
        self.minus.setFocusPolicy(Qt.NoFocus)
        self.minus.clicked.connect(lambda: self.spinbox.stepBy(-1))

        self.plus = QPushButton("+")
        self.plus.setObjectName("stepButton")
        self.plus.setFixedWidth(30)
        self.plus.setFocusPolicy(Qt.NoFocus)
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
        self.prev_btn.setFocusPolicy(Qt.NoFocus)
        self.prev_btn.clicked.connect(lambda: self.step_preset(-1))

        self.combo = NoWheelComboBox()
        self.setFocusProxy(self.combo)
        for name, value in self.presets:
            self.combo.addItem(f"{name} ({value})", value)
        self.combo.addItem("Custom", "__custom__")
        self.combo.currentIndexChanged.connect(self._on_combo_changed)

        self.next_btn = QPushButton(">")
        self.next_btn.setObjectName("stepButton")
        self.next_btn.setFixedWidth(34)
        self.next_btn.setFocusPolicy(Qt.NoFocus)
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
        self._suppress_ffs_item_change = False
        self._run_cancelled = False
        self._current_stage_key = ""
        self._pending_stage_keys: list[str] = []
        self._loaded_project_schema_version = CURRENT_PROJECT_SCHEMA_VERSION
        self._saved_project_signature = ""
        self._reverting_project_selection = False
        self.active_project_slug = ""
        self.active_project_name = ""
        self.project_presets: dict[str, dict[str, object]] = {}
        self.project_active_preset = ""
        self.project_run_state: dict[str, object] = {}
        self.theme = str(self.store.get("theme", "light")).lower()
        if self.theme not in {"light", "dark"}:
            self.theme = "light"
        self._build_ui()
        self._apply_style()
        self.refresh_project_list(select_slug="")
        self._reset_to_default_state()
        self._restore_geometry()
        self.store.set("theme", self.theme)

    def _build_ui(self):
        root = QWidget()
        root_lay = QVBoxLayout(root)
        root_lay.setContentsMargins(18, 18, 18, 18)
        root_lay.setSpacing(16)

        title_band = QFrame()
        title_band.setObjectName("titleBand")
        title_lay = QHBoxLayout(title_band)
        title_lay.setContentsMargins(22, 20, 22, 20)
        title_lay.setSpacing(16)

        brand_lay = QVBoxLayout()
        brand_lay.setContentsMargins(0, 0, 0, 0)
        brand_lay.setSpacing(6)
        self.hero_title = QLabel("Antenna Toolkit Studio")
        self.hero_title.setObjectName("brandTitle")
        brand_subtitle = QLabel("Projects now keep inputs, presets, settings, and generated results together in one workspace.")
        brand_subtitle.setObjectName("brandSubtitle")
        brand_subtitle.setWordWrap(True)
        brand_lay.addWidget(self.hero_title)
        brand_lay.addWidget(brand_subtitle)
        title_lay.addLayout(brand_lay, 1)

        title_tools = QHBoxLayout()
        title_tools.setContentsMargins(0, 0, 0, 0)
        title_tools.setSpacing(10)
        self.console_toggle = QPushButton()
        self.console_toggle.setObjectName("ghostButton")
        self.console_toggle.setCheckable(True)
        self.console_toggle.clicked.connect(self.toggle_console)
        self.theme_toggle = QPushButton()
        self.theme_toggle.setObjectName("themeToggle")
        self.theme_toggle.setCheckable(True)
        self.theme_toggle.clicked.connect(self.toggle_theme)
        self.console_toggle.setToolTip("Show or hide the separate output console window.")
        self.theme_toggle.setToolTip("Switch between the light and dark studio themes.")
        title_tools.addWidget(self.console_toggle)
        title_tools.addWidget(self.theme_toggle)
        title_lay.addLayout(title_tools)
        root_lay.addWidget(title_band)

        command_panel = ResponsiveCardPanel(max_columns=2, min_card_width=480)

        project_card = Card("Project workspace", "Command center")
        project_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        project_help = QLabel("Select a project first. Everything else in the window follows that project: inputs, presets, processing settings, and outputs.")
        project_help.setWordWrap(True)
        project_help.setObjectName("helper")
        project_card.body.addWidget(project_help)
        project_row = QVBoxLayout()
        project_row.setContentsMargins(0, 0, 0, 0)
        project_row.setSpacing(8)
        self.project_combo = QComboBox()
        self.project_combo.currentIndexChanged.connect(self.on_project_selected)
        self.project_combo.setToolTip("Select the active project.")
        self.project_new_button = QPushButton("New project")
        self.project_new_button.clicked.connect(self.create_project)
        self.project_save_button = QPushButton("Save project")
        self.project_save_button.clicked.connect(self.save_project_changes)
        self.project_edit_button = QPushButton("Edit project")
        self.project_edit_button.clicked.connect(self.edit_project)
        self.project_duplicate_button = QPushButton("Duplicate")
        self.project_duplicate_button.clicked.connect(self.duplicate_project)
        self.project_delete_button = QPushButton("Delete project")
        self.project_delete_button.clicked.connect(self.delete_project)
        self.project_import_button = QPushButton("Import bundle")
        self.project_import_button.clicked.connect(self.import_project_bundle)
        self.project_export_button = QPushButton("Export bundle")
        self.project_export_button.clicked.connect(self.export_project_bundle)
        self.project_new_button.setToolTip("Create a new project and store its inputs in the Projects directory.")
        self.project_save_button.setToolTip("Write the current project inputs, presets, settings, and run metadata to disk.")
        self.project_edit_button.setToolTip("Rename the active project or update its input files.")
        self.project_duplicate_button.setToolTip("Create a copy of the active project with the same settings and inputs.")
        self.project_delete_button.setToolTip("Delete the active project and everything saved inside its folder.")
        self.project_import_button.setToolTip("Import a previously exported project bundle into the Projects directory.")
        self.project_export_button.setToolTip("Export the active project directory as a bundle.")
        project_row.addWidget(self.project_combo)
        project_actions = ResponsiveButtonPanel(max_columns=3, min_button_width=130)
        project_actions.set_buttons([
            self.project_new_button,
            self.project_save_button,
            self.project_edit_button,
            self.project_duplicate_button,
            self.project_delete_button,
            self.project_import_button,
            self.project_export_button,
        ])
        project_row.addWidget(project_actions)
        project_card.body.addLayout(project_row)
        self.project_name = QLabel("No project selected")
        self.project_name.setObjectName("projectName")
        project_card.body.addWidget(self.project_name)
        self.project_meta = QLabel("Create a project to keep inputs, presets, and generated results together.")
        self.project_meta.setObjectName("projectMeta")
        self.project_meta.setWordWrap(True)
        project_card.body.addWidget(self.project_meta)
        self.project_health = QLabel("No validation issues to report.")
        self.project_health.setObjectName("helper")
        self.project_health.setWordWrap(True)
        project_card.body.addWidget(self.project_health)
        badge_grid = QGridLayout()
        badge_grid.setContentsMargins(0, 0, 0, 0)
        badge_grid.setHorizontalSpacing(8)
        badge_grid.setVerticalSpacing(8)
        self.project_badge = QLabel("Project: none")
        self.project_badge.setObjectName("summaryBadge")
        self.count_badge = QLabel("0 far-field files")
        self.count_badge.setObjectName("summaryBadge")
        self.preset_badge = QLabel("Preset: none")
        self.preset_badge.setObjectName("summaryBadge")
        badge_grid.addWidget(self.project_badge, 0, 0)
        badge_grid.addWidget(self.count_badge, 0, 1)
        badge_grid.addWidget(self.preset_badge, 1, 0, 1, 2)
        project_card.body.addLayout(badge_grid)
        self.project_folder_button = QPushButton("Open Project Folder")
        self.project_folder_button.setObjectName("ghostButton")
        self.project_folder_button.setToolTip("Open the active project's folder in File Explorer.")
        self.project_folder_button.clicked.connect(lambda: open_in_file_manager(self.project_results_dir()))
        project_card.body.addWidget(self.project_folder_button, 0, Qt.AlignLeft)

        quick_actions = Card("Pipeline", "Run")
        quick_actions.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        run_help = QLabel("Use Full Pipeline for the usual workflow. The other actions are for rerunning only one stage after you change inputs or settings.")
        run_help.setObjectName("helper")
        run_help.setWordWrap(True)
        quick_actions.body.addWidget(run_help)
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
        self.btn_cancel = QPushButton("Cancel Run")
        self.btn_cancel.setObjectName("ghostButton")
        self.btn_cancel.clicked.connect(self.cancel_run)
        self.btn_full.setToolTip("Run workbook generation, chart generation, and VSWR generation in sequence.")
        self.btn_beam.setToolTip("Generate only the Excel workbook from the selected far-field files.")
        self.btn_extract.setToolTip("Generate a separate Excel workbook with extracted gain, beamwidth, VSWR, impedance, and front-to-back metrics.")
        self.btn_plot.setToolTip("Generate only the plots that are based on the derived workbook.")
        self.btn_vswr.setToolTip("Generate only the VSWR plot from the current Touchstone file.")
        self.btn_cancel.setToolTip("Stop the current run and clear any queued stages.")
        self.hero_actions = ResponsiveButtonPanel(max_columns=3, min_button_width=150)
        self.hero_actions.set_buttons([
            self.btn_full,
            self.btn_beam,
            self.btn_extract,
            self.btn_plot,
            self.btn_vswr,
            self.btn_cancel,
        ])
        quick_actions.body.addWidget(self.hero_actions)
        self.run_info = QLabel("Idle")
        self.run_info.setObjectName("runInfo")
        self.run_info.setWordWrap(True)
        self.run_summary = QLabel("No run summary yet.")
        self.run_summary.setObjectName("helper")
        self.run_summary.setWordWrap(True)
        self.busy = QProgressBar()
        self.busy.setVisible(False)
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        quick_actions.body.addWidget(self.run_info)
        stage_grid = QGridLayout()
        stage_grid.setContentsMargins(0, 0, 0, 0)
        stage_grid.setHorizontalSpacing(8)
        stage_grid.setVerticalSpacing(8)
        self.stage_status_labels: dict[str, QLabel] = {}
        self.stage_open_buttons: dict[str, QPushButton] = {}
        for index, (stage_key, stage_label) in enumerate(STAGE_DEFINITIONS):
            label = QLabel(f"{stage_label}: waiting")
            label.setObjectName("helper")
            button = QPushButton("Open")
            button.setObjectName("ghostButton")
            button.setFixedWidth(72)
            button.clicked.connect(lambda _checked=False, key=stage_key: self.open_stage_output(key))
            stage_grid.addWidget(label, index, 0)
            stage_grid.addWidget(button, index, 1)
            self.stage_status_labels[stage_key] = label
            self.stage_open_buttons[stage_key] = button
        quick_actions.body.addLayout(stage_grid)
        quick_actions.body.addWidget(self.run_summary)
        quick_actions.body.addWidget(self.busy)
        command_panel.set_cards([project_card, quick_actions])
        root_lay.addWidget(command_panel)

        workspace_shell = QFrame()
        workspace_shell.setObjectName("workspaceShell")
        workspace_shell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        shell_lay = QVBoxLayout(workspace_shell)
        shell_lay.setContentsMargins(20, 20, 20, 20)
        shell_lay.setSpacing(14)
        self.workflow_tabs = QTabWidget()
        self.workflow_tabs.setObjectName("workflowTabs")
        self.workflow_tabs.currentChanged.connect(self.on_tab_changed)
        shell_lay.addWidget(self.workflow_tabs, 1)
        root_lay.addWidget(workspace_shell, 1)

        overview_scroll, _overview_page, overview_lay = self._make_scroll_page()
        inputs_scroll, _inputs_page, inputs_lay = self._make_scroll_page()
        processing_scroll, _processing_page, processing_lay = self._make_scroll_page()
        charts_scroll, _charts_page, charts_lay = self._make_scroll_page()

        outputs_card = Card("Output files", "Results")
        outputs_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        outputs_help = QLabel("All generated files stay inside the active project folder so the deliverables are always tied to the correct input set.")
        outputs_help.setWordWrap(True)
        outputs_help.setObjectName("helper")
        outputs_card.body.addWidget(outputs_help)
        self.project_stats_label = QLabel("No project stats yet.")
        self.project_stats_label.setObjectName("helper")
        self.project_stats_label.setWordWrap(True)
        outputs_card.body.addWidget(self.project_stats_label)
        self.artifact_summary_label = QLabel("Artifacts will appear here after the first run.")
        self.artifact_summary_label.setObjectName("helper")
        self.artifact_summary_label.setWordWrap(True)
        outputs_card.body.addWidget(self.artifact_summary_label)
        self.workbook_field = QLineEdit(); self.workbook_field.setReadOnly(True)
        self.extract_field = QLineEdit(); self.extract_field.setReadOnly(True)
        self.results_field = QLineEdit(); self.results_field.setReadOnly(True)
        self.vswr_field = QLineEdit(); self.vswr_field.setReadOnly(True)
        self.workbook_field.setToolTip("Workbook stored inside the selected project directory.")
        self.extract_field.setToolTip("Extracted-data workbook stored inside the selected project directory.")
        self.results_field.setToolTip("Project directory containing metadata and generated outputs.")
        self.vswr_field.setToolTip("VSWR plot stored inside the selected project directory.")
        form = QFormLayout()
        form.addRow("Project folder", self._path_row(self.results_field))
        form.addRow("Workbook", self._path_row(self.workbook_field))
        form.addRow("Extract workbook", self._path_row(self.extract_field))
        form.addRow("VSWR output", self._path_row(self.vswr_field))
        outputs_card.body.addLayout(form)

        preset_card = Card("Saved presets", "Presets")
        preset_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        preset_help = QLabel("Save reusable control/range/style presets for product lines. Presets do not change the currently selected input files.")
        preset_help.setWordWrap(True)
        preset_help.setObjectName("helper")
        preset_card.body.addWidget(preset_help)
        self.preset_combo = QComboBox()
        self.preset_combo.currentTextChanged.connect(self.on_preset_selected)
        self.preset_combo.setToolTip("Choose a saved preset to apply its control, range, and style settings.")
        preset_card.body.addWidget(self.preset_combo)
        self.preset_state_label = QLabel("Choose a preset or keep working manually.")
        self.preset_state_label.setObjectName("helper")
        self.preset_state_label.setWordWrap(True)
        preset_card.body.addWidget(self.preset_state_label)
        self.preset_new_button = QPushButton("New"); self.preset_new_button.clicked.connect(self.create_preset)
        self.preset_save_button = QPushButton("Save"); self.preset_save_button.clicked.connect(self.save_preset)
        self.preset_rename_button = QPushButton("Rename"); self.preset_rename_button.clicked.connect(self.rename_preset)
        self.preset_delete_button = QPushButton("Delete"); self.preset_delete_button.clicked.connect(self.delete_preset)
        self.preset_new_button.setToolTip("Create a new preset from the current GUI settings. Use Save project to persist it.")
        self.preset_save_button.setToolTip("Overwrite the selected preset with the current GUI settings. Use Save project to persist it.")
        self.preset_rename_button.setToolTip("Rename the selected preset without changing its settings. Use Save project to persist it.")
        self.preset_delete_button.setToolTip("Delete the selected preset. Use Save project to persist it.")
        preset_actions = ResponsiveButtonPanel(max_columns=4, min_button_width=110)
        preset_actions.set_buttons([self.preset_new_button, self.preset_save_button, self.preset_rename_button, self.preset_delete_button])
        preset_card.body.addWidget(preset_actions)
        self.preset_import_button = QPushButton("Import"); self.preset_import_button.clicked.connect(self.import_presets)
        self.preset_export_button = QPushButton("Export"); self.preset_export_button.clicked.connect(self.export_presets)
        self.preset_import_button.setToolTip("Import presets from a JSON file and merge them into the current list. Use Save project to persist them.")
        self.preset_export_button.setToolTip("Export all saved presets to a JSON file.")
        preset_io = ResponsiveButtonPanel(max_columns=2, min_button_width=120)
        preset_io.set_buttons([self.preset_import_button, self.preset_export_button])
        preset_card.body.addWidget(preset_io)
        storage_card = Card("Workspace guide", "Flow")
        storage_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        storage_note = QLabel(
            "1. Add or edit project inputs on the Inputs tab.\n"
            "2. Tune smoothing and frequency limits on Processing.\n"
            "3. Adjust chart ranges and colors on Charts, then run the pipeline from the top command area."
        )
        storage_note.setWordWrap(True)
        storage_note.setObjectName("helper")
        storage_card.body.addWidget(storage_note)
        validation_card = Card("Validation", "Checks")
        validation_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.validation_label = QLabel("No validation issues.")
        self.validation_label.setObjectName("helper")
        self.validation_label.setWordWrap(True)
        validation_card.body.addWidget(self.validation_label)
        activity_card = Card("Recent activity", "Runs")
        activity_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.last_run_label = QLabel("Last successful run: never")
        self.last_run_label.setObjectName("helper")
        self.last_run_label.setWordWrap(True)
        self.run_state_label = QLabel("No stage history yet.")
        self.run_state_label.setObjectName("helper")
        self.run_state_label.setWordWrap(True)
        activity_card.body.addWidget(self.last_run_label)
        activity_card.body.addWidget(self.run_state_label)
        overview_panel = ResponsiveCardPanel(max_columns=3, min_card_width=320, column_orders={2: [0, 3, 1, 4, 2]})
        overview_panel.set_cards([outputs_card, preset_card, storage_card, validation_card, activity_card])
        overview_lay.addWidget(overview_panel)
        overview_lay.addStretch(1)

        ffs_card = Card("Far-field files", "Primary input")
        ffs_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        helper = QLabel("Drop .ffs files here or add them manually. Changes are saved into the active project.")
        helper.setWordWrap(True)
        helper.setObjectName("helper")
        ffs_card.body.addWidget(helper)
        self.ffs_list = DropList(self._add_ffs_files)
        self.ffs_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ffs_list.setMinimumHeight(230)
        self.ffs_list.setToolTip("Add one or more CST far-field export files (.ffs). Their names drive project-name deduction.")
        self.ffs_list.itemChanged.connect(self.on_ffs_item_changed)
        self.ffs_list.itemSelectionChanged.connect(self._update_ffs_action_state)
        ffs_card.body.addWidget(self.ffs_list, 1)
        self.add_ffs_button = QPushButton("Add .ffs"); self.add_ffs_button.clicked.connect(self.add_ffs)
        self.remove_ffs_button = QPushButton("Remove selected"); self.remove_ffs_button.clicked.connect(self.remove_ffs)
        self.clear_ffs_button = QPushButton("Clear list"); self.clear_ffs_button.clicked.connect(self.clear_ffs)
        self.ffs_up_button = QPushButton("Move up"); self.ffs_up_button.clicked.connect(self.move_ffs_up)
        self.ffs_down_button = QPushButton("Move down"); self.ffs_down_button.clicked.connect(self.move_ffs_down)
        self.ffs_sort_button = QPushButton("Sort"); self.ffs_sort_button.clicked.connect(self.sort_ffs)
        self.ffs_toggle_button = QPushButton("Enable/disable"); self.ffs_toggle_button.clicked.connect(self.toggle_selected_ffs_enabled)
        self.ffs_missing_button = QPushButton("Remove missing"); self.ffs_missing_button.clicked.connect(self.remove_missing_ffs)
        self.add_ffs_button.setToolTip("Browse for CST far-field export files to include in this project.")
        self.remove_ffs_button.setToolTip("Remove the highlighted far-field files from the current project.")
        self.clear_ffs_button.setToolTip("Clear the full far-field file list.")
        self.ffs_up_button.setToolTip("Move the selected far-field files up in the processing order.")
        self.ffs_down_button.setToolTip("Move the selected far-field files down in the processing order.")
        self.ffs_sort_button.setToolTip("Sort far-field files alphabetically by display name.")
        self.ffs_toggle_button.setToolTip("Temporarily disable or re-enable the selected far-field files without deleting them.")
        self.ffs_missing_button.setToolTip("Remove any far-field entries that no longer exist on disk.")
        ffs_actions = ResponsiveButtonPanel(max_columns=3, min_button_width=135)
        ffs_actions.set_buttons([
            self.add_ffs_button,
            self.remove_ffs_button,
            self.clear_ffs_button,
            self.ffs_up_button,
            self.ffs_down_button,
            self.ffs_sort_button,
            self.ffs_toggle_button,
            self.ffs_missing_button,
        ])
        ffs_card.body.addWidget(ffs_actions)

        inputs_help_card = Card("Input guide", "Flow")
        inputs_help_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        inputs_help = QLabel(
            "The far-field list is the main input for workbook generation.\n"
            "Touchstone is optional unless you need the VSWR plot.\n"
            "Project changes are saved automatically as you edit the inputs."
        )
        inputs_help.setWordWrap(True)
        inputs_help.setObjectName("helper")
        inputs_help_card.body.addWidget(inputs_help)

        s2p_card = Card("Touchstone file", "VSWR")
        s2p_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.s2p_field = QLineEdit("")
        self.s2p_field.setReadOnly(True)
        self.s2p_field.setToolTip("Detected or manually selected Touchstone file used for the VSWR plot (.s1p or .s2p).")
        s2p_card.body.addWidget(self.s2p_field)
        self.select_s2p_button = QPushButton("Select Touchstone"); self.select_s2p_button.clicked.connect(self.browse_s2p)
        self.clear_s2p_button = QPushButton("Clear"); self.clear_s2p_button.clicked.connect(self.clear_s2p)
        self.open_s2p_button = QPushButton("Open"); self.open_s2p_button.clicked.connect(lambda: open_in_file_manager(resolve_workspace_path(self.s2p_field.text())))
        self.select_s2p_button.setToolTip("Choose a Touchstone file manually if the automatic project match is not the one you want.")
        self.clear_s2p_button.setToolTip("Clear the current Touchstone selection and let deduction run again.")
        self.open_s2p_button.setToolTip("Open the selected Touchstone file in File Explorer.")
        s2p_actions = ResponsiveButtonPanel(max_columns=3, min_button_width=145)
        s2p_actions.set_buttons([self.select_s2p_button, self.clear_s2p_button, self.open_s2p_button])
        s2p_card.body.addWidget(s2p_actions)
        inputs_panel = ResponsiveCardPanel(max_columns=3, min_card_width=320, column_orders={2: [0, 2, 1]})
        inputs_panel.set_cards([ffs_card, s2p_card, inputs_help_card])
        inputs_lay.addWidget(inputs_panel)
        inputs_lay.addStretch(1)

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
        workbook_card = Card("Beam, workbook, and VSWR smoothing", "Processing")
        workbook_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        workbook_card.setMinimumWidth(320)
        workbook_form = QFormLayout()
        workbook_form.setContentsMargins(0, 0, 0, 0)
        workbook_form.setHorizontalSpacing(10)
        workbook_form.setVerticalSpacing(8)
        workbook_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        workbook_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_form_row(workbook_form, "Beam smooth", StepperField(self.beam_smooth), "Smoothing window used while creating the workbook from the far-field files. Higher values smooth more aggressively.")
        add_form_row(workbook_form, "Theta window", StepperField(self.theta_window), "Angular window in degrees used for the beamwidth calculation around the main lobe.")
        add_form_row(workbook_form, "Plot smooth", StepperField(self.plot_smooth), "Smoothing window applied to the workbook-based line plots.")
        add_form_row(workbook_form, "VSWR smooth", StepperField(self.vswr_smooth), "Smoothing window applied to the VSWR traces.")
        workbook_card.body.addLayout(workbook_form)

        frequency_card = Card("Shared frequency window", "Frequency")
        frequency_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        frequency_card.setMinimumWidth(320)
        frequency_form = QFormLayout()
        frequency_form.setContentsMargins(0, 0, 0, 0)
        frequency_form.setHorizontalSpacing(10)
        frequency_form.setVerticalSpacing(8)
        frequency_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        frequency_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_form_row(frequency_form, "Shared x tick", StepperField(self.shared_xstep), "Spacing between x-axis tick labels used by both workbook plots and the VSWR plot, in GHz.")
        add_form_row(frequency_form, "Shared fmin", StepperField(self.shared_fmin), "Lower frequency bound used by both workbook plots and the VSWR plot, in GHz. Use 0 to keep the full range.")
        add_form_row(frequency_form, "Shared fmax", StepperField(self.shared_fmax), "Upper frequency bound used by both workbook plots and the VSWR plot, in GHz. Use 0 to keep the full range.")
        add_form_row(frequency_form, "Shared x axis", self.shared_xlog, "Switch both workbook plots and the VSWR plot between linear and logarithmic x-axis scaling.")
        frequency_card.body.addLayout(frequency_form)
        processing_help = Card("When to rerun", "Flow")
        processing_help.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        processing_note = QLabel(
            "Run Full Pipeline when the inputs changed and you want the full deliverable.\n"
            "Use Workbook Only after changing far-field files or smoothing.\n"
            "Use Plots Only after changing chart ranges or colors.\n"
            "Use VSWR Only after changing the Touchstone file or VSWR settings."
        )
        processing_note.setWordWrap(True)
        processing_note.setObjectName("helper")
        processing_help.body.addWidget(processing_note)
        processing_panel = ResponsiveCardPanel(max_columns=3, min_card_width=320, column_orders={2: [0, 2, 1]})
        processing_panel.set_cards([workbook_card, frequency_card, processing_help])
        processing_lay.addWidget(processing_panel)
        processing_lay.addStretch(1)

        gain_range_card = Card("Gain range", "Ranges")
        gain_range_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        gain_range_card.setMinimumWidth(320)
        gain_range_form = QFormLayout()
        gain_range_form.setContentsMargins(0, 0, 0, 0)
        gain_range_form.setHorizontalSpacing(10)
        gain_range_form.setVerticalSpacing(8)
        gain_range_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        gain_range_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_form_row(gain_range_form, "Gain y min", StepperField(self.gain_ymin), "Lower limit override for the gain plot. Use 0 to keep the default automatic minimum.")
        add_form_row(gain_range_form, "Gain y max", StepperField(self.gain_ymax), "Upper limit override for the gain plot. Use 0 to keep the default automatic maximum.")
        add_form_row(gain_range_form, "Gain y tick", StepperField(self.gain_y_step), "Y-axis tick spacing override for the gain plot. Use 0 to keep the default tick spacing.")
        gain_range_card.body.addLayout(gain_range_form)

        beamwidth_range_card = Card("Beamwidth range", "Ranges")
        beamwidth_range_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        beamwidth_range_card.setMinimumWidth(320)
        beamwidth_range_form = QFormLayout()
        beamwidth_range_form.setContentsMargins(0, 0, 0, 0)
        beamwidth_range_form.setHorizontalSpacing(10)
        beamwidth_range_form.setVerticalSpacing(8)
        beamwidth_range_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        beamwidth_range_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_form_row(beamwidth_range_form, "Beamwidth y min", StepperField(self.beamwidth_ymin), "Lower limit override for the beamwidth plot. Use 0 to keep the default automatic minimum.")
        add_form_row(beamwidth_range_form, "Beamwidth y max", StepperField(self.beamwidth_ymax), "Upper limit override for the beamwidth plot. Use 0 to keep the default automatic maximum.")
        add_form_row(beamwidth_range_form, "Beamwidth y tick", StepperField(self.beamwidth_y_step), "Y-axis tick spacing override for the beamwidth plot. Use 0 to keep the default tick spacing.")
        beamwidth_range_card.body.addLayout(beamwidth_range_form)

        efficiency_range_card = Card("Efficiency range", "Ranges")
        efficiency_range_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        efficiency_range_card.setMinimumWidth(320)
        efficiency_range_form = QFormLayout()
        efficiency_range_form.setContentsMargins(0, 0, 0, 0)
        efficiency_range_form.setHorizontalSpacing(10)
        efficiency_range_form.setVerticalSpacing(8)
        efficiency_range_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        efficiency_range_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_form_row(efficiency_range_form, "Beam eff y min", StepperField(self.beam_eff_ymin), "Lower limit override for the beam efficiency plot. Use 0 to keep the default automatic minimum.")
        add_form_row(efficiency_range_form, "Beam eff y max", StepperField(self.beam_eff_ymax), "Upper limit override for the beam efficiency plot. Use 0 to keep the default automatic maximum.")
        add_form_row(efficiency_range_form, "Beam eff y tick", StepperField(self.beam_eff_y_step), "Y-axis tick spacing override for the beam efficiency plot. Use 0 to keep the default tick spacing.")
        efficiency_range_card.body.addLayout(efficiency_range_form)

        vswr_range_card = Card("VSWR range", "Ranges")
        vswr_range_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        vswr_range_card.setMinimumWidth(320)
        vswr_range_form = QFormLayout()
        vswr_range_form.setContentsMargins(0, 0, 0, 0)
        vswr_range_form.setHorizontalSpacing(10)
        vswr_range_form.setVerticalSpacing(8)
        vswr_range_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        vswr_range_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_form_row(vswr_range_form, "VSWR y min", StepperField(self.vswr_ymin), "Lower limit of the VSWR y-axis.")
        add_form_row(vswr_range_form, "VSWR y max", StepperField(self.vswr_ymax), "Upper limit of the VSWR y-axis.")
        add_form_row(vswr_range_form, "VSWR y tick", StepperField(self.vswr_ystep), "Spacing between VSWR y-axis tick labels.")
        vswr_range_card.body.addLayout(vswr_range_form)

        polar_card = Card("Polar plot", "Polar")
        polar_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        polar_card.setMinimumWidth(320)
        self.plot_grid = StudioColorSelector(self.store, "grid_color", DEFAULT_GRID_COLOR, presets=GREY_COLOR_OPTIONS)
        self.plot_line1 = StudioColorSelector(self.store, "plot_line_1", DEFAULT_LINE_COLORS[0][1])
        self.plot_line2 = StudioColorSelector(self.store, "plot_line_2", DEFAULT_LINE_COLORS[1][1])
        self.rings = QLineEdit(self.store.get("rings", "0,-7.5,-15,-22.5,-30")); self.rings.textChanged.connect(lambda v: self.store.set("rings", v))
        self.angle_step = NoWheelSpinBox(); self.angle_step.setRange(5, 90); self.angle_step.setSingleStep(5); self.angle_step.setValue(int(self.store.get("angle", 30))); self.angle_step.valueChanged.connect(lambda v: self.store.set("angle", int(v)))
        self.clip_db = TrimmedDoubleSpinBox(); self.clip_db.setRange(-120.0, 0.0); self.clip_db.setDecimals(6); self.clip_db.setSingleStep(0.5); self.clip_db.setValue(float(self.store.get("clip", -30.0))); self.clip_db.valueChanged.connect(lambda v: self.store.set("clip", float(v)))
        self.rings.setToolTip("Comma-separated dB ring values used on the polar plots.")
        polar_form = QFormLayout()
        polar_form.setContentsMargins(0, 0, 0, 0)
        polar_form.setHorizontalSpacing(10)
        polar_form.setVerticalSpacing(8)
        polar_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        polar_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_form_row(polar_form, "Polar rings", self.rings, "Comma-separated dB ring values used on the polar plots.")
        add_form_row(polar_form, "Polar angle step", StepperField(self.angle_step), "Angle spacing, in degrees, for polar plot annotations.")
        add_form_row(polar_form, "Polar clip below", StepperField(self.clip_db), "Clip polar-plot values below this dB level to keep the chart readable.")
        polar_card.body.addLayout(polar_form)

        plot_color_card = Card("Plot colors", "Style")
        plot_color_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        plot_color_card.setMinimumWidth(320)
        plot_color_form = QFormLayout()
        plot_color_form.setContentsMargins(0, 0, 0, 0)
        plot_color_form.setHorizontalSpacing(10)
        plot_color_form.setVerticalSpacing(8)
        plot_color_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        plot_color_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_form_row(plot_color_form, "Grid color", self.plot_grid, "Grid and axis color used by both the workbook plots and the VSWR plot. Presets are neutral greys, with a custom color option.")
        add_form_row(plot_color_form, "Line color 1", self.plot_line1, "Primary line color used by both the workbook plots and the VSWR plot.")
        add_form_row(plot_color_form, "Line color 2", self.plot_line2, "Secondary line color used by both the workbook plots and the VSWR plot.")
        plot_color_card.body.addLayout(plot_color_form)

        charts_panel = ResponsiveCardPanel(max_columns=3, min_card_width=320, column_orders={2: [0, 1, 2, 5, 3, 4]})
        charts_panel.set_cards([gain_range_card, beamwidth_range_card, efficiency_range_card, vswr_range_card, polar_card, plot_color_card])
        charts_lay.addWidget(charts_panel)
        charts_lay.addStretch(1)

        self.workflow_tabs.addTab(overview_scroll, "Overview")
        self.workflow_tabs.addTab(inputs_scroll, "Inputs")
        self.workflow_tabs.addTab(processing_scroll, "Processing")
        self.workflow_tabs.addTab(charts_scroll, "Charts")
        self.setCentralWidget(root)

        self.console_window = ConsoleWindow(self, self.store)
        self.console = self.console_window.console
        self._set_console_visible(False, persist=False)

        self._bind_project_persistence()
        self.refresh_preset_list()
        self._sync_theme_toggle()
        self._sync_console_toggle()
        self.workflow_tabs.setCurrentIndex(0)
        self.on_tab_changed(self.workflow_tabs.currentIndex())

    def _make_scroll_page(self) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll, content, layout

    def on_tab_changed(self, index: int) -> None:
        if index < 0:
            return
        self.store.set("studio_nav_index", index)

    def _reset_to_default_state(self) -> None:
        self._loading_project = True
        self.active_project_slug = ""
        self.active_project_name = ""
        self.project_presets = {}
        self.project_active_preset = ""
        self.project_run_state = {}
        self._saved_project_signature = ""
        self._pending_stage_keys = []
        self._current_stage_key = ""
        self._loaded_project_schema_version = CURRENT_PROJECT_SCHEMA_VERSION
        self.ffs_list.clear()
        self.s2p_field.clear()
        self.beam_smooth.setValue(5)
        self.theta_window.setValue(8.0)
        self.plot_smooth.setValue(5)
        self.shared_xstep.setValue(0.2)
        self.shared_fmin.setValue(0.0)
        self.shared_fmax.setValue(0.0)
        self.shared_xlog.setChecked(False)
        self.gain_ymin.setValue(0.0)
        self.gain_ymax.setValue(0.0)
        self.gain_y_step.setValue(0.0)
        self.beamwidth_ymin.setValue(0.0)
        self.beamwidth_ymax.setValue(0.0)
        self.beamwidth_y_step.setValue(0.0)
        self.beam_eff_ymin.setValue(0.0)
        self.beam_eff_ymax.setValue(0.0)
        self.beam_eff_y_step.setValue(0.0)
        self.vswr_ymin.setValue(1.0)
        self.vswr_ymax.setValue(10.0)
        self.vswr_ystep.setValue(1.0)
        self.vswr_smooth.setValue(5)
        self.plot_grid.set_color(DEFAULT_GRID_COLOR, persist=False)
        self.plot_line1.set_color(DEFAULT_LINE_COLORS[0][1], persist=False)
        self.plot_line2.set_color(DEFAULT_LINE_COLORS[1][1], persist=False)
        self.rings.setText("0,-7.5,-15,-22.5,-30")
        self.angle_step.setValue(30)
        self.clip_db.setValue(-30.0)
        self.workflow_tabs.setCurrentIndex(0)
        self.refresh_preset_list(select_name="")
        self.project_combo.blockSignals(True)
        self.project_combo.setCurrentIndex(0)
        self.project_combo.blockSignals(False)
        self.store.set("active_project", "")
        self._loading_project = False
        self.refresh_derived_paths()

    def _project_signature(self, project: ProjectRecord | None = None) -> str:
        project = project or self.current_project()
        if not project:
            return ""
        return json.dumps(project.to_dict(), sort_keys=True)

    def _capture_saved_project_signature(self, project: ProjectRecord | None = None) -> None:
        self._saved_project_signature = self._project_signature(project)

    def has_unsaved_project_changes(self) -> bool:
        if self._loading_project or not self.active_project_slug:
            return False
        return self._project_signature() != self._saved_project_signature

    def _mark_project_dirty(self) -> None:
        if self._loading_project or not self.active_project_slug:
            return
        self.refresh_derived_paths()

    def _confirm_pending_project_changes(self, action: str) -> bool:
        if not self.has_unsaved_project_changes():
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved Changes",
            f"The current project or its presets have unsaved changes. Save before {action}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            self.save_active_project()
        return True

    def _save_project_if_dirty(self) -> None:
        if self.has_unsaved_project_changes():
            self.save_active_project()

    def save_project_changes(self) -> None:
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        self.save_active_project()
        self.status("Project saved")

    def _path_row(self, field: QLineEdit) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(field, 1)
        btn = QPushButton("Open")
        btn.setToolTip("Open this location in File Explorer.")
        btn.clicked.connect(lambda: open_in_file_manager(resolve_workspace_path(field.text())))
        field.textChanged.connect(lambda text: btn.setEnabled(bool(str(text).strip())))
        btn.setEnabled(bool(field.text().strip()))
        lay.addWidget(btn)
        return row

    def _apply_style(self):
        QApplication.setStyle(QStyleFactory.create("Fusion"))
        pal = QPalette()
        if self.theme == "dark":
            pal.setColor(QPalette.Window, QColor("#10161d"))
            pal.setColor(QPalette.WindowText, QColor("#f4f6f8"))
            pal.setColor(QPalette.Base, QColor("#121a22"))
            pal.setColor(QPalette.Text, QColor("#f4f6f8"))
            pal.setColor(QPalette.Highlight, QColor("#e4874a"))
            pal.setColor(QPalette.HighlightedText, QColor("#10161d"))
            window_bg = "#10161d"
            title_band_bg = "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #0d1722, stop:0.55 #163247, stop:1 #214e4a)"
            title_subtle = "rgba(226,232,240,0.82)"
            shell_bg = "#16202a"
            shell_border = "#283645"
            card_bg = "#1b2630"
            card_border = "#30414f"
            title_color = "#f4f6f8"
            text_color = "#d5dee5"
            input_bg = "#121a22"
            input_border = "#32424f"
            button_bg = "#202b35"
            button_hover = "#283640"
            list_selected = "#29414c"
            primary_bg = "#e4874a"
            primary_hover = "#d77433"
            progress_bg = "rgba(255,255,255,0.08)"
            ghost_bg = "#1f2a33"
            ghost_hover = "#293640"
            step_bg = "#141c24"
            step_hover = "#1c2630"
            step_border = "#3a4a57"
            helper_color = "#9fb1bf"
            tab_bg = "#202c37"
            tab_hover = "#253440"
            tab_selected = "#1b2630"
            badge_bg = "rgba(228,135,74,0.14)"
            badge_border = "#7b4d2f"
            badge_text = "#ffd8c2"
            eyebrow_color = "#6fc7ae"
        else:
            pal.setColor(QPalette.Window, QColor("#efe7dc"))
            pal.setColor(QPalette.WindowText, QColor("#182635"))
            pal.setColor(QPalette.Base, QColor("#fffaf2"))
            pal.setColor(QPalette.Text, QColor("#182635"))
            pal.setColor(QPalette.Highlight, QColor("#c76a38"))
            pal.setColor(QPalette.HighlightedText, QColor("#fffaf2"))
            window_bg = "#efe7dc"
            title_band_bg = "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #142033, stop:0.55 #26445b, stop:1 #496f63)"
            title_subtle = "rgba(241,245,249,0.84)"
            shell_bg = "#f7f1e7"
            shell_border = "#d8c8b4"
            card_bg = "#fffaf2"
            card_border = "#d9ccb9"
            title_color = "#182635"
            text_color = "#314354"
            input_bg = "#f6efe4"
            input_border = "#d7c8b4"
            button_bg = "#fff9ef"
            button_hover = "#f4e8d7"
            list_selected = "#f3dfca"
            primary_bg = "#c76a38"
            primary_hover = "#b85a25"
            progress_bg = "rgba(54,73,92,0.12)"
            ghost_bg = "#eee4d6"
            ghost_hover = "#e5d7c4"
            step_bg = "#f1e6d6"
            step_hover = "#e8dac4"
            step_border = "#c7b59b"
            helper_color = "#697887"
            tab_bg = "#e7ddcf"
            tab_hover = "#ded1bf"
            tab_selected = "#fffaf2"
            badge_bg = "rgba(199,106,56,0.10)"
            badge_border = "#d9b292"
            badge_text = "#7b4628"
            eyebrow_color = "#2f7d6a"
        QApplication.setPalette(pal)
        app = QApplication.instance()
        if app:
            app.setStyleSheet("""
                QWidget { font-family: "Segoe UI"; font-size: 10.5pt; }
                QMainWindow { background: %(window_bg)s; }
                QScrollArea { background: transparent; border: none; }
                #titleBand { border-radius: 28px; background: %(title_band_bg)s; }
                #workspaceShell { background: %(shell_bg)s; border: 1px solid %(shell_border)s; border-radius: 28px; }
                #brandTitle { color: white; font-family: "Bahnschrift"; font-size: 20pt; font-weight: 700; }
                #brandSubtitle { color: %(title_subtle)s; font-size: 10pt; }
                #runInfo { color: %(text_color)s; font-size: 10pt; }
                #card { background: %(card_bg)s; border: 1px solid %(card_border)s; border-radius: 20px; }
                #cardTitle { color: %(title_color)s; font-size: 13pt; font-weight: 700; }
                #eyebrow { color: %(eyebrow_color)s; font-size: 8.5pt; font-weight: 700; }
                #projectName { color: %(title_color)s; font-size: 18pt; font-weight: 700; }
                #projectMeta { color: %(helper_color)s; font-size: 10pt; }
                #summaryBadge { background: %(badge_bg)s; color: %(badge_text)s; border: 1px solid %(badge_border)s; border-radius: 12px; padding: 6px 10px; font-size: 8.75pt; font-weight: 700; }
                QLabel { color: %(text_color)s; }
                #helper { color: %(helper_color)s; }
                QTabWidget::pane { border: none; background: transparent; margin-top: 8px; }
                QTabBar::tab { background: %(tab_bg)s; border: 1px solid %(shell_border)s; border-bottom: none; border-top-left-radius: 14px; border-top-right-radius: 14px; padding: 10px 16px; margin-right: 6px; min-width: 110px; color: %(helper_color)s; font-weight: 700; }
                QTabBar::tab:hover { background: %(tab_hover)s; color: %(title_color)s; }
                QTabBar::tab:selected { background: %(tab_selected)s; color: %(title_color)s; }
                QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget, QPlainTextEdit { background: %(input_bg)s; border: 1px solid %(input_border)s; border-radius: 14px; padding: 8px 11px; color: %(title_color)s; }
                QComboBox::drop-down { border: none; width: 28px; }
                QComboBox QAbstractItemView { background: %(card_bg)s; border: 1px solid %(card_border)s; color: %(title_color)s; selection-background-color: %(list_selected)s; selection-color: %(title_color)s; }
                QListWidget::item { padding: 7px 10px; border-radius: 10px; margin: 1px 0; }
                QListWidget::item:selected { background: %(list_selected)s; color: %(title_color)s; }
                QPushButton { background: %(button_bg)s; border: 1px solid %(input_border)s; border-radius: 14px; padding: 9px 13px; color: %(title_color)s; font-weight: 600; }
                QPushButton:hover { border-color: #7fb2cf; background: %(button_hover)s; }
                QPushButton:disabled { color: %(helper_color)s; background: %(input_bg)s; border-color: %(card_border)s; }
                QPushButton#primaryButton { background: %(primary_bg)s; color: white; border: none; padding: 10px 16px; }
                QPushButton#primaryButton:hover { background: %(primary_hover)s; }
                QPushButton#themeToggle { min-width: 120px; }
                QPushButton#ghostButton { background: %(ghost_bg)s; }
                QPushButton#ghostButton:hover { background: %(ghost_hover)s; }
                QPushButton#stepButton { background: %(step_bg)s; border: 1px solid %(step_border)s; border-radius: 12px; padding: 6px 0; font-size: 11pt; font-weight: 700; min-width: 30px; }
                QPushButton#stepButton:hover { background: %(step_hover)s; border-color: #7fb2cf; }
                QCheckBox#pillCheck { spacing: 8px; padding: 7px 10px; border: 1px solid %(input_border)s; border-radius: 12px; background: %(ghost_bg)s; color: %(title_color)s; font-weight: 600; }
                QCheckBox#pillCheck:hover { border-color: #7fb2cf; background: %(ghost_hover)s; }
                QCheckBox#pillCheck::indicator { width: 16px; height: 16px; border-radius: 8px; border: 1px solid %(step_border)s; background: transparent; }
                QCheckBox#pillCheck::indicator:checked { background: %(primary_bg)s; border-color: %(primary_bg)s; }
                QProgressBar { background: %(progress_bg)s; border: 1px solid %(card_border)s; border-radius: 10px; color: %(title_color)s; min-height: 18px; }
                QProgressBar::chunk { background: %(primary_bg)s; border-radius: 8px; }
            """ % {
                "window_bg": window_bg,
                "title_band_bg": title_band_bg,
                "title_subtle": title_subtle,
                "shell_bg": shell_bg,
                "shell_border": shell_border,
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
                "tab_bg": tab_bg,
                "tab_hover": tab_hover,
                "tab_selected": tab_selected,
                "badge_bg": badge_bg,
                "badge_border": badge_border,
                "badge_text": badge_text,
                "eyebrow_color": eyebrow_color,
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
        ]
        for signal in tracked_signals:
            signal.connect(self.on_project_configuration_changed)

    def on_project_configuration_changed(self, *_args) -> None:
        self._mark_project_dirty()

    def collect_ffs_items(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for i in range(self.ffs_list.count()):
            item = self.ffs_list.item(i)
            items.append({
                "path": self._item_path(item),
                "enabled": item.checkState() == Qt.Checked,
            })
        return items

    def _selected_ffs_paths(self) -> list[str]:
        return [self._item_path(item) for item in self.ffs_list.selectedItems()]

    def _enabled_ffs_count(self) -> int:
        return sum(1 for item in self.collect_ffs_items() if bool(item["enabled"]))

    def _path_fingerprint(self, path: str | Path | None) -> dict[str, object]:
        resolved = Path(resolve_workspace_path(path)) if path else Path()
        exists = bool(path) and resolved.exists()
        payload: dict[str, object] = {
            "path": serialize_workspace_path(THIS_DIR, resolved) if path else "",
            "exists": exists,
        }
        if exists:
            stat = resolved.stat()
            payload["mtime_ns"] = int(stat.st_mtime_ns)
            payload["size"] = int(stat.st_size)
        return payload

    def _stage_settings_snapshot(self, stage_key: str) -> dict[str, object]:
        values = self.collect_preset_values()
        setting_keys = {
            "beam": ["smooth", "theta"],
            "extract": ["smooth", "theta", "shared_fmin", "shared_fmax"],
            "plot": [
                "smooth2", "shared_xstep", "shared_fmin", "shared_fmax", "shared_xlog",
                "gain_ymin", "gain_ymax", "gain_y_step",
                "beamwidth_ymin", "beamwidth_ymax", "beamwidth_y_step",
                "beam_eff_ymin", "beam_eff_ymax", "beam_eff_y_step",
                "grid_color", "plot_line_1", "plot_line_2", "rings", "angle", "clip",
            ],
            "vswr": [
                "shared_xstep", "shared_fmin", "shared_fmax", "shared_xlog",
                "vswr_ymin", "vswr_ymax", "vswr_ystep", "vswr_smooth",
                "grid_color", "plot_line_1", "plot_line_2",
            ],
        }
        return {key: values[key] for key in setting_keys.get(stage_key, []) if key in values}

    def _current_stage_snapshot(self, stage_key: str) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "schema_version": CURRENT_PROJECT_SCHEMA_VERSION,
            "settings": self._stage_settings_snapshot(stage_key),
        }
        if stage_key in {"beam", "extract", "plot"}:
            snapshot["ffs_items"] = [
                {
                    "path": serialize_workspace_path(THIS_DIR, str(item["path"])),
                    "enabled": bool(item["enabled"]),
                    "file": self._path_fingerprint(str(item["path"])),
                }
                for item in self.collect_ffs_items()
            ]
        if stage_key in {"extract", "vswr"}:
            snapshot["touchstone"] = self._path_fingerprint(self.selected_s2p())
        if stage_key in {"extract", "plot"}:
            snapshot["beam_workbook"] = self._path_fingerprint(self.deduced_beam_output())
        return snapshot

    def _stage_output_files(self, stage_key: str) -> list[Path]:
        if stage_key == "beam":
            return [self.deduced_beam_output()]
        if stage_key == "extract":
            return [self.deduced_extract_output()]
        if stage_key == "vswr":
            return [self.deduced_vswr_output()]
        if stage_key == "plot":
            stem = self.deduced_beam_output().stem
            out_dir = self.project_results_dir()
            return [
                out_dir / f"{stem}_gain.svg",
                out_dir / f"{stem}_beamwidth.svg",
                out_dir / f"{stem}_beam_efficiency.svg",
            ]
        return []

    def _stage_output_target(self, stage_key: str) -> Path:
        if stage_key == "plot":
            return self.project_results_dir()
        files = self._stage_output_files(stage_key)
        return files[0] if files else self.project_results_dir()

    def _stage_output_exists(self, stage_key: str) -> bool:
        files = self._stage_output_files(stage_key)
        if not files:
            return False
        return all(path.exists() for path in files)

    def _ensure_run_state(self) -> None:
        if not isinstance(self.project_run_state, dict):
            self.project_run_state = {}
        stages = self.project_run_state.get("stages")
        if not isinstance(stages, dict):
            stages = {}
            self.project_run_state["stages"] = stages
        history = self.project_run_state.get("history")
        if not isinstance(history, list):
            self.project_run_state["history"] = []

    def _stage_state(self, stage_key: str) -> dict[str, object]:
        self._ensure_run_state()
        stages = self.project_run_state["stages"]
        stage_state = stages.get(stage_key)
        if not isinstance(stage_state, dict):
            stage_state = {}
            stages[stage_key] = stage_state
        return stage_state

    def _append_history(self, action: str, stage_key: str = "", **extra: object) -> None:
        self._ensure_run_state()
        history = self.project_run_state["history"]
        if not isinstance(history, list):
            history = []
            self.project_run_state["history"] = history
        entry: dict[str, object] = {"action": action, "at": utc_now_iso()}
        if stage_key:
            entry["stage"] = stage_key
        entry.update(extra)
        history.insert(0, entry)
        del history[20:]

    def _stage_is_applicable(self, stage_key: str) -> bool:
        enabled_ffs = bool(self.selected_ffs())
        has_touchstone = bool(self.selected_s2p())
        if stage_key == "beam":
            return enabled_ffs
        if stage_key == "extract":
            return enabled_ffs or has_touchstone
        if stage_key == "plot":
            return enabled_ffs
        if stage_key == "vswr":
            return has_touchstone
        return False

    def _stage_is_stale(self, stage_key: str) -> bool:
        if not self._stage_output_exists(stage_key):
            return False
        stage_state = self._stage_state(stage_key)
        snapshot = stage_state.get("snapshot")
        if not snapshot:
            return True
        return snapshot != self._current_stage_snapshot(stage_key)

    def _stale_stage_keys(self) -> list[str]:
        return [
            stage_key
            for stage_key, _label in STAGE_DEFINITIONS
            if self._stage_is_applicable(stage_key) and self._stage_is_stale(stage_key)
        ]

    def _preset_matches_selected(self) -> bool:
        name = self.project_active_preset or self.current_preset_name()
        if not name:
            return False
        preset = self.project_presets.get(name)
        return isinstance(preset, dict) and preset == self.collect_preset_values()

    def _validation_messages(self) -> list[str]:
        if not self.active_project_slug:
            return ["Select or create a project to begin."]
        messages: list[str] = []
        items = self.collect_ffs_items()
        paths = [str(item["path"]) for item in items]
        enabled_paths = [str(item["path"]) for item in items if bool(item["enabled"])]
        duplicates = sorted({path for path in paths if paths.count(path) > 1})
        missing_ffs = [path for path in paths if path and not Path(path).exists()]
        if not items:
            messages.append("Add at least one far-field file for workbook and plot stages.")
        elif not enabled_paths:
            messages.append("All far-field files are disabled. Enable at least one to run workbook or plots.")
        if duplicates:
            messages.append(f"Duplicate far-field entries: {', '.join(display_workspace_path(path) for path in duplicates[:3])}")
        if missing_ffs:
            sample = ", ".join(display_workspace_path(path) for path in missing_ffs[:3])
            more = " ..." if len(missing_ffs) > 3 else ""
            messages.append(f"Missing far-field files: {sample}{more}")
        s2p = self.selected_s2p()
        if s2p and not Path(s2p).exists():
            messages.append(f"Selected Touchstone file is missing: {display_workspace_path(s2p)}")
        elif not s2p:
            messages.append("VSWR stage is unavailable until a Touchstone file is selected.")
        fmin = float(self.shared_fmin.value())
        fmax = float(self.shared_fmax.value())
        if fmin > 0 and fmax <= fmin:
            messages.append("Shared frequency window is invalid: max must be greater than min.")
        return messages

    def _last_success_timestamp(self) -> str:
        stamps = [
            str(self._stage_state(stage_key).get("last_success_at", "")).strip()
            for stage_key, _label in STAGE_DEFINITIONS
        ]
        stamps = [stamp for stamp in stamps if stamp]
        return max(stamps) if stamps else ""

    def _recent_activity_text(self) -> str:
        self._ensure_run_state()
        history = self.project_run_state.get("history", [])
        if not isinstance(history, list) or not history:
            return "No stage history yet."
        lines: list[str] = []
        for entry in history[:3]:
            if not isinstance(entry, dict):
                continue
            stage_key = str(entry.get("stage", "")).strip()
            action = str(entry.get("action", "activity")).replace("_", " ")
            stage_label = STAGE_LABELS.get(stage_key, stage_key.title()) if stage_key else "Project"
            lines.append(f"{format_timestamp(str(entry.get('at', '')))}: {stage_label} {action}")
        return "\n".join(lines) if lines else "No stage history yet."

    def _refresh_stage_labels(self) -> None:
        for stage_key, stage_label in STAGE_DEFINITIONS:
            stage_state = self._stage_state(stage_key)
            status = str(stage_state.get("status", "")).strip().lower()
            last_finished = str(stage_state.get("last_finished_at", "")).strip()
            last_success = str(stage_state.get("last_success_at", "")).strip()
            button = self.stage_open_buttons[stage_key]
            button.setEnabled(bool(self.active_project_slug) and self._stage_output_exists(stage_key))
            if not self.active_project_slug:
                text = f"{stage_label}: no project"
            elif stage_key == self._current_stage_key:
                text = f"{stage_label}: running"
            elif stage_key in self._pending_stage_keys:
                text = f"{stage_label}: queued"
            elif not self._stage_is_applicable(stage_key):
                text = f"{stage_label}: not configured"
            elif status in {"failed", "cancelled"} and (not last_success or last_finished >= last_success):
                text = f"{stage_label}: {status}"
            elif self._stage_is_stale(stage_key):
                text = f"{stage_label}: stale"
            elif self._stage_output_exists(stage_key):
                stamp = format_timestamp(str(stage_state.get("last_success_at", "")))
                text = f"{stage_label}: ready ({stamp})"
            elif status == "failed":
                text = f"{stage_label}: failed"
            elif status == "cancelled":
                text = f"{stage_label}: cancelled"
            else:
                text = f"{stage_label}: waiting"
            self.stage_status_labels[stage_key].setText(text)

    def _refresh_project_summary(self) -> None:
        has_project = bool(self.active_project_slug)
        messages = self._validation_messages()
        stale_stages = self._stale_stage_keys() if has_project else []
        total_ffs = len(self.collect_ffs_items()) if has_project else 0
        enabled_ffs = self._enabled_ffs_count() if has_project else 0
        disabled_ffs = max(0, total_ffs - enabled_ffs)
        if not has_project:
            self.project_health.setText("Create a project to keep inputs, presets, settings, and outputs together.")
            self.validation_label.setText(messages[0])
            self.project_stats_label.setText("No project stats yet.")
            self.artifact_summary_label.setText("Artifacts will appear here after the first run.")
            self.last_run_label.setText("Last successful run: never")
            self.run_state_label.setText("No stage history yet.")
            self.run_summary.setText("No run summary yet.")
            self._refresh_stage_labels()
            return

        artifact_bits: list[str] = []
        for stage_key, stage_label in STAGE_DEFINITIONS:
            if not self._stage_is_applicable(stage_key):
                artifact_bits.append(f"{stage_label}: off")
            elif self._stage_is_stale(stage_key):
                artifact_bits.append(f"{stage_label}: stale")
            elif self._stage_output_exists(stage_key):
                artifact_bits.append(f"{stage_label}: ready")
            else:
                artifact_bits.append(f"{stage_label}: missing")
        project_dir = self.project_results_dir()
        file_count = sum(1 for path in project_dir.rglob("*") if path.is_file()) if project_dir.exists() else 0
        self.project_stats_label.setText(
            f"Schema v{self._loaded_project_schema_version}->{CURRENT_PROJECT_SCHEMA_VERSION} | "
            f"{enabled_ffs} enabled / {total_ffs} far-field files"
            + (f" | {disabled_ffs} disabled" if disabled_ffs else "")
            + f" | {file_count} file(s) in project folder"
        )
        self.artifact_summary_label.setText(" | ".join(artifact_bits))
        unsaved_changes = self.has_unsaved_project_changes()
        if unsaved_changes:
            self.project_health.setText("Unsaved project or preset changes are pending.")
            self.run_summary.setText("Current edits are not saved yet.")
        blocking_messages = [msg for msg in messages if not msg.startswith("VSWR stage is unavailable")]
        if not unsaved_changes and blocking_messages:
            self.validation_label.setText("\n".join(messages))
            self.project_health.setText(f"Validation needs attention. {len(blocking_messages)} item(s) flagged.")
        elif not unsaved_changes and messages:
            self.validation_label.setText("\n".join(messages))
            self.project_health.setText("Core inputs are valid. Add a Touchstone file when you need VSWR output.")
        elif not unsaved_changes and stale_stages:
            labels = ", ".join(STAGE_LABELS[key] for key in stale_stages)
            self.validation_label.setText(f"Outputs are stale for: {labels}")
            self.project_health.setText(f"Project changed since the last successful run: {labels}.")
        elif not unsaved_changes:
            self.validation_label.setText("No validation issues.")
            self.project_health.setText("Inputs, presets, and generated outputs are in sync.")
        elif messages:
            self.validation_label.setText("\n".join(messages))
        else:
            self.validation_label.setText("Save or discard the current edits before leaving.")
        last_success = self._last_success_timestamp()
        self.last_run_label.setText(f"Last successful run: {format_timestamp(last_success)}" if last_success else "Last successful run: never")
        self.run_state_label.setText(self._recent_activity_text())
        if unsaved_changes and not self._current_stage_key:
            pass
        elif self._current_stage_key:
            queued = len(self._pending_stage_keys)
            self.run_summary.setText(
                f"Running {STAGE_LABELS.get(self._current_stage_key, self._current_stage_key.title())}"
                + (f" | {queued} stage(s) queued" if queued else "")
            )
        else:
            latest_failed = next(
                (
                    stage_key
                    for stage_key, _label in STAGE_DEFINITIONS
                    if (
                        str(self._stage_state(stage_key).get("status", "")).strip().lower() == "failed"
                        and (
                            not str(self._stage_state(stage_key).get("last_success_at", "")).strip()
                            or str(self._stage_state(stage_key).get("last_finished_at", "")).strip()
                            >= str(self._stage_state(stage_key).get("last_success_at", "")).strip()
                        )
                    )
                ),
                "",
            )
            if latest_failed:
                self.run_summary.setText(f"Last run failed in {STAGE_LABELS.get(latest_failed, latest_failed.title())}.")
            elif stale_stages:
                self.run_summary.setText(
                    "Outputs need rerun: " + ", ".join(STAGE_LABELS[key] for key in stale_stages)
                )
            elif any(self._stage_is_applicable(stage_key) and self._stage_output_exists(stage_key) for stage_key, _label in STAGE_DEFINITIONS):
                self.run_summary.setText("Outputs are up to date.")
            else:
                self.run_summary.setText("No completed run yet.")
        self._refresh_stage_labels()

    def selected_ffs(self) -> list[str]:
        return [str(item["path"]) for item in self.collect_ffs_items() if bool(item["enabled"])]

    def selected_s2p(self) -> str:
        value = self.s2p_field.text().strip()
        return str(resolve_workspace_path(value)) if value else ""

    def current_project(self) -> ProjectRecord | None:
        if not self.active_project_slug:
            return None
        return ProjectRecord(
            name=self.active_project_name or self.active_project_slug,
            slug=self.active_project_slug,
            schema_version=CURRENT_PROJECT_SCHEMA_VERSION,
            ffs_items=[
                {
                    "path": serialize_workspace_path(THIS_DIR, str(item["path"])),
                    "enabled": bool(item["enabled"]),
                }
                for item in self.collect_ffs_items()
            ],
            touchstone_file=serialize_workspace_path(THIS_DIR, self.selected_s2p()),
            settings=self.collect_preset_values(),
            presets=self.project_presets,
            active_preset=self.project_active_preset,
            run_state=clean_run_state(dict(self.project_run_state)),
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
            self.project_meta.setText(f"Folder: {display_workspace_path(self.project_results_dir())}")
            self.project_badge.setText(f"Project: {project_label}")
            self.workbook_field.setText(display_workspace_path(self.deduced_beam_output()))
            self.extract_field.setText(display_workspace_path(self.deduced_extract_output()))
            self.results_field.setText(display_workspace_path(self.project_results_dir()))
            self.vswr_field.setText(display_workspace_path(self.deduced_vswr_output()))
        else:
            self.project_name.setText("No project selected")
            self.project_meta.setText("Create a project to keep inputs, presets, and generated results together.")
            self.project_badge.setText("Project: none")
            self.workbook_field.clear()
            self.extract_field.clear()
            self.results_field.clear()
            self.vswr_field.clear()
        total_ffs = len(self.collect_ffs_items()) if self.active_project_slug else 0
        enabled_ffs = len(self.selected_ffs()) if self.active_project_slug else 0
        self.count_badge.setText(f"{enabled_ffs}/{total_ffs} far-field enabled" if total_ffs else "0 far-field files")
        if self.active_project_slug:
            suffix = " *" if self.has_unsaved_project_changes() else ""
            self.project_badge.setText(f"Project: {(self.active_project_name or self.active_project_slug)}{suffix}")
        self.open_s2p_button.setEnabled(bool(self.active_project_slug and self.selected_s2p()))
        self._update_ffs_action_state()
        self._refresh_project_summary()
        self._update_project_action_state()

    def _update_project_action_state(self) -> None:
        has_project = bool(self.active_project_slug)
        is_running = bool(self.proc.running_cmd or self.proc.queue)
        is_dirty = self.has_unsaved_project_changes()
        self.project_save_button.setEnabled(has_project and is_dirty)
        self.project_edit_button.setEnabled(has_project)
        self.project_duplicate_button.setEnabled(has_project)
        self.project_delete_button.setEnabled(has_project)
        self.project_export_button.setEnabled(has_project)
        self.project_import_button.setEnabled(True)
        for widget in (
            self.btn_full,
            self.btn_beam,
            self.btn_extract,
            self.btn_plot,
            self.btn_vswr,
            self.ffs_list,
            self.s2p_field,
            self.add_ffs_button,
            self.remove_ffs_button,
            self.clear_ffs_button,
            self.select_s2p_button,
            self.clear_s2p_button,
            self.open_s2p_button,
            self.project_folder_button,
        ):
            widget.setEnabled(has_project)
        self.btn_cancel.setEnabled(has_project and is_running)
        self._update_preset_action_state()

    def _update_preset_action_state(self) -> None:
        if not hasattr(self, "preset_combo"):
            return
        has_project = bool(self.active_project_slug)
        has_preset = bool(self.current_preset_name())
        self.preset_combo.setEnabled(has_project)
        self.preset_new_button.setEnabled(has_project)
        self.preset_save_button.setEnabled(has_project)
        self.preset_rename_button.setEnabled(has_project and has_preset)
        self.preset_delete_button.setEnabled(has_project and has_preset)
        self.preset_import_button.setEnabled(has_project)
        self.preset_export_button.setEnabled(has_project and bool(self.project_presets))
        preset_label = self.project_active_preset or ("Manual" if has_project else "none")
        self.preset_badge.setText(f"Preset: {preset_label}")
        if not has_project:
            self.preset_state_label.setText("Choose a preset or keep working manually.")
        elif not has_preset:
            self.preset_state_label.setText("Manual settings only. Save them as a preset if you want to reuse them.")
        elif self._preset_matches_selected():
            self.preset_state_label.setText(f"Preset '{self.project_active_preset}' matches the current controls.")
        else:
            self.preset_state_label.setText(
                f"Current controls differ from preset '{self.project_active_preset}'. Save to update it or create a new preset."
            )

    def refresh_project_list(self, select_slug: str = "") -> None:
        projects = self.project_store.list_projects()
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItem("Select a project", "")
        for project in projects:
            self.project_combo.addItem(project.name, project.slug)
        index = self.project_combo.findData(select_slug)
        if index < 0 and projects:
            index = 1 if select_slug else 0
        self.project_combo.setCurrentIndex(max(0, index))
        self.project_combo.blockSignals(False)
        self.on_project_selected(self.project_combo.currentIndex())

    def on_project_selected(self, _index: int) -> None:
        if self._reverting_project_selection:
            return
        slug = str(self.project_combo.currentData() or "")
        if slug != self.active_project_slug and not self._confirm_pending_project_changes("switching projects"):
            self._reverting_project_selection = True
            self.project_combo.blockSignals(True)
            restore_index = self.project_combo.findData(self.active_project_slug)
            self.project_combo.setCurrentIndex(restore_index if restore_index >= 0 else 0)
            self.project_combo.blockSignals(False)
            self._reverting_project_selection = False
            return
        if not slug:
            self.active_project_slug = ""
            self.active_project_name = ""
            self.project_presets = {}
            self.project_active_preset = ""
            self.project_run_state = {}
            self._saved_project_signature = ""
            self._loaded_project_schema_version = CURRENT_PROJECT_SCHEMA_VERSION
            self._pending_stage_keys = []
            self._current_stage_key = ""
            self._loading_project = True
            self.ffs_list.clear()
            self.s2p_field.clear()
            self._loading_project = False
            self.store.set("active_project", "")
            self.refresh_preset_list()
            self.refresh_derived_paths()
            return
        project = self.project_store.load_project(slug)
        self._apply_project(project)

    def _apply_project(self, project: ProjectRecord) -> None:
        self._loading_project = True
        self.active_project_slug = project.slug
        self.active_project_name = project.name
        self.project_run_state = dict(project.run_state)
        self._loaded_project_schema_version = int(project.schema_version or 1)
        self._pending_stage_keys = []
        self._current_stage_key = ""
        self.store.set("active_project", project.slug)
        self.ffs_list.clear()
        self._add_ffs_files(project.ffs_items or [{"path": path, "enabled": True} for path in project.ffs_files], save=False)
        touchstone = resolve_project_path(THIS_DIR, project.touchstone_file)
        if not touchstone and project.name:
            guessed = guess_touchstone_path(project.name, self.selected_ffs())
            touchstone = guessed
        self.s2p_field.setText(display_workspace_path(touchstone))
        self.project_presets = normalize_preset_payload(project.presets)
        self.project_active_preset = project.active_preset if project.active_preset in self.project_presets else ""
        if not self.project_presets:
            legacy_presets = normalize_preset_payload(self.store.get("ui_presets", {}))
            legacy_active = str(self.store.get("active_preset", "")).strip()
            if legacy_presets:
                self.project_presets = legacy_presets
                self.project_active_preset = legacy_active if legacy_active in legacy_presets else ""
        self.refresh_preset_list(select_name=self.project_active_preset)
        self.apply_preset_values(project.settings)
        self.store.set("beam_ffs", self.selected_ffs())
        self.store.set("vswr_s2p", touchstone)
        self._loading_project = False
        self._capture_saved_project_signature(self.current_project())
        if self._loaded_project_schema_version < CURRENT_PROJECT_SCHEMA_VERSION:
            self.save_active_project()
        elif not project.presets and self.project_presets:
            self.save_active_project()
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
        self._loaded_project_schema_version = CURRENT_PROJECT_SCHEMA_VERSION
        self._capture_saved_project_signature(project)
        self.store.set("active_project", project.slug)
        self.store.set("beam_ffs", self.selected_ffs())
        self.store.set("vswr_s2p", self.selected_s2p())
        self.refresh_derived_paths()

    def create_project(self) -> None:
        seed_ffs = [str(item["path"]) for item in self.collect_ffs_items()]
        suggested_name = deduce_project_name(seed_ffs or [self.selected_s2p()]) if (seed_ffs or self.selected_s2p()) else "New project"
        dialog = ProjectDialog(self, name=suggested_name, ffs_files=seed_ffs, touchstone_file=self.selected_s2p())
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
            ffs_items=[{"path": serialize_workspace_path(THIS_DIR, path), "enabled": True} for path in dialog.ffs_files()],
            touchstone_file=serialize_workspace_path(THIS_DIR, touchstone),
            settings=self.collect_preset_values(),
            presets={},
            active_preset="",
            run_state={},
        )
        project.record_activity("created")
        self.project_store.save_project(project)
        self.refresh_project_list(select_slug=project.slug)

    def edit_project(self) -> None:
        if not self.active_project_slug:
            QMessageBox.information(self, "No Project Selected", "Select a project to edit.")
            return
        dialog = ProjectDialog(
            self,
            name=self.active_project_name,
            ffs_files=[str(item["path"]) for item in self.collect_ffs_items()],
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
        enabled_map = {
            str(item["path"]): bool(item["enabled"])
            for item in self.collect_ffs_items()
        }
        project = ProjectRecord(
            name=name,
            slug=new_slug,
            ffs_items=[
                {
                    "path": serialize_workspace_path(THIS_DIR, path),
                    "enabled": enabled_map.get(str(resolve_workspace_path(path)), True),
                }
                for path in dialog.ffs_files()
            ],
            touchstone_file=serialize_workspace_path(THIS_DIR, touchstone),
            settings=self.collect_preset_values(),
            presets=self.project_presets,
            active_preset=self.project_active_preset,
            run_state=self.project_run_state,
        )
        project.record_activity("edited")
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

    def duplicate_project(self) -> None:
        if not self.active_project_slug:
            QMessageBox.information(self, "No Project Selected", "Select a project to duplicate.")
            return
        suggested = f"{self.active_project_name or self.active_project_slug} copy"
        name, ok = QInputDialog.getText(self, "Duplicate Project", "New project name:", text=suggested)
        name = name.strip()
        if not ok or not name:
            return
        duplicate = self.project_store.duplicate_project(self.active_project_slug, name)
        QMessageBox.information(self, "Project Duplicated", f"Created '{duplicate.name}'.")
        self.refresh_project_list(select_slug=duplicate.slug)

    def export_project_bundle(self) -> None:
        if not self.active_project_slug:
            QMessageBox.information(self, "No Project Selected", "Select a project to export.")
            return
        suggested = str((self.project_store.projects_dir / f"{self.active_project_slug}_bundle.zip").resolve())
        path, _ = QFileDialog.getSaveFileName(self, "Export Project Bundle", suggested, "ZIP (*.zip)")
        if not path:
            return
        bundle_path = Path(path)
        if bundle_path.suffix.lower() != ".zip":
            bundle_path = bundle_path.with_suffix(".zip")
        self.project_store.export_project_bundle(self.active_project_slug, bundle_path)
        QMessageBox.information(self, "Bundle Exported", f"Project bundle written to:\n{bundle_path}")

    def import_project_bundle(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Project Bundle", str(self.project_store.projects_dir), "ZIP (*.zip)")
        if not path:
            return
        try:
            project = self.project_store.import_project_bundle(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "Import Failed", f"Could not import bundle:\n{exc}")
            return
        QMessageBox.information(self, "Bundle Imported", f"Imported project '{project.name}'.")
        self.refresh_project_list(select_slug=project.slug)

    def _set_touchstone(self, path: str) -> None:
        resolved = str(resolve_workspace_path(path)) if path else ""
        self.s2p_field.setText(display_workspace_path(resolved))
        self.store.set("vswr_s2p", resolved)
        self._mark_project_dirty()

    def preset_names(self) -> list[str]:
        return sorted(str(name) for name in self.project_presets.keys())

    def current_preset_name(self) -> str:
        if not hasattr(self, "preset_combo"):
            return ""
        name = self.preset_combo.currentData()
        return str(name or "")

    def refresh_preset_list(self, select_name: str = "") -> None:
        if not hasattr(self, "preset_combo"):
            return
        if not select_name:
            select_name = self.project_active_preset
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("No preset", "")
        for name in self.preset_names():
            self.preset_combo.addItem(name, name)
        index = max(0, self.preset_combo.findData(select_name))
        self.preset_combo.setCurrentIndex(index)
        self.preset_combo.blockSignals(False)
        self._update_preset_action_state()

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

    def on_preset_selected(self, _text: str) -> None:
        name = self.current_preset_name()
        self.project_active_preset = name
        self._update_preset_action_state()
        if not name:
            self._mark_project_dirty()
            return
        values = self.project_presets.get(name, {})
        if isinstance(values, dict):
            self.apply_preset_values(values)
        self._mark_project_dirty()

    def create_preset(self) -> None:
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        suggested = suggest_preset_name(self.preset_names(), self.active_project_name or "Preset")
        name, ok = QInputDialog.getText(self, "Create Preset", "Preset name:", text=suggested)
        name = name.strip()
        if not ok or not name:
            return
        if name in self.project_presets:
            QMessageBox.information(self, "Preset Exists", f"A preset named '{name}' already exists.")
            return
        self.project_presets[name] = self.collect_preset_values()
        self.project_active_preset = name
        self._mark_project_dirty()
        self.refresh_preset_list(select_name=name)

    def save_preset(self) -> None:
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        name = self.current_preset_name()
        if not name:
            self.create_preset()
            return
        self.project_presets[name] = self.collect_preset_values()
        self.project_active_preset = name
        self._mark_project_dirty()
        self.refresh_preset_list(select_name=name)

    def rename_preset(self) -> None:
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        name = self.current_preset_name()
        if not name:
            QMessageBox.information(self, "No Preset Selected", "Select a preset to rename.")
            return
        new_name, ok = QInputDialog.getText(self, "Rename Preset", "New preset name:", text=name)
        new_name = new_name.strip()
        if not ok or not new_name or new_name == name:
            return
        if new_name in self.project_presets:
            QMessageBox.information(self, "Preset Exists", f"A preset named '{new_name}' already exists.")
            return
        self.project_presets[new_name] = self.project_presets.pop(name)
        self.project_active_preset = new_name
        self._mark_project_dirty()
        self.refresh_preset_list(select_name=new_name)

    def delete_preset(self) -> None:
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        name = self.current_preset_name()
        if not name:
            QMessageBox.information(self, "No Preset Selected", "Select a preset to delete.")
            return
        if QMessageBox.question(self, "Delete Preset", f"Delete preset '{name}'?") != QMessageBox.Yes:
            return
        self.project_presets.pop(name, None)
        self.project_active_preset = ""
        self._mark_project_dirty()
        self.refresh_preset_list(select_name="")

    def import_presets(self) -> None:
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
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
        self.project_presets.update(imported)
        self._mark_project_dirty()
        self.refresh_preset_list(select_name=self.current_preset_name())
        QMessageBox.information(self, "Presets Imported", f"Imported {len(imported)} preset(s).")

    def export_presets(self) -> None:
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        if not self.project_presets:
            QMessageBox.information(self, "No Presets", "There are no presets to export.")
            return
        suggested = str((self.project_results_dir() / "antenna_toolkit_presets.json").resolve())
        path, _ = QFileDialog.getSaveFileName(self, "Export Presets", suggested, "JSON (*.json)")
        if not path:
            return
        out_path = Path(path)
        if out_path.suffix.lower() != ".json":
            out_path = out_path.with_suffix(".json")
        out_path.write_text(json.dumps({"presets": self.project_presets}, indent=2), encoding="utf-8")
        QMessageBox.information(self, "Presets Exported", f"Exported {len(self.project_presets)} preset(s) to:\n{out_path}")

    def _item_path(self, item: QListWidgetItem) -> str:
        return item.data(Qt.UserRole) or str(resolve_workspace_path(item.text()))

    def _refresh_ffs_item_display(self, item: QListWidgetItem) -> None:
        path = self._item_path(item)
        enabled = item.checkState() == Qt.Checked
        suffixes: list[str] = []
        if not enabled:
            suffixes.append("disabled")
        if path and not Path(path).exists():
            suffixes.append("missing")
        label = display_workspace_path(path)
        if suffixes:
            label += " [" + ", ".join(suffixes) + "]"
        previous = self._suppress_ffs_item_change
        self._suppress_ffs_item_change = True
        item.setText(label)
        item.setToolTip(path)
        self._suppress_ffs_item_change = previous

    def _make_ffs_item(self, path: str, enabled: bool = True) -> QListWidgetItem:
        actual = str(resolve_workspace_path(path))
        item = QListWidgetItem()
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        item.setData(Qt.UserRole, actual)
        item.setCheckState(Qt.Checked if enabled else Qt.Unchecked)
        self._refresh_ffs_item_display(item)
        return item

    def _replace_ffs_items(self, items: list[dict[str, object]], selected_paths: list[str] | None = None, save: bool = True) -> None:
        selected = set(selected_paths or [])
        self._suppress_ffs_item_change = True
        self.ffs_list.clear()
        for entry in items:
            path = str(entry.get("path", "")).strip()
            if not path:
                continue
            item = self._make_ffs_item(path, bool(entry.get("enabled", True)))
            self.ffs_list.addItem(item)
            if path in selected:
                item.setSelected(True)
        self._suppress_ffs_item_change = False
        self._update_ffs_action_state()
        if save:
            self.store.set("beam_ffs", self.selected_ffs())
            self._mark_project_dirty()

    def on_ffs_item_changed(self, item: QListWidgetItem) -> None:
        if self._loading_project or self._suppress_ffs_item_change:
            return
        self._refresh_ffs_item_display(item)
        self.store.set("beam_ffs", self.selected_ffs())
        self._mark_project_dirty()

    def _update_ffs_action_state(self) -> None:
        has_project = bool(self.active_project_slug)
        selected = bool(self.ffs_list.selectedItems())
        count = self.ffs_list.count()
        self.remove_ffs_button.setEnabled(has_project and selected)
        self.clear_ffs_button.setEnabled(has_project and count > 0)
        self.ffs_up_button.setEnabled(has_project and selected)
        self.ffs_down_button.setEnabled(has_project and selected)
        self.ffs_sort_button.setEnabled(has_project and count > 1)
        self.ffs_toggle_button.setEnabled(has_project and selected)
        self.ffs_missing_button.setEnabled(has_project and count > 0)

    def _add_ffs_files(self, files: list[object], save: bool = True):
        existing = {self._item_path(self.ffs_list.item(i)) for i in range(self.ffs_list.count())}
        added = False
        self._suppress_ffs_item_change = True
        for raw in files:
            if isinstance(raw, dict):
                path = str(raw.get("path", "")).strip()
                enabled = bool(raw.get("enabled", True))
            else:
                path = str(raw).strip()
                enabled = True
            actual = str(resolve_workspace_path(path))
            if actual.lower().endswith(".ffs") and actual not in existing:
                item = self._make_ffs_item(actual, enabled)
                self.ffs_list.addItem(item)
                existing.add(actual)
                added = True
        self._suppress_ffs_item_change = False
        self._update_ffs_action_state()
        if save:
            self.store.set("beam_ffs", self.selected_ffs())
            self._mark_project_dirty()
        elif added:
            self.refresh_derived_paths()

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
        self._mark_project_dirty()

    def clear_ffs(self):
        self.ffs_list.clear()
        self.store.set("beam_ffs", [])
        self._mark_project_dirty()

    def move_ffs_up(self) -> None:
        selected = set(self._selected_ffs_paths())
        if not selected:
            return
        items = self.collect_ffs_items()
        for index in range(1, len(items)):
            current = str(items[index]["path"])
            previous = str(items[index - 1]["path"])
            if current in selected and previous not in selected:
                items[index - 1], items[index] = items[index], items[index - 1]
        self._replace_ffs_items(items, selected_paths=list(selected))

    def move_ffs_down(self) -> None:
        selected = set(self._selected_ffs_paths())
        if not selected:
            return
        items = self.collect_ffs_items()
        for index in range(len(items) - 2, -1, -1):
            current = str(items[index]["path"])
            following = str(items[index + 1]["path"])
            if current in selected and following not in selected:
                items[index], items[index + 1] = items[index + 1], items[index]
        self._replace_ffs_items(items, selected_paths=list(selected))

    def sort_ffs(self) -> None:
        items = sorted(
            self.collect_ffs_items(),
            key=lambda entry: display_workspace_path(str(entry["path"])).lower(),
        )
        self._replace_ffs_items(items, selected_paths=self._selected_ffs_paths())

    def toggle_selected_ffs_enabled(self) -> None:
        selected = set(self._selected_ffs_paths())
        if not selected:
            return
        items = self.collect_ffs_items()
        enable_selected = any(not bool(entry["enabled"]) for entry in items if str(entry["path"]) in selected)
        for entry in items:
            if str(entry["path"]) in selected:
                entry["enabled"] = enable_selected
        self._replace_ffs_items(items, selected_paths=list(selected))

    def remove_missing_ffs(self) -> None:
        items = [entry for entry in self.collect_ffs_items() if Path(str(entry["path"])).exists()]
        self._replace_ffs_items(items)

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

    def _frequency_window_is_valid(self) -> bool:
        fmin = float(self.shared_fmin.value())
        fmax = float(self.shared_fmax.value())
        return fmin <= 0 or fmax > fmin

    def _missing_enabled_ffs(self) -> list[str]:
        return [path for path in self.selected_ffs() if not Path(path).exists()]

    def _detect_stage_key(self, args: list[str]) -> str:
        names = {Path(str(arg)).name.lower() for arg in args}
        mapping = {
            Path(SCRIPT_BEAM).name.lower(): "beam",
            Path(SCRIPT_EXTRACT).name.lower(): "extract",
            Path(SCRIPT_PLOT).name.lower(): "plot",
            Path(SCRIPT_VSWR).name.lower(): "vswr",
        }
        for script_name, stage_key in mapping.items():
            if script_name in names:
                return stage_key
        return ""

    def _enqueue_stage(self, stage_key: str, args: list[str]) -> None:
        self._pending_stage_keys.append(stage_key)
        self.proc.enqueue(args)
        self.refresh_derived_paths()

    def cancel_run(self) -> None:
        if not (self.proc.running_cmd or self.proc.queue):
            return
        stage_key = self._current_stage_key
        if stage_key:
            stage_state = self._stage_state(stage_key)
            stage_state["status"] = "cancelled"
            stage_state["last_finished_at"] = utc_now_iso()
            self._append_history("cancelled", stage_key, reason="user")
        self._pending_stage_keys = []
        self._current_stage_key = ""
        self._run_cancelled = True
        self.proc.stop()
        self.save_active_project()
        self.refresh_derived_paths()

    def open_stage_output(self, stage_key: str) -> None:
        target = self._stage_output_target(stage_key)
        if stage_key != "plot" and not target.exists():
            self.status("Generate that output first")
            return
        if stage_key == "plot" and not self._stage_output_exists("plot"):
            self.status("Generate the plots first")
            return
        open_in_file_manager(target)

    def on_proc_step_started(self, args: list[str], cmd: str) -> None:
        stage_key = self._pending_stage_keys.pop(0) if self._pending_stage_keys else self._detect_stage_key(args)
        self._current_stage_key = stage_key
        self._run_cancelled = False
        if not stage_key:
            self.refresh_derived_paths()
            return
        stage_state = self._stage_state(stage_key)
        stage_state["status"] = "running"
        stage_state["command"] = cmd
        stage_state["last_started_at"] = utc_now_iso()
        self.project_run_state["last_run_at"] = stage_state["last_started_at"]
        self._append_history("started", stage_key)
        self.save_active_project()
        self.refresh_derived_paths()

    def on_proc_step_finished(self, args: list[str], exit_code: int, _exit_status) -> None:
        stage_key = self._current_stage_key or self._detect_stage_key(args)
        self._current_stage_key = ""
        if not stage_key:
            self.refresh_derived_paths()
            return
        if self._run_cancelled:
            self.refresh_derived_paths()
            return
        stage_state = self._stage_state(stage_key)
        finished_at = utc_now_iso()
        stage_state["last_finished_at"] = finished_at
        stage_state["exit_code"] = int(exit_code)
        if int(exit_code) == 0:
            stage_state["status"] = "success"
            stage_state["last_success_at"] = finished_at
            stage_state["snapshot"] = self._current_stage_snapshot(stage_key)
            self.project_run_state["last_success_at"] = finished_at
            self._append_history("succeeded", stage_key)
        else:
            stage_state["status"] = "failed"
            self._append_history("failed", stage_key, exit_code=int(exit_code))
        self.save_active_project()
        self.refresh_derived_paths()

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
        self.run_info.setText("Advancing to next stage..." if self.proc.queue else "Idle")

    def _update_run_info(self):
        elapsed = int(time.time() - getattr(self, "_started_ts", time.time()))
        mm, ss = divmod(elapsed, 60)
        hh, mm = divmod(mm, 60)
        self.run_info.setText(f"Running | {getattr(self, '_line_count', 0)} lines | {hh:02d}:{mm:02d}:{ss:02d}")

    def run_beam(self):
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        missing = self._missing_enabled_ffs()
        if missing:
            self.status("Remove or fix missing far-field files before running")
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
        self._save_project_if_dirty()
        self._enqueue_stage("beam", args)

    def build_extract_args(self) -> list[str] | None:
        if not self.active_project_slug:
            return None
        if not self._frequency_window_is_valid():
            return None
        ffs = [path for path in self.selected_ffs() if Path(path).exists()]
        s2p = self.selected_s2p()
        if s2p and not Path(s2p).exists():
            s2p = ""
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
        if self.selected_ffs() and self._missing_enabled_ffs() and not (self.selected_s2p() and Path(self.selected_s2p()).exists()):
            self.status("Remove or fix missing far-field files before running")
            return
        args = self.build_extract_args()
        if not args:
            self.status("Add a valid .ffs or Touchstone input and fix the shared frequency window if needed")
            return
        self._save_project_if_dirty()
        self._enqueue_stage("extract", args)

    def run_plot(self):
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        if not self._frequency_window_is_valid():
            self.status("Set a valid shared frequency window or clear it")
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
        self._save_project_if_dirty()
        self._enqueue_stage("plot", args)

    def run_vswr(self):
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        if not self._frequency_window_is_valid():
            self.status("Set a valid shared frequency window or clear it")
            return
        s2p = self.selected_s2p()
        if not s2p:
            self.status("Select a .s1p or .s2p file")
            return
        if not Path(s2p).exists():
            self.status("Selected Touchstone file is missing")
            return
        args = [which_python(), "-u", SCRIPT_VSWR, s2p,
                "--output", str(self.deduced_vswr_output()),
                "--grid-color", self.plot_grid.color(),
                "--line-colors", ",".join([self.plot_line1.color(), self.plot_line2.color()]),
                "--x-step", str(self.shared_xstep.value()),
                "--ymin", str(self.vswr_ymin.value()),
                "--ymax", str(self.vswr_ymax.value()),
                "--y-step", str(self.vswr_ystep.value()),
                "--smooth-window", str(self.vswr_smooth.value())]
        if self.shared_xlog.isChecked():
            args.append("--x-log")
        if self.shared_fmin.value() > 0 and self.shared_fmax.value() > self.shared_fmin.value():
            args += ["--fmin", f"{self.shared_fmin.value()}", "--fmax", f"{self.shared_fmax.value()}"]
        self._save_project_if_dirty()
        self._enqueue_stage("vswr", args)

    def run_full(self):
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        if not self._frequency_window_is_valid():
            self.status("Set a valid shared frequency window or clear it")
            return
        missing = self._missing_enabled_ffs()
        if missing:
            self.status("Remove or fix missing far-field files before running")
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
        self._save_project_if_dirty()
        self._enqueue_stage("beam", args_beam)

        args_extract = self.build_extract_args()
        if args_extract:
            self._enqueue_stage("extract", args_extract)

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
        self._enqueue_stage("plot", args_plot)

        s2p = self.selected_s2p()
        if s2p and Path(s2p).exists():
            args_vswr = [which_python(), "-u", SCRIPT_VSWR, s2p,
                    "--output", str(self.deduced_vswr_output()),
                    "--grid-color", self.plot_grid.color(),
                    "--line-colors", ",".join([self.plot_line1.color(), self.plot_line2.color()]),
                    "--x-step", str(self.shared_xstep.value()),
                    "--ymin", str(self.vswr_ymin.value()),
                    "--ymax", str(self.vswr_ymax.value()),
                    "--y-step", str(self.vswr_ystep.value()),
                    "--smooth-window", str(self.vswr_smooth.value())]
            if self.shared_xlog.isChecked():
                args_vswr.append("--x-log")
            if self.shared_fmin.value() > 0 and self.shared_fmax.value() > self.shared_fmin.value():
                args_vswr += ["--fmin", f"{self.shared_fmin.value()}", "--fmax", f"{self.shared_fmax.value()}"]
            self._enqueue_stage("vswr", args_vswr)

    def _restore_geometry(self):
        width = self.store.get("window_width", None)
        height = self.store.get("window_height", None)
        try:
            width = int(width)
            height = int(height)
        except (TypeError, ValueError):
            return
        if width >= 900 and height >= 600:
            self.resize(width, height)

    def _save_geometry(self):
        try:
            self.store.set("window_width", int(self.width()))
            self.store.set("window_height", int(self.height()))
            if hasattr(self, "console_window"):
                self.console_window._save_geometry()
        except Exception:
            pass

    def closeEvent(self, e):
        if not self._confirm_pending_project_changes("exiting"):
            e.ignore()
            return
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
