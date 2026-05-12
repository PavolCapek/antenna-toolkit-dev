from __future__ import annotations

from studio_dirty_state_base import *


class StudioRunWorkflowTests(StudioDirtyStateBase):
    def test_run_preflight_reports_all_full_pipeline_blockers(self) -> None:
        missing_ffs = Path(self.temp_dir.name) / "missing.ffs"
        self.window._add_ffs_files([str(missing_ffs)])
        self.window.shared_fmin.setValue(6.0)
        self.window.shared_fmax.setValue(5.0)
        self.app.processEvents()

        messages = self.window._run_preflight_messages(["beam", "extract", "plot", "vswr", "datasheet"])

        self.assertTrue(any("missing .ffs" in message for message in messages))
        self.assertTrue(any("Touchstone" in message for message in messages))
        self.assertTrue(any("Technical Data" in message for message in messages))
        self.assertTrue(any("frequency window" in message for message in messages))
        self.assertGreaterEqual(len(messages), 4)

    def test_validate_project_shows_dry_run_report(self) -> None:
        with mock.patch("antenna_toolkit_studio.QMessageBox.information") as info:
            self.window.validate_project()

        info.assert_called_once()
        _parent, title, report = info.call_args.args
        self.assertEqual(title, "Validate Project")
        self.assertIn("Overall preflight", report)
        self.assertIn("Stage readiness", report)
        self.assertIn("Workbook", report)

    def test_run_button_shows_preflight_warning_without_starting(self) -> None:
        with mock.patch("antenna_toolkit_studio.QMessageBox.warning") as warning:
            self.window.run_beam()

        warning.assert_called_once()
        self.assertFalse(self.window.proc.queue)
        self.assertIsNone(self.window.proc.running_cmd)

    def test_needed_rerun_prefers_latest_failed_stage(self) -> None:
        self.window.project_run_state = {
            "stages": {
                "beam": {
                    "status": "failed",
                    "last_finished_at": "2026-04-30T10:00:00Z",
                },
                "plot": {
                    "status": "failed",
                    "last_finished_at": "2026-04-30T11:00:00Z",
                },
            }
        }

        self.assertEqual(self.window._latest_failed_stage_key(), "plot")

    def test_run_needed_outputs_queues_only_needed_stages(self) -> None:
        with (
            mock.patch.object(self.window, "_needed_rerun_stage_keys", return_value=["beam", "plot"]),
            mock.patch.object(self.window, "_run_preflight_passes", return_value=True),
            mock.patch.object(self.window, "_save_project_if_dirty"),
            mock.patch.object(self.window, "_enqueue_stage") as enqueue,
        ):
            self.window.run_needed_outputs()

        self.assertEqual([call.args[0] for call in enqueue.call_args_list], ["beam", "plot"])

    def test_clear_generated_files_refreshes_ready_stage_pills(self) -> None:
        ffs_path = Path(self.temp_dir.name) / "sample.ffs"
        ffs_path.write_text("ffs", encoding="utf-8")
        self.window._add_ffs_files([str(ffs_path)])
        self.window.save_project_changes()
        beam_output = self.window.deduced_beam_output()
        beam_output.parent.mkdir(parents=True, exist_ok=True)
        beam_output.write_text("workbook", encoding="utf-8")
        stage_state = self.window._stage_state("beam")
        stage_state["status"] = "success"
        stage_state["last_success_at"] = "2026-04-30T12:00:00Z"
        stage_state["snapshot"] = self.window._current_stage_snapshot("beam")

        self.window.refresh_derived_paths()
        self.app.processEvents()
        self.assertEqual(self.window.stage_chip_labels["beam"].text(), "Ready")

        with mock.patch("antenna_toolkit_studio.QMessageBox.question", return_value=QMessageBox.Yes):
            self.window.delete_all_outputs()
        self.app.processEvents()

        self.assertFalse(beam_output.exists())
        self.assertEqual(self.window.stage_chip_labels["beam"].text(), "Waiting")

    def test_needed_rerun_combines_failed_and_stale_with_skip_summary(self) -> None:
        self.window.project_run_state = {
            "stages": {
                "beam": {
                    "status": "success",
                    "last_success_at": "2026-04-30T09:00:00Z",
                    "snapshot": self.window._current_stage_snapshot("beam"),
                },
                "plot": {
                    "status": "failed",
                    "last_finished_at": "2026-04-30T11:00:00Z",
                },
                "vswr": {
                    "status": "success",
                    "last_success_at": "2026-04-30T09:00:00Z",
                    "snapshot": self.window._current_stage_snapshot("vswr"),
                },
            }
        }
        with (
            mock.patch.object(self.window, "_stale_stage_keys", return_value=["vswr"]),
            mock.patch.object(self.window, "_stage_is_applicable", return_value=True),
            mock.patch.object(self.window, "_stage_output_exists", return_value=True),
            mock.patch.object(self.window, "_stage_is_stale", side_effect=lambda key: key == "vswr"),
        ):
            self.assertEqual(self.window._needed_rerun_stage_keys(), ["plot", "vswr"])
            summary = self.window._recovery_plan_text()

        self.assertIn("failed: Plots", summary)
        self.assertIn("stale: VSWR", summary)
        self.assertIn("skip current outputs", summary)
        self.assertIn("Workbook", summary)

    def test_old_plot_asset_snapshot_marks_plot_outputs_stale(self) -> None:
        ffs_path = Path(self.temp_dir.name) / "sample.ffs"
        ffs_path.write_text("ffs", encoding="utf-8")
        self.window._add_ffs_files([{"path": str(ffs_path), "enabled": True, "port_label": "Port 1"}])
        project_dir = self.window.project_results_dir()
        stem = self.window.deduced_beam_output().stem
        for suffix in (
            "gain",
            "gain-legend",
            "beamwidth",
            "beamwidth-legend",
            "beam-efficiency",
            "beam-efficiency-legend",
        ):
            path = project_dir / f"{stem}-{suffix}.svg"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("<svg />", encoding="utf-8")
        artifact_manifest = project_dir / f"{stem}-artifacts.json"
        artifact_manifest.write_text("{}", encoding="utf-8")

        legacy_snapshot = dict(self.window._current_stage_snapshot("plot"))
        legacy_snapshot.pop("tool_versions", None)
        self.window._stage_state("plot").update(
            {
                "status": "success",
                "last_success_at": "2026-04-24T12:00:00+00:00",
                "snapshot": legacy_snapshot,
            }
        )

        self.assertTrue(self.window._stage_is_stale("plot"))
        self.assertEqual(self.window._stage_stale_detail("plot"), "App plot styling changed. Rerun Plots only.")
        self.window.refresh_derived_paths()
        self.app.processEvents()
        self.assertEqual(self.window.stage_status_labels["plot"].text(), "App plot styling changed. Rerun Plots only.")

    def test_successful_plot_and_datasheet_snapshots_include_tool_versions(self) -> None:
        ffs_path = Path(self.temp_dir.name) / "sample.ffs"
        s2p_path = Path(self.temp_dir.name) / "sample.s2p"
        technical_path = Path(self.temp_dir.name) / "technical.xlsx"
        for path, content in (
            (ffs_path, "ffs"),
            (s2p_path, "s2p"),
            (technical_path, "xlsx"),
            (self.window.deduced_beam_output(), "beam"),
            (self.window.deduced_extract_output(), "extract"),
            (self.window.deduced_datasheet_output(), "pdf"),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.window._add_ffs_files([{"path": str(ffs_path), "enabled": True, "port_label": "Port 1"}])
        self.window._set_touchstone(str(s2p_path))
        self.window._set_technical_data(str(technical_path))
        for path in self.window._stage_output_files("plot"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("<svg />", encoding="utf-8")

        plot_args = [studio_module.SCRIPT_PLOT]
        self.window.on_proc_step_started(plot_args, "plot.py")
        self.window.on_proc_step_finished(plot_args, 0, None)
        plot_snapshot = self.window._stage_state("plot")["snapshot"]

        self.assertEqual(
            plot_snapshot["tool_versions"]["plot_assets"],
            studio_module.PLOT_ASSET_STYLE_VERSION,
        )
        self.assertFalse(self.window._stage_is_stale("plot"))

        datasheet_args = [studio_module.SCRIPT_DATASHEET]
        self.window.on_proc_step_started(datasheet_args, "datasheet_pdf.py")
        self.window.on_proc_step_finished(datasheet_args, 0, None)
        datasheet_snapshot = self.window._stage_state("datasheet")["snapshot"]

        self.assertEqual(
            datasheet_snapshot["tool_versions"]["plot_assets"],
            studio_module.PLOT_ASSET_STYLE_VERSION,
        )
        self.assertEqual(
            datasheet_snapshot["tool_versions"]["datasheet_render"],
            studio_module.DATASHEET_RENDER_VERSION,
        )
        self.assertFalse(self.window._stage_is_stale("datasheet"))

    def test_stage_output_files_are_cached_during_refresh(self) -> None:
        beam_output = self.window.deduced_beam_output()
        with mock.patch("antenna_toolkit_studio.stage_output_files", return_value=[beam_output]) as output_files:
            self.window._refresh_cache = {}
            self.window._refresh_cache_enabled = True
            try:
                first = self.window._stage_output_files("beam")
                second = self.window._stage_output_files("beam")
            finally:
                self.window._refresh_cache = {}
                self.window._refresh_cache_enabled = False

        self.assertEqual(first, [beam_output])
        self.assertEqual(second, [beam_output])
        output_files.assert_called_once()

    def test_pipeline_buttons_include_recovery_action(self) -> None:
        labels = [button.text() for button in self.window.hero_actions._buttons]

        self.assertEqual(labels, ["Run Full Pipeline", "Run Needed Only", "Clear Generated Files"])
        self.assertFalse(self.window.btn_run_needed.isHidden())
        self.assertFalse(self.window.btn_run_needed.isEnabled())
        self.assertEqual(self.window.btn_validate.parent(), self.window.readiness_card)

    def test_pipeline_stage_list_gates_actions_by_output_state(self) -> None:
        self.assertEqual(set(self.window.stage_open_buttons.keys()), {"beam", "extract", "datasheet", "plot", "vswr"})
        self.assertEqual(set(self.window.stage_timestamp_labels.keys()), {"beam", "extract", "datasheet", "plot", "vswr"})
        self.assertEqual(set(self.window.stage_chip_labels.keys()), {"beam", "extract", "datasheet", "plot", "vswr"})
        self.assertEqual(set(self.window.stage_more_buttons.keys()), {"beam", "extract", "datasheet", "plot", "vswr"})

        with (
            mock.patch.object(self.window, "_stage_output_exists", return_value=False),
            mock.patch.object(self.window, "_stage_output_any_exists", return_value=False),
            mock.patch.object(self.window, "_stage_is_applicable", return_value=True),
        ):
            self.window.refresh_derived_paths()
            self.app.processEvents()
            self.assertTrue(all(button.isHidden() for button in self.window.stage_open_buttons.values()))
            self.assertTrue(all(button.isEnabled() for button in self.window.stage_rerun_buttons.values()))
            self.assertTrue(all(not button.isHidden() for button in self.window.stage_rerun_buttons.values()))
            self.assertTrue(all(not button.isHidden() for button in self.window.stage_more_buttons.values()))
            self.assertTrue(all(not button.isEnabled() for button in self.window.stage_more_buttons.values()))
            self.assertTrue(all(not action.isEnabled() for action in self.window.stage_reveal_actions.values()))
            self.assertTrue(all(not action.isEnabled() for action in self.window.stage_delete_actions.values()))

        with (
            mock.patch.object(self.window, "_stage_output_exists", side_effect=lambda stage_key: stage_key == "beam"),
            mock.patch.object(self.window, "_stage_output_any_exists", side_effect=lambda stage_key: stage_key == "beam"),
            mock.patch.object(self.window, "_stage_is_applicable", return_value=True),
        ):
            self.window.refresh_derived_paths()
            self.app.processEvents()
            self.assertFalse(self.window.stage_open_buttons["beam"].isHidden())
            self.assertTrue(self.window.stage_open_buttons["beam"].isEnabled())
            self.assertTrue(self.window.stage_more_buttons["beam"].isEnabled())
            self.assertTrue(self.window.stage_reveal_actions["beam"].isEnabled())
            self.assertTrue(self.window.stage_delete_actions["beam"].isEnabled())
            self.assertTrue(self.window.stage_open_buttons["extract"].isHidden())
            self.assertFalse(self.window.stage_more_buttons["extract"].isEnabled())
            self.assertFalse(self.window.stage_reveal_actions["extract"].isEnabled())
            self.assertFalse(self.window.stage_delete_actions["extract"].isEnabled())
            self.assertTrue(self.window.stage_open_buttons["datasheet"].isHidden())
            self.assertTrue(self.window.stage_open_buttons["plot"].isHidden())
            self.assertTrue(self.window.stage_open_buttons["vswr"].isHidden())

        with (
            mock.patch.object(self.window, "_stage_output_exists", return_value=False),
            mock.patch.object(self.window, "_stage_output_any_exists", return_value=False),
            mock.patch.object(self.window, "_stage_is_applicable", side_effect=lambda stage_key: stage_key != "vswr"),
        ):
            self.window.refresh_derived_paths()
            self.app.processEvents()
            self.assertTrue(self.window.stage_rerun_buttons["vswr"].isHidden())
            self.assertTrue(self.window.stage_more_buttons["vswr"].isHidden())
            self.assertEqual(self.window.stage_status_labels["vswr"].text(), "Not configured for this project.")
            self.assertEqual(self.window.stage_timestamp_labels["vswr"].text(), "Generated: not applicable")
            self.assertEqual(self.window.stage_chip_labels["vswr"].text(), "Off")

    @pytest.mark.export_acceptance
    def test_run_full_queues_datasheet_stage(self) -> None:
        ffs_path = Path(self.temp_dir.name) / "sample.ffs"
        s2p_path = Path(self.temp_dir.name) / "sample.s2p"
        technical_data_path = Path(self.temp_dir.name) / "technical.xlsx"
        ffs_path.write_text(
            "// #Frequencies\n2\nRadiated/Accepted/Stimulated Power\n0.1\n0.2\n0.3\n4.9e9\n\n0.1\n0.2\n0.3\n6.0e9\n",
            encoding="utf-8",
        )
        s2p_path.write_text("s2p", encoding="utf-8")
        technical_data_path.write_text("xlsx", encoding="utf-8")
        self.window._add_ffs_files([{"path": str(ffs_path), "enabled": True, "port_label": "Port 1"}])
        self.window.refresh_radiation_frequency_list()
        self.window._set_radiation_frequency_selection([4.9, 6.0])
        self.window._set_touchstone(str(s2p_path))
        self.window._set_technical_data(str(technical_data_path))
        self.window.pdf_metadata_author.setText("Pipeline Author")
        self.window.cartesian_figure_width.setValue(9.75)
        self.window.cartesian_figure_height.setValue(4.5)
        self.window.polar_figure_size.setValue(7.75)
        self.window.polar_azimuth_line1.set_color("#111111")
        self.window.polar_azimuth_line1.set_style("solid")
        self.window.polar_azimuth_line2.set_color("#222222")
        self.window.polar_azimuth_line2.set_style("dashed")
        self.window.polar_elevation_line1.set_color("#333333")
        self.window.polar_elevation_line1.set_style("dashed")
        self.window.polar_elevation_line2.set_color("#444444")
        self.window.polar_elevation_line2.set_style("solid")
        self.app.processEvents()

        queued: list[str] = []
        queued_args: dict[str, list[str]] = {}

        with (
            mock.patch.object(self.window, "_save_project_if_dirty"),
            mock.patch.object(
                self.window,
                "_enqueue_stage",
                side_effect=lambda stage_key, args: (queued.append(stage_key), queued_args.setdefault(stage_key, args)),
            ),
        ):
            self.window.run_full()

        self.assertEqual(queued, ["beam", "extract", "plot", "vswr", "datasheet"])
        self.assertIn("--beamwidth-db-colors", queued_args["plot"])
        self.assertEqual(queued_args["plot"][queued_args["plot"].index("--cartesian-figure-width") + 1], "9.75")
        self.assertEqual(queued_args["plot"][queued_args["plot"].index("--cartesian-figure-height") + 1], "4.5")
        self.assertEqual(queued_args["plot"][queued_args["plot"].index("--polar-figure-size") + 1], "7.75")
        self.assertEqual(queued_args["plot"][queued_args["plot"].index("--polar-line-colors") + 1], "#111111,#222222,#333333,#444444")
        self.assertEqual(queued_args["plot"][queued_args["plot"].index("--polar-line-styles") + 1], "solid,dashed,dashed,solid")
        self.assertIn("--polar-port-labels-json", queued_args["plot"])
        plot_port_labels = json.loads(queued_args["plot"][queued_args["plot"].index("--polar-port-labels-json") + 1])
        self.assertIn("sample", plot_port_labels)
        self.assertEqual(plot_port_labels["sample"], "Port 1")
        self.assertEqual(queued_args["vswr"][queued_args["vswr"].index("--cartesian-figure-width") + 1], "9.75")
        self.assertEqual(queued_args["vswr"][queued_args["vswr"].index("--cartesian-figure-height") + 1], "4.5")
        self.assertIn("--template", queued_args["datasheet"])
        self.assertEqual(Path(queued_args["datasheet"][queued_args["datasheet"].index("--template") + 1]).name, "Datasheet - RFE.pdf")
        self.assertIn("--metadata-author", queued_args["datasheet"])
        self.assertEqual(queued_args["datasheet"][queued_args["datasheet"].index("--metadata-author") + 1], "Pipeline Author")
        self.assertEqual(queued_args["datasheet"][queued_args["datasheet"].index("--cartesian-figure-width") + 1], "9.75")
        self.assertEqual(queued_args["datasheet"][queued_args["datasheet"].index("--cartesian-figure-height") + 1], "4.5")
        self.assertEqual(queued_args["datasheet"][queued_args["datasheet"].index("--polar-figure-size") + 1], "7.75")
        self.assertEqual(queued_args["datasheet"][queued_args["datasheet"].index("--radiation-frequencies-ghz") + 1], "4.9,6")

    @pytest.mark.export_acceptance
    def test_run_plot_passes_beamwidth_db_colors(self) -> None:
        beam_output = self.window.deduced_beam_output()
        beam_output.parent.mkdir(parents=True, exist_ok=True)
        beam_output.write_text("xlsx", encoding="utf-8")
        ffs_path = Path(self.temp_dir.name) / "plot_sample.ffs"
        ffs_path.write_text("ffs", encoding="utf-8")
        self.window._add_ffs_files([{"path": str(ffs_path), "enabled": True, "port_label": "+45"}])
        self.window.beamwidth_3db_color.set_color("#aa0000")
        self.window.beamwidth_6db_color.set_color("#777777")
        self.window.beamwidth_10db_color.set_color("#111111")
        self.window.cartesian_figure_width.setValue(9.25)
        self.window.cartesian_figure_height.setValue(3.75)
        self.window.polar_figure_size.setValue(6.5)
        self.window.polar_azimuth_line1.set_color("#121212")
        self.window.polar_azimuth_line1.set_style("dashed")
        self.window.polar_azimuth_line2.set_color("#232323")
        self.window.polar_azimuth_line2.set_style("solid")
        self.window.polar_elevation_line1.set_color("#343434")
        self.window.polar_elevation_line1.set_style("solid")
        self.window.polar_elevation_line2.set_color("#454545")
        self.window.polar_elevation_line2.set_style("dashed")
        self.app.processEvents()

        queued: list[str] = []
        queued_args: dict[str, list[str]] = {}

        with (
            mock.patch.object(self.window, "_save_project_if_dirty"),
            mock.patch.object(
                self.window,
                "_enqueue_stage",
                side_effect=lambda stage_key, args: (queued.append(stage_key), queued_args.setdefault(stage_key, args)),
            ),
        ):
            self.window.run_plot()

        self.assertEqual(queued, ["plot"])
        plot_args = queued_args["plot"]
        self.assertIn("--beamwidth-db-colors", plot_args)
        self.assertEqual(
            plot_args[plot_args.index("--beamwidth-db-colors") + 1],
            "#aa0000,#777777,#111111",
        )
        self.assertEqual(plot_args[plot_args.index("--cartesian-figure-width") + 1], "9.25")
        self.assertEqual(plot_args[plot_args.index("--cartesian-figure-height") + 1], "3.75")
        self.assertEqual(plot_args[plot_args.index("--polar-figure-size") + 1], "6.5")
        self.assertEqual(plot_args[plot_args.index("--polar-line-colors") + 1], "#121212,#232323,#343434,#454545")
        self.assertEqual(plot_args[plot_args.index("--polar-line-styles") + 1], "dashed,solid,solid,dashed")
        self.assertIn("--polar-port-labels-json", plot_args)
        port_labels = json.loads(plot_args[plot_args.index("--polar-port-labels-json") + 1])
        self.assertEqual(port_labels["plot_sample"], "+45")
        snapshot = self.window._stage_settings_snapshot("plot")
        self.assertEqual(snapshot["polar_figure_size"], 6.5)
        self.assertEqual(snapshot["polar_azimuth_line_1_color"], "#121212")
        self.assertEqual(snapshot["polar_elevation_line_2_style"], "dashed")
        self.assertEqual(self.window._current_stage_snapshot("plot")["ffs_items"][0]["port_label"], "+45")

    def test_running_progress_updates_summary_and_stage_rows(self) -> None:
        with mock.patch.object(self.window.proc, "enqueue"):
            self.window._enqueue_stage("beam", ["python", "beamwidth_xlsx.py"])
            self.window._enqueue_stage("extract", ["python", "extract_data_xlsx.py"])

        self.window.on_proc_step_started(["beamwidth_xlsx.py"], "python beamwidth_xlsx.py")
        self.window.on_proc_progress(
            {"stage": "beam", "current": 2, "total": 5, "label": "Processing sample.ffs"}
        )
        self.app.processEvents()
        self.window.flush_derived_paths_refresh()

        self.assertEqual(self.window.stage_status_labels["beam"].text(), "Running (2/5 | Processing sample.ffs)")
        self.assertEqual(self.window.stage_timestamp_labels["beam"].text(), "Generated: in progress")
        self.assertEqual(self.window.stage_chip_labels["beam"].text(), "Running")
        self.assertEqual(self.window.busy.maximum(), 100)
        self.assertEqual(self.window.busy.value(), 20)
        self.assertFalse(self.window.btn_cancel.isHidden())
        self.assertFalse(self.window.readiness_action.isVisible())

    def test_delete_all_outputs_action_only_clears_generated_artifacts(self) -> None:
        beam_output = self.window.deduced_beam_output()
        extract_output = self.window.deduced_extract_output()
        datasheet_output = self.window.deduced_datasheet_output()
        vswr_output = self.window.deduced_vswr_output()
        project_dir = self.window.project_results_dir()
        project_file = self.window.current_project().project_file(Path(self.temp_dir.name))
        ant_output = project_dir / "ant_files" / f"{beam_output.stem}-5_8GHz.ant"
        polar_combined_output = project_dir / "polar_combined" / f"{beam_output.stem}-polar-5_8ghz-combined.svg"
        polar_combined_legend = project_dir / "polar_combined" / f"{beam_output.stem}-polar-5_8ghz-combined-legend.svg"
        polar_az_output = project_dir / "polar_single" / "azimuth" / f"{beam_output.stem}-polar-azimuth-5_8ghz.svg"
        polar_el_output = project_dir / "polar_single" / "elevation" / f"{beam_output.stem}-polar-elevation-5_8ghz.svg"
        polar_e_plane_output = project_dir / "polar_single" / "e-plane" / f"{beam_output.stem}-polar-e-plane-5_8ghz.svg"
        polar_h_plane_output = project_dir / "polar_single" / "h-plane" / f"{beam_output.stem}-polar-h-plane-5_8ghz.svg"
        beamwidth_e_plane_output = project_dir / f"{beam_output.stem}-beamwidth-e-plane-h.svg"
        beamwidth_e_plane_legend = project_dir / f"{beam_output.stem}-beamwidth-e-plane-h-legend.svg"
        artifact_manifest = project_dir / f"{beam_output.stem}-artifacts.json"
        project_dir.mkdir(parents=True, exist_ok=True)
        for path in (
            beam_output,
            extract_output,
            datasheet_output,
            vswr_output,
            vswr_output.with_name(f"{vswr_output.stem}-legend{vswr_output.suffix}"),
            project_dir / f"{beam_output.stem}-gain.svg",
            project_dir / f"{beam_output.stem}-gain-legend.svg",
            project_dir / f"{beam_output.stem}-beamwidth.svg",
            project_dir / f"{beam_output.stem}-beamwidth-legend.svg",
            beamwidth_e_plane_output,
            beamwidth_e_plane_legend,
            project_dir / f"{beam_output.stem}-beam-efficiency.svg",
            project_dir / f"{beam_output.stem}-beam-efficiency-legend.svg",
            ant_output,
            polar_combined_output,
            polar_combined_legend,
            polar_az_output,
            polar_el_output,
            polar_e_plane_output,
            polar_h_plane_output,
            artifact_manifest,
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("generated", encoding="utf-8")
        untouched = project_dir / "notes.txt"
        untouched.write_text("keep", encoding="utf-8")

        self.window.refresh_derived_paths()
        self.app.processEvents()
        self.assertTrue(self.window.project_delete_outputs_action.isEnabled())
        self.assertTrue(self.window.btn_clear_outputs.isEnabled())

        with mock.patch("antenna_toolkit_studio.QMessageBox.question", return_value=QMessageBox.Yes):
            self.window.delete_all_outputs()
        self.app.processEvents()

        self.assertFalse(beam_output.exists())
        self.assertFalse(extract_output.exists())
        self.assertFalse(datasheet_output.exists())
        self.assertFalse(vswr_output.exists())
        self.assertFalse(ant_output.exists())
        self.assertFalse(polar_combined_output.exists())
        self.assertFalse(polar_combined_legend.exists())
        self.assertFalse(polar_az_output.exists())
        self.assertFalse(polar_el_output.exists())
        self.assertFalse(polar_e_plane_output.exists())
        self.assertFalse(polar_h_plane_output.exists())
        self.assertFalse(beamwidth_e_plane_output.exists())
        self.assertFalse(beamwidth_e_plane_legend.exists())
        self.assertFalse(artifact_manifest.exists())
        self.assertFalse((project_dir / "ant_files").exists())
        self.assertFalse((project_dir / "polar_combined").exists())
        self.assertFalse((project_dir / "polar_single").exists())
        self.assertTrue(project_file.exists())
        self.assertTrue(untouched.exists())
        self.assertEqual(self.window._stage_state("beam").get("status"), "waiting")
        self.assertFalse(self.window.project_delete_outputs_action.isEnabled())
        self.assertFalse(self.window.btn_clear_outputs.isEnabled())

    def test_cancel_run_clears_live_progress(self) -> None:
        with mock.patch.object(self.window.proc, "enqueue"):
            self.window._enqueue_stage("beam", ["python", "beamwidth_xlsx.py"])

        self.window.proc.running_cmd = ["python", "beamwidth_xlsx.py"]
        self.window.on_proc_step_started(["beamwidth_xlsx.py"], "python beamwidth_xlsx.py")
        self.window.on_proc_progress(
            {"stage": "beam", "current": 1, "total": 2, "label": "Processing sample.ffs"}
        )

        with mock.patch.object(self.window.proc, "stop"):
            self.window.cancel_run()
        self.app.processEvents()

        self.assertEqual(self.window._live_run_total_stages, 0)
        self.assertEqual(self.window._live_run_completed_stages, 0)
        self.assertEqual(self.window._stage_state("beam").get("status"), "cancelled")
        self.assertNotIn("running", self.window.stage_status_labels["beam"].text().lower())
        self.assertTrue(self.window.btn_cancel.isHidden())
