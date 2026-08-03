from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QMessageBox

from pipeline.commands import build_compliance_command, build_datasheet_command, build_plot_command, build_vswr_command
from pipeline.preflight import collect_preflight_issues
from pipeline.run_context import RunContext
from project_store import utc_now_iso
from studio_runtime import (
    GoogleSheetDownloadError,
    STAGE_DEFINITIONS,
    STAGE_LABELS,
    extract_google_sheet_id,
)
from studio_support import (
    SCRIPT_BEAM,
    SCRIPT_COMPLIANCE,
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
    def _technical_data_sheet_name(self) -> str:
        return "Datasheet" if self.technical_data_is_google_sheet() else ""

    def _stage_validation_status(self, stage_key: str) -> tuple[str, list[str]]:
        blockers = self._run_preflight_messages([stage_key])
        if blockers:
            return "Blocked", blockers
        if not self._stage_is_applicable(stage_key):
            return "Not applicable", []
        if self._stage_output_exists(stage_key):
            if self._stage_is_stale(stage_key):
                detail = self._stage_stale_detail(stage_key)
                return "Stale", [detail] if detail else []
            return "Ready", []
        return "Ready to run", []

    def _build_validation_report(self) -> str:
        lines: list[str] = []
        project_name = self.active_project_name or self.active_project_slug or "None"
        lines.append(f"Project: {project_name}")
        lines.append(f"Path: {display_workspace_path(self.project_results_dir())}")
        lines.append("")
        lines.append("Overall preflight")
        overall = self._run_preflight_messages([stage_key for stage_key, _ in STAGE_DEFINITIONS])
        if overall:
            for message in overall:
                lines.append(f"- {message}")
        else:
            lines.append("- All required inputs are valid for a full run.")
        lines.append("")
        lines.append("Stage readiness")
        for stage_key, stage_label in STAGE_DEFINITIONS:
            status, notes = self._stage_validation_status(stage_key)
            lines.append(f"- {stage_label}: {status}")
            for note in notes:
                lines.append(f"  - {note}")
        needed = self._needed_rerun_stage_keys()
        if needed:
            labels = ", ".join(STAGE_LABELS.get(key, key.title()) for key in needed)
            lines.append("")
            lines.append(f"Suggested rerun: {labels}")
        return "\n".join(lines)

    def validate_project(self) -> None:
        if not self.active_project_slug:
            self.status("Create or select a project first")
            QMessageBox.information(self, "Validate Project", "Create or select a project first.")
            return
        report = self._build_validation_report()
        QMessageBox.information(self, "Validate Project", report)
        self.status("Validation report generated")

    def _build_run_context(self, settings=None, touchstone_path: str | None = None) -> RunContext:
        active_settings = settings or self.current_preset_settings()
        return RunContext(
            project_slug=str(self.active_project_slug or ""),
            project_dir=self.project_results_dir(),
            beam_output=self.deduced_beam_output(),
            extract_output=self.deduced_extract_output(),
            datasheet_output=self.deduced_datasheet_output(),
            vswr_output=self.deduced_vswr_output(),
            settings=active_settings,
            compliance_output=self.deduced_compliance_output(),
            polar_port_labels_json=self.polar_port_labels_json(),
            touchstone_path=str(touchstone_path if touchstone_path is not None else (self.selected_s2p() or "")),
        )

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

    def _show_run_start_feedback(self, label: str) -> None:
        self._clear_live_run_progress()
        self._reset_live_stage_progress("", label)
        self.set_busy(True)
        self.run_info.setText(label)
        self.status(label)
        QCoreApplication.processEvents()

    def _clear_run_start_feedback_if_idle(self) -> None:
        if self.proc.running_cmd or self.proc.queue or self._pending_stage_keys or self._current_stage_key:
            return
        self._clear_live_run_progress()
        self.set_busy(False)
        self.run_info.setText("Idle")
        self.refresh_derived_paths()

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
        self.request_derived_paths_refresh()

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
        self.request_derived_paths_refresh()

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
        enabled_ffs = self.selected_ffs()
        missing_ffs = self._missing_enabled_ffs()
        s2p = self.selected_s2p()
        technical_data = self.selected_technical_data()
        technical_data_is_google_sheet = self.technical_data_is_google_sheet()
        technical_data_exists = bool(technical_data) and Path(technical_data).exists()
        touchstone_ready = bool(s2p) and Path(s2p).exists()
        template_path = self.selected_datasheet_template_path()
        issues = collect_preflight_issues(
            stage_keys=stage_keys,
            has_active_project=bool(self.active_project_slug),
            enabled_ffs=enabled_ffs,
            missing_ffs_display=[display_workspace_path(path) for path in missing_ffs],
            touchstone_selected=bool(s2p),
            touchstone_ready=touchstone_ready,
            touchstone_display=display_workspace_path(s2p) if s2p else "",
            technical_data=str(technical_data or ""),
            technical_data_is_url=is_url(technical_data),
            technical_data_is_google_sheet=technical_data_is_google_sheet,
            google_sheet_has_id=bool(extract_google_sheet_id(technical_data)) if technical_data_is_google_sheet else False,
            google_sheets_auth_configured=self.google_sheets_auth_configured(),
            technical_data_exists=technical_data_exists,
            technical_data_display=display_workspace_path(technical_data) if technical_data else "",
            template_exists=template_path.exists(),
            template_display=display_workspace_path(template_path),
            frequency_window_valid=self._frequency_window_is_valid(),
            beam_output_exists=self.deduced_beam_output().exists(),
            extract_output_exists=self.deduced_extract_output().exists(),
            extract_stage_stale=self._stage_is_stale("extract"),
            plot_output_exists=self._stage_output_exists("plot"),
            plot_stage_stale=self._stage_is_stale("plot"),
        )
        messages = [issue.message for issue in issues]
        if "plot" in stage_keys and "beam" not in stage_keys and self.deduced_beam_output().exists() and self._stage_is_stale("beam"):
            messages.append("Rerun Workbook before generating plots because the workbook is stale.")
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
            Path(SCRIPT_COMPLIANCE).name.lower(): "compliance",
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

    def _enqueue_stage_batch(self, stage_commands: list[tuple[str, list[str]]]) -> None:
        commands = [(stage_key, args) for stage_key, args in stage_commands if args]
        if not commands:
            return
        if not (self.proc.running_cmd or self.proc.queue or self._pending_stage_keys or self._current_stage_key):
            self._clear_live_run_progress()
        self._pending_stage_keys.extend(stage_key for stage_key, _args in commands)
        self._live_run_total_stages += len(commands)
        self.proc.enqueue_many([args for _stage_key, args in commands])
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
            "compliance": self.run_compliance,
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
        context = self._build_run_context(settings=settings)
        self._save_project_if_dirty()
        for stage_key in stage_keys:
            if stage_key == "beam":
                args = [which_python(), "-u", SCRIPT_BEAM, str(context.beam_output)] + self.selected_ffs() + [
                    "--smooth", str(self.beam_smooth.value()),
                    "--theta-window", str(self.theta_window.value()),
                ]
            elif stage_key == "compliance":
                args = build_compliance_command(
                    python_executable=which_python(),
                    script_path=SCRIPT_COMPLIANCE,
                    ffs_paths=self.selected_ffs(),
                    context=context,
                )
            elif stage_key == "extract":
                args = self.build_extract_args()
                if not args:
                    self.status("Extract is not ready to run")
                    return False
            elif stage_key == "plot":
                args = build_plot_command(
                    python_executable=which_python(),
                    script_path=SCRIPT_PLOT,
                    context=context,
                )
            elif stage_key == "vswr":
                args = build_vswr_command(
                    python_executable=which_python(),
                    script_path=SCRIPT_VSWR,
                    context=context,
                )
            elif stage_key == "datasheet":
                args = build_datasheet_command(
                    python_executable=which_python(),
                    script_path=SCRIPT_DATASHEET,
                    template_path=self.selected_datasheet_template_path(),
                    technical_data_workbook=technical_data_workbook,
                    technical_data_sheet=self._technical_data_sheet_name(),
                    metadata_author=self.selected_pdf_metadata_author(),
                    radiation_frequencies_ghz=self.radiation_frequencies_arg(),
                    context=context,
                )
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
        self.clear_derived_path_cache()
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
        self.clear_derived_path_cache()
        deleted_stages: list[str] = []
        for stage_key, _label in STAGE_DEFINITIONS:
            stage_files = self._stage_output_files(stage_key)
            if any(path in files for path in stage_files) or any(path in stage_dirs for path in self._stage_generated_directories(stage_key)):
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
        stage_state.pop("blocked_by", None)
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

    def on_proc_batch_aborted(self, failed_args: list[str], exit_code: int, skipped_commands: list[list[str]]) -> None:
        failed_stage = self._detect_stage_key(failed_args)
        finished_at = utc_now_iso()
        skipped_keys: list[str] = []
        for command in skipped_commands:
            stage_key = self._detect_stage_key(command)
            if not stage_key:
                continue
            skipped_keys.append(stage_key)
            stage_state = self._stage_state(stage_key)
            stage_state["status"] = "blocked"
            stage_state["blocked_by"] = failed_stage
            stage_state["last_finished_at"] = finished_at
            self._append_history("blocked", stage_key, blocked_by=failed_stage, exit_code=int(exit_code))
        self._pending_stage_keys = []
        self._current_stage_key = ""
        if skipped_keys:
            labels = ", ".join(STAGE_LABELS.get(key, key.title()) for key in skipped_keys)
            self.status(f"Pipeline stopped after {STAGE_LABELS.get(failed_stage, failed_stage.title())} failed; blocked: {labels}")
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

    def run_compliance(self):
        if not self._run_preflight_passes(["compliance"], "Compliance Preflight"):
            return
        context = self._build_run_context()
        args = build_compliance_command(
            python_executable=which_python(),
            script_path=SCRIPT_COMPLIANCE,
            ffs_paths=self.selected_ffs(),
            context=context,
        )
        self._save_project_if_dirty()
        self._enqueue_stage("compliance", args)

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
        settings = self.current_preset_settings()
        context = self._build_run_context(settings=settings)
        args = build_datasheet_command(
            python_executable=which_python(),
            script_path=SCRIPT_DATASHEET,
            output_path=self.deduced_datasheet_output(),
            template_path=template_path,
            extract_workbook=extract_output,
            technical_data_workbook=technical_data_workbook,
            technical_data_sheet=self._technical_data_sheet_name(),
            settings=settings,
            metadata_author=self.selected_pdf_metadata_author(),
            radiation_frequencies_ghz=self.radiation_frequencies_arg(),
            context=context,
        )
        self._save_project_if_dirty()
        self._enqueue_stage("datasheet", args)

    def run_plot(self):
        if not self._run_preflight_passes(["plot"], "Plots Preflight"):
            return
        context = self._build_run_context()
        args = build_plot_command(
            python_executable=which_python(),
            script_path=SCRIPT_PLOT,
            context=context,
        )
        self._save_project_if_dirty()
        self._enqueue_stage("plot", args)

    def run_vswr(self):
        if not self._run_preflight_passes(["vswr"], "VSWR Preflight"):
            return
        context = self._build_run_context(touchstone_path=self.selected_s2p())
        args = build_vswr_command(
            python_executable=which_python(),
            script_path=SCRIPT_VSWR,
            context=context,
        )
        self._save_project_if_dirty()
        self._enqueue_stage("vswr", args)

    def run_full(self):
        if not self._run_preflight_passes(["beam", "compliance", "extract", "plot", "vswr", "datasheet"], "Full Pipeline Preflight"):
            return
        self._show_run_start_feedback("Preparing full pipeline...")
        context = self._build_run_context()
        out = str(context.beam_output)
        ffs = self.selected_ffs()
        template_path = self.selected_datasheet_template_path()
        try:
            technical_data_workbook = self.prepare_technical_data_workbook()
        except GoogleSheetDownloadError as exc:
            self._clear_run_start_feedback_if_idle()
            self.status(str(exc))
            return

        args_beam = [which_python(), "-u", SCRIPT_BEAM, out] + ffs + [
            "--smooth", str(self.beam_smooth.value()),
            "--theta-window", str(self.theta_window.value())
        ]
        stage_commands: list[tuple[str, list[str]]] = [("beam", args_beam)]

        stage_commands.append(
            (
                "compliance",
                build_compliance_command(
                    python_executable=which_python(),
                    script_path=SCRIPT_COMPLIANCE,
                    ffs_paths=ffs,
                    context=context,
                ),
            )
        )

        args_extract = self.build_extract_args()
        if args_extract:
            stage_commands.append(("extract", args_extract))

        settings = self.current_preset_settings()
        context = self._build_run_context(settings=settings)
        args_plot = build_plot_command(
            python_executable=which_python(),
            script_path=SCRIPT_PLOT,
            context=context,
        )
        stage_commands.append(("plot", args_plot))

        args_vswr = build_vswr_command(
            python_executable=which_python(),
            script_path=SCRIPT_VSWR,
            context=context,
        )
        stage_commands.append(("vswr", args_vswr))
        if args_extract:
            datasheet_args = build_datasheet_command(
                python_executable=which_python(),
                script_path=SCRIPT_DATASHEET,
                template_path=template_path,
                technical_data_workbook=technical_data_workbook,
                technical_data_sheet=self._technical_data_sheet_name(),
                metadata_author=self.selected_pdf_metadata_author(),
                radiation_frequencies_ghz=self.radiation_frequencies_arg(),
                context=context,
            )
            stage_commands.append(("datasheet", datasheet_args))
        self._save_project_if_dirty()
        self._enqueue_stage_batch(stage_commands)
