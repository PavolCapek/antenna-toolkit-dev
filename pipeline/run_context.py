from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipeline.settings import PresetSettings


@dataclass(frozen=True)
class RunContext:
    project_slug: str
    project_dir: Path
    beam_output: Path
    extract_output: Path
    datasheet_output: Path
    vswr_output: Path
    settings: PresetSettings
    compliance_output: Path | None = None
    polar_port_labels_json: str = ""
    touchstone_path: str = ""
