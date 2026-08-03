from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

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
    etsi_profiles_for_frequency,
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


def _mask_result(actual: np.ndarray, angles: np.ndarray, points: tuple[tuple[float, float], ...]) -> dict[str, float | bool | None]:
    limits, valid = mask_limits(points, angles)
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


def _etsi_profile_result(pattern: Pattern, profile: ETSIRPEProfile) -> dict[str, object]:
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
    co = _mask_result(co_az, pattern.thetas_deg, co_points)
    cross = _mask_result(cross_az, pattern.thetas_deg, profile.cross_points)
    elevation = None
    if profile.elevation_points:
        co_el = _plane_envelope(pattern.co_directivity_dbi, pattern.phis_deg, 90.0)
        elevation = _mask_result(co_el, pattern.thetas_deg, profile.elevation_points)
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


def _xpd_values(pattern: Pattern) -> tuple[float, float, float]:
    co_az = _plane_envelope(pattern.co_directivity_dbi, pattern.phis_deg, 0.0)
    cross_az = _plane_envelope(pattern.cross_directivity_dbi, pattern.phis_deg, 0.0)
    peak = float(np.nanmax(pattern.co_directivity_dbi))
    one_db_az = co_az >= peak - 1.0
    category1 = float(np.nanmin(co_az[one_db_az] - cross_az[one_db_az])) if np.any(one_db_az) else float("nan")

    one_db_3d = pattern.co_directivity_dbi >= peak - 1.0
    category2 = float(np.nanmin(pattern.co_directivity_dbi[one_db_3d] - pattern.cross_directivity_dbi[one_db_3d])) if np.any(one_db_3d) else float("nan")

    extended = one_db_3d | (pattern.thetas_deg[None, :] <= 3.0)
    category3 = float(np.nanmin(pattern.co_directivity_dbi[extended] - pattern.cross_directivity_dbi[extended])) if np.any(extended) else float("nan")
    return category1, category2, category3


def _etsi_xpd_result(pattern: Pattern) -> dict[str, object]:
    requirements = etsi_xpd_requirements(pattern.frequency_hz / 1e9)
    measured = _xpd_values(pattern)
    passed: list[str] = []
    details: list[str] = []
    category_results: dict[str, dict[str, object]] = {}
    for index, (minimum, actual) in enumerate(zip(requirements, measured), start=1):
        if minimum is None:
            continue
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
                    f"{actual:.2f} dB, which is {-margin:.2f} dB below the required {minimum:.2f} dB."
                )
            else:
                note = f"ETSI XPD Category {index} fails because no valid cross-polar discrimination value could be calculated."
        category_results[str(index)] = {
            "status": "PASS" if ok else "FAIL",
            "measured_db": actual,
            "required_db": minimum,
            "margin_db": margin,
            "note": note,
        }
    return {
        "best_category": passed[-1] if passed else "None",
        "passed_categories": ", ".join(passed),
        "category1_xpd_db": measured[0],
        "category2_xpd_db": measured[1],
        "category3_xpd_db": measured[2],
        "detail": "; ".join(details) if details else "No XPD category is defined for this frequency",
        "category_results": category_results,
    }


def _suppression_result(angles: np.ndarray, actual_dbi: np.ndarray, requirements: tuple[float | None, ...], peak_dbi: float) -> dict[str, object]:
    margins: list[tuple[float, float, float, float]] = []
    for (low, high), minimum in zip(FCC_ANGLE_BINS, requirements):
        if minimum is None:
            continue
        selected = (angles >= low) & (angles <= high)
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


def _fcc_profile_result(pattern: Pattern, profile: FCCProfile) -> dict[str, object]:
    az_bw = plane_beamwidth(pattern, 0.0)
    el_bw = plane_beamwidth(pattern, 90.0)
    beam_pass = (
        profile.max_beamwidth_deg is not None
        and math.isfinite(az_bw)
        and math.isfinite(el_bw)
        and az_bw <= profile.max_beamwidth_deg
        and el_bw <= profile.max_beamwidth_deg
    )
    gain_pass = profile.min_gain_dbi is not None and pattern.max_directivity_dbi >= profile.min_gain_dbi
    beam_or_gain = bool(beam_pass or gain_pass)

    co_az = _plane_envelope(pattern.co_directivity_dbi, pattern.phis_deg, 0.0)
    cross_az = _plane_envelope(pattern.cross_directivity_dbi, pattern.phis_deg, 0.0)
    co_peak = float(np.nanmax(pattern.co_directivity_dbi))
    co_suppression = _suppression_result(pattern.thetas_deg, co_az, profile.suppression_db, co_peak)
    cross_suppression = None
    if profile.cross_suppression_db:
        cross_suppression = _suppression_result(pattern.thetas_deg, cross_az, profile.cross_suppression_db, co_peak)

    xpd_pass = True
    minimum_xpd = None
    if profile.xpd_min_db is not None:
        near = pattern.thetas_deg < 5.0
        xpd = pattern.co_directivity_dbi[:, near] - pattern.cross_directivity_dbi[:, near]
        minimum_xpd = float(np.nanmin(xpd)) if xpd.size else float("nan")
        xpd_pass = math.isfinite(minimum_xpd) and minimum_xpd >= profile.xpd_min_db
    passed = beam_or_gain and bool(co_suppression["passed"]) and bool(xpd_pass) and (
        cross_suppression is None or bool(cross_suppression["passed"])
    )
    return {
        "status": "PASS" if passed else "FAIL",
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
        "limiting_angle_deg": co_suppression.get("angle_deg"),
        "cross_suppression_pass": None if cross_suppression is None else bool(cross_suppression["passed"]),
        "cross_suppression_margin_db": None if cross_suppression is None else cross_suppression.get("margin_db"),
        "minimum_xpd_db": minimum_xpd,
        "required_xpd_db": profile.xpd_min_db,
        "xpd_pass": xpd_pass,
    }


def analyze_pattern(path: Path, port_label: str, pattern: Pattern) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
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
        result = _etsi_profile_result(pattern, profile)
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
        result = _fcc_profile_result(pattern, profile)
        row = {**common, "fcc_band": fcc_band, "standard": profile.standard, "note": profile.note, **result}
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
) -> dict[str, list[dict[str, object]]]:
    labels = {str(key).lower(): str(value).strip() for key, value in (port_labels or {}).items()}
    summary_rows: list[dict[str, object]] = []
    etsi_rows: list[dict[str, object]] = []
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
            summary, etsi, fcc = analyze_pattern(path, label, pattern)
            summary_rows.append(summary)
            etsi_rows.extend(etsi)
            fcc_rows.extend(fcc)
    if not summary_rows:
        raise ValueError("No far-field frequencies fall inside the selected compliance frequency window")
    return {
        "rollup": _build_rollup(summary_rows, etsi_rows, fcc_rows),
        "summary": summary_rows,
        "etsi": etsi_rows,
        "fcc": fcc_rows,
    }


def _build_rollup(
    summary_rows: list[dict[str, object]],
    etsi_rows: list[dict[str, object]],
    fcc_rows: list[dict[str, object]],
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
        margins = [
            float(value)
            for row in rows
            for value in (row.get("suppression_margin_db"), row.get("cross_suppression_margin_db"))
            if value is not None
        ]
        rollup.append(
            {
                **dict(zip(base_keys, key[: len(base_keys)])),
                "family": "FCC Part 101",
                "band": key[-2],
                "classification": f"Standard {key[-1]}",
                "status": "PASS" if all(row.get("status") == "PASS" for row in rows) else "FAIL",
                "frequencies_checked": len(rows),
                "frequency_min_ghz": min(float(row["frequency_ghz"]) for row in rows),
                "frequency_max_ghz": max(float(row["frequency_ghz"]) for row in rows),
                "worst_margin_db": min(margins) if margins else None,
            }
        )
    return rollup
