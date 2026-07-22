from __future__ import annotations


BEAM_DATA_VERSION = 4
EXTRACT_DATA_VERSION = 1
TOUCHSTONE_PARSER_VERSION = 1
PLOT_ASSET_STYLE_VERSION = 6
VSWR_ASSET_STYLE_VERSION = 1
DATASHEET_RENDER_VERSION = 6
WORKBOOK_MANIFEST_VERSION = 1


def stage_versions(stage_key: str) -> dict[str, int]:
    versions: dict[str, int] = {}
    if stage_key in {"beam", "extract", "plot", "datasheet"}:
        versions["beam_data"] = BEAM_DATA_VERSION
    if stage_key in {"extract", "datasheet"}:
        versions["extract_data"] = EXTRACT_DATA_VERSION
    if stage_key in {"extract", "vswr", "datasheet"}:
        versions["touchstone_parser"] = TOUCHSTONE_PARSER_VERSION
    if stage_key in {"plot", "datasheet"}:
        versions["plot_assets"] = PLOT_ASSET_STYLE_VERSION
    if stage_key in {"vswr", "datasheet"}:
        versions["vswr_assets"] = VSWR_ASSET_STYLE_VERSION
    if stage_key == "datasheet":
        versions["datasheet_render"] = DATASHEET_RENDER_VERSION
    return versions
