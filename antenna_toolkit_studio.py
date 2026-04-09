#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QByteArray, Signal
from PySide6.QtGui import QColor, QPalette, QTextCursor, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QAbstractItemView,
    QAbstractSpinBox,
    QComboBox, QColorDialog,
    QCheckBox,
    QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QProgressBar,
    QFormLayout, QFrame, QSizePolicy, QStyleFactory, QMessageBox, QInputDialog,
    QDialog, QDialogButtonBox, QScrollArea, QGridLayout, QTabWidget, QMenu, QToolButton
)

from antenna_toolkit_qt import (
    THIS_DIR, SCRIPT_BEAM, SCRIPT_EXTRACT, SCRIPT_DATASHEET, SCRIPT_PLOT, SCRIPT_VSWR,
    suggest_preset_name, normalize_preset_payload,
    DEFAULT_GRID_COLOR, DEFAULT_LINE_COLORS, Persist, Proc, resolve_state_file,
    which_python, open_in_file_manager, resolve_workspace_path,
    display_workspace_path, deduce_project_name, normalized_project_stem,
)
from project_store import (
    CURRENT_PROJECT_SCHEMA_VERSION, ProjectRecord, ProjectStore, resolve_project_path,
    sanitize_project_slug, serialize_workspace_path, utc_now_iso,
)

APP_TITLE = "Antenna Toolkit Studio"
STATE_FILE = resolve_state_file(".nova_qt_studio_state.json", THIS_DIR / ".nova_qt_studio_state.json")
COMPACT_SCREEN_HEIGHT = 1200
COMPACT_WINDOW_WIDTH = 1360
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
    ("datasheet", "Datasheet"),
    ("plot", "Plots"),
    ("vswr", "VSWR"),
]
STAGE_LABELS = dict(STAGE_DEFINITIONS)
DATASHEET_TEMPLATE = THIS_DIR / "Datasheet.pdf"
THEME_OPTIONS = [
    ("light", "Canvas"),
    ("dark", "Midnight"),
    ("graphite", "Graphite"),
    ("sage", "Sage"),
    ("sepia", "Sepia"),
]
THEME_LABELS = {key: label for key, label in THEME_OPTIONS}
PRESET_STORE_KEY = "ui_presets"
ACTIVE_PRESET_KEY = "active_preset"
THEME_STYLES = {
    "light": {
        "palette_window": "#edf2f7",
        "palette_window_text": "#172433",
        "palette_base": "#ffffff",
        "palette_text": "#172433",
        "palette_button": "#f3f7fb",
        "palette_button_text": "#172433",
        "palette_highlight": "#d37436",
        "palette_highlight_text": "#ffffff",
        "window_bg": "#edf2f7",
        "title_band_bg": "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #142033, stop:0.55 #25516c, stop:1 #2f7a73)",
        "title_subtle": "rgba(237,244,249,0.86)",
        "shell_bg": "#f7f9fb",
        "shell_border": "#d5dde6",
        "card_bg": "#ffffff",
        "card_border": "#d5dde6",
        "title_color": "#172433",
        "text_color": "#314255",
        "input_bg": "#f7fafc",
        "input_border": "#c7d2de",
        "button_bg": "#f3f7fb",
        "button_hover": "#e8f0f7",
        "list_selected": "#d9e8f4",
        "primary_bg": "#d37436",
        "primary_hover": "#bf6226",
        "progress_bg": "rgba(29,45,60,0.10)",
        "ghost_bg": "#ebf0f5",
        "ghost_hover": "#dfe8f0",
        "step_bg": "#eef4f8",
        "step_hover": "#e1ebf2",
        "step_border": "#bdcbd8",
        "helper_color": "#5f7182",
        "tab_bg": "#e7edf3",
        "tab_hover": "#dde7ef",
        "tab_selected": "#ffffff",
        "badge_bg": "rgba(211,116,54,0.10)",
        "badge_border": "#e2b290",
        "badge_text": "#7c4929",
        "eyebrow_color": "#19706a",
    },
    "dark": {
        "palette_window": "#0f1720",
        "palette_window_text": "#f3f6f9",
        "palette_base": "#121b24",
        "palette_text": "#f3f6f9",
        "palette_button": "#202c37",
        "palette_button_text": "#f3f6f9",
        "palette_highlight": "#f19a5b",
        "palette_highlight_text": "#10161d",
        "window_bg": "#0f1720",
        "title_band_bg": "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #0c1722, stop:0.55 #17344a, stop:1 #1f5a53)",
        "title_subtle": "rgba(226,234,240,0.84)",
        "shell_bg": "#16212c",
        "shell_border": "#283848",
        "card_bg": "#1c2935",
        "card_border": "#30414f",
        "title_color": "#f3f6f9",
        "text_color": "#d9e3ea",
        "input_bg": "#121b24",
        "input_border": "#334653",
        "button_bg": "#202c37",
        "button_hover": "#2a3844",
        "list_selected": "#29414c",
        "primary_bg": "#f19a5b",
        "primary_hover": "#de8442",
        "progress_bg": "rgba(255,255,255,0.08)",
        "ghost_bg": "#1f2b35",
        "ghost_hover": "#293743",
        "step_bg": "#141d26",
        "step_hover": "#1c2731",
        "step_border": "#3a4a57",
        "helper_color": "#9fb2c2",
        "tab_bg": "#202c37",
        "tab_hover": "#253440",
        "tab_selected": "#1c2935",
        "badge_bg": "rgba(241,154,91,0.16)",
        "badge_border": "#8b5630",
        "badge_text": "#ffe0cb",
        "eyebrow_color": "#72ccb4",
    },
    "graphite": {
        "palette_window": "#171a20",
        "palette_window_text": "#f2f4f7",
        "palette_base": "#1d2128",
        "palette_text": "#f2f4f7",
        "palette_button": "#262c35",
        "palette_button_text": "#f2f4f7",
        "palette_highlight": "#75aeda",
        "palette_highlight_text": "#141920",
        "window_bg": "#171a20",
        "title_band_bg": "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #14171d, stop:0.55 #283340, stop:1 #3b4654)",
        "title_subtle": "rgba(228,232,237,0.82)",
        "shell_bg": "#1d2128",
        "shell_border": "#313845",
        "card_bg": "#222831",
        "card_border": "#3a4351",
        "title_color": "#f2f4f7",
        "text_color": "#d8dee6",
        "input_bg": "#191d24",
        "input_border": "#3b4452",
        "button_bg": "#262c35",
        "button_hover": "#303744",
        "list_selected": "#334455",
        "primary_bg": "#75aeda",
        "primary_hover": "#6199c8",
        "progress_bg": "rgba(255,255,255,0.07)",
        "ghost_bg": "#242a33",
        "ghost_hover": "#2d3440",
        "step_bg": "#191e25",
        "step_hover": "#212730",
        "step_border": "#46505f",
        "helper_color": "#a5afbb",
        "tab_bg": "#262c35",
        "tab_hover": "#303744",
        "tab_selected": "#222831",
        "badge_bg": "rgba(117,174,218,0.16)",
        "badge_border": "#53789b",
        "badge_text": "#dbefff",
        "eyebrow_color": "#87c5d4",
    },
    "sage": {
        "palette_window": "#e8f0eb",
        "palette_window_text": "#19332d",
        "palette_base": "#fcfffd",
        "palette_text": "#19332d",
        "palette_button": "#eef5f0",
        "palette_button_text": "#19332d",
        "palette_highlight": "#4b8270",
        "palette_highlight_text": "#ffffff",
        "window_bg": "#e8f0eb",
        "title_band_bg": "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #17312f, stop:0.55 #2f5b55, stop:1 #5b7a5f)",
        "title_subtle": "rgba(236,245,240,0.86)",
        "shell_bg": "#f5faf6",
        "shell_border": "#cbdace",
        "card_bg": "#fcfffd",
        "card_border": "#d2ddd4",
        "title_color": "#19332d",
        "text_color": "#3c544d",
        "input_bg": "#f1f7f3",
        "input_border": "#c7d9cd",
        "button_bg": "#eef5f0",
        "button_hover": "#e1ede5",
        "list_selected": "#d6e7db",
        "primary_bg": "#4b8270",
        "primary_hover": "#3d6e5d",
        "progress_bg": "rgba(24,48,42,0.10)",
        "ghost_bg": "#e6efe8",
        "ghost_hover": "#d9e8dc",
        "step_bg": "#eaf2ec",
        "step_hover": "#dde9e0",
        "step_border": "#b7cabd",
        "helper_color": "#657c74",
        "tab_bg": "#e3ece5",
        "tab_hover": "#d7e6db",
        "tab_selected": "#fcfffd",
        "badge_bg": "rgba(75,130,112,0.12)",
        "badge_border": "#9ebcae",
        "badge_text": "#2f5a4d",
        "eyebrow_color": "#2f7863",
    },
    "sepia": {
        "palette_window": "#f3eadc",
        "palette_window_text": "#30251a",
        "palette_base": "#fffaf1",
        "palette_text": "#30251a",
        "palette_button": "#f6efe4",
        "palette_button_text": "#30251a",
        "palette_highlight": "#a6612f",
        "palette_highlight_text": "#fff8f0",
        "window_bg": "#f3eadc",
        "title_band_bg": "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #332219, stop:0.55 #6c4931, stop:1 #8b6a48)",
        "title_subtle": "rgba(247,240,230,0.88)",
        "shell_bg": "#fbf4e9",
        "shell_border": "#d8c6ae",
        "card_bg": "#fffaf1",
        "card_border": "#dccab3",
        "title_color": "#30251a",
        "text_color": "#5b4b3d",
        "input_bg": "#f7efe2",
        "input_border": "#d4c1a9",
        "button_bg": "#f6efe4",
        "button_hover": "#eee3d3",
        "list_selected": "#efd9bd",
        "primary_bg": "#a6612f",
        "primary_hover": "#8f5225",
        "progress_bg": "rgba(60,42,26,0.10)",
        "ghost_bg": "#efe4d4",
        "ghost_hover": "#e6d7c1",
        "step_bg": "#f1e6d7",
        "step_hover": "#e8dac6",
        "step_border": "#c5ae92",
        "helper_color": "#7a6958",
        "tab_bg": "#eadfce",
        "tab_hover": "#e1d2bc",
        "tab_selected": "#fffaf1",
        "badge_bg": "rgba(166,97,47,0.12)",
        "badge_border": "#c89d76",
        "badge_text": "#7a431f",
        "eyebrow_color": "#896038",
    },
}


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
    def __init__(self, parent: QWidget, name: str = "", title: str = "Project", note_text: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(440, 180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        form = QFormLayout()
        self.name_field = QLineEdit(name)
        self.name_field.setPlaceholderText("Project name")
        form.addRow("Name", self.name_field)
        layout.addLayout(form)

        note = QLabel(
            note_text
            or "Projects are created by name. Add far-field and Touchstone inputs on the Inputs tab, then click Save project to persist them."
        )
        note.setWordWrap(True)
        note.setObjectName("helper")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def project_name(self) -> str:
        return self.name_field.text().strip()


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


class HelpWindow(QWidget):
    def __init__(self, owner: "ModernMainWindow", store: Persist):
        super().__init__(None, Qt.Window)
        self.owner = owner
        self.store = store
        self.setWindowTitle(f"{APP_TITLE} Help")
        self.resize(760, 460)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        workspace_card = Card("Workspace guide", "Flow")
        workspace_note = QLabel(
            "1. Create a project by name.\n"
            "2. Add or edit project inputs on the Inputs tab.\n"
            "3. Choose or update the project preset and tuning controls.\n"
            "4. Click Save project to persist the current inputs and preset.\n"
            "5. Run the pipeline from the Run tab."
        )
        workspace_note.setWordWrap(True)
        workspace_note.setObjectName("helper")
        workspace_card.body.addWidget(workspace_note)
        lay.addWidget(workspace_card)

        run_card = Card("When to run", "Flow")
        run_note = QLabel(
            "Run Full Pipeline when the inputs changed and you want the full deliverable.\n"
            "Use Workbook Only after changing far-field files or smoothing.\n"
            "Use Plots Only after changing chart ranges or colors.\n"
            "Use VSWR Only after changing the Touchstone file or VSWR settings."
        )
        run_note.setWordWrap(True)
        run_note.setObjectName("helper")
        run_card.body.addWidget(run_note)
        lay.addWidget(run_card)
        lay.addStretch(1)
        self._restore_geometry()

    def _restore_geometry(self):
        geo = self.store.get("help_geometry", None)
        if geo:
            try:
                ba = QByteArray.fromBase64(geo.encode("ascii"))
                self.restoreGeometry(ba)
            except Exception:
                pass

    def _save_geometry(self):
        try:
            ba = self.saveGeometry().toBase64().data().decode("ascii")
            self.store.set("help_geometry", ba)
        except Exception:
            pass

    def closeEvent(self, event):
        self._save_geometry()
        self.owner.on_help_popup_closed()
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
        self.global_presets: dict[str, dict[str, object]] = normalize_preset_payload(self.store.get(PRESET_STORE_KEY, {}))
        self.global_active_preset = str(self.store.get(ACTIVE_PRESET_KEY, "")).strip()
        if self.global_active_preset and self.global_active_preset not in self.global_presets:
            self.global_active_preset = ""
            self.store.set(ACTIVE_PRESET_KEY, "")
        self.project_active_preset = ""
        self.project_run_state: dict[str, object] = {}
        self._compact_layout = False
        self._scroll_page_layouts: list[QVBoxLayout] = []
        self.theme = str(self.store.get("theme", "light")).lower()
        if self.theme not in THEME_LABELS:
            self.theme = "light"
        initial_project_slug = str(self.store.get("active_project", "")).strip()
        self._build_ui()
        self._apply_style()
        self._reset_to_default_state(clear_persisted_project=False)
        self.refresh_project_list(select_slug=initial_project_slug)
        self._restore_geometry()
        self._update_layout_mode(force=True)
        self.store.set("theme", self.theme)

    def _build_ui(self):
        root = QWidget()
        root_lay = QVBoxLayout(root)
        self.root_lay = root_lay
        root_lay.setContentsMargins(18, 18, 18, 18)
        root_lay.setSpacing(16)

        title_band = QFrame()
        title_band.setObjectName("titleBand")
        title_lay = QHBoxLayout(title_band)
        self.title_lay = title_lay
        title_lay.setContentsMargins(22, 20, 22, 20)
        title_lay.setSpacing(16)

        brand_lay = QVBoxLayout()
        self.brand_lay = brand_lay
        brand_lay.setContentsMargins(0, 0, 0, 0)
        brand_lay.setSpacing(6)
        self.hero_title = QLabel("Antenna Toolkit Studio")
        self.hero_title.setObjectName("brandTitle")
        brand_subtitle = QLabel("Projects now keep inputs, presets, settings, and generated results together in one workspace.")
        brand_subtitle.setObjectName("brandSubtitle")
        brand_subtitle.setWordWrap(True)
        self.brand_subtitle = brand_subtitle
        brand_lay.addWidget(self.hero_title)
        brand_lay.addWidget(brand_subtitle)
        title_lay.addLayout(brand_lay, 1)

        title_tools = QHBoxLayout()
        self.title_tools = title_tools
        title_tools.setContentsMargins(0, 0, 0, 0)
        title_tools.setSpacing(10)
        self.console_toggle = QPushButton()
        self.console_toggle.setObjectName("ghostButton")
        self.console_toggle.setCheckable(True)
        self.console_toggle.clicked.connect(self.toggle_console)
        self.help_button = QPushButton()
        self.help_button.setObjectName("ghostButton")
        self.help_button.setCheckable(True)
        self.help_button.clicked.connect(self.toggle_help)
        self.theme_selector = QComboBox()
        self.theme_selector.setObjectName("themeSelector")
        for theme_key, theme_label in THEME_OPTIONS:
            self.theme_selector.addItem(theme_label, theme_key)
        self.theme_selector.currentIndexChanged.connect(self.on_theme_selected)
        self.console_toggle.setToolTip("Show or hide the separate output console window.")
        self.help_button.setToolTip("Show or hide the separate help window.")
        self.theme_selector.setToolTip("Choose a studio theme.")
        title_tools.addWidget(self.console_toggle)
        title_tools.addWidget(self.help_button)
        title_tools.addWidget(self.theme_selector)
        title_lay.addLayout(title_tools)
        root_lay.addWidget(title_band)

        command_panel = ResponsiveCardPanel(max_columns=2, min_card_width=480)
        self.command_panel = command_panel

        quick_actions = Card("Pipeline", "Run")
        self.quick_actions_card = quick_actions
        quick_actions.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        run_help = QLabel("Use Full Pipeline for the usual workflow. Manual reruns for individual stages are available from the Manual runs menu.")
        run_help.setObjectName("helper")
        run_help.setWordWrap(True)
        self.run_help_label = run_help
        quick_actions.body.addWidget(run_help)
        self.btn_full = QPushButton("Run Full Pipeline")
        self.btn_full.setObjectName("primaryButton")
        self.btn_full.clicked.connect(self.run_full)
        self.btn_cancel = QPushButton("Cancel Run")
        self.btn_cancel.setObjectName("ghostButton")
        self.btn_cancel.clicked.connect(self.cancel_run)
        self.run_more_button = QToolButton()
        self.run_more_button.setText("Manual runs")
        self.run_more_button.setPopupMode(QToolButton.InstantPopup)
        self.run_more_button.setToolTip("Run a single stage without running the full pipeline.")
        self.run_more_menu = QMenu(self.run_more_button)
        self.run_more_beam_action = self.run_more_menu.addAction("Workbook only", self.run_beam)
        self.run_more_extract_action = self.run_more_menu.addAction("Extract data", self.run_extract)
        self.run_more_datasheet_action = self.run_more_menu.addAction("Generate datasheet PDF", self.run_datasheet)
        self.run_more_plot_action = self.run_more_menu.addAction("Plots only", self.run_plot)
        self.run_more_vswr_action = self.run_more_menu.addAction("VSWR only", self.run_vswr)
        self.run_more_button.setMenu(self.run_more_menu)
        self.btn_full.setToolTip("Run workbook generation, extract generation, plot generation, datasheet generation, and VSWR generation in sequence.")
        self.btn_cancel.setToolTip("Stop the current run and clear any queued stages.")
        self.hero_actions = ResponsiveButtonPanel(max_columns=3, min_button_width=150)
        self.hero_actions.set_buttons([
            self.btn_full,
            self.btn_cancel,
            self.run_more_button,
        ])
        quick_actions.body.addWidget(self.hero_actions)
        self.run_info = QLabel("Idle")
        self.run_info.setObjectName("runInfo")
        self.run_info.setWordWrap(True)
        self.run_summary = QLabel("No run summary yet.")
        self.run_summary.setObjectName("helper")
        self.run_summary.setWordWrap(True)
        self.pipeline_details_toggle = QPushButton("Show Details")
        self.pipeline_details_toggle.setObjectName("ghostButton")
        self.pipeline_details_toggle.setCheckable(True)
        self.pipeline_details_toggle.clicked.connect(self._on_pipeline_details_toggled)
        self.project_stats_label = QLabel("No project stats yet.")
        self.project_stats_label.setObjectName("helper")
        self.project_stats_label.setWordWrap(True)
        self.artifact_summary_label = QLabel("Artifacts will appear here after the first run.")
        self.artifact_summary_label.setObjectName("helper")
        self.artifact_summary_label.setWordWrap(True)
        self.workbook_field = QLineEdit(); self.workbook_field.setReadOnly(True)
        self.extract_field = QLineEdit(); self.extract_field.setReadOnly(True)
        self.datasheet_field = QLineEdit(); self.datasheet_field.setReadOnly(True)
        self.results_field = QLineEdit(); self.results_field.setReadOnly(True)
        self.vswr_field = QLineEdit(); self.vswr_field.setReadOnly(True)
        self.workbook_field.setToolTip("Workbook stored inside the selected project directory.")
        self.extract_field.setToolTip("Extracted-data workbook stored inside the selected project directory.")
        self.datasheet_field.setToolTip("Generated datasheet PDF stored inside the selected project directory.")
        self.results_field.setToolTip("Project directory containing metadata and generated outputs.")
        self.vswr_field.setToolTip("VSWR plot stored inside the selected project directory.")
        self.busy = QProgressBar()
        self.busy.setVisible(False)
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        quick_actions.body.addWidget(self.run_info)
        quick_actions.body.addWidget(self.run_summary)
        quick_actions.body.addWidget(self.pipeline_details_toggle)
        self.pipeline_details = QWidget()
        self.pipeline_details_layout = QVBoxLayout(self.pipeline_details)
        self.pipeline_details_layout.setContentsMargins(0, 0, 0, 0)
        self.pipeline_details_layout.setSpacing(8)
        self.pipeline_details_layout.addWidget(self.project_stats_label)
        self.pipeline_details_layout.addWidget(self.artifact_summary_label)
        pipeline_outputs = QFormLayout()
        pipeline_outputs.addRow("Project folder", self._path_row(self.results_field))
        pipeline_outputs.addRow("Workbook", self._path_row(self.workbook_field))
        pipeline_outputs.addRow("Extract workbook", self._path_row(self.extract_field))
        pipeline_outputs.addRow("Datasheet PDF", self._path_row(self.datasheet_field))
        pipeline_outputs.addRow("VSWR output", self._path_row(self.vswr_field))
        self.pipeline_details_layout.addLayout(pipeline_outputs)
        quick_actions.body.addWidget(self.pipeline_details)
        quick_actions.body.addWidget(self.busy)
        self.stage_status_labels: dict[str, QLabel] = {}
        self.stage_open_buttons: dict[str, QPushButton] = {}
        project_card = Card("Project workspace", "Command center")
        self.project_card = project_card
        project_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        project_help = QLabel("Create or select a project first. Each project keeps its own inputs, selected preset, processing settings, and outputs.")
        project_help.setWordWrap(True)
        project_help.setObjectName("helper")
        self.project_help_label = project_help
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
        self.project_new_button.setToolTip("Create a new project by name. Add inputs on the Inputs tab, then save the project.")
        self.project_save_button.setToolTip("Write the current project inputs, presets, settings, and run metadata to disk.")
        self.project_more_button = QToolButton()
        self.project_more_button.setText("More")
        self.project_more_button.setPopupMode(QToolButton.InstantPopup)
        self.project_more_button.setToolTip("More project actions.")
        self.project_more_menu = QMenu(self.project_more_button)
        self.project_rename_action = self.project_more_menu.addAction("Rename project", self.edit_project)
        self.project_duplicate_action = self.project_more_menu.addAction("Duplicate project", self.duplicate_project)
        self.project_delete_action = self.project_more_menu.addAction("Delete project", self.delete_project)
        self.project_more_menu.addSeparator()
        self.project_run_menu = self.project_more_menu.addMenu("Run stage")
        self.project_run_beam_action = self.project_run_menu.addAction("Workbook only", self.run_beam)
        self.project_run_extract_action = self.project_run_menu.addAction("Extract data", self.run_extract)
        self.project_run_datasheet_action = self.project_run_menu.addAction("Generate datasheet PDF", self.run_datasheet)
        self.project_run_plot_action = self.project_run_menu.addAction("Plots only", self.run_plot)
        self.project_run_vswr_action = self.project_run_menu.addAction("VSWR only", self.run_vswr)
        self.project_more_menu.addSeparator()
        self.project_import_action = self.project_more_menu.addAction("Import bundle", self.import_project_bundle)
        self.project_export_action = self.project_more_menu.addAction("Export bundle", self.export_project_bundle)
        self.project_more_menu.addSeparator()
        self.project_open_folder_action = self.project_more_menu.addAction("Open project folder", lambda: open_in_file_manager(self.project_results_dir()))
        self.project_more_button.setMenu(self.project_more_menu)
        project_row.addWidget(self.project_combo)
        project_actions = ResponsiveButtonPanel(max_columns=3, min_button_width=130)
        self.project_actions = project_actions
        project_actions.set_buttons([
            self.project_new_button,
            self.project_save_button,
            self.project_more_button,
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
        self.count_badge = QLabel("0 far-field files")
        self.count_badge.setObjectName("summaryBadge")
        self.preset_badge = QLabel("Preset: none")
        self.preset_badge.setObjectName("summaryBadge")
        badge_grid.addWidget(self.count_badge, 0, 0)
        badge_grid.addWidget(self.preset_badge, 0, 1)
        project_card.body.addLayout(badge_grid)

        command_left = QWidget()
        command_left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        command_left_layout = QVBoxLayout(command_left)
        command_left_layout.setContentsMargins(0, 0, 0, 0)
        command_left_layout.setSpacing(0)
        command_left_layout.addWidget(project_card)

        workspace_shell = QFrame()
        workspace_shell.setObjectName("workspaceShell")
        workspace_shell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        shell_lay = QVBoxLayout(workspace_shell)
        self.shell_lay = shell_lay
        shell_lay.setContentsMargins(20, 20, 20, 20)
        shell_lay.setSpacing(14)
        readiness_card = Card("Run readiness", "Status")
        self.readiness_card = readiness_card
        readiness_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.readiness_summary = QLabel("Create a project to start tracking run readiness.")
        self.readiness_summary.setObjectName("helper")
        self.readiness_summary.setWordWrap(True)
        readiness_card.body.addWidget(self.readiness_summary)
        readiness_panel = ResponsiveCardPanel(max_columns=4, min_card_width=170)
        self.readiness_panel = readiness_panel
        readiness_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.readiness_badges: dict[str, QLabel] = {}
        readiness_tiles: list[QWidget] = []
        for key, title in (
            ("project", "Project"),
            ("inputs", "Far-field"),
            ("touchstone", "Touchstone"),
            ("outputs", "Outputs"),
        ):
            tile = QWidget()
            tile_lay = QVBoxLayout(tile)
            tile_lay.setContentsMargins(0, 0, 0, 0)
            tile_lay.setSpacing(4)
            tile_title = QLabel(title)
            tile_title.setObjectName("helper")
            tile_value = QLabel("Waiting")
            tile_value.setObjectName("summaryBadge")
            self.readiness_badges[key] = tile_value
            tile_lay.addWidget(tile_title)
            tile_lay.addWidget(tile_value)
            readiness_tiles.append(tile)
        readiness_panel.set_cards(readiness_tiles)
        readiness_card.body.addWidget(readiness_panel)
        readiness_action_row = QHBoxLayout()
        readiness_action_row.setContentsMargins(0, 0, 0, 0)
        readiness_action_row.setSpacing(10)
        self.readiness_action = QPushButton("Create project")
        self.readiness_action.setObjectName("primaryButton")
        self.readiness_action.setMinimumWidth(180)
        readiness_action_row.addWidget(self.readiness_action, 0, Qt.AlignLeft)
        readiness_action_row.addStretch(1)
        readiness_card.body.addLayout(readiness_action_row)
        self.workflow_tabs = QTabWidget()
        self.workflow_tabs.setObjectName("workflowTabs")
        self.workflow_tabs.setDocumentMode(True)
        self.workflow_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.workflow_tabs.currentChanged.connect(self.on_tab_changed)
        shell_lay.addWidget(self.workflow_tabs, 1)
        command_panel.set_cards([command_left, workspace_shell])
        root_lay.addWidget(command_panel, 1)

        run_scroll, _run_page, run_lay = self._make_scroll_page()
        inputs_scroll, _inputs_page, inputs_lay = self._make_scroll_page()
        processing_scroll, _processing_page, processing_lay = self._make_scroll_page()
        style_scroll, _style_page, style_lay = self._make_scroll_page()
        run_lay.addWidget(readiness_card)
        run_lay.addWidget(quick_actions)
        run_lay.addStretch(1)

        preset_card = Card("Saved presets", "Presets")
        self.preset_card = preset_card
        preset_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        preset_help = QLabel("Save reusable control/range/style presets for product lines. Presets do not change the currently selected input files.")
        preset_help.setWordWrap(True)
        preset_help.setObjectName("helper")
        self.preset_help_label = preset_help
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
        self.preset_new_button.setToolTip("Create a new preset from the current GUI settings. Use Save project to persist it.")
        self.preset_save_button.setToolTip("Overwrite the selected preset with the current GUI settings. Use Save project to persist it.")
        self.preset_more_button = QToolButton()
        self.preset_more_button.setText("More")
        self.preset_more_button.setPopupMode(QToolButton.InstantPopup)
        self.preset_more_button.setToolTip("More preset actions.")
        self.preset_more_menu = QMenu(self.preset_more_button)
        self.preset_rename_action = self.preset_more_menu.addAction("Rename preset", self.rename_preset)
        self.preset_delete_action = self.preset_more_menu.addAction("Delete preset", self.delete_preset)
        self.preset_more_menu.addSeparator()
        self.preset_import_action = self.preset_more_menu.addAction("Import presets", self.import_presets)
        self.preset_export_action = self.preset_more_menu.addAction("Export presets", self.export_presets)
        self.preset_more_button.setMenu(self.preset_more_menu)
        preset_actions = ResponsiveButtonPanel(max_columns=3, min_button_width=110)
        self.preset_actions = preset_actions
        preset_actions.set_buttons([self.preset_new_button, self.preset_save_button, self.preset_more_button])
        preset_card.body.addWidget(preset_actions)
        command_left_layout.addSpacing(14)
        command_left_layout.addWidget(preset_card)
        command_left_layout.addStretch(1)
        self.validation_label = QLabel("No validation issues.")
        self.validation_label.setObjectName("helper")
        self.validation_label.setWordWrap(True)
        self.last_run_label = QLabel("Last successful run: never")
        self.last_run_label.setObjectName("helper")
        self.last_run_label.setWordWrap(True)
        self.run_state_label = QLabel("No stage history yet.")
        self.run_state_label.setObjectName("helper")
        self.run_state_label.setWordWrap(True)
        ffs_card = Card("Far-field files", "Primary input")
        self.ffs_card = ffs_card
        ffs_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        helper = QLabel("Drop .ffs files here or add them manually. The changes stay local to the active project until you click Save project.")
        helper.setWordWrap(True)
        helper.setObjectName("helper")
        self.ffs_help_label = helper
        ffs_card.body.addWidget(helper)
        self.ffs_list = DropList(self._add_ffs_files)
        self.ffs_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ffs_list.setMinimumHeight(170)
        self.ffs_list.setToolTip("Add one or more CST far-field export files (.ffs). Their names drive project-name deduction.")
        self.ffs_list.itemChanged.connect(self.on_ffs_item_changed)
        self.ffs_list.itemSelectionChanged.connect(self._update_ffs_action_state)
        ffs_card.body.addWidget(self.ffs_list, 1)
        self.add_ffs_button = QPushButton("Add .ffs"); self.add_ffs_button.clicked.connect(self.add_ffs)
        self.remove_ffs_button = QPushButton("Remove selected"); self.remove_ffs_button.clicked.connect(self.remove_ffs)
        self.clear_ffs_button = QPushButton("Clear list"); self.clear_ffs_button.clicked.connect(self.clear_ffs)
        self.ffs_up_button = QPushButton("Move up"); self.ffs_up_button.clicked.connect(self.move_ffs_up)
        self.ffs_down_button = QPushButton("Move down"); self.ffs_down_button.clicked.connect(self.move_ffs_down)
        self.ffs_toggle_button = QPushButton("Enable/disable"); self.ffs_toggle_button.clicked.connect(self.toggle_selected_ffs_enabled)
        self.add_ffs_button.setToolTip("Browse for CST far-field export files to include in this project.")
        self.remove_ffs_button.setToolTip("Remove the highlighted far-field files from the current project.")
        self.clear_ffs_button.setToolTip("Clear the full far-field file list.")
        self.ffs_up_button.setToolTip("Move the selected far-field files up in the processing order.")
        self.ffs_down_button.setToolTip("Move the selected far-field files down in the processing order.")
        self.ffs_toggle_button.setToolTip("Temporarily disable or re-enable the selected far-field files without deleting them.")
        ffs_actions = ResponsiveButtonPanel(max_columns=3, min_button_width=135)
        self.ffs_actions = ffs_actions
        ffs_actions.set_buttons([
            self.add_ffs_button,
            self.remove_ffs_button,
            self.clear_ffs_button,
            self.ffs_up_button,
            self.ffs_down_button,
            self.ffs_toggle_button,
        ])
        ffs_card.body.addWidget(ffs_actions)

        inputs_help_card = Card("Input guide", "Flow")
        inputs_help_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        inputs_help = QLabel(
            "The far-field list is the main input for workbook generation.\n"
            "Touchstone is optional unless you need the VSWR plot.\n"
            "Input and preset changes are kept as pending project edits until you save."
        )
        inputs_help.setWordWrap(True)
        inputs_help.setObjectName("helper")
        self.inputs_help_label = inputs_help
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
        self.s2p_actions = s2p_actions
        s2p_actions.set_buttons([self.select_s2p_button, self.clear_s2p_button, self.open_s2p_button])
        s2p_card.body.addWidget(s2p_actions)
        inputs_left = QWidget()
        inputs_left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        inputs_left_layout = QVBoxLayout(inputs_left)
        inputs_left_layout.setContentsMargins(0, 0, 0, 0)
        inputs_left_layout.setSpacing(12)
        inputs_left_layout.addWidget(inputs_help_card)
        inputs_left_layout.addWidget(s2p_card)
        inputs_left_layout.addStretch(1)
        inputs_panel = ResponsiveCardPanel(max_columns=1, min_card_width=360)
        self.inputs_panel = inputs_panel
        inputs_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        inputs_panel.set_cards([inputs_left, ffs_card])
        inputs_lay.addWidget(inputs_panel, 1)

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

        legend_card = Card("Legend labels", "Style")
        legend_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        legend_card.setMinimumWidth(320)
        self.gain_legend_labels = QLineEdit(self.store.get("gain_legend_labels", ""))
        self.beamwidth_legend_labels = QLineEdit(self.store.get("beamwidth_legend_labels", ""))
        self.beam_eff_legend_labels = QLineEdit(self.store.get("beam_eff_legend_labels", ""))
        self.vswr_legend_labels = QLineEdit(self.store.get("vswr_legend_labels", ""))
        self.gain_legend_labels.textChanged.connect(lambda v: self.store.set("gain_legend_labels", v))
        self.beamwidth_legend_labels.textChanged.connect(lambda v: self.store.set("beamwidth_legend_labels", v))
        self.beam_eff_legend_labels.textChanged.connect(lambda v: self.store.set("beam_eff_legend_labels", v))
        self.vswr_legend_labels.textChanged.connect(lambda v: self.store.set("vswr_legend_labels", v))
        legend_form = QFormLayout()
        legend_form.setContentsMargins(0, 0, 0, 0)
        legend_form.setHorizontalSpacing(10)
        legend_form.setVerticalSpacing(8)
        legend_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        legend_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_form_row(legend_form, "Gain legends", self.gain_legend_labels, "Optional comma-separated legend labels for the gain plot, in trace order.")
        add_form_row(legend_form, "Beamwidth legends", self.beamwidth_legend_labels, "Optional comma-separated legend labels for the beamwidth plot, in trace order.")
        add_form_row(legend_form, "Beam eff legends", self.beam_eff_legend_labels, "Optional comma-separated legend labels for the beam-efficiency plot, in trace order.")
        add_form_row(legend_form, "VSWR legends", self.vswr_legend_labels, "Optional comma-separated legend labels for the VSWR plot, in trace order.")
        legend_card.body.addLayout(legend_form)

        processing_panel = ResponsiveCardPanel(max_columns=2, min_card_width=320)
        self.processing_panel = processing_panel
        processing_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        processing_panel.set_cards([
            workbook_card,
            frequency_card,
            gain_range_card,
            beamwidth_range_card,
            efficiency_range_card,
            vswr_range_card,
        ])
        self.ranges_panel = processing_panel
        processing_lay.addWidget(processing_panel, 1)
        processing_lay.addStretch(1)

        colors_panel = ResponsiveCardPanel(max_columns=2, min_card_width=320)
        self.colors_panel = colors_panel
        colors_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        colors_panel.set_cards([plot_color_card, polar_card])
        style_lay.addWidget(colors_panel, 1)

        style_lay.addWidget(legend_card, 1)
        style_lay.addStretch(1)

        self.workflow_tabs.addTab(inputs_scroll, "Inputs")
        self.workflow_tabs.addTab(processing_scroll, "Processing")
        self.workflow_tabs.addTab(style_scroll, "Style")
        self.workflow_tabs.addTab(run_scroll, "Run")
        self.workflow_tabs.setTabToolTip(0, "Far-field and Touchstone inputs.")
        self.workflow_tabs.setTabToolTip(1, "Beam, workbook, VSWR, and axis-range controls.")
        self.workflow_tabs.setTabToolTip(2, "Plot colors, polar presentation, and legend labels.")
        self.workflow_tabs.setTabToolTip(3, "Run the pipeline, inspect readiness, and review generated output paths.")
        self.setCentralWidget(root)

        self.console_window = ConsoleWindow(self, self.store)
        self.console = self.console_window.console
        self.help_window = HelpWindow(self, self.store)
        self._set_console_visible(False, persist=False)
        self._set_help_visible(False, persist=False)

        self._bind_project_persistence()
        self.refresh_preset_list()
        self._sync_theme_selector()
        self._sync_console_toggle()
        self._sync_help_toggle()
        restore_index = int(self.store.get("studio_nav_index", 0))
        self.workflow_tabs.setCurrentIndex(max(0, min(restore_index, self.workflow_tabs.count() - 1)))
        self.on_tab_changed(self.workflow_tabs.currentIndex())

    def _make_scroll_page(self) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
        content = QWidget()
        layout = QVBoxLayout(content)
        self._scroll_page_layouts.append(layout)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll, content, layout

    def _select_workflow_tab(self, title: str) -> None:
        for index in range(self.workflow_tabs.count()):
            if self.workflow_tabs.tabText(index) == title:
                self.workflow_tabs.setCurrentIndex(index)
                return

    def _show_inputs_tab(self) -> None:
        self._select_workflow_tab("Inputs")

    def _show_processing_tab(self) -> None:
        self._select_workflow_tab("Processing")

    def _open_manual_runs_menu(self) -> None:
        if self.run_more_button.isEnabled():
            self.run_more_button.showMenu()

    def _set_readiness_action(self, text: str, callback, enabled: bool = True, tooltip: str = "") -> None:
        previous = getattr(self, "_readiness_action_callback", None)
        if previous is not None:
            try:
                self.readiness_action.clicked.disconnect(previous)
            except TypeError:
                pass
        self._readiness_action_callback = callback if enabled else None
        if enabled and callback is not None:
            self.readiness_action.clicked.connect(callback)
        self.readiness_action.setText(text)
        self.readiness_action.setEnabled(enabled)
        self.readiness_action.setToolTip(tooltip or text)
        self.readiness_action.setVisible(text != "Run Full Pipeline")

    def on_tab_changed(self, index: int) -> None:
        if index < 0:
            return
        self.store.set("studio_nav_index", index)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_layout_mode()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_layout_mode()

    def _reset_to_default_state(self, clear_persisted_project: bool = True) -> None:
        self._loading_project = True
        self.active_project_slug = ""
        self.active_project_name = ""
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
        self.gain_legend_labels.clear()
        self.beamwidth_legend_labels.clear()
        self.beam_eff_legend_labels.clear()
        self.vswr_legend_labels.clear()
        self.rings.setText("0,-7.5,-15,-22.5,-30")
        self.angle_step.setValue(30)
        self.clip_db.setValue(-30.0)
        self.workflow_tabs.setCurrentIndex(0)
        self.refresh_preset_list(select_name=self.global_active_preset)
        self.project_combo.blockSignals(True)
        self.project_combo.setCurrentIndex(0)
        self.project_combo.blockSignals(False)
        if clear_persisted_project:
            self.store.set("active_project", "")
        self._loading_project = False
        self.refresh_derived_paths()

    def _default_project_settings(self) -> dict[str, object]:
        return {
            "smooth": 5,
            "theta": 8.0,
            "smooth2": 5,
            "shared_xstep": 0.2,
            "shared_fmin": 0.0,
            "shared_fmax": 0.0,
            "shared_xlog": False,
            "gain_ymin": 0.0,
            "gain_ymax": 0.0,
            "gain_y_step": 0.0,
            "beamwidth_ymin": 0.0,
            "beamwidth_ymax": 0.0,
            "beamwidth_y_step": 0.0,
            "beam_eff_ymin": 0.0,
            "beam_eff_ymax": 0.0,
            "beam_eff_y_step": 0.0,
            "vswr_ymin": 1.0,
            "vswr_ymax": 10.0,
            "vswr_ystep": 1.0,
            "vswr_smooth": 5,
            "grid_color": DEFAULT_GRID_COLOR,
            "plot_line_1": DEFAULT_LINE_COLORS[0][1],
            "plot_line_2": DEFAULT_LINE_COLORS[1][1],
            "gain_legend_labels": "",
            "beamwidth_legend_labels": "",
            "beam_eff_legend_labels": "",
            "vswr_legend_labels": "",
            "rings": "0,-7.5,-15,-22.5,-30",
            "angle": 30,
            "clip": -30.0,
        }

    def _apply_default_project_settings(self) -> None:
        self.apply_preset_values(self._default_project_settings())

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
            f"The current project has unsaved changes. Save before {action}?",
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

    def _screen_available_height(self) -> int:
        screen = self.screen()
        if screen:
            return int(screen.availableGeometry().height())
        app = QApplication.instance()
        if app and app.primaryScreen():
            return int(app.primaryScreen().availableGeometry().height())
        return int(self.height())

    def _available_window_width(self) -> int:
        if self.width() > 0:
            return int(self.width())
        screen = self.screen()
        if screen:
            return int(screen.availableGeometry().width())
        app = QApplication.instance()
        if app and app.primaryScreen():
            return int(app.primaryScreen().availableGeometry().width())
        return 0

    def _should_use_compact_layout(self) -> bool:
        return (
            self._screen_available_height() <= COMPACT_SCREEN_HEIGHT
            or self._available_window_width() <= COMPACT_WINDOW_WIDTH
        )

    def _layout_metrics(self) -> dict[str, object]:
        if self._compact_layout:
            return {
                "base_font_size": 11,
                "widget_font_size": 11,
                "title_band_radius": 24,
                "workspace_shell_radius": 24,
                "card_radius": 18,
                "root_margin": 14,
                "root_spacing": 14,
                "title_margins": (18, 14, 18, 14),
                "title_spacing": 12,
                "brand_spacing": 3,
                "title_tools_spacing": 8,
                "shell_margin": 14,
                "shell_spacing": 10,
                "scroll_top_margin": 2,
                "scroll_spacing": 10,
                "card_margin": 14,
                "card_spacing": 7,
                "card_body_spacing": 7,
                "panel_gap": 10,
                "button_gap": 6,
                "command_panel_min_card_width": 430,
                "readiness_panel_min_card_width": 150,
                "inputs_panel_min_card_width": 320,
                "processing_panel_min_card_width": 300,
                "ranges_panel_min_card_width": 300,
                "colors_panel_min_card_width": 300,
                "hero_min_button_width": 132,
                "project_min_button_width": 118,
                "preset_min_button_width": 96,
                "ffs_min_button_width": 118,
                "s2p_min_button_width": 122,
                "ffs_list_min_height": 140,
                "brand_title_size": 19,
                "brand_subtitle_size": 10.25,
                "run_info_size": 10.25,
                "card_title_size": 13,
                "eyebrow_size": 9,
                "project_name_size": 17.5,
                "helper_size": 10.25,
                "badge_font_size": 9,
                "badge_padding": (5, 9),
                "tab_margin_top": 4,
                "tab_padding": (8, 14),
                "tab_min_width": 102,
                "input_padding": (7, 10),
                "button_padding": (9, 13),
                "primary_button_padding": (10, 15),
                "step_button_padding_v": 6,
                "step_button_font_size": 11,
                "pill_padding": (6, 9),
            }
        return {
            "base_font_size": 12,
            "widget_font_size": 12,
            "title_band_radius": 28,
            "workspace_shell_radius": 28,
            "card_radius": 20,
            "root_margin": 18,
            "root_spacing": 16,
            "title_margins": (22, 20, 22, 20),
            "title_spacing": 16,
            "brand_spacing": 6,
            "title_tools_spacing": 10,
            "shell_margin": 20,
            "shell_spacing": 14,
            "scroll_top_margin": 6,
            "scroll_spacing": 14,
            "card_margin": 18,
            "card_spacing": 10,
            "card_body_spacing": 10,
            "panel_gap": 14,
            "button_gap": 10,
            "command_panel_min_card_width": 480,
            "readiness_panel_min_card_width": 170,
            "inputs_panel_min_card_width": 360,
            "processing_panel_min_card_width": 320,
            "ranges_panel_min_card_width": 320,
            "colors_panel_min_card_width": 320,
            "hero_min_button_width": 150,
            "project_min_button_width": 130,
            "preset_min_button_width": 110,
            "ffs_min_button_width": 135,
            "s2p_min_button_width": 145,
            "ffs_list_min_height": 170,
            "brand_title_size": 24,
            "brand_subtitle_size": 11.5,
            "run_info_size": 11.5,
            "card_title_size": 15,
            "eyebrow_size": 9.5,
            "project_name_size": 20.5,
            "helper_size": 11.5,
            "badge_font_size": 10,
            "badge_padding": (7, 11),
            "tab_margin_top": 8,
            "tab_padding": (11, 18),
            "tab_min_width": 120,
            "input_padding": (9, 12),
            "button_padding": (11, 15),
            "primary_button_padding": (12, 18),
            "step_button_padding_v": 7,
            "step_button_font_size": 12,
            "pill_padding": (8, 11),
        }

    def _set_pipeline_details_visible(self, visible: bool) -> None:
        self.pipeline_details.setVisible(visible)
        self.pipeline_details_toggle.setChecked(visible)
        self.pipeline_details_toggle.setText("Hide Details" if visible else "Show Details")

    def _on_pipeline_details_toggled(self, checked: bool) -> None:
        self._set_pipeline_details_visible(checked)

    def _apply_layout_metrics(self) -> None:
        metrics = self._layout_metrics()
        root_margin = int(metrics["root_margin"])
        self.root_lay.setContentsMargins(root_margin, root_margin, root_margin, root_margin)
        self.root_lay.setSpacing(int(metrics["root_spacing"]))
        left, top, right, bottom = metrics["title_margins"]
        self.title_lay.setContentsMargins(int(left), int(top), int(right), int(bottom))
        self.title_lay.setSpacing(int(metrics["title_spacing"]))
        self.brand_lay.setSpacing(int(metrics["brand_spacing"]))
        self.title_tools.setSpacing(int(metrics["title_tools_spacing"]))
        shell_margin = int(metrics["shell_margin"])
        self.shell_lay.setContentsMargins(shell_margin, shell_margin, shell_margin, shell_margin)
        self.shell_lay.setSpacing(int(metrics["shell_spacing"]))
        for layout in self._scroll_page_layouts:
            layout.setContentsMargins(0, int(metrics["scroll_top_margin"]), 0, 0)
            layout.setSpacing(int(metrics["scroll_spacing"]))
        for card in self.findChildren(Card):
            layout = card.layout()
            if not isinstance(layout, QVBoxLayout):
                continue
            card_margin = int(metrics["card_margin"])
            layout.setContentsMargins(card_margin, card_margin, card_margin, card_margin)
            layout.setSpacing(int(metrics["card_spacing"]))
            card.body.setSpacing(int(metrics["card_body_spacing"]))
        panel_gap = int(metrics["panel_gap"])
        for panel, min_width in (
            (self.command_panel, int(metrics["command_panel_min_card_width"])),
            (self.readiness_panel, int(metrics["readiness_panel_min_card_width"])),
            (self.inputs_panel, int(metrics["inputs_panel_min_card_width"])),
            (self.processing_panel, int(metrics["processing_panel_min_card_width"])),
            (self.ranges_panel, int(metrics["ranges_panel_min_card_width"])),
            (self.colors_panel, int(metrics["colors_panel_min_card_width"])),
        ):
            panel.min_card_width = min_width
            panel.grid.setHorizontalSpacing(panel_gap)
            panel.grid.setVerticalSpacing(panel_gap)
            panel.refresh_layout(force=True)
        button_gap = int(metrics["button_gap"])
        for panel, min_width in (
            (self.hero_actions, int(metrics["hero_min_button_width"])),
            (self.project_actions, int(metrics["project_min_button_width"])),
            (self.preset_actions, int(metrics["preset_min_button_width"])),
            (self.ffs_actions, int(metrics["ffs_min_button_width"])),
            (self.s2p_actions, int(metrics["s2p_min_button_width"])),
        ):
            panel.min_button_width = min_width
            panel.grid.setHorizontalSpacing(button_gap)
            panel.grid.setVerticalSpacing(button_gap)
            panel.refresh_layout(force=True)
        self.pipeline_details_layout.setSpacing(int(metrics["card_body_spacing"]))
        self.ffs_list.setMinimumHeight(int(metrics["ffs_list_min_height"]))
        compact = self._compact_layout
        self.brand_subtitle.setVisible(not compact)
        self.run_help_label.setVisible(not compact)
        self.project_help_label.setVisible(not compact)
        self.preset_help_label.setVisible(not compact)
        self.ffs_help_label.setVisible(not compact)
        self.inputs_help_label.setVisible(not compact)
        self.pipeline_details_toggle.setVisible(compact)
        if compact:
            self._set_pipeline_details_visible(False)
        else:
            self._set_pipeline_details_visible(True)

    def _update_layout_mode(self, force: bool = False) -> None:
        compact = self._should_use_compact_layout()
        if not force and compact == self._compact_layout:
            return
        self._compact_layout = compact
        self._apply_layout_metrics()
        self._apply_style()

    def _apply_style(self):
        QApplication.setStyle(QStyleFactory.create("Fusion"))
        theme = THEME_STYLES.get(self.theme, THEME_STYLES["light"])
        metrics = self._layout_metrics()
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor(theme["palette_window"]))
        pal.setColor(QPalette.WindowText, QColor(theme["palette_window_text"]))
        pal.setColor(QPalette.Base, QColor(theme["palette_base"]))
        pal.setColor(QPalette.AlternateBase, QColor(theme["card_bg"]))
        pal.setColor(QPalette.Text, QColor(theme["palette_text"]))
        pal.setColor(QPalette.Button, QColor(theme["palette_button"]))
        pal.setColor(QPalette.ButtonText, QColor(theme["palette_button_text"]))
        pal.setColor(QPalette.ToolTipBase, QColor(theme["card_bg"]))
        pal.setColor(QPalette.ToolTipText, QColor(theme["title_color"]))
        pal.setColor(QPalette.Highlight, QColor(theme["palette_highlight"]))
        pal.setColor(QPalette.HighlightedText, QColor(theme["palette_highlight_text"]))
        QApplication.setPalette(pal)
        app = QApplication.instance()
        if app:
            base_font = QFont("Segoe UI", int(metrics["base_font_size"]))
            app.setFont(base_font)
            app.setStyleSheet("""
                QWidget { font-size: %(widget_font_size)gpt; }
                QMainWindow { background: %(window_bg)s; }
                QScrollArea { background: transparent; border: none; }
                QLabel { color: %(text_color)s; }
                QMainWindow, QDialog { color: %(text_color)s; }
                #titleBand { border-radius: %(title_band_radius)spx; background: %(title_band_bg)s; }
                #workspaceShell { background: %(shell_bg)s; border: 1px solid %(shell_border)s; border-radius: %(workspace_shell_radius)spx; }
                #brandTitle { color: white; font-size: %(brand_title_size)gpt; font-weight: 700; }
                #brandSubtitle { color: %(title_subtle)s; font-size: %(brand_subtitle_size)gpt; font-weight: 500; }
                #runInfo { color: %(text_color)s; font-size: %(run_info_size)gpt; }
                #card { background: %(card_bg)s; border: 1px solid %(card_border)s; border-radius: %(card_radius)spx; }
                #cardTitle { color: %(title_color)s; font-size: %(card_title_size)gpt; font-weight: 700; }
                #eyebrow { color: %(eyebrow_color)s; font-size: %(eyebrow_size)gpt; font-weight: 700; }
                #projectName { color: %(title_color)s; font-size: %(project_name_size)gpt; font-weight: 700; }
                #projectMeta { color: %(helper_color)s; font-size: %(helper_size)gpt; }
                #summaryBadge { background: %(badge_bg)s; color: %(badge_text)s; border: 1px solid %(badge_border)s; border-radius: 12px; padding: %(badge_padding_v)spx %(badge_padding_h)spx; font-size: %(badge_font_size)gpt; font-weight: 700; }
                #helper { color: %(helper_color)s; font-size: %(helper_size)gpt; }
                QTabWidget::pane { border: none; background: transparent; margin-top: %(tab_margin_top)spx; }
                QTabBar::tab { background: %(tab_bg)s; border: 1px solid %(shell_border)s; border-bottom: none; border-top-left-radius: 14px; border-top-right-radius: 14px; padding: %(tab_padding_v)spx %(tab_padding_h)spx; margin-right: 6px; min-width: %(tab_min_width)spx; color: %(helper_color)s; font-weight: 700; }
                QTabBar::tab:hover { background: %(tab_hover)s; color: %(title_color)s; }
                QTabBar::tab:selected { background: %(tab_selected)s; color: %(title_color)s; }
                QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget, QPlainTextEdit { background: %(input_bg)s; border: 1px solid %(input_border)s; border-radius: 14px; padding: %(input_padding_v)spx %(input_padding_h)spx; color: %(title_color)s; }
                QComboBox::drop-down { border: none; width: 28px; }
                QComboBox QAbstractItemView { background: %(card_bg)s; border: 1px solid %(card_border)s; color: %(title_color)s; selection-background-color: %(list_selected)s; selection-color: %(title_color)s; }
                QListWidget::item { padding: 7px 10px; border-radius: 10px; margin: 1px 0; }
                QListWidget::item:selected { background: %(list_selected)s; color: %(title_color)s; }
                QPushButton { background: %(button_bg)s; border: 1px solid %(input_border)s; border-radius: 14px; padding: %(button_padding_v)spx %(button_padding_h)spx; color: %(title_color)s; font-weight: 600; }
                QPushButton:hover { border-color: #7fb2cf; background: %(button_hover)s; }
                QPushButton:disabled { color: %(helper_color)s; background: %(input_bg)s; border-color: %(card_border)s; }
                QPushButton#primaryButton { background: %(primary_bg)s; color: white; border: none; padding: %(primary_button_padding_v)spx %(primary_button_padding_h)spx; }
                QPushButton#primaryButton:hover { background: %(primary_hover)s; }
                QPushButton#ghostButton { background: %(ghost_bg)s; }
                QPushButton#ghostButton:hover { background: %(ghost_hover)s; }
                QComboBox#themeSelector { min-width: 168px; font-weight: 600; }
                QPushButton#stepButton { background: %(step_bg)s; border: 1px solid %(step_border)s; border-radius: 12px; padding: %(step_button_padding_v)spx 0; font-size: %(step_button_font_size)gpt; font-weight: 700; min-width: 30px; }
                QPushButton#stepButton:hover { background: %(step_hover)s; border-color: #7fb2cf; }
                QCheckBox#pillCheck { spacing: 8px; padding: %(pill_padding_v)spx %(pill_padding_h)spx; border: 1px solid %(input_border)s; border-radius: 12px; background: %(ghost_bg)s; color: %(title_color)s; font-weight: 600; }
                QCheckBox#pillCheck:hover { border-color: #7fb2cf; background: %(ghost_hover)s; }
                QCheckBox#pillCheck::indicator { width: 16px; height: 16px; border-radius: 8px; border: 1px solid %(step_border)s; background: transparent; }
                QCheckBox#pillCheck::indicator:checked { background: %(primary_bg)s; border-color: %(primary_bg)s; }
                QProgressBar { background: %(progress_bg)s; border: 1px solid %(card_border)s; border-radius: 10px; color: %(title_color)s; min-height: 18px; }
                QProgressBar::chunk { background: %(primary_bg)s; border-radius: 8px; }
            """ % {
                **theme,
                "widget_font_size": metrics["widget_font_size"],
                "title_band_radius": metrics["title_band_radius"],
                "workspace_shell_radius": metrics["workspace_shell_radius"],
                "brand_title_size": metrics["brand_title_size"],
                "brand_subtitle_size": metrics["brand_subtitle_size"],
                "run_info_size": metrics["run_info_size"],
                "card_radius": metrics["card_radius"],
                "card_title_size": metrics["card_title_size"],
                "eyebrow_size": metrics["eyebrow_size"],
                "project_name_size": metrics["project_name_size"],
                "helper_size": metrics["helper_size"],
                "badge_font_size": metrics["badge_font_size"],
                "badge_padding_v": metrics["badge_padding"][0],
                "badge_padding_h": metrics["badge_padding"][1],
                "tab_margin_top": metrics["tab_margin_top"],
                "tab_padding_v": metrics["tab_padding"][0],
                "tab_padding_h": metrics["tab_padding"][1],
                "tab_min_width": metrics["tab_min_width"],
                "input_padding_v": metrics["input_padding"][0],
                "input_padding_h": metrics["input_padding"][1],
                "button_padding_v": metrics["button_padding"][0],
                "button_padding_h": metrics["button_padding"][1],
                "primary_button_padding_v": metrics["primary_button_padding"][0],
                "primary_button_padding_h": metrics["primary_button_padding"][1],
                "step_button_padding_v": metrics["step_button_padding_v"],
                "step_button_font_size": metrics["step_button_font_size"],
                "pill_padding_v": metrics["pill_padding"][0],
                "pill_padding_h": metrics["pill_padding"][1],
            })

    def _sync_theme_selector(self):
        if not hasattr(self, "theme_selector"):
            return
        index = self.theme_selector.findData(self.theme)
        self.theme_selector.blockSignals(True)
        self.theme_selector.setCurrentIndex(max(0, index))
        self.theme_selector.blockSignals(False)

    def _sync_console_toggle(self):
        visible = self.console_window.isVisible() if hasattr(self, "console_window") else bool(self.store.get("console_visible", False))
        self.console_toggle.setChecked(visible)
        self.console_toggle.setText("Hide Console" if visible else "Show Console")

    def _sync_help_toggle(self):
        visible = self.help_window.isVisible() if hasattr(self, "help_window") else bool(self.store.get("help_visible", False))
        self.help_button.setChecked(visible)
        self.help_button.setText("Hide Help" if visible else "Show Help")

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

    def _set_help_visible(self, visible: bool, persist: bool = True):
        if visible:
            self.help_window.show()
            self.help_window.raise_()
            self.help_window.activateWindow()
        else:
            self.help_window._save_geometry()
            self.help_window.hide()
        self.help_button.setChecked(visible)
        self.help_button.setText("Hide Help" if visible else "Show Help")
        if persist:
            self.store.set("help_visible", visible)

    def on_console_popup_closed(self):
        if self._closing_app:
            return
        self.console_toggle.setChecked(False)
        self.console_toggle.setText("Show Console")
        self.store.set("console_visible", False)

    def on_help_popup_closed(self):
        if self._closing_app:
            return
        self.help_button.setChecked(False)
        self.help_button.setText("Show Help")
        self.store.set("help_visible", False)

    def on_theme_selected(self, _index: int) -> None:
        selected = str(self.theme_selector.currentData() or "").strip().lower()
        if not selected or selected == self.theme:
            return
        self.theme = selected if selected in THEME_LABELS else "light"
        self.store.set("theme", self.theme)
        self._sync_theme_selector()
        self._apply_style()

    def toggle_console(self, checked: bool = False):
        self._set_console_visible(checked)

    def toggle_help(self, checked: bool = False):
        self._set_help_visible(checked)

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
            self.gain_legend_labels.textChanged,
            self.beamwidth_legend_labels.textChanged,
            self.beam_eff_legend_labels.textChanged,
            self.vswr_legend_labels.textChanged,
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
            "datasheet": ["smooth", "theta", "shared_fmin", "shared_fmax"],
            "plot": [
                "smooth2", "shared_xstep", "shared_fmin", "shared_fmax", "shared_xlog",
                "gain_ymin", "gain_ymax", "gain_y_step",
                "beamwidth_ymin", "beamwidth_ymax", "beamwidth_y_step",
                "beam_eff_ymin", "beam_eff_ymax", "beam_eff_y_step",
                "grid_color", "plot_line_1", "plot_line_2",
                "gain_legend_labels", "beamwidth_legend_labels", "beam_eff_legend_labels",
                "rings", "angle", "clip",
            ],
            "vswr": [
                "shared_xstep", "shared_fmin", "shared_fmax", "shared_xlog",
                "vswr_ymin", "vswr_ymax", "vswr_ystep", "vswr_smooth",
                "grid_color", "plot_line_1", "plot_line_2", "vswr_legend_labels",
            ],
        }
        return {key: values[key] for key in setting_keys.get(stage_key, []) if key in values}

    def _current_stage_snapshot(self, stage_key: str) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "schema_version": CURRENT_PROJECT_SCHEMA_VERSION,
            "settings": self._stage_settings_snapshot(stage_key),
        }
        if stage_key in {"beam", "extract", "plot", "datasheet"}:
            snapshot["ffs_items"] = [
                {
                    "path": serialize_workspace_path(THIS_DIR, str(item["path"])),
                    "enabled": bool(item["enabled"]),
                    "file": self._path_fingerprint(str(item["path"])),
                }
                for item in self.collect_ffs_items()
            ]
        if stage_key in {"extract", "vswr", "datasheet"}:
            snapshot["touchstone"] = self._path_fingerprint(self.selected_s2p())
        if stage_key in {"extract", "plot", "datasheet"}:
            snapshot["beam_workbook"] = self._path_fingerprint(self.deduced_beam_output())
        if stage_key == "datasheet":
            snapshot["extract_workbook"] = self._path_fingerprint(self.deduced_extract_output())
            snapshot["template_pdf"] = self._path_fingerprint(DATASHEET_TEMPLATE)
            snapshot["plot_outputs"] = [
                self._path_fingerprint(path)
                for path in self._stage_output_files("plot")
            ]
        return snapshot

    def _stage_output_files(self, stage_key: str) -> list[Path]:
        if stage_key == "beam":
            return [self.deduced_beam_output()]
        if stage_key == "extract":
            return [self.deduced_extract_output()]
        if stage_key == "datasheet":
            return [self.deduced_datasheet_output()]
        if stage_key == "vswr":
            vswr_output = self.deduced_vswr_output()
            return [
                vswr_output,
                vswr_output.with_name(f"{vswr_output.stem}_legend{vswr_output.suffix}"),
            ]
        if stage_key == "plot":
            stem = self.deduced_beam_output().stem
            out_dir = self.project_results_dir()
            return [
                out_dir / f"{stem}_gain.svg",
                out_dir / f"{stem}_gain_legend.svg",
                out_dir / f"{stem}_beamwidth.svg",
                out_dir / f"{stem}_beamwidth_legend.svg",
                out_dir / f"{stem}_beam_efficiency.svg",
                out_dir / f"{stem}_beam_efficiency_legend.svg",
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
        if stage_key == "datasheet":
            return enabled_ffs and has_touchstone
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
        preset = self.global_presets.get(name)
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
        if not DATASHEET_TEMPLATE.exists():
            messages.append(f"Datasheet template is missing: {display_workspace_path(DATASHEET_TEMPLATE)}")
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

    def _latest_failed_stage_key(self) -> str:
        return next(
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

    def _refresh_stage_labels(self) -> None:
        if not self.stage_status_labels or not self.stage_open_buttons:
            return
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

    def _refresh_run_readiness(self) -> None:
        has_project = bool(self.active_project_slug)
        total_ffs = len(self.collect_ffs_items()) if has_project else 0
        enabled_ffs = self._enabled_ffs_count() if has_project else 0
        missing_enabled = self._missing_enabled_ffs() if has_project else []
        s2p = self.selected_s2p() if has_project else ""
        touchstone_ready = bool(s2p) and Path(s2p).exists()
        frequency_ready = self._frequency_window_is_valid()
        stale_stages = self._stale_stage_keys() if has_project else []
        latest_failed = self._latest_failed_stage_key() if has_project else ""
        applicable_stages = [
            stage_key
            for stage_key, _label in STAGE_DEFINITIONS
            if has_project and self._stage_is_applicable(stage_key)
        ]
        ready_stages = [stage_key for stage_key in applicable_stages if self._stage_output_exists(stage_key)]
        running = bool(self._current_stage_key or self._pending_stage_keys or self.proc.running_cmd or self.proc.queue)
        unsaved_changes = self.has_unsaved_project_changes()
        full_ready = (
            has_project
            and frequency_ready
            and enabled_ffs > 0
            and not missing_enabled
            and touchstone_ready
            and DATASHEET_TEMPLATE.exists()
        )
        vswr_ready = has_project and frequency_ready and touchstone_ready

        if not has_project:
            self.readiness_badges["project"].setText("Not selected")
            self.readiness_badges["inputs"].setText("No files")
            self.readiness_badges["touchstone"].setText("Not selected")
            self.readiness_badges["outputs"].setText("No outputs")
            self.readiness_summary.setText("Create a project first. Input paths, preset selection, and output freshness are tracked per project.")
            self._set_readiness_action("Create project", self.create_project, tooltip="Create a new project.")
            return

        self.readiness_badges["project"].setText("Unsaved" if unsaved_changes else "Saved")
        if missing_enabled:
            self.readiness_badges["inputs"].setText("Files missing")
        elif total_ffs == 0:
            self.readiness_badges["inputs"].setText("No files")
        elif enabled_ffs == 0:
            self.readiness_badges["inputs"].setText("All disabled")
        else:
            self.readiness_badges["inputs"].setText(f"{enabled_ffs} ready")

        if not s2p:
            self.readiness_badges["touchstone"].setText("Optional")
        elif touchstone_ready:
            self.readiness_badges["touchstone"].setText("Ready")
        else:
            self.readiness_badges["touchstone"].setText("File missing")

        if running:
            outputs_state = "Running"
        elif stale_stages:
            outputs_state = f"{len(stale_stages)} stale"
        elif not ready_stages:
            outputs_state = "Not generated"
        elif len(ready_stages) < len(applicable_stages):
            outputs_state = "Partial"
        else:
            outputs_state = "Up to date"
        self.readiness_badges["outputs"].setText(outputs_state)

        if running:
            stage_label = STAGE_LABELS.get(self._current_stage_key, self._current_stage_key.title()) if self._current_stage_key else "Pipeline"
            queued = len(self._pending_stage_keys)
            self.readiness_summary.setText(
                f"{stage_label} is running."
                + (f" {queued} stage(s) remain queued." if queued else " The queue is active.")
            )
            self._set_readiness_action("Cancel run", self.cancel_run, tooltip="Stop the current run and clear any queued stages.")
            return

        if unsaved_changes:
            self.readiness_summary.setText("Save the current project before running so the edited inputs and preset selection match the next run snapshot.")
            self._set_readiness_action("Save project", self.save_project_changes, tooltip="Persist the current project state.")
            return

        if not frequency_ready:
            self.readiness_summary.setText("The shared frequency window is invalid. Fix it before running stages that depend on workbook, extract, plot, or VSWR settings.")
            self._set_readiness_action("Open Processing", self._show_processing_tab, tooltip="Go to the Processing tab to fix the shared frequency window.")
            return

        if missing_enabled:
            self.readiness_summary.setText("One or more enabled far-field files are missing. Fix or disable them before running workbook-based stages.")
            self._set_readiness_action("Open Inputs", self._show_inputs_tab, tooltip="Go to the Inputs tab to fix far-field file paths.")
            return

        if total_ffs == 0:
            if vswr_ready:
                self.readiness_summary.setText("No far-field files are configured, so VSWR is the only runnable output right now.")
                self._set_readiness_action("Run VSWR", self.run_vswr, tooltip="Generate the VSWR output from the selected Touchstone file.")
            else:
                self.readiness_summary.setText("Add far-field files for workbook and plot stages, or select a Touchstone file if you only need VSWR.")
                self._set_readiness_action("Open Inputs", self._show_inputs_tab, tooltip="Go to the Inputs tab to add far-field files or a Touchstone file.")
            return

        if enabled_ffs == 0:
            if vswr_ready:
                self.readiness_summary.setText("All far-field files are disabled, so VSWR is the only runnable output right now.")
                self._set_readiness_action("Run VSWR", self.run_vswr, tooltip="Generate the VSWR output from the selected Touchstone file.")
            else:
                self.readiness_summary.setText("All far-field files are disabled. Enable at least one to run workbook and plot stages.")
                self._set_readiness_action("Open Inputs", self._show_inputs_tab, tooltip="Go to the Inputs tab to re-enable far-field files.")
            return

        if s2p and not touchstone_ready:
            self.readiness_summary.setText("The selected Touchstone file is missing. Full Pipeline and VSWR stay unavailable until you fix that path.")
            self._set_readiness_action("Open Inputs", self._show_inputs_tab, tooltip="Go to the Inputs tab to fix the Touchstone file path.")
            return

        if not s2p:
            self.readiness_summary.setText("Far-field stages are ready, but Touchstone is still missing. Use Manual runs for workbook, extract, or plots, or add Touchstone for Full Pipeline.")
            self._set_readiness_action("Manual runs", self._open_manual_runs_menu, tooltip="Open the single-stage run menu.")
            return

        if not DATASHEET_TEMPLATE.exists():
            self.readiness_summary.setText("Datasheet.pdf is missing from the project root, so Full Pipeline cannot complete. Use Manual runs until the template is restored.")
            self._set_readiness_action("Manual runs", self._open_manual_runs_menu, tooltip="Open the single-stage run menu.")
            return

        if latest_failed:
            self.readiness_summary.setText(f"Last run failed in {STAGE_LABELS.get(latest_failed, latest_failed.title())}. Retry after reviewing the console output.")
            self._set_readiness_action("Run Full Pipeline", self.run_full, tooltip="Retry the full pipeline.")
            return

        if stale_stages:
            labels = ", ".join(STAGE_LABELS[key] for key in stale_stages[:3])
            if len(stale_stages) > 3:
                labels += ", ..."
            self.readiness_summary.setText(f"Saved inputs changed since the last successful run. Rebuild the stale outputs: {labels}.")
            self._set_readiness_action("Run Full Pipeline", self.run_full, tooltip="Rebuild all outputs for the current project.")
            return

        if not ready_stages:
            self.readiness_summary.setText("The project is configured, but no outputs have been generated yet.")
            self._set_readiness_action("Run Full Pipeline", self.run_full, tooltip="Generate all configured outputs.")
            return

        if len(ready_stages) < len(applicable_stages):
            self.readiness_summary.setText("Some configured outputs are ready, but others have not been generated yet.")
            self._set_readiness_action("Run Full Pipeline", self.run_full, tooltip="Complete the remaining outputs with a full rerun.")
            return

        self.readiness_summary.setText("Inputs, selected preset, and generated outputs are in sync.")
        self._set_readiness_action("Run Full Pipeline", self.run_full, tooltip="Run the full pipeline again for a fresh rebuild.")

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
            self._refresh_run_readiness()
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
            latest_failed = self._latest_failed_stage_key()
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
        self._refresh_run_readiness()
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
            settings={},
            presets={},
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

    def deduced_datasheet_output(self) -> Path:
        project = self.current_project()
        return project.datasheet_path(THIS_DIR) if project else (self.project_results_dir() / "project_datasheet.pdf")

    def deduced_vswr_output(self) -> Path:
        project = self.current_project()
        return project.vswr_path(THIS_DIR) if project else (self.project_results_dir() / "project_vswr.svg")

    def refresh_derived_paths(self) -> None:
        if self.active_project_slug:
            project_label = self.active_project_name or self.active_project_slug
            self.project_name.setText(project_label)
            self.project_meta.setText(f"Folder: {display_workspace_path(self.project_results_dir())}")
            self.workbook_field.setText(display_workspace_path(self.deduced_beam_output()))
            self.extract_field.setText(display_workspace_path(self.deduced_extract_output()))
            self.datasheet_field.setText(display_workspace_path(self.deduced_datasheet_output()))
            self.results_field.setText(display_workspace_path(self.project_results_dir()))
            self.vswr_field.setText(display_workspace_path(self.deduced_vswr_output()))
        else:
            self.project_name.setText("No project selected")
            self.project_meta.setText("Create a project to keep inputs, presets, and generated results together.")
            self.workbook_field.clear()
            self.extract_field.clear()
            self.datasheet_field.clear()
            self.results_field.clear()
            self.vswr_field.clear()
        total_ffs = len(self.collect_ffs_items()) if self.active_project_slug else 0
        enabled_ffs = len(self.selected_ffs()) if self.active_project_slug else 0
        self.count_badge.setText(f"{enabled_ffs}/{total_ffs} far-field enabled" if total_ffs else "0 far-field files")
        if self.active_project_slug:
            suffix = " *" if self.has_unsaved_project_changes() else ""
            self.project_name.setText(f"{(self.active_project_name or self.active_project_slug)}{suffix}")
        self.open_s2p_button.setEnabled(bool(self.active_project_slug and self.selected_s2p()))
        self._update_ffs_action_state()
        self._refresh_project_summary()
        self._update_project_action_state()

    def _update_project_action_state(self) -> None:
        has_project = bool(self.active_project_slug)
        is_running = bool(self.proc.running_cmd or self.proc.queue)
        is_dirty = self.has_unsaved_project_changes()
        self.project_save_button.setEnabled(has_project and is_dirty)
        self.project_more_button.setEnabled(True)
        self.project_rename_action.setEnabled(has_project)
        self.project_duplicate_action.setEnabled(has_project)
        self.project_delete_action.setEnabled(has_project)
        self.project_run_menu.setEnabled(has_project)
        self.project_run_beam_action.setEnabled(has_project)
        self.project_run_extract_action.setEnabled(has_project)
        self.project_run_datasheet_action.setEnabled(has_project)
        self.project_run_plot_action.setEnabled(has_project)
        self.project_run_vswr_action.setEnabled(has_project)
        self.run_more_button.setEnabled(has_project)
        self.run_more_beam_action.setEnabled(has_project)
        self.run_more_extract_action.setEnabled(has_project)
        self.run_more_datasheet_action.setEnabled(has_project)
        self.run_more_plot_action.setEnabled(has_project)
        self.run_more_vswr_action.setEnabled(has_project)
        self.project_import_action.setEnabled(True)
        self.project_export_action.setEnabled(has_project)
        self.project_open_folder_action.setEnabled(has_project)
        for widget in (
            self.btn_full,
            self.ffs_list,
            self.s2p_field,
            self.add_ffs_button,
            self.remove_ffs_button,
            self.clear_ffs_button,
            self.select_s2p_button,
            self.clear_s2p_button,
            self.open_s2p_button,
        ):
            widget.setEnabled(has_project)
        self.btn_cancel.setEnabled(has_project and is_running)
        self._update_preset_action_state()

    def _update_preset_action_state(self) -> None:
        if not hasattr(self, "preset_combo"):
            return
        has_project = bool(self.active_project_slug)
        has_preset = bool(self.current_preset_name())
        self.preset_combo.setEnabled(True)
        self.preset_new_button.setEnabled(True)
        self.preset_save_button.setEnabled(True)
        self.preset_more_button.setEnabled(True)
        self.preset_rename_action.setEnabled(has_preset)
        self.preset_delete_action.setEnabled(has_preset)
        self.preset_import_action.setEnabled(True)
        self.preset_export_action.setEnabled(bool(self.global_presets))
        preset_label = self.project_active_preset or self.global_active_preset or ("Manual" if has_project else "none")
        self.preset_badge.setText(f"Preset: {preset_label}")
        if not has_project:
            if has_preset:
                self.preset_state_label.setText(f"Preset '{self.current_preset_name()}' is available globally. Select a project to save that choice with it.")
            else:
                self.preset_state_label.setText("Choose a preset or keep working manually.")
        elif self.project_active_preset and self.project_active_preset not in self.global_presets:
            self.preset_state_label.setText(
                f"Project preset '{self.project_active_preset}' is missing. Select an existing preset or save the current controls as a new one."
            )
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
            self.refresh_preset_list(select_name=self.global_active_preset)
            self.refresh_derived_paths()
            return
        project = self.project_store.load_project(slug)
        self._apply_project(project)

    def _persist_global_presets(self) -> None:
        self.store.set(PRESET_STORE_KEY, self.global_presets)
        active_name = self.global_active_preset if self.global_active_preset in self.global_presets else ""
        self.global_active_preset = active_name
        self.store.set(ACTIVE_PRESET_KEY, active_name)

    def _migrate_legacy_project_presets(self, presets: dict[str, dict[str, object]] | object) -> bool:
        imported = normalize_preset_payload(presets)
        changed = False
        for name, values in imported.items():
            if self.global_presets.get(name) != values:
                self.global_presets[name] = values
                changed = True
        if changed:
            self._persist_global_presets()
        return changed

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
        legacy_presets_migrated = self._migrate_legacy_project_presets(project.presets)
        self.project_active_preset = project.active_preset.strip()
        missing_preset = bool(self.project_active_preset and self.project_active_preset not in self.global_presets)
        self._apply_default_project_settings()
        if not missing_preset and self.project_active_preset:
            self.global_active_preset = self.project_active_preset
            self.apply_preset_values(self.global_presets.get(self.project_active_preset, {}))
        elif missing_preset:
            self.status(f"Preset '{self.project_active_preset}' is missing; using default controls for this project")
        self._persist_global_presets()
        self.refresh_preset_list(select_name=self.project_active_preset)
        self.store.set("beam_ffs", self.selected_ffs())
        self.store.set("vswr_s2p", touchstone)
        self._loading_project = False
        self._capture_saved_project_signature(self.current_project())
        if self._loaded_project_schema_version < CURRENT_PROJECT_SCHEMA_VERSION:
            self.save_active_project()
        elif project.settings or project.presets or legacy_presets_migrated:
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
        dialog = ProjectDialog(
            self,
            name=suggested_name,
            title="Create Project",
            note_text="Create the project by name first. Add far-field and Touchstone inputs on the Inputs tab, then click Save project.",
        )
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
        project = ProjectRecord(
            name=name,
            slug=slug,
            ffs_items=[],
            touchstone_file="",
            settings={},
            presets={},
            active_preset=self.current_preset_name(),
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
            title="Edit Project",
            note_text="Rename the project here. Update far-field and Touchstone inputs on the Inputs tab, then click Save project to persist them.",
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
        project = self.current_project()
        if not project:
            return
        project.name = name
        project.slug = new_slug
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
        return sorted(str(name) for name in self.global_presets.keys())

    def current_preset_name(self) -> str:
        if not hasattr(self, "preset_combo"):
            return ""
        name = self.preset_combo.currentData()
        return str(name or "")

    def refresh_preset_list(self, select_name: str | None = None) -> None:
        if not hasattr(self, "preset_combo"):
            return
        if select_name is None:
            select_name = self.project_active_preset or self.global_active_preset
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
            "gain_legend_labels": self.gain_legend_labels.text().strip(),
            "beamwidth_legend_labels": self.beamwidth_legend_labels.text().strip(),
            "beam_eff_legend_labels": self.beam_eff_legend_labels.text().strip(),
            "vswr_legend_labels": self.vswr_legend_labels.text().strip(),
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
        if "gain_legend_labels" in values: self.gain_legend_labels.setText(str(values["gain_legend_labels"]))
        if "beamwidth_legend_labels" in values: self.beamwidth_legend_labels.setText(str(values["beamwidth_legend_labels"]))
        if "beam_eff_legend_labels" in values: self.beam_eff_legend_labels.setText(str(values["beam_eff_legend_labels"]))
        if "vswr_legend_labels" in values: self.vswr_legend_labels.setText(str(values["vswr_legend_labels"]))
        if "rings" in values: self.rings.setText(str(values["rings"]))
        if "angle" in values: self.angle_step.setValue(int(values["angle"]))
        if "clip" in values: self.clip_db.setValue(float(values["clip"]))

    def on_preset_selected(self, _text: str) -> None:
        name = self.current_preset_name()
        self.project_active_preset = name
        self.global_active_preset = name if name in self.global_presets else ""
        self._persist_global_presets()
        self._update_preset_action_state()
        if not name:
            self._mark_project_dirty()
            return
        values = self.global_presets.get(name, {})
        if isinstance(values, dict):
            self.apply_preset_values(values)
        self._mark_project_dirty()

    def create_preset(self) -> None:
        suggested = suggest_preset_name(self.preset_names(), self.active_project_name or "Preset")
        name, ok = QInputDialog.getText(self, "Create Preset", "Preset name:", text=suggested)
        name = name.strip()
        if not ok or not name:
            return
        if name in self.global_presets:
            QMessageBox.information(self, "Preset Exists", f"A preset named '{name}' already exists.")
            return
        self.global_presets[name] = self.collect_preset_values()
        self.project_active_preset = name
        self.global_active_preset = name
        self._persist_global_presets()
        self._mark_project_dirty()
        self.refresh_preset_list(select_name=name)

    def save_preset(self) -> None:
        name = self.current_preset_name()
        if not name:
            self.create_preset()
            return
        self.global_presets[name] = self.collect_preset_values()
        self.project_active_preset = name
        self.global_active_preset = name
        self._persist_global_presets()
        self._mark_project_dirty()
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
        if new_name in self.global_presets:
            QMessageBox.information(self, "Preset Exists", f"A preset named '{new_name}' already exists.")
            return
        self.global_presets[new_name] = self.global_presets.pop(name)
        if self.project_active_preset == name:
            self.project_active_preset = new_name
        if self.global_active_preset == name:
            self.global_active_preset = new_name
        self._persist_global_presets()
        self._mark_project_dirty()
        self.refresh_preset_list(select_name=new_name)

    def delete_preset(self) -> None:
        name = self.current_preset_name()
        if not name:
            QMessageBox.information(self, "No Preset Selected", "Select a preset to delete.")
            return
        if QMessageBox.question(self, "Delete Preset", f"Delete preset '{name}'?") != QMessageBox.Yes:
            return
        self.global_presets.pop(name, None)
        if self.project_active_preset == name:
            self.project_active_preset = ""
        if self.global_active_preset == name:
            self.global_active_preset = ""
        self._persist_global_presets()
        self._mark_project_dirty()
        self.refresh_preset_list(select_name="")

    def import_presets(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Presets", str(self.project_results_dir() if self.active_project_slug else self.project_store.projects_dir), "JSON (*.json)")
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
        self.global_presets.update(imported)
        self._persist_global_presets()
        self._mark_project_dirty()
        self.refresh_preset_list(select_name=self.current_preset_name())
        QMessageBox.information(self, "Presets Imported", f"Imported {len(imported)} preset(s).")

    def export_presets(self) -> None:
        if not self.global_presets:
            QMessageBox.information(self, "No Presets", "There are no presets to export.")
            return
        base_dir = self.project_results_dir() if self.active_project_slug else self.project_store.projects_dir
        suggested = str((base_dir / "antenna_toolkit_presets.json").resolve())
        path, _ = QFileDialog.getSaveFileName(self, "Export Presets", suggested, "JSON (*.json)")
        if not path:
            return
        out_path = Path(path)
        if out_path.suffix.lower() != ".json":
            out_path = out_path.with_suffix(".json")
        out_path.write_text(json.dumps({"presets": self.global_presets}, indent=2), encoding="utf-8")
        QMessageBox.information(self, "Presets Exported", f"Exported {len(self.global_presets)} preset(s) to:\n{out_path}")

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
        self.ffs_toggle_button.setEnabled(has_project and selected)

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
            Path(SCRIPT_DATASHEET).name.lower(): "datasheet",
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

    def run_datasheet(self):
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        if not DATASHEET_TEMPLATE.exists():
            self.status("Datasheet.pdf is missing from the project root")
            return
        if self._missing_enabled_ffs():
            self.status("Remove or fix missing far-field files before generating the datasheet")
            return
        s2p = self.selected_s2p()
        if not s2p:
            self.status("Select a Touchstone file before generating the datasheet")
            return
        if not Path(s2p).exists():
            self.status("Selected Touchstone file is missing")
            return
        extract_output = self.deduced_extract_output()
        if not extract_output.exists():
            self.status("Generate the extract workbook first")
            return
        if self._stage_is_stale("extract"):
            self.status("Extract output is stale. Run Extract Data again before generating the datasheet")
            return
        if not self._stage_output_exists("plot"):
            self.status("Generate plots first so the datasheet can embed the chart assets")
            return
        if self._stage_is_stale("plot"):
            self.status("Plot output is stale. Run Plots only again before generating the datasheet")
            return
        args = [
            which_python(),
            "-u",
            SCRIPT_DATASHEET,
            str(self.deduced_datasheet_output()),
            "--template",
            str(DATASHEET_TEMPLATE),
            "--extract-workbook",
            str(extract_output),
        ]
        self._save_project_if_dirty()
        self._enqueue_stage("datasheet", args)

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
        if self.gain_legend_labels.text().strip():
            args += ["--gain-legend-labels", self.gain_legend_labels.text().strip()]
        if self.beamwidth_legend_labels.text().strip():
            args += ["--beamwidth-legend-labels", self.beamwidth_legend_labels.text().strip()]
        if self.beam_eff_legend_labels.text().strip():
            args += ["--beam-eff-legend-labels", self.beam_eff_legend_labels.text().strip()]
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
        if self.vswr_legend_labels.text().strip():
            args += ["--legend-labels", self.vswr_legend_labels.text().strip()]
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
        if not DATASHEET_TEMPLATE.exists():
            self.status("Datasheet.pdf is missing from the project root")
            return
        s2p = self.selected_s2p()
        if not s2p:
            self.status("Select a Touchstone file before running the full pipeline")
            return
        if not Path(s2p).exists():
            self.status("Selected Touchstone file is missing")
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
        if self.gain_legend_labels.text().strip():
            args_plot += ["--gain-legend-labels", self.gain_legend_labels.text().strip()]
        if self.beamwidth_legend_labels.text().strip():
            args_plot += ["--beamwidth-legend-labels", self.beamwidth_legend_labels.text().strip()]
        if self.beam_eff_legend_labels.text().strip():
            args_plot += ["--beam-eff-legend-labels", self.beam_eff_legend_labels.text().strip()]
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
        if args_extract:
            self._enqueue_stage(
                "datasheet",
                [
                    which_python(),
                    "-u",
                    SCRIPT_DATASHEET,
                    str(self.deduced_datasheet_output()),
                    "--template",
                    str(DATASHEET_TEMPLATE),
                    "--extract-workbook",
                    str(self.deduced_extract_output()),
                ],
            )

        args_vswr = [which_python(), "-u", SCRIPT_VSWR, s2p,
                "--output", str(self.deduced_vswr_output()),
                "--grid-color", self.plot_grid.color(),
                "--line-colors", ",".join([self.plot_line1.color(), self.plot_line2.color()]),
                "--x-step", str(self.shared_xstep.value()),
                "--ymin", str(self.vswr_ymin.value()),
                "--ymax", str(self.vswr_ymax.value()),
                "--y-step", str(self.vswr_ystep.value()),
                "--smooth-window", str(self.vswr_smooth.value())]
        if self.vswr_legend_labels.text().strip():
            args_vswr += ["--legend-labels", self.vswr_legend_labels.text().strip()]
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
            if hasattr(self, "help_window"):
                self.help_window._save_geometry()
        except Exception:
            pass

    def closeEvent(self, e):
        if not self._confirm_pending_project_changes("exiting"):
            e.ignore()
            return
        self._closing_app = True
        self.store.set("console_visible", bool(hasattr(self, "console_window") and self.console_window.isVisible()))
        self.store.set("help_visible", bool(hasattr(self, "help_window") and self.help_window.isVisible()))
        self._save_geometry()
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    win = ModernMainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
