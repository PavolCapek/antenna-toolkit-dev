from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable


MANIFEST_CHART_KEYS = (
    "gain",
    "beamwidth",
    "beam_efficiency",
    "vswr",
    "beamwidth_planes",
    "polar_combined",
    "polar_combined_planes",
    "polar_single",
    "polar_planes",
)

LIST_CHART_KEYS = {
    "beamwidth_planes",
    "polar_combined",
    "polar_combined_planes",
    "polar_single",
    "polar_planes",
}

CHART_FAMILY_BY_KEY = {
    "gain": "gain",
    "beamwidth": "beamwidth",
    "beam_efficiency": "beam_efficiency",
    "vswr": "vswr",
    "beamwidth_planes": "beamwidth",
    "polar_combined": "polar",
    "polar_combined_planes": "polar",
    "polar_single": "polar",
    "polar_planes": "polar",
}

BASE_LABEL_BY_KEY = {
    "gain": "Gain",
    "beamwidth": "Beamwidth",
    "beam_efficiency": "Beam Efficiency",
    "vswr": "VSWR",
    "beamwidth_planes": "Beamwidth",
    "polar_combined": "Polar Combined",
    "polar_combined_planes": "Polar Combined Planes",
    "polar_single": "Polar",
    "polar_planes": "Polar Planes",
}


@dataclass(frozen=True)
class AssetCatalogItem:
    asset_id: str
    label: str
    chart_family: str
    manifest_key: str
    plane: str | None
    polarization: str | None
    frequency_ghz: float | None
    svg_path: Path
    legend_path: Path | None
    source_record: dict[str, Any]


@dataclass(frozen=True)
class AssetCatalog:
    items: tuple[AssetCatalogItem, ...]

    def by_id(self) -> dict[str, AssetCatalogItem]:
        return {item.asset_id: item for item in self.items}

    def by_manifest_key(self, manifest_key: str) -> tuple[AssetCatalogItem, ...]:
        return tuple(item for item in self.items if item.manifest_key == manifest_key)


def build_asset_catalog(manifest: dict[str, Any] | None) -> AssetCatalog:
    items = list(_iter_catalog_items(manifest))
    return AssetCatalog(tuple(_with_unique_ids(items)))


def _iter_catalog_items(manifest: dict[str, Any] | None) -> Iterable[AssetCatalogItem]:
    if not isinstance(manifest, dict):
        return
    charts = manifest.get("charts")
    if not isinstance(charts, dict):
        return

    for chart_key in MANIFEST_CHART_KEYS:
        value = charts.get(chart_key)
        records = value if chart_key in LIST_CHART_KEYS else [value]
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            svg_path = _path_from_record(record, "svg")
            if svg_path is None:
                continue
            yield _catalog_item(chart_key, record, svg_path)


def _catalog_item(chart_key: str, record: dict[str, Any], svg_path: Path) -> AssetCatalogItem:
    plane = _clean_text(record.get("plane") or record.get("plane_mode"))
    polarization = _clean_text(record.get("polarization"))
    frequency_ghz = _float_or_none(record.get("frequency_ghz"))
    source_record = dict(record)
    return AssetCatalogItem(
        asset_id=_asset_id(chart_key, plane=plane, polarization=polarization, frequency_ghz=frequency_ghz),
        label=_label_for(chart_key, source_record, plane=plane, polarization=polarization, frequency_ghz=frequency_ghz),
        chart_family=CHART_FAMILY_BY_KEY.get(chart_key, chart_key),
        manifest_key=chart_key,
        plane=plane,
        polarization=polarization,
        frequency_ghz=frequency_ghz,
        svg_path=svg_path,
        legend_path=_path_from_record(record, "legend_svg") or _path_from_record(record, "legend"),
        source_record=source_record,
    )


def _with_unique_ids(items: list[AssetCatalogItem]) -> list[AssetCatalogItem]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.asset_id] = counts.get(item.asset_id, 0) + 1
    if all(count == 1 for count in counts.values()):
        return items

    unique_items: list[AssetCatalogItem] = []
    seen: set[str] = set()
    for item in items:
        if counts[item.asset_id] == 1:
            unique_items.append(item)
            seen.add(item.asset_id)
            continue
        digest = hashlib.sha1(str(item.svg_path).encode("utf-8")).hexdigest()[:8]
        asset_id = f"{item.asset_id}__{digest}"
        while asset_id in seen:
            digest = hashlib.sha1(f"{item.svg_path}:{len(seen)}".encode("utf-8")).hexdigest()[:8]
            asset_id = f"{item.asset_id}__{digest}"
        seen.add(asset_id)
        unique_items.append(replace(item, asset_id=asset_id))
    return unique_items


def _asset_id(
    chart_key: str,
    *,
    plane: str | None,
    polarization: str | None,
    frequency_ghz: float | None,
) -> str:
    parts = [chart_key]
    for value in (plane, polarization):
        if value:
            parts.append(_slug(value))
    frequency = _frequency_token(frequency_ghz)
    if frequency:
        parts.append(frequency)
    return "__".join(parts)


def _label_for(
    chart_key: str,
    record: dict[str, Any],
    *,
    plane: str | None,
    polarization: str | None,
    frequency_ghz: float | None,
) -> str:
    label = _clean_text(record.get("label"))
    if label:
        return label
    parts = [BASE_LABEL_BY_KEY.get(chart_key, chart_key.replace("_", " ").title())]
    if plane:
        parts.append(_display_token(plane))
    if polarization:
        parts.append(str(polarization).strip().upper())
    frequency = _frequency_label(frequency_ghz)
    if frequency:
        parts.append(frequency)
    return " ".join(parts)


def _path_from_record(record: dict[str, Any], key: str) -> Path | None:
    value = str(record.get(key) or "").strip()
    if not value:
        return None
    return Path(value)


def _clean_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _frequency_token(value: float | None) -> str | None:
    if value is None:
        return None
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return f"{text.replace('.', 'p')}ghz"


def _frequency_label(value: float | None) -> str | None:
    if value is None:
        return None
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return f"{text} GHz"


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return normalized or "unknown"


def _display_token(value: str) -> str:
    return " ".join(part.upper() if len(part) == 1 else part.title() for part in re.split(r"[\s_-]+", value) if part)
