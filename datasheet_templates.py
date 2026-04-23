from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass(frozen=True)
class DatasheetTemplateAdapter:
    key: str
    display_name: str
    filename_tokens: tuple[str, ...]
    required_text_markers: tuple[str, ...] = ()
    chart_layout_mode: str = "generic"
    technical_layout_mode: str = "generic"

    def matches(self, template_path: Path, doc: fitz.Document) -> bool:
        path_text = template_path.name.lower()
        if any(token in path_text for token in self.filename_tokens):
            return True
        page_zero_text = ""
        page_one_text = ""
        if doc.page_count > 0:
            page_zero_text = doc[0].get_text("text").upper()
        if doc.page_count > 1:
            page_one_text = doc[1].get_text("text").upper()
        combined = f"{page_zero_text}\n{page_one_text}"
        return all(marker in combined for marker in self.required_text_markers)


GENERIC_TEMPLATE_ADAPTER = DatasheetTemplateAdapter(
    key="generic",
    display_name="Generic Datasheet",
    filename_tokens=(),
)

NETQUI_TEMPLATE_ADAPTER = DatasheetTemplateAdapter(
    key="netqui",
    display_name="Netqui Datasheet",
    filename_tokens=("netqui",),
    required_text_markers=("ANTENNA GAIN", "ANTENNA BEAMWIDTH", "RADIATION PATTERNS"),
    chart_layout_mode="netqui",
    technical_layout_mode="netqui",
)

RFE_TEMPLATE_ADAPTER = DatasheetTemplateAdapter(
    key="rfe",
    display_name="RFE Datasheet",
    filename_tokens=("rfe", "rf elements"),
)

KNOWN_TEMPLATE_ADAPTERS = (
    NETQUI_TEMPLATE_ADAPTER,
    RFE_TEMPLATE_ADAPTER,
)


def resolve_template_adapter(template_path: str | Path, doc: fitz.Document) -> DatasheetTemplateAdapter:
    path = Path(template_path)
    for adapter in KNOWN_TEMPLATE_ADAPTERS:
        if adapter.matches(path, doc):
            return adapter
    return GENERIC_TEMPLATE_ADAPTER
