#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import sys
import webbrowser
from pathlib import Path
from typing import List
from urllib.parse import quote

from PySide6.QtCore import QProcess, QProcessEnvironment
from path_utils import (
    display_workspace_path as _display_workspace_path,
    is_url as _is_url,
    resolve_workspace_path as _resolve_workspace_path,
)

THIS_DIR = Path(__file__).resolve().parent
SCRIPT_BEAM = str(THIS_DIR / "beamwidth_xlsx.py")
SCRIPT_EXTRACT = str(THIS_DIR / "extract_data_xlsx.py")
SCRIPT_DATASHEET = str(THIS_DIR / "datasheet_pdf.py")
SCRIPT_PLOT = str(THIS_DIR / "plot.py")
SCRIPT_VSWR = str(THIS_DIR / "plot_vswr.py")
logger = logging.getLogger(__name__)

DEFAULT_GRID_COLOR = "#6f7a81"
DEFAULT_LINE_COLORS = [
    ("Sky", "#2bb6f6"),
    ("Amber", "#f5a623"),
    ("Coral", "#ef6c5b"),
    ("Pine", "#2f8f6b"),
    ("Slate", "#5b6c7d"),
]
DEFAULT_COLOR_OPTIONS = [
    ("Sky", "#2bb6f6"),
    ("Azure", "#2563eb"),
    ("Navy", "#1d4ed8"),
    ("Indigo", "#4f46e5"),
    ("Violet", "#7c3aed"),
    ("Magenta", "#c026d3"),
    ("Rose", "#e11d48"),
    ("Coral", "#ef6c5b"),
    ("Signal Red", "#ff0000"),
    ("Bright Red", "#e60000"),
    ("Deep Red", "#b00000"),
    ("Amber", "#f5a623"),
    ("Orange", "#f97316"),
    ("Gold", "#eab308"),
    ("Lime", "#84cc16"),
    ("Green", "#22c55e"),
    ("Pine", "#2f8f6b"),
    ("Teal", "#14b8a6"),
    ("Cyan", "#06b6d4"),
    ("Charcoal", "#4b5563"),
    ("Slate", "#5b6c7d"),
    ("Neutral Gray", "#808080"),
    ("Light Gray", "#a3a3a3"),
    ("Mist", "#c4c7cf"),
    ("Graphite", "#404040"),
    ("Jet Black", "#000000"),
]
DEFAULT_BEAMWIDTH_DB_COLORS = [
    ("Signal Red", "#ff0000"),
    ("Bright Red", "#e60000"),
    ("Deep Red", "#b00000"),
    ("Dark Red", "#8b0000"),
    ("Soft Red", "#ef4444"),
    ("Neutral Gray", "#808080"),
    ("Light Gray", "#a3a3a3"),
    ("Cool Gray", "#737373"),
    ("Dark Gray", "#525252"),
    ("Graphite", "#404040"),
    ("Jet Black", "#000000"),
    ("Near Black", "#111111"),
    ("Charcoal", "#1f1f1f"),
    ("Soft Black", "#262626"),
]
PRESET_STORE_KEY = "ui_presets"
PRESET_DIRECTORY_NAME = "Presets"
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
    "cartesian_grid_line_width",
    "polar_grid_line_width",
    "cartesian_line_width",
    "cartesian_figure_width",
    "cartesian_figure_height",
    "polar_figure_size",
    "polar_line_width",
    "cartesian_font_size",
    "polar_font_size",
    "cartesian_legend_font_size",
    "polar_legend_font_size",
    "plot_grid_line_width",
    "plot_line_width",
    "plot_font_size",
    "plot_legend_font_size",
    "plot_line_1",
    "plot_line_2",
    "polar_azimuth_line_1_color",
    "polar_azimuth_line_1_style",
    "polar_azimuth_line_2_color",
    "polar_azimuth_line_2_style",
    "polar_elevation_line_1_color",
    "polar_elevation_line_1_style",
    "polar_elevation_line_2_color",
    "polar_elevation_line_2_style",
    "beamwidth_3db_color",
    "beamwidth_6db_color",
    "beamwidth_10db_color",
    "datasheet_template",
    "pdf_metadata_author",
    "rings",
    "angle",
    "clip",
]


def app_state_dir() -> Path:
    if os.name == "nt":
        base = Path(
            os.environ.get("APPDATA")
            or os.environ.get("LOCALAPPDATA")
            or (Path.home() / "AppData" / "Roaming")
        )
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "AntennaToolkit"


def resolve_state_file(filename: str, legacy_path: Path | None = None) -> Path:
    state_path = app_state_dir() / filename
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        logger.warning("Could not create state directory: %s", state_path.parent, exc_info=True)
    if legacy_path and legacy_path.exists() and not state_path.exists():
        try:
            shutil.copy2(legacy_path, state_path)
        except Exception:
            try:
                state_path.write_text(legacy_path.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception:
                logger.warning("Could not migrate legacy state file from %s to %s", legacy_path, state_path, exc_info=True)
    return state_path


def trim_project_token(token: str) -> str:
    return re.sub(r"[_\-\s]+$", "", token.strip())


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


def preset_storage_dir(state_path: Path) -> Path:
    return THIS_DIR / PRESET_DIRECTORY_NAME


def legacy_preset_storage_dirs(state_path: Path) -> list[Path]:
    candidates = [state_path.parent / PRESET_DIRECTORY_NAME]
    seen: set[Path] = set()
    unique: list[Path] = []
    current = preset_storage_dir(state_path).resolve()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if resolved == current or resolved in seen:
            continue
        seen.add(resolved)
        unique.append(candidate)
    return unique


def which_python() -> str:
    return sys.executable or "python3"


def is_win() -> bool:
    return os.name == "nt"


def open_in_file_manager(path: str | Path):
    if not path:
        return
    if is_url(path):
        try:
            webbrowser.open(str(path))
        except Exception:
            logger.warning("Could not open URL: %s", path, exc_info=True)
        return
    p = Path(path)
    try:
        if is_win():
            os.startfile(p)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            if p.is_file():
                os.system(f"open -R {shlex.quote(str(p))}")
            else:
                os.system(f"open {shlex.quote(str(p))}")
        else:
            os.system(f"xdg-open {shlex.quote(str(p if p.is_dir() else p.parent))} >/dev/null 2>&1 &")
    except Exception:
        logger.warning("Could not open path in file manager: %s", p, exc_info=True)


def resolve_workspace_path(path: str | Path | None) -> Path:
    return _resolve_workspace_path(THIS_DIR, path)


def display_workspace_path(path: str | Path | None) -> str:
    return _display_workspace_path(THIS_DIR, path)


def display_command_part(part: str) -> str:
    if not part or part.startswith("-"):
        return part
    if any(sep in part for sep in ("\\", "/")):
        return display_workspace_path(part)
    return part


def is_url(value: str | Path | None) -> bool:
    return _is_url(value)


class Persist:
    def __init__(self, path: Path):
        self.path = path
        self.data = {}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            logger.warning("Could not create settings directory: %s", self.path.parent, exc_info=True)
        try:
            if path.exists():
                self.data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Could not read settings file: %s", path, exc_info=True)
            self.data = {}

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except Exception:
            logger.warning("Could not save settings file: %s", self.path, exc_info=True)

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value):
        if key in self.data and self.data.get(key) == value:
            return
        self.data[key] = value
        self.save()

    def delete(self, key: str) -> None:
        if key in self.data:
            del self.data[key]
            self.save()


class PresetFileStore:
    def __init__(self, directory: Path, legacy_directories: list[Path] | None = None):
        self.directory = directory
        self.legacy_directories = list(legacy_directories or [])
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except Exception:
            logger.warning("Could not create preset directory: %s", self.directory, exc_info=True)

    def _path_for_name(self, name: str) -> Path:
        encoded = quote(name.strip(), safe="")
        return self.directory / f"{encoded}.json"

    def load_presets(self) -> dict[str, dict[str, object]]:
        presets: dict[str, dict[str, object]] = {}
        try:
            candidates = sorted(self.directory.glob("*.json"))
        except Exception:
            logger.warning("Could not list presets in %s", self.directory, exc_info=True)
            return presets
        for path in candidates:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("Could not read preset file: %s", path, exc_info=True)
                continue
            if isinstance(payload, dict) and isinstance(payload.get("name"), str):
                name = payload["name"].strip()
                values = payload.get("values", {})
                clean = normalize_preset_payload({name: values})
            else:
                clean = normalize_preset_payload(payload)
            presets.update(clean)
        return presets

    def save_preset(self, name: str, values: dict[str, object]) -> None:
        clean = normalize_preset_payload({name: values})
        if name not in clean:
            return
        path = self._path_for_name(name)
        payload = {"name": name, "values": clean[name]}
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            logger.warning("Could not save preset file: %s", path, exc_info=True)

    def delete_preset(self, name: str) -> None:
        path = self._path_for_name(name)
        try:
            if path.exists():
                path.unlink()
        except Exception:
            logger.warning("Could not delete preset file: %s", path, exc_info=True)

    def rename_preset(self, old_name: str, new_name: str, values: dict[str, object]) -> None:
        if old_name != new_name:
            self.delete_preset(old_name)
        self.save_preset(new_name, values)

    def replace_all(self, presets: dict[str, dict[str, object]]) -> None:
        clean = normalize_preset_payload(presets)
        desired_paths = {self._path_for_name(name).resolve() for name in clean}
        for name, values in clean.items():
            self.save_preset(name, values)
        try:
            for path in self.directory.glob("*.json"):
                if path.resolve() not in desired_paths:
                    path.unlink()
        except Exception:
            logger.warning("Could not prune preset directory: %s", self.directory, exc_info=True)

    def migrate_from_state(self, store: Persist, key: str = PRESET_STORE_KEY) -> dict[str, dict[str, object]]:
        merged = self.load_presets()
        for legacy_dir in self.legacy_directories:
            legacy_presets = PresetFileStore(legacy_dir).load_presets()
            if legacy_presets:
                merged.update(legacy_presets)
        inline = normalize_preset_payload(store.get(key, {}))
        if inline:
            merged.update(inline)
        if merged != self.load_presets():
            self.replace_all(merged)
        if inline:
            store.delete(key)
        return merged


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


class Proc:
    def __init__(self, window):
        self.win = window
        self.proc = QProcess()
        self.proc.setProcessChannelMode(QProcess.SeparateChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        self.proc.setProcessEnvironment(env)
        self.proc.readyReadStandardOutput.connect(self._on_out_stdout)
        self.proc.readyReadStandardError.connect(self._on_out_stderr)
        self.proc.finished.connect(self._on_finished)
        self.queue: List[list[str]] = []
        self.running_cmd: List[str] | None = None
        self._progress_buffers = {"stdout": "", "stderr": ""}

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
                logger.warning("Run step-start callback failed", exc_info=True)
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
            self._consume_progress_text("stdout", data)

    def _on_out_stderr(self):
        data = bytes(self.proc.readAllStandardError()).decode(errors="replace")
        if data:
            self.win.log(data, color="#ff8a80", channel="stderr")
            self._consume_progress_text("stderr", data)

    def _consume_progress_text(self, channel: str, text: str):
        buffer = self._progress_buffers.get(channel, "") + text
        lines = buffer.splitlines(keepends=True)
        remainder = ""
        if lines and not (lines[-1].endswith("\n") or lines[-1].endswith("\r")):
            remainder = lines.pop()
        self._progress_buffers[channel] = remainder
        for line in lines:
            self._maybe_progress_from_text(line)

    def _flush_progress_buffers(self):
        for channel, text in list(self._progress_buffers.items()):
            if text:
                self._maybe_progress_from_text(text)
                self._progress_buffers[channel] = ""

    def _dispatch_structured_progress(self, payload: dict):
        if hasattr(self.win, "on_proc_progress"):
            try:
                self.win.on_proc_progress(dict(payload))
                return
            except Exception:
                logger.warning("Structured progress callback failed", exc_info=True)
        try:
            current = int(payload.get("current", 0))
            total = int(payload.get("total", 0))
        except Exception:
            logger.debug("Ignoring structured progress payload with invalid numeric fields: %r", payload, exc_info=True)
            return
        if total > 0:
            self.win.set_progress(int(round(max(0.0, min(1.0, current / total)) * 100)))

    def _dispatch_percent_progress(self, pct: int):
        if hasattr(self.win, "on_proc_progress_percent"):
            try:
                self.win.on_proc_progress_percent(int(pct))
                return
            except Exception:
                logger.warning("Percent progress callback failed", exc_info=True)
        self.win.set_progress(int(pct))

    def _maybe_progress_from_text(self, text: str):
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("AT_PROGRESS "):
                payload_text = line[len("AT_PROGRESS "):].strip()
                try:
                    payload = json.loads(payload_text)
                except Exception:
                    logger.debug("Ignoring malformed progress JSON: %s", payload_text, exc_info=True)
                    continue
                if not isinstance(payload, dict):
                    continue
                required = {"stage", "current", "total", "label"}
                if not required.issubset(payload):
                    continue
                try:
                    stage = str(payload["stage"]).strip().lower()
                    current = int(payload["current"])
                    total = int(payload["total"])
                    label = str(payload["label"]).strip()
                except Exception:
                    logger.debug("Ignoring progress payload with invalid fields: %r", payload, exc_info=True)
                    continue
                if not stage or total <= 0:
                    continue
                current = max(0, min(total, current))
                self._dispatch_structured_progress(
                    {
                        "stage": stage,
                        "current": current,
                        "total": total,
                        "label": label,
                    }
                )
                continue
            m = re.search(r"(\b\d{1,3})%", line)
            if m:
                pct = max(0, min(100, int(m.group(1))))
                self._dispatch_percent_progress(pct)

    def _on_finished(self, exit_code=0, exit_status=None):
        self._flush_progress_buffers()
        self.win.set_busy(False)
        self.win.set_progress(None)
        if hasattr(self.win, "on_proc_step_finished"):
            try:
                self.win.on_proc_step_finished(list(self.running_cmd or []), int(exit_code), exit_status)
            except Exception:
                logger.warning("Run step-finished callback failed", exc_info=True)
        self.win.on_proc_finished()
        self._dequeue_and_start()
