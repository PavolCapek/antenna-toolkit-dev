from __future__ import annotations

from collections.abc import Sequence
import re
from pathlib import Path


def parse_legend_labels(raw: str | None) -> list[str]:
    if raw is None:
        return []
    return [item.strip() for item in raw.split(",")]


def apply_legend_labels(defaults: Sequence[str], overrides: Sequence[str]) -> list[str]:
    resolved: list[str] = []
    for index, default in enumerate(defaults):
        if index < len(overrides) and overrides[index]:
            resolved.append(overrides[index])
        else:
            resolved.append(default)
    return resolved


def detect_polarization(name: str) -> str | None:
    tokens = [token for token in re.split(r"[^a-z0-9]+", str(name).strip().lower()) if token]
    if "horizontal" in tokens or "h" in tokens:
        return "H"
    if "vertical" in tokens or "v" in tokens:
        return "V"
    return None


def polarization_sort_key(name: str) -> tuple[int, str]:
    polarization = detect_polarization(name)
    rank = {"H": 0, "V": 1}.get(polarization, 2)
    return rank, str(name).lower()


def gain_legend_label(name: str) -> str:
    polarization = detect_polarization(name)
    return f"Gain {polarization} (IEEE)" if polarization else f"Gain {name} (IEEE)"


def beamwidth_legend_label(name: str, plane: str) -> str:
    polarization = detect_polarization(name)
    suffix = polarization if polarization else str(name)
    return f"Beamwidth {plane} {suffix} -6 dB"


def beam_efficiency_legend_label(name: str) -> str:
    polarization = detect_polarization(name)
    return f"Beam Efficiency {polarization}" if polarization else f"Beam Efficiency {name}"


def clean_port_source_label(name: str) -> str:
    stem = Path(str(name)).stem or str(name)
    tokens = [token for token in re.split(r"[_\-\s]+", stem) if token]
    removable = {"phi0", "phi90", "azimuth", "elevation"}
    while tokens and tokens[-1].lower() in removable:
        tokens.pop()
    return " ".join(tokens) if tokens else stem


def polar_legend_label(
    name: str,
    plane: str,
    frequency_label: str = "",
    *,
    port_label: str | None = None,
    single_source: bool = False,
) -> str:
    explicit = str(port_label or "").strip()
    polarization = detect_polarization(name)
    prefix = explicit or (polarization if polarization else "")
    if not prefix and not single_source:
        prefix = clean_port_source_label(name)
    suffix = f" {frequency_label}" if str(frequency_label).strip() else ""
    return f"{prefix} {plane}{suffix}".strip() if prefix else f"{plane}{suffix}".strip()
