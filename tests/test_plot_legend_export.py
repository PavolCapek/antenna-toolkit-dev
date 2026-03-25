from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz
import matplotlib

matplotlib.use("Agg")

from plot import export_stacked_line_legend


class PlotLegendExportTests(unittest.TestCase):
    def _content_bounds(self, svg_path: Path, *, scale: float = 2.0) -> tuple[int, int, int, int, fitz.Pixmap]:
        with fitz.open(svg_path) as doc:
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)

        samples = pix.samples

        def pixel_is_content(x: int, y: int) -> bool:
            offset = (y * pix.width + x) * pix.n
            return (
                samples[offset] < 250
                or samples[offset + 1] < 250
                or samples[offset + 2] < 250
            )

        top = 0
        while top < pix.height and not any(pixel_is_content(x, top) for x in range(pix.width)):
            top += 1

        bottom = pix.height - 1
        while bottom >= 0 and not any(pixel_is_content(x, bottom) for x in range(pix.width)):
            bottom -= 1

        left = 0
        while left < pix.width and not any(pixel_is_content(left, y) for y in range(pix.height)):
            left += 1

        right = pix.width - 1
        while right >= 0 and not any(pixel_is_content(right, y) for y in range(pix.height)):
            right -= 1

        return left, top, right, bottom, pix

    def test_export_stacked_line_legend_keeps_small_safe_outer_margins(self) -> None:
        items = [
            ("Beamwidth Azimuth H -6 dB", "#2bb6f6", "-"),
            ("Beamwidth Azimuth V -6 dB", "#f5a623", "-"),
            ("Beamwidth Elevation H -6 dB", "#2bb6f6", "--"),
            ("Beamwidth Elevation V gypqj -6 dB", "#f5a623", "--"),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "beamwidth.svg"
            legend_path = export_stacked_line_legend(items, out_path, ncol=1)

            self.assertIsNotNone(legend_path)
            assert legend_path is not None
            self.assertTrue(legend_path.exists())

            left, top, right, bottom, pix = self._content_bounds(legend_path)
            margin_left = left
            margin_top = top
            margin_right = pix.width - 1 - right
            margin_bottom = pix.height - 1 - bottom

            self.assertGreaterEqual(margin_bottom, 4)
            self.assertLessEqual(margin_bottom, 30)
            self.assertGreaterEqual(margin_top, 4)
            self.assertLessEqual(margin_top, 30)
            self.assertGreaterEqual(margin_left, 4)
            self.assertLessEqual(margin_left, 20)
            self.assertGreaterEqual(margin_right, 4)
            self.assertLessEqual(margin_right, 20)


if __name__ == "__main__":
    unittest.main()
