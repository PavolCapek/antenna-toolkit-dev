#!/usr/bin/env python3
"""
Antenna Toolkit — PySide6 UI (Nova-QT)

Drop-in GUI for your existing CLI scripts:
  - beamwidth_xlsx.py
  - plot.py
  - plot_vswr.py

Highlights
- Clean, modern PySide6 interface (Fusion theme with light/dark toggle)
- Non-blocking process runner (QProcess) with live console updates
- Drag & drop support for .ffs and .s2p files
- Clickable file/link buttons that open in your OS file manager
- Persists UI settings between runs (paths, options, theme, console filter, window size, splitter)
- One-click FULL pipeline: Beamwidth → Plots
- Console filters (All / Stdout only / Errors only / Compact)
- Progress bar shows live updates; switches to percentage if a line like "42%" appears

Dependencies
  pip install PySide6 numpy pandas matplotlib openpyxl

Author: ChatGPT
"""
from __future__ import annotations
import os, sys, json, platform, shlex, re, time
from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, QProcess, QTimer, QUrl, QProcessEnvironment, QByteArray
from PySide6.QtGui import QDesktopServices, QIcon, QPalette, QColor, QAction, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QVBoxLayout, QHBoxLayout,
    QSplitter, QGroupBox, QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QFormLayout, QStyleFactory,
    QProgressBar, QAbstractItemView, QColorDialog, QFrame, QMessageBox, QInputDialog
)

APP_TITLE = "Antenna Toolkit — Nova-QT"
THIS_DIR = Path(__file__).resolve().parent
SCRIPT_BEAM = str(THIS_DIR / "beamwidth_xlsx.py")
SCRIPT_EXTRACT = str(THIS_DIR / "extract_data_xlsx.py")
SCRIPT_DATASHEET = str(THIS_DIR / "datasheet_pdf.py")
SCRIPT_PLOT = str(THIS_DIR / "plot.py")
SCRIPT_VSWR = str(THIS_DIR / "plot_vswr.py")
STATE_FILE = THIS_DIR / ".nova_qt_state.json"
RESULTS_DIR = THIS_DIR / "Results"
DEFAULT_GRID_COLOR = "#6f7a81"
DEFAULT_LINE_COLORS = [
    ("Sky", "#2bb6f6"),
    ("Amber", "#f5a623"),
    ("Coral", "#ef6c5b"),
    ("Pine", "#2f8f6b"),
    ("Slate", "#5b6c7d"),
]
PRESET_STORE_KEY = "ui_presets"
ACTIVE_PRESET_KEY = "active_preset"
PRESET_KEYS = [
    "smooth",
    "theta",
    "smooth2",
    "shared_xstep",
    "shared_fmin",
    "shared_fmax",
    "shared_xlog",
    "gain_ymin",
    "gain_ymax",
    "gain_y_step",
    "beamwidth_ymin",
    "beamwidth_ymax",
    "beamwidth_y_step",
    "beam_eff_ymin",
    "beam_eff_ymax",
    "beam_eff_y_step",
    "vswr_ymin",
    "vswr_ymax",
    "vswr_ystep",
    "vswr_smooth",
    "grid_color",
    "plot_line_1",
    "plot_line_2",
    "rings",
    "angle",
    "clip",
]


def suggest_preset_name(existing_names: list[str], base_name: str) -> str:
    base = trim_project_token(base_name) or "Preset"
    if base not in existing_names:
        return base
    idx = 2
    while f"{base} {idx}" in existing_names:
        idx += 1
    return f"{base} {idx}"


def normalize_preset_payload(payload: object) -> dict[str, dict[str, object]]:
    if isinstance(payload, dict) and "presets" in payload:
        payload = payload.get("presets", {})
    if not isinstance(payload, dict):
        return {}
    clean: dict[str, dict[str, object]] = {}
    for name, values in payload.items():
        if not isinstance(name, str) or not isinstance(values, dict):
            continue
        clean[name] = {key: value for key, value in values.items() if key in PRESET_KEYS}
    return clean

# ---------------------------------------------------------
# Utilities
# ---------------------------------------------------------

def which_python() -> str:
    return sys.executable or "python3"

def is_win() -> bool:
    return os.name == "nt"

def open_in_file_manager(path: str | Path):
    if not path:
        return
    p = Path(path)
    try:
        if is_win():
            os.startfile(p)  # type: ignore
        elif sys.platform == "darwin":
            if p.is_file():
                os.system(f"open -R {shlex.quote(str(p))}")
            else:
                os.system(f"open {shlex.quote(str(p))}")
        else:
            os.system(f"xdg-open {shlex.quote(str(p if p.is_dir() else p.parent))} >/dev/null 2>&1 &")
    except Exception:
        pass


def resolve_workspace_path(path: str | Path | None) -> Path:
    if not path:
        return THIS_DIR
    p = Path(path)
    return p.resolve() if p.is_absolute() else (THIS_DIR / p).resolve()


def display_workspace_path(path: str | Path | None) -> str:
    if not path:
        return ""
    p = resolve_workspace_path(path)
    try:
        return str(p.relative_to(THIS_DIR))
    except ValueError:
        return str(p)


def display_command_part(part: str) -> str:
    if not part or part.startswith("-"):
        return part
    if any(sep in part for sep in ("\\", "/")):
        return display_workspace_path(part)
    return part

class Persist:
    def __init__(self, path: Path):
        self.path = path
        self.data = {}
        try:
            if path.exists():
                self.data = json.loads(path.read_text())
        except Exception:
            self.data = {}
    def get(self, key: str, default=None):
        return self.data.get(key, default)
    def set(self, key: str, value):
        self.data[key] = value
        try:
            self.path.write_text(json.dumps(self.data, indent=2))
        except Exception:
            pass


def normalize_color(value: str | None, fallback: str) -> str:
    color = QColor(value or fallback)
    return color.name() if color.isValid() else QColor(fallback).name()


def trim_project_token(token: str) -> str:
    return re.sub(r"[_\-\s]+$", "", token.strip())


def normalized_project_stem(stem: str) -> str:
    tokens = [t for t in re.split(r"[_\-\s]+", stem) if t]
    removable = {
        "horizontal", "vertical", "azimuth", "elevation",
        "phi0", "phi90", "port1", "port2", "h", "v",
    }
    while tokens and tokens[-1].lower() in removable:
        tokens.pop()
    return "_".join(tokens) if tokens else stem


def deduce_project_name(paths: list[str]) -> str:
    stems = [normalized_project_stem(Path(p).stem) for p in paths if p]
    if not stems:
        return "results"
    if len(stems) == 1:
        return trim_project_token(stems[0]) or "results"

    common = trim_project_token(os.path.commonprefix(stems))
    if common:
        return common

    split_stems = [re.split(r"[_\-\s]+", stem) for stem in stems]
    shared: list[str] = []
    for group in zip(*split_stems):
        if len({item.lower() for item in group}) == 1:
            shared.append(group[0])
        else:
            break
    if shared:
        return "_".join(shared)
    return trim_project_token(stems[0]) or "results"


class ColorSelector(QWidget):
    def __init__(self, store: Persist, key: str, default: str):
        super().__init__()
        self.store = store
        self.key = key
        self.custom_color = normalize_color(store.get(key, default), default)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.combo = QComboBox()
        for name, value in DEFAULT_LINE_COLORS:
            self.combo.addItem(f"{name} ({value})", value)
        self.combo.addItem("Custom", "__custom__")
        self.combo.currentIndexChanged.connect(self._on_combo_changed)

        self.swatch = QFrame()
        self.swatch.setFixedSize(18, 18)
        self.swatch.setFrameShape(QFrame.StyledPanel)

        self.pick = QPushButton()
        self.pick.setFixedWidth(90)
        self.pick.clicked.connect(self.pick_color)

        lay.addWidget(self.combo, 1)
        lay.addWidget(self.swatch)
        lay.addWidget(self.pick)
        self.set_color(self.custom_color, persist=False)

    def color(self) -> str:
        return self.current_color

    def set_color(self, value: str, persist: bool = True):
        color = normalize_color(value, self.custom_color)
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

    def _on_combo_changed(self):
        value = self.combo.currentData()
        if value == "__custom__":
            self.set_color(self.custom_color)
            return
        self.set_color(str(value))

    def pick_color(self):
        color = QColorDialog.getColor(QColor(self.current_color), self, "Select color")
        if color.isValid():
            self.set_color(color.name())

# ---------------------------------------------------------
# Process runner
# ---------------------------------------------------------
class Proc:
    def __init__(self, window: "MainWindow"):
        self.win = window
        self.proc = QProcess()
        # Separate channels so we can filter/colour
        self.proc.setProcessChannelMode(QProcess.SeparateChannels)
        # Ensure unbuffered Python output from children
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        self.proc.setProcessEnvironment(env)
        self.proc.readyReadStandardOutput.connect(self._on_out_stdout)
        self.proc.readyReadStandardError.connect(self._on_out_stderr)
        self.proc.finished.connect(self._on_finished)
        self.queue: List[list[str]] = []
        self.running_cmd: List[str] | None = None

    def enqueue(self, args: List[str]):
        self.queue.append(args)
        if self.running_cmd is None:
            self._dequeue_and_start()

    def _dequeue_and_start(self):
        if not self.queue:
            self.running_cmd = None
            self.win.set_busy(False)
            self.win.on_proc_finished()
            return
        self.running_cmd = self.queue.pop(0)
        program = self.running_cmd[0]
        args = self.running_cmd[1:]
        base = Path(program).name.lower()
        if base in ("python", "python3", "python.exe", "python3.exe") and (not args or args[0] != "-u"):
            args = ["-u"] + args
        self.win.set_busy(True)
        cmd_str = " ".join([display_command_part(program)] + [display_command_part(arg) for arg in args])
        self.win.on_proc_started(cmd_str)
        if hasattr(self.win, "on_proc_step_started"):
            try:
                self.win.on_proc_step_started(list(self.running_cmd), cmd_str)
            except Exception:
                pass
        self.win.log(f"\n$ {cmd_str}\n", color="#8aa2b8", channel="meta")
        self.proc.start(program, args)

    def stop(self):
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self.proc.kill()
        self.queue.clear()
        self.running_cmd = None
        self.win.set_busy(False)
        self.win.on_proc_finished()

    def _on_out_stdout(self):
        data = bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
        if data:
            self.win.log(data, channel="stdout")
            self._maybe_progress_from_text(data)

    def _on_out_stderr(self):
        data = bytes(self.proc.readAllStandardError()).decode(errors="replace")
        if data:
            self.win.log(data, color="#ff8a80", channel="stderr")
            self._maybe_progress_from_text(data)

    def _maybe_progress_from_text(self, text: str):
        m = re.search(r"(\b\d{1,3})%", text)
        if m:
            pct = max(0, min(100, int(m.group(1))))
            self.win.set_progress(pct)

    def _on_finished(self, exit_code=0, exit_status=None):
        self.win.set_busy(False)
        self.win.set_progress(None)
        if hasattr(self.win, "on_proc_step_finished"):
            try:
                self.win.on_proc_step_finished(list(self.running_cmd or []), int(exit_code), exit_status)
            except Exception:
                pass
        self.win.on_proc_finished()
        self._dequeue_and_start()

# ---------------------------------------------------------
# Widgets (Sections)
# ---------------------------------------------------------
class BeamSection(QGroupBox):
    def __init__(self, win: "MainWindow"):
        super().__init__("1) Beamwidth → XLSX (beamwidth_xlsx.py)")
        self.win = win
        lay = QVBoxLayout(self)

        # Output xlsx
        row = QHBoxLayout(); lay.addLayout(row)
        row.addWidget(QLabel("Derived workbook (.xlsx):"))
        self.out_xlsx = QLineEdit("")
        self.out_xlsx.setReadOnly(True)
        row.addWidget(self.out_xlsx, 1)
        b = QPushButton("Browse…"); b.clicked.connect(self.browse_out)
        row.addWidget(b)
        b.hide()
        openb = QPushButton("Open folder"); openb.clicked.connect(lambda: open_in_file_manager(resolve_workspace_path(self.out_xlsx.text())))
        row.addWidget(openb)

        # FFS list + controls
        lay.addWidget(QLabel("Selected far‑field files (.ffs):"))
        self.list = QListWidget(); self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setAcceptDrops(True); self.list.viewport().setAcceptDrops(True)
        self.list.setDragDropMode(QAbstractItemView.DropOnly)
        self.list.dragEnterEvent = self._drag_enter  # type: ignore
        self.list.dropEvent = self._drop  # type: ignore
        lay.addWidget(self.list, 1)

        ctr = QHBoxLayout(); lay.addLayout(ctr)
        addb = QPushButton("Add .ffs…"); addb.clicked.connect(self.add_ffs)
        rem = QPushButton("Remove selected"); rem.clicked.connect(self.remove_sel)
        clr = QPushButton("Clear"); clr.clicked.connect(self.clear_all)
        for w in (addb, rem, clr): ctr.addWidget(w)
        ctr.addStretch(1)

        # Options
        opt = QFormLayout(); lay.addLayout(opt)
        self.smooth = QSpinBox(); self.smooth.setRange(1,99); self.smooth.setValue(int(win.store.get("smooth",5)))
        self.smooth.valueChanged.connect(lambda v: self.win.store.set("smooth", int(v)))
        self.theta = QDoubleSpinBox(); self.theta.setRange(0.0,90.0); self.theta.setSingleStep(0.5); self.theta.setValue(float(win.store.get("theta",8.0)))
        self.theta.valueChanged.connect(lambda v: self.win.store.set("theta", float(v)))
        opt.addRow("Smooth (samples):", self.smooth)
        opt.addRow("Theta window (deg):", self.theta)

        run = QPushButton("Run beamwidth_xlsx ▶"); run.clicked.connect(self.run)
        lay.addWidget(run, alignment=Qt.AlignRight)
        self.update_derived_paths()

        # Load any persisted .ffs list
        for p in self.win.store.get("beam_ffs", []):
            self._add_files([p], save=False)
        self.update_derived_paths()

    # drag & drop helpers
    def _drag_enter(self, e):
        if any(u.toLocalFile().lower().endswith(".ffs") for u in e.mimeData().urls()):
            e.acceptProposedAction()
    def _drop(self, e):
        self._add_files([u.toLocalFile() for u in e.mimeData().urls()])
        e.acceptProposedAction()

    def browse_out(self):
        fn, _ = QFileDialog.getSaveFileName(self, "Save Excel", self.out_xlsx.text(), "Excel (*.xlsx)")
        if fn:
            if not fn.lower().endswith(".xlsx"): fn += ".xlsx"
            self.out_xlsx.setText(display_workspace_path(fn))
            self.win.store.set("beam_out", fn)

    def add_ffs(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add .ffs", str(THIS_DIR), "CST Farfield (*.ffs)")
        self._add_files(files)

    def remove_sel(self):
        for it in list(self.list.selectedItems()):
            self.list.takeItem(self.list.row(it))
        self._save_ffs()

    def clear_all(self):
        self.list.clear()
        self._save_ffs()

    def _save_ffs(self):
        ffs = self.actual_paths()
        self.win.store.set("beam_ffs", ffs)
        self.win.refresh_derived_paths()

    def _add_files(self, files: list[str], save: bool = True):
        existing = {self.actual_path_for_item(self.list.item(i)) for i in range(self.list.count())}
        for path in files:
            actual_path = str(resolve_workspace_path(path))
            if actual_path.lower().endswith(".ffs") and actual_path not in existing:
                item = QListWidgetItem(display_workspace_path(actual_path))
                item.setData(Qt.UserRole, actual_path)
                self.list.addItem(item)
                existing.add(actual_path)
        if save:
            self._save_ffs()

    def actual_path_for_item(self, item: QListWidgetItem) -> str:
        return item.data(Qt.UserRole) or str(resolve_workspace_path(item.text()))

    def actual_paths(self) -> list[str]:
        return [self.actual_path_for_item(self.list.item(i)) for i in range(self.list.count())]

    def update_derived_paths(self):
        self.out_xlsx.setText(display_workspace_path(self.win.deduced_beam_output()))

    def run(self):
        out = str(resolve_workspace_path(self.out_xlsx.text().strip()))
        ffs = self.actual_paths()
        if not ffs:
            self.win.status("Add at least one .ffs")
            return
        args = [which_python(), "-u", SCRIPT_BEAM, out]
        args += ffs
        args += ["--smooth", str(self.smooth.value()), "--theta-window", str(self.theta.value())]
        self.win.proc.enqueue(args)


class SharedAxisSection(QGroupBox):
    def __init__(self, win: "MainWindow"):
        super().__init__("Shared Frequency / X Axis")
        self.win = win
        lay = QVBoxLayout(self)

        form = QFormLayout()
        lay.addLayout(form)

        xstep_value = self.win.store.get("shared_xstep", self.win.store.get("xstep", self.win.store.get("vswr_xstep", 0.2)))
        fmin_value = self.win.store.get("shared_fmin", self.win.store.get("plot_fmin", self.win.store.get("vswr_fmin", 0.0)))
        fmax_value = self.win.store.get("shared_fmax", self.win.store.get("plot_fmax", self.win.store.get("vswr_fmax", 0.0)))
        xlog_value = self.win.store.get("shared_xlog", self.win.store.get("plot_xlog", self.win.store.get("vswr_xlog", False)))

        self.xstep = QDoubleSpinBox(); self.xstep.setRange(0.01, 10.0); self.xstep.setSingleStep(0.01); self.xstep.setValue(float(xstep_value))
        self.xstep.valueChanged.connect(lambda v: self.win.store.set("shared_xstep", float(v)))
        self.fmin = QDoubleSpinBox(); self.fmin.setRange(0.0, 1000.0); self.fmin.setDecimals(6); self.fmin.setValue(float(fmin_value))
        self.fmin.valueChanged.connect(lambda v: self.win.store.set("shared_fmin", float(v)))
        self.fmax = QDoubleSpinBox(); self.fmax.setRange(0.0, 1000.0); self.fmax.setDecimals(6); self.fmax.setValue(float(fmax_value))
        self.fmax.valueChanged.connect(lambda v: self.win.store.set("shared_fmax", float(v)))
        self.xlog = QComboBox(); self.xlog.addItems(["Linear", "Log"]); self.xlog.setCurrentText("Log" if bool(xlog_value) else "Linear")
        self.xlog.currentTextChanged.connect(lambda text: self.win.store.set("shared_xlog", text == "Log"))

        form.addRow("X tick step (GHz):", self.xstep)
        form.addRow("fmin (GHz, opt):", self.fmin)
        form.addRow("fmax (GHz, opt):", self.fmax)
        form.addRow("X axis:", self.xlog)

    def use_log_scale(self) -> bool:
        return self.xlog.currentText() == "Log"


class YRangeSection(QGroupBox):
    def __init__(self, win: "MainWindow"):
        super().__init__("Y-Axis Ranges")
        self.win = win
        lay = QVBoxLayout(self)
        form = QFormLayout()
        lay.addLayout(form)

        self.gain_ymin = QDoubleSpinBox(); self.gain_ymin.setRange(-1000.0, 1000.0); self.gain_ymin.setDecimals(6); self.gain_ymin.setValue(float(self.win.store.get("gain_ymin", 0.0)))
        self.gain_ymin.valueChanged.connect(lambda v: self.win.store.set("gain_ymin", float(v)))
        self.gain_ymax = QDoubleSpinBox(); self.gain_ymax.setRange(-1000.0, 1000.0); self.gain_ymax.setDecimals(6); self.gain_ymax.setValue(float(self.win.store.get("gain_ymax", 0.0)))
        self.gain_ymax.valueChanged.connect(lambda v: self.win.store.set("gain_ymax", float(v)))
        self.gain_ystep = QDoubleSpinBox(); self.gain_ystep.setRange(0.0, 1000.0); self.gain_ystep.setDecimals(6); self.gain_ystep.setSingleStep(0.5); self.gain_ystep.setValue(float(self.win.store.get("gain_y_step", 0.0)))
        self.gain_ystep.valueChanged.connect(lambda v: self.win.store.set("gain_y_step", float(v)))
        self.bw_ymin = QDoubleSpinBox(); self.bw_ymin.setRange(-1000.0, 1000.0); self.bw_ymin.setDecimals(6); self.bw_ymin.setValue(float(self.win.store.get("beamwidth_ymin", 0.0)))
        self.bw_ymin.valueChanged.connect(lambda v: self.win.store.set("beamwidth_ymin", float(v)))
        self.bw_ymax = QDoubleSpinBox(); self.bw_ymax.setRange(-1000.0, 1000.0); self.bw_ymax.setDecimals(6); self.bw_ymax.setValue(float(self.win.store.get("beamwidth_ymax", 0.0)))
        self.bw_ymax.valueChanged.connect(lambda v: self.win.store.set("beamwidth_ymax", float(v)))
        self.bw_ystep = QDoubleSpinBox(); self.bw_ystep.setRange(0.0, 1000.0); self.bw_ystep.setDecimals(6); self.bw_ystep.setSingleStep(0.5); self.bw_ystep.setValue(float(self.win.store.get("beamwidth_y_step", 0.0)))
        self.bw_ystep.valueChanged.connect(lambda v: self.win.store.set("beamwidth_y_step", float(v)))
        self.be_ymin = QDoubleSpinBox(); self.be_ymin.setRange(-1000.0, 1000.0); self.be_ymin.setDecimals(6); self.be_ymin.setValue(float(self.win.store.get("beam_eff_ymin", 0.0)))
        self.be_ymin.valueChanged.connect(lambda v: self.win.store.set("beam_eff_ymin", float(v)))
        self.be_ymax = QDoubleSpinBox(); self.be_ymax.setRange(-1000.0, 1000.0); self.be_ymax.setDecimals(6); self.be_ymax.setValue(float(self.win.store.get("beam_eff_ymax", 0.0)))
        self.be_ymax.valueChanged.connect(lambda v: self.win.store.set("beam_eff_ymax", float(v)))
        self.be_ystep = QDoubleSpinBox(); self.be_ystep.setRange(0.0, 1000.0); self.be_ystep.setDecimals(6); self.be_ystep.setSingleStep(0.5); self.be_ystep.setValue(float(self.win.store.get("beam_eff_y_step", 0.0)))
        self.be_ystep.valueChanged.connect(lambda v: self.win.store.set("beam_eff_y_step", float(v)))
        self.vswr_ymin = QDoubleSpinBox(); self.vswr_ymin.setRange(0.0, 1000.0); self.vswr_ymin.setDecimals(6); self.vswr_ymin.setValue(float(self.win.store.get("vswr_ymin", 1.0)))
        self.vswr_ymin.valueChanged.connect(lambda v: self.win.store.set("vswr_ymin", float(v)))
        self.vswr_ymax = QDoubleSpinBox(); self.vswr_ymax.setRange(0.0, 1000.0); self.vswr_ymax.setDecimals(6); self.vswr_ymax.setValue(float(self.win.store.get("vswr_ymax", 10.0)))
        self.vswr_ymax.valueChanged.connect(lambda v: self.win.store.set("vswr_ymax", float(v)))
        self.vswr_ystep = QDoubleSpinBox(); self.vswr_ystep.setRange(0.01, 1000.0); self.vswr_ystep.setDecimals(6); self.vswr_ystep.setSingleStep(0.5); self.vswr_ystep.setValue(float(self.win.store.get("vswr_ystep", 1.0)))
        self.vswr_ystep.valueChanged.connect(lambda v: self.win.store.set("vswr_ystep", float(v)))

        form.addRow("Gain y min:", self.gain_ymin)
        form.addRow("Gain y max:", self.gain_ymax)
        form.addRow("Gain y tick:", self.gain_ystep)
        form.addRow("Beamwidth y min:", self.bw_ymin)
        form.addRow("Beamwidth y max:", self.bw_ymax)
        form.addRow("Beamwidth y tick:", self.bw_ystep)
        form.addRow("Beam eff y min:", self.be_ymin)
        form.addRow("Beam eff y max:", self.be_ymax)
        form.addRow("Beam eff y tick:", self.be_ystep)
        form.addRow("VSWR y min:", self.vswr_ymin)
        form.addRow("VSWR y max:", self.vswr_ymax)
        form.addRow("VSWR y tick:", self.vswr_ystep)

class PlotSection(QGroupBox):
    def __init__(self, win: "MainWindow"):
        super().__init__("2) Plots from Excel (plot.py)")
        self.win = win
        lay = QVBoxLayout(self)

        # input xlsx
        r1 = QHBoxLayout(); lay.addLayout(r1)
        r1.addWidget(QLabel("Derived workbook (.xlsx):"))
        self.in_xlsx = QLineEdit("")
        self.in_xlsx.setReadOnly(True)
        r1.addWidget(self.in_xlsx, 1)
        b1 = QPushButton("Browse…"); b1.clicked.connect(self.browse_in); r1.addWidget(b1)
        b1.hide()
        o1 = QPushButton("Open"); o1.clicked.connect(lambda: open_in_file_manager(resolve_workspace_path(self.in_xlsx.text()))); r1.addWidget(o1)

        # out dir
        r2 = QHBoxLayout(); lay.addLayout(r2)
        r2.addWidget(QLabel("Result folder:"))
        self.out_dir = QLineEdit("")
        self.out_dir.setReadOnly(True)
        r2.addWidget(self.out_dir, 1)
        b2 = QPushButton("Browse…"); b2.clicked.connect(self.browse_out); r2.addWidget(b2)
        b2.hide()
        o2 = QPushButton("Open"); o2.clicked.connect(lambda: open_in_file_manager(resolve_workspace_path(self.out_dir.text()))); r2.addWidget(o2)

        # options
        form = QFormLayout(); lay.addLayout(form)
        self.grid = QLineEdit(self.win.store.get("grid_color", "#6f7a81"))
        self.grid.textChanged.connect(lambda v: self.win.store.set("grid_color", v))
        self.line1 = ColorSelector(self.win.store, "plot_line_1", DEFAULT_LINE_COLORS[0][1])
        self.line2 = ColorSelector(self.win.store, "plot_line_2", DEFAULT_LINE_COLORS[1][1])
        self.rings = QLineEdit(self.win.store.get("rings", "0,-7.5,-15,-22.5,-30"))
        self.rings.textChanged.connect(lambda v: self.win.store.set("rings", v))
        self.ang = QSpinBox(); self.ang.setRange(5,90); self.ang.setSingleStep(5); self.ang.setValue(int(self.win.store.get("angle",30)))
        self.ang.valueChanged.connect(lambda v: self.win.store.set("angle", int(v)))
        self.clip = QDoubleSpinBox(); self.clip.setRange(-120.0, 0.0); self.clip.setSingleStep(0.5); self.clip.setValue(float(self.win.store.get("clip", -30.0)))
        self.clip.valueChanged.connect(lambda v: self.win.store.set("clip", float(v)))
        self.smooth = QSpinBox(); self.smooth.setRange(1,99); self.smooth.setValue(int(self.win.store.get("smooth2",5)))
        self.smooth.valueChanged.connect(lambda v: self.win.store.set("smooth2", int(v)))
        form.addRow("Grid color:", self.grid)
        form.addRow("Line color 1:", self.line1)
        form.addRow("Line color 2:", self.line2)
        form.addRow("Rings (dB):", self.rings)
        form.addRow("Angle step (°):", self.ang)
        form.addRow("Clip below (dB):", self.clip)
        form.addRow("Smooth window:", self.smooth)

        run = QPushButton("Run plot ▶"); run.clicked.connect(self.run)
        lay.addWidget(run, alignment=Qt.AlignRight)
        self.update_derived_paths()

    def browse_in(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Open Excel", self.in_xlsx.text(), "Excel (*.xlsx)")
        if fn:
            self.in_xlsx.setText(display_workspace_path(fn)); self.win.store.set("plot_in", fn)
    def browse_out(self):
        dn = QFileDialog.getExistingDirectory(self, "Choose output directory", self.out_dir.text())
        if dn:
            self.out_dir.setText(display_workspace_path(dn)); self.win.store.set("plot_out", dn)

    def update_derived_paths(self):
        self.in_xlsx.setText(display_workspace_path(self.win.deduced_beam_output()))
        self.out_dir.setText(display_workspace_path(self.win.deduced_results_dir()))

    def run(self):
        xlsx = resolve_workspace_path(self.in_xlsx.text().strip())
        outd = resolve_workspace_path(self.out_dir.text().strip())
        if not xlsx.exists():
            self.win.status("Run beamwidth_xlsx or select .ffs files first")
            return
        args = [which_python(), "-u", SCRIPT_PLOT, str(xlsx),
                "--out-dir", str(outd),
                "--grid-color", self.grid.text().strip(),
                "--line-colors", ",".join([self.line1.color(), self.line2.color()]),
                "--rings", self.rings.text().strip(),
                "--angle-step", str(self.ang.value()),
                "--clip-db", str(self.clip.value()),
                "--smooth-window", str(self.smooth.value()),
                "--x-step", str(self.win.shared_axis.xstep.value())]
        if self.win.y_ranges.gain_ymin.value() != 0:
            args += ["--gain-ymin", f"{self.win.y_ranges.gain_ymin.value()}"]
        if self.win.y_ranges.gain_ymax.value() != 0:
            args += ["--gain-ymax", f"{self.win.y_ranges.gain_ymax.value()}"]
        if self.win.y_ranges.gain_ystep.value() != 0:
            args += ["--gain-y-step", f"{self.win.y_ranges.gain_ystep.value()}"]
        if self.win.y_ranges.bw_ymin.value() != 0:
            args += ["--beamwidth-ymin", f"{self.win.y_ranges.bw_ymin.value()}"]
        if self.win.y_ranges.bw_ymax.value() != 0:
            args += ["--beamwidth-ymax", f"{self.win.y_ranges.bw_ymax.value()}"]
        if self.win.y_ranges.bw_ystep.value() != 0:
            args += ["--beamwidth-y-step", f"{self.win.y_ranges.bw_ystep.value()}"]
        if self.win.y_ranges.be_ymin.value() != 0:
            args += ["--beam-eff-ymin", f"{self.win.y_ranges.be_ymin.value()}"]
        if self.win.y_ranges.be_ymax.value() != 0:
            args += ["--beam-eff-ymax", f"{self.win.y_ranges.be_ymax.value()}"]
        if self.win.y_ranges.be_ystep.value() != 0:
            args += ["--beam-eff-y-step", f"{self.win.y_ranges.be_ystep.value()}"]
        if self.win.shared_axis.use_log_scale():
            args.append("--x-log")
        if self.win.shared_axis.fmin.value() > 0 and self.win.shared_axis.fmax.value() > self.win.shared_axis.fmin.value():
            args += ["--fmin", f"{self.win.shared_axis.fmin.value()}", "--fmax", f"{self.win.shared_axis.fmax.value()}"]
        self.win.proc.enqueue(args)

class VswrSection(QGroupBox):
    def __init__(self, win: "MainWindow"):
        super().__init__("VSWR (plot_vswr.py)")
        self.win = win
        lay = QVBoxLayout(self)

        # Touchstone
        r1 = QHBoxLayout(); lay.addLayout(r1)
        r1.addWidget(QLabel("Touchstone (.s1p/.s2p):"))
        self.s2p = QLineEdit(display_workspace_path(self.win.store.get("vswr_s2p", ""))); self.s2p.setReadOnly(True)
        r1.addWidget(self.s2p, 1)
        b1 = QPushButton("Browse…"); b1.clicked.connect(self.browse_s2p); r1.addWidget(b1)
        o1 = QPushButton("Open"); o1.clicked.connect(lambda: open_in_file_manager(resolve_workspace_path(self.s2p.text()))); r1.addWidget(o1)

        # out dir
        r2 = QHBoxLayout(); lay.addLayout(r2)
        r2.addWidget(QLabel("Output SVG:"))
        self.out_dir = QLineEdit(""); self.out_dir.setReadOnly(True)
        r2.addWidget(self.out_dir, 1)
        b2 = QPushButton("Browse…"); b2.clicked.connect(self.browse_out); r2.addWidget(b2)
        b2.hide()
        o2 = QPushButton("Open"); o2.clicked.connect(lambda: open_in_file_manager(resolve_workspace_path(self.out_dir.text()))); r2.addWidget(o2)

        # options
        form = QFormLayout(); lay.addLayout(form)
        self.grid = QLineEdit(self.win.store.get("vswr_grid", "#6f7a81"))
        self.grid.textChanged.connect(lambda v: self.win.store.set("vswr_grid", v))
        self.line1 = ColorSelector(self.win.store, "vswr_line_1", DEFAULT_LINE_COLORS[0][1])
        self.line2 = ColorSelector(self.win.store, "vswr_line_2", DEFAULT_LINE_COLORS[1][1])
        self.smooth = QSpinBox(); self.smooth.setRange(1,99); self.smooth.setValue(int(self.win.store.get("vswr_smooth", 5)))
        self.smooth.valueChanged.connect(lambda v: self.win.store.set("vswr_smooth", int(v)))
        form.addRow("Grid color:", self.grid)
        form.addRow("Line color 1:", self.line1)
        form.addRow("Line color 2:", self.line2)
        form.addRow("Smooth window:", self.smooth)

        run = QPushButton("Run VSWR ▶"); run.clicked.connect(self.run)
        lay.addWidget(run, alignment=Qt.AlignRight)

        self.update_derived_paths()

        # drag & drop for Touchstone
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                if u.toLocalFile().lower().endswith((".s1p", ".s2p")):
                    e.acceptProposedAction(); return
        e.ignore()
    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith((".s1p", ".s2p")):
                self.s2p.setText(display_workspace_path(p)); self.win.store.set("vswr_s2p", str(resolve_workspace_path(p)))
                self.win.refresh_derived_paths()
                break

    def browse_s2p(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Open Touchstone", str(THIS_DIR), "Touchstone (*.s1p *.s2p)")
        if fn:
            self.s2p.setText(display_workspace_path(fn)); self.win.store.set("vswr_s2p", str(resolve_workspace_path(fn)))
            self.win.refresh_derived_paths()
    def browse_out(self):
        dn = QFileDialog.getExistingDirectory(self, "Choose output directory", self.out_dir.text())
        if dn:
            self.out_dir.setText(display_workspace_path(dn)); self.win.store.set("vswr_out", dn)

    def update_derived_paths(self):
        self.out_dir.setText(display_workspace_path(self.win.deduced_vswr_output()))

    def run(self):
        s2p = resolve_workspace_path(self.s2p.text().strip())
        outd = resolve_workspace_path(self.out_dir.text().strip())
        if not self.s2p.text().strip():
            self.win.status("Choose a .s1p or .s2p file")
            return
        args = [which_python(), "-u", SCRIPT_VSWR, str(s2p), "--output", str(outd),
                "--grid-color", self.grid.text().strip(),
                "--line-colors", ",".join([self.line1.color(), self.line2.color()]),
                "--x-step", str(self.win.shared_axis.xstep.value()),
                "--ymin", str(self.win.y_ranges.vswr_ymin.value()), "--ymax", str(self.win.y_ranges.vswr_ymax.value()),
                "--y-step", str(self.win.y_ranges.vswr_ystep.value()),
                "--smooth-window", str(self.smooth.value())]
        if self.win.shared_axis.use_log_scale():
            args.append("--x-log")
        if self.win.shared_axis.fmin.value() > 0 and self.win.shared_axis.fmax.value() > 0 and self.win.shared_axis.fmax.value() > self.win.shared_axis.fmin.value():
            args += ["--fmin", f"{self.win.shared_axis.fmin.value()}", "--fmax", f"{self.win.shared_axis.fmax.value()}"]
        self.win.proc.enqueue(args)


class ExtractSection(QGroupBox):
    def __init__(self, win: "MainWindow"):
        super().__init__("Extracted Data (extract_data_xlsx.py)")
        self.win = win
        lay = QVBoxLayout(self)

        row = QHBoxLayout()
        lay.addLayout(row)
        row.addWidget(QLabel("Derived extract workbook (.xlsx):"))
        self.out_xlsx = QLineEdit("")
        self.out_xlsx.setReadOnly(True)
        row.addWidget(self.out_xlsx, 1)
        openb = QPushButton("Open folder")
        openb.clicked.connect(lambda: open_in_file_manager(resolve_workspace_path(self.out_xlsx.text())))
        row.addWidget(openb)

        note = QLabel("Uses the current .ffs selection, the selected Touchstone file, Beam smooth/theta, the shared frequency/x-axis controls, and the grouped y-axis ranges.")
        note.setWordWrap(True)
        lay.addWidget(note)

        run = QPushButton("Run extract_data_xlsx ▶")
        run.clicked.connect(self.run)
        lay.addWidget(run, alignment=Qt.AlignRight)
        self.update_derived_paths()

    def update_derived_paths(self):
        self.out_xlsx.setText(display_workspace_path(self.win.deduced_extract_output()))

    def run(self):
        self.win.run_extract()

# ---------------------------------------------------------
# Main window
# ---------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1360, 860)

        self.store = Persist(STATE_FILE)
        self.proc = Proc(self)

        # Toolbar
        tb = self.addToolBar("main")
        a_run_all = QAction("Run FULL pipeline ⮕", self); a_run_all.triggered.connect(self.run_full)
        a_run_extract = QAction("Run extract data ⮕", self); a_run_extract.triggered.connect(self.run_extract)
        a_stop = QAction("Stop", self); a_stop.triggered.connect(self.proc.stop)
        tb.addAction(a_run_all); tb.addAction(a_run_extract); tb.addAction(a_stop)
        tb.addSeparator()

        tb.addWidget(QLabel(f"Python: {which_python()}  "))
        tb.addSeparator()

        tb.addWidget(QLabel("Theme:"))
        self.theme = QComboBox(); self.theme.addItems(["Dark", "Light"]) ; self.theme.currentTextChanged.connect(self.apply_theme)
        tb.addWidget(self.theme)
        self.theme.setCurrentText(self.store.get("theme", "Dark"))

        tb.addSeparator()
        tb.addWidget(QLabel("Console:"))
        self.verbosity = QComboBox(); self.verbosity.addItems(["All", "Stdout only", "Errors only", "Compact"]) 
        tb.addWidget(self.verbosity)
        self.verbosity.setCurrentText(self.store.get("verbosity", "All"))
        self.verbosity.currentTextChanged.connect(lambda v: self.store.set("verbosity", v))
        tb.addSeparator()
        tb.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.currentTextChanged.connect(self.on_preset_selected)
        tb.addWidget(self.preset_combo)
        preset_new = QPushButton("New"); preset_new.clicked.connect(self.create_preset); tb.addWidget(preset_new)
        preset_save = QPushButton("Save"); preset_save.clicked.connect(self.save_preset); tb.addWidget(preset_save)
        preset_rename = QPushButton("Rename"); preset_rename.clicked.connect(self.rename_preset); tb.addWidget(preset_rename)
        preset_delete = QPushButton("Delete"); preset_delete.clicked.connect(self.delete_preset); tb.addWidget(preset_delete)
        preset_import = QPushButton("Import"); preset_import.clicked.connect(self.import_presets); tb.addWidget(preset_import)
        preset_export = QPushButton("Export"); preset_export.clicked.connect(self.export_presets); tb.addWidget(preset_export)

        # Central splitter
        split = QSplitter(); split.setOrientation(Qt.Horizontal)
        left = QWidget(); left_lay = QVBoxLayout(left); left_lay.setContentsMargins(8,8,8,8); left_lay.setSpacing(10)
        right = QWidget(); right_lay = QVBoxLayout(right); right_lay.setContentsMargins(8,8,8,8); right_lay.setSpacing(8)

        self.beam = BeamSection(self)
        self.shared_axis = SharedAxisSection(self)
        self.y_ranges = YRangeSection(self)
        self.plot = PlotSection(self)
        self.vswr = VswrSection(self)
        self.extract = ExtractSection(self)

        left_lay.addWidget(self.beam)
        left_lay.addWidget(self.shared_axis)
        left_lay.addWidget(self.y_ranges)
        left_lay.addWidget(self.plot)
        left_lay.addWidget(self.vswr)
        left_lay.addWidget(self.extract)
        left_lay.addStretch(1)

        # Console
        head = QHBoxLayout()
        head.addWidget(QLabel("Output Console"))
        self.run_info = QLabel("")
        head.addWidget(self.run_info)
        head.addStretch(1)
        self.busy = QProgressBar(); self.busy.setRange(0,0); self.busy.setVisible(False); self.busy.setFixedWidth(280)
        head.addWidget(self.busy)

        right_lay.addLayout(head)
        self.console = QPlainTextEdit(); self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(5000)  # keep things light
        font = self.console.font(); font.setFamily("Consolas" if is_win() else "Monospace"); font.setPointSize(font.pointSize()-1); self.console.setFont(font)
        right_lay.addWidget(self.console, 1)

        split.addWidget(left); split.addWidget(right)
        split.setSizes(self.store.get("split_sizes", [520, 800]))
        self.setCentralWidget(split)
        self._split = split

        self.refresh_derived_paths()
        self.refresh_preset_list(select_name=str(self.store.get(ACTIVE_PRESET_KEY, "")))
        self.apply_theme(self.theme.currentText())
        self._restore_geometry()

    # ---- persist helpers ----
    def _restore_geometry(self):
        geo = self.store.get("geometry", None)
        if geo:
            try:
                ba = QByteArray.fromBase64(geo.encode("ascii"))
                self.restoreGeometry(ba)
            except Exception:
                pass

    def selected_ffs(self) -> list[str]:
        if not hasattr(self, "beam"):
            return []
        return self.beam.actual_paths()

    def selected_s2p(self) -> str:
        if not hasattr(self, "vswr"):
            return ""
        value = self.vswr.s2p.text().strip()
        return str(resolve_workspace_path(value)) if value else ""

    def deduced_project_name(self) -> str:
        ffs = self.selected_ffs()
        if ffs:
            return deduce_project_name(ffs)
        s2p = self.selected_s2p()
        return deduce_project_name([s2p]) if s2p else "results"

    def deduced_results_dir(self) -> Path:
        return RESULTS_DIR / self.deduced_project_name()

    def deduced_beam_output(self) -> Path:
        project = self.deduced_project_name()
        return self.deduced_results_dir() / f"{project}.xlsx"

    def deduced_vswr_output(self) -> Path:
        s2p = self.selected_s2p()
        stem = self.deduced_project_name() if self.selected_ffs() else (normalized_project_stem(Path(s2p).stem) if s2p else self.deduced_project_name())
        return self.deduced_results_dir() / f"{stem}_vswr.svg"

    def deduced_extract_output(self) -> Path:
        project = self.deduced_project_name()
        return self.deduced_results_dir() / f"{project}_extracted_data.xlsx"

    def refresh_derived_paths(self):
        if hasattr(self, "beam"):
            self.beam.update_derived_paths()
        if hasattr(self, "plot"):
            self.plot.update_derived_paths()
        if hasattr(self, "vswr"):
            self.vswr.update_derived_paths()
        if hasattr(self, "extract"):
            self.extract.update_derived_paths()

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
            "smooth": int(self.beam.smooth.value()),
            "theta": float(self.beam.theta.value()),
            "smooth2": int(self.plot.smooth.value()),
            "shared_xstep": float(self.shared_axis.xstep.value()),
            "shared_fmin": float(self.shared_axis.fmin.value()),
            "shared_fmax": float(self.shared_axis.fmax.value()),
            "shared_xlog": bool(self.shared_axis.use_log_scale()),
            "gain_ymin": float(self.y_ranges.gain_ymin.value()),
            "gain_ymax": float(self.y_ranges.gain_ymax.value()),
            "gain_y_step": float(self.y_ranges.gain_ystep.value()),
            "beamwidth_ymin": float(self.y_ranges.bw_ymin.value()),
            "beamwidth_ymax": float(self.y_ranges.bw_ymax.value()),
            "beamwidth_y_step": float(self.y_ranges.bw_ystep.value()),
            "beam_eff_ymin": float(self.y_ranges.be_ymin.value()),
            "beam_eff_ymax": float(self.y_ranges.be_ymax.value()),
            "beam_eff_y_step": float(self.y_ranges.be_ystep.value()),
            "vswr_ymin": float(self.y_ranges.vswr_ymin.value()),
            "vswr_ymax": float(self.y_ranges.vswr_ymax.value()),
            "vswr_ystep": float(self.y_ranges.vswr_ystep.value()),
            "vswr_smooth": int(self.vswr.smooth.value()),
            "grid_color": self.plot.grid.text().strip(),
            "plot_line_1": self.plot.line1.color(),
            "plot_line_2": self.plot.line2.color(),
            "rings": self.plot.rings.text().strip(),
            "angle": int(self.plot.ang.value()),
            "clip": float(self.plot.clip.value()),
            "vswr_grid": self.vswr.grid.text().strip(),
            "vswr_line_1": self.vswr.line1.color(),
            "vswr_line_2": self.vswr.line2.color(),
        }

    def apply_preset_values(self, values: dict[str, object]) -> None:
        if not values:
            return
        if "smooth" in values: self.beam.smooth.setValue(int(values["smooth"]))
        if "theta" in values: self.beam.theta.setValue(float(values["theta"]))
        if "smooth2" in values: self.plot.smooth.setValue(int(values["smooth2"]))
        if "shared_xstep" in values: self.shared_axis.xstep.setValue(float(values["shared_xstep"]))
        if "shared_fmin" in values: self.shared_axis.fmin.setValue(float(values["shared_fmin"]))
        if "shared_fmax" in values: self.shared_axis.fmax.setValue(float(values["shared_fmax"]))
        if "shared_xlog" in values: self.shared_axis.xlog.setCurrentText("Log" if bool(values["shared_xlog"]) else "Linear")
        if "gain_ymin" in values: self.y_ranges.gain_ymin.setValue(float(values["gain_ymin"]))
        if "gain_ymax" in values: self.y_ranges.gain_ymax.setValue(float(values["gain_ymax"]))
        if "gain_y_step" in values: self.y_ranges.gain_ystep.setValue(float(values["gain_y_step"]))
        if "beamwidth_ymin" in values: self.y_ranges.bw_ymin.setValue(float(values["beamwidth_ymin"]))
        if "beamwidth_ymax" in values: self.y_ranges.bw_ymax.setValue(float(values["beamwidth_ymax"]))
        if "beamwidth_y_step" in values: self.y_ranges.bw_ystep.setValue(float(values["beamwidth_y_step"]))
        if "beam_eff_ymin" in values: self.y_ranges.be_ymin.setValue(float(values["beam_eff_ymin"]))
        if "beam_eff_ymax" in values: self.y_ranges.be_ymax.setValue(float(values["beam_eff_ymax"]))
        if "beam_eff_y_step" in values: self.y_ranges.be_ystep.setValue(float(values["beam_eff_y_step"]))
        if "vswr_ymin" in values: self.y_ranges.vswr_ymin.setValue(float(values["vswr_ymin"]))
        if "vswr_ymax" in values: self.y_ranges.vswr_ymax.setValue(float(values["vswr_ymax"]))
        if "vswr_ystep" in values: self.y_ranges.vswr_ystep.setValue(float(values["vswr_ystep"]))
        if "vswr_smooth" in values: self.vswr.smooth.setValue(int(values["vswr_smooth"]))
        if "grid_color" in values: self.plot.grid.setText(str(values["grid_color"]))
        if "plot_line_1" in values: self.plot.line1.set_color(str(values["plot_line_1"]))
        if "plot_line_2" in values: self.plot.line2.set_color(str(values["plot_line_2"]))
        if "rings" in values: self.plot.rings.setText(str(values["rings"]))
        if "angle" in values: self.plot.ang.setValue(int(values["angle"]))
        if "clip" in values: self.plot.clip.setValue(float(values["clip"]))
        if "vswr_grid" in values: self.vswr.grid.setText(str(values["vswr_grid"]))
        if "vswr_line_1" in values: self.vswr.line1.set_color(str(values["vswr_line_1"]))
        if "vswr_line_2" in values: self.vswr.line2.set_color(str(values["vswr_line_2"]))

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
        suggested = suggest_preset_name(self.preset_names(), self.deduced_project_name())
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
        path, _ = QFileDialog.getOpenFileName(self, "Import Presets", str(self.deduced_results_dir()), "JSON (*.json)")
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
        suggested = str((self.deduced_results_dir() / "antenna_toolkit_presets.json").resolve())
        path, _ = QFileDialog.getSaveFileName(self, "Export Presets", suggested, "JSON (*.json)")
        if not path:
            return
        out_path = Path(path)
        if out_path.suffix.lower() != ".json":
            out_path = out_path.with_suffix(".json")
        out_path.write_text(json.dumps({"presets": presets}, indent=2), encoding="utf-8")
        QMessageBox.information(self, "Presets Exported", f"Exported {len(presets)} preset(s) to:\n{out_path}")

    def _save_geometry(self):
        try:
            ba = self.saveGeometry().toBase64().data().decode("ascii")
            self.store.set("geometry", ba)
            self.store.set("split_sizes", self._split.sizes())
        except Exception:
            pass

    def closeEvent(self, e):
        self._save_geometry()
        super().closeEvent(e)

    # ---- status + console helpers ----
    def set_busy(self, on: bool):
        self.busy.setVisible(on)
        if on:
            # indeterminate until we detect %
            self.busy.setRange(0,0)
        else:
            self.busy.setRange(0,100)
            self.busy.setValue(0)

    def log(self, text: str, color: str | None = None, channel: str | None = None):
        # Filter based on verbosity
        mode = self.verbosity.currentText() if hasattr(self, "verbosity") else "All"
        if mode == "Stdout only" and channel == "stderr":
            return
        if mode == "Errors only" and channel != "stderr":
            return
        if mode == "Compact":
            text = re.sub(r"\n{3,}", "\n\n", text)
        if color:
            safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">","&gt;")
            self.console.appendHtml(f'<pre style="color:{color}; margin:0">{safe}</pre>')
        else:
            self.console.appendPlainText(text)
        self.console.moveCursor(QTextCursor.End)
        if channel:
            self._line_count = getattr(self, "_line_count", 0) + text.count("\n")
            self._update_run_info()

    def status(self, msg: str):
        self.statusBar().showMessage(msg, 4000)

    # ---- progress helpers ----
    def on_proc_started(self, cmd: str):
        self._line_count = 0
        self._current_cmd = cmd
        self._started_ts = time.time()
        if not hasattr(self, "_tick"):
            self._tick = QTimer(self); self._tick.timeout.connect(self._update_run_info)
        self._tick.start(250)
        self._update_run_info()

    def on_proc_finished(self):
        if hasattr(self, "_tick"):
            self._tick.stop()
        self._update_run_info(final=True)
        self._current_cmd = None

    def _update_run_info(self, final: bool=False):
        if getattr(self, "_current_cmd", None) and getattr(self, "_started_ts", None):
            elapsed = int(time.time() - self._started_ts)
            mm, ss = divmod(elapsed, 60)
            hh, mm = divmod(mm, 60)
            t = f"{hh:02d}:{mm:02d}:{ss:02d}"
            self.run_info.setText(f"Running… lines: {getattr(self,'_line_count',0)} | {t}")
        else:
            self.run_info.setText("")

    def set_progress(self, value: int | None):
        if value is None:
            # switch to indeterminate
            self.busy.setRange(0,0)
        else:
            if self.busy.maximum() != 100:
                self.busy.setRange(0,100)
            self.busy.setValue(value)

    # ---- theme ----
    def apply_theme(self, mode: str):
        self.store.set("theme", mode)
        QApplication.setStyle(QStyleFactory.create("Fusion"))
        pal = QPalette()
        if mode == "Dark":
            pal.setColor(QPalette.Window, QColor(30, 32, 36))
            pal.setColor(QPalette.WindowText, Qt.white)
            pal.setColor(QPalette.Base, QColor(25, 27, 30))
            pal.setColor(QPalette.AlternateBase, QColor(45, 47, 52))
            pal.setColor(QPalette.ToolTipBase, Qt.white)
            pal.setColor(QPalette.ToolTipText, Qt.white)
            pal.setColor(QPalette.Text, Qt.white)
            pal.setColor(QPalette.Button, QColor(45, 47, 52))
            pal.setColor(QPalette.ButtonText, Qt.white)
            pal.setColor(QPalette.BrightText, Qt.red)
            pal.setColor(QPalette.Highlight, QColor(64, 128, 255))
            pal.setColor(QPalette.HighlightedText, Qt.white)
        else:
            # light defaults
            pass
        QApplication.setPalette(pal)

    def build_extract_args(self) -> list[str] | None:
        self.refresh_derived_paths()
        ffs = self.beam.actual_paths() if hasattr(self, "beam") else []
        s2p = self.selected_s2p()
        if not ffs and not s2p:
            return None

        args = [which_python(), "-u", SCRIPT_EXTRACT, str(self.deduced_extract_output())]
        args += ffs
        args += ["--smooth", str(self.beam.smooth.value()), "--theta-window", str(self.beam.theta.value())]
        if ffs:
            args += ["--beam-workbook", str(self.deduced_beam_output())]
        if s2p:
            args += ["--touchstone", s2p]
        if self.shared_axis.fmin.value() > 0 and self.shared_axis.fmax.value() > 0 and self.shared_axis.fmax.value() > self.shared_axis.fmin.value():
            args += ["--ffs-fmin", f"{self.shared_axis.fmin.value()}", "--ffs-fmax", f"{self.shared_axis.fmax.value()}"]
            args += ["--touchstone-fmin", f"{self.shared_axis.fmin.value()}", "--touchstone-fmax", f"{self.shared_axis.fmax.value()}"]
        return args

    def run_extract(self):
        args = self.build_extract_args()
        if not args:
            self.status("Choose at least one .ffs file or a Touchstone file")
            return
        self.proc.enqueue(args)

    # ---- orchestration ----
    def run_full(self):
        # Beam → Plot pipeline
        self.refresh_derived_paths()
        out_xlsx = str(resolve_workspace_path(self.beam.out_xlsx.text().strip()))
        ffs = self.beam.actual_paths()
        if not ffs:
            self.status("Add at least one .ffs for the pipeline")
            return
        # enqueue beam
        args_beam = [which_python(), "-u", SCRIPT_BEAM, out_xlsx] + ffs + [
            "--smooth", str(self.beam.smooth.value()),
            "--theta-window", str(self.beam.theta.value())
        ]
        self.proc.enqueue(args_beam)
        args_extract = self.build_extract_args()
        if args_extract:
            self.proc.enqueue(args_extract)
        # enqueue plot (uses same xlsx)
        args_plot = [which_python(), "-u", SCRIPT_PLOT, out_xlsx,
                     "--out-dir", str(resolve_workspace_path(self.plot.out_dir.text().strip())),
                     "--grid-color", self.plot.grid.text().strip(),
                     "--line-colors", ",".join([self.plot.line1.color(), self.plot.line2.color()]),
                     "--rings", self.plot.rings.text().strip(),
                     "--angle-step", str(self.plot.ang.value()),
                     "--clip-db", str(self.plot.clip.value()),
                     "--smooth-window", str(self.plot.smooth.value()),
                     "--x-step", str(self.shared_axis.xstep.value())]
        if self.y_ranges.gain_ymin.value() != 0:
            args_plot += ["--gain-ymin", f"{self.y_ranges.gain_ymin.value()}"]
        if self.y_ranges.gain_ymax.value() != 0:
            args_plot += ["--gain-ymax", f"{self.y_ranges.gain_ymax.value()}"]
        if self.y_ranges.gain_ystep.value() != 0:
            args_plot += ["--gain-y-step", f"{self.y_ranges.gain_ystep.value()}"]
        if self.y_ranges.bw_ymin.value() != 0:
            args_plot += ["--beamwidth-ymin", f"{self.y_ranges.bw_ymin.value()}"]
        if self.y_ranges.bw_ymax.value() != 0:
            args_plot += ["--beamwidth-ymax", f"{self.y_ranges.bw_ymax.value()}"]
        if self.y_ranges.bw_ystep.value() != 0:
            args_plot += ["--beamwidth-y-step", f"{self.y_ranges.bw_ystep.value()}"]
        if self.y_ranges.be_ymin.value() != 0:
            args_plot += ["--beam-eff-ymin", f"{self.y_ranges.be_ymin.value()}"]
        if self.y_ranges.be_ymax.value() != 0:
            args_plot += ["--beam-eff-ymax", f"{self.y_ranges.be_ymax.value()}"]
        if self.y_ranges.be_ystep.value() != 0:
            args_plot += ["--beam-eff-y-step", f"{self.y_ranges.be_ystep.value()}"]
        if self.shared_axis.use_log_scale():
            args_plot.append("--x-log")
        if self.shared_axis.fmin.value() > 0 and self.shared_axis.fmax.value() > 0 and self.shared_axis.fmax.value() > self.shared_axis.fmin.value():
            args_plot += ["--fmin", f"{self.shared_axis.fmin.value()}", "--fmax", f"{self.shared_axis.fmax.value()}"]
        self.proc.enqueue(args_plot)

# ---------------------------------------------------------
# Entry point
# ---------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
