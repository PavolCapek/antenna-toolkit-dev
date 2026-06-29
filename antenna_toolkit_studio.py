#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, QByteArray, Signal, QSize
from PySide6.QtGui import QColor, QPalette, QFont, QIcon, QPixmap
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

from studio_support import (
    THIS_DIR,
    suggest_preset_name, normalize_preset_payload, PresetFileStore, preset_storage_dir, legacy_preset_storage_dirs,
    DEFAULT_GRID_COLOR, DEFAULT_LINE_COLORS, DEFAULT_COLOR_OPTIONS, DEFAULT_BEAMWIDTH_DB_COLORS, Persist, Proc, resolve_state_file, app_state_dir, is_url,
    open_in_file_manager, resolve_workspace_path,
    SCRIPT_BEAM, SCRIPT_DATASHEET, SCRIPT_EXTRACT, SCRIPT_PLOT, SCRIPT_VSWR,
    display_workspace_path, deduce_project_name, normalized_project_stem,
)
from project_store import (
    CURRENT_PROJECT_SCHEMA_VERSION, ProjectRecord, ProjectStore, resolve_project_path,
    normalize_radiation_frequencies, sanitize_project_slug, serialize_workspace_path, utc_now_iso,
)
from legend_utils import detect_polarization
from pipeline.settings import (
    DEFAULT_DATASHEET_TEMPLATE_NAME,
    DEFAULT_PDF_METADATA_AUTHOR,
    PresetSettings,
    default_preset_settings,
)
from pipeline.stages import (
    stage_generated_directories,
    stage_is_applicable,
    stage_output_files,
    stage_settings_snapshot,
    stage_stale_detail,
    stage_tool_versions,
)
from studio_run import StudioRunMixin
from studio_runtime import (
    GoogleSheetDownloadError,
    STAGE_DEFINITIONS,
    STAGE_LABELS,
    clean_run_state,
    extract_google_sheet_id,
    format_timestamp,
    google_sheet_export_url,
    is_google_sheet_url,
)
from datasheet.technical_data import GoogleSheetTechnicalDataSource, LocalTechnicalDataSource, TechnicalDataError

APP_TITLE = "Antenna Toolkit Studio"
STATE_FILE = resolve_state_file(".nova_qt_studio_state.json", THIS_DIR / ".nova_qt_studio_state.json")
COMPACT_SCREEN_HEIGHT = 1200
COMPACT_WINDOW_WIDTH = 1360
PLOT_ASSET_STYLE_VERSION = 5
DATASHEET_RENDER_VERSION = 5
DATASHEET_TEMPLATE_DIR = THIS_DIR / "Templates"
LEGACY_DATASHEET_TEMPLATE_ALIASES = {
    "Datasheet.pdf": "Datasheet - RFE.pdf",
    "Datasheet Netqui.pdf": "Datasheet - Netqui.pdf",
    "Datasheet - Netqui - 1Pol - Placeholder.pdf": "Datasheet - Netqui - 1Pol.pdf",
}
GOOGLE_SHEETS_OAUTH_CLIENT_KEY = "google_sheets_oauth_client_json"
GOOGLE_SHEETS_TOKEN_FILENAME = "google_sheets_token.json"
GOOGLE_SHEETS_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FFS_FREQ_RE_FALLBACK = re.compile(r"(?i)freq[^0-9]*([0-9.eE+-]+)\s*([GMk]?Hz)?")
THEME_OPTIONS = [
    ("light", "Canvas"),
    ("dark", "Midnight"),
    ("graphite", "Graphite"),
    ("sage", "Sage"),
    ("sepia", "Sepia"),
]
THEME_LABELS = {key: label for key, label in THEME_OPTIONS}
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
        "state_saved_bg": "rgba(47,158,91,0.13)",
        "state_saved_border": "#84c89f",
        "state_saved_text": "#17633f",
        "state_unsaved_bg": "rgba(230,139,34,0.16)",
        "state_unsaved_border": "#e0a15a",
        "state_unsaved_text": "#8a4a00",
        "state_neutral_bg": "rgba(95,113,130,0.12)",
        "state_neutral_border": "#c2ccd6",
        "state_neutral_text": "#5f7182",
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
        "state_saved_bg": "rgba(74,194,120,0.18)",
        "state_saved_border": "#3f8f60",
        "state_saved_text": "#b8f0c8",
        "state_unsaved_bg": "rgba(245,166,35,0.20)",
        "state_unsaved_border": "#9a6a22",
        "state_unsaved_text": "#ffd28a",
        "state_neutral_bg": "rgba(159,178,194,0.12)",
        "state_neutral_border": "#425464",
        "state_neutral_text": "#b4c3cf",
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
        "state_saved_bg": "rgba(74,194,120,0.18)",
        "state_saved_border": "#4f9168",
        "state_saved_text": "#baf0cb",
        "state_unsaved_bg": "rgba(245,166,35,0.18)",
        "state_unsaved_border": "#9c722c",
        "state_unsaved_text": "#ffd58e",
        "state_neutral_bg": "rgba(165,175,187,0.12)",
        "state_neutral_border": "#4a5360",
        "state_neutral_text": "#b6c0cb",
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
        "state_saved_bg": "rgba(47,158,91,0.13)",
        "state_saved_border": "#82bf99",
        "state_saved_text": "#1e6240",
        "state_unsaved_bg": "rgba(215,129,31,0.15)",
        "state_unsaved_border": "#d59c56",
        "state_unsaved_text": "#804600",
        "state_neutral_bg": "rgba(101,124,116,0.12)",
        "state_neutral_border": "#c1d0c6",
        "state_neutral_text": "#657c74",
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
        "state_saved_bg": "rgba(47,158,91,0.12)",
        "state_saved_border": "#8ab986",
        "state_saved_text": "#28623b",
        "state_unsaved_bg": "rgba(214,125,28,0.16)",
        "state_unsaved_border": "#c9904d",
        "state_unsaved_text": "#7b4300",
        "state_neutral_bg": "rgba(122,105,88,0.12)",
        "state_neutral_border": "#d2bea5",
        "state_neutral_text": "#7a6958",
        "eyebrow_color": "#896038",
    },
}


def _unit_to_ghz(unit: str | None) -> float:
    key = str(unit or "").strip().lower()
    if key == "hz":
        return 1e-9
    if key == "khz":
        return 1e-6
    if key == "mhz":
        return 1e-3
    return 1.0


def _normalize_frequency_block_values(values: list[float]) -> list[float]:
    finite = [value for value in values if value > 0]
    if not finite:
        return []
    factor = 1e-9 if max(finite) > 1e6 else 1.0
    return sorted({round(value * factor, 6) for value in finite if value * factor > 0})


def _float_tokens(raw_line: str) -> list[float]:
    values: list[float] = []
    for token in raw_line.split():
        try:
            values.append(float(token))
        except ValueError:
            continue
    return values


def read_ffs_frequency_headers(path: str | Path) -> list[float]:
    def add_fallback_value(raw_line: str, values: list[float]) -> None:
        match = FFS_FREQ_RE_FALLBACK.search(raw_line)
        if not match:
            return
        try:
            values.append(float(match.group(1)) * _unit_to_ghz(match.group(2)))
        except ValueError:
            pass

    values_by_unit: list[float] = []
    try:
        with Path(path).open("r", encoding="utf-8", errors="ignore") as handle:
            iterator = iter(handle)
            for line in iterator:
                add_fallback_value(line, values_by_unit)
                if line.strip() != "// #Frequencies":
                    continue
                count_line = ""
                for count_line in iterator:
                    add_fallback_value(count_line, values_by_unit)
                    if count_line.strip():
                        break
                if not count_line:
                    continue
                try:
                    count = int(float(count_line.strip()))
                except ValueError:
                    continue
                for marker_line in iterator:
                    add_fallback_value(marker_line, values_by_unit)
                    if "Radiated/Accepted/Stimulated Power" in marker_line:
                        break
                else:
                    continue
                values: list[float] = []
                record: list[float] = []
                for raw in iterator:
                    if raw.lstrip().startswith("//") and record:
                        break
                    add_fallback_value(raw, values_by_unit)
                    tokens = _float_tokens(raw)
                    if not tokens:
                        if record:
                            values.append(record[-1])
                            record = []
                            if len(values) >= count:
                                break
                        continue
                    record.extend(tokens)
                    if len(record) >= 4:
                        values.append(record[-1])
                        record = []
                        if len(values) >= count:
                            break
                if record and len(values) < count:
                    values.append(record[-1])
                if values:
                    return _normalize_frequency_block_values(values)
    except OSError:
        return []
    return sorted({round(value, 6) for value in values_by_unit if value > 0})


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
    elif isinstance(widget, PolarLineStyleSelector):
        widget.color_selector.combo.setToolTip(text)
        widget.color_selector.prev_btn.setToolTip(text)
        widget.color_selector.next_btn.setToolTip(text)
        widget.color_selector.pick.setToolTip(text)
        widget.color_selector.swatch.setToolTip(text)
        widget.style_combo.setToolTip(text)


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
        ttl = QLabel(title)
        ttl.setObjectName("cardTitle")
        outer.addWidget(ttl)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body, 1)


class HoverDiffIndicator(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self._diff_items: list[str] = []
        self._popup = QFrame(None, Qt.ToolTip)
        self._popup.setObjectName("saveStateDiffPopup")
        self._popup.setFrameShape(QFrame.StyledPanel)
        self._popup_layout = QVBoxLayout(self._popup)
        self._popup_layout.setContentsMargins(10, 8, 10, 8)
        self._popup_layout.setSpacing(4)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(140)
        self._hide_timer.timeout.connect(self._hide_if_unhovered)

    def set_diff_items(self, items: list[str]) -> None:
        self._diff_items = [str(item) for item in items if str(item).strip()]
        if not self._diff_items:
            self._popup.hide()

    def diff_items(self) -> list[str]:
        return list(self._diff_items)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._hide_timer.stop()
        self._show_popup()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._hide_timer.start()

    def _show_popup(self) -> None:
        if not self._diff_items:
            return
        while self._popup_layout.count():
            item = self._popup_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for text in self._diff_items:
            row = QLabel(text)
            row.setObjectName("saveStateDiffItem")
            row.setWordWrap(True)
            row.setMaximumWidth(380)
            self._popup_layout.addWidget(row)
        self._popup.setStyleSheet(
            "QFrame#saveStateDiffPopup { background: #ffffff; color: #172033; "
            "border: 1px solid #b9c2d0; border-radius: 8px; } "
            "QLabel#saveStateDiffItem { background: transparent; padding: 1px 0; }"
        )
        self._popup.adjustSize()
        self._popup.move(self.mapToGlobal(self.rect().bottomLeft()))
        self._popup.show()

    def _hide_if_unhovered(self) -> None:
        if self.underMouse() or self._popup.underMouse():
            self._hide_timer.start()
            return
        self._popup.hide()


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


class ResponsiveInputsPanel(QWidget):
    def __init__(self, main_min_width: int = 520, side_width: int = 400):
        super().__init__()
        self.main_min_width = max(360, main_min_width)
        self.side_width = max(320, side_width)
        self._main: QWidget | None = None
        self._side: QWidget | None = None
        self._stacked: bool | None = None
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(12)

    def set_cards(self, main: QWidget, side: QWidget) -> None:
        self._main = main
        self._side = side
        self.refresh_layout(force=True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.refresh_layout()

    def _should_stack(self) -> bool:
        width = max(0, self.width())
        gap = max(0, self.grid.horizontalSpacing())
        return width < self.main_min_width + self.side_width + gap

    def refresh_layout(self, force: bool = False) -> None:
        if self._main is None or self._side is None:
            return
        stacked = self._should_stack()
        if not force and stacked == self._stacked:
            return
        self._stacked = stacked
        while self.grid.count():
            self.grid.takeAt(0)
        if stacked:
            self._side.setMaximumWidth(16777215)
            self.grid.setColumnStretch(0, 1)
            self.grid.setColumnStretch(1, 0)
            self.grid.setColumnMinimumWidth(1, 0)
            self.grid.addWidget(self._main, 0, 0)
            self.grid.addWidget(self._side, 1, 0)
            return
        self._side.setMaximumWidth(self.side_width)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 0)
        self.grid.setColumnMinimumWidth(1, self.side_width)
        self.grid.addWidget(self._main, 0, 0)
        self.grid.addWidget(self._side, 0, 1)


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
        self.presets = presets or DEFAULT_COLOR_OPTIONS
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
        self.combo.setIconSize(QSize(18, 18))
        self.setFocusProxy(self.combo)
        for name, value in self.presets:
            color = self._normalize(value, default)
            self.combo.addItem(self._color_icon(color), f"{name} ({color.upper()})", color)
        self.combo.addItem(self._color_icon(self.custom_color), f"Custom ({self.custom_color.upper()})", "__custom__")
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

    def _color_icon(self, value: str) -> QIcon:
        pixmap = QPixmap(18, 18)
        pixmap.fill(QColor(value))
        return QIcon(pixmap)

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
        custom_index = self.combo.count() - 1
        self.combo.setItemIcon(custom_index, self._color_icon(color))
        self.combo.setItemText(custom_index, f"Custom ({color.upper()})")
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


class PolarLineStyleSelector(QWidget):
    styleChanged = Signal()

    def __init__(
        self,
        store: Persist,
        color_key: str,
        style_key: str,
        default_color: str,
        default_style: str,
    ):
        super().__init__()
        self.store = store
        self.color_key = color_key
        self.style_key = style_key
        self.color_selector = StudioColorSelector(store, color_key, default_color)
        self.style_combo = NoWheelComboBox()
        self.style_combo.addItem("Solid", "solid")
        self.style_combo.addItem("Dashed", "dashed")
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        self.setFocusProxy(self.color_selector.combo)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self.color_selector, 1)
        lay.addWidget(self.style_combo)

        self.color_selector.colorChanged.connect(lambda _value: self.styleChanged.emit())
        self.set_style(str(store.get(style_key, default_style)), persist=False)

    def color(self) -> str:
        return self.color_selector.color()

    def set_color(self, value: str, persist: bool = True) -> None:
        self.color_selector.set_color(value, persist=persist)

    def style(self) -> str:
        return str(self.style_combo.currentData() or "solid")

    def set_style(self, value: str, persist: bool = True) -> None:
        normalized = "dashed" if str(value).strip().lower() in {"dashed", "dash", "--"} else "solid"
        index = self.style_combo.findData(normalized)
        self.style_combo.blockSignals(True)
        self.style_combo.setCurrentIndex(index if index >= 0 else 0)
        self.style_combo.blockSignals(False)
        if persist:
            self.store.set(self.style_key, normalized)
        self.styleChanged.emit()

    def _on_style_changed(self) -> None:
        self.store.set(self.style_key, self.style())
        self.styleChanged.emit()


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


class ModernMainWindow(StudioRunMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1460, 920)
        self.store = Persist(STATE_FILE)
        self.project_store = ProjectStore(THIS_DIR)
        self.proc = Proc(self)
        self._closing_app = False
        self._loading_project = False
        self._applying_preset_values = False
        self._suppress_ffs_item_change = False
        self._suppress_radiation_frequency_change = False
        self._project_radiation_frequencies: list[float] | None = None
        self._ffs_frequency_cache: dict[str, tuple[int, int, list[float]]] = {}
        self._refresh_cache: dict[str, object] = {}
        self._refresh_cache_enabled = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(75)
        self._refresh_timer.timeout.connect(self.refresh_derived_paths)
        self._run_cancelled = False
        self._current_stage_key = ""
        self._pending_stage_keys: list[str] = []
        self._live_run_total_stages = 0
        self._live_run_completed_stages = 0
        self._live_stage_progress_key = ""
        self._live_stage_progress_current = 0
        self._live_stage_progress_total = 0
        self._live_stage_progress_label = ""
        self._loaded_project_schema_version = CURRENT_PROJECT_SCHEMA_VERSION
        self._saved_project_signature = ""
        self._reverting_project_selection = False
        self._reverting_preset_selection = False
        self._suppress_project_selection_prompt = False
        self.active_project_slug = ""
        self.active_project_name = ""
        self.preset_store = PresetFileStore(preset_storage_dir(STATE_FILE), legacy_preset_storage_dirs(STATE_FILE))
        self.global_presets: dict[str, dict[str, object]] = self.preset_store.migrate_from_state(self.store)
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
        self._build_ui()
        self._apply_style()
        self._reset_to_default_state(clear_persisted_project=False)
        self.refresh_project_list(select_slug=str(self.store.get("active_project", "")).strip())
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
        run_help = QLabel("Use Full Pipeline for the usual workflow. Clear generated files without removing the project, or rerun individual stages from each stage row or the Project workspace menu.")
        run_help.setObjectName("helper")
        run_help.setWordWrap(True)
        self.run_help_label = run_help
        quick_actions.body.addWidget(run_help)
        self.btn_full = QPushButton("Run Full Pipeline")
        self.btn_full.setObjectName("primaryButton")
        self.btn_full.clicked.connect(self.run_full)
        self.btn_run_needed = QPushButton("Run Needed Only")
        self.btn_run_needed.setObjectName("ghostButton")
        self.btn_run_needed.clicked.connect(self.run_needed_outputs)
        self.btn_clear_outputs = QPushButton("Clear Generated Files")
        self.btn_clear_outputs.setObjectName("ghostButton")
        self.btn_clear_outputs.clicked.connect(self.delete_all_outputs)
        self.btn_cancel = QPushButton("Cancel Run")
        self.btn_cancel.setObjectName("ghostButton")
        self.btn_cancel.clicked.connect(self.cancel_run)
        self.btn_full.setToolTip("Run workbook generation, extract generation, plot generation, datasheet generation, and VSWR generation in sequence.")
        self.btn_run_needed.setToolTip("Run only the currently failed stage, or the outputs marked stale.")
        self.btn_clear_outputs.setToolTip("Delete generated output files for the active project while keeping the project file and settings.")
        self.btn_cancel.setToolTip("Stop the current run and clear any queued stages.")
        self.hero_actions = ResponsiveButtonPanel(max_columns=3, min_button_width=150)
        self.hero_actions.set_buttons([
            self.btn_full,
            self.btn_run_needed,
            self.btn_clear_outputs,
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
        self.busy = QProgressBar()
        self.busy.setVisible(False)
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        quick_actions.body.addWidget(self.pipeline_details_toggle)
        self.pipeline_details = QWidget()
        self.pipeline_details_layout = QVBoxLayout(self.pipeline_details)
        self.pipeline_details_layout.setContentsMargins(0, 0, 0, 0)
        self.pipeline_details_layout.setSpacing(8)
        self.stage_status_labels: dict[str, QLabel] = {}
        self.stage_timestamp_labels: dict[str, QLabel] = {}
        self.stage_chip_labels: dict[str, QLabel] = {}
        self.stage_open_buttons: dict[str, QPushButton] = {}
        self.stage_rerun_buttons: dict[str, QPushButton] = {}
        self.stage_more_buttons: dict[str, QPushButton] = {}
        self.stage_reveal_actions: dict[str, object] = {}
        self.stage_delete_actions: dict[str, object] = {}
        self.stage_rows = QWidget()
        self.stage_rows_layout = QVBoxLayout(self.stage_rows)
        self.stage_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.stage_rows_layout.setSpacing(0)
        for index, (stage_key, stage_label) in enumerate(STAGE_DEFINITIONS):
            if index:
                divider = QFrame()
                divider.setFrameShape(QFrame.HLine)
                divider.setFrameShadow(QFrame.Plain)
                divider.setObjectName("stageDivider")
                self.stage_rows_layout.addWidget(divider)
            row = QFrame()
            row.setObjectName("stageRow")
            row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 10, 0, 10)
            row_layout.setSpacing(10)
            info = QWidget()
            info_layout = QVBoxLayout(info)
            info_layout.setContentsMargins(0, 0, 0, 0)
            info_layout.setSpacing(2)
            name_label = QLabel(stage_label)
            name_label.setObjectName("stageTitle")
            status_label = QLabel("Waiting for the first run.")
            status_label.setObjectName("stageStatus")
            status_label.setWordWrap(True)
            timestamp_label = QLabel("Generated: not yet")
            timestamp_label.setObjectName("helper")
            timestamp_label.setWordWrap(True)
            info_layout.addWidget(name_label)
            info_layout.addWidget(status_label)
            info_layout.addWidget(timestamp_label)
            row_layout.addWidget(info, 1)
            chip_label = QLabel("Waiting")
            chip_label.setObjectName("stageChip")
            chip_label.setAlignment(Qt.AlignCenter)
            row_layout.addWidget(chip_label, 0, Qt.AlignVCenter)
            actions = QWidget()
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(0, 0, 0, 0)
            actions_layout.setSpacing(8)
            open_button = QPushButton("Open")
            open_button.setToolTip(f"Open the {stage_label.lower()} output.")
            open_button.clicked.connect(lambda _checked=False, key=stage_key: self.open_stage_output(key))
            rerun_button = QPushButton("Rerun")
            rerun_button.setToolTip(f"Run the {stage_label.lower()} stage again.")
            rerun_button.clicked.connect(lambda _checked=False, key=stage_key: self.rerun_stage(key))
            more_button = QPushButton("More")
            more_button.setToolTip(f"More actions for the {stage_label.lower()} output.")
            more_menu = QMenu(more_button)
            reveal_action = more_menu.addAction("Reveal in folder", lambda key=stage_key: self.reveal_stage_output(key))
            delete_action = more_menu.addAction("Delete output", lambda key=stage_key: self.delete_stage_output(key))
            more_button.setMenu(more_menu)
            actions_layout.addWidget(open_button)
            actions_layout.addWidget(rerun_button)
            actions_layout.addWidget(more_button)
            row_layout.addWidget(actions, 0, Qt.AlignVCenter)
            self.stage_rows_layout.addWidget(row)
            self.stage_status_labels[stage_key] = status_label
            self.stage_timestamp_labels[stage_key] = timestamp_label
            self.stage_chip_labels[stage_key] = chip_label
            self.stage_open_buttons[stage_key] = open_button
            self.stage_rerun_buttons[stage_key] = rerun_button
            self.stage_more_buttons[stage_key] = more_button
            self.stage_reveal_actions[stage_key] = reveal_action
            self.stage_delete_actions[stage_key] = delete_action
        self.pipeline_details_layout.addWidget(self.stage_rows)
        quick_actions.body.addWidget(self.pipeline_details)
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(10)
        progress_row.addWidget(self.busy, 1)
        self.btn_cancel.setVisible(False)
        progress_row.addWidget(self.btn_cancel, 0, Qt.AlignRight)
        quick_actions.body.addLayout(progress_row)
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
        self.project_run_needed_action = self.project_more_menu.addAction("Run failed/stale only", self.run_needed_outputs)
        self.project_validate_action = self.project_more_menu.addAction("Validate project", self.validate_project)
        self.project_more_menu.addSeparator()
        self.project_import_action = self.project_more_menu.addAction("Import bundle", self.import_project_bundle)
        self.project_export_action = self.project_more_menu.addAction("Export bundle", self.export_project_bundle)
        self.project_more_menu.addSeparator()
        self.project_delete_outputs_action = self.project_more_menu.addAction("Clear generated files", self.delete_all_outputs)
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
        self.project_save_state_indicator = HoverDiffIndicator("No project selected")
        self.project_save_state_indicator.setObjectName("saveStateIndicator")
        project_card.body.addWidget(self.project_save_state_indicator, 0, Qt.AlignLeft)

        command_left = QWidget()
        self.command_left = command_left
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
        self.btn_validate = QPushButton("Validate Project")
        self.btn_validate.setObjectName("ghostButton")
        self.btn_validate.clicked.connect(self.validate_project)
        self.btn_validate.setToolTip("Dry run stage validation and show a readiness report without running scripts.")
        readiness_action_row.addWidget(self.readiness_action, 0, Qt.AlignLeft)
        readiness_action_row.addWidget(self.btn_validate, 0, Qt.AlignLeft)
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
        document_scroll, _document_page, document_lay = self._make_scroll_page()
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
        self.preset_save_state_indicator = HoverDiffIndicator("No preset selected")
        self.preset_save_state_indicator.setObjectName("saveStateIndicator")
        preset_card.body.addWidget(self.preset_save_state_indicator, 0, Qt.AlignLeft)
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
        ffs_label_row = QHBoxLayout()
        ffs_label_row.setContentsMargins(0, 0, 0, 0)
        self.ffs_port_label_field = QLineEdit()
        self.ffs_port_label_field.setPlaceholderText("blank, H, V, Port 1, +45...")
        self.ffs_port_label_field.setToolTip("Legend label for the selected far-field file. Leave blank for no prefix on single-port plots.")
        self.ffs_port_label_field.setEnabled(False)
        self.ffs_port_label_field.textEdited.connect(self.update_selected_ffs_port_label)
        ffs_label_row.addWidget(QLabel("Selected port label"))
        ffs_label_row.addWidget(self.ffs_port_label_field, 1)
        ffs_card.body.addLayout(ffs_label_row)
        self.add_ffs_button = QPushButton("Add .ffs"); self.add_ffs_button.clicked.connect(self.add_ffs)
        self.remove_ffs_button = QPushButton("Remove selected"); self.remove_ffs_button.clicked.connect(self.remove_ffs)
        self.clear_ffs_button = QPushButton("Clear list"); self.clear_ffs_button.clicked.connect(self.clear_ffs)
        self.ffs_up_button = QPushButton("Move up"); self.ffs_up_button.clicked.connect(self.move_ffs_up)
        self.ffs_down_button = QPushButton("Move down"); self.ffs_down_button.clicked.connect(self.move_ffs_down)
        self.add_ffs_button.setToolTip("Browse for CST far-field export files to include in this project.")
        self.remove_ffs_button.setToolTip("Remove the highlighted far-field files from the current project.")
        self.clear_ffs_button.setToolTip("Clear the full far-field file list.")
        self.ffs_up_button.setToolTip("Move the selected far-field files up in the processing order.")
        self.ffs_down_button.setToolTip("Move the selected far-field files down in the processing order.")
        ffs_actions = ResponsiveButtonPanel(max_columns=3, min_button_width=135)
        self.ffs_actions = ffs_actions
        ffs_actions.set_buttons([
            self.add_ffs_button,
            self.remove_ffs_button,
            self.clear_ffs_button,
            self.ffs_up_button,
            self.ffs_down_button,
        ])
        ffs_card.body.addWidget(ffs_actions)

        radiation_card = Card("Radiation pattern frequencies", "Datasheet")
        self.radiation_frequency_card = radiation_card
        radiation_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        radiation_help = QLabel("Choose which available far-field frequencies are included in datasheet radiation pattern sections.")
        radiation_help.setWordWrap(True)
        radiation_help.setObjectName("helper")
        radiation_card.body.addWidget(radiation_help)
        self.radiation_frequency_list = QListWidget()
        self.radiation_frequency_list.setMinimumHeight(320)
        self.radiation_frequency_list.setToolTip("Checked frequencies are placed into the datasheet radiation pattern section for this project.")
        self.radiation_frequency_list.itemChanged.connect(self.on_radiation_frequency_item_changed)
        radiation_card.body.addWidget(self.radiation_frequency_list, 1)
        self.radiation_frequency_state_label = QLabel("Add far-field files to populate available frequencies.")
        self.radiation_frequency_state_label.setObjectName("helper")
        self.radiation_frequency_state_label.setWordWrap(True)
        radiation_card.body.addWidget(self.radiation_frequency_state_label)
        self.radiation_defaults_button = QPushButton("Defaults"); self.radiation_defaults_button.clicked.connect(self.select_default_radiation_frequencies)
        self.radiation_select_all_button = QPushButton("Select all"); self.radiation_select_all_button.clicked.connect(self.select_all_radiation_frequencies)
        self.radiation_clear_button = QPushButton("Clear"); self.radiation_clear_button.clicked.connect(self.clear_radiation_frequencies)
        radiation_actions = ResponsiveButtonPanel(max_columns=3, min_button_width=110)
        self.radiation_actions = radiation_actions
        radiation_actions.set_buttons([self.radiation_defaults_button, self.radiation_select_all_button, self.radiation_clear_button])
        radiation_card.body.addWidget(radiation_actions)

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

        technical_data_card = Card("Technical Data source", "Datasheet")
        technical_data_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.technical_data_field = QLineEdit("")
        self.technical_data_field.setReadOnly(True)
        self.technical_data_field.setToolTip("Technical Data workbook used to populate datasheet placeholders and the Technical Data table.")
        technical_data_card.body.addWidget(self.technical_data_field)
        self.select_technical_data_button = QPushButton("Select Technical Data"); self.select_technical_data_button.clicked.connect(self.browse_technical_data)
        self.google_sheet_technical_data_button = QPushButton("Use Google Sheet"); self.google_sheet_technical_data_button.clicked.connect(self.use_google_sheet_technical_data)
        self.google_credentials_button = QPushButton("Google Sign In"); self.google_credentials_button.clicked.connect(self.configure_google_sheet_credentials)
        self.open_technical_data_button = QPushButton("Open"); self.open_technical_data_button.clicked.connect(self.open_technical_data_source)
        self.select_technical_data_button.setToolTip("Choose the Excel workbook containing Antenna Name, Product ID, and Technical Data rows.")
        self.google_sheet_technical_data_button.setToolTip("Use a private Google Sheet as the Technical Data source. It will be downloaded as XLSX on each datasheet run.")
        self.google_credentials_button.setToolTip("Select OAuth client credentials and sign in to Google for private Sheet downloads.")
        self.open_technical_data_button.setToolTip("Open the selected Technical Data workbook or Google Sheet.")
        technical_data_actions = ResponsiveButtonPanel(max_columns=4, min_button_width=145)
        self.technical_data_actions = technical_data_actions
        technical_data_actions.set_buttons([
            self.select_technical_data_button,
            self.google_sheet_technical_data_button,
            self.google_credentials_button,
            self.open_technical_data_button,
        ])
        technical_data_card.body.addWidget(technical_data_actions)
        inputs_left = QWidget()
        inputs_left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        inputs_left_layout = QVBoxLayout(inputs_left)
        inputs_left_layout.setContentsMargins(0, 0, 0, 0)
        inputs_left_layout.setSpacing(12)
        inputs_left_layout.addWidget(s2p_card)
        inputs_left_layout.addWidget(technical_data_card)
        inputs_left_layout.addWidget(ffs_card)
        inputs_panel = ResponsiveInputsPanel(main_min_width=520, side_width=400)
        self.inputs_panel = inputs_panel
        inputs_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        inputs_panel.set_cards(inputs_left, radiation_card)
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

        self.plot_grid = StudioColorSelector(self.store, "grid_color", DEFAULT_GRID_COLOR)
        self.cartesian_grid_line_width = TrimmedDoubleSpinBox(); self.cartesian_grid_line_width.setRange(0.1, 10.0); self.cartesian_grid_line_width.setDecimals(2); self.cartesian_grid_line_width.setSingleStep(0.1); self.cartesian_grid_line_width.setValue(float(self.store.get("cartesian_grid_line_width", self.store.get("plot_grid_line_width", 0.9)))); self.cartesian_grid_line_width.valueChanged.connect(lambda v: self.store.set("cartesian_grid_line_width", float(v)))
        self.polar_grid_line_width = TrimmedDoubleSpinBox(); self.polar_grid_line_width.setRange(0.1, 10.0); self.polar_grid_line_width.setDecimals(2); self.polar_grid_line_width.setSingleStep(0.1); self.polar_grid_line_width.setValue(float(self.store.get("polar_grid_line_width", self.store.get("plot_grid_line_width", 0.9)))); self.polar_grid_line_width.valueChanged.connect(lambda v: self.store.set("polar_grid_line_width", float(v)))
        self.plot_line1 = StudioColorSelector(self.store, "plot_line_1", DEFAULT_LINE_COLORS[0][1])
        self.plot_line2 = StudioColorSelector(self.store, "plot_line_2", DEFAULT_LINE_COLORS[1][1])
        self.polar_azimuth_line1 = PolarLineStyleSelector(self.store, "polar_azimuth_line_1_color", "polar_azimuth_line_1_style", self.store.get("plot_line_1", DEFAULT_LINE_COLORS[0][1]), "solid")
        self.polar_azimuth_line2 = PolarLineStyleSelector(self.store, "polar_azimuth_line_2_color", "polar_azimuth_line_2_style", self.store.get("plot_line_2", DEFAULT_LINE_COLORS[1][1]), "solid")
        self.polar_elevation_line1 = PolarLineStyleSelector(self.store, "polar_elevation_line_1_color", "polar_elevation_line_1_style", self.store.get("plot_line_1", DEFAULT_LINE_COLORS[0][1]), "dashed")
        self.polar_elevation_line2 = PolarLineStyleSelector(self.store, "polar_elevation_line_2_color", "polar_elevation_line_2_style", self.store.get("plot_line_2", DEFAULT_LINE_COLORS[1][1]), "dashed")
        self.beamwidth_3db_color = StudioColorSelector(self.store, "beamwidth_3db_color", DEFAULT_BEAMWIDTH_DB_COLORS[0][1])
        self.beamwidth_6db_color = StudioColorSelector(self.store, "beamwidth_6db_color", DEFAULT_BEAMWIDTH_DB_COLORS[1][1])
        self.beamwidth_10db_color = StudioColorSelector(self.store, "beamwidth_10db_color", DEFAULT_BEAMWIDTH_DB_COLORS[2][1])
        self.cartesian_line_width = TrimmedDoubleSpinBox(); self.cartesian_line_width.setRange(0.1, 20.0); self.cartesian_line_width.setDecimals(2); self.cartesian_line_width.setSingleStep(0.1); self.cartesian_line_width.setValue(float(self.store.get("cartesian_line_width", self.store.get("plot_line_width", 2.0)))); self.cartesian_line_width.valueChanged.connect(lambda v: self.store.set("cartesian_line_width", float(v)))
        self.cartesian_figure_width = TrimmedDoubleSpinBox(); self.cartesian_figure_width.setRange(2.0, 24.0); self.cartesian_figure_width.setDecimals(2); self.cartesian_figure_width.setSingleStep(0.25); self.cartesian_figure_width.setValue(float(self.store.get("cartesian_figure_width", 12.0))); self.cartesian_figure_width.valueChanged.connect(lambda v: self.store.set("cartesian_figure_width", float(v)))
        self.cartesian_figure_height = TrimmedDoubleSpinBox(); self.cartesian_figure_height.setRange(1.0, 18.0); self.cartesian_figure_height.setDecimals(2); self.cartesian_figure_height.setSingleStep(0.25); self.cartesian_figure_height.setValue(float(self.store.get("cartesian_figure_height", 5.04))); self.cartesian_figure_height.valueChanged.connect(lambda v: self.store.set("cartesian_figure_height", float(v)))
        self.polar_figure_size = TrimmedDoubleSpinBox(); self.polar_figure_size.setRange(2.0, 24.0); self.polar_figure_size.setDecimals(2); self.polar_figure_size.setSingleStep(0.25); self.polar_figure_size.setValue(float(self.store.get("polar_figure_size", 9.0))); self.polar_figure_size.valueChanged.connect(lambda v: self.store.set("polar_figure_size", float(v)))
        self.polar_line_width = TrimmedDoubleSpinBox(); self.polar_line_width.setRange(0.1, 20.0); self.polar_line_width.setDecimals(2); self.polar_line_width.setSingleStep(0.1); self.polar_line_width.setValue(float(self.store.get("polar_line_width", self.store.get("plot_line_width", 2.0)))); self.polar_line_width.valueChanged.connect(lambda v: self.store.set("polar_line_width", float(v)))
        self.cartesian_font_size = TrimmedDoubleSpinBox(); self.cartesian_font_size.setRange(1.0, 72.0); self.cartesian_font_size.setDecimals(1); self.cartesian_font_size.setSingleStep(0.5); self.cartesian_font_size.setValue(float(self.store.get("cartesian_font_size", self.store.get("plot_font_size", 10.5)))); self.cartesian_font_size.valueChanged.connect(lambda v: self.store.set("cartesian_font_size", float(v)))
        self.polar_font_size = TrimmedDoubleSpinBox(); self.polar_font_size.setRange(1.0, 72.0); self.polar_font_size.setDecimals(1); self.polar_font_size.setSingleStep(0.5); self.polar_font_size.setValue(float(self.store.get("polar_font_size", self.store.get("plot_font_size", 10.5)))); self.polar_font_size.valueChanged.connect(lambda v: self.store.set("polar_font_size", float(v)))
        self.cartesian_legend_font_size = TrimmedDoubleSpinBox(); self.cartesian_legend_font_size.setRange(1.0, 72.0); self.cartesian_legend_font_size.setDecimals(1); self.cartesian_legend_font_size.setSingleStep(0.5); self.cartesian_legend_font_size.setValue(float(self.store.get("cartesian_legend_font_size", self.store.get("plot_legend_font_size", 10.5)))); self.cartesian_legend_font_size.valueChanged.connect(lambda v: self.store.set("cartesian_legend_font_size", float(v)))
        self.polar_legend_font_size = TrimmedDoubleSpinBox(); self.polar_legend_font_size.setRange(1.0, 72.0); self.polar_legend_font_size.setDecimals(1); self.polar_legend_font_size.setSingleStep(0.5); self.polar_legend_font_size.setValue(float(self.store.get("polar_legend_font_size", self.store.get("plot_legend_font_size", 10.5)))); self.polar_legend_font_size.valueChanged.connect(lambda v: self.store.set("polar_legend_font_size", float(v)))
        self.rings = QLineEdit(self.store.get("rings", "0,-7.5,-15,-22.5,-30")); self.rings.textChanged.connect(lambda v: self.store.set("rings", v))
        self.angle_step = NoWheelSpinBox(); self.angle_step.setRange(5, 90); self.angle_step.setSingleStep(5); self.angle_step.setValue(int(self.store.get("angle", 30))); self.angle_step.valueChanged.connect(lambda v: self.store.set("angle", int(v)))
        self.clip_db = TrimmedDoubleSpinBox(); self.clip_db.setRange(-120.0, 0.0); self.clip_db.setDecimals(6); self.clip_db.setSingleStep(0.5); self.clip_db.setValue(float(self.store.get("clip", -30.0))); self.clip_db.valueChanged.connect(lambda v: self.store.set("clip", float(v)))
        self.rings.setToolTip("Comma-separated dB ring values used on the polar plots.")
        plot_color_card = Card("Plot colors")
        plot_color_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        plot_color_card.setMinimumWidth(320)
        plot_color_form = QFormLayout()
        plot_color_form.setContentsMargins(0, 0, 0, 0)
        plot_color_form.setHorizontalSpacing(10)
        plot_color_form.setVerticalSpacing(8)
        plot_color_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        plot_color_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_form_row(plot_color_form, "Grid color", self.plot_grid, "Grid and axis color used across the cartesian, polar, and VSWR plots.")
        add_form_row(plot_color_form, "Line color 1", self.plot_line1, "Primary line color used across the cartesian, polar, and VSWR plots.")
        add_form_row(plot_color_form, "Line color 2", self.plot_line2, "Secondary line color used across the cartesian, polar, and VSWR plots.")
        add_form_row(plot_color_form, "3 dB", self.beamwidth_3db_color, "Line color used for 3 dB E-plane and H-plane beamwidth plots.")
        add_form_row(plot_color_form, "6 dB", self.beamwidth_6db_color, "Line color used for 6 dB E-plane and H-plane beamwidth plots.")
        add_form_row(plot_color_form, "10 dB", self.beamwidth_10db_color, "Line color used for 10 dB E-plane and H-plane beamwidth plots.")
        plot_color_card.body.addLayout(plot_color_form)

        polar_color_card = Card("Polar plot colors")
        polar_color_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        polar_color_card.setMinimumWidth(320)
        polar_color_form = QFormLayout()
        polar_color_form.setContentsMargins(0, 0, 0, 0)
        polar_color_form.setHorizontalSpacing(10)
        polar_color_form.setVerticalSpacing(8)
        polar_color_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        polar_color_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_form_row(polar_color_form, "Azimuth line 1", self.polar_azimuth_line1, "Color and style for the first azimuth polar trace.")
        add_form_row(polar_color_form, "Azimuth line 2", self.polar_azimuth_line2, "Color and style for the second azimuth polar trace.")
        add_form_row(polar_color_form, "Elevation line 1", self.polar_elevation_line1, "Color and style for the first elevation polar trace.")
        add_form_row(polar_color_form, "Elevation line 2", self.polar_elevation_line2, "Color and style for the second elevation polar trace.")
        polar_color_card.body.addLayout(polar_color_form)

        cartesian_metrics_card = Card("Cartesian styling")
        cartesian_metrics_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        cartesian_metrics_card.setMinimumWidth(320)
        cartesian_metrics_form = QFormLayout()
        cartesian_metrics_form.setContentsMargins(0, 0, 0, 0)
        cartesian_metrics_form.setHorizontalSpacing(10)
        cartesian_metrics_form.setVerticalSpacing(8)
        cartesian_metrics_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        cartesian_metrics_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_form_row(cartesian_metrics_form, "Grid width", StepperField(self.cartesian_grid_line_width), "Line width used by cartesian grid lines, axes, and tick marks.")
        add_form_row(cartesian_metrics_form, "Line width", StepperField(self.cartesian_line_width), "Trace thickness used by the workbook cartesian plots and the VSWR plot.")
        add_form_row(cartesian_metrics_form, "Figure width", StepperField(self.cartesian_figure_width), "Width used when rendering cartesian SVG plots.")
        add_form_row(cartesian_metrics_form, "Figure height", StepperField(self.cartesian_figure_height), "Height used when rendering cartesian SVG plots.")
        add_form_row(cartesian_metrics_form, "Font size", StepperField(self.cartesian_font_size), "Base font size used by cartesian plot labels and tick labels.")
        add_form_row(cartesian_metrics_form, "Legend font", StepperField(self.cartesian_legend_font_size), "Font size used by exported cartesian and VSWR legends.")
        cartesian_metrics_card.body.addLayout(cartesian_metrics_form)

        polar_metrics_card = Card("Polar styling")
        polar_metrics_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        polar_metrics_card.setMinimumWidth(320)
        polar_metrics_form = QFormLayout()
        polar_metrics_form.setContentsMargins(0, 0, 0, 0)
        polar_metrics_form.setHorizontalSpacing(10)
        polar_metrics_form.setVerticalSpacing(8)
        polar_metrics_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        polar_metrics_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_form_row(polar_metrics_form, "Grid width", StepperField(self.polar_grid_line_width), "Line width used by polar grid lines and tick marks.")
        add_form_row(polar_metrics_form, "Line width", StepperField(self.polar_line_width), "Trace thickness used by the polar plots.")
        add_form_row(polar_metrics_form, "Figure size", StepperField(self.polar_figure_size), "Size used when rendering square polar SVG plots.")
        add_form_row(polar_metrics_form, "Font size", StepperField(self.polar_font_size), "Base font size used by polar plot labels and tick labels.")
        add_form_row(polar_metrics_form, "Legend font", StepperField(self.polar_legend_font_size), "Font size used by exported polar legends.")
        add_form_row(polar_metrics_form, "Polar rings", self.rings, "Comma-separated dB ring values used on the polar plots.")
        add_form_row(polar_metrics_form, "Polar angle step", StepperField(self.angle_step), "Angle spacing, in degrees, for polar plot annotations.")
        add_form_row(polar_metrics_form, "Polar clip below", StepperField(self.clip_db), "Clip polar-plot values below this dB level to keep the chart readable.")
        polar_metrics_card.body.addLayout(polar_metrics_form)

        legend_card = Card("Legend labels")
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

        metadata_card = Card("PDF metadata", "Document")
        metadata_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        metadata_card.setMinimumWidth(320)
        self.datasheet_template_combo = QComboBox()
        self.datasheet_template_combo.setToolTip("PDF template used as the datasheet export style.")
        self.refresh_datasheet_template_options(str(self.store.get("datasheet_template", DEFAULT_DATASHEET_TEMPLATE_NAME)))
        self.datasheet_template_combo.currentIndexChanged.connect(self.on_datasheet_template_selected)
        self.pdf_metadata_author = QLineEdit(str(self.store.get("pdf_metadata_author", DEFAULT_PDF_METADATA_AUTHOR)))
        self.pdf_metadata_author.textChanged.connect(lambda v: self.store.set("pdf_metadata_author", v))
        metadata_form = QFormLayout()
        metadata_form.setContentsMargins(0, 0, 0, 0)
        metadata_form.setHorizontalSpacing(10)
        metadata_form.setVerticalSpacing(8)
        metadata_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        metadata_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_form_row(metadata_form, "Export style", self.datasheet_template_combo, "PDF template used as the datasheet export style.")
        add_form_row(metadata_form, "Author", self.pdf_metadata_author, "Author value written into the exported PDF metadata.")
        metadata_card.body.addLayout(metadata_form)

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
        colors_panel.set_cards([plot_color_card, polar_color_card, cartesian_metrics_card, polar_metrics_card])
        style_lay.addWidget(colors_panel, 1)

        style_lay.addWidget(legend_card, 1)
        style_lay.addStretch(1)

        document_lay.addWidget(metadata_card)
        document_lay.addStretch(1)

        self.workflow_tabs.addTab(inputs_scroll, "Inputs")
        self.workflow_tabs.addTab(processing_scroll, "Processing")
        self.workflow_tabs.addTab(style_scroll, "Style")
        self.workflow_tabs.addTab(document_scroll, "Document")
        self.workflow_tabs.addTab(run_scroll, "Run")
        self.workflow_tabs.setTabToolTip(0, "Far-field, Touchstone, and Technical Data inputs.")
        self.workflow_tabs.setTabToolTip(1, "Beam, workbook, VSWR, and axis-range controls.")
        self.workflow_tabs.setTabToolTip(2, "Plot colors, polar presentation, and legend labels.")
        self.workflow_tabs.setTabToolTip(3, "Document-wide fields used by exported files.")
        self.workflow_tabs.setTabToolTip(4, "Run the pipeline, inspect readiness, and manage generated artifacts.")
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

    def _show_document_tab(self) -> None:
        self._select_workflow_tab("Document")

    def _open_project_actions_menu(self) -> None:
        if self.project_more_button.isEnabled():
            self.project_more_button.showMenu()

    def _datasheet_template_label(self, filename: str) -> str:
        stem = Path(str(filename or "")).stem.strip()
        label = stem.replace("_", " ").replace("-", " ").strip()
        return " ".join(label.split()) or str(filename or "Template")

    def _datasheet_template_options(self) -> list[tuple[str, Path]]:
        templates: list[Path] = []
        if DATASHEET_TEMPLATE_DIR.exists():
            templates = sorted(
                (path for path in DATASHEET_TEMPLATE_DIR.glob("*.pdf") if path.is_file()),
                key=lambda path: path.stem.lower(),
            )
        return [(path.name, path.resolve()) for path in templates]

    def refresh_datasheet_template_options(self, select_name: str | None = None) -> None:
        if not hasattr(self, "datasheet_template_combo"):
            return
        current_name = str(select_name or self.selected_datasheet_template_name() or DEFAULT_DATASHEET_TEMPLATE_NAME)
        options = self._datasheet_template_options()
        option_names = {filename for filename, _path in options}
        current_name = LEGACY_DATASHEET_TEMPLATE_ALIASES.get(current_name, current_name)
        if current_name not in option_names:
            legacy_target = LEGACY_DATASHEET_TEMPLATE_ALIASES.get(current_name)
            if legacy_target in option_names:
                current_name = legacy_target
        self.datasheet_template_combo.blockSignals(True)
        self.datasheet_template_combo.clear()
        for filename, _path in options:
            self.datasheet_template_combo.addItem(self._datasheet_template_label(filename), filename)
        index = self.datasheet_template_combo.findData(current_name)
        if index < 0 and current_name:
            self.datasheet_template_combo.addItem(f"{self._datasheet_template_label(current_name)} (missing)", current_name)
            index = self.datasheet_template_combo.count() - 1
        elif index < 0 and self.datasheet_template_combo.count():
            index = 0
        if index >= 0:
            self.datasheet_template_combo.setCurrentIndex(index)
        self.datasheet_template_combo.blockSignals(False)

    def selected_datasheet_template_name(self) -> str:
        if not hasattr(self, "datasheet_template_combo"):
            return DEFAULT_DATASHEET_TEMPLATE_NAME
        value = self.datasheet_template_combo.currentData()
        return str(value or "").strip() or DEFAULT_DATASHEET_TEMPLATE_NAME

    def selected_datasheet_template_path(self) -> Path:
        selected_name = self.selected_datasheet_template_name()
        for filename, path in self._datasheet_template_options():
            if filename == selected_name:
                return path
        return (DATASHEET_TEMPLATE_DIR / selected_name).resolve()

    def on_datasheet_template_selected(self, *_args) -> None:
        self.store.set("datasheet_template", self.selected_datasheet_template_name())
        self._mark_project_dirty()
        self.refresh_radiation_frequency_list()

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
        self.readiness_action.setVisible(text not in {"Run Full Pipeline", "Open Inputs"})

    def _update_google_credentials_button_state(self) -> None:
        ready = self.google_sheets_auth_configured()
        if ready:
            self.google_credentials_button.setText("Google Sign In Ready")
            self.google_credentials_button.setToolTip("Google Sheets sign-in is configured. Select a new OAuth client JSON to sign in again.")
            self.google_credentials_button.setStyleSheet(
                "QPushButton { background: #e8f6ee; border-color: #2f9e5b; color: #1f7a45; font-weight: 700; }"
                "QPushButton:hover { background: #d8f0e3; border-color: #267f49; }"
                "QPushButton:disabled { background: #eef4f1; border-color: #9cc9ad; color: #6b9479; }"
            )
        else:
            self.google_credentials_button.setText("Google Sign In Needed")
            self.google_credentials_button.setToolTip("Select OAuth client credentials and sign in to Google for private Sheet downloads.")
            self.google_credentials_button.setStyleSheet(
                "QPushButton { background: #fdecec; border-color: #d64545; color: #9b2c2c; font-weight: 700; }"
                "QPushButton:hover { background: #fbdada; border-color: #b83232; }"
                "QPushButton:disabled { background: #f5eeee; border-color: #d9aaaa; color: #a98080; }"
            )

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
        self._clear_live_run_progress()
        self._loaded_project_schema_version = CURRENT_PROJECT_SCHEMA_VERSION
        self.ffs_list.clear()
        self.s2p_field.clear()
        self.technical_data_field.clear()
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
        self.cartesian_grid_line_width.setValue(0.9)
        self.polar_grid_line_width.setValue(0.9)
        self.cartesian_line_width.setValue(2.0)
        self.cartesian_figure_width.setValue(12.0)
        self.cartesian_figure_height.setValue(5.04)
        self.polar_figure_size.setValue(9.0)
        self.polar_line_width.setValue(2.0)
        self.cartesian_font_size.setValue(10.5)
        self.polar_font_size.setValue(10.5)
        self.cartesian_legend_font_size.setValue(10.5)
        self.polar_legend_font_size.setValue(10.5)
        self.plot_line1.set_color(DEFAULT_LINE_COLORS[0][1], persist=False)
        self.plot_line2.set_color(DEFAULT_LINE_COLORS[1][1], persist=False)
        self.polar_azimuth_line1.set_color(DEFAULT_LINE_COLORS[0][1], persist=False)
        self.polar_azimuth_line1.set_style("solid", persist=False)
        self.polar_azimuth_line2.set_color(DEFAULT_LINE_COLORS[1][1], persist=False)
        self.polar_azimuth_line2.set_style("solid", persist=False)
        self.polar_elevation_line1.set_color(DEFAULT_LINE_COLORS[0][1], persist=False)
        self.polar_elevation_line1.set_style("dashed", persist=False)
        self.polar_elevation_line2.set_color(DEFAULT_LINE_COLORS[1][1], persist=False)
        self.polar_elevation_line2.set_style("dashed", persist=False)
        self.beamwidth_3db_color.set_color(DEFAULT_BEAMWIDTH_DB_COLORS[0][1], persist=False)
        self.beamwidth_6db_color.set_color(DEFAULT_BEAMWIDTH_DB_COLORS[1][1], persist=False)
        self.beamwidth_10db_color.set_color(DEFAULT_BEAMWIDTH_DB_COLORS[2][1], persist=False)
        self.gain_legend_labels.clear()
        self.beamwidth_legend_labels.clear()
        self.beam_eff_legend_labels.clear()
        self.vswr_legend_labels.clear()
        self.refresh_datasheet_template_options(DEFAULT_DATASHEET_TEMPLATE_NAME)
        self.store.set("datasheet_template", self.selected_datasheet_template_name())
        self.pdf_metadata_author.setText(DEFAULT_PDF_METADATA_AUTHOR)
        self.rings.setText("0,-7.5,-15,-22.5,-30")
        self.angle_step.setValue(30)
        self.clip_db.setValue(-30.0)
        if self.global_active_preset in self.global_presets:
            self.apply_preset_values(self.global_presets.get(self.global_active_preset, {}))
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
        return default_preset_settings()

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

    def _saved_project_dict(self) -> dict[str, Any]:
        try:
            payload = json.loads(self._saved_project_signature or "{}")
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _active_preset_for_dirty_check(self) -> str:
        return str(self.project_active_preset or self.global_active_preset or self.current_preset_name()).strip()

    def _normalized_preset_values(self, values: dict[str, object] | None) -> dict[str, object]:
        coerced = PresetSettings.from_mapping(values if isinstance(values, dict) else {}).to_dict()
        for key in list(coerced):
            if key.endswith("_color") or key.startswith("plot_line_") or key == "grid_color":
                coerced[key] = str(coerced[key]).strip().upper()
        return coerced

    def has_unsaved_preset_changes(self) -> bool:
        if self._loading_project:
            return False
        name = self._active_preset_for_dirty_check()
        if not name:
            return False
        preset = self.global_presets.get(name)
        return isinstance(preset, dict) and self._normalized_preset_values(preset) != self._normalized_preset_values(self.collect_preset_values())

    def _limited_diff_items(self, items: list[str], limit: int = 12) -> list[str]:
        if len(items) <= limit:
            return items
        return items[:limit] + [f"{len(items) - limit} more changes..."]

    def _display_diff_value(self, value: Any) -> str:
        if value in (None, ""):
            return "empty"
        if isinstance(value, bool):
            return "on" if value else "off"
        if isinstance(value, float):
            return f"{value:g}"
        if isinstance(value, list):
            if not value:
                return "none"
            return ", ".join(self._display_diff_value(item) for item in value[:4]) + ("..." if len(value) > 4 else "")
        if isinstance(value, dict):
            return f"{len(value)} value(s)"
        text = str(value).strip()
        if any(sep in text for sep in ("\\", "/")):
            text = display_workspace_path(text)
        return text if len(text) <= 72 else f"{text[:69]}..."

    def _diff_change_text(self, label: str, before: Any, after: Any) -> str:
        return f"{label}: {self._display_diff_value(before)} -> {self._display_diff_value(after)}"

    def _preset_field_label(self, key: str) -> str:
        labels = {
            "smooth": "Beam smoothing",
            "theta": "Theta window",
            "smooth2": "Plot smoothing",
            "shared_xstep": "Shared X step",
            "shared_fmin": "Shared frequency minimum",
            "shared_fmax": "Shared frequency maximum",
            "shared_xlog": "Shared logarithmic X axis",
            "gain_ymin": "Gain Y minimum",
            "gain_ymax": "Gain Y maximum",
            "gain_y_step": "Gain Y step",
            "beamwidth_ymin": "Beamwidth Y minimum",
            "beamwidth_ymax": "Beamwidth Y maximum",
            "beamwidth_y_step": "Beamwidth Y step",
            "beam_eff_ymin": "Beam efficiency Y minimum",
            "beam_eff_ymax": "Beam efficiency Y maximum",
            "beam_eff_y_step": "Beam efficiency Y step",
            "vswr_ymin": "VSWR Y minimum",
            "vswr_ymax": "VSWR Y maximum",
            "vswr_ystep": "VSWR Y step",
            "vswr_smooth": "VSWR smoothing",
            "grid_color": "Grid color",
            "cartesian_grid_line_width": "Cartesian grid width",
            "polar_grid_line_width": "Polar grid width",
            "cartesian_line_width": "Cartesian line width",
            "cartesian_figure_width": "Cartesian figure width",
            "cartesian_figure_height": "Cartesian figure height",
            "polar_figure_size": "Polar figure size",
            "polar_line_width": "Polar line width",
            "cartesian_font_size": "Cartesian font size",
            "polar_font_size": "Polar font size",
            "cartesian_legend_font_size": "Cartesian legend font size",
            "polar_legend_font_size": "Polar legend font size",
            "plot_line_1": "Plot line 1 color",
            "plot_line_2": "Plot line 2 color",
            "polar_azimuth_line_1_color": "Azimuth line 1 color",
            "polar_azimuth_line_1_style": "Azimuth line 1 style",
            "polar_azimuth_line_2_color": "Azimuth line 2 color",
            "polar_azimuth_line_2_style": "Azimuth line 2 style",
            "polar_elevation_line_1_color": "Elevation line 1 color",
            "polar_elevation_line_1_style": "Elevation line 1 style",
            "polar_elevation_line_2_color": "Elevation line 2 color",
            "polar_elevation_line_2_style": "Elevation line 2 style",
            "beamwidth_3db_color": "3 dB beamwidth color",
            "beamwidth_6db_color": "6 dB beamwidth color",
            "beamwidth_10db_color": "10 dB beamwidth color",
            "gain_legend_labels": "Gain legend labels",
            "beamwidth_legend_labels": "Beamwidth legend labels",
            "beam_eff_legend_labels": "Beam efficiency legend labels",
            "vswr_legend_labels": "VSWR legend labels",
            "datasheet_template": "Datasheet template",
            "pdf_metadata_author": "PDF metadata author",
            "rings": "Polar rings",
            "angle": "Polar angle step",
            "clip": "Polar clip",
        }
        return labels.get(key, key.replace("_", " ").title())

    def _preset_diff_items(self, before: dict[str, Any] | None = None, after: dict[str, Any] | None = None) -> list[str]:
        old_values = self._normalized_preset_values(before if isinstance(before, dict) else {})
        new_values = self._normalized_preset_values(after if isinstance(after, dict) else self.collect_preset_values())
        items: list[str] = []
        for key in sorted(set(old_values) | set(new_values), key=self._preset_field_label):
            if old_values.get(key) != new_values.get(key):
                items.append(self._diff_change_text(self._preset_field_label(key), old_values.get(key), new_values.get(key)))
        return self._limited_diff_items(items)

    def _project_diff_items(self) -> list[str]:
        if not self.active_project_slug:
            return []
        before = self._saved_project_dict()
        project = self.current_project()
        after = project.to_dict() if project else {}
        if not before or not after:
            return []
        items: list[str] = []
        old_ffs = before.get("ffs_items", []) if isinstance(before.get("ffs_items"), list) else []
        new_ffs = after.get("ffs_items", []) if isinstance(after.get("ffs_items"), list) else []
        old_by_path = {str(item.get("path", "")).strip(): item for item in old_ffs if isinstance(item, dict) and str(item.get("path", "")).strip()}
        new_by_path = {str(item.get("path", "")).strip(): item for item in new_ffs if isinstance(item, dict) and str(item.get("path", "")).strip()}
        old_paths = list(old_by_path)
        new_paths = list(new_by_path)
        for path in new_paths:
            if path not in old_by_path:
                items.append(f"Far-field file added: {self._display_diff_value(path)}")
        for path in old_paths:
            if path not in new_by_path:
                items.append(f"Far-field file removed: {self._display_diff_value(path)}")
        if old_paths != new_paths and set(old_paths) == set(new_paths):
            items.append("Far-field file order changed")
        for path in [path for path in new_paths if path in old_by_path]:
            old_item = old_by_path[path]
            new_item = new_by_path[path]
            if bool(old_item.get("enabled", True)) != bool(new_item.get("enabled", True)):
                items.append(self._diff_change_text(f"Far-field enabled ({self._display_diff_value(path)})", bool(old_item.get("enabled", True)), bool(new_item.get("enabled", True))))
            if str(old_item.get("port_label", "")).strip() != str(new_item.get("port_label", "")).strip():
                items.append(self._diff_change_text(f"Port label ({self._display_diff_value(path)})", old_item.get("port_label", ""), new_item.get("port_label", "")))
        for key, label in (
            ("touchstone_file", "Touchstone file"),
            ("technical_data_file", "Technical Data source"),
            ("active_preset", "Active preset"),
            ("radiation_pattern_frequencies_ghz", "Radiation frequencies"),
        ):
            if before.get(key) != after.get(key):
                items.append(self._diff_change_text(label, before.get(key), after.get(key)))
        if before.get("settings", {}) != after.get("settings", {}):
            items.extend(self._preset_diff_items(before.get("settings", {}), after.get("settings", {})))
        if before.get("run_state", {}) != after.get("run_state", {}):
            items.append("Run metadata changed")
        return self._limited_diff_items(items)

    def _current_preset_diff_items(self) -> list[str]:
        name = self._active_preset_for_dirty_check()
        preset = self.global_presets.get(name)
        if not name or not isinstance(preset, dict):
            return []
        return self._preset_diff_items(preset, self.collect_preset_values())

    def _mark_project_dirty(self) -> None:
        if self._loading_project or not self.active_project_slug:
            return
        self.refresh_derived_paths()

    def request_derived_paths_refresh(self) -> None:
        if self._loading_project:
            return
        self._refresh_timer.start()

    def flush_derived_paths_refresh(self) -> None:
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()
        self.refresh_derived_paths()

    def _save_active_preset(self, *, refresh: bool = False) -> bool:
        name = self._active_preset_for_dirty_check()
        if not name or name not in self.global_presets:
            return False
        self.global_presets[name] = self.collect_preset_values()
        self.project_active_preset = name
        self.global_active_preset = name
        self._persist_global_presets()
        if refresh:
            self.refresh_preset_list(select_name=name)
        else:
            self.refresh_derived_paths()
        return True

    def _confirm_pending_preset_changes(self, action: str) -> bool:
        if not self.has_unsaved_preset_changes():
            return True
        name = self._active_preset_for_dirty_check()
        answer = QMessageBox.question(
            self,
            "Unsaved Preset Changes",
            f"Preset '{name}' has unsaved changes. Save before {action}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            self._save_active_preset(refresh=False)
        return True

    def _confirm_pending_project_changes(self, action: str) -> bool:
        if not self.has_unsaved_project_changes():
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved Project Changes",
            f"The current project has unsaved changes. Save before {action}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            self.save_active_project()
        return True

    def _confirm_pending_changes(self, action: str, *, include_preset: bool = True, include_project: bool = True) -> bool:
        if include_preset and not self._confirm_pending_preset_changes(action):
            return False
        if include_project and not self._confirm_pending_project_changes(action):
            return False
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
                "command_panel_min_card_width": 320,
                "command_left_max_width": 340,
                "readiness_panel_min_card_width": 150,
                "inputs_main_min_width": 460,
                "inputs_side_width": 360,
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
            "command_panel_min_card_width": 360,
            "command_left_max_width": 390,
            "readiness_panel_min_card_width": 170,
            "inputs_main_min_width": 520,
            "inputs_side_width": 400,
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
            "tab_min_width": 110,
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
            (self.processing_panel, int(metrics["processing_panel_min_card_width"])),
            (self.ranges_panel, int(metrics["ranges_panel_min_card_width"])),
            (self.colors_panel, int(metrics["colors_panel_min_card_width"])),
        ):
            panel.min_card_width = min_width
            panel.grid.setHorizontalSpacing(panel_gap)
            panel.grid.setVerticalSpacing(panel_gap)
            panel.refresh_layout(force=True)
        self.inputs_panel.main_min_width = int(metrics["inputs_main_min_width"])
        self.inputs_panel.side_width = int(metrics["inputs_side_width"])
        self.inputs_panel.grid.setHorizontalSpacing(panel_gap)
        self.inputs_panel.grid.setVerticalSpacing(panel_gap)
        self.inputs_panel.refresh_layout(force=True)
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
        self.command_left.setMaximumWidth(int(metrics["command_left_max_width"]))
        compact = self._compact_layout
        self.brand_subtitle.setVisible(not compact)
        self.run_help_label.setVisible(not compact)
        self.project_help_label.setVisible(not compact)
        self.preset_help_label.setVisible(not compact)
        self.ffs_help_label.setVisible(not compact)
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
                #stageTitle { color: %(title_color)s; font-size: %(helper_size)gpt; font-weight: 700; }
                #stageStatus { color: %(text_color)s; font-size: %(helper_size)gpt; font-weight: 600; }
                #stageChip { border-radius: 12px; padding: 4px 10px; font-size: %(badge_font_size)gpt; font-weight: 700; min-width: 74px; }
                #stageDivider { color: %(card_border)s; background: %(card_border)s; min-height: 1px; max-height: 1px; border: none; }
                QTabWidget::pane { border: none; background: transparent; margin-top: %(tab_margin_top)spx; }
                QTabBar::tab { background: %(tab_bg)s; border: 1px solid %(shell_border)s; border-bottom: none; border-top-left-radius: 14px; border-top-right-radius: 14px; padding: %(tab_padding_v)spx %(tab_padding_h)spx; margin-right: 6px; min-width: %(tab_min_width)spx; color: %(helper_color)s; font-weight: 700; }
                QTabBar::tab:hover { background: %(tab_hover)s; color: %(title_color)s; }
                QTabBar::tab:selected { background: %(tab_selected)s; color: %(primary_bg)s; font-weight: 800; }
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

    def _set_save_state_indicator(self, label: QLabel, text: str, state: str) -> None:
        theme = THEME_STYLES.get(self.theme, THEME_STYLES["light"])
        key = state if state in {"saved", "unsaved", "neutral"} else "neutral"
        label.setText(text)
        if isinstance(label, HoverDiffIndicator):
            label.set_diff_items([])
        label.setStyleSheet(
            "QLabel#saveStateIndicator { "
            f"background: {theme[f'state_{key}_bg']}; "
            f"color: {theme[f'state_{key}_text']}; "
            f"border: 1px solid {theme[f'state_{key}_border']}; "
            "border-radius: 12px; "
            "padding: 5px 10px; "
            "font-weight: 700; "
            "}"
        )

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
        self._refresh_stage_labels()
        self.refresh_derived_paths()
        self._update_preset_action_state()

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
            self.cartesian_grid_line_width.valueChanged,
            self.polar_grid_line_width.valueChanged,
            self.cartesian_line_width.valueChanged,
            self.cartesian_figure_width.valueChanged,
            self.cartesian_figure_height.valueChanged,
            self.polar_figure_size.valueChanged,
            self.polar_line_width.valueChanged,
            self.cartesian_font_size.valueChanged,
            self.polar_font_size.valueChanged,
            self.cartesian_legend_font_size.valueChanged,
            self.polar_legend_font_size.valueChanged,
            self.plot_line1.colorChanged,
            self.plot_line2.colorChanged,
            self.polar_azimuth_line1.styleChanged,
            self.polar_azimuth_line2.styleChanged,
            self.polar_elevation_line1.styleChanged,
            self.polar_elevation_line2.styleChanged,
            self.beamwidth_3db_color.colorChanged,
            self.beamwidth_6db_color.colorChanged,
            self.beamwidth_10db_color.colorChanged,
            self.gain_legend_labels.textChanged,
            self.beamwidth_legend_labels.textChanged,
            self.beam_eff_legend_labels.textChanged,
            self.vswr_legend_labels.textChanged,
            self.datasheet_template_combo.currentIndexChanged,
            self.pdf_metadata_author.textChanged,
            self.rings.textChanged,
            self.angle_step.valueChanged,
            self.clip_db.valueChanged,
        ]
        for signal in tracked_signals:
            signal.connect(self.on_project_configuration_changed)

    def on_project_configuration_changed(self, *_args) -> None:
        if self._loading_project or self._applying_preset_values:
            return
        if self._active_preset_for_dirty_check():
            self.request_derived_paths_refresh()
            return
        if self.active_project_slug:
            self.request_derived_paths_refresh()

    def collect_ffs_items(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for i in range(self.ffs_list.count()):
            item = self.ffs_list.item(i)
            items.append({
                "path": self._item_path(item),
                "enabled": item.checkState() == Qt.Checked,
                "port_label": self._item_port_label(item),
            })
        return items

    def selected_radiation_frequencies(self) -> list[float]:
        if not hasattr(self, "radiation_frequency_list"):
            return []
        values: list[float] = []
        for index in range(self.radiation_frequency_list.count()):
            item = self.radiation_frequency_list.item(index)
            if item.checkState() != Qt.Checked:
                continue
            try:
                values.append(round(float(item.data(Qt.UserRole)), 6))
            except (TypeError, ValueError):
                continue
        return sorted(set(values))

    def radiation_frequencies_arg(self) -> str | None:
        if self._project_radiation_frequencies is None:
            return None
        return ",".join(f"{value:.6f}".rstrip("0").rstrip(".") for value in self.selected_radiation_frequencies())

    def _selected_radiation_set(self) -> set[float]:
        stored = normalize_radiation_frequencies(self._project_radiation_frequencies)
        if stored is not None:
            return set(stored)
        return set(self._default_radiation_frequencies())

    def _available_radiation_frequencies(self) -> list[float]:
        frequencies: set[float] = set()
        for path in self.selected_ffs():
            frequencies.update(self._cached_ffs_frequency_headers(path))
        if frequencies:
            return sorted(frequencies)
        manifest_path = self.project_results_dir() / f"{self.deduced_beam_output().stem}-artifacts.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        charts = manifest.get("charts", {}) if isinstance(manifest, dict) else {}
        if not isinstance(charts, dict):
            return []
        for key in ("polar_combined_planes", "polar_combined", "polar_single"):
            records = charts.get(key)
            if not isinstance(records, list):
                continue
            for record in records:
                if not isinstance(record, dict):
                    continue
                try:
                    value = round(float(record.get("frequency_ghz")), 6)
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    frequencies.add(value)
        return sorted(frequencies)

    def _cached_ffs_frequency_headers(self, path: str | Path) -> list[float]:
        resolved = resolve_workspace_path(path)
        cache_key = str(resolved)
        try:
            stat = resolved.stat()
        except OSError:
            self._ffs_frequency_cache.pop(cache_key, None)
            return []
        signature = (int(stat.st_mtime_ns), int(stat.st_size))
        cached = self._ffs_frequency_cache.get(cache_key)
        if cached and cached[:2] == signature:
            return list(cached[2])
        values = read_ffs_frequency_headers(resolved)
        self._ffs_frequency_cache[cache_key] = (signature[0], signature[1], list(values))
        return values

    def _closest_available_frequencies(self, targets: list[float], count: int) -> list[float]:
        available = self._available_radiation_frequencies()
        if not available or count <= 0:
            return []
        selected: list[float] = []
        for target in targets:
            remaining = [value for value in available if value not in selected]
            if not remaining:
                break
            selected.append(min(remaining, key=lambda value: (abs(value - target), value)))
        return selected[:count]

    def _default_radiation_frequencies(self) -> list[float]:
        available = self._available_radiation_frequencies()
        if not available:
            return []
        template_name = self.selected_datasheet_template_name().lower() if hasattr(self, "datasheet_template_combo") else ""
        if "netqui" in template_name and "1pol" in template_name:
            count = min(6, len(available))
        else:
            count = 1
        if count == 1:
            targets = [(available[0] + available[-1]) / 2.0]
        else:
            step = (available[-1] - available[0]) / float(count - 1)
            targets = [available[0] + step * index for index in range(count)]
        return self._closest_available_frequencies(targets, count)

    def refresh_radiation_frequency_list(self) -> None:
        if not hasattr(self, "radiation_frequency_list"):
            return
        available = self._available_radiation_frequencies() if self.active_project_slug else []
        selected = self._selected_radiation_set()
        self._suppress_radiation_frequency_change = True
        self.radiation_frequency_list.clear()
        for value in available:
            item = QListWidgetItem(f"{value:g} GHz")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            item.setData(Qt.UserRole, value)
            item.setCheckState(Qt.Checked if value in selected else Qt.Unchecked)
            self.radiation_frequency_list.addItem(item)
        self._suppress_radiation_frequency_change = False
        has_project = bool(self.active_project_slug)
        has_available = bool(available)
        self.radiation_frequency_list.setEnabled(has_project and has_available)
        self.radiation_defaults_button.setEnabled(has_project and has_available)
        self.radiation_select_all_button.setEnabled(has_project and has_available)
        self.radiation_clear_button.setEnabled(has_project and has_available)
        self._update_radiation_frequency_state_label(has_project=has_project, available_count=len(available))

    def _update_radiation_frequency_state_label(self, *, has_project: bool | None = None, available_count: int | None = None) -> None:
        if not hasattr(self, "radiation_frequency_state_label"):
            return
        has_project = bool(self.active_project_slug) if has_project is None else has_project
        available_count = self.radiation_frequency_list.count() if available_count is None else available_count
        if not has_project:
            self.radiation_frequency_state_label.setText("Create or select a project first.")
        elif available_count <= 0:
            self.radiation_frequency_state_label.setText("No radiation frequencies found in enabled far-field files yet.")
        else:
            checked = len(self.selected_radiation_frequencies())
            self.radiation_frequency_state_label.setText(f"{checked}/{available_count} frequencies selected for datasheets.")

    def _set_radiation_frequency_selection(self, values: list[float]) -> None:
        selected = set(normalize_radiation_frequencies(values) or [])
        self._suppress_radiation_frequency_change = True
        for index in range(self.radiation_frequency_list.count()):
            item = self.radiation_frequency_list.item(index)
            try:
                value = round(float(item.data(Qt.UserRole)), 6)
            except (TypeError, ValueError):
                value = 0.0
            item.setCheckState(Qt.Checked if value in selected else Qt.Unchecked)
        self._suppress_radiation_frequency_change = False
        self._project_radiation_frequencies = sorted(selected)
        self._update_radiation_frequency_state_label()
        self._mark_project_dirty()

    def on_radiation_frequency_item_changed(self, _item: QListWidgetItem) -> None:
        if self._loading_project or self._suppress_radiation_frequency_change:
            return
        self._project_radiation_frequencies = self.selected_radiation_frequencies()
        self._update_radiation_frequency_state_label()
        self._mark_project_dirty()

    def select_default_radiation_frequencies(self) -> None:
        self._set_radiation_frequency_selection(self._default_radiation_frequencies())

    def select_all_radiation_frequencies(self) -> None:
        self._set_radiation_frequency_selection(self._available_radiation_frequencies())

    def clear_radiation_frequencies(self) -> None:
        self._set_radiation_frequency_selection([])

    def _selected_ffs_paths(self) -> list[str]:
        return [self._item_path(item) for item in self.ffs_list.selectedItems()]

    def _enabled_ffs_count(self) -> int:
        return sum(1 for item in self.collect_ffs_items() if bool(item["enabled"]))

    def _cache_get(self, key: str) -> object | None:
        if not self._refresh_cache_enabled:
            return None
        return self._refresh_cache.get(key)

    def _cache_set(self, key: str, value: object) -> object:
        if self._refresh_cache_enabled:
            self._refresh_cache[key] = value
        return value

    def _cached_path_exists(self, path: str | Path) -> bool:
        cache_key = f"exists:{Path(path)}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return bool(cached)
        return bool(self._cache_set(cache_key, Path(path).exists()))

    def _cached_project_file_count(self) -> int:
        project_dir = self.project_results_dir()
        cache_key = f"file_count:{project_dir}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return int(cached)
        count = sum(1 for path in project_dir.rglob("*") if path.is_file()) if project_dir.exists() else 0
        return int(self._cache_set(cache_key, count))

    def _path_fingerprint(self, path: str | Path | None) -> dict[str, object]:
        if is_url(path):
            return {
                "path": str(path).strip(),
                "exists": True,
                "type": "url",
            }
        resolved = Path(resolve_workspace_path(path)) if path else Path()
        cache_key = f"fingerprint:{resolved}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return dict(cached)
        exists = bool(path) and self._cached_path_exists(resolved)
        payload: dict[str, object] = {
            "path": serialize_workspace_path(THIS_DIR, resolved) if path else "",
            "exists": exists,
        }
        if exists:
            stat = resolved.stat()
            payload["mtime_ns"] = int(stat.st_mtime_ns)
            payload["size"] = int(stat.st_size)
        self._cache_set(cache_key, dict(payload))
        return payload

    def _stage_settings_snapshot(self, stage_key: str) -> dict[str, object]:
        return stage_settings_snapshot(stage_key, self.collect_preset_values())

    def _stage_tool_versions(self, stage_key: str) -> dict[str, int]:
        return stage_tool_versions(
            stage_key,
            plot_asset_style_version=PLOT_ASSET_STYLE_VERSION,
            datasheet_render_version=DATASHEET_RENDER_VERSION,
        )

    def _current_stage_snapshot(self, stage_key: str) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "schema_version": CURRENT_PROJECT_SCHEMA_VERSION,
            "settings": self._stage_settings_snapshot(stage_key),
        }
        tool_versions = self._stage_tool_versions(stage_key)
        if tool_versions:
            snapshot["tool_versions"] = tool_versions
        if stage_key in {"beam", "extract", "plot", "datasheet"}:
            snapshot["ffs_items"] = [
                {
                    "path": serialize_workspace_path(THIS_DIR, str(item["path"])),
                    "enabled": bool(item["enabled"]),
                    "port_label": str(item.get("port_label", "")).strip(),
                    "file": self._path_fingerprint(str(item["path"])),
                }
                for item in self.collect_ffs_items()
            ]
        if stage_key in {"extract", "vswr", "datasheet"}:
            snapshot["touchstone"] = self._path_fingerprint(self.selected_s2p())
        if stage_key == "datasheet":
            snapshot["technical_data"] = self._technical_data_snapshot()
            snapshot["radiation_pattern_frequencies_ghz"] = None if self._project_radiation_frequencies is None else self.selected_radiation_frequencies()
        if stage_key in {"extract", "plot", "datasheet"}:
            snapshot["beam_workbook"] = self._path_fingerprint(self.deduced_beam_output())
        if stage_key == "datasheet":
            snapshot["extract_workbook"] = self._path_fingerprint(self.deduced_extract_output())
            snapshot["template_pdf"] = self._path_fingerprint(self.selected_datasheet_template_path())
            snapshot["plot_outputs"] = [
                self._path_fingerprint(path)
                for path in self._stage_output_files("plot")
            ]
        return snapshot

    def _stage_output_files(self, stage_key: str) -> list[Path]:
        cache_key = f"stage_files:{stage_key}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return list(cached)
        files = stage_output_files(
            stage_key,
            project_dir=self.project_results_dir(),
            beam_output=self.deduced_beam_output(),
            extract_output=self.deduced_extract_output(),
            datasheet_output=self.deduced_datasheet_output(),
            vswr_output=self.deduced_vswr_output(),
        )
        self._cache_set(cache_key, list(files))
        return files

    def _stage_generated_directories(self, stage_key: str) -> list[Path]:
        return stage_generated_directories(stage_key, project_dir=self.project_results_dir())

    def _stage_output_target(self, stage_key: str) -> Path:
        if stage_key == "plot":
            return self.project_results_dir()
        files = self._stage_output_files(stage_key)
        return files[0] if files else self.project_results_dir()

    def _all_generated_output_files(self) -> list[Path]:
        files: list[Path] = []
        seen: set[Path] = set()
        for stage_key, _label in STAGE_DEFINITIONS:
            for path in self._stage_output_files(stage_key):
                if path not in seen:
                    seen.add(path)
                    files.append(path)
        return files

    def _remove_generated_directories(self, stage_keys: list[str]) -> None:
        seen: set[Path] = set()
        for stage_key in stage_keys:
            for path in self._stage_generated_directories(stage_key):
                if path in seen or not path.exists():
                    continue
                seen.add(path)
                shutil.rmtree(path, ignore_errors=False)

    def _stage_output_any_exists(self, stage_key: str) -> bool:
        cache_key = f"stage_any:{stage_key}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return bool(cached)
        files = self._stage_output_files(stage_key)
        if not files:
            return False
        exists = any(self._cached_path_exists(path) for path in files)
        return bool(self._cache_set(cache_key, exists))

    def _stage_output_exists(self, stage_key: str) -> bool:
        cache_key = f"stage_all:{stage_key}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return bool(cached)
        files = self._stage_output_files(stage_key)
        if not files:
            return False
        exists = all(self._cached_path_exists(path) for path in files)
        return bool(self._cache_set(cache_key, exists))

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
        return stage_is_applicable(
            stage_key,
            has_enabled_ffs=bool(self.selected_ffs()),
            has_touchstone=bool(self.selected_s2p()),
            has_technical_data=bool(self.selected_technical_data()),
        )

    def _stage_is_stale(self, stage_key: str) -> bool:
        cache_key = f"stage_stale:{stage_key}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return bool(cached)
        if not self._stage_output_exists(stage_key):
            return bool(self._cache_set(cache_key, False))
        stage_state = self._stage_state(stage_key)
        snapshot = stage_state.get("snapshot")
        if not snapshot:
            return bool(self._cache_set(cache_key, True))
        stale = snapshot != self._current_stage_snapshot(stage_key)
        return bool(self._cache_set(cache_key, stale))

    def _stage_stale_detail(self, stage_key: str) -> str:
        if not self._stage_output_exists(stage_key):
            return ""
        stage_state = self._stage_state(stage_key)
        snapshot = stage_state.get("snapshot")
        if not isinstance(snapshot, dict):
            return ""
        current_versions = self._stage_tool_versions(stage_key)
        if not current_versions:
            return ""
        return stage_stale_detail(stage_key, snapshot.get("tool_versions"), current_versions)

    def _stale_stage_keys(self) -> list[str]:
        cache_key = "stale_stage_keys"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return list(cached)
        keys = [
            stage_key
            for stage_key, _label in STAGE_DEFINITIONS
            if self._stage_is_applicable(stage_key) and self._stage_is_stale(stage_key)
        ]
        self._cache_set(cache_key, list(keys))
        return keys

    def _preset_matches_selected(self) -> bool:
        name = self.project_active_preset or self.current_preset_name()
        if not name:
            return False
        preset = self.global_presets.get(name)
        return isinstance(preset, dict) and self._normalized_preset_values(preset) == self._normalized_preset_values(self.collect_preset_values())

    def _validation_messages(self) -> list[str]:
        if not self.active_project_slug:
            return ["Select or create a project to begin."]
        messages: list[str] = []
        items = self.collect_ffs_items()
        paths = [str(item["path"]) for item in items]
        enabled_paths = [str(item["path"]) for item in items if bool(item["enabled"])]
        duplicates = sorted({path for path in paths if paths.count(path) > 1})
        missing_ffs = [path for path in paths if path and not self._cached_path_exists(Path(path))]
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
        if s2p and not self._cached_path_exists(Path(s2p)):
            messages.append(f"Selected Touchstone file is missing: {display_workspace_path(s2p)}")
        elif not s2p:
            messages.append("VSWR stage is unavailable until a Touchstone file is selected.")
        technical_data = self.selected_technical_data()
        if is_url(technical_data) and not self.technical_data_is_google_sheet():
            messages.append("Selected Technical Data URL is not a Google Sheet link.")
        elif self.technical_data_is_google_sheet() and not extract_google_sheet_id(technical_data):
            messages.append("Selected Google Sheet URL is missing a spreadsheet ID.")
        elif self.technical_data_is_google_sheet() and not self.google_sheets_auth_configured():
            messages.append("Google Sheets sign-in is required before Datasheet generation.")
        elif technical_data and not is_url(technical_data) and not self._cached_path_exists(Path(technical_data)):
            messages.append(f"Selected Technical Data workbook is missing: {display_workspace_path(technical_data)}")
        elif not technical_data:
            messages.append("Datasheet stage is unavailable until a Technical Data workbook is selected.")
        template_path = self.selected_datasheet_template_path()
        if not self._cached_path_exists(template_path):
            messages.append(f"Selected datasheet template is missing: {display_workspace_path(template_path)}")
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
        failed: list[tuple[str, str]] = []
        for stage_key, _label in STAGE_DEFINITIONS:
            stage_state = self._stage_state(stage_key)
            if str(stage_state.get("status", "")).strip().lower() != "failed":
                continue
            last_finished = str(stage_state.get("last_finished_at", "")).strip()
            last_success = str(stage_state.get("last_success_at", "")).strip()
            if last_success and last_finished < last_success:
                continue
            failed.append((last_finished, stage_key))
        if not failed:
            return ""
        return max(failed)[1]

    def _needed_rerun_stage_keys(self) -> list[str]:
        failed = self._latest_failed_stage_key()
        needed = set(self._stale_stage_keys())
        if failed and self._stage_is_applicable(failed):
            needed.add(failed)
        return [
            stage_key
            for stage_key, _label in STAGE_DEFINITIONS
            if stage_key in needed and self._stage_is_applicable(stage_key)
        ]

    def _stage_label_list(self, stage_keys: list[str]) -> str:
        return ", ".join(STAGE_LABELS.get(key, key.title()) for key in stage_keys)

    def _skipped_rerun_stage_keys(self, needed_stage_keys: list[str]) -> list[str]:
        needed = set(needed_stage_keys)
        return [
            stage_key
            for stage_key, _label in STAGE_DEFINITIONS
            if (
                stage_key not in needed
                and self._stage_is_applicable(stage_key)
                and self._stage_output_exists(stage_key)
                and not self._stage_is_stale(stage_key)
            )
        ]

    def _recovery_plan_text(self) -> str:
        needed = self._needed_rerun_stage_keys()
        if not needed:
            return "No failed or stale outputs need rerun."
        failed = self._latest_failed_stage_key()
        stale = [key for key in self._stale_stage_keys() if key in needed and key != failed]
        parts: list[str] = []
        if failed and failed in needed:
            parts.append(f"failed: {STAGE_LABELS.get(failed, failed.title())}")
        if stale:
            parts.append(f"stale: {self._stage_label_list(stale)}")
        summary = "Run Needed Only will rerun " + "; ".join(parts or [self._stage_label_list(needed)]) + "."
        skipped = self._skipped_rerun_stage_keys(needed)
        if skipped:
            summary += f" It will skip current outputs: {self._stage_label_list(skipped)}."
        return summary

    def _chip_rgba(self, color: QColor, alpha: int) -> str:
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"

    def _stage_chip_style(self, tone: str) -> str:
        theme = THEME_STYLES.get(self.theme, THEME_STYLES["light"])
        title = QColor(theme["title_color"])
        helper = QColor(theme["helper_color"])
        semantic_colors = {
            "ready": QColor("#2f9e5b"),
            "running": QColor("#2f80ed"),
            "queued": QColor("#6b7a90"),
            "stale": QColor("#d69e2e"),
            "failed": QColor("#d64545"),
            "cancelled": QColor("#8b94a7"),
            "muted": QColor("#66758a"),
        }
        base = semantic_colors.get(tone, semantic_colors["muted"])
        text = helper if tone == "muted" else title
        background_alpha = 48 if tone in {"ready", "running", "stale", "failed"} else 36
        border_alpha = 170 if tone in {"ready", "running", "stale", "failed"} else 120
        return (
            f"background: {self._chip_rgba(base, background_alpha)}; "
            f"border: 1px solid {self._chip_rgba(base, border_alpha)}; "
            f"color: {text.name()};"
        )

    def _readiness_badge_style(self, tone: str) -> str:
        theme = THEME_STYLES.get(self.theme, THEME_STYLES["light"])
        title = QColor(theme["title_color"])
        helper = QColor(theme["helper_color"])
        semantic_colors = {
            "ready": QColor("#2f9e5b"),
            "warning": QColor("#d69e2e"),
            "blocked": QColor("#d64545"),
            "running": QColor("#2f80ed"),
            "optional": QColor("#6b7a90"),
            "muted": QColor("#66758a"),
        }
        base = semantic_colors.get(tone, semantic_colors["muted"])
        text = helper if tone in {"optional", "muted"} else title
        background_alpha = 48 if tone in {"ready", "warning", "blocked", "running"} else 36
        border_alpha = 170 if tone in {"ready", "warning", "blocked", "running"} else 120
        return (
            f"background: {self._chip_rgba(base, background_alpha)}; "
            f"border: 1px solid {self._chip_rgba(base, border_alpha)}; "
            f"color: {text.name()};"
        )

    def _set_readiness_badge(self, key: str, text: str, tone: str) -> None:
        badge = self.readiness_badges[key]
        badge.setText(text)
        badge.setStyleSheet(self._readiness_badge_style(tone))

    def _refresh_stage_labels(self) -> None:
        if not self.stage_status_labels or not self.stage_open_buttons:
            return
        is_running = bool(self.proc.running_cmd or self.proc.queue or self._current_stage_key or self._pending_stage_keys)
        for stage_key, stage_label in STAGE_DEFINITIONS:
            stage_state = self._stage_state(stage_key)
            status = str(stage_state.get("status", "")).strip().lower()
            last_finished = str(stage_state.get("last_finished_at", "")).strip()
            last_success = str(stage_state.get("last_success_at", "")).strip()
            applicable = self._stage_is_applicable(stage_key)
            output_exists = self._stage_output_exists(stage_key)
            any_output_exists = self._stage_output_any_exists(stage_key)
            has_project = bool(self.active_project_slug)
            self.stage_open_buttons[stage_key].setEnabled(bool(self.active_project_slug) and output_exists)
            self.stage_reveal_actions[stage_key].setEnabled(bool(self.active_project_slug) and any_output_exists)
            self.stage_delete_actions[stage_key].setEnabled(bool(self.active_project_slug) and any_output_exists)
            self.stage_rerun_buttons[stage_key].setEnabled(
                has_project
                and applicable
                and not is_running
            )
            self.stage_open_buttons[stage_key].setVisible(output_exists)
            self.stage_rerun_buttons[stage_key].setVisible(has_project and applicable)
            self.stage_more_buttons[stage_key].setVisible(has_project and (applicable or any_output_exists))
            self.stage_more_buttons[stage_key].setEnabled(has_project and any_output_exists)
            if not self.active_project_slug:
                text = "No project selected."
                timestamp_text = "Generated: not available"
                chip_text = "None"
                chip_tone = "muted"
            elif stage_key == self._current_stage_key:
                progress = self._live_stage_progress_text(stage_key)
                text = "Running"
                if progress:
                    text += f" ({progress})"
                timestamp_text = "Generated: in progress"
                chip_text = "Running"
                chip_tone = "running"
            elif stage_key in self._pending_stage_keys:
                text = "Queued"
                timestamp_text = f"Generated: {format_timestamp(last_success)}" if last_success and any_output_exists else "Generated: waiting"
                chip_text = "Queued"
                chip_tone = "queued"
            elif not applicable:
                text = "Not configured for this project."
                timestamp_text = "Generated: not applicable"
                chip_text = "Off"
                chip_tone = "muted"
            elif status in {"failed", "cancelled"} and (not last_success or last_finished >= last_success):
                text = status.capitalize()
                timestamp_text = f"Generated: {format_timestamp(last_success)}" if last_success and any_output_exists else "Generated: not available"
                chip_text = status.capitalize()
                chip_tone = status
            elif self._stage_is_stale(stage_key):
                text = self._stage_stale_detail(stage_key) or "Stale"
                timestamp_text = f"Generated: {format_timestamp(last_success)}" if last_success else "Generated: unknown"
                chip_text = "Stale"
                chip_tone = "stale"
            elif output_exists:
                stamp = format_timestamp(str(stage_state.get("last_success_at", "")))
                text = "Ready"
                timestamp_text = f"Generated: {stamp}"
                chip_text = "Ready"
                chip_tone = "ready"
            elif status == "failed":
                text = "Failed"
                timestamp_text = f"Generated: {format_timestamp(last_success)}" if last_success and any_output_exists else "Generated: not available"
                chip_text = "Failed"
                chip_tone = "failed"
            elif status == "cancelled":
                text = "Cancelled"
                timestamp_text = f"Generated: {format_timestamp(last_success)}" if last_success and any_output_exists else "Generated: not available"
                chip_text = "Cancelled"
                chip_tone = "cancelled"
            else:
                text = "Waiting for the first run."
                timestamp_text = "Generated: not yet"
                chip_text = "Waiting"
                chip_tone = "muted"
            self.stage_status_labels[stage_key].setText(text)
            self.stage_timestamp_labels[stage_key].setText(timestamp_text)
            self.stage_chip_labels[stage_key].setText(chip_text)
            self.stage_chip_labels[stage_key].setStyleSheet(self._stage_chip_style(chip_tone))

    def _refresh_run_readiness(self) -> None:
        has_project = bool(self.active_project_slug)
        total_ffs = len(self.collect_ffs_items()) if has_project else 0
        enabled_ffs = self._enabled_ffs_count() if has_project else 0
        missing_enabled = self._missing_enabled_ffs() if has_project else []
        s2p = self.selected_s2p() if has_project else ""
        touchstone_ready = bool(s2p) and self._cached_path_exists(Path(s2p))
        technical_data = self.selected_technical_data() if has_project else ""
        technical_data_ready = self.technical_data_source_ready() if has_project else False
        template_path = self.selected_datasheet_template_path()
        template_ready = self._cached_path_exists(template_path)
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
            and technical_data_ready
            and template_ready
        )
        vswr_ready = has_project and frequency_ready and touchstone_ready

        if not has_project:
            self._set_readiness_badge("project", "Not selected", "muted")
            self._set_readiness_badge("inputs", "No files", "muted")
            self._set_readiness_badge("touchstone", "Not selected", "muted")
            self._set_readiness_badge("outputs", "No outputs", "muted")
            self.readiness_summary.setText("Create a project first. Input paths, preset selection, and output freshness are tracked per project.")
            self._set_readiness_action("Create project", self.create_project, tooltip="Create a new project.")
            return

        self._set_readiness_badge("project", "Unsaved" if unsaved_changes else "Saved", "warning" if unsaved_changes else "ready")
        if missing_enabled:
            self._set_readiness_badge("inputs", "Files missing", "blocked")
        elif total_ffs == 0:
            self._set_readiness_badge("inputs", "No files", "warning")
        elif enabled_ffs == 0:
            self._set_readiness_badge("inputs", "All disabled", "warning")
        else:
            self._set_readiness_badge("inputs", f"{enabled_ffs} ready", "ready")

        if not s2p:
            self._set_readiness_badge("touchstone", "Optional", "optional")
        elif touchstone_ready:
            self._set_readiness_badge("touchstone", "Ready", "ready")
        else:
            self._set_readiness_badge("touchstone", "File missing", "blocked")

        if running:
            outputs_state = "Running"
        elif stale_stages:
            outputs_state = f"{len(stale_stages)} stale"
        elif not ready_stages:
            outputs_state = "Not generated"
        elif len(ready_stages) < len(applicable_stages):
            outputs_state = "Partial"
            outputs_tone = "warning"
        else:
            outputs_state = "Up to date"
            outputs_tone = "ready"
        if running:
            outputs_tone = "running"
        elif stale_stages:
            outputs_tone = "warning"
        elif not ready_stages:
            outputs_tone = "muted"
        self._set_readiness_badge("outputs", outputs_state, outputs_tone)

        if running:
            stage_label = STAGE_LABELS.get(self._current_stage_key, self._current_stage_key.title()) if self._current_stage_key else "Pipeline"
            queued = len(self._pending_stage_keys)
            summary = f"{stage_label} is running."
            progress = self._live_stage_progress_text()
            if progress:
                summary += f" {progress}."
            summary += f" {queued} stage(s) remain queued." if queued else " The queue is active."
            self.readiness_summary.setText(summary)
            self._set_readiness_action("Run Full Pipeline", self.run_full, enabled=False, tooltip="")
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
            self.readiness_summary.setText("Far-field stages are ready, but Touchstone is still missing. Use the Project workspace menu for workbook, extract, or plots, or add Touchstone for Full Pipeline.")
            self._set_readiness_action("Project actions", self._open_project_actions_menu, tooltip="Open the Project workspace actions menu.")
            return

        if is_url(technical_data) and not self.technical_data_is_google_sheet():
            self.readiness_summary.setText("The selected Technical Data URL is not a Google Sheet link. Choose a local workbook or a valid Google Sheet.")
            self._set_readiness_action("Open Inputs", self._show_inputs_tab, tooltip="Go to the Inputs tab to fix the Technical Data source.")
            return

        if self.technical_data_is_google_sheet() and not technical_data_ready:
            self.readiness_summary.setText("Google Sheets sign-in is required before Datasheet or Full Pipeline can download the Technical Data workbook.")
            self._set_readiness_action("Open Inputs", self._show_inputs_tab, tooltip="Go to the Inputs tab and use Google Sign In.")
            return

        if technical_data and not technical_data_ready:
            self.readiness_summary.setText("The selected Technical Data workbook is missing. Full Pipeline and Datasheet stay unavailable until you fix that path.")
            self._set_readiness_action("Open Inputs", self._show_inputs_tab, tooltip="Go to the Inputs tab to fix the Technical Data workbook path.")
            return

        if not technical_data:
            self.readiness_summary.setText("Far-field and Touchstone inputs are ready, but Technical Data is still missing. Add it before running Datasheet or Full Pipeline.")
            self._set_readiness_action("Open Inputs", self._show_inputs_tab, tooltip="Go to the Inputs tab to select a Technical Data workbook.")
            return

        if not template_ready:
            self.readiness_summary.setText("The selected datasheet export style is missing. Choose an available style before running Datasheet or Full Pipeline.")
            self._set_readiness_action("Open Document", self._show_document_tab, tooltip="Go to the Document tab to select a datasheet export style.")
            return

        if latest_failed:
            self.readiness_summary.setText(self._recovery_plan_text())
            self._set_readiness_action("Run Failed Stage", self.run_needed_outputs, tooltip="Retry only the failed stage.")
            return

        if stale_stages:
            stale_details = [self._stage_stale_detail(key) for key in stale_stages]
            stale_details = [detail for detail in stale_details if detail]
            if stale_details:
                self.readiness_summary.setText(f"{stale_details[0]} {self._recovery_plan_text()}")
            else:
                self.readiness_summary.setText(self._recovery_plan_text())
            self._set_readiness_action("Run Full Pipeline", self.run_full, enabled=False, tooltip="")
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
            self._set_save_state_indicator(self.project_save_state_indicator, "No project selected", "neutral")
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
        file_count = self._cached_project_file_count()
        self.project_stats_label.setText(
            f"Schema v{self._loaded_project_schema_version}->{CURRENT_PROJECT_SCHEMA_VERSION} | "
            f"{enabled_ffs} enabled / {total_ffs} far-field files"
            + (f" | {disabled_ffs} disabled" if disabled_ffs else "")
            + f" | {file_count} file(s) in project folder"
        )
        self.artifact_summary_label.setText(" | ".join(artifact_bits))
        unsaved_changes = self.has_unsaved_project_changes()
        if unsaved_changes:
            self._set_save_state_indicator(self.project_save_state_indicator, "Project has unsaved changes", "unsaved")
            self.project_save_state_indicator.set_diff_items(self._project_diff_items())
            self.project_health.setText("Unsaved project or preset changes are pending.")
            self.run_summary.setText("Current edits are not saved yet.")
        else:
            self._set_save_state_indicator(self.project_save_state_indicator, "Project saved", "saved")
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
            stale_details = [self._stage_stale_detail(key) for key in stale_stages]
            stale_details = [detail for detail in stale_details if detail]
            if stale_details:
                self.project_health.setText(stale_details[0])
            else:
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
            self.run_summary.setText(self._running_summary_text())
        else:
            latest_failed = self._latest_failed_stage_key()
            if latest_failed:
                self.run_summary.setText(self._recovery_plan_text())
            elif stale_stages:
                self.run_summary.setText(self._recovery_plan_text())
            elif any(self._stage_is_applicable(stage_key) and self._stage_output_exists(stage_key) for stage_key, _label in STAGE_DEFINITIONS):
                self.run_summary.setText("Outputs are up to date.")
            else:
                self.run_summary.setText("No completed run yet.")
        self._refresh_run_readiness()
        self._refresh_stage_labels()

    def selected_ffs(self) -> list[str]:
        return [str(item["path"]) for item in self.collect_ffs_items() if bool(item["enabled"])]

    def polar_port_labels_json(self) -> str:
        labels: dict[str, str] = {}
        for item in self.collect_ffs_items():
            if not bool(item.get("enabled", True)):
                continue
            label = str(item.get("port_label", "")).strip()
            if not label:
                continue
            path = str(item.get("path", "")).strip()
            if not path:
                continue
            resolved = str(resolve_workspace_path(path))
            stem = Path(resolved).stem
            for key in (resolved, display_workspace_path(resolved), stem, stem[:31]):
                if key:
                    labels[key] = label
        return json.dumps(labels, sort_keys=True)

    def selected_s2p(self) -> str:
        value = self.s2p_field.text().strip()
        return str(resolve_workspace_path(value)) if value else ""

    def selected_technical_data(self) -> str:
        value = self.technical_data_field.text().strip()
        if is_url(value):
            return value
        return str(resolve_workspace_path(value)) if value else ""

    def technical_data_is_google_sheet(self) -> bool:
        return is_google_sheet_url(self.selected_technical_data())

    def google_sheets_token_path(self) -> Path:
        return app_state_dir() / GOOGLE_SHEETS_TOKEN_FILENAME

    def google_sheets_oauth_client_path(self) -> Path:
        value = str(self.store.get(GOOGLE_SHEETS_OAUTH_CLIENT_KEY, "") or "").strip()
        if not value:
            return Path()
        path = Path(value)
        return path if path.is_absolute() else resolve_workspace_path(path)

    def google_sheets_auth_configured(self) -> bool:
        client_path = self.google_sheets_oauth_client_path()
        return bool(client_path and client_path.exists() and self.google_sheets_token_path().exists())

    def technical_data_cache_path(self) -> Path:
        return self.project_results_dir() / "_cache" / "technical-data.xlsx"

    def _technical_data_snapshot(self) -> dict[str, object]:
        source = self.selected_technical_data()
        if self.technical_data_is_google_sheet():
            return {
                "source": source,
                "type": "google_sheet",
                "cached_xlsx": self._path_fingerprint(self.technical_data_cache_path()),
            }
        return self._path_fingerprint(source)

    def _ensure_google_sheets_credentials(self, *, interactive: bool):
        try:
            from google.auth.exceptions import RefreshError
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise GoogleSheetDownloadError("Install Google auth dependencies from requirements.txt before using Google Sheets.") from exc

        token_path = self.google_sheets_token_path()
        client_path = self.google_sheets_oauth_client_path()
        credentials = None
        if token_path.exists():
            try:
                credentials = Credentials.from_authorized_user_file(str(token_path), GOOGLE_SHEETS_SCOPES)
            except Exception:
                credentials = None
        if credentials and credentials.valid:
            return credentials
        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                token_path.parent.mkdir(parents=True, exist_ok=True)
                token_path.write_text(credentials.to_json(), encoding="utf-8")
                return credentials
            except RefreshError as exc:
                if token_path.exists():
                    token_path.unlink()
                if not interactive:
                    raise GoogleSheetDownloadError("Google Sheets sign-in expired. Use Google Sign In, then run again.") from exc
        if not interactive:
            raise GoogleSheetDownloadError("Google Sheets sign-in is required. Use Google Sign In before running Datasheet or Full Pipeline.")
        if not client_path.exists():
            raise GoogleSheetDownloadError("Select a Google OAuth client JSON before signing in.")
        flow = InstalledAppFlow.from_client_secrets_file(str(client_path), GOOGLE_SHEETS_SCOPES)
        credentials = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(credentials.to_json(), encoding="utf-8")
        return credentials

    def download_google_sheet_technical_data(self, source: str) -> Path:
        spreadsheet_id = extract_google_sheet_id(source)
        if not spreadsheet_id:
            raise GoogleSheetDownloadError("Selected Google Sheet URL is missing a spreadsheet ID.")
        try:
            from google.auth.transport.requests import AuthorizedSession
        except ImportError as exc:
            raise GoogleSheetDownloadError("Install Google auth dependencies from requirements.txt before using Google Sheets.") from exc

        credentials = self._ensure_google_sheets_credentials(interactive=False)
        session = AuthorizedSession(credentials)
        response = session.get(google_sheet_export_url(spreadsheet_id), timeout=60)
        if response.status_code != 200:
            detail = response.text[:240].strip() if getattr(response, "text", "") else f"HTTP {response.status_code}"
            raise GoogleSheetDownloadError(f"Could not download Google Sheet as XLSX: {detail}")
        output = self.technical_data_cache_path()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(response.content)
        return output

    def prepare_technical_data_workbook(self) -> str:
        source = self.selected_technical_data()
        if not source:
            return ""
        try:
            if self.technical_data_is_google_sheet():
                source_adapter = GoogleSheetTechnicalDataSource(
                    source,
                    self.technical_data_cache_path(),
                    lambda url, _output: self.download_google_sheet_technical_data(url),
                )
                return str(source_adapter.prepare_workbook())
            return str(LocalTechnicalDataSource(Path(source)).prepare_workbook())
        except TechnicalDataError as exc:
            raise GoogleSheetDownloadError(str(exc)) from exc

    def technical_data_source_ready(self) -> bool:
        source = self.selected_technical_data()
        if not source:
            return False
        if is_url(source):
            return self.technical_data_is_google_sheet() and bool(extract_google_sheet_id(source)) and self.google_sheets_auth_configured()
        return self._cached_path_exists(Path(source))

    def selected_pdf_metadata_author(self) -> str:
        return self.pdf_metadata_author.text().strip()

    def _project_uses_saved_preset(self) -> bool:
        return bool(self.project_active_preset and self.project_active_preset in self.global_presets)

    def _project_record_settings(self) -> dict[str, object]:
        if self._project_uses_saved_preset():
            return {}
        return self.collect_preset_values()

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
                    "port_label": str(item.get("port_label", "")).strip(),
                }
                for item in self.collect_ffs_items()
            ],
            touchstone_file=serialize_workspace_path(THIS_DIR, self.selected_s2p()),
            technical_data_file=serialize_workspace_path(THIS_DIR, self.selected_technical_data()),
            settings=self._project_record_settings(),
            presets={},
            active_preset=self.project_active_preset,
            radiation_pattern_frequencies_ghz=None if self._project_radiation_frequencies is None else self.selected_radiation_frequencies(),
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
        return project.extract_path(THIS_DIR) if project else (self.project_results_dir() / "project-extracted-data.xlsx")

    def deduced_datasheet_output(self) -> Path:
        project = self.current_project()
        return project.datasheet_path(THIS_DIR) if project else (self.project_results_dir() / "project-datasheet.pdf")

    def deduced_vswr_output(self) -> Path:
        project = self.current_project()
        return project.vswr_path(THIS_DIR) if project else (self.project_results_dir() / "project-vswr.svg")

    def refresh_derived_paths(self) -> None:
        was_enabled = self._refresh_cache_enabled
        if not was_enabled:
            self._refresh_cache = {}
            self._refresh_cache_enabled = True
        try:
            if self.active_project_slug:
                project_label = self.active_project_name or self.active_project_slug
                self.project_name.setText(project_label)
                self.project_meta.setText(f"Folder: {display_workspace_path(self.project_results_dir())}")
            else:
                self.project_name.setText("No project selected")
                self.project_meta.setText("Create a project to keep inputs, presets, and generated results together.")
            if self.active_project_slug:
                suffix = " *" if self.has_unsaved_project_changes() else ""
                self.project_name.setText(f"{(self.active_project_name or self.active_project_slug)}{suffix}")
            self.open_s2p_button.setEnabled(bool(self.active_project_slug and self.selected_s2p()))
            self.open_technical_data_button.setEnabled(bool(self.active_project_slug and self.selected_technical_data()))
            self._update_google_credentials_button_state()
            self._update_ffs_action_state()
            self._refresh_project_summary()
            self._update_project_action_state()
            self.refresh_radiation_frequency_list()
        finally:
            if not was_enabled:
                self._refresh_cache = {}
                self._refresh_cache_enabled = False

    def clear_derived_path_cache(self) -> None:
        self._refresh_cache = {}

    def _update_project_action_state(self) -> None:
        has_project = bool(self.active_project_slug)
        is_running = bool(self.proc.running_cmd or self.proc.queue or self._current_stage_key or self._pending_stage_keys)
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
        needed_stage_keys = self._needed_rerun_stage_keys() if has_project else []
        self.project_run_needed_action.setEnabled(has_project and not is_running and bool(needed_stage_keys))
        self.project_run_needed_action.setText("Run failed/stale only")
        self.project_import_action.setEnabled(True)
        self.project_export_action.setEnabled(has_project)
        has_generated_outputs = any(self._cached_path_exists(path) for path in self._all_generated_output_files()) if has_project else False
        self.project_delete_outputs_action.setEnabled(has_project and not is_running and has_generated_outputs)
        self.project_open_folder_action.setEnabled(has_project)
        for widget in (
            self.btn_full,
            self.btn_run_needed,
            self.btn_validate,
            self.btn_clear_outputs,
            self.ffs_list,
            self.ffs_port_label_field,
            self.s2p_field,
            self.technical_data_field,
            self.add_ffs_button,
            self.remove_ffs_button,
            self.clear_ffs_button,
            self.select_s2p_button,
            self.clear_s2p_button,
            self.open_s2p_button,
            self.select_technical_data_button,
            self.google_sheet_technical_data_button,
            self.google_credentials_button,
            self.open_technical_data_button,
            self.radiation_frequency_list,
            self.radiation_defaults_button,
            self.radiation_select_all_button,
            self.radiation_clear_button,
            self.datasheet_template_combo,
            self.pdf_metadata_author,
        ):
            widget.setEnabled(has_project)
        self.btn_clear_outputs.setEnabled(has_project and not is_running and has_generated_outputs)
        self.btn_run_needed.setEnabled(has_project and not is_running and bool(needed_stage_keys))
        if needed_stage_keys:
            needed_label = self._stage_label_list(needed_stage_keys)
            self.btn_run_needed.setToolTip(f"Run only failed or stale outputs: {needed_label}.")
            self.project_run_needed_action.setToolTip(self._recovery_plan_text())
        else:
            self.btn_run_needed.setToolTip("No failed or stale outputs need rerun.")
            self.project_run_needed_action.setToolTip("No failed or stale outputs need rerun.")
        self.btn_cancel.setEnabled(has_project and is_running)
        self.btn_cancel.setVisible(has_project and is_running)
        self._update_preset_action_state()

    def _clear_live_run_progress(self) -> None:
        self._live_run_total_stages = 0
        self._live_run_completed_stages = 0
        self._live_stage_progress_key = ""
        self._live_stage_progress_current = 0
        self._live_stage_progress_total = 0
        self._live_stage_progress_label = ""

    def _reset_live_stage_progress(self, stage_key: str = "", label: str = "") -> None:
        self._live_stage_progress_key = stage_key
        self._live_stage_progress_current = 0
        self._live_stage_progress_total = 0
        self._live_stage_progress_label = label

    def _live_stage_progress_fraction(self, stage_key: str | None = None) -> float | None:
        key = stage_key or self._current_stage_key or self._live_stage_progress_key
        if not key or key != self._live_stage_progress_key or self._live_stage_progress_total <= 0:
            return None
        return max(0.0, min(1.0, self._live_stage_progress_current / self._live_stage_progress_total))

    def _live_stage_progress_text(self, stage_key: str | None = None) -> str:
        key = stage_key or self._current_stage_key or self._live_stage_progress_key
        if not key or key != self._live_stage_progress_key:
            return ""
        parts: list[str] = []
        if self._live_stage_progress_total > 0:
            parts.append(f"{self._live_stage_progress_current}/{self._live_stage_progress_total}")
        if self._live_stage_progress_label:
            parts.append(self._live_stage_progress_label)
        return " | ".join(parts)

    def _live_overall_progress_value(self) -> int | None:
        if self._live_run_total_stages <= 0:
            return None
        fraction = self._live_stage_progress_fraction()
        if fraction is None:
            return None
        completed = float(self._live_run_completed_stages)
        completed += fraction
        return int(round(max(0.0, min(1.0, completed / self._live_run_total_stages)) * 100))

    def _sync_live_progress_bar(self) -> None:
        self.set_progress(self._live_overall_progress_value())

    def _running_stage_label(self) -> str:
        stage_key = self._current_stage_key or self._live_stage_progress_key
        if not stage_key:
            return "Pipeline"
        return STAGE_LABELS.get(stage_key, stage_key.title())

    def _running_summary_text(self) -> str:
        text = f"Running {self._running_stage_label()}"
        progress = self._live_stage_progress_text()
        if progress:
            text += f" | {progress}"
        queued = len(self._pending_stage_keys)
        if queued:
            text += f" | {queued} stage(s) queued"
        return text

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
        preset_dirty = self.has_unsaved_preset_changes()
        if not has_project:
            if has_preset:
                self.preset_state_label.setText(f"Preset '{self.current_preset_name()}' is available globally. Select a project to save that choice with it.")
                if preset_dirty:
                    self._set_save_state_indicator(self.preset_save_state_indicator, "Preset has unsaved changes", "unsaved")
                    self.preset_save_state_indicator.set_diff_items(self._current_preset_diff_items())
                else:
                    self._set_save_state_indicator(self.preset_save_state_indicator, "Preset saved", "saved")
            else:
                self.preset_state_label.setText("Choose a preset or keep working manually.")
                self._set_save_state_indicator(self.preset_save_state_indicator, "No preset selected", "neutral")
        elif self.project_active_preset and self.project_active_preset not in self.global_presets:
            self.preset_state_label.setText(
                f"Project preset '{self.project_active_preset}' is missing. Select an existing preset or save the current controls as a new one."
            )
            self._set_save_state_indicator(self.preset_save_state_indicator, "Preset missing", "unsaved")
        elif not has_preset:
            self.preset_state_label.setText("Manual settings only. Save them as a preset if you want to reuse them.")
            self._set_save_state_indicator(self.preset_save_state_indicator, "No preset selected", "neutral")
        elif self._preset_matches_selected():
            self.preset_state_label.setText(f"Preset '{self.project_active_preset}' matches the current controls.")
            self._set_save_state_indicator(self.preset_save_state_indicator, "Preset saved", "saved")
        else:
            self.preset_state_label.setText(
                f"Current controls differ from preset '{self.project_active_preset}'. Save to update it or create a new preset."
            )
            self._set_save_state_indicator(self.preset_save_state_indicator, "Preset has unsaved changes", "unsaved")
            self.preset_save_state_indicator.set_diff_items(self._current_preset_diff_items())

    def refresh_project_list(self, select_slug: str = "", *, confirm_changes: bool = False) -> None:
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
        previous = self._suppress_project_selection_prompt
        self._suppress_project_selection_prompt = not confirm_changes
        try:
            self.on_project_selected(self.project_combo.currentIndex())
        finally:
            self._suppress_project_selection_prompt = previous

    def on_project_selected(self, _index: int) -> None:
        if self._reverting_project_selection:
            return
        slug = str(self.project_combo.currentData() or "")
        if (
            slug != self.active_project_slug
            and not self._suppress_project_selection_prompt
            and not self._confirm_pending_changes("switching projects")
        ):
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
            self._project_radiation_frequencies = None
            self._saved_project_signature = ""
            self._loaded_project_schema_version = CURRENT_PROJECT_SCHEMA_VERSION
            self._pending_stage_keys = []
            self._current_stage_key = ""
            self._clear_live_run_progress()
            self._loading_project = True
            self.ffs_list.clear()
            self.s2p_field.clear()
            self._loading_project = False
            self.store.set("active_project", "")
            self.refresh_preset_list(select_name=self.global_active_preset)
            self.refresh_radiation_frequency_list()
            self.refresh_derived_paths()
            return
        project = self.project_store.load_project(slug)
        self._apply_project(project)

    def _persist_global_presets(self) -> None:
        self.preset_store.replace_all(self.global_presets)
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
        self._project_radiation_frequencies = normalize_radiation_frequencies(project.radiation_pattern_frequencies_ghz)
        self._loaded_project_schema_version = int(project.schema_version or 1)
        self._pending_stage_keys = []
        self._current_stage_key = ""
        self._clear_live_run_progress()
        self.store.set("active_project", project.slug)
        self.ffs_list.clear()
        self._add_ffs_files(project.ffs_items or [{"path": path, "enabled": True} for path in project.ffs_files], save=False)
        touchstone = resolve_project_path(THIS_DIR, project.touchstone_file)
        if not touchstone and project.name:
            guessed = guess_touchstone_path(project.name, self.selected_ffs())
            touchstone = guessed
        self.s2p_field.setText(display_workspace_path(touchstone))
        technical_data = resolve_project_path(THIS_DIR, project.technical_data_file)
        self.technical_data_field.setText(display_workspace_path(technical_data))
        legacy_presets_migrated = self._migrate_legacy_project_presets(project.presets)
        self.project_active_preset = project.active_preset.strip()
        missing_preset = bool(self.project_active_preset and self.project_active_preset not in self.global_presets)
        self._apply_default_project_settings()
        if not missing_preset and self.project_active_preset:
            self.global_active_preset = self.project_active_preset
            self.apply_preset_values(self.global_presets.get(self.project_active_preset, {}))
        elif missing_preset:
            self.status(f"Preset '{self.project_active_preset}' is missing; using default settings")
            if project.settings:
                self.apply_preset_values(project.settings)
        elif project.settings:
            self.apply_preset_values(project.settings)
        self._persist_global_presets()
        self.refresh_preset_list(select_name=self.project_active_preset)
        self.store.set("beam_ffs", self.selected_ffs())
        self.store.set("vswr_s2p", touchstone)
        self.store.set("technical_data_xlsx", technical_data)
        self._loading_project = False
        self.refresh_radiation_frequency_list()
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
        self.store.set("technical_data_xlsx", self.selected_technical_data())
        self.refresh_derived_paths()

    def create_project(self) -> None:
        if not self._confirm_pending_changes("creating a new project"):
            return
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
            technical_data_file="",
            settings={},
            presets={},
            active_preset=self.current_preset_name(),
            radiation_pattern_frequencies_ghz=None,
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
        if not self._confirm_pending_changes("duplicating this project"):
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
        if not self._confirm_pending_changes("exporting this project"):
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
        if not self._confirm_pending_changes("importing a project bundle"):
            return
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

    def _set_technical_data(self, path: str) -> None:
        if is_url(path):
            resolved = str(path).strip()
            self.technical_data_field.setText(resolved)
        else:
            resolved = str(resolve_workspace_path(path)) if path else ""
            self.technical_data_field.setText(display_workspace_path(resolved))
        self.store.set("technical_data_xlsx", resolved)
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
        return PresetSettings.from_mapping({
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
            "cartesian_grid_line_width": float(self.cartesian_grid_line_width.value()),
            "polar_grid_line_width": float(self.polar_grid_line_width.value()),
            "cartesian_line_width": float(self.cartesian_line_width.value()),
            "cartesian_figure_width": float(self.cartesian_figure_width.value()),
            "cartesian_figure_height": float(self.cartesian_figure_height.value()),
            "polar_figure_size": float(self.polar_figure_size.value()),
            "polar_line_width": float(self.polar_line_width.value()),
            "cartesian_font_size": float(self.cartesian_font_size.value()),
            "polar_font_size": float(self.polar_font_size.value()),
            "cartesian_legend_font_size": float(self.cartesian_legend_font_size.value()),
            "polar_legend_font_size": float(self.polar_legend_font_size.value()),
            "plot_line_1": self.plot_line1.color(),
            "plot_line_2": self.plot_line2.color(),
            "polar_azimuth_line_1_color": self.polar_azimuth_line1.color(),
            "polar_azimuth_line_1_style": self.polar_azimuth_line1.style(),
            "polar_azimuth_line_2_color": self.polar_azimuth_line2.color(),
            "polar_azimuth_line_2_style": self.polar_azimuth_line2.style(),
            "polar_elevation_line_1_color": self.polar_elevation_line1.color(),
            "polar_elevation_line_1_style": self.polar_elevation_line1.style(),
            "polar_elevation_line_2_color": self.polar_elevation_line2.color(),
            "polar_elevation_line_2_style": self.polar_elevation_line2.style(),
            "beamwidth_3db_color": self.beamwidth_3db_color.color(),
            "beamwidth_6db_color": self.beamwidth_6db_color.color(),
            "beamwidth_10db_color": self.beamwidth_10db_color.color(),
            "gain_legend_labels": self.gain_legend_labels.text().strip(),
            "beamwidth_legend_labels": self.beamwidth_legend_labels.text().strip(),
            "beam_eff_legend_labels": self.beam_eff_legend_labels.text().strip(),
            "vswr_legend_labels": self.vswr_legend_labels.text().strip(),
            "datasheet_template": self.selected_datasheet_template_name(),
            "pdf_metadata_author": self.selected_pdf_metadata_author(),
            "rings": self.rings.text().strip(),
            "angle": int(self.angle_step.value()),
            "clip": float(self.clip_db.value()),
        }).to_dict()

    def current_preset_settings(self) -> PresetSettings:
        return PresetSettings.from_mapping(self.collect_preset_values())

    def apply_preset_values(self, values: dict[str, object]) -> None:
        if not values:
            return
        previous = self._applying_preset_values
        self._applying_preset_values = True
        try:
            self._apply_preset_values_unchecked(values)
        finally:
            self._applying_preset_values = previous

    def _apply_preset_values_unchecked(self, values: dict[str, object]) -> None:
        def value_or_legacy(primary: str, legacy: str) -> object | None:
            if primary in values:
                return values[primary]
            if legacy in values:
                return values[legacy]
            return None

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
        cartesian_grid_line_width = value_or_legacy("cartesian_grid_line_width", "plot_grid_line_width")
        if cartesian_grid_line_width is not None: self.cartesian_grid_line_width.setValue(float(cartesian_grid_line_width))
        polar_grid_line_width = value_or_legacy("polar_grid_line_width", "plot_grid_line_width")
        if polar_grid_line_width is not None: self.polar_grid_line_width.setValue(float(polar_grid_line_width))
        cartesian_line_width = value_or_legacy("cartesian_line_width", "plot_line_width")
        if cartesian_line_width is not None: self.cartesian_line_width.setValue(float(cartesian_line_width))
        if "cartesian_figure_width" in values: self.cartesian_figure_width.setValue(float(values["cartesian_figure_width"]))
        if "cartesian_figure_height" in values: self.cartesian_figure_height.setValue(float(values["cartesian_figure_height"]))
        if "polar_figure_size" in values: self.polar_figure_size.setValue(float(values["polar_figure_size"]))
        polar_line_width = value_or_legacy("polar_line_width", "plot_line_width")
        if polar_line_width is not None: self.polar_line_width.setValue(float(polar_line_width))
        cartesian_font_size = value_or_legacy("cartesian_font_size", "plot_font_size")
        if cartesian_font_size is not None: self.cartesian_font_size.setValue(float(cartesian_font_size))
        polar_font_size = value_or_legacy("polar_font_size", "plot_font_size")
        if polar_font_size is not None: self.polar_font_size.setValue(float(polar_font_size))
        cartesian_legend_font_size = value_or_legacy("cartesian_legend_font_size", "plot_legend_font_size")
        if cartesian_legend_font_size is not None: self.cartesian_legend_font_size.setValue(float(cartesian_legend_font_size))
        polar_legend_font_size = value_or_legacy("polar_legend_font_size", "plot_legend_font_size")
        if polar_legend_font_size is not None: self.polar_legend_font_size.setValue(float(polar_legend_font_size))
        if "plot_line_1" in values: self.plot_line1.set_color(str(values["plot_line_1"]))
        if "plot_line_2" in values: self.plot_line2.set_color(str(values["plot_line_2"]))
        if "polar_azimuth_line_1_color" in values or "plot_line_1" in values:
            self.polar_azimuth_line1.set_color(str(values.get("polar_azimuth_line_1_color", values.get("plot_line_1"))))
        if "polar_azimuth_line_2_color" in values or "plot_line_2" in values:
            self.polar_azimuth_line2.set_color(str(values.get("polar_azimuth_line_2_color", values.get("plot_line_2"))))
        if "polar_elevation_line_1_color" in values or "plot_line_1" in values:
            self.polar_elevation_line1.set_color(str(values.get("polar_elevation_line_1_color", values.get("plot_line_1"))))
        if "polar_elevation_line_2_color" in values or "plot_line_2" in values:
            self.polar_elevation_line2.set_color(str(values.get("polar_elevation_line_2_color", values.get("plot_line_2"))))
        if "polar_azimuth_line_1_style" in values: self.polar_azimuth_line1.set_style(str(values["polar_azimuth_line_1_style"]))
        if "polar_azimuth_line_2_style" in values: self.polar_azimuth_line2.set_style(str(values["polar_azimuth_line_2_style"]))
        if "polar_elevation_line_1_style" in values: self.polar_elevation_line1.set_style(str(values["polar_elevation_line_1_style"]))
        if "polar_elevation_line_2_style" in values: self.polar_elevation_line2.set_style(str(values["polar_elevation_line_2_style"]))
        if "beamwidth_3db_color" in values: self.beamwidth_3db_color.set_color(str(values["beamwidth_3db_color"]))
        if "beamwidth_6db_color" in values: self.beamwidth_6db_color.set_color(str(values["beamwidth_6db_color"]))
        if "beamwidth_10db_color" in values: self.beamwidth_10db_color.set_color(str(values["beamwidth_10db_color"]))
        if "gain_legend_labels" in values: self.gain_legend_labels.setText(str(values["gain_legend_labels"]))
        if "beamwidth_legend_labels" in values: self.beamwidth_legend_labels.setText(str(values["beamwidth_legend_labels"]))
        if "beam_eff_legend_labels" in values: self.beam_eff_legend_labels.setText(str(values["beam_eff_legend_labels"]))
        if "vswr_legend_labels" in values: self.vswr_legend_labels.setText(str(values["vswr_legend_labels"]))
        if "datasheet_template" in values:
            self.refresh_datasheet_template_options(str(values["datasheet_template"]))
            self.store.set("datasheet_template", self.selected_datasheet_template_name())
        if "pdf_metadata_author" in values: self.pdf_metadata_author.setText(str(values["pdf_metadata_author"]))
        if "rings" in values: self.rings.setText(str(values["rings"]))
        if "angle" in values: self.angle_step.setValue(int(values["angle"]))
        if "clip" in values: self.clip_db.setValue(float(values["clip"]))

    def on_preset_selected(self, _text: str) -> None:
        if self._reverting_preset_selection or self._loading_project:
            return
        name = self.current_preset_name()
        previous_name = self._active_preset_for_dirty_check()
        if name != previous_name and not self._confirm_pending_changes("switching presets", include_project=False):
            self._reverting_preset_selection = True
            self.preset_combo.blockSignals(True)
            restore_index = self.preset_combo.findData(previous_name)
            self.preset_combo.setCurrentIndex(restore_index if restore_index >= 0 else 0)
            self.preset_combo.blockSignals(False)
            self._reverting_preset_selection = False
            self._update_preset_action_state()
            return
        self.project_active_preset = name
        self.global_active_preset = name if name in self.global_presets else ""
        self._persist_global_presets()
        if not name:
            self._mark_project_dirty()
            self._update_preset_action_state()
            return
        values = self.global_presets.get(name, {})
        if isinstance(values, dict):
            self.apply_preset_values(values)
        self._mark_project_dirty()
        self._update_preset_action_state()

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
        self._save_active_preset(refresh=True)

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

    def _item_port_label(self, item: QListWidgetItem) -> str:
        return str(item.data(Qt.UserRole + 1) or "").strip()

    def _default_port_label_for_path(self, path: str) -> str:
        return detect_polarization(Path(path).stem) or ""

    def _refresh_ffs_item_display(self, item: QListWidgetItem) -> None:
        path = self._item_path(item)
        enabled = item.checkState() == Qt.Checked
        suffixes: list[str] = []
        if not enabled:
            suffixes.append("disabled")
        if path and not Path(path).exists():
            suffixes.append("missing")
        label = display_workspace_path(path)
        port_label = self._item_port_label(item)
        if port_label:
            label += f"  |  Port: {port_label}"
        if suffixes:
            label += " [" + ", ".join(suffixes) + "]"
        previous = self._suppress_ffs_item_change
        self._suppress_ffs_item_change = True
        item.setText(label)
        item.setToolTip(path)
        self._suppress_ffs_item_change = previous

    def _make_ffs_item(self, path: str, enabled: bool = True, port_label: str = "") -> QListWidgetItem:
        actual = str(resolve_workspace_path(path))
        item = QListWidgetItem()
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        item.setData(Qt.UserRole, actual)
        item.setData(Qt.UserRole + 1, str(port_label).strip())
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
            item = self._make_ffs_item(path, bool(entry.get("enabled", True)), str(entry.get("port_label", "")).strip())
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
        selected_items = self.ffs_list.selectedItems()
        selected = bool(selected_items)
        count = self.ffs_list.count()
        self.remove_ffs_button.setEnabled(has_project and selected)
        self.ffs_port_label_field.setEnabled(has_project and selected)
        previous = self.ffs_port_label_field.blockSignals(True)
        self.ffs_port_label_field.setText(self._item_port_label(selected_items[0]) if selected else "")
        self.ffs_port_label_field.blockSignals(previous)
        self.clear_ffs_button.setEnabled(has_project and count > 0)
        self.ffs_up_button.setEnabled(has_project and selected)
        self.ffs_down_button.setEnabled(has_project and selected)

    def _add_ffs_files(self, files: list[object], save: bool = True):
        existing = {self._item_path(self.ffs_list.item(i)) for i in range(self.ffs_list.count())}
        added = False
        self._suppress_ffs_item_change = True
        for raw in files:
            if isinstance(raw, dict):
                path = str(raw.get("path", "")).strip()
                enabled = bool(raw.get("enabled", True))
                port_label = str(raw.get("port_label", "")).strip()
            else:
                path = str(raw).strip()
                enabled = True
                port_label = self._default_port_label_for_path(path)
            actual = str(resolve_workspace_path(path))
            if actual.lower().endswith(".ffs") and actual not in existing:
                item = self._make_ffs_item(actual, enabled, port_label)
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

    def edit_selected_ffs_port_label(self) -> None:
        selected = self.ffs_list.selectedItems()
        if not selected:
            return
        item = selected[0]
        current = self._item_port_label(item)
        label, ok = QInputDialog.getText(self, "Port Label", "Legend label for selected far-field file:", text=current)
        if not ok:
            return
        label = label.strip()
        if label == current:
            return
        item.setData(Qt.UserRole + 1, label)
        self._refresh_ffs_item_display(item)
        previous = self.ffs_port_label_field.blockSignals(True)
        self.ffs_port_label_field.setText(label)
        self.ffs_port_label_field.blockSignals(previous)
        self._mark_project_dirty()

    def update_selected_ffs_port_label(self, text: str) -> None:
        selected = self.ffs_list.selectedItems()
        if not selected or self._loading_project:
            return
        item = selected[0]
        label = text.strip()
        if label == self._item_port_label(item):
            return
        item.setData(Qt.UserRole + 1, label)
        self._refresh_ffs_item_display(item)
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

    def browse_technical_data(self):
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        fn, _ = QFileDialog.getOpenFileName(self, "Select Technical Data", str(THIS_DIR), "Excel Workbooks (*.xlsx *.xlsm)")
        if fn:
            self._set_technical_data(fn)

    def use_google_sheet_technical_data(self):
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        current = self.selected_technical_data() if self.technical_data_is_google_sheet() else ""
        url, ok = QInputDialog.getText(self, "Use Google Sheet", "Google Sheet URL:", text=current)
        url = url.strip()
        if not ok or not url:
            return
        if not is_google_sheet_url(url) or not extract_google_sheet_id(url):
            QMessageBox.warning(self, "Invalid Google Sheet", "Enter a Google Sheets URL like https://docs.google.com/spreadsheets/d/<id>/edit.")
            return
        self._set_technical_data(url)

    def open_technical_data_source(self):
        source = self.selected_technical_data()
        if not source:
            return
        if is_url(source):
            open_in_file_manager(source)
            return
        open_in_file_manager(resolve_workspace_path(source))

    def configure_google_sheet_credentials(self):
        client_path = self.google_sheets_oauth_client_path()
        start_dir = client_path.parent if client_path.exists() else THIS_DIR
        path, _ = QFileDialog.getOpenFileName(self, "Select Google OAuth Client JSON", str(start_dir), "JSON (*.json)")
        if path:
            self.store.set(GOOGLE_SHEETS_OAUTH_CLIENT_KEY, str(Path(path).resolve()))
        elif not client_path.exists():
            return
        try:
            self._ensure_google_sheets_credentials(interactive=True)
        except Exception as exc:
            QMessageBox.warning(self, "Google Sign In Failed", str(exc))
            return
        self.status("Google Sheets sign-in is ready")
        self.refresh_derived_paths()

    def clear_technical_data(self):
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        self._set_technical_data("")

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
        if not self._confirm_pending_changes("exiting"):
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
