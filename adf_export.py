"""NSMA WG16.99.050 envelopes from the sampled CST far fields."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


RELATIVE_DB_FLOOR = -300.0


@dataclass(frozen=True)
class ADFSample:
    source: str
    frequency_hz: float
    polarization: str
    angles_deg: np.ndarray
    co_relative_db: np.ndarray
    cross_relative_db: np.ndarray
    gain_dbi: float
    azimuth_width_deg: float
    elevation_width_deg: float


def sample_from_rows(path: Path, frequency_hz: float, rows, port_label: str = "") -> ADFSample:
    # Import lazily: the compliance engine also uses the beam workbook parser.
    from compliance.engine import pattern_from_rows, plane_beamwidth

    pattern = pattern_from_rows(path, frequency_hz, rows, port_label)
    theta = pattern.thetas_deg
    if theta[0] < 0.0 or theta[-1] > 180.0:
        raise ValueError(f"{path.name}: ADF export requires CST theta angles within 0..180 degrees")

    def phi_index(target: float) -> int:
        delta = np.abs((pattern.phis_deg - target + 180.0) % 360.0 - 180.0)
        return int(np.argmin(delta))

    nonzero = theta > 0.0
    angles = np.concatenate((-theta[nonzero][::-1], theta))
    reference = float(np.max(pattern.co_directivity_dbi))

    def half_plane(values: np.ndarray, target: float) -> np.ndarray:
        index = phi_index(target)
        if np.isclose(pattern.phis_deg[index], target):
            return values[index]
        # Interpolate between surrounding phi planes rather than copying one side.
        phis = np.concatenate(([pattern.phis_deg[-1] - 360.0], pattern.phis_deg,
                               [pattern.phis_deg[0] + 360.0]))
        extended = np.vstack((values[-1], values, values[0]))
        right = int(np.searchsorted(phis, target))
        weight = (target - phis[right - 1]) / (phis[right] - phis[right - 1])
        return extended[right - 1] * (1.0 - weight) + extended[right] * weight

    def signed_cut(values: np.ndarray) -> np.ndarray:
        cut = np.concatenate((half_plane(values, 180.0)[nonzero][::-1], half_plane(values, 0.0)))
        return np.maximum(cut - reference, RELATIVE_DB_FLOOR)

    # Derive beamwidth headers only when both requested half-planes exist.
    def has_planes(targets: tuple[float, float]) -> bool:
        return all(np.isclose(pattern.phis_deg[phi_index(target)], target) for target in targets)
    return ADFSample(
        source=str(path.resolve()),
        frequency_hz=frequency_hz,
        polarization=pattern.polarization,
        angles_deg=angles,
        co_relative_db=signed_cut(pattern.co_directivity_dbi),
        cross_relative_db=signed_cut(pattern.cross_directivity_dbi),
        gain_dbi=pattern.max_directivity_dbi,
        azimuth_width_deg=plane_beamwidth(pattern, 0.0) if has_planes((0.0, 180.0)) else float("nan"),
        elevation_width_deg=plane_beamwidth(pattern, 90.0) if has_planes((90.0, 270.0)) else float("nan"),
    )


def _rounded_cut(sample: ADFSample) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    # NSMA stores millidegrees. Retain the highest level if rounding merges samples.
    rounded = np.round(sample.angles_deg, 3)
    angles, starts = np.unique(rounded, return_index=True)
    co = np.maximum.reduceat(sample.co_relative_db, starts)
    cross = np.maximum.reduceat(sample.cross_relative_db, starts)
    return angles, co, cross


def _envelope(samples: list[ADFSample]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cuts = [_rounded_cut(sample) for sample in samples]
    low = max(angles[0] for angles, _co, _cross in cuts)
    high = min(angles[-1] for angles, _co, _cross in cuts)
    if low >= high:
        raise ValueError("ADF cuts have no common angular range")
    angles = np.unique(np.concatenate([cut[0] for cut in cuts]))
    angles = angles[(angles >= low) & (angles <= high)]
    co = np.maximum.reduce([np.interp(angles, x, y) for x, y, _cross in cuts])
    cross = np.maximum.reduce([np.interp(angles, x, y) for x, _co, y in cuts])
    return angles, co, cross


def _header_text(value: str, limit: int) -> str:
    # Commas delimit fields; ! starts an NSMA comment. Keep metadata on one record.
    text = " ".join(str(value).replace(",", " ").replace("!", " ").split())
    return text.encode("ascii", errors="replace").decode("ascii")[:limit]


def build_adf_document(
    samples: list[ADFSample], *, model: str, manufacturer: str = "", data_date: str = ""
) -> str:
    if not samples:
        raise ValueError("ADF export requires at least one far-field sample")
    frequencies = sorted({sample.frequency_hz for sample in samples})
    low, high = frequencies[0], frequencies[-1]
    middle = (low + high) / 2.0
    sources = sorted({sample.source for sample in samples})

    def representatives(frequency: float) -> list[ADFSample]:
        return [
            min(
                (sample for sample in samples if sample.source == source),
                key=lambda sample: (abs(sample.frequency_hz - frequency), sample.frequency_hz),
            )
            for source in sources
        ]

    def gain(frequency: float) -> str:
        # One nominal gain header represents all ports; use the lowest port gain.
        return f"{min(sample.gain_dbi for sample in representatives(frequency)):.2f}"

    mid_samples = representatives(middle)

    def width(attribute: str) -> str:
        values = [getattr(sample, attribute) for sample in mid_samples]
        finite = [value for value in values if np.isfinite(value)]
        return f"{max(finite):.2f}" if finite else ""

    envelopes = []
    for polarization in ("H", "V"):
        selected = [sample for sample in samples if sample.polarization == polarization]
        if selected:
            angles, co, cross = _envelope(selected)
            other = "V" if polarization == "H" else "H"
            envelopes.extend(((f"{polarization}/{polarization}", angles, co),
                              (f"{polarization}/{other}", angles, cross)))
    if not envelopes:
        raise ValueError("ADF export requires H or V polarization")

    fields = [
        ("REVNUM", "NSMA WG16.99.050"), ("REVDAT", "19990520"),
        ("COMNT1", "Simulation envelope; directivity used as gain."),
        ("COMNT2", "Sampled frequencies; co/cross share each sample's co-polar peak."),
        ("ANTMAN", _header_text(manufacturer or "UNKNOWN", 34)),
        ("MODNUM", _header_text(model, 34)), ("FILNUM", ""), ("PATNUM", ""),
        ("FEDORN", ""), *[(f"DESCR{i}", "") for i in range(1, 6)],
        ("DTDATA", data_date or datetime.now(timezone.utc).strftime("%Y%m%d")),
        ("LOWFRQ", f"{low / 1e6:.6f}"), ("HGHFRQ", f"{high / 1e6:.6f}"),
        ("GUNITS", "DBI/DBR"), ("LWGAIN", gain(low)),
        ("MDGAIN", gain(middle)), ("HGGAIN", gain(high)),
        ("AZWIDT", width("azimuth_width_deg")), ("ELWIDT", width("elevation_width_deg")),
        *[(key, "") for key in ("CONTYP", "ATVSWR", "FRTOBA", "ELTILT", "RADCTR",
                                 "POTOPO", "MAXPOW", "ANTLEN", "ANTWID", "ANTDEP", "ANTWGT")],
        *[(f"FIELD{i}", "") for i in range(1, 5)], ("FIELD5", "UNKNOWN"),
        ("PATTYP", "ENVELOPE"), ("NOFREQ", "-1.00"), ("PATFRE", ""),
        ("NUMCUT", str(len(envelopes))),
    ]
    lines = [f"{key}:,\t{value}" for key, value in fields]
    for polarization, angles, levels in envelopes:
        lines.extend(("PATCUT:,\tAZ", f"POLARI:,\t{polarization}",
                      f"NUPOIN:,\t{len(angles)}",
                      f"FSTLST:,\t{angles[0]:.3f},{angles[-1]:.3f}"))
        lines.extend(f"{angle:.3f}, {level:.3f}," for angle, level in zip(angles, levels))
    lines.append("ENDFIL:,EOF")
    return "\r\n".join(lines) + "\r\n"


def write_adf_file(path: Path, document: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(document.encode("ascii"))
