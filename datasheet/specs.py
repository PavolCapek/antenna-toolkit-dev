from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SPEC_FILE_SUFFIXES = {".json", ".yaml", ".yml"}


@dataclass(frozen=True)
class TemplateMatchSpec:
    filename_tokens: tuple[str, ...] = ()
    required_text_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChartSlotSpec:
    kind: str
    slot_index: int
    asset_key: str
    required: bool = True
    plane: str | None = None
    frequency_role: str | None = None
    legend_mode: str = "auto"


@dataclass(frozen=True)
class TableAliasSpec:
    canonical_key: str
    labels: tuple[str, ...]


@dataclass(frozen=True)
class TableSpec:
    aliases: tuple[TableAliasSpec, ...] = ()
    electrical_sections: tuple[str, ...] = ("performance", "electrical data")
    mechanical_sections: tuple[str, ...] = ("technical data", "mechanical data")


@dataclass(frozen=True)
class ChartLayoutSpec:
    page_index: int | None = None
    min_image_slots: int = 0
    slots: tuple[ChartSlotSpec, ...] = ()
    normalize_width_kinds: tuple[str, ...] = ()
    slot_order: str = "spatial"


@dataclass(frozen=True)
class DatasheetSpec:
    key: str
    display_name: str
    layout_key: str
    match: TemplateMatchSpec = TemplateMatchSpec()
    chart_layout: ChartLayoutSpec | None = None
    table: TableSpec = TableSpec()
    technical_layout_mode: str = "generic"
    chart_layout_mode: str = "generic"
    default_image_selection: str = "template_default"
    source_path: Path | None = None


class DatasheetSpecError(ValueError):
    """Raised when an external datasheet spec is invalid."""


def _string_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise DatasheetSpecError(f"{field_name} must be a list of strings.")
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return tuple(result)


def _load_raw_spec(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
    elif suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise DatasheetSpecError("YAML datasheet specs require PyYAML to be installed.") from exc
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    else:
        raise DatasheetSpecError(f"Unsupported datasheet spec file type: {path.suffix}")
    if not isinstance(payload, dict):
        raise DatasheetSpecError("Datasheet spec root must be an object.")
    return payload


def _parse_chart_slot(payload: object, index: int) -> ChartSlotSpec:
    if not isinstance(payload, dict):
        raise DatasheetSpecError(f"chart_layout.slots[{index}] must be an object.")
    kind = str(payload.get("kind") or "").strip()
    asset_key = str(payload.get("asset_key") or "").strip()
    if not kind:
        raise DatasheetSpecError(f"chart_layout.slots[{index}].kind is required.")
    if not asset_key:
        raise DatasheetSpecError(f"chart_layout.slots[{index}].asset_key is required.")
    try:
        slot_index = int(payload.get("slot_index"))
    except (TypeError, ValueError) as exc:
        raise DatasheetSpecError(f"chart_layout.slots[{index}].slot_index must be an integer.") from exc
    return ChartSlotSpec(
        kind=kind,
        slot_index=slot_index,
        asset_key=asset_key,
        required=bool(payload.get("required", True)),
        plane=str(payload["plane"]).strip() if payload.get("plane") is not None else None,
        frequency_role=str(payload["frequency_role"]).strip() if payload.get("frequency_role") is not None else None,
        legend_mode=str(payload.get("legend_mode") or "auto").strip() or "auto",
    )


def _parse_chart_layout(payload: object) -> ChartLayoutSpec | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise DatasheetSpecError("chart_layout must be an object.")
    raw_slots = payload.get("slots") or []
    if not isinstance(raw_slots, list):
        raise DatasheetSpecError("chart_layout.slots must be a list.")
    page_index_raw = payload.get("page_index")
    page_index = int(page_index_raw) if page_index_raw is not None else None
    return ChartLayoutSpec(
        page_index=page_index,
        min_image_slots=int(payload.get("min_image_slots") or 0),
        slots=tuple(_parse_chart_slot(slot, index) for index, slot in enumerate(raw_slots)),
        normalize_width_kinds=_string_tuple(payload.get("normalize_width_kinds"), field_name="chart_layout.normalize_width_kinds"),
        slot_order=str(payload.get("slot_order") or "spatial").strip() or "spatial",
    )


def _parse_table(payload: object) -> TableSpec:
    if payload is None:
        return TableSpec()
    if not isinstance(payload, dict):
        raise DatasheetSpecError("table must be an object.")
    raw_aliases = payload.get("aliases") or []
    if not isinstance(raw_aliases, list):
        raise DatasheetSpecError("table.aliases must be a list.")
    aliases: list[TableAliasSpec] = []
    for index, raw_alias in enumerate(raw_aliases):
        if not isinstance(raw_alias, dict):
            raise DatasheetSpecError(f"table.aliases[{index}] must be an object.")
        canonical_key = str(raw_alias.get("canonical_key") or "").strip()
        if not canonical_key:
            raise DatasheetSpecError(f"table.aliases[{index}].canonical_key is required.")
        aliases.append(
            TableAliasSpec(
                canonical_key=canonical_key,
                labels=_string_tuple(raw_alias.get("labels"), field_name=f"table.aliases[{index}].labels"),
            )
        )
    return TableSpec(
        aliases=tuple(aliases),
        electrical_sections=_string_tuple(payload.get("electrical_sections"), field_name="table.electrical_sections") or TableSpec().electrical_sections,
        mechanical_sections=_string_tuple(payload.get("mechanical_sections"), field_name="table.mechanical_sections") or TableSpec().mechanical_sections,
    )


def load_datasheet_spec(path: str | Path) -> DatasheetSpec:
    spec_path = Path(path)
    payload = _load_raw_spec(spec_path)
    key = str(payload.get("key") or "").strip()
    display_name = str(payload.get("display_name") or "").strip()
    layout_key = str(payload.get("layout_key") or key).strip()
    if not key:
        raise DatasheetSpecError("Datasheet spec key is required.")
    if not display_name:
        raise DatasheetSpecError("Datasheet spec display_name is required.")
    match_payload = payload.get("match") or {}
    if not isinstance(match_payload, dict):
        raise DatasheetSpecError("match must be an object.")
    return DatasheetSpec(
        key=key,
        display_name=display_name,
        layout_key=layout_key or key,
        match=TemplateMatchSpec(
            filename_tokens=_string_tuple(match_payload.get("filename_tokens"), field_name="match.filename_tokens"),
            required_text_markers=_string_tuple(match_payload.get("required_text_markers"), field_name="match.required_text_markers"),
        ),
        chart_layout=_parse_chart_layout(payload.get("chart_layout")),
        table=_parse_table(payload.get("table")),
        technical_layout_mode=str(payload.get("technical_layout_mode") or "generic").strip() or "generic",
        chart_layout_mode=str(payload.get("chart_layout_mode") or "generic").strip() or "generic",
        default_image_selection=str(payload.get("default_image_selection") or "template_default").strip() or "template_default",
        source_path=spec_path.resolve(),
    )


def load_datasheet_specs(directory: str | Path) -> dict[str, DatasheetSpec]:
    spec_dir = Path(directory)
    specs: dict[str, DatasheetSpec] = {}
    if not spec_dir.exists():
        return specs
    for path in sorted((item for item in spec_dir.iterdir() if item.is_file() and item.suffix.lower() in SPEC_FILE_SUFFIXES), key=lambda item: item.name.lower()):
        spec = load_datasheet_spec(path)
        if spec.key in specs:
            raise DatasheetSpecError(f"Duplicate datasheet spec key: {spec.key}")
        specs[spec.key] = spec
    return specs


def default_spec_directory() -> Path:
    return Path(__file__).resolve().parent / "spec_definitions"


def load_default_datasheet_specs() -> dict[str, DatasheetSpec]:
    return load_datasheet_specs(default_spec_directory())
