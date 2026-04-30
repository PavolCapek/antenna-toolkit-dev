from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QMessageBox

from pipeline.commands import build_plot_command, build_vswr_command
from project_store import utc_now_iso
from studio_runtime import (
    GoogleSheetDownloadError,
    STAGE_DEFINITIONS,
    STAGE_LABELS,
    extract_google_sheet_id,
)
from studio_support import (
    SCRIPT_BEAM,
    SCRIPT_DATASHEET,
    SCRIPT_EXTRACT,
    SCRIPT_PLOT,
    SCRIPT_VSWR,
    display_workspace_path,
    is_url,
    open_in_file_manager,
    which_python,
)


class StudioRunMixin:
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

    def on_proc_progress(self, payload: dict[str, object]) -> None:
        stage_key = str(payload.get("stage", "")).strip().lower()
        if not stage_key:
            stage_key = self._current_stage_key
        if self._current_stage_key and stage_key and stage_key != self._current_stage_key:
            return
        try:
            current = int(payload.get("current", 0))
            total = int(payload.get("total", 0))
        except (TypeError, ValueError):
            return
        if total <= 0:
            return
        self._live_stage_progress_key = stage_key or self._current_stage_key
        self._live_stage_progress_total = max(1, total)
        self._live_stage_progress_current = max(0, min(self._live_stage_progress_total, current))
        self._live_stage_progress_label = str(payload.get("label", "")).strip()
        self._sync_live_progress_bar()
        self.refresh_derived_paths()

    def on_proc_progress_percent(self, pct: int) -> None:
        if not self._current_stage_key:
            self.set_progress(pct)
            return
        self._live_stage_progress_key = self._current_stage_key
        self._live_stage_progress_total = 100
        self._live_stage_progress_current = max(0, min(100, int(pct)))
        if not self._live_stage_progress_label:
            self._live_stage_progress_label = "Working"
        self._sync_live_progress_bar()
        self.refresh_derived_paths()

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

    def _run_preflight_messages(self, stage_keys: list[str]) -> list[str]:
        if not self.active_project_slug:
            return ["Create or select a project first."]

        requested = set(stage_keys)
        messages: list[str] = []
        needs_ffs = bool(requested & {"beam", "extract", "plot", "datasheet"})
        needs_frequency = bool(requested & {"extract", "plot", "vswr", "datasheet"})
        needs_touchstone = bool(requested & {"vswr", "datasheet"})
        needs_technical_data = "datasheet" in requested
        needs_template = "datasheet" in requested

        ffs = self.selected_ffs()
        missing_ffs = self._missing_enabled_ffs()
        if needs_ffs and not ffs:
            messages.append("Add at least one enabled .ffs file.")
        if missing_ffs and (needs_ffs or "extract" in requested):
            sample = ", ".join(display_workspace_path(path) for path in missing_ffs[:3])
            more = " ..." if len(missing_ffs) > 3 else ""
            messages.append(f"Fix or disable missing .ffs files: {sample}{more}")

        s2p = self.selected_s2p()
        touchstone_ready = bool(s2p) and Path(s2p).exists()
        if needs_touchstone and not s2p:
            messages.append("Select a Touchstone .s1p or .s2p file.")
        elif s2p and not touchstone_ready and ("extract" in requested or needs_touchstone):
            messages.append(f"Fix the missing Touchstone file: {display_workspace_path(s2p)}")

        if "extract" in requested and not ffs and not touchstone_ready:
            messages.append("Extract needs at least one valid .ffs file or a valid Touchstone file.")

        if needs_technical_data:
            technical_data = self.selected_technical_data()
            if not technical_data:
                messages.append("Select a Technical Data workbook or Google Sheet.")
            elif is_url(technical_data) and not self.technical_data_is_google_sheet():
                messages.append("Use a Google Sheet link or a local workbook for Technical Data.")
            elif self.technical_data_is_google_sheet():
                if not extract_google_sheet_id(technical_data):
                    messages.append("The selected Google Sheet URL is missing a spreadsheet ID.")
                elif not self.google_sheets_auth_configured():
                    messages.append("Sign in to Google Sheets before generating the datasheet.")
            elif not Path(technical_data).exists():
                messages.append(f"Fix the missing Technical Data workbook: {display_workspace_path(technical_data)}")

        if needs_template:
            template_path = self.selected_datasheet_template_path()
            if not template_path.exists():
                messages.append(f"Select an available datasheet export style: {display_workspace_path(template_path)}")

        if needs_frequency and not self._frequency_window_is_valid():
            messages.append("Set a valid shared frequency window or clear it.")

        if "plot" in requested:
            workbook = self.deduced_beam_output()
            if not workbook.exists() and "beam" not in requested:
                messages.append("Generate the workbook before running Plots.")

        if "datasheet" in requested:
            extract_output = self.deduced_extract_output()
            if not extract_output.exists() and "extract" not in requested:
                messages.append("Generate the extract workbook before generating the datasheet.")
            elif "extract" not in requested and self._stage_is_stale("extract"):
                messages.append("Rerun Extract before generating the datasheet.")
            if not self._stage_output_exists("plot") and "plot" not in requested:
                messages.append("Generate plots before generating the datasheet.")
            elif "plot" not in requested and self._stage_is_stale("plot"):
                messages.append("Rerun Plots before generating the datasheet.")

        return messages

    def _run_preflight_passes(self, stage_keys: list[str], title: str) -> bool:
        messages = self._run_preflight_messages(stage_keys)
        if not messages:
            return True
        message = "\n".join(f"- {text}" for text in messages)
        QMessageBox.warning(self, title, f"Fix these items before running:\n\n{message}")
        self.status(messages[0])
        return False

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
        if not (self.proc.running_cmd or self.proc.queue or self._pending_stage_keys or self._current_stage_key):
            self._clear_live_run_progress()
        self._pending_stage_keys.append(stage_key)
        self._live_run_total_stages += 1
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
        self._clear_live_run_progress()
        self.proc.running_cmd = None
        self.proc.queue.clear()
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

    def reveal_stage_output(self, stage_key: str) -> None:
        if not self._stage_output_any_exists(stage_key):
            self.status("Generate that output first")
            return
        target = self._stage_output_target(stage_key)
        folder = target if stage_key == "plot" else target.parent
        open_in_file_manager(folder)

    def rerun_stage(self, stage_key: str) -> None:
        callbacks = {
            "beam": self.run_beam,
            "extract": self.run_extract,
            "datasheet": self.run_datasheet,
            "plot": self.run_plot,
            "vswr": self.run_vswr,
        }
        callback = callbacks.get(stage_key)
        if callback is None:
            self.status("That stage cannot be rerun")
            return
        callback()

    def _enqueue_stage_run_sequence(self, stage_keys: list[str]) -> bool:
        technical_data_workbook = ""
        if "datasheet" in stage_keys:
            try:
                technical_data_workbook = self.prepare_technical_data_workbook()
            except GoogleSheetDownloadError as exc:
                self.status(str(exc))
                return False
        settings = self.current_preset_settings()
        self._save_project_if_dirty()
        for stage_key in stage_keys:
            if stage_key == "beam":
                args = [which_python(), "-u", SCRIPT_BEAM, str(self.deduced_beam_output())] + self.selected_ffs() + [
                    "--smooth", str(self.beam_smooth.value()),
                    "--theta-window", str(self.theta_window.value()),
                ]
            elif stage_key == "extract":
                args = self.build_extract_args()
                if not args:
                    self.status("Extract is not ready to run")
                    return False
            elif stage_key == "plot":
                args = build_plot_command(
                    python_executable=which_python(),
                    script_path=SCRIPT_PLOT,
                    input_workbook=self.deduced_beam_output(),
                    out_dir=self.project_results_dir(),
                    settings=settings,
                    polar_port_labels_json=self.polar_port_labels_json(),
                )
            elif stage_key == "vswr":
                args = build_vswr_command(
                    python_executable=which_python(),
                    script_path=SCRIPT_VSWR,
                    touchstone_path=self.selected_s2p(),
                    output_path=self.deduced_vswr_output(),
                    settings=settings,
                )
            elif stage_key == "datasheet":
                args = [
                    which_python(),
                    "-u",
                    SCRIPT_DATASHEET,
                    str(self.deduced_datasheet_output()),
                    "--template",
                    str(self.selected_datasheet_template_path()),
                    "--extract-workbook",
                    str(self.deduced_extract_output()),
                    "--technical-data-workbook",
                    technical_data_workbook,
                    "--metadata-author",
                    self.selected_pdf_metadata_author(),
                ]
                radiation_frequencies = self.radiation_frequencies_arg()
                if radiation_frequencies is not None:
                    args.extend(["--radiation-frequencies-ghz", radiation_frequencies])
            else:
                continue
            self._enqueue_stage(stage_key, args)
        return True

    def run_needed_outputs(self) -> None:
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        if self.proc.running_cmd or self.proc.queue or self._current_stage_key or self._pending_stage_keys:
            self.status("Wait for the current run to finish")
            return
        stage_keys = self._needed_rerun_stage_keys()
        if not stage_keys:
            self.status("No failed or stale outputs need rerun")
            return
        if not self._run_preflight_passes(stage_keys, "Run Needed Preflight"):
            return
        if self._enqueue_stage_run_sequence(stage_keys):
            labels = ", ".join(STAGE_LABELS.get(key, key.title()) for key in stage_keys)
            self.status(f"Queued needed outputs: {labels}")

    def delete_stage_output(self, stage_key: str) -> None:
        files = [path for path in self._stage_output_files(stage_key) if path.exists()]
        stage_dirs = [path for path in self._stage_generated_directories(stage_key) if path.exists()]
        if not files and not stage_dirs:
            self.status("Generate that output first")
            return
        stage_label = STAGE_LABELS.get(stage_key, stage_key.title())
        answer = QMessageBox.question(
            self,
            f"Delete {stage_label}",
            f"Delete the generated {stage_label.lower()} output?",
        )
        if answer != QMessageBox.Yes:
            return
        for path in files:
            try:
                path.unlink()
            except OSError as exc:
                QMessageBox.warning(self, "Delete Failed", f"Could not delete:\n{path}\n\n{exc}")
                return
        try:
            self._remove_generated_directories([stage_key])
        except OSError as exc:
            QMessageBox.warning(self, "Delete Failed", f"Could not delete generated folder contents.\n\n{exc}")
            return
        stage_state = self._stage_state(stage_key)
        stage_state["status"] = "waiting"
        stage_state["last_finished_at"] = utc_now_iso()
        self._append_history("deleted", stage_key)
        self.save_active_project()
        self.refresh_derived_paths()
        self.status(f"Deleted {stage_label.lower()} output")

    def delete_all_outputs(self) -> None:
        if not self.active_project_slug:
            self.status("Create or select a project first")
            return
        files = [path for path in self._all_generated_output_files() if path.exists()]
        stage_dirs = [path for stage_key, _label in STAGE_DEFINITIONS for path in self._stage_generated_directories(stage_key) if path.exists()]
        if not files and not stage_dirs:
            self.status("No generated outputs to delete")
            return
        answer = QMessageBox.question(
            self,
            "Clear Generated Files",
            "Delete all generated output files for the current project directory?\n\nThe project file and saved settings will be kept.",
        )
        if answer != QMessageBox.Yes:
            return
        for path in files:
            try:
                path.unlink()
            except OSError as exc:
                QMessageBox.warning(self, "Delete Failed", f"Could not delete:\n{path}\n\n{exc}")
                return
        try:
            self._remove_generated_directories([stage_key for stage_key, _label in STAGE_DEFINITIONS])
        except OSError as exc:
            QMessageBox.warning(self, "Delete Failed", f"Could not delete generated folder contents.\n\n{exc}")
            return
        deleted_stages: list[str] = []
        for stage_key, _label in STAGE_DEFINITIONS:
            stage_files = self._stage_output_files(stage_key)
            if any(path in files for path in stage_files):
                stage_state = self._stage_state(stage_key)
                stage_state["status"] = "waiting"
                stage_state["last_finished_at"] = utc_now_iso()
                deleted_stages.append(stage_key)
        for stage_key in deleted_stages:
            self._append_history("deleted", stage_key)
        self.save_active_project()
        self.refresh_derived_paths()
        self.status("Cleared generated files")

    def on_proc_step_started(self, args: list[str], cmd: str) -> None:
        stage_key = self._pending_stage_keys.pop(0) if self._pending_stage_keys else self._detect_stage_key(args)
        self._current_stage_key = stage_key
        self._run_cancelled = False
        self._reset_live_stage_progress(stage_key, f"Starting {STAGE_LABELS.get(stage_key, stage_key.title())}" if stage_key else "")
        self._sync_live_progress_bar()
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
        if self._live_run_completed_stages < self._live_run_total_stages:
            self._live_run_completed_stages += 1
        self._reset_live_stage_progress()
        self._sync_live_progress_bar()
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
        if self.proc.queue:
            self.run_info.setText("Advancing to next stage...")
            return
        self._clear_live_run_progress()
        self.run_info.setText("Idle")
        self.refresh_derived_paths()

    def _update_run_info(self):
        if not (self._current_stage_key or self.proc.running_cmd or self.proc.queue):
            return
        elapsed = int(time.time() - getattr(self, "_started_ts", time.time()))
        mm, ss = divmod(elapsed, 60)
        hh, mm = divmod(mm, 60)
        text = f"Running {self._running_stage_label()} | {hh:02d}:{mm:02d}:{ss:02d}"
        if self._live_stage_progress_total > 0:
            text = (
                f"Running {self._running_stage_label()} | "
                f"{self._live_stage_progress_current}/{self._live_stage_progress_total} | "
                f"{hh:02d}:{mm:02d}:{ss:02d}"
            )
        self.run_info.setText(text)

    def run_beam(self):
        if not self._run_preflight_passes(["beam"], "Workbook Preflight"):
            return
        out = str(self.deduced_beam_output())
        ffs = self.selected_ffs()
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
        if not self._run_preflight_passes(["extract"], "Extract Preflight"):
            return
        args = self.build_extract_args()
        if not args:
            self.status("Add a valid .ffs or Touchstone input and fix the shared frequency window if needed")
            return
        self._save_project_if_dirty()
        self._enqueue_stage("extract", args)

    def run_datasheet(self):
        if not self._run_preflight_passes(["datasheet"], "Datasheet Preflight"):
            return
        template_path = self.selected_datasheet_template_path()
        s2p = self.selected_s2p()
        extract_output = self.deduced_extract_output()
        try:
            technical_data_workbook = self.prepare_technical_data_workbook()
        except GoogleSheetDownloadError as exc:
            self.status(str(exc))
            return
        args = [
            which_python(),
            "-u",
            SCRIPT_DATASHEET,
            str(self.deduced_datasheet_output()),
            "--template",
            str(template_path),
            "--extract-workbook",
            str(extract_output),
            "--technical-data-workbook",
            technical_data_workbook,
            "--metadata-author",
            self.selected_pdf_metadata_author(),
        ]
        radiation_frequencies = self.radiation_frequencies_arg()
        if radiation_frequencies is not None:
            args.extend(["--radiation-frequencies-ghz", radiation_frequencies])
        self._save_project_if_dirty()
        self._enqueue_stage("datasheet", args)

    def run_plot(self):
        if not self._run_preflight_passes(["plot"], "Plots Preflight"):
            return
        xlsx = self.deduced_beam_output()
        args = build_plot_command(
            python_executable=which_python(),
            script_path=SCRIPT_PLOT,
            input_workbook=xlsx,
            out_dir=self.project_results_dir(),
            settings=self.current_preset_settings(),
            polar_port_labels_json=self.polar_port_labels_json(),
        )
        self._save_project_if_dirty()
        self._enqueue_stage("plot", args)

    def run_vswr(self):
        if not self._run_preflight_passes(["vswr"], "VSWR Preflight"):
            return
        s2p = self.selected_s2p()
        args = build_vswr_command(
            python_executable=which_python(),
            script_path=SCRIPT_VSWR,
            touchstone_path=s2p,
            output_path=self.deduced_vswr_output(),
            settings=self.current_preset_settings(),
        )
        self._save_project_if_dirty()
        self._enqueue_stage("vswr", args)

    def run_full(self):
        if not self._run_preflight_passes(["beam", "extract", "plot", "vswr", "datasheet"], "Full Pipeline Preflight"):
            return
        out = str(self.deduced_beam_output())
        ffs = self.selected_ffs()
        template_path = self.selected_datasheet_template_path()
        s2p = self.selected_s2p()
        try:
            technical_data_workbook = self.prepare_technical_data_workbook()
        except GoogleSheetDownloadError as exc:
            self.status(str(exc))
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

        settings = self.current_preset_settings()
        args_plot = build_plot_command(
            python_executable=which_python(),
            script_path=SCRIPT_PLOT,
            input_workbook=out,
            out_dir=self.project_results_dir(),
            settings=settings,
            polar_port_labels_json=self.polar_port_labels_json(),
        )
        self._enqueue_stage("plot", args_plot)

        args_vswr = build_vswr_command(
            python_executable=which_python(),
            script_path=SCRIPT_VSWR,
            touchstone_path=s2p,
            output_path=self.deduced_vswr_output(),
            settings=settings,
        )
        self._enqueue_stage("vswr", args_vswr)
        if args_extract:
            datasheet_args = [
                which_python(),
                "-u",
                SCRIPT_DATASHEET,
                str(self.deduced_datasheet_output()),
                "--template",
                str(template_path),
                "--extract-workbook",
                str(self.deduced_extract_output()),
                "--technical-data-workbook",
                technical_data_workbook,
                "--metadata-author",
                self.selected_pdf_metadata_author(),
            ]
            radiation_frequencies = self.radiation_frequencies_arg()
            if radiation_frequencies is not None:
                datasheet_args.extend(["--radiation-frequencies-ghz", radiation_frequencies])
            self._enqueue_stage("datasheet", datasheet_args)
