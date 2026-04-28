from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ARTIFACT_MANIFEST_SCHEMA_VERSION = 1
ARTIFACT_MANIFEST_SUFFIX = "-artifacts.json"


def artifact_manifest_path(out_dir: str | Path, bookstem: str) -> Path:
    directory = Path(out_dir).resolve()
    return directory / f"{bookstem}{ARTIFACT_MANIFEST_SUFFIX}"


def _empty_manifest(bookstem: str) -> dict[str, Any]:
    return {
        "schema_version": ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "bookstem": str(bookstem),
        "charts": {
            "gain": None,
            "beamwidth": None,
            "beam_efficiency": None,
            "vswr": None,
            "beamwidth_planes": [],
            "polar_combined": [],
            "polar_combined_planes": [],
            "polar_single": [],
            "polar_planes": [],
        },
    }


def load_artifact_manifest(path: str | Path, *, bookstem: str | None = None) -> dict[str, Any]:
    manifest_path = Path(path)
    if not manifest_path.exists():
        return _empty_manifest(bookstem or manifest_path.stem.replace(ARTIFACT_MANIFEST_SUFFIX, ""))
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_manifest(bookstem or manifest_path.stem.replace(ARTIFACT_MANIFEST_SUFFIX, ""))
    if not isinstance(payload, dict):
        return _empty_manifest(bookstem or manifest_path.stem.replace(ARTIFACT_MANIFEST_SUFFIX, ""))
    charts = payload.get("charts")
    if not isinstance(charts, dict):
        payload["charts"] = _empty_manifest(str(payload.get("bookstem") or bookstem or "")).get("charts", {})
    else:
        payload["charts"] = {
            "gain": charts.get("gain"),
            "beamwidth": charts.get("beamwidth"),
            "beam_efficiency": charts.get("beam_efficiency"),
            "vswr": charts.get("vswr"),
            "beamwidth_planes": list(charts.get("beamwidth_planes") or []),
            "polar_combined": list(charts.get("polar_combined") or []),
            "polar_combined_planes": list(charts.get("polar_combined_planes") or []),
            "polar_single": list(charts.get("polar_single") or []),
            "polar_planes": list(charts.get("polar_planes") or []),
        }
    payload["schema_version"] = int(payload.get("schema_version") or ARTIFACT_MANIFEST_SCHEMA_VERSION)
    payload["bookstem"] = str(payload.get("bookstem") or bookstem or "")
    return payload


def save_artifact_manifest(path: str | Path, manifest: dict[str, Any]) -> Path:
    manifest_path = Path(path).resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": int(manifest.get("schema_version") or ARTIFACT_MANIFEST_SCHEMA_VERSION),
        "bookstem": str(manifest.get("bookstem") or ""),
        "charts": manifest.get("charts") or {},
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return manifest_path


def build_asset_record(
    svg_path: str | Path | None,
    *,
    legend_path: str | Path | None = None,
    **metadata: Any,
) -> dict[str, Any] | None:
    if not svg_path:
        return None
    record: dict[str, Any] = {"svg": str(Path(svg_path).resolve())}
    if legend_path:
        record["legend_svg"] = str(Path(legend_path).resolve())
    for key, value in metadata.items():
        if value is not None:
            record[key] = value
    return record


def update_artifact_manifest(
    out_dir: str | Path,
    bookstem: str,
    *,
    gain: dict[str, Any] | None = None,
    beamwidth: dict[str, Any] | None = None,
    beam_efficiency: dict[str, Any] | None = None,
    vswr: dict[str, Any] | None = None,
    beamwidth_planes: list[dict[str, Any]] | None = None,
    polar_combined: list[dict[str, Any]] | None = None,
    polar_combined_planes: list[dict[str, Any]] | None = None,
    polar_single: list[dict[str, Any]] | None = None,
    polar_planes: list[dict[str, Any]] | None = None,
) -> Path:
    manifest_path = artifact_manifest_path(out_dir, bookstem)
    manifest = load_artifact_manifest(manifest_path, bookstem=bookstem)
    charts = manifest.setdefault("charts", {})
    if gain is not None:
        charts["gain"] = gain
    if beamwidth is not None:
        charts["beamwidth"] = beamwidth
    if beam_efficiency is not None:
        charts["beam_efficiency"] = beam_efficiency
    if vswr is not None:
        charts["vswr"] = vswr
    if beamwidth_planes is not None:
        charts["beamwidth_planes"] = beamwidth_planes
    if polar_combined is not None:
        charts["polar_combined"] = polar_combined
    if polar_combined_planes is not None:
        charts["polar_combined_planes"] = polar_combined_planes
    if polar_single is not None:
        charts["polar_single"] = polar_single
    if polar_planes is not None:
        charts["polar_planes"] = polar_planes
    manifest["bookstem"] = str(bookstem)
    manifest["schema_version"] = ARTIFACT_MANIFEST_SCHEMA_VERSION
    return save_artifact_manifest(manifest_path, manifest)

