from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable

import numpy as np

from compliance.engine import (
    OmittedAngleRange,
    Pattern,
    _plane_envelope,
    _plane_sides,
    mask_limits,
    xpd_assessment_masks,
)
from compliance.standards import (
    ETSI_EDITION,
    ETSI_SECTOR_EDITION,
    FCC_ANGLE_BINS,
    FCC_EDITION,
    etsi_profiles_for_frequency,
    etsi_sector_profiles,
    fcc_profiles_for_frequency,
)


@dataclass(frozen=True)
class EvidenceCase:
    source_file: str
    source_path: str
    port_label: str
    polarization: str
    frequency_ghz: float
    family: str
    band: str
    classification: str
    status: str
    margin_db: float | None
    limiting_component: str
    location: str
    measured_value: float | None
    limit_value: float | None
    unit: str
    explanation: str
    pattern: Pattern
    row: dict[str, object]

    @property
    def key(self) -> tuple[object, ...]:
        return (
            self.source_file,
            self.source_path,
            self.port_label,
            self.polarization,
            self.family,
            self.band,
            self.classification,
        )


def _finite_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _location_from_row(row: dict[str, object], *, angle_key: str, phi_key: str = "", theta_key: str = "") -> str:
    angle = _finite_float(row.get(angle_key))
    if angle is not None:
        component = str(row.get("limiting_component", "")).strip()
        prefix = f"{component} at " if component else ""
        return f"{prefix}{angle:.2f} degrees from boresight"
    phi = _finite_float(row.get(phi_key)) if phi_key else None
    theta = _finite_float(row.get(theta_key)) if theta_key else None
    if phi is not None and theta is not None:
        return f"phi {phi:.2f} degrees, theta {theta:.2f} degrees"
    return ""


class EvidenceCollector:
    """Keep the minimum-margin frequency for every rollup classification."""

    def __init__(self) -> None:
        self._cases: dict[tuple[object, ...], EvidenceCase] = {}

    @staticmethod
    def _rank(case: EvidenceCase) -> tuple[int, float, float]:
        margin = _finite_float(case.margin_db)
        if margin is None:
            return 1, math.inf, case.frequency_ghz
        return 0, margin, case.frequency_ghz

    def _consider(self, case: EvidenceCase) -> None:
        previous = self._cases.get(case.key)
        if previous is None or self._rank(case) < self._rank(previous):
            self._cases[case.key] = case

    def observe(
        self,
        _path: Path,
        _port_label: str,
        pattern: Pattern,
        summary: dict[str, object],
        etsi_rows: list[dict[str, object]],
        sector_rows: list[dict[str, object]],
        fcc_rows: list[dict[str, object]],
    ) -> None:
        common = {
            "source_file": str(summary.get("source_file", "")),
            "source_path": str(summary.get("source_path", "")),
            "port_label": str(summary.get("port_label", "")),
            "polarization": str(summary.get("polarization", "")),
            "frequency_ghz": float(summary["frequency_ghz"]),
        }

        for row in etsi_rows:
            component = str(row.get("limiting_component", "") or "")
            angle = _finite_float(row.get("limiting_angle_deg"))
            self._consider(
                EvidenceCase(
                    **common,
                    family="ETSI RPE",
                    band=str(row.get("etsi_range", "")),
                    classification=f"Class {row.get('rpe_class', '')}",
                    status=str(row.get("status", "")),
                    margin_db=_finite_float(row.get("margin_db")),
                    limiting_component=component,
                    location="" if angle is None else f"{component} at {angle:.2f} degrees from boresight",
                    measured_value=_finite_float(row.get("actual_dbi")),
                    limit_value=_finite_float(row.get("limit_dbi")),
                    unit="dBi",
                    explanation=str(row.get("note", "") or ""),
                    pattern=pattern,
                    row=row,
                )
            )

        for row in sector_rows:
            component = str(row.get("limiting_component", "") or "")
            angle = _finite_float(row.get("limiting_angle_deg"))
            self._consider(
                EvidenceCase(
                    **common,
                    family="ETSI Sector RPE",
                    band=str(row.get("etsi_sector_range", "")),
                    classification=f"Class {row.get('sector_class', '')}",
                    status=str(row.get("status", "")),
                    margin_db=_finite_float(row.get("margin_db")),
                    limiting_component=component,
                    location="" if angle is None else f"{component} at {angle:.2f} degrees from boresight",
                    measured_value=_finite_float(row.get("actual_relative_db")),
                    limit_value=_finite_float(row.get("limit_relative_db")),
                    unit="dB relative to sector maximum",
                    explanation=str(row.get("note", "") or ""),
                    pattern=pattern,
                    row=row,
                )
            )

        categories = dict(summary.get("_etsi_xpd_categories", {}))
        for category, raw_result in categories.items():
            result = dict(raw_result)
            self._consider(
                EvidenceCase(
                    **common,
                    family="ETSI XPD",
                    band=str(summary.get("etsi_range", "")),
                    classification=f"Category {category}",
                    status=str(result.get("status", "")),
                    margin_db=_finite_float(result.get("margin_db")),
                    limiting_component="cross-polar discrimination",
                    location=_location_from_row(result, angle_key="", phi_key="phi_deg", theta_key="theta_deg"),
                    measured_value=_finite_float(result.get("measured_db")),
                    limit_value=_finite_float(result.get("required_db")),
                    unit="dB",
                    explanation=str(result.get("note", "") or ""),
                    pattern=pattern,
                    row=result,
                )
            )

        for row in fcc_rows:
            standard = str(row.get("standard", ""))
            classification = "Band requirement" if standard == "Band requirement" else f"Standard {standard}"
            self._consider(
                EvidenceCase(
                    **common,
                    family="FCC Part 101",
                    band=str(row.get("fcc_band", "")),
                    classification=classification,
                    status=str(row.get("status", "")),
                    margin_db=_finite_float(row.get("overall_margin_db")),
                    limiting_component=str(row.get("limiting_component", "") or ""),
                    location=_location_from_row(
                        row,
                        angle_key="overall_limiting_angle_deg",
                        phi_key="overall_limiting_phi_deg",
                        theta_key="overall_limiting_theta_deg",
                    ),
                    measured_value=_finite_float(row.get("limiting_measured_value")),
                    limit_value=_finite_float(row.get("limiting_limit_value")),
                    unit=str(row.get("limiting_unit", "") or ""),
                    explanation=str(row.get("failure_note", "") or ""),
                    pattern=pattern,
                    row=row,
                )
            )

    def ordered_cases(self, rollup_rows: Iterable[dict[str, object]]) -> list[EvidenceCase]:
        ordered: list[EvidenceCase] = []
        for row in rollup_rows:
            key = (
                row.get("source_file"),
                row.get("source_path"),
                row.get("port_label"),
                row.get("polarization"),
                row.get("family"),
                row.get("band"),
                row.get("classification"),
            )
            case = self._cases.get(key)
            if case is None:
                raise ValueError(f"No evidence case was collected for {key}")
            ordered.append(case)
        return ordered


def _included_angles(angles: np.ndarray, omitted_angle_range: OmittedAngleRange) -> np.ndarray:
    if omitted_angle_range is None:
        return np.ones_like(angles, dtype=bool)
    low, high = omitted_angle_range
    return ~((angles >= low - 1e-9) & (angles <= high + 1e-9))


def _profile_for_case(case: EvidenceCase):
    if case.family == "ETSI RPE":
        class_name = case.classification.removeprefix("Class ")
        return next(
            (profile for profile in etsi_profiles_for_frequency(case.frequency_ghz) if profile.class_name == class_name),
            None,
        )
    if case.family == "ETSI Sector RPE":
        class_name = case.classification.removeprefix("Class ")
        width = float(case.row.get("sector_width_deg", 0.0) or 0.0)
        center = float(case.row.get("sector_center_ghz", 0.0) or 0.0)
        return next(
            (
                profile
                for profile in etsi_sector_profiles(case.frequency_ghz, center, width)
                if profile.class_name == class_name
            ),
            None,
        )
    if case.family == "FCC Part 101":
        standard = case.classification.removeprefix("Standard ")
        return next(
            (profile for profile in fcc_profiles_for_frequency(case.frequency_ghz * 1000.0) if profile.standard == standard),
            None,
        )
    return None


def _plot_message(axis, message: str) -> None:
    axis.axis("off")
    axis.text(0.5, 0.5, message, ha="center", va="center", wrap=True, fontsize=11, color="#4B5563")


def _plot_etsi_rpe(axis, case: EvidenceCase, omitted_angle_range: OmittedAngleRange) -> None:
    profile = _profile_for_case(case)
    if profile is None or not case.limiting_component:
        _plot_message(axis, case.explanation or "No applicable mask curve is available for this result.")
        return
    component = case.limiting_component
    if component == "co-polar azimuth":
        actual = _plane_envelope(case.pattern.co_directivity_dbi, case.pattern.phis_deg, 0.0)
        points = profile.co_h_points if case.polarization == "H" and profile.co_h_points else profile.co_points
        if case.polarization == "V" and profile.co_v_points:
            points = profile.co_v_points
    elif component == "cross-polar azimuth":
        actual = _plane_envelope(case.pattern.cross_directivity_dbi, case.pattern.phis_deg, 0.0)
        points = profile.cross_points
    else:
        actual = _plane_envelope(case.pattern.co_directivity_dbi, case.pattern.phis_deg, 90.0)
        points = profile.elevation_points
    _plot_mask_overlay(axis, case, actual, points, omitted_angle_range, ylabel="Directivity (dBi)")


def _plot_etsi_sector(axis, case: EvidenceCase, omitted_angle_range: OmittedAngleRange) -> None:
    profile = _profile_for_case(case)
    if profile is None or not case.limiting_component:
        _plot_message(axis, case.explanation or "No applicable sector mask curve is available for this result.")
        return
    component = case.limiting_component
    if component == "co-polar azimuth":
        actual = _plane_envelope(case.pattern.co_directivity_dbi, case.pattern.phis_deg, 0.0)
        points = profile.co_points
    elif component == "cross-polar azimuth":
        actual = _plane_envelope(case.pattern.cross_directivity_dbi, case.pattern.phis_deg, 0.0)
        points = profile.cross_points
    elif component == "co-polar elevation":
        actual = _plane_envelope(case.pattern.co_directivity_dbi, case.pattern.phis_deg, 90.0)
        points = profile.elevation_co_points
    else:
        actual = _plane_envelope(case.pattern.cross_directivity_dbi, case.pattern.phis_deg, 90.0)
        points = profile.elevation_cross_points
    reference = _finite_float(case.row.get("sector_reference_directivity_dbi"))
    if reference is None:
        _plot_message(axis, case.explanation or "No usable sector reference could be calculated.")
        return
    _plot_mask_overlay(
        axis,
        case,
        actual - reference,
        points,
        omitted_angle_range,
        ylabel="Level relative to sector maximum (dB)",
    )


def _plot_mask_overlay(
    axis,
    case: EvidenceCase,
    actual: np.ndarray,
    points,
    omitted_angle_range: OmittedAngleRange,
    *,
    ylabel: str,
) -> None:
    angles = case.pattern.thetas_deg
    limits, valid = mask_limits(points, angles)
    evaluated = valid & _included_angles(angles, omitted_angle_range)
    axis.plot(angles[evaluated], actual[evaluated], color="#2563EB", linewidth=1.8, label="Antenna pattern")
    axis.plot(angles[evaluated], limits[evaluated], color="#DC2626", linewidth=1.8, label="Requirement mask")
    angle = _finite_float(case.row.get("limiting_angle_deg"))
    measured = case.measured_value
    if angle is not None and measured is not None:
        axis.scatter([angle], [measured], color="#111827", s=38, zorder=5, label="Limiting sample")
    axis.set_xlabel("Angle from boresight (degrees)")
    axis.set_ylabel(ylabel)
    axis.set_xlim(float(np.nanmin(angles)), float(np.nanmax(angles)))
    axis.grid(True, color="#D1D5DB", linewidth=0.6, alpha=0.8)
    axis.legend(loc="best", fontsize=8)


def _plot_xpd(axis, case: EvidenceCase, *, category: int | None = None, requirement: float | None = None) -> None:
    xpd = case.pattern.co_directivity_dbi - case.pattern.cross_directivity_dbi
    if category is None:
        usable = np.broadcast_to(case.pattern.thetas_deg[None, :] < 5.0, xpd.shape) & np.isfinite(xpd)
    else:
        usable = xpd_assessment_masks(case.pattern)[category - 1] & np.isfinite(xpd)
    if not np.any(usable):
        _plot_message(axis, "No usable XPD samples are available for this assessment region.")
        return
    phi_grid, theta_grid = np.meshgrid(case.pattern.phis_deg, case.pattern.thetas_deg, indexing="ij")
    values = xpd[usable]
    lower, upper = np.nanpercentile(values, [2.0, 98.0])
    if math.isclose(float(lower), float(upper)):
        upper = lower + 1.0
    scatter = axis.scatter(
        theta_grid[usable],
        phi_grid[usable],
        c=values,
        cmap="viridis",
        vmin=float(lower),
        vmax=float(upper),
        s=14,
        linewidths=0,
    )
    phi = _finite_float(case.row.get("phi_deg", case.row.get("overall_limiting_phi_deg")))
    theta = _finite_float(case.row.get("theta_deg", case.row.get("overall_limiting_theta_deg")))
    if phi is not None and theta is not None:
        axis.scatter([theta], [phi], color="#DC2626", marker="x", s=70, linewidths=2.0, label="Limiting sample")
        axis.legend(loc="best", fontsize=8)
    axis.set_xlabel("Theta (degrees)")
    axis.set_ylabel("Phi (degrees)")
    title = "Measured cross-polar discrimination"
    if requirement is not None:
        title += f" (requirement {requirement:.2f} dB)"
    axis.set_title(title, fontsize=10)
    colorbar = axis.figure.colorbar(scatter, ax=axis, pad=0.02)
    colorbar.set_label("XPD (dB)")
    axis.grid(True, color="#E5E7EB", linewidth=0.5)


def _fcc_requirement_curve(requirements, angles: np.ndarray) -> np.ndarray:
    curve = np.full_like(angles, np.nan, dtype=float)
    for (low, high), minimum in zip(FCC_ANGLE_BINS, requirements):
        if minimum is None:
            continue
        selected = (angles >= low) & (angles <= high)
        empty = selected & ~np.isfinite(curve)
        curve[empty] = float(minimum)
        overlap = selected & np.isfinite(curve)
        curve[overlap] = np.maximum(curve[overlap], float(minimum))
    return curve


def _plot_fcc(axis, case: EvidenceCase, omitted_angle_range: OmittedAngleRange) -> None:
    profile = _profile_for_case(case)
    component = case.limiting_component
    if profile is None or not component:
        _plot_message(axis, case.explanation or "No applicable FCC requirement plot is available.")
        return
    if component in {"co-polar suppression", "cross-polar suppression"}:
        is_cross = component.startswith("cross")
        values = case.pattern.cross_directivity_dbi if is_cross else case.pattern.co_directivity_dbi
        requirements = profile.cross_suppression_db if is_cross else profile.suppression_db
        actual_directivity = _plane_envelope(values, case.pattern.phis_deg, 0.0)
        peak = float(np.nanmax(case.pattern.co_directivity_dbi))
        actual = peak - actual_directivity
        required = _fcc_requirement_curve(requirements, case.pattern.thetas_deg)
        evaluated = np.isfinite(required) & _included_angles(case.pattern.thetas_deg, omitted_angle_range)
        axis.plot(case.pattern.thetas_deg[evaluated], actual[evaluated], color="#2563EB", label="Measured suppression")
        axis.plot(case.pattern.thetas_deg[evaluated], required[evaluated], color="#DC2626", label="Required suppression")
        angle = _finite_float(case.row.get("overall_limiting_angle_deg"))
        if angle is not None and case.measured_value is not None:
            axis.scatter([angle], [case.measured_value], color="#111827", s=38, label="Limiting sample", zorder=5)
        axis.set_xlabel("Angle from boresight (degrees)")
        axis.set_ylabel("Suppression (dB)")
        axis.grid(True, color="#D1D5DB", linewidth=0.6)
        axis.legend(loc="best", fontsize=8)
        return
    if component == "cross-polar discrimination":
        _plot_xpd(axis, case, requirement=profile.xpd_min_db)
        return
    if component == "directivity qualification":
        actual = case.pattern.max_directivity_dbi
        required = profile.min_gain_dbi
        if required is None:
            _plot_message(axis, "This FCC profile has no directivity requirement.")
            return
        axis.barh(["Directivity"], [actual], color="#2563EB", height=0.45, label="Measured")
        axis.axvline(required, color="#DC2626", linewidth=2.0, label=f"Required {required:.2f} dBi")
        axis.set_xlabel("Directivity used as gain (dBi)")
        axis.grid(True, axis="x", color="#D1D5DB", linewidth=0.6)
        axis.legend(loc="best", fontsize=8)
        return
    if component == "beamwidth qualification":
        peak = float(np.nanmax(case.pattern.co_directivity_dbi))
        for target, label, color in ((0.0, "Azimuth", "#2563EB"), (90.0, "Elevation", "#059669")):
            positive, negative = _plane_sides(case.pattern.co_directivity_dbi, case.pattern.phis_deg, target)
            signed_angles = np.concatenate((-case.pattern.thetas_deg[:0:-1], case.pattern.thetas_deg))
            normalized = np.concatenate((negative[:0:-1], positive)) - peak
            axis.plot(signed_angles, normalized, color=color, linewidth=1.6, label=label)
        axis.axhline(-3.0, color="#DC2626", linestyle="--", linewidth=1.4, label="-3 dB level")
        limit = profile.max_beamwidth_deg or 10.0
        span = max(10.0, min(45.0, float(limit) * 4.0))
        axis.set_xlim(-span, span)
        axis.set_ylim(-20.0, 1.0)
        axis.set_xlabel("Angle from boresight (degrees)")
        axis.set_ylabel("Co-polar level relative to peak (dB)")
        axis.grid(True, color="#D1D5DB", linewidth=0.6)
        axis.legend(loc="best", fontsize=8)
        return
    _plot_message(axis, f"No visual renderer is defined for limiting component: {component}.")


def _case_figure(case: EvidenceCase, omitted_angle_range: OmittedAngleRange):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=(10.2, 4.4), dpi=140, facecolor="white")
    FigureCanvasAgg(figure)
    axis = figure.add_subplot(111)
    if case.family == "ETSI RPE":
        _plot_etsi_rpe(axis, case, omitted_angle_range)
    elif case.family == "ETSI Sector RPE":
        _plot_etsi_sector(axis, case, omitted_angle_range)
    elif case.family == "ETSI XPD":
        category = int(case.classification.removeprefix("Category "))
        _plot_xpd(axis, case, category=category, requirement=case.limit_value)
    elif case.family == "FCC Part 101":
        _plot_fcc(axis, case, omitted_angle_range)
    else:
        _plot_message(axis, "No evidence plot is available for this result family.")
    axis.set_title(f"{case.family} - {case.classification} at {case.frequency_ghz:.3f} GHz", fontsize=11)
    figure.tight_layout(pad=1.0)
    return figure


def _ascii_text(value: object) -> str:
    return (
        str(value or "")
        .replace("\N{NON-BREAKING HYPHEN}", "-")
        .replace("\N{EN DASH}", "-")
        .replace("\N{EM DASH}", "-")
    )


def _draw_lines(canvas, text: str, x: float, y: float, width: float, *, font: str, size: float, leading: float) -> float:
    from reportlab.lib.utils import simpleSplit

    canvas.setFont(font, size)
    for line in simpleSplit(_ascii_text(text), font, size, width):
        canvas.drawString(x, y, line)
        y -= leading
    return y


def _frequency_window_text(fmin_ghz: float, fmax_ghz: float) -> str:
    if fmin_ghz > 0 and fmax_ghz > 0:
        return f"{fmin_ghz:g} to {fmax_ghz:g} GHz"
    if fmin_ghz > 0:
        return f"{fmin_ghz:g} GHz and above"
    if fmax_ghz > 0:
        return f"Up to {fmax_ghz:g} GHz"
    return "All input frequencies"


def _metric_text(case: EvidenceCase) -> str:
    pieces = [f"Status: {case.status}", f"Selected frequency: {case.frequency_ghz:.3f} GHz"]
    if case.margin_db is not None:
        pieces.append(f"Margin: {case.margin_db:.2f} dB")
    if case.measured_value is not None:
        measured = f"Measured: {case.measured_value:.2f}"
        if case.unit:
            measured += f" {case.unit}"
        pieces.append(measured)
    if case.limit_value is not None:
        limit = f"Limit: {case.limit_value:.2f}"
        if case.unit:
            limit += f" {case.unit}"
        pieces.append(limit)
    return " | ".join(pieces)


def _fcc_summary_text(case: EvidenceCase) -> str:
    if case.family != "FCC Part 101":
        return case.location
    row = case.row
    items = []
    azimuth = _finite_float(row.get("azimuth_beamwidth_deg"))
    elevation = _finite_float(row.get("elevation_beamwidth_deg"))
    beam_limit = _finite_float(row.get("max_beamwidth_deg"))
    if azimuth is not None and elevation is not None and beam_limit is not None:
        items.append(f"Beamwidth A/E {azimuth:.2f}/{elevation:.2f} degrees vs {beam_limit:.2f} degrees")
    directivity = _finite_float(row.get("directivity_dbi"))
    gain_limit = _finite_float(row.get("min_gain_dbi"))
    if directivity is not None and gain_limit is not None:
        items.append(f"Directivity {directivity:.2f} dBi vs {gain_limit:.2f} dBi")
    suppression = _finite_float(row.get("suppression_db"))
    required_suppression = _finite_float(row.get("required_suppression_db"))
    if suppression is not None and required_suppression is not None:
        items.append(f"Co-polar suppression {suppression:.2f} dB vs {required_suppression:.2f} dB")
    return " | ".join(items) or case.location


def write_evidence_pdf(
    output: Path,
    cases: Iterable[EvidenceCase],
    *,
    input_files: Iterable[Path],
    fmin_ghz: float,
    fmax_ghz: float,
    generated_at_utc: str,
    omitted_angle_range: OmittedAngleRange = None,
) -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as reportlab_canvas

    output.parent.mkdir(parents=True, exist_ok=True)
    selected_cases = list(cases)
    page_width, page_height = landscape(letter)
    pdf = reportlab_canvas.Canvas(str(output), pagesize=(page_width, page_height))
    pdf.setTitle("Antenna standards compliance evidence")
    pdf.setSubject("ETSI and FCC pre-compliance evidence plots")
    pdf.setCreator("Antenna Toolkit")

    pdf.setFillColor(colors.HexColor("#1F4E78"))
    pdf.rect(0, page_height - 92, page_width, 92, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawString(42, page_height - 54, "Standards Compliance Evidence")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(42, page_height - 76, "ETSI and FCC engineering pre-compliance assessment")
    pdf.setFillColor(colors.HexColor("#111827"))
    y = page_height - 135
    y = _draw_lines(pdf, f"Generated UTC: {generated_at_utc}", 48, y, 690, font="Helvetica-Bold", size=10, leading=15)
    y = _draw_lines(
        pdf,
        "Input antennas: " + ", ".join(Path(path).name for path in input_files),
        48,
        y - 4,
        690,
        font="Helvetica",
        size=10,
        leading=15,
    )
    y = _draw_lines(
        pdf,
        f"Frequency window: {_frequency_window_text(fmin_ghz, fmax_ghz)}",
        48,
        y - 4,
        690,
        font="Helvetica",
        size=10,
        leading=15,
    )
    y = _draw_lines(pdf, f"ETSI point-to-point: {ETSI_EDITION}", 48, y - 4, 690, font="Helvetica", size=10, leading=15)
    y = _draw_lines(pdf, f"ETSI sector: {ETSI_SECTOR_EDITION}", 48, y - 4, 690, font="Helvetica", size=10, leading=15)
    y = _draw_lines(pdf, f"FCC: {FCC_EDITION}", 48, y - 4, 690, font="Helvetica", size=10, leading=15)
    y = _draw_lines(
        pdf,
        "Each following page shows the minimum-margin frequency for one workbook Overview result. "
        "Directivity is used wherever a standard refers to antenna gain.",
        48,
        y - 18,
        690,
        font="Helvetica",
        size=10,
        leading=15,
    )
    _draw_lines(
        pdf,
        "This is a simulation/data pre-compliance assessment. It is not an accredited measurement report or regulatory certification.",
        48,
        y - 18,
        690,
        font="Helvetica-Oblique",
        size=10,
        leading=15,
    )
    if not selected_cases:
        _draw_lines(
            pdf,
            "No applicable rollup results were available, so no evidence pages were generated.",
            48,
            100,
            690,
            font="Helvetica-Bold",
            size=12,
            leading=16,
        )
    pdf.setFont("Helvetica", 8)
    pdf.drawRightString(page_width - 36, 24, "Page 1")
    pdf.showPage()

    status_colors = {
        "PASS": "#C6EFCE",
        "FAIL": "#FFC7CE",
        "NOT APPLICABLE": "#E7E6E6",
        "INDETERMINATE": "#FFE699",
    }
    total_pages = 1 + len(selected_cases)
    for page_number, case in enumerate(selected_cases, start=2):
        pdf.setFillColor(colors.HexColor("#1F4E78"))
        pdf.rect(0, page_height - 52, page_width, 52, fill=1, stroke=0)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(36, page_height - 32, _ascii_text(f"{case.family} - {case.classification}"))
        pdf.setFont("Helvetica", 9)
        pdf.drawString(
            36,
            page_height - 46,
            _ascii_text(
                f"{case.source_file} | Port {case.port_label or '-'} | {case.polarization} polarization | {case.band}"
            ),
        )
        pdf.setFillColor(colors.HexColor(status_colors.get(case.status, "#E7E6E6")))
        pdf.roundRect(page_width - 122, page_height - 39, 86, 22, 4, fill=1, stroke=0)
        pdf.setFillColor(colors.HexColor("#111827"))
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawCentredString(page_width - 79, page_height - 31, _ascii_text(case.status))

        _draw_lines(pdf, _metric_text(case), 36, page_height - 72, 720, font="Helvetica-Bold", size=9, leading=12)
        _draw_lines(pdf, _fcc_summary_text(case), 36, page_height - 88, 720, font="Helvetica", size=8.5, leading=11)
        explanation = case.explanation or "All evaluated requirements passed at this minimum-margin frequency."
        _draw_lines(pdf, explanation, 36, page_height - 106, 720, font="Helvetica", size=8.2, leading=10.5)

        figure = _case_figure(case, omitted_angle_range)
        image_buffer = BytesIO()
        FigureCanvasAgg(figure)
        figure.savefig(image_buffer, format="png", dpi=150, facecolor="white")
        image_buffer.seek(0)
        pdf.drawImage(ImageReader(image_buffer), 36, 66, width=720, height=350, preserveAspectRatio=True, anchor="c")
        figure.clear()

        pdf.setFillColor(colors.HexColor("#4B5563"))
        pdf.setFont("Helvetica", 8)
        pdf.drawString(36, 24, "Antenna Toolkit pre-compliance evidence")
        pdf.drawRightString(page_width - 36, 24, f"Page {page_number} of {total_pages}")
        pdf.showPage()

    pdf.save()
