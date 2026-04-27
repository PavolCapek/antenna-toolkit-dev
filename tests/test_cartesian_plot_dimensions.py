from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz
import matplotlib
import numpy as np

matplotlib.use("Agg")

from plot import plot_xy as plot_workbook_xy
from plot_vswr import plot_xy as plot_vswr_xy


class CartesianPlotDimensionTests(unittest.TestCase):
    def _export_ratio(self, svg_path: Path) -> float:
        with fitz.open(svg_path) as doc:
            page = doc[0]
            return page.rect.height / page.rect.width

    def test_workbook_cartesian_plot_exports_with_taller_aspect_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "gain.svg"
            plot_workbook_xy(
                np.array([4.9, 5.5, 6.1, 7.2]),
                [np.array([15.8, 16.2, 16.9, 17.8])],
                ["Gain H (IEEE)"],
                str(out_path),
                y_label="Gain / dBi",
                smooth_window=1,
            )

            self.assertGreater(self._export_ratio(out_path), 0.39)

    def test_vswr_cartesian_plot_matches_taller_aspect_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "vswr.svg"
            plot_vswr_xy(
                np.array([4.9, 5.5, 6.1, 7.2]),
                [np.array([1.2, 1.3, 1.5, 1.7])],
                ["VSWR Port 1"],
                str(out_path),
                y_label="VSWR",
                smooth_window=1,
            )

            self.assertGreater(self._export_ratio(out_path), 0.39)

    def test_workbook_cartesian_plot_uses_custom_figure_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "gain-custom.svg"
            plot_workbook_xy(
                np.array([4.9, 5.5, 6.1, 7.2]),
                [np.array([15.8, 16.2, 16.9, 17.8])],
                ["Gain H (IEEE)"],
                str(out_path),
                y_label="Gain / dBi",
                smooth_window=1,
                figure_width=6.0,
                figure_height=6.0,
            )

            self.assertGreater(self._export_ratio(out_path), 0.80)

    def test_vswr_cartesian_plot_uses_custom_figure_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "vswr-custom.svg"
            plot_vswr_xy(
                np.array([4.9, 5.5, 6.1, 7.2]),
                [np.array([1.2, 1.3, 1.5, 1.7])],
                ["VSWR Port 1"],
                str(out_path),
                y_label="VSWR",
                smooth_window=1,
                figure_width=6.0,
                figure_height=6.0,
            )

            self.assertGreater(self._export_ratio(out_path), 0.80)


if __name__ == "__main__":
    unittest.main()
