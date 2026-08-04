#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from compliance.engine import analyze_files, parse_omitted_angle_range
from compliance.standards import (
    ETSI_EDITION,
    ETSI_SECTOR_EDITION,
    ETSI_SECTOR_SOURCE_URL,
    ETSI_SOURCE_URL,
    FCC_EDITION,
    FCC_SOURCE_URL,
)
from pipeline.atomic import StageWorkspace
from pipeline.progress import emit_progress


def _clean_excel_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _write_table_sheet(workbook, title: str, rows: list[dict[str, object]]) -> None:
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    worksheet = workbook.create_sheet(title)
    if not rows:
        worksheet.append(["No applicable requirements or results"])
        return
    headers: list[str] = []
    for row in rows:
        for header in row:
            if not header.startswith("_") and header not in headers:
                headers.append(header)
    display_tokens = {
        "db": "dB",
        "dbi": "dBi",
        "etsi": "ETSI",
        "fcc": "FCC",
        "ghz": "GHz",
        "rpe": "RPE",
        "xpd": "XPD",
    }
    display_headers = [
        " ".join(display_tokens.get(token, token.capitalize()) for token in header.split("_"))
        for header in headers
    ]
    worksheet.append(display_headers)
    for row in rows:
        worksheet.append([_clean_excel_value(row.get(header)) for header in headers])
    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    worksheet.row_dimensions[1].height = 30
    worksheet.sheet_view.showGridLines = False
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    status_columns = {index + 1 for index, name in enumerate(headers) if name == "status" or name.endswith("_pass")}
    pass_fill = PatternFill("solid", fgColor="C6EFCE")
    fail_fill = PatternFill("solid", fgColor="FFC7CE")
    neutral_fill = PatternFill("solid", fgColor="E7E6E6")
    row_border = Border(bottom=Side(style="hair", color="D9E2F3"))
    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.border = row_border
            cell.alignment = Alignment(vertical="top")
        for index in status_columns:
            cell = row[index - 1]
            normalized = str(cell.value).strip().upper()
            if normalized in {"PASS", "TRUE"}:
                cell.fill = pass_fill
            elif normalized in {"FAIL", "FALSE"}:
                cell.fill = fail_fill
            elif normalized:
                cell.fill = neutral_fill
    for index, header in enumerate(headers, start=1):
        sample = [display_headers[index - 1]] + [str(row.get(header, "")) for row in rows[:200]]
        width = min(48, max(10, max(len(value) for value in sample) + 2))
        worksheet.column_dimensions[worksheet.cell(1, index).column_letter].width = width
        column_cells = worksheet.iter_cols(min_col=index, max_col=index, min_row=2)
        cells = next(column_cells)
        if header == "note":
            worksheet.column_dimensions[worksheet.cell(1, index).column_letter].width = 60
            for cell in cells:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                if cell.value:
                    wrapped_lines = max(1, math.ceil(len(str(cell.value)) / 72))
                    worksheet.row_dimensions[cell.row].height = min(120, max(30, 16 * wrapped_lines + 6))
        if header == "frequencies_checked":
            for cell in cells:
                cell.number_format = "0"
        elif header.endswith("_ghz"):
            for cell in cells:
                cell.number_format = "0.000"
        elif header.endswith(("_db", "_dbi", "_deg")):
            for cell in cells:
                cell.number_format = "0.00"
        elif header in {"measured_value", "limit_value"}:
            for cell in cells:
                cell.number_format = "0.00"


def write_workbook(
    output: Path,
    results: dict[str, list[dict[str, object]]],
    *,
    fmin_ghz: float,
    fmax_ghz: float,
    sector_width_deg: float = 0.0,
    sector_center_ghz: float = 0.0,
) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = Workbook()
    workbook.remove(workbook.active)
    _write_table_sheet(workbook, "Antenna Rollup", results["rollup"])
    _write_table_sheet(workbook, "Per-Frequency Results", results["per_frequency"])
    _write_table_sheet(workbook, "Summary", results["summary"])
    _write_table_sheet(workbook, "ETSI RPE Details", [*results["etsi"], *results.get("sector", [])])
    _write_table_sheet(workbook, "FCC Details", results["fcc"])

    methodology = workbook.create_sheet("Methodology")
    if fmin_ghz > 0 and fmax_ghz > 0:
        frequency_window = f"{fmin_ghz:g} to {fmax_ghz:g} GHz"
    elif fmin_ghz > 0:
        frequency_window = f"{fmin_ghz:g} GHz and above"
    elif fmax_ghz > 0:
        frequency_window = f"Up to {fmax_ghz:g} GHz"
    else:
        frequency_window = "All input frequencies"
    methodology_rows = [
        ("Generated UTC", datetime.now(timezone.utc).replace(microsecond=0).isoformat()),
        ("ETSI rules", ETSI_EDITION),
        ("ETSI source", ETSI_SOURCE_URL),
        ("ETSI sector rules", ETSI_SECTOR_EDITION),
        ("ETSI sector source", ETSI_SECTOR_SOURCE_URL),
        ("FCC rules", FCC_EDITION),
        ("FCC source", FCC_SOURCE_URL),
        ("Frequency window", frequency_window),
        ("Sample coverage", "Every available input frequency sample inside the selected frequency window is listed. Frequencies outside ETSI or FCC bands are retained as Not applicable."),
        ("Gain convention", "Directivity is used wherever ETSI or FCC refers to antenna gain, by explicit project decision."),
        ("Polarization convention", "Ludwig-3 linear co/cross components; H or V comes from the port label/filename, otherwise the main-beam field is used."),
        ("Plane convention", "CST phi=0/180 is azimuth and phi=90/270 is elevation. Opposite sides are evaluated independently."),
        ("ETSI RPE method", "Actual co/cross directivity is compared with every applicable piecewise-linear RPE mask over its published angular domain."),
        (
            "ETSI sector method",
            "Disabled (sector width is 0)."
            if sector_width_deg <= 0
            else (
                f"Linear single-beam sector RPEs with symmetric elevation are evaluated for a declared {sector_width_deg:g} degree sector. "
                "Co-polar and cross-polar results are expressed relative to the strongest co-polar azimuth sample inside the declared sector. "
                + (
                    f"Declared operating-range centre f0 is {sector_center_ghz:g} GHz."
                    if sector_center_ghz > 0
                    else "Automatic f0 uses the midpoint of the selected, bounded compliance frequency window."
                )
            ),
        ),
        ("ETSI XPD method", "Category 1 uses the azimuth 1 dB beamwidth; Category 2 uses the 3D 1 dB contour; Category 3 conservatively includes the 3 degree main-beam region."),
        ("FCC method", "Compliance requires beamwidth in both planes OR directivity, plus every applicable co-polar suppression bin and any cross-polar/XPD requirement."),
        ("Interpretation", "This is a simulation/data pre-compliance assessment. It is not an accredited measurement report or regulatory certification."),
        ("Coverage note", "ETSI range 8/9 class 4 is listed in the overview but no class 4 actual RPE corner-point figure is published in V2.2.1; it is not auto-assigned."),
    ]
    for key, value in methodology_rows:
        methodology.append([key, value])
    label_fill = PatternFill("solid", fgColor="D9EAF7")
    for row in methodology.iter_rows():
        row[0].font = Font(bold=True, color="1F1F1F")
        row[0].fill = label_fill
        row[1].alignment = Alignment(wrap_text=True, vertical="top")
    for row_number in (3, 5, 7):
        methodology.cell(row_number, 2).hyperlink = methodology.cell(row_number, 2).value
        methodology.cell(row_number, 2).style = "Hyperlink"
    methodology.sheet_view.showGridLines = False
    methodology.column_dimensions["A"].width = 24
    methodology.column_dimensions["B"].width = 120
    methodology.freeze_panes = "A2"
    workbook.save(output)


def _port_labels(raw: str) -> dict[str, str]:
    if not str(raw or "").strip():
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("--port-labels-json must contain a JSON object")
    return {str(key): str(value) for key, value in payload.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check CST far-field patterns against ETSI point-to-point/sector and FCC Part 101 antenna requirements.")
    parser.add_argument("output", type=Path, help="Output compliance workbook (.xlsx)")
    parser.add_argument("ffs", nargs="+", type=Path, help="CST broadband .ffs input files")
    parser.add_argument("--port-labels-json", default="", help="Optional filename-to-port-label JSON object")
    parser.add_argument("--fmin", type=float, default=0.0, help="Minimum frequency in GHz")
    parser.add_argument("--fmax", type=float, default=0.0, help="Maximum frequency in GHz")
    parser.add_argument(
        "--sector-width",
        type=float,
        default=0.0,
        metavar="DEGREES",
        help="Declared ETSI single-beam sector width (2 alpha); 0 disables sector evaluation",
    )
    parser.add_argument(
        "--sector-center",
        type=float,
        default=0.0,
        metavar="GHZ",
        help="Declared sector operating-range centre f0; 0 selects it automatically",
    )
    parser.add_argument(
        "--omit-angle-range",
        type=parse_omitted_angle_range,
        default=None,
        metavar="MIN-MAX",
        help="Inclusive boresight-angle range omitted from ETSI/FCC pattern comparisons",
    )
    args = parser.parse_args()
    if args.fmin > 0 and args.fmax > 0 and args.fmax <= args.fmin:
        parser.error("--fmax must be greater than --fmin")
    if args.sector_width != 0.0 and not 15.0 <= args.sector_width <= 180.0:
        parser.error("--sector-width must be 0 (disabled) or between 15 and 180 degrees")
    if args.sector_center < 0.0:
        parser.error("--sector-center must be 0 (automatic) or greater than 0 GHz")
    if args.sector_width > 0.0 and args.sector_center == 0.0 and not (args.fmin > 0.0 and args.fmax > 0.0):
        parser.error("sector evaluation requires --sector-center, or both --fmin and --fmax for automatic f0")
    if args.output.suffix.lower() != ".xlsx":
        parser.error("output must use the .xlsx extension")

    emit_progress("compliance", 1, 2, "Analyzing ETSI and FCC requirements")
    results = analyze_files(
        args.ffs,
        port_labels=_port_labels(args.port_labels_json),
        fmin_ghz=args.fmin,
        fmax_ghz=args.fmax,
        omitted_angle_range=args.omit_angle_range,
        sector_width_deg=args.sector_width,
        sector_center_ghz=args.sector_center,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with StageWorkspace(args.output.parent, "compliance") as stage:
        staged_output = stage.path(args.output.name)
        write_workbook(
            staged_output,
            results,
            fmin_ghz=args.fmin,
            fmax_ghz=args.fmax,
            sector_width_deg=args.sector_width,
            sector_center_ghz=args.sector_center,
        )
        emit_progress("compliance", 2, 2, f"Saving {args.output.name}")
        stage.publish([args.output.name])
    print(f"Wrote compliance workbook: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
