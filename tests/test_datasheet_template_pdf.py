from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from datasheet_template_pdf import build_datasheet_template_pdf


class DatasheetTemplatePdfTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_pdf = self.root / "source.pdf"
        self.output_pdf = self.root / "output.pdf"
        self._write_source_pdf()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_source_pdf(self) -> None:
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((36, 48), "Product Datasheet", fontsize=12, fontname="helv")
            page.insert_text((36, 90), "Original Antenna Title", fontsize=22, fontname="helv")
            page.insert_text((36, 120), "Original descriptive paragraph text.", fontsize=8, fontname="helv")
            page.insert_text((140, 220), "Original Label", fontsize=8, fontname="helv", rotate=90)
            doc.save(self.source_pdf)

    def test_build_datasheet_template_pdf_replaces_all_text(self) -> None:
        build_datasheet_template_pdf(template=self.source_pdf, output=self.output_pdf)

        with fitz.open(self.output_pdf) as doc:
            text = "\n".join(page.get_text() for page in doc)

        self.assertIn("Antenna name", text)
        self.assertNotIn("Original Antenna Title", text)
        self.assertNotIn("Original descriptive paragraph text.", text)
        self.assertNotIn("Original Label", text)
        self.assertIn("lorem", text.lower())


if __name__ == "__main__":
    unittest.main()
