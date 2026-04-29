from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz

from datasheet.layouts.netqui_1pol import NETQUI_SLOT_ORDER_ROWS
from datasheet.layouts.rfe import RFE_SLOT_ORDER_FIRST_TWO_THEN_X


@dataclass(frozen=True)
class TemplateChartSlot:
    kind: str
    slot_index: int
    asset_key: str
    required: bool = True
    plane: str | None = None
    frequency_role: str | None = None
    legend_mode: str = "auto"


@dataclass(frozen=True)
class TemplateChartManifest:
    page_index: int | None
    min_image_slots: int
    slots: tuple[TemplateChartSlot, ...]
    normalize_width_kinds: tuple[str, ...] = ()
    slot_order: str = "spatial"


@dataclass(frozen=True)
class TemplateTableAlias:
    canonical_key: str
    labels: tuple[str, ...]


@dataclass(frozen=True)
class TemplateTableManifest:
    aliases: tuple[TemplateTableAlias, ...] = ()
    electrical_sections: tuple[str, ...] = ("performance", "electrical data")
    mechanical_sections: tuple[str, ...] = ("technical data", "mechanical data")


@dataclass(frozen=True)
class TemplateManifest:
    key: str
    chart_layout: TemplateChartManifest | None = None
    table_layout: TemplateTableManifest = TemplateTableManifest()
    technical_layout_mode: str = "generic"


@dataclass(frozen=True)
class DatasheetTemplateAdapter:
    key: str
    display_name: str
    filename_tokens: tuple[str, ...]
    required_text_markers: tuple[str, ...] = ()
    chart_layout_mode: str = "generic"
    technical_layout_mode: str = "generic"
    manifest: TemplateManifest | None = None

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
        if not self.required_text_markers:
            return False
        return all(marker in combined for marker in self.required_text_markers)


GENERIC_TEMPLATE_MANIFEST = TemplateManifest(
    key="generic",
    chart_layout=TemplateChartManifest(
        page_index=None,
        min_image_slots=2,
        slots=(
            TemplateChartSlot("gain", 0, "gain"),
            TemplateChartSlot("beamwidth", 1, "beamwidth"),
            TemplateChartSlot("azimuth", 2, "polar_azimuth", required=False),
            TemplateChartSlot("elevation", 3, "polar_elevation", required=False),
        ),
        normalize_width_kinds=("gain", "beamwidth"),
    ),
)

NETQUI_TEMPLATE_MANIFEST = TemplateManifest(
    key="netqui",
    chart_layout=TemplateChartManifest(
        page_index=None,
        min_image_slots=4,
        slots=(
            TemplateChartSlot("gain", 0, "gain", legend_mode="netqui_top_side"),
            TemplateChartSlot("vswr", 1, "vswr", required=False, legend_mode="netqui_top_side"),
            TemplateChartSlot("beamwidth_e_plane", 2, "beamwidth_plane", plane="e-plane", legend_mode="netqui_side"),
            TemplateChartSlot("beamwidth_h_plane", 3, "beamwidth_plane", plane="h-plane", legend_mode="netqui_side"),
        ),
        slot_order=NETQUI_SLOT_ORDER_ROWS,
    ),
    table_layout=TemplateTableManifest(
        aliases=(
            TemplateTableAlias("frequency range", ("Frequency Range", "Frequency")),
            TemplateTableAlias("gain", ("Gain", "Antenna Gain", "Nominal Gain")),
            TemplateTableAlias("azimuth beam width -3 db/-6db", ("Beamwidth H plane.", "Beamwidth H plane", "H Plane Beamwidth", "Horizontal Beamwidth")),
            TemplateTableAlias("elevation beam width -3 db/-6db", ("Beamwidth E plane.", "Beamwidth E plane", "E Plane Beamwidth", "Vertical Beamwidth")),
            TemplateTableAlias("vswr", ("VSWR",)),
            TemplateTableAlias("polarization", ("Polarization",)),
            TemplateTableAlias("impedance", ("Nominal Impedance", "Impedance")),
            TemplateTableAlias("radio connection", ("RF Connection", "Radio Connection")),
            TemplateTableAlias("materials", ("Material", "Materials")),
            TemplateTableAlias("dimensions", ("Dimensions (LxWxD)", "Dimensions (H x W x D)", "Dimensions")),
        ),
    ),
    technical_layout_mode="netqui",
)

NETQUI_1POL_TEMPLATE_MANIFEST = TemplateManifest(
    key="netqui_1pol",
    chart_layout=TemplateChartManifest(
        page_index=1,
        min_image_slots=7,
        slots=(
            TemplateChartSlot("gain", 0, "gain", legend_mode="netqui_top_side"),
            TemplateChartSlot("vswr", 1, "vswr", required=False, legend_mode="netqui_top_side"),
            TemplateChartSlot("beamwidth_e_plane", 2, "beamwidth_plane", plane="e-plane", legend_mode="netqui_side"),
            TemplateChartSlot("beamwidth_h_plane", 3, "beamwidth_plane", plane="h-plane", legend_mode="netqui_side"),
            TemplateChartSlot("radiation_low", 4, "polar_combined_planes_triplet", frequency_role="low", legend_mode="netqui_bottom"),
            TemplateChartSlot("radiation_mid", 5, "polar_combined_planes_triplet", frequency_role="mid", legend_mode="netqui_bottom"),
            TemplateChartSlot("radiation_high", 6, "polar_combined_planes_triplet", frequency_role="high", legend_mode="netqui_bottom"),
        ),
        slot_order=NETQUI_SLOT_ORDER_ROWS,
    ),
    table_layout=NETQUI_TEMPLATE_MANIFEST.table_layout,
    technical_layout_mode="netqui_1pol",
)

RFE_TEMPLATE_MANIFEST = TemplateManifest(
    key="rfe",
    chart_layout=TemplateChartManifest(
        page_index=None,
        min_image_slots=2,
        slots=(
            TemplateChartSlot("gain", 0, "gain"),
            TemplateChartSlot("beamwidth", 1, "beamwidth"),
            TemplateChartSlot("azimuth", 2, "polar_azimuth", required=False),
            TemplateChartSlot("elevation", 3, "polar_elevation", required=False),
        ),
        normalize_width_kinds=("gain", "beamwidth"),
        slot_order=RFE_SLOT_ORDER_FIRST_TWO_THEN_X,
    ),
)

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
    manifest=NETQUI_TEMPLATE_MANIFEST,
)

NETQUI_1POL_TEMPLATE_ADAPTER = DatasheetTemplateAdapter(
    key="netqui_1pol",
    display_name="Netqui 1Pol Datasheet",
    filename_tokens=("netqui - 1pol", "netqui-1pol", "netqui_1pol"),
    chart_layout_mode="netqui_1pol",
    technical_layout_mode="netqui_1pol",
    manifest=NETQUI_1POL_TEMPLATE_MANIFEST,
)

RFE_TEMPLATE_ADAPTER = DatasheetTemplateAdapter(
    key="rfe",
    display_name="RFE Datasheet",
    filename_tokens=("rfe", "rf elements"),
    manifest=RFE_TEMPLATE_MANIFEST,
)

KNOWN_TEMPLATE_ADAPTERS = (
    NETQUI_1POL_TEMPLATE_ADAPTER,
    NETQUI_TEMPLATE_ADAPTER,
    RFE_TEMPLATE_ADAPTER,
)


def resolve_template_adapter(template_path: str | Path, doc: fitz.Document) -> DatasheetTemplateAdapter:
    path = Path(template_path)
    for adapter in KNOWN_TEMPLATE_ADAPTERS:
        if adapter.matches(path, doc):
            return adapter
    return GENERIC_TEMPLATE_ADAPTER
