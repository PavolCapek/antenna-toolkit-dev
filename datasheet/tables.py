from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from datasheet.models import (
    FIELD_LABELS,
    TECHNICAL_DATA_RESERVED_KEYS,
    DatasheetTableRow,
    canonical_field_key,
    normalize_table_section,
    normalize_technical_key,
)
from datasheet.templates import DatasheetTemplateAdapter


GENERATED_PERFORMANCE_KEYS = {canonical_field_key(label) for label in FIELD_LABELS}


@dataclass
class ResolvedDatasheetTables:
    generated_rows: list[DatasheetTableRow] = field(default_factory=list)
    excel_rows: list[DatasheetTableRow] = field(default_factory=list)
    adapter: DatasheetTemplateAdapter | None = None

    @property
    def generated_by_key(self) -> dict[str, DatasheetTableRow]:
        return {row.canonical_key: row for row in self.generated_rows if row.canonical_key}

    @property
    def excel_by_key(self) -> dict[str, DatasheetTableRow]:
        rows: dict[str, DatasheetTableRow] = {}
        for row in self.excel_rows:
            if row.canonical_key:
                rows[row.canonical_key] = row
        return rows


def _template_alias_key_map(adapter: DatasheetTemplateAdapter | None) -> dict[str, str]:
    manifest = adapter.manifest if adapter is not None else None
    table_layout = manifest.table_layout if manifest is not None else None
    if table_layout is None:
        return {}
    aliases: dict[str, str] = {}
    for alias_group in table_layout.aliases:
        canonical_key = normalize_technical_key(alias_group.canonical_key)
        if not canonical_key:
            continue
        aliases[canonical_key] = canonical_key
        for label in alias_group.labels:
            key = normalize_technical_key(label)
            if key:
                aliases[key] = canonical_key
    return aliases


def canonical_key_for_template(label: object, adapter: DatasheetTemplateAdapter | None = None) -> str:
    key = canonical_field_key(label)
    template_aliases = _template_alias_key_map(adapter)
    return template_aliases.get(key, key)


def resolved_table_row(
    *,
    section: str,
    label: str,
    value: str,
    source: str,
    adapter: DatasheetTemplateAdapter | None = None,
) -> DatasheetTableRow:
    return DatasheetTableRow(
        label=label,
        value=value,
        section=normalize_table_section(section),
        canonical_key=canonical_key_for_template(label, adapter),
        source=source,
    )


def resolve_datasheet_tables(
    performance_fields: dict[str, str],
    excel_rows: Iterable[DatasheetTableRow],
    *,
    adapter: DatasheetTemplateAdapter | None = None,
) -> ResolvedDatasheetTables:
    generated = [
        resolved_table_row(section="Performance", label=label, value=value, source="generated", adapter=adapter)
        for label, value in performance_fields.items()
    ]
    resolved_excel = [
        resolved_table_row(
            section=row.section,
            label=row.label,
            value=row.value,
            source=row.source or "excel",
            adapter=adapter,
        )
        for row in excel_rows
    ]
    return ResolvedDatasheetTables(generated_rows=generated, excel_rows=resolved_excel, adapter=adapter)


def row_for_fixed_label(tables: ResolvedDatasheetTables, label: str) -> DatasheetTableRow | None:
    key = canonical_key_for_template(label, tables.adapter)
    generated = tables.generated_by_key.get(key)
    if generated is not None:
        return generated
    return tables.excel_by_key.get(key)


def section_key(section: object) -> str:
    return normalize_technical_key(normalize_table_section(section))


def is_electrical_section(section: object, adapter: DatasheetTemplateAdapter | None = None) -> bool:
    key = section_key(section)
    manifest = adapter.manifest if adapter is not None else None
    table_layout = manifest.table_layout if manifest is not None else None
    allowed = table_layout.electrical_sections if table_layout is not None else ("performance", "electrical data")
    return key in {normalize_technical_key(value) for value in allowed}


def is_mechanical_section(section: object, adapter: DatasheetTemplateAdapter | None = None) -> bool:
    key = section_key(section)
    manifest = adapter.manifest if adapter is not None else None
    table_layout = manifest.table_layout if manifest is not None else None
    allowed = table_layout.mechanical_sections if table_layout is not None else ("technical data", "mechanical data")
    return key in {normalize_technical_key(value) for value in allowed}


def extra_rows_for_sections(
    tables: ResolvedDatasheetTables,
    *,
    used_keys: set[str],
    section_filter,
) -> list[DatasheetTableRow]:
    extras: list[DatasheetTableRow] = []
    for row in tables.excel_rows:
        key = row.canonical_key
        if not key or key in used_keys or key in GENERATED_PERFORMANCE_KEYS or key in TECHNICAL_DATA_RESERVED_KEYS:
            continue
        if not str(row.value or "").strip():
            continue
        if section_filter(row.section, tables.adapter):
            extras.append(row)
            used_keys.add(key)
    return extras
