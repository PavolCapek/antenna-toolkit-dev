from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import fitz

from datasheet.models import DatasheetModel, load_datasheet_model
from datasheet.specs import DatasheetSpec
from datasheet.templates import DatasheetTemplateAdapter, resolve_template_adapter


@dataclass(frozen=True)
class DatasheetRenderContext:
    model: DatasheetModel
    adapter: DatasheetTemplateAdapter


def build_render_context(
    template_path: str | Path,
    doc: fitz.Document,
    extract_workbook: Path,
    technical_data_workbook: Path | None = None,
    *,
    output_dir: Path | None = None,
    technical_data_sheet: str | int | None = None,
    datasheet_specs: Mapping[str, DatasheetSpec] | None = None,
) -> DatasheetRenderContext:
    adapter = resolve_template_adapter(
        template_path,
        doc,
        specs=datasheet_specs,
    )
    model = load_datasheet_model(
        extract_workbook.resolve(),
        technical_data_workbook.resolve() if technical_data_workbook else None,
        output_dir=output_dir,
        technical_data_sheet=technical_data_sheet,
        technical_data_profile="rfe" if adapter.key == "rfe" else None,
    )
    return DatasheetRenderContext(model=model, adapter=adapter)

