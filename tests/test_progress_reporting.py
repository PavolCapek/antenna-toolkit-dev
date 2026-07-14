from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import studio_support as qt_module
import beamwidth_xlsx
import datasheet_pdf
import extract_data_xlsx
import plot
import plot_vswr


def progress_lines(output: str) -> list[dict[str, object]]:
    lines = []
    for line in output.splitlines():
        if line.startswith("AT_PROGRESS "):
            lines.append(json.loads(line[len("AT_PROGRESS "):]))
    return lines


class DummyProgressWindow:
    def __init__(self) -> None:
        self.structured: list[dict[str, object]] = []
        self.progress_values: list[int | None] = []

    def on_proc_progress(self, payload: dict[str, object]) -> None:
        self.structured.append(payload)

    def set_progress(self, value: int | None) -> None:
        self.progress_values.append(value)


class DummyPercentWindow:
    def __init__(self) -> None:
        self.progress_values: list[int | None] = []

    def set_progress(self, value: int | None) -> None:
        self.progress_values.append(value)


class ProgressReportingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_proc_parses_structured_progress(self) -> None:
        window = DummyProgressWindow()
        proc = qt_module.Proc(window)  # type: ignore[arg-type]

        proc._maybe_progress_from_text(
            'AT_PROGRESS {"stage":"beam","current":2,"total":5,"label":"Processing sample.ffs"}\n'
        )

        self.assertEqual(
            window.structured,
            [{"stage": "beam", "current": 2, "total": 5, "label": "Processing sample.ffs"}],
        )

    def test_proc_ignores_malformed_structured_progress(self) -> None:
        window = DummyProgressWindow()
        proc = qt_module.Proc(window)  # type: ignore[arg-type]

        proc._maybe_progress_from_text('AT_PROGRESS {"stage":"beam","current":"bad"}\n')

        self.assertEqual(window.structured, [])
        self.assertEqual(window.progress_values, [])

    def test_proc_keeps_percent_fallback(self) -> None:
        window = DummyPercentWindow()
        proc = qt_module.Proc(window)  # type: ignore[arg-type]

        proc._maybe_progress_from_text("42%\n")

        self.assertEqual(window.progress_values[-1], 42)

    def test_beamwidth_stage_emits_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "result.xlsx"
            ffs_path = root / "sample.ffs"
            ffs_path.write_text("ffs", encoding="utf-8")
            argv = ["beamwidth_xlsx.py", str(output), str(ffs_path)]
            buffer = io.StringIO()
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(beamwidth_xlsx, "read_ffs_broadband", return_value={}),
                mock.patch.object(beamwidth_xlsx, "compute_for_file", return_value=([], None, None, None, [])),
                mock.patch("beamwidth_xlsx.StageWorkspace.publish"),
                redirect_stdout(buffer),
            ):
                exit_code = beamwidth_xlsx.main()

        self.assertEqual(exit_code, 0)
        payloads = progress_lines(buffer.getvalue())
        self.assertGreaterEqual(len(payloads), 2)
        self.assertEqual(payloads[0]["stage"], "beam")

    def test_extract_stage_emits_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "extract.xlsx"
            ffs_path = root / "sample.ffs"
            ffs_path.write_text("ffs", encoding="utf-8")
            argv = ["extract_data_xlsx.py", str(output), str(ffs_path)]
            buffer = io.StringIO()
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(extract_data_xlsx, "compute_ffs_rows", return_value=[{"freq_GHz": 5.5}]),
                mock.patch.object(extract_data_xlsx, "filter_rows_by_range", return_value=([{"freq_GHz": 5.5}], 5.5, 5.5)),
                mock.patch.object(extract_data_xlsx, "summarize_ffs_rows", return_value={"source_file": "sample.ffs"}),
                mock.patch.object(extract_data_xlsx, "build_workbook"),
                mock.patch("extract_data_xlsx.StageWorkspace.publish"),
                redirect_stdout(buffer),
            ):
                exit_code = extract_data_xlsx.main()

        self.assertEqual(exit_code, 0)
        payloads = progress_lines(buffer.getvalue())
        self.assertGreaterEqual(len(payloads), 2)
        self.assertEqual(payloads[0]["stage"], "extract")

    def test_datasheet_stage_emits_progress(self) -> None:
        replacements = {label: f"value-{idx}" for idx, label in enumerate(datasheet_pdf.FIELD_LABELS)}

        class FakePage:
            def add_redact_annot(self, *_args, **_kwargs) -> None:
                return None

            def apply_redactions(self, **_kwargs) -> None:
                return None

            def insert_font(self, **_kwargs) -> None:
                return None

            def insert_text(self, *_args, **_kwargs) -> int:
                return 1

            def get_fonts(self, full=False) -> list:
                return []

        class FakeDoc:
            def __init__(self) -> None:
                self.metadata = {}
                self.page = FakePage()

            def __enter__(self) -> "FakeDoc":
                return self

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

            def __getitem__(self, _index: int) -> FakePage:
                return self.page

            def __iter__(self):
                yield self.page

            def set_metadata(self, _metadata) -> None:
                return None

            def set_xml_metadata(self, _metadata) -> None:
                return None

            def save(self, output, **_kwargs) -> None:
                Path(output).write_bytes(b"pdf")

        slot = mock.Mock(erase_rect=(0, 0, 1, 1), font_name="helv", origin=(0, 0), color=(0, 0, 0))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "datasheet.pdf"
            template = root / "template.pdf"
            workbook = root / "extract.xlsx"
            buffer = io.StringIO()
            model = SimpleNamespace(
                performance_fields=replacements,
                technical_entries=[],
                artifact_manifest={},
            )
            context = SimpleNamespace(model=model, adapter=None)
            slots = {label: slot for label in datasheet_pdf.FIELD_LABELS}
            with (
                mock.patch.object(datasheet_pdf, "build_render_context", return_value=context),
                mock.patch.object(datasheet_pdf.fitz, "open", return_value=FakeDoc()),
                mock.patch.object(datasheet_pdf, "_build_pdf_metadata", return_value={}),
                mock.patch.object(datasheet_pdf, "_extract_page_spans", return_value=[]),
                mock.patch.object(datasheet_pdf, "_find_replacement_slots", return_value=slots),
                mock.patch.object(datasheet_pdf, "_fit_font_size", return_value=7.0),
                mock.patch.object(datasheet_pdf, "_font_path_for_display_font", return_value=None),
                mock.patch.object(datasheet_pdf, "_resolve_font_name", return_value="helv"),
                mock.patch.object(datasheet_pdf, "_replace_chart_images"),
                mock.patch.object(datasheet_pdf, "_redraw_split_table_separators"),
                mock.patch.object(datasheet_pdf, "_build_xmp_metadata", return_value=""),
                redirect_stdout(buffer),
            ):
                result = datasheet_pdf.build_datasheet_pdf(output, template, workbook)
                self.assertTrue(output.exists())

        self.assertEqual(result, replacements)
        payloads = progress_lines(buffer.getvalue())
        self.assertEqual([payload["current"] for payload in payloads], [1, 2, 3])

    def test_plot_stage_emits_progress(self) -> None:
        summary_df = pd.DataFrame(
            {
                "freq_GHz": [5.0, 5.5, 6.0],
                "phi_cut_deg": [0, 0, 0],
                "max_gain_dBi": [10.0, 11.0, 12.0],
                "eta_beam_percent": [90.0, 91.0, 92.0],
                "beamwidth_6dB_2sided_deg": [30.0, 31.0, 32.0],
            }
        )

        class FakeExcel:
            sheet_names = ["summary"]

            def parse(self, _sheet_name: str) -> pd.DataFrame:
                return summary_df.copy()

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_input = Path(temp_dir) / "input.xlsx"
            argv = ["plot.py", str(fake_input)]
            buffer = io.StringIO()

            def fake_plot_xy(*args, **_kwargs):
                output = Path(args[3])
                legend = output.with_name(f"{output.stem}-legend{output.suffix}")
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("<svg/>", encoding="utf-8")
                legend.write_text("<svg/>", encoding="utf-8")
                return str(output), str(legend)

            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(plot.pd, "ExcelFile", return_value=FakeExcel()),
                mock.patch.object(plot, "plot_xy", side_effect=fake_plot_xy),
                redirect_stdout(buffer),
            ):
                plot.main()

        payloads = progress_lines(buffer.getvalue())
        self.assertGreaterEqual(len(payloads), 3)
        self.assertTrue(all(payload["stage"] == "plot" for payload in payloads))

    def test_vswr_stage_emits_progress(self) -> None:
        freqs_hz = np.array([5.0e9, 5.5e9, 6.0e9], dtype=float)
        touchstone_rows = np.array([[0.1, 0.0], [0.2, 0.0], [0.15, 0.0]], dtype=float)

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "sample.s1p"
            argv = ["plot_vswr.py", str(input_path)]
            buffer = io.StringIO()
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(plot_vswr, "read_touchstone", return_value=(freqs_hz, touchstone_rows, "ri", 50.0, 1)),
                mock.patch.object(plot_vswr, "plot_xy", return_value=(Path(temp_dir) / "vswr.svg", Path(temp_dir) / "vswr-legend.svg")),
                mock.patch("plot_vswr.StageWorkspace.publish"),
                redirect_stdout(buffer),
            ):
                plot_vswr.main()

        payloads = progress_lines(buffer.getvalue())
        self.assertEqual([payload["current"] for payload in payloads], [1, 2])
        self.assertTrue(all(payload["stage"] == "vswr" for payload in payloads))


if __name__ == "__main__":
    unittest.main()
