from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import fitz

from datasheet.layouts.netqui_1pol import NETQUI_SLOT_ORDER_ROWS
from datasheet.layouts.rfe import RFE_SLOT_ORDER_FIRST_TWO_THEN_X
from datasheet.specs import DatasheetSpec, load_default_datasheet_specs


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
        if not self.required_text_markers:
            return False
        combined = "\n".join(doc[index].get_text("text").upper() for index in range(doc.page_count))
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

NETQUI_1POL_PLACEHOLDER_TEMPLATE_MANIFEST = TemplateManifest(
    key="netqui_1pol_placeholder",
    chart_layout=NETQUI_1POL_TEMPLATE_MANIFEST.chart_layout,
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

NETQUI_1POL_PLACEHOLDER_TEMPLATE_ADAPTER = DatasheetTemplateAdapter(
    key="netqui_1pol_placeholder",
    display_name="Netqui 1Pol Placeholder Datasheet",
    filename_tokens=("netqui - 1pol - placeholder",),
    required_text_markers=("PACKAGING", "MANUFACTURER INFORMATION"),
    chart_layout_mode="netqui_1pol_placeholder",
    technical_layout_mode="netqui_1pol",
    manifest=NETQUI_1POL_PLACEHOLDER_TEMPLATE_MANIFEST,
)

RFE_TEMPLATE_ADAPTER = DatasheetTemplateAdapter(
    key="rfe",
    display_name="RFE Datasheet",
    filename_tokens=("rfe", "rf elements"),
    manifest=RFE_TEMPLATE_MANIFEST,
)

KNOWN_TEMPLATE_ADAPTERS = (
    NETQUI_1POL_PLACEHOLDER_TEMPLATE_ADAPTER,
    NETQUI_1POL_TEMPLATE_ADAPTER,
    NETQUI_TEMPLATE_ADAPTER,
    RFE_TEMPLATE_ADAPTER,
)
KNOWN_TEMPLATE_KEYS = {adapter.key for adapter in KNOWN_TEMPLATE_ADAPTERS} | {"generic"}


def adapter_from_datasheet_spec(spec: DatasheetSpec) -> DatasheetTemplateAdapter:
    chart_layout = None
    if spec.chart_layout is not None:
        chart_layout = TemplateChartManifest(
            page_index=spec.chart_layout.page_index,
            min_image_slots=spec.chart_layout.min_image_slots,
            slots=tuple(
                TemplateChartSlot(
                    slot.kind,
                    slot.slot_index,
                    slot.asset_key,
                    required=slot.required,
                    plane=slot.plane,
                    frequency_role=slot.frequency_role,
                    legend_mode=slot.legend_mode,
                )
                for slot in spec.chart_layout.slots
            ),
            normalize_width_kinds=spec.chart_layout.normalize_width_kinds,
            slot_order=spec.chart_layout.slot_order,
        )
    table_layout = TemplateTableManifest(
        aliases=tuple(
            TemplateTableAlias(alias.canonical_key, alias.labels)
            for alias in spec.table.aliases
        ),
        electrical_sections=spec.table.electrical_sections,
        mechanical_sections=spec.table.mechanical_sections,
    )
    return DatasheetTemplateAdapter(
        key=spec.key,
        display_name=spec.display_name,
        filename_tokens=spec.match.filename_tokens,
        required_text_markers=spec.match.required_text_markers,
        chart_layout_mode=spec.chart_layout_mode,
        technical_layout_mode=spec.technical_layout_mode,
        manifest=TemplateManifest(
            key=spec.key,
            chart_layout=chart_layout,
            table_layout=table_layout,
            technical_layout_mode=spec.technical_layout_mode,
        ),
    )


def _candidate_auto_specs(specs: Mapping[str, DatasheetSpec] | None) -> list[DatasheetSpec]:
    resolved_specs = specs if specs is not None else load_default_datasheet_specs()
    candidates = [
        spec for spec in resolved_specs.values()
        if spec.key not in KNOWN_TEMPLATE_KEYS and (spec.match.filename_tokens or spec.match.required_text_markers)
    ]
    return sorted(
        candidates,
        key=lambda spec: (
            max((len(token) for token in spec.match.filename_tokens), default=0),
            len(spec.match.required_text_markers),
            spec.key,
        ),
        reverse=True,
    )


def _resolve_auto_spec_adapter(
    template_path: Path,
    doc: fitz.Document,
    specs: Mapping[str, DatasheetSpec] | None,
) -> DatasheetTemplateAdapter | None:
    for spec in _candidate_auto_specs(specs):
        adapter = adapter_from_datasheet_spec(spec)
        if adapter.matches(template_path, doc):
            return adapter
    return None


def resolve_template_adapter(
    template_path: str | Path,
    doc: fitz.Document,
    *,
    specs: Mapping[str, DatasheetSpec] | None = None,
) -> DatasheetTemplateAdapter:
    path = Path(template_path)
    for adapter in KNOWN_TEMPLATE_ADAPTERS:
        if adapter.matches(path, doc):
            return adapter
    auto_spec_adapter = _resolve_auto_spec_adapter(path, doc, specs)
    if auto_spec_adapter is not None:
        return auto_spec_adapter
    return GENERIC_TEMPLATE_ADAPTER
