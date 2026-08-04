from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from beamwidth_xlsx import (
    FFSParseError,
    circular_cell_sizes,
    linear_cell_sizes,
    read_ffs_broadband,
)
from compliance.standards import (
    FCC_ANGLE_BINS,
    FCCProfile,
    ETSIRPEProfile,
    ETSISectorProfile,
    etsi_profiles_for_frequency,
    etsi_sector_profiles,
    etsi_xpd_requirements,
    fcc_profiles_for_frequency,
)
from legend_utils import detect_polarization


@dataclass(frozen=True)
class Pattern:
    frequency_hz: float
    phis_deg: np.ndarray
    thetas_deg: np.ndarray
    total_directivity_dbi: np.ndarray
    co_directivity_dbi: np.ndarray
    cross_directivity_dbi: np.ndarray
    polarization: str
    polarization_basis: str

    @property
    def max_directivity_dbi(self) -> float:
        return float(np.nanmax(self.total_directivity_dbi))


OmittedAngleRange = tuple[float, float] | None


def parse_omitted_angle_range(value: str) -> OmittedAngleRange:
    """Parse an inclusive 0..180 degree range, or return None for blank text."""
    text = str(value or "").strip()
    if not text:
        return None
    number = r"(?:\d+(?:\.\d*)?|\.\d+)"
    match = re.fullmatch(rf"({number})\s*(?:-|:|,)\s*({number})", text)
    if match is None:
        single = re.fullmatch(rf"({number})", text)
        if single is None:
            raise ValueError("omitted angle range must look like 179-180, or be a single angle such as 180")
        low = high = float(single.group(1))
    else:
        low, high = (float(match.group(1)), float(match.group(2)))
    if not (0.0 <= low <= high <= 180.0):
        raise ValueError("omitted angle range must satisfy 0 <= minimum <= maximum <= 180 degrees")
    return low, high


def _included_angle_mask(angles_deg: np.ndarray, omitted_angle_range: OmittedAngleRange) -> np.ndarray:
    if omitted_angle_range is None:
        return np.ones_like(angles_deg, dtype=bool)
    low, high = omitted_angle_range
    omitted = (angles_deg >= low - 1e-9) & (angles_deg <= high + 1e-9)
    return ~omitted


def _grid_from_rows(rows) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    arr = np.asarray(rows, dtype=object)
    phis = np.mod(np.asarray(arr[:, 0], dtype=float), 360.0)
    thetas = np.asarray(arr[:, 1], dtype=float)
    etheta = np.asarray(arr[:, 2], dtype=complex)
    ephi = np.asarray(arr[:, 3], dtype=complex)

    order = np.lexsort((thetas, phis))
    phis = phis[order]
    thetas = thetas[order]
    etheta = etheta[order]
    ephi = ephi[order]
    pair_keys = np.column_stack((np.round(phis, 8), np.round(thetas, 8)))
    keep = np.ones(len(phis), dtype=bool)
    keep[1:] = np.any(pair_keys[1:] != pair_keys[:-1], axis=1)
    phis = phis[keep]
    thetas = thetas[keep]
    etheta = etheta[keep]
    ephi = ephi[keep]

    unique_phis = np.unique(np.round(phis, 8))
    unique_thetas = np.unique(np.round(thetas, 8))
    if len(unique_phis) * len(unique_thetas) != len(phis):
        raise FFSParseError("Compliance analysis requires a complete phi/theta grid")
    shape = (len(unique_phis), len(unique_thetas))
    return unique_phis, unique_thetas, etheta.reshape(shape), ephi.reshape(shape)


def _resolve_polarization(path: Path, label: str, etheta: np.ndarray, ephi: np.ndarray, phis: np.ndarray, thetas: np.ndarray) -> tuple[str, str]:
    explicit = detect_polarization(label) or detect_polarization(path.stem)
    if explicit:
        return explicit, "port label or filename"

    phi_rad = np.radians(phis)[:, None]
    x_co = etheta * np.cos(phi_rad) - ephi * np.sin(phi_rad)
    y_co = etheta * np.sin(phi_rad) + ephi * np.cos(phi_rad)
    near = thetas <= min(5.0, float(np.nanmax(thetas)))
    x_power = float(np.nanmean(np.abs(x_co[:, near]) ** 2))
    y_power = float(np.nanmean(np.abs(y_co[:, near]) ** 2))
    return ("H", "inferred from main-beam field") if x_power >= y_power else ("V", "inferred from main-beam field")


def pattern_from_rows(path: Path, frequency_hz: float, rows, port_label: str = "") -> Pattern:
    phis, thetas, etheta, ephi = _grid_from_rows(rows)
    polarization, basis = _resolve_polarization(path, port_label, etheta, ephi, phis, thetas)

    phi_rad = np.radians(phis)[:, None]
    x_component = etheta * np.cos(phi_rad) - ephi * np.sin(phi_rad)
    y_component = etheta * np.sin(phi_rad) + ephi * np.cos(phi_rad)
    if polarization == "H":
        eco, ecross = x_component, y_component
    else:
        eco, ecross = y_component, x_component

    total_power = np.abs(etheta) ** 2 + np.abs(ephi) ** 2
    co_power = np.abs(eco) ** 2
    cross_power = np.abs(ecross) ** 2
    phir = np.radians(phis)
    thetar = np.radians(thetas)
    weights = np.outer(circular_cell_sizes(phir), np.sin(thetar) * linear_cell_sizes(thetar))
    radiated_power = float(np.sum(total_power * weights))
    if not math.isfinite(radiated_power) or radiated_power <= 0:
        raise FFSParseError(f"{path.name}: frequency {frequency_hz:g} Hz has invalid radiated power")

    scale = 4.0 * math.pi / radiated_power

    def to_dbi(value: np.ndarray) -> np.ndarray:
        return 10.0 * np.log10(np.maximum(value * scale, 1e-300))
    return Pattern(
        frequency_hz=float(frequency_hz),
        phis_deg=phis,
        thetas_deg=thetas,
        total_directivity_dbi=to_dbi(total_power),
        co_directivity_dbi=to_dbi(co_power),
        cross_directivity_dbi=to_dbi(cross_power),
        polarization=polarization,
        polarization_basis=basis,
    )


def _nearest_phi_index(phis: np.ndarray, target: float) -> int:
    delta = np.abs(np.mod(phis - target + 180.0, 360.0) - 180.0)
    return int(np.argmin(delta))


def _plane_sides(values: np.ndarray, phis: np.ndarray, target: float) -> tuple[np.ndarray, np.ndarray]:
    return values[_nearest_phi_index(phis, target)], values[_nearest_phi_index(phis, target + 180.0)]


def _plane_envelope(values: np.ndarray, phis: np.ndarray, target: float) -> np.ndarray:
    positive, negative = _plane_sides(values, phis, target)
    return np.maximum(positive, negative)


def mask_limits(points: tuple[tuple[float, float], ...], angles_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return piecewise-linear mask limits and the angles where the mask is defined.

    When the standard repeats an angle to draw a vertical step, the last point
    controls at and after that angle.
    """
    if not points:
        return np.full_like(angles_deg, np.nan, dtype=float), np.zeros_like(angles_deg, dtype=bool)
    grouped: dict[float, list[float]] = {}
    for angle, limit in points:
        grouped.setdefault(float(angle), []).append(float(limit))
    x = np.asarray(sorted(grouped), dtype=float)
    valid = (angles_deg >= x[0]) & (angles_deg <= x[-1])
    limits = np.full_like(angles_deg, np.nan, dtype=float)
    for output_index in np.flatnonzero(valid):
        angle = float(angles_deg[output_index])
        exact = np.flatnonzero(np.isclose(x, angle, rtol=0.0, atol=1e-12))
        if exact.size:
            limits[output_index] = grouped[float(x[int(exact[-1])])][-1]
            continue
        right = int(np.searchsorted(x, angle, side="right"))
        left = right - 1
        x0, x1 = float(x[left]), float(x[right])
        y0 = grouped[x0][-1]
        y1 = grouped[x1][0]
        fraction = (angle - x0) / (x1 - x0)
        limits[output_index] = y0 + fraction * (y1 - y0)
    return limits, valid


def _mask_result(
    actual: np.ndarray,
    angles: np.ndarray,
    points: tuple[tuple[float, float], ...],
    omitted_angle_range: OmittedAngleRange = None,
) -> dict[str, float | bool | None]:
    limits, valid = mask_limits(points, angles)
    valid &= _included_angle_mask(angles, omitted_angle_range)
    if not np.any(valid):
        return {"passed": False, "margin_db": None, "angle_deg": None, "actual_dbi": None, "limit_dbi": None}
    margins = limits[valid] - actual[valid]
    index_local = int(np.nanargmin(margins))
    indices = np.flatnonzero(valid)
    index = int(indices[index_local])
    margin = float(margins[index_local])
    return {
        "passed": margin >= -1e-9,
        "margin_db": margin,
        "angle_deg": float(angles[index]),
        "actual_dbi": float(actual[index]),
        "limit_dbi": float(limits[index]),
    }


def _half_power_crossing(angles: np.ndarray, values: np.ndarray, peak_dbi: float) -> float:
    threshold = peak_dbi - 3.0
    for index in range(1, len(angles)):
        before = float(values[index - 1])
        after = float(values[index])
        if before > threshold >= after:
            span = after - before
            fraction = 0.0 if span == 0 else (threshold - before) / span
            return float(angles[index - 1] + fraction * (angles[index] - angles[index - 1]))
    return float("nan")


def plane_beamwidth(pattern: Pattern, target_phi: float) -> float:
    positive, negative = _plane_sides(pattern.co_directivity_dbi, pattern.phis_deg, target_phi)
    peak = float(np.nanmax(pattern.co_directivity_dbi))
    left = _half_power_crossing(pattern.thetas_deg, negative, peak)
    right = _half_power_crossing(pattern.thetas_deg, positive, peak)
    return left + right if math.isfinite(left) and math.isfinite(right) else float("nan")


def _etsi_profile_result(
    pattern: Pattern,
    profile: ETSIRPEProfile,
    omitted_angle_range: OmittedAngleRange = None,
) -> dict[str, object]:
    co_points = profile.co_points
    if profile.polarization_restriction and pattern.polarization != profile.polarization_restriction:
        return {
            "status": "NOT APPLICABLE",
            "note": f"ETSI Class {profile.class_name} is not applicable because it is restricted to {profile.polarization_restriction} polarization.",
            "reason": f"Class is restricted to {profile.polarization_restriction} polarization",
        }
    if profile.co_h_points or profile.co_v_points:
        co_points = profile.co_h_points if pattern.polarization == "H" else profile.co_v_points
    if not co_points:
        return {
            "status": "INDETERMINATE",
            "note": f"ETSI Class {profile.class_name} could not be evaluated because its polarization-specific co-polar mask could not be selected.",
            "reason": "Polarization-specific co-polar mask could not be selected",
        }

    co_az = _plane_envelope(pattern.co_directivity_dbi, pattern.phis_deg, 0.0)
    cross_az = _plane_envelope(pattern.cross_directivity_dbi, pattern.phis_deg, 0.0)
    co = _mask_result(co_az, pattern.thetas_deg, co_points, omitted_angle_range)
    cross = _mask_result(cross_az, pattern.thetas_deg, profile.cross_points, omitted_angle_range)
    elevation = None
    if profile.elevation_points:
        co_el = _plane_envelope(pattern.co_directivity_dbi, pattern.phis_deg, 90.0)
        elevation = _mask_result(co_el, pattern.thetas_deg, profile.elevation_points, omitted_angle_range)
    passed = bool(co["passed"] and cross["passed"] and (elevation is None or elevation["passed"]))
    components = [("co-polar azimuth", co), ("cross-polar azimuth", cross)]
    if elevation is not None:
        components.append(("co-polar elevation", elevation))
    finite_components = [item for item in components if item[1]["margin_db"] is not None]
    limiting_name, limiting = min(finite_components, key=lambda item: float(item[1]["margin_db"]))
    failed_components = [item for item in components if not item[1]["passed"]]
    failure_details: list[str] = []
    for component_name, component in failed_components:
        if component["margin_db"] is None:
            failure_details.append(f"the {component_name} mask could not be evaluated from the available angular samples")
            continue
        shortfall = -float(component["margin_db"])
        failure_details.append(
            f"the {component_name} pattern is {shortfall:.2f} dB above the allowed limit at "
            f"{float(component['angle_deg']):.2f} degrees "
            f"(measured {float(component['actual_dbi']):.2f} dBi; limit {float(component['limit_dbi']):.2f} dBi)"
        )
    note = ""
    if failed_components:
        note = f"ETSI Class {profile.class_name} fails because " + "; and ".join(failure_details) + "."
    return {
        "status": "PASS" if passed else "FAIL",
        "note": note,
        "co_pass": bool(co["passed"]),
        "cross_pass": bool(cross["passed"]),
        "elevation_pass": None if elevation is None else bool(elevation["passed"]),
        "margin_db": limiting["margin_db"],
        "limiting_component": limiting_name,
        "limiting_angle_deg": limiting["angle_deg"],
        "actual_dbi": limiting["actual_dbi"],
        "limit_dbi": limiting["limit_dbi"],
    }


def _etsi_sector_profile_result(
    pattern: Pattern,
    profile: ETSISectorProfile,
    sector_width_deg: float,
    center_frequency_ghz: float,
    omitted_angle_range: OmittedAngleRange = None,
) -> dict[str, object]:
    class_label = f"ETSI Sector Class {profile.class_name}"
    if not (profile.sector_width_min_deg <= sector_width_deg <= profile.sector_width_max_deg):
        return {
            "status": "NOT APPLICABLE",
            "note": (
                f"{class_label} is not applicable because its permitted sector width is "
                f"{profile.sector_width_min_deg:g}-{profile.sector_width_max_deg:g} degrees, "
                f"but {sector_width_deg:g} degrees was declared."
            ),
            "reason": "Declared sector width is outside the class range",
        }
    if not (profile.frequency_min_ghz <= center_frequency_ghz <= profile.frequency_max_ghz):
        return {
            "status": "INDETERMINATE",
            "note": (
                f"{class_label} could not be evaluated because declared centre frequency f0 is "
                f"{center_frequency_ghz:g} GHz, outside the {profile.range_key} mask range."
            ),
            "reason": "Declared centre frequency is outside the mask range",
        }

    co_az = _plane_envelope(pattern.co_directivity_dbi, pattern.phis_deg, 0.0)
    cross_az = _plane_envelope(pattern.cross_directivity_dbi, pattern.phis_deg, 0.0)
    reference_samples = (
        (pattern.thetas_deg <= sector_width_deg / 2.0 + 1e-9)
        & _included_angle_mask(pattern.thetas_deg, omitted_angle_range)
        & np.isfinite(co_az)
    )
    if not np.any(reference_samples):
        return {
            "status": "INDETERMINATE",
            "note": f"{class_label} could not be evaluated because no usable samples remain inside the declared sector.",
            "reason": "No usable samples inside the declared sector",
        }
    reference_dbi = float(np.nanmax(co_az[reference_samples]))
    co_el = _plane_envelope(pattern.co_directivity_dbi, pattern.phis_deg, 90.0)
    cross_el = _plane_envelope(pattern.cross_directivity_dbi, pattern.phis_deg, 90.0)
    components = [
        ("co-polar azimuth", _mask_result(co_az - reference_dbi, pattern.thetas_deg, profile.co_points, omitted_angle_range)),
        ("cross-polar azimuth", _mask_result(cross_az - reference_dbi, pattern.thetas_deg, profile.cross_points, omitted_angle_range)),
        ("co-polar elevation", _mask_result(co_el - reference_dbi, pattern.thetas_deg, profile.elevation_co_points, omitted_angle_range)),
        ("cross-polar elevation", _mask_result(cross_el - reference_dbi, pattern.thetas_deg, profile.elevation_cross_points, omitted_angle_range)),
    ]
    finite_components = [item for item in components if item[1]["margin_db"] is not None]
    if not finite_components:
        return {
            "status": "INDETERMINATE",
            "note": f"{class_label} could not be evaluated because none of its mask angles are available.",
            "reason": "No mask angles are available",
            "sector_reference_directivity_dbi": reference_dbi,
        }
    limiting_name, limiting = min(finite_components, key=lambda item: float(item[1]["margin_db"]))
    failed_components = [item for item in components if not item[1]["passed"]]
    failure_details: list[str] = []
    for component_name, component in failed_components:
        if component["margin_db"] is None:
            failure_details.append(f"the {component_name} mask could not be evaluated from the available angular samples")
            continue
        shortfall = -float(component["margin_db"])
        failure_details.append(
            f"the relative {component_name} pattern is {shortfall:.2f} dB above the allowed limit at "
            f"{float(component['angle_deg']):.2f} degrees "
            f"(measured {float(component['actual_dbi']):.2f} dB relative to the sector maximum; "
            f"limit {float(component['limit_dbi']):.2f} dB)"
        )
    note = f"{class_label} fails because " + "; and ".join(failure_details) + "." if failure_details else ""
    return {
        "status": "FAIL" if failed_components else "PASS",
        "note": note,
        "co_azimuth_pass": bool(components[0][1]["passed"]),
        "cross_azimuth_pass": bool(components[1][1]["passed"]),
        "co_elevation_pass": bool(components[2][1]["passed"]),
        "cross_elevation_pass": bool(components[3][1]["passed"]),
        "margin_db": limiting["margin_db"],
        "limiting_component": limiting_name,
        "limiting_angle_deg": limiting["angle_deg"],
        "actual_relative_db": limiting["actual_dbi"],
        "limit_relative_db": limiting["limit_dbi"],
        "sector_reference_directivity_dbi": reference_dbi,
    }


def _minimum_xpd_measurement(pattern: Pattern, valid: np.ndarray) -> dict[str, float | None]:
    xpd = pattern.co_directivity_dbi - pattern.cross_directivity_dbi
    usable = np.broadcast_to(valid, xpd.shape) & np.isfinite(xpd)
    if not np.any(usable):
        return {"measured_db": float("nan"), "phi_deg": None, "theta_deg": None}
    masked = np.where(usable, xpd, np.nan)
    phi_index, theta_index = np.unravel_index(int(np.nanargmin(masked)), masked.shape)
    return {
        "measured_db": float(masked[phi_index, theta_index]),
        "phi_deg": float(pattern.phis_deg[phi_index]),
        "theta_deg": float(pattern.thetas_deg[theta_index]),
    }


def xpd_assessment_masks(pattern: Pattern) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    peak = float(np.nanmax(pattern.co_directivity_dbi))
    category1_mask = np.zeros_like(pattern.co_directivity_dbi, dtype=bool)
    for target_phi in (0.0, 180.0):
        phi_index = _nearest_phi_index(pattern.phis_deg, target_phi)
        category1_mask[phi_index, :] = pattern.co_directivity_dbi[phi_index, :] >= peak - 1.0

    one_db_3d = pattern.co_directivity_dbi >= peak - 1.0
    extended = one_db_3d | (pattern.thetas_deg[None, :] <= 3.0)
    return category1_mask, one_db_3d, extended


def _xpd_measurements(pattern: Pattern) -> tuple[dict[str, float | None], ...]:
    return tuple(
        _minimum_xpd_measurement(pattern, mask)
        for mask in xpd_assessment_masks(pattern)
    )


def _etsi_xpd_result(pattern: Pattern) -> dict[str, object]:
    requirements = etsi_xpd_requirements(pattern.frequency_hz / 1e9)
    measurements = _xpd_measurements(pattern)
    passed: list[str] = []
    details: list[str] = []
    category_results: dict[str, dict[str, object]] = {}
    for index, (minimum, measurement) in enumerate(zip(requirements, measurements), start=1):
        if minimum is None:
            continue
        actual = float(measurement["measured_db"])
        ok = math.isfinite(actual) and actual >= minimum
        details.append(f"Category {index}: {actual:.2f} dB vs {minimum:.2f} dB")
        if ok:
            passed.append(str(index))
        margin = actual - minimum if math.isfinite(actual) else float("nan")
        note = ""
        if not ok:
            if math.isfinite(actual):
                note = (
                    f"ETSI XPD Category {index} fails because the minimum measured cross-polar discrimination is "
                    f"{actual:.2f} dB at phi {float(measurement['phi_deg']):.2f} degrees, "
                    f"theta {float(measurement['theta_deg']):.2f} degrees, which is {-margin:.2f} dB below "
                    f"the required {minimum:.2f} dB."
                )
            else:
                note = f"ETSI XPD Category {index} fails because no valid cross-polar discrimination value could be calculated."
        category_results[str(index)] = {
            "status": "PASS" if ok else "FAIL",
            "measured_db": actual,
            "required_db": minimum,
            "margin_db": margin,
            "phi_deg": measurement["phi_deg"],
            "theta_deg": measurement["theta_deg"],
            "note": note,
        }
    return {
        "best_category": passed[-1] if passed else "None",
        "passed_categories": ", ".join(passed),
        "category1_xpd_db": measurements[0]["measured_db"],
        "category2_xpd_db": measurements[1]["measured_db"],
        "category3_xpd_db": measurements[2]["measured_db"],
        "detail": "; ".join(details) if details else "No XPD category is defined for this frequency",
        "category_results": category_results,
    }


def _suppression_result(
    angles: np.ndarray,
    actual_dbi: np.ndarray,
    requirements: tuple[float | None, ...],
    peak_dbi: float,
    omitted_angle_range: OmittedAngleRange = None,
) -> dict[str, object]:
    margins: list[tuple[float, float, float, float]] = []
    included = _included_angle_mask(angles, omitted_angle_range)
    for (low, high), minimum in zip(FCC_ANGLE_BINS, requirements):
        if minimum is None:
            continue
        selected = (angles >= low) & (angles <= high) & included
        if not np.any(selected):
            return {"passed": False, "margin_db": None, "angle_deg": None, "reason": f"No samples in {low:g}-{high:g} degrees"}
        indices = np.flatnonzero(selected)
        local = int(np.nanargmax(actual_dbi[selected]))
        index = int(indices[local])
        suppression = peak_dbi - float(actual_dbi[index])
        margins.append((suppression - float(minimum), float(angles[index]), suppression, float(minimum)))
    if not margins:
        return {"passed": True, "margin_db": None, "angle_deg": None, "reason": "No suppression limits"}
    margin, angle, suppression, minimum = min(margins, key=lambda item: item[0])
    return {
        "passed": margin >= -1e-9,
        "margin_db": margin,
        "angle_deg": angle,
        "actual_suppression_db": suppression,
        "required_suppression_db": minimum,
    }


def _fcc_profile_result(
    pattern: Pattern,
    profile: FCCProfile,
    omitted_angle_range: OmittedAngleRange = None,
) -> dict[str, object]:
    az_bw = plane_beamwidth(pattern, 0.0)
    el_bw = plane_beamwidth(pattern, 90.0)
    beam_pass = None
    if profile.max_beamwidth_deg is not None:
        beam_pass = bool(
            math.isfinite(az_bw)
            and math.isfinite(el_bw)
            and az_bw <= profile.max_beamwidth_deg
            and el_bw <= profile.max_beamwidth_deg
        )
    gain_pass = None
    if profile.min_gain_dbi is not None:
        gain_pass = pattern.max_directivity_dbi >= profile.min_gain_dbi
    beam_or_gain = bool(beam_pass is True or gain_pass is True)

    co_az = _plane_envelope(pattern.co_directivity_dbi, pattern.phis_deg, 0.0)
    cross_az = _plane_envelope(pattern.cross_directivity_dbi, pattern.phis_deg, 0.0)
    co_peak = float(np.nanmax(pattern.co_directivity_dbi))
    co_suppression = _suppression_result(
        pattern.thetas_deg, co_az, profile.suppression_db, co_peak, omitted_angle_range
    )
    cross_suppression = None
    if profile.cross_suppression_db:
        cross_suppression = _suppression_result(
            pattern.thetas_deg, cross_az, profile.cross_suppression_db, co_peak, omitted_angle_range
        )

    xpd_pass = True
    minimum_xpd = None
    xpd_phi = None
    xpd_theta = None
    if profile.xpd_min_db is not None:
        xpd_measurement = _minimum_xpd_measurement(pattern, pattern.thetas_deg[None, :] < 5.0)
        minimum_xpd = float(xpd_measurement["measured_db"])
        xpd_phi = xpd_measurement["phi_deg"]
        xpd_theta = xpd_measurement["theta_deg"]
        xpd_pass = math.isfinite(minimum_xpd) and minimum_xpd >= profile.xpd_min_db
    passed = beam_or_gain and bool(co_suppression["passed"]) and bool(xpd_pass) and (
        cross_suppression is None or bool(cross_suppression["passed"])
    )

    beam_margin = None
    if profile.max_beamwidth_deg is not None and math.isfinite(az_bw) and math.isfinite(el_bw):
        beam_margin = profile.max_beamwidth_deg - max(az_bw, el_bw)
    gain_margin = None
    if profile.min_gain_dbi is not None:
        gain_margin = pattern.max_directivity_dbi - profile.min_gain_dbi
    qualification_options = [
        ("beamwidth qualification", beam_margin, max(az_bw, el_bw), profile.max_beamwidth_deg, "degrees")
        if beam_margin is not None
        else None,
        ("directivity qualification", gain_margin, pattern.max_directivity_dbi, profile.min_gain_dbi, "dBi")
        if gain_margin is not None
        else None,
    ]
    qualification_options = [option for option in qualification_options if option is not None]
    qualification = max(qualification_options, key=lambda item: float(item[1])) if qualification_options else None

    limiting_candidates: list[tuple[str, float, float | None, float | None, str, float | None, float | None, float | None]] = []
    if qualification is not None:
        limiting_candidates.append((qualification[0], float(qualification[1]), qualification[2], qualification[3], qualification[4], None, None, None))
    if co_suppression.get("margin_db") is not None:
        limiting_candidates.append(
            (
                "co-polar suppression",
                float(co_suppression["margin_db"]),
                float(co_suppression["actual_suppression_db"]),
                float(co_suppression["required_suppression_db"]),
                "dB",
                float(co_suppression["angle_deg"]),
                None,
                None,
            )
        )
    if cross_suppression is not None and cross_suppression.get("margin_db") is not None:
        limiting_candidates.append(
            (
                "cross-polar suppression",
                float(cross_suppression["margin_db"]),
                float(cross_suppression["actual_suppression_db"]),
                float(cross_suppression["required_suppression_db"]),
                "dB",
                float(cross_suppression["angle_deg"]),
                None,
                None,
            )
        )
    if profile.xpd_min_db is not None and minimum_xpd is not None and math.isfinite(minimum_xpd):
        limiting_candidates.append(
            (
                "cross-polar discrimination",
                minimum_xpd - profile.xpd_min_db,
                minimum_xpd,
                profile.xpd_min_db,
                "dB",
                None,
                None if xpd_phi is None else float(xpd_phi),
                None if xpd_theta is None else float(xpd_theta),
            )
        )
    limiting = min(limiting_candidates, key=lambda item: item[1]) if limiting_candidates else None

    failure_details: list[str] = []
    if not beam_or_gain:
        alternatives: list[str] = []
        has_both_qualification_routes = profile.max_beamwidth_deg is not None and profile.min_gain_dbi is not None
        if profile.max_beamwidth_deg is not None:
            if math.isfinite(az_bw) and math.isfinite(el_bw):
                exceeded = []
                if az_bw > profile.max_beamwidth_deg:
                    exceeded.append(f"azimuth beamwidth {az_bw:.2f} degrees")
                if el_bw > profile.max_beamwidth_deg:
                    exceeded.append(f"elevation beamwidth {el_bw:.2f} degrees")
                beamwidth_problem = f"{' and '.join(exceeded)} exceed the {profile.max_beamwidth_deg:.2f}-degree maximum"
                alternatives.append(
                    f"the beamwidth alternative is not met because {beamwidth_problem}"
                    if has_both_qualification_routes
                    else beamwidth_problem
                )
            else:
                alternatives.append(
                    "the beamwidth alternative could not be calculated from the available angular samples"
                    if has_both_qualification_routes
                    else "beamwidth could not be calculated from the available angular samples"
                )
        if profile.min_gain_dbi is not None:
            directivity_problem = (
                f"directivity {pattern.max_directivity_dbi:.2f} dBi is "
                f"{profile.min_gain_dbi - pattern.max_directivity_dbi:.2f} dB below the required {profile.min_gain_dbi:.2f} dBi"
            )
            alternatives.append(
                f"the directivity alternative is not met because {directivity_problem}"
                if has_both_qualification_routes
                else directivity_problem
            )
        if has_both_qualification_routes:
            failure_details.append("neither beamwidth nor directivity qualifies: " + "; and ".join(alternatives))
        else:
            failure_details.extend(alternatives)
    if not co_suppression["passed"]:
        if co_suppression.get("margin_db") is None:
            failure_details.append(f"the co-polar suppression requirement could not be evaluated ({co_suppression.get('reason', 'missing samples')})")
        else:
            failure_details.append(
                f"co-polar suppression is {float(co_suppression['actual_suppression_db']):.2f} dB at "
                f"{float(co_suppression['angle_deg']):.2f} degrees, {abs(float(co_suppression['margin_db'])):.2f} dB below "
                f"the required {float(co_suppression['required_suppression_db']):.2f} dB"
            )
    if cross_suppression is not None and not cross_suppression["passed"]:
        if cross_suppression.get("margin_db") is None:
            failure_details.append(f"the cross-polar suppression requirement could not be evaluated ({cross_suppression.get('reason', 'missing samples')})")
        else:
            failure_details.append(
                f"cross-polar suppression is {float(cross_suppression['actual_suppression_db']):.2f} dB at "
                f"{float(cross_suppression['angle_deg']):.2f} degrees, {abs(float(cross_suppression['margin_db'])):.2f} dB below "
                f"the required {float(cross_suppression['required_suppression_db']):.2f} dB"
            )
    if not xpd_pass:
        if minimum_xpd is not None and math.isfinite(minimum_xpd):
            failure_details.append(
                f"cross-polar discrimination is {minimum_xpd:.2f} dB at phi {float(xpd_phi):.2f} degrees, "
                f"theta {float(xpd_theta):.2f} degrees, {profile.xpd_min_db - minimum_xpd:.2f} dB below "
                f"the required {profile.xpd_min_db:.2f} dB"
            )
        else:
            failure_details.append("cross-polar discrimination could not be calculated from the available samples")
    standard_label = "FCC band requirement" if profile.standard == "Band requirement" else f"FCC Standard {profile.standard}"
    failure_note = f"{standard_label} fails because " + "; and ".join(failure_details) + "." if failure_details else ""
    return {
        "status": "PASS" if passed else "FAIL",
        "failure_note": failure_note,
        "azimuth_beamwidth_deg": az_bw,
        "elevation_beamwidth_deg": el_bw,
        "max_beamwidth_deg": profile.max_beamwidth_deg,
        "beamwidth_pass": beam_pass,
        "directivity_dbi": pattern.max_directivity_dbi,
        "min_gain_dbi": profile.min_gain_dbi,
        "gain_pass": gain_pass,
        "beam_or_gain_pass": beam_or_gain,
        "suppression_pass": bool(co_suppression["passed"]),
        "suppression_margin_db": co_suppression.get("margin_db"),
        "suppression_db": co_suppression.get("actual_suppression_db"),
        "required_suppression_db": co_suppression.get("required_suppression_db"),
        "limiting_angle_deg": co_suppression.get("angle_deg"),
        "cross_suppression_pass": None if cross_suppression is None else bool(cross_suppression["passed"]),
        "cross_suppression_margin_db": None if cross_suppression is None else cross_suppression.get("margin_db"),
        "cross_suppression_db": None if cross_suppression is None else cross_suppression.get("actual_suppression_db"),
        "required_cross_suppression_db": None if cross_suppression is None else cross_suppression.get("required_suppression_db"),
        "cross_limiting_angle_deg": None if cross_suppression is None else cross_suppression.get("angle_deg"),
        "minimum_xpd_db": minimum_xpd,
        "required_xpd_db": profile.xpd_min_db,
        "minimum_xpd_phi_deg": xpd_phi,
        "minimum_xpd_theta_deg": xpd_theta,
        "xpd_pass": None if profile.xpd_min_db is None else xpd_pass,
        "overall_margin_db": None if limiting is None else limiting[1],
        "limiting_component": None if limiting is None else limiting[0],
        "limiting_measured_value": None if limiting is None else limiting[2],
        "limiting_limit_value": None if limiting is None else limiting[3],
        "limiting_unit": None if limiting is None else limiting[4],
        "overall_limiting_angle_deg": None if limiting is None else limiting[5],
        "overall_limiting_phi_deg": None if limiting is None else limiting[6],
        "overall_limiting_theta_deg": None if limiting is None else limiting[7],
    }


def analyze_pattern(
    path: Path,
    port_label: str,
    pattern: Pattern,
    *,
    omitted_angle_range: OmittedAngleRange = None,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    frequency_ghz = pattern.frequency_hz / 1e9
    common = {
        "source_file": path.name,
        "source_path": str(path),
        "port_label": port_label,
        "frequency_ghz": frequency_ghz,
        "polarization": pattern.polarization,
        "polarization_basis": pattern.polarization_basis,
        "max_directivity_dbi": pattern.max_directivity_dbi,
    }

    etsi_details: list[dict[str, object]] = []
    etsi_passed: list[str] = []
    etsi_range = "Not applicable"
    for profile in etsi_profiles_for_frequency(frequency_ghz):
        etsi_range = profile.range_key
        result = _etsi_profile_result(pattern, profile, omitted_angle_range)
        row = {**common, "etsi_range": profile.range_key, "rpe_class": profile.class_name, **result}
        etsi_details.append(row)
        if result.get("status") == "PASS":
            etsi_passed.append(profile.class_name)
    xpd = _etsi_xpd_result(pattern)

    fcc_details: list[dict[str, object]] = []
    fcc_passed: list[str] = []
    fcc_band = "Not applicable"
    for profile in fcc_profiles_for_frequency(pattern.frequency_hz / 1e6):
        fcc_band = f"{profile.frequency_min_mhz:g}-{profile.frequency_max_mhz:g} MHz"
        result = _fcc_profile_result(pattern, profile, omitted_angle_range)
        row = {**common, "fcc_band": fcc_band, "standard": profile.standard, "regulatory_note": profile.note, **result}
        fcc_details.append(row)
        if result["status"] == "PASS":
            fcc_passed.append(profile.standard)
    if "A" in fcc_passed:
        fcc_best = "A"
    elif fcc_passed:
        fcc_best = fcc_passed[0]
    else:
        fcc_best = "None" if fcc_details else "Not applicable"

    summary = {
        **common,
        "etsi_range": etsi_range,
        "etsi_best_rpe_class": etsi_passed[-1] if etsi_passed else ("None" if etsi_details else "Not applicable"),
        "etsi_passed_rpe_classes": ", ".join(etsi_passed),
        "etsi_best_xpd_category": xpd["best_category"],
        "etsi_passed_xpd_categories": xpd["passed_categories"],
        "etsi_xpd_detail": xpd["detail"],
        "_etsi_xpd_categories": xpd["category_results"],
        "fcc_band": fcc_band,
        "fcc_best_standard": fcc_best,
        "fcc_passed_standards": ", ".join(fcc_passed),
    }
    return summary, etsi_details, fcc_details


def analyze_files(
    paths: Iterable[Path],
    *,
    port_labels: dict[str, str] | None = None,
    fmin_ghz: float = 0.0,
    fmax_ghz: float = 0.0,
    omitted_angle_range: OmittedAngleRange = None,
    sector_width_deg: float = 0.0,
    sector_center_ghz: float = 0.0,
    pattern_observer: Callable[..., None] | None = None,
) -> dict[str, list[dict[str, object]]]:
    if sector_width_deg > 0.0 and sector_center_ghz <= 0.0 and not (fmin_ghz > 0.0 and fmax_ghz > 0.0):
        raise ValueError(
            "Sector evaluation requires a declared centre frequency, or both compliance frequency bounds for automatic f0"
        )
    labels = {str(key).lower(): str(value).strip() for key, value in (port_labels or {}).items()}
    summary_rows: list[dict[str, object]] = []
    etsi_rows: list[dict[str, object]] = []
    sector_rows: list[dict[str, object]] = []
    fcc_rows: list[dict[str, object]] = []
    for path_value in paths:
        path = Path(path_value)
        label = labels.get(path.name.lower(), labels.get(str(path).lower(), ""))
        for frequency_hz, rows in sorted(read_ffs_broadband(path).items()):
            frequency_ghz = frequency_hz / 1e9
            if fmin_ghz > 0 and frequency_ghz < fmin_ghz:
                continue
            if fmax_ghz > 0 and frequency_ghz > fmax_ghz:
                continue
            pattern = pattern_from_rows(path, frequency_hz, rows, label)
            summary, etsi, fcc = analyze_pattern(
                path,
                label,
                pattern,
                omitted_angle_range=omitted_angle_range,
            )
            sample_sector_rows: list[dict[str, object]] = []
            if sector_width_deg > 0.0:
                effective_center = sector_center_ghz
                if effective_center <= 0.0:
                    effective_center = (fmin_ghz + fmax_ghz) / 2.0
                passed_sector_classes: list[str] = []
                profiles = etsi_sector_profiles(frequency_ghz, effective_center, sector_width_deg)
                for profile in profiles:
                    result = _etsi_sector_profile_result(
                        pattern,
                        profile,
                        sector_width_deg,
                        effective_center,
                        omitted_angle_range,
                    )
                    sample_sector_rows.append(
                        {
                            **{name: summary.get(name) for name in (
                                "source_file",
                                "source_path",
                                "port_label",
                                "frequency_ghz",
                                "polarization",
                                "polarization_basis",
                                "max_directivity_dbi",
                            )},
                            "standard_family": "ETSI EN 302 326-3 single-beam sector (linear, symmetric elevation)",
                            "etsi_sector_range": profile.range_key,
                            "sector_class": profile.class_name,
                            "sector_width_deg": sector_width_deg,
                            "sector_center_ghz": effective_center,
                            "sector_width_min_deg": profile.sector_width_min_deg,
                            "sector_width_max_deg": profile.sector_width_max_deg,
                            **result,
                        }
                    )
                    if result.get("status") == "PASS":
                        passed_sector_classes.append(profile.class_name)
                summary.update(
                    {
                        "etsi_sector_enabled": True,
                        "etsi_sector_width_deg": sector_width_deg,
                        "etsi_sector_center_ghz": effective_center,
                        "etsi_sector_range": profiles[0].range_key if profiles else "Not applicable",
                        "etsi_best_sector_class": passed_sector_classes[-1]
                        if passed_sector_classes
                        else ("None" if profiles else "Not applicable"),
                        "etsi_passed_sector_classes": ", ".join(passed_sector_classes),
                    }
                )
            if pattern_observer is not None:
                pattern_observer(path, label, pattern, summary, etsi, sample_sector_rows, fcc)
            summary_rows.append(summary)
            etsi_rows.extend(etsi)
            sector_rows.extend(sample_sector_rows)
            fcc_rows.extend(fcc)
    if not summary_rows:
        raise ValueError("No far-field frequencies fall inside the selected compliance frequency window")
    return {
        "rollup": _build_rollup(summary_rows, etsi_rows, fcc_rows, sector_rows),
        "per_frequency": _build_per_frequency_results(summary_rows, etsi_rows, fcc_rows, sector_rows),
        "summary": summary_rows,
        "etsi": etsi_rows,
        "sector": sector_rows,
        "fcc": fcc_rows,
    }


def _sample_key(row: dict[str, object]) -> tuple[object, ...]:
    return (row.get("source_path"), row.get("frequency_ghz"), row.get("polarization"))


def _build_per_frequency_results(
    summary_rows: list[dict[str, object]],
    etsi_rows: list[dict[str, object]],
    fcc_rows: list[dict[str, object]],
    sector_rows: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    etsi_by_sample: dict[tuple[object, ...], list[dict[str, object]]] = {}
    fcc_by_sample: dict[tuple[object, ...], list[dict[str, object]]] = {}
    sector_by_sample: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for row in etsi_rows:
        etsi_by_sample.setdefault(_sample_key(row), []).append(row)
    for row in fcc_rows:
        fcc_by_sample.setdefault(_sample_key(row), []).append(row)
    for row in sector_rows or []:
        sector_by_sample.setdefault(_sample_key(row), []).append(row)

    results: list[dict[str, object]] = []
    for summary in sorted(summary_rows, key=lambda row: (str(row.get("source_path", "")), float(row["frequency_ghz"]))):
        key = _sample_key(summary)
        common = {
            name: summary.get(name)
            for name in (
                "source_file",
                "source_path",
                "port_label",
                "frequency_ghz",
                "polarization",
                "max_directivity_dbi",
            )
        }

        sample_etsi = etsi_by_sample.get(key, [])
        if sample_etsi:
            for row in sample_etsi:
                angle = row.get("limiting_angle_deg")
                results.append(
                    {
                        **common,
                        "family": "ETSI RPE",
                        "band": row.get("etsi_range"),
                        "classification": f"Class {row.get('rpe_class')}",
                        "status": row.get("status"),
                        "note": row.get("note", ""),
                        "limiting_component": row.get("limiting_component"),
                        "location": "" if angle is None else f"{row.get('limiting_component')} at {float(angle):.2f} degrees from boresight",
                        "limiting_angle_deg": angle,
                        "limiting_phi_deg": None,
                        "limiting_theta_deg": None,
                        "measured_value": row.get("actual_dbi"),
                        "limit_value": row.get("limit_dbi"),
                        "unit": "dBi",
                        "margin_db": row.get("margin_db"),
                    }
                )
        else:
            results.append(
                {
                    **common,
                    "family": "ETSI RPE",
                    "band": "Not applicable",
                    "classification": "No applicable class",
                    "status": "NOT APPLICABLE",
                    "note": f"No ETSI RPE frequency range covers {float(summary['frequency_ghz']):.3f} GHz.",
                }
            )

        if summary.get("etsi_sector_enabled"):
            sample_sector = sector_by_sample.get(key, [])
            if sample_sector:
                for row in sample_sector:
                    angle = row.get("limiting_angle_deg")
                    results.append(
                        {
                            **common,
                            "family": "ETSI Sector RPE",
                            "band": row.get("etsi_sector_range"),
                            "classification": f"Class {row.get('sector_class')}",
                            "status": row.get("status"),
                            "note": row.get("note", ""),
                            "limiting_component": row.get("limiting_component"),
                            "location": "" if angle is None else f"{row.get('limiting_component')} at {float(angle):.2f} degrees from boresight",
                            "limiting_angle_deg": angle,
                            "limiting_phi_deg": None,
                            "limiting_theta_deg": None,
                            "measured_value": row.get("actual_relative_db"),
                            "limit_value": row.get("limit_relative_db"),
                            "unit": "dB relative to sector maximum",
                            "margin_db": row.get("margin_db"),
                        }
                    )
            else:
                results.append(
                    {
                        **common,
                        "family": "ETSI Sector RPE",
                        "band": "Not applicable",
                        "classification": "No applicable class",
                        "status": "NOT APPLICABLE",
                        "note": f"No ETSI EN 302 326-3 single-beam sector RPE covers {float(summary['frequency_ghz']):.3f} GHz.",
                    }
                )

        xpd_categories = dict(summary.get("_etsi_xpd_categories", {}))
        if xpd_categories:
            for category, category_result in sorted(xpd_categories.items()):
                phi = category_result.get("phi_deg")
                theta = category_result.get("theta_deg")
                location = ""
                if phi is not None and theta is not None:
                    location = f"phi {float(phi):.2f} degrees, theta {float(theta):.2f} degrees"
                results.append(
                    {
                        **common,
                        "family": "ETSI XPD",
                        "band": summary.get("etsi_range"),
                        "classification": f"Category {category}",
                        "status": category_result.get("status"),
                        "note": category_result.get("note", ""),
                        "limiting_component": "cross-polar discrimination",
                        "location": location,
                        "limiting_angle_deg": None,
                        "limiting_phi_deg": phi,
                        "limiting_theta_deg": theta,
                        "measured_value": category_result.get("measured_db"),
                        "limit_value": category_result.get("required_db"),
                        "unit": "dB",
                        "margin_db": category_result.get("margin_db"),
                    }
                )
        else:
            results.append(
                {
                    **common,
                    "family": "ETSI XPD",
                    "band": summary.get("etsi_range"),
                    "classification": "No applicable category",
                    "status": "NOT APPLICABLE",
                    "note": f"No ETSI XPD category is defined at {float(summary['frequency_ghz']):.3f} GHz.",
                }
            )

        sample_fcc = fcc_by_sample.get(key, [])
        if sample_fcc:
            for row in sample_fcc:
                angle = row.get("overall_limiting_angle_deg")
                phi = row.get("overall_limiting_phi_deg")
                theta = row.get("overall_limiting_theta_deg")
                if angle is not None:
                    location = f"{float(angle):.2f} degrees from boresight"
                elif phi is not None and theta is not None:
                    location = f"phi {float(phi):.2f} degrees, theta {float(theta):.2f} degrees"
                else:
                    location = "beamwidth/directivity qualification"
                results.append(
                    {
                        **common,
                        "family": "FCC Part 101",
                        "band": row.get("fcc_band"),
                        "classification": "Band requirement"
                        if row.get("standard") == "Band requirement"
                        else f"Standard {row.get('standard')}",
                        "status": row.get("status"),
                        "note": row.get("failure_note", ""),
                        "limiting_component": row.get("limiting_component"),
                        "location": location,
                        "limiting_angle_deg": angle,
                        "limiting_phi_deg": phi,
                        "limiting_theta_deg": theta,
                        "measured_value": row.get("limiting_measured_value"),
                        "limit_value": row.get("limiting_limit_value"),
                        "unit": row.get("limiting_unit"),
                        "margin_db": row.get("overall_margin_db"),
                    }
                )
        else:
            results.append(
                {
                    **common,
                    "family": "FCC Part 101",
                    "band": "Not applicable",
                    "classification": "No applicable standard",
                    "status": "NOT APPLICABLE",
                    "note": f"No FCC Part 101 antenna standard covers {float(summary['frequency_ghz']):.3f} GHz.",
                }
            )
    return results


def _build_rollup(
    summary_rows: list[dict[str, object]],
    etsi_rows: list[dict[str, object]],
    fcc_rows: list[dict[str, object]],
    sector_rows: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    rollup: list[dict[str, object]] = []
    base_keys = ("source_file", "source_path", "port_label", "polarization")

    etsi_groups: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for row in etsi_rows:
        key = tuple(row.get(name) for name in base_keys) + (row.get("etsi_range"), row.get("rpe_class"))
        etsi_groups.setdefault(key, []).append(row)
    for key, rows in etsi_groups.items():
        statuses = [str(row.get("status", "")) for row in rows]
        margins = [float(row["margin_db"]) for row in rows if row.get("margin_db") is not None]
        status = "PASS" if statuses and all(value == "PASS" for value in statuses) else (
            "NOT APPLICABLE" if statuses and all(value == "NOT APPLICABLE" for value in statuses) else "FAIL"
        )
        note = ""
        if status == "FAIL":
            failed_rows = [row for row in rows if row.get("status") == "FAIL"]
            if failed_rows:
                worst = min(
                    failed_rows,
                    key=lambda row: float(row["margin_db"]) if row.get("margin_db") is not None else -math.inf,
                )
                note = f"At {float(worst['frequency_ghz']):.3f} GHz, {str(worst.get('note', '')).strip()}"
        elif status == "NOT APPLICABLE":
            note = str(rows[0].get("note", ""))
        rollup.append(
            {
                **dict(zip(base_keys, key[: len(base_keys)])),
                "family": "ETSI RPE",
                "band": key[-2],
                "classification": f"Class {key[-1]}",
                "status": status,
                "note": note,
                "frequencies_checked": len(rows),
                "frequency_min_ghz": min(float(row["frequency_ghz"]) for row in rows),
                "frequency_max_ghz": max(float(row["frequency_ghz"]) for row in rows),
                "worst_margin_db": min(margins) if margins else None,
            }
        )

    sector_groups: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for row in sector_rows or []:
        key = tuple(row.get(name) for name in base_keys) + (row.get("etsi_sector_range"), row.get("sector_class"))
        sector_groups.setdefault(key, []).append(row)
    for key, rows in sector_groups.items():
        statuses = [str(row.get("status", "")) for row in rows]
        margins = [float(row["margin_db"]) for row in rows if row.get("margin_db") is not None]
        status = "PASS" if statuses and all(value == "PASS" for value in statuses) else (
            "NOT APPLICABLE" if statuses and all(value == "NOT APPLICABLE" for value in statuses) else (
                "INDETERMINATE" if statuses and all(value == "INDETERMINATE" for value in statuses) else "FAIL"
            )
        )
        note = ""
        if status == "FAIL":
            failed_rows = [row for row in rows if row.get("status") == "FAIL"]
            if failed_rows:
                worst = min(
                    failed_rows,
                    key=lambda row: float(row["margin_db"]) if row.get("margin_db") is not None else -math.inf,
                )
                note = f"At {float(worst['frequency_ghz']):.3f} GHz, {str(worst.get('note', '')).strip()}"
        elif status in {"NOT APPLICABLE", "INDETERMINATE"}:
            note = str(rows[0].get("note", ""))
        rollup.append(
            {
                **dict(zip(base_keys, key[: len(base_keys)])),
                "family": "ETSI Sector RPE",
                "band": key[-2],
                "classification": f"Class {key[-1]}",
                "status": status,
                "note": note,
                "frequencies_checked": len(rows),
                "frequency_min_ghz": min(float(row["frequency_ghz"]) for row in rows),
                "frequency_max_ghz": max(float(row["frequency_ghz"]) for row in rows),
                "worst_margin_db": min(margins) if margins else None,
            }
        )

    summary_groups: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for row in summary_rows:
        if row.get("etsi_range") == "Not applicable":
            continue
        key = tuple(row.get(name) for name in base_keys) + (row.get("etsi_range"),)
        summary_groups.setdefault(key, []).append(row)
    for key, rows in summary_groups.items():
        applicable_categories = {
            category
            for row in rows
            for category in dict(row.get("_etsi_xpd_categories", {}))
        }
        for category in sorted(applicable_categories):
            category_rows = [
                (row, dict(row.get("_etsi_xpd_categories", {}))[category])
                for row in rows
                if category in dict(row.get("_etsi_xpd_categories", {}))
            ]
            passed = bool(category_rows) and all(result.get("status") == "PASS" for _, result in category_rows)
            margins = [
                float(result["margin_db"])
                for _, result in category_rows
                if result.get("margin_db") is not None and math.isfinite(float(result["margin_db"]))
            ]
            note = ""
            if not passed:
                failed = [(row, result) for row, result in category_rows if result.get("status") == "FAIL"]
                if failed:
                    worst_row, worst_result = min(
                        failed,
                        key=lambda item: float(item[1]["margin_db"])
                        if item[1].get("margin_db") is not None and math.isfinite(float(item[1]["margin_db"]))
                        else -math.inf,
                    )
                    note = f"At {float(worst_row['frequency_ghz']):.3f} GHz, {str(worst_result.get('note', '')).strip()}"
            rollup.append(
                {
                    **dict(zip(base_keys, key[: len(base_keys)])),
                    "family": "ETSI XPD",
                    "band": key[-1],
                    "classification": f"Category {category}",
                    "status": "PASS" if passed else "FAIL",
                    "note": note,
                    "frequencies_checked": len(rows),
                    "frequency_min_ghz": min(float(row["frequency_ghz"]) for row in rows),
                    "frequency_max_ghz": max(float(row["frequency_ghz"]) for row in rows),
                    "worst_margin_db": min(margins) if margins else None,
                }
            )

    fcc_groups: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for row in fcc_rows:
        key = tuple(row.get(name) for name in base_keys) + (row.get("fcc_band"), row.get("standard"))
        fcc_groups.setdefault(key, []).append(row)
    for key, rows in fcc_groups.items():
        margins = [float(row["overall_margin_db"]) for row in rows if row.get("overall_margin_db") is not None]
        passed = all(row.get("status") == "PASS" for row in rows)
        note = ""
        if not passed:
            failed_rows = [row for row in rows if row.get("status") == "FAIL"]
            if failed_rows:
                worst = min(
                    failed_rows,
                    key=lambda row: float(row["overall_margin_db"])
                    if row.get("overall_margin_db") is not None
                    else -math.inf,
                )
                note = f"At {float(worst['frequency_ghz']):.3f} GHz, {str(worst.get('failure_note', '')).strip()}"
        rollup.append(
            {
                **dict(zip(base_keys, key[: len(base_keys)])),
                "family": "FCC Part 101",
                "band": key[-2],
                "classification": "Band requirement" if key[-1] == "Band requirement" else f"Standard {key[-1]}",
                "status": "PASS" if passed else "FAIL",
                "note": note,
                "frequencies_checked": len(rows),
                "frequency_min_ghz": min(float(row["frequency_ghz"]) for row in rows),
                "frequency_max_ghz": max(float(row["frequency_ghz"]) for row in rows),
                "worst_margin_db": min(margins) if margins else None,
            }
        )
    return rollup
