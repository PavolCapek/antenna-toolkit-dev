from __future__ import annotations

import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import fitz
import numpy as np
import pandas as pd

import plot
from plot import beamwidth_plane_phi


class BeamwidthPlanePlotTests(unittest.TestCase):
    def _legend_stroke_widths(self, path: Path) -> set[str]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return {
            value.strip()
            for value in re.findall(r"stroke-width:\s*([^;\"]+)", text)
            if value.strip()
        }

    def _first_handle_height(self, path: Path) -> int:
        with fitz.open(path) as doc:
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)
        ys: list[int] = []
        handle_limit = min(pix.width, 80)
        for y in range(pix.height):
            for x in range(handle_limit):
                offset = (y * pix.width + x) * pix.n
                red, green, blue = pix.samples[offset : offset + 3]
                if min(red, green, blue) < 245:
                    ys.append(y)
                    break
        if not ys:
            return 0
        clusters: list[tuple[int, int]] = []
        start = previous = sorted(set(ys))[0]
        for y in sorted(set(ys))[1:]:
            if y <= previous + 4:
                previous = y
                continue
            clusters.append((start, previous))
            start = previous = y
        clusters.append((start, previous))
        first_start, first_end = clusters[0]
        return first_end - first_start + 1

    def test_beamwidth_plane_phi_maps_by_polarization(self) -> None:
        self.assertEqual(beamwidth_plane_phi("H", "E"), 0)
        self.assertEqual(beamwidth_plane_phi("H", "H"), 90)
        self.assertEqual(beamwidth_plane_phi("V", "E"), 90)
        self.assertEqual(beamwidth_plane_phi("V", "H"), 0)

    def test_dual_polarization_workbook_emits_e_and_h_plane_plots(self) -> None:
        freqs = [5.0, 5.5]

        def summary_rows(phi0_values: tuple[int, int, int], phi90_values: tuple[int, int, int]) -> pd.DataFrame:
            rows = []
            for phi, values in [(0, phi0_values), (90, phi90_values)]:
                for index, freq in enumerate(freqs):
                    rows.append(
                        {
                            "freq_GHz": freq,
                            "phi_cut_deg": phi,
                            "beamwidth_3dB_2sided_deg": float(values[0] + index),
                            "beamwidth_6dB_2sided_deg": float(values[1] + index),
                            "beamwidth_10dB_2sided_deg": float(values[2] + index),
                        }
                    )
            return pd.DataFrame(rows)

        h_df = summary_rows((10, 20, 30), (40, 50, 60))
        v_df = summary_rows((70, 80, 90), (100, 110, 120))

        class FakeExcel:
            sheet_names = ["Example_H", "Example_V"]

            def parse(self, sheet_name: str) -> pd.DataFrame:
                if sheet_name == "Example_H":
                    return h_df.copy()
                if sheet_name == "Example_V":
                    return v_df.copy()
                raise AssertionError(f"Unexpected sheet: {sheet_name}")

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.xlsx"
            out_dir = Path(temp_dir) / "plots"
            argv = [
                "plot.py",
                str(input_path),
                "--out-dir",
                str(out_dir),
                "--beamwidth-db-colors",
                "#aa0000,#777777,#111111",
            ]
            calls = []

            def fake_plot_xy(*args, **kwargs):
                calls.append((args, kwargs))
                out_path = Path(args[3])
                return str(out_path), str(out_path.with_name(f"{out_path.stem}-legend{out_path.suffix}"))

            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(plot.pd, "ExcelFile", return_value=FakeExcel()),
                mock.patch.object(plot, "plot_xy", side_effect=fake_plot_xy),
                redirect_stdout(io.StringIO()),
            ):
                plot.main()

        by_name = {Path(args[3]).name: (args, kwargs) for args, kwargs in calls}
        for expected in [
            "input-beamwidth-e-plane-h.svg",
            "input-beamwidth-h-plane-h.svg",
            "input-beamwidth-e-plane-v.svg",
            "input-beamwidth-h-plane-v.svg",
        ]:
            self.assertIn(expected, by_name)

        h_e_series = by_name["input-beamwidth-e-plane-h.svg"][0][1]
        h_h_series = by_name["input-beamwidth-h-plane-h.svg"][0][1]
        v_e_series = by_name["input-beamwidth-e-plane-v.svg"][0][1]
        v_h_series = by_name["input-beamwidth-h-plane-v.svg"][0][1]

        np.testing.assert_allclose(h_e_series[0], [10.0, 11.0])
        np.testing.assert_allclose(h_h_series[0], [40.0, 41.0])
        np.testing.assert_allclose(v_e_series[0], [100.0, 101.0])
        np.testing.assert_allclose(v_h_series[0], [70.0, 71.0])

        self.assertEqual(by_name["input-beamwidth-e-plane-h.svg"][0][2], ["3dB E-plane", "6dB E-plane", "10dB E-plane"])
        self.assertEqual(by_name["input-beamwidth-h-plane-v.svg"][0][2], ["3dB H-plane", "6dB H-plane", "10dB H-plane"])
        self.assertEqual(by_name["input-beamwidth-e-plane-h.svg"][1]["colors"], ["#aa0000", "#777777", "#111111"])

    def test_single_polarization_workbook_emits_unsuffixed_e_and_h_plane_plots(self) -> None:
        summary_df = pd.DataFrame(
            [
                {
                    "freq_GHz": 4.4,
                    "phi_cut_deg": phi,
                    "beamwidth_3dB_2sided_deg": 10.0 + phi,
                    "beamwidth_6dB_2sided_deg": 20.0 + phi,
                    "beamwidth_10dB_2sided_deg": 30.0 + phi,
                }
                for phi in (0, 90)
            ]
        )

        class FakeExcel:
            sheet_names = ["TWB-DQ-47-26"]

            def parse(self, _sheet_name: str) -> pd.DataFrame:
                return summary_df.copy()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.xlsx"
            out_dir = Path(temp_dir) / "plots"
            argv = ["plot.py", str(input_path), "--out-dir", str(out_dir)]
            calls = []

            def fake_plot_xy(*args, **kwargs):
                calls.append((args, kwargs))
                out_path = Path(args[3])
                return str(out_path), str(out_path.with_name(f"{out_path.stem}-legend{out_path.suffix}"))

            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(plot.pd, "ExcelFile", return_value=FakeExcel()),
                mock.patch.object(plot, "plot_xy", side_effect=fake_plot_xy),
                redirect_stdout(io.StringIO()),
            ):
                plot.main()

        by_name = {Path(args[3]).name: args for args, _kwargs in calls}
        self.assertIn("input-beamwidth-e-plane.svg", by_name)
        self.assertIn("input-beamwidth-h-plane.svg", by_name)
        np.testing.assert_allclose(by_name["input-beamwidth-e-plane.svg"][1][0], [100.0])
        np.testing.assert_allclose(by_name["input-beamwidth-h-plane.svg"][1][0], [10.0])

    def test_cartesian_and_polar_legend_handles_use_same_stroke_width(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            cartesian_path = temp_path / "cartesian.svg"
            polar_path = temp_path / "polar.svg"

            plot.plot_xy(
                np.array([1.0, 2.0, 3.0]),
                [np.array([1.0, 2.0, 3.0]), np.array([1.5, 2.5, 3.5])],
                ["Cartesian A", "Cartesian B"],
                cartesian_path,
                "Value",
                line_width=6.0,
            )
            plot.save_polar(
                polar_path,
                [
                    {
                        "angles": np.array([0.0, 90.0, 180.0, 270.0, 360.0]),
                        "series": np.array([0.0, -3.0, -12.0, -3.0, 0.0]),
                        "label": "Polar A",
                        "linestyle": "-",
                    },
                    {
                        "angles": np.array([0.0, 90.0, 180.0, 270.0, 360.0]),
                        "series": np.array([-1.0, -4.0, -14.0, -4.0, -1.0]),
                        "label": "Polar B",
                        "linestyle": "--",
                    },
                ],
                "Polar",
                line_width=9.0,
                legend_ncol=1,
            )

            cartesian_legend = plot.legend_output_path(cartesian_path)
            polar_legend = plot.legend_output_path(polar_path)

            self.assertEqual(self._legend_stroke_widths(cartesian_legend), {"3"})
            self.assertEqual(self._legend_stroke_widths(polar_legend), {"3"})
            self.assertLessEqual(
                abs(self._first_handle_height(cartesian_legend) - self._first_handle_height(polar_legend)),
                2,
            )

    def test_save_polar_respects_explicit_dataset_colors_and_styles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / "polar.svg"

            plot.save_polar(
                out_path,
                [
                    {
                        "angles": np.array([0.0, 90.0, 180.0, 270.0, 360.0]),
                        "series": np.array([0.0, -3.0, -12.0, -3.0, 0.0]),
                        "label": "Custom solid",
                        "color": "#123456",
                        "linestyle": "-",
                    },
                    {
                        "angles": np.array([0.0, 90.0, 180.0, 270.0, 360.0]),
                        "series": np.array([-1.0, -4.0, -14.0, -4.0, -1.0]),
                        "label": "Custom dashed",
                        "color": "#abcdef",
                        "linestyle": "--",
                    },
                ],
                "Polar",
                legend_ncol=1,
            )

            svg_text = out_path.read_text(encoding="utf-8", errors="ignore").lower()
            legend_text = plot.legend_output_path(out_path).read_text(encoding="utf-8", errors="ignore").lower()
            combined = svg_text + legend_text

            self.assertIn("#123456", combined)
            self.assertIn("#abcdef", combined)
            self.assertIn("stroke-dasharray", combined)

    def test_polar_cli_styles_and_emits_e_h_plane_assets(self) -> None:
        angles = pd.DataFrame(
            {
                "theta_deg": [0.0, 90.0, 180.0, 270.0, 360.0],
                "5.0 GHz": [0.0, -3.0, -10.0, -3.0, 0.0],
                "6.0 GHz": [0.0, -2.0, -9.0, -2.0, 0.0],
            }
        )
        h_phi0 = angles.copy()
        h_phi0["5.0 GHz"] = [1.0, 2.0, 3.0, 2.0, 1.0]
        h_phi0["6.0 GHz"] = [1.5, 2.5, 3.5, 2.5, 1.5]
        h_phi90 = angles.copy()
        h_phi90["5.0 GHz"] = [4.0, 5.0, 6.0, 5.0, 4.0]
        h_phi90["6.0 GHz"] = [4.5, 5.5, 6.5, 5.5, 4.5]
        v_phi0 = angles.copy()
        v_phi0["5.0 GHz"] = [7.0, 8.0, 9.0, 8.0, 7.0]
        v_phi0["6.0 GHz"] = [7.5, 8.5, 9.5, 8.5, 7.5]
        v_phi90 = angles.copy()
        v_phi90["5.0 GHz"] = [10.0, 11.0, 12.0, 11.0, 10.0]
        v_phi90["6.0 GHz"] = [10.5, 11.5, 12.5, 11.5, 10.5]

        class FakeExcel:
            sheet_names = ["Example_H_phi0", "Example_H_phi90", "Example_V_phi0", "Example_V_phi90"]

            def parse(self, sheet_name: str) -> pd.DataFrame:
                return {
                    "Example_H_phi0": h_phi0,
                    "Example_H_phi90": h_phi90,
                    "Example_V_phi0": v_phi0,
                    "Example_V_phi90": v_phi90,
                }[sheet_name].copy()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.xlsx"
            out_dir = Path(temp_dir) / "plots"
            argv = [
                "plot.py",
                str(input_path),
                "--out-dir",
                str(out_dir),
                "--polar-line-colors",
                "#010101,#020202,#030303,#040404",
                "--polar-line-styles",
                "solid,dashed,dashed,solid",
                "--polar-port-labels-json",
                json.dumps({"Example_H": "Port 1", "Example_V": "Port 2"}),
            ]
            calls = []

            def fake_save_polar(out_path, datasets, *args, **kwargs):
                calls.append((Path(out_path), datasets, kwargs))
                path = Path(out_path)
                legend = Path(kwargs.get("legend_out_path") or path.with_name(f"{path.stem}-legend{path.suffix}"))
                return str(path), str(legend)

            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(plot.pd, "ExcelFile", return_value=FakeExcel()),
                mock.patch.object(plot, "save_polar", side_effect=fake_save_polar),
                redirect_stdout(io.StringIO()),
            ):
                plot.main()

            by_name = {path.name: datasets for path, datasets, _kwargs in calls}
            by_name_kwargs = {path.name: kwargs for path, _datasets, kwargs in calls}
            self.assertIn("input-polar-e-plane-5.0-GHz.svg", by_name)
            self.assertIn("input-polar-h-plane-5.0-GHz.svg", by_name)
            self.assertIn("input-polar-5.0-GHz-e-h-plane-combined.svg", by_name)
            self.assertIn("input-polar-e-plane-6.0-GHz.svg", by_name)
            self.assertEqual(by_name["input-polar-5.0-GHz-combined.svg"][0]["label"], "Port 1 Azimuth 5.0 GHz")
            self.assertEqual(by_name["input-polar-5.0-GHz-e-h-plane-combined.svg"][0]["label"], "Port 1 E-plane 5.0 GHz")
            self.assertEqual(by_name["input-polar-azimuth-5.0-GHz.svg"][0]["label"], "Port 1 Azimuth 5.0 GHz")
            self.assertEqual(by_name["input-polar-elevation-5.0-GHz.svg"][1]["label"], "Port 2 Elevation 5.0 GHz")
            self.assertEqual(by_name["input-polar-azimuth-5.0-GHz.svg"][0]["color"], "#010101")
            self.assertEqual(by_name["input-polar-azimuth-5.0-GHz.svg"][1]["color"], "#020202")
            self.assertEqual(by_name["input-polar-elevation-5.0-GHz.svg"][0]["linestyle"], "--")
            self.assertEqual(by_name["input-polar-elevation-5.0-GHz.svg"][1]["linestyle"], "-")
            self.assertEqual(
                Path(by_name_kwargs["input-polar-azimuth-5.0-GHz.svg"].get("legend_out_path") or "input-polar-azimuth-5.0-GHz-legend.svg").name,
                "input-polar-azimuth-5.0-GHz-legend.svg",
            )
            self.assertEqual(
                Path(by_name_kwargs["input-polar-azimuth-6.0-GHz.svg"].get("legend_out_path") or "input-polar-azimuth-6.0-GHz-legend.svg").name,
                "input-polar-azimuth-6.0-GHz-legend.svg",
            )
            self.assertNotIn("export_legend", by_name_kwargs["input-polar-azimuth-5.0-GHz.svg"])
            self.assertNotIn("export_legend", by_name_kwargs["input-polar-azimuth-6.0-GHz.svg"])
            self.assertNotIn("export_legend", by_name_kwargs["input-polar-5.0-GHz-combined.svg"])
            self.assertNotIn("legend_out_path", by_name_kwargs["input-polar-5.0-GHz-combined.svg"])
            self.assertNotIn("legend_out_path", by_name_kwargs["input-polar-5.0-GHz-e-h-plane-combined.svg"])
            np.testing.assert_allclose(by_name["input-polar-e-plane-5.0-GHz.svg"][0]["series"], h_phi0["5.0 GHz"].to_numpy())
            np.testing.assert_allclose(by_name["input-polar-e-plane-5.0-GHz.svg"][1]["series"], v_phi90["5.0 GHz"].to_numpy())
            np.testing.assert_allclose(by_name["input-polar-h-plane-5.0-GHz.svg"][0]["series"], h_phi90["5.0 GHz"].to_numpy())
            np.testing.assert_allclose(by_name["input-polar-h-plane-5.0-GHz.svg"][1]["series"], v_phi0["5.0 GHz"].to_numpy())

            manifest = json.loads((out_dir / "input-artifacts.json").read_text(encoding="utf-8"))
            polar_planes = manifest["charts"]["polar_planes"]
            self.assertEqual({record["plane"] for record in polar_planes}, {"e-plane", "h-plane"})
            self.assertEqual(len(polar_planes), 4)
            polar_combined_planes = manifest["charts"]["polar_combined_planes"]
            self.assertEqual(len(polar_combined_planes), 2)
            self.assertEqual({record["plane_mode"] for record in polar_combined_planes}, {"e-h-plane"})


if __name__ == "__main__":
    unittest.main()
