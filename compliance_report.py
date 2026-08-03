#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from compliance.engine import analyze_files
from compliance.standards import (
    ETSI_EDITION,
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
    headers = [header for header in rows[0] if not header.startswith("_")]
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
                    worksheet.row_dimensions[cell.row].height = 48
        if header == "frequencies_checked":
            for cell in cells:
                cell.number_format = "0"
        elif header.endswith("_ghz"):
            for cell in cells:
                cell.number_format = "0.000"
        elif header.endswith(("_db", "_dbi", "_deg")):
            for cell in cells:
                cell.number_format = "0.00"


def write_workbook(output: Path, results: dict[str, list[dict[str, object]]], *, fmin_ghz: float, fmax_ghz: float) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = Workbook()
    workbook.remove(workbook.active)
    _write_table_sheet(workbook, "Antenna Rollup", results["rollup"])
    _write_table_sheet(workbook, "Summary", results["summary"])
    _write_table_sheet(workbook, "ETSI RPE Details", results["etsi"])
    _write_table_sheet(workbook, "FCC Details", results["fcc"])

    methodology = workbook.create_sheet("Methodology")
    methodology_rows = [
        ("Generated UTC", datetime.now(timezone.utc).replace(microsecond=0).isoformat()),
        ("ETSI rules", ETSI_EDITION),
        ("ETSI source", ETSI_SOURCE_URL),
        ("FCC rules", FCC_EDITION),
        ("FCC source", FCC_SOURCE_URL),
        ("Frequency window", f"{fmin_ghz:g} to {fmax_ghz:g} GHz" if fmin_ghz > 0 and fmax_ghz > 0 else "All input frequencies"),
        ("Gain convention", "Directivity is used wherever ETSI or FCC refers to antenna gain, by explicit project decision."),
        ("Polarization convention", "Ludwig-3 linear co/cross components; H or V comes from the port label/filename, otherwise the main-beam field is used."),
        ("Plane convention", "CST phi=0/180 is azimuth and phi=90/270 is elevation. Opposite sides are evaluated independently."),
        ("ETSI RPE method", "Actual co/cross directivity is compared with every applicable piecewise-linear RPE mask over its published angular domain."),
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
    for row_number in (3, 5):
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
    parser = argparse.ArgumentParser(description="Check CST far-field patterns against ETSI EN 302 217 and FCC Part 101 antenna requirements.")
    parser.add_argument("output", type=Path, help="Output compliance workbook (.xlsx)")
    parser.add_argument("ffs", nargs="+", type=Path, help="CST broadband .ffs input files")
    parser.add_argument("--port-labels-json", default="", help="Optional filename-to-port-label JSON object")
    parser.add_argument("--fmin", type=float, default=0.0, help="Minimum frequency in GHz")
    parser.add_argument("--fmax", type=float, default=0.0, help="Maximum frequency in GHz")
    args = parser.parse_args()
    if args.fmin > 0 and args.fmax > 0 and args.fmax <= args.fmin:
        parser.error("--fmax must be greater than --fmin")
    if args.output.suffix.lower() != ".xlsx":
        parser.error("output must use the .xlsx extension")

    emit_progress("compliance", 1, 2, "Analyzing ETSI and FCC requirements")
    results = analyze_files(
        args.ffs,
        port_labels=_port_labels(args.port_labels_json),
        fmin_ghz=args.fmin,
        fmax_ghz=args.fmax,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with StageWorkspace(args.output.parent, "compliance") as stage:
        staged_output = stage.path(args.output.name)
        write_workbook(staged_output, results, fmin_ghz=args.fmin, fmax_ghz=args.fmax)
        emit_progress("compliance", 2, 2, f"Saving {args.output.name}")
        stage.publish([args.output.name])
    print(f"Wrote compliance workbook: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
