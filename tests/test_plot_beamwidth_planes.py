from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

import plot
from plot import beamwidth_plane_phi


class BeamwidthPlanePlotTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
