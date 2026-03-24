from __future__ import annotations

from collections.abc import Sequence
import re


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


def polar_legend_label(name: str, plane: str, frequency_label: str) -> str:
    polarization = detect_polarization(name)
    prefix = polarization if polarization else str(name)
    return f"{prefix} - Port Pattern {plane} {frequency_label}"
