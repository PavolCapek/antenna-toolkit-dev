from __future__ import annotations

import csv
import math
import subprocess
import sys
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

import beamwidth_xlsx
from adf_export import ADFSample, build_adf_document, sample_from_rows


def _read_document(document: str):
    headers, cuts = {}, []
    current = None
    for line in document.splitlines():
        cells = [cell.strip() for cell in next(csv.reader([line]))]
        if cells[0].endswith(":"):
            key, value = cells[0][:-1], ",".join(cells[1:])
            if key == "PATCUT":
                current = {"PATCUT": value, "points": []}
                cuts.append(current)
            elif key in {"POLARI", "NUPOIN", "FSTLST"}:
                current[key] = value
            else:
                headers[key] = value
        else:
            current["points"].append(tuple(float(cell) if cell else None for cell in cells))
    return headers, cuts


def _rows(polarization="H"):
    rows = []
    for phi in (0.0, 90.0, 180.0, 270.0):
        phi_rad = math.radians(phi)
        for theta in (0.0, 0.2, 1.0, 2.0, 90.0, 180.0):
            # Different levels on opposite half-planes must survive export.
            level = 0.0 if theta == 0.0 else -min(theta * (3 if phi == 0 else 6), 60)
            co = 10 ** (level / 20) * 1j
            cross = co * 10 ** (-30 / 20)
            x, y = (co, cross) if polarization == "H" else (cross, co)
            etheta = x * math.cos(phi_rad) + y * math.sin(phi_rad)
            ephi = -x * math.sin(phi_rad) + y * math.cos(phi_rad)
            rows.append((phi, theta, etheta, ephi))
    return rows


def _sample(source, frequency, polarization, angles, co, gain):
    return ADFSample(
        source=source, frequency_hz=frequency, polarization=polarization,
        angles_deg=np.asarray(angles, dtype=float),
        co_relative_db=np.asarray(co, dtype=float),
        cross_relative_db=np.asarray(co, dtype=float) - 30,
        gain_dbi=gain, azimuth_width_deg=3.2, elevation_width_deg=3.0,
    )


@pytest.mark.parametrize("polarization", ["H", "V"])
def test_native_cuts_preserve_asymmetry_subdegree_samples_and_cross_reference(polarization):
    sample = sample_from_rows(Path("unnamed.ffs"), 21.2e9, _rows(polarization), polarization)
    assert sample.polarization == polarization
    levels = dict(zip(sample.angles_deg, sample.co_relative_db))
    assert levels[-1] == pytest.approx(-6)
    assert levels[1] == pytest.approx(-3)
    assert levels[0.2] == pytest.approx(-0.6)
    assert sample.cross_relative_db - sample.co_relative_db == pytest.approx(-30)
    assert sample.angles_deg[[0, -1]].tolist() == [-180, 180]


def test_envelope_uses_worst_frequency_on_union_grid_and_directivity_headers():
    samples = [
        _sample("h", 21.2e9, "H", [-180, -0.2, 0, 0.2, 180], [-60, -3, 0, -5, -60], 35.6),
        _sample("h", 23.6e9, "H", [-180, -1, 0, 1, 180], [-70, -4, 0, -4, -70], 36.0),
        _sample("v", 21.2e9, "V", [-180, 0, 180], [-65, 0, -65], 35.2),
        _sample("v", 23.6e9, "V", [-180, 0, 180], [-67, 0, -67], 35.8),
    ]
    document = build_adf_document(samples, model="Example", manufacturer="Maker", data_date="20260930")
    headers, cuts = _read_document(document)
    assert headers["GUNITS"] == "DBI/DBR"
    assert float(headers["LWGAIN"]) == 35.2
    assert float(headers["MDGAIN"]) == 35.2  # nearest mid-band sample; conservative port gain
    assert float(headers["HGGAIN"]) == 35.8
    assert float(headers["LOWFRQ"]) == 21200
    assert float(headers["HGHFRQ"]) == 23600
    assert (headers["PATTYP"], headers["NOFREQ"], headers["PATFRE"]) == ("ENVELOPE", "-1.00", "")
    assert headers["NUMCUT"] == "4"
    assert [cut["POLARI"] for cut in cuts] == ["H/H", "H/V", "V/V", "V/H"]
    h_co = {angle: level for angle, level, _phase in cuts[0]["points"]}
    h_cross = {angle: level for angle, level, _phase in cuts[1]["points"]}
    assert h_co[-0.2] == -0.8  # second frequency dominates here
    assert h_co[-180] == -60  # first frequency dominates here
    assert h_cross[0] == -30
    for cut in cuts:
        assert cut["PATCUT"] == "AZ"
        assert int(cut["NUPOIN"]) == len(cut["points"])
        angles = [point[0] for point in cut["points"]]
        assert all(a < b for a, b in zip(angles, angles[1:]))
        assert cut["FSTLST"] == "-180.000,180.000"
        assert all(point[2] is None for point in cut["points"])
    assert headers["ENDFIL"] == "EOF"
    assert document.endswith("ENDFIL:,EOF\r\n")
    assert document.count("\n") == document.count("\r\n")


def test_missing_azimuth_planes_are_interpolated_periodically_without_copying_a_side():
    rows = []
    for phi, slope in ((45, 3), (135, 9), (225, 6), (315, 12)):
        radians = math.radians(phi)
        for theta in (0, 1, 180):
            co = 10 ** (-min(theta * slope, 60) / 20)
            cross = co * 0.1
            rows.append((phi, theta, complex(co * math.cos(radians) + cross * math.sin(radians)),
                         complex(-co * math.sin(radians) + cross * math.cos(radians))))
    sample = sample_from_rows(Path("antenna_H.ffs"), 5e9, rows)
    co = dict(zip(sample.angles_deg, sample.co_relative_db))
    cross = dict(zip(sample.angles_deg, sample.cross_relative_db))
    assert co[1] == pytest.approx(-7.5)
    assert co[-1] == pytest.approx(-7.5)
    assert cross[1] == pytest.approx(-27.5)
    assert math.isnan(sample.azimuth_width_deg)


def test_single_polarization_rounding_keeps_highest_level_and_metadata_cannot_add_records():
    sample = _sample("h", 5e9, "H", [-1, 0, 0.2001, 0.2002, 1], [-10, 0, -8, -2, -10], 12)
    headers, cuts = _read_document(build_adf_document(
        [sample], model="Example,\n!Injected", manufacturer="Manufacturer,\r\n!text"
    ))
    assert headers["NUMCUT"] == "2"
    assert headers["MODNUM"] == "Example Injected"
    assert headers["ANTMAN"] == "Manufacturer text"
    assert cuts[0]["points"][2] == (0.2, -2.0, None)


def _write_ffs(path: Path, polarization: str, frequencies=(5.0, 6.0)):
    lines = []
    for frequency in frequencies:
        lines.append(f"Frequency {frequency} GHz")
        for phi, theta, etheta, ephi in _rows(polarization):
            lines.append(f"{phi} {theta} {etheta.real} {etheta.imag} {ephi.real} {ephi.imag}")
    path.write_text("\n".join(lines), encoding="ascii")


@pytest.mark.parametrize("suffix", [".xlsx", ".csv"])
def test_beam_run_publishes_dual_polarization_adf_with_other_exports(tmp_path, suffix):
    horizontal, vertical = tmp_path / "port1.ffs", tmp_path / "port2.ffs"
    _write_ffs(horizontal, "H")
    _write_ffs(vertical, "V")
    output = tmp_path / f"Example{suffix}"
    radiation = tmp_path / beamwidth_xlsx.RADIATION_PATTERN_FILES_DIR
    stale = radiation / "adf" / "old.adf"
    stale.parent.mkdir(parents=True)
    stale.write_text("obsolete", encoding="ascii")
    argv = ["beamwidth_xlsx.py", str(output), str(horizontal), str(vertical),
            "--port-labels-json", '{"port1":"H","port2":"V"}',
            "--adf-manufacturer", "Maker", "--adf-model", "Antenna model"]
    if suffix == ".xlsx":
        completed = subprocess.run(
            [sys.executable, str(Path(beamwidth_xlsx.__file__).resolve()), *argv[1:]],
            capture_output=True, text=True, timeout=60,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
    else:
        with mock.patch.object(sys, "argv", argv):
            assert beamwidth_xlsx.main() == 0
    adf_path = radiation / "adf" / "Example.adf"
    raw = adf_path.read_bytes()
    headers, cuts = _read_document(raw.decode("ascii"))
    assert headers["ANTMAN"] == "Maker"
    assert headers["MODNUM"] == "Antenna model"
    assert len(cuts) == 4
    assert raw.count(b"\n") == raw.count(b"\r\n")
    assert not stale.exists()
    assert len(list((radiation / "ant_files").glob("*.ant"))) == 4
    assert len(list((radiation / "linkCalc").glob("*.ffs"))) == 4
    assert len(list((radiation / "netsim").iterdir())) == 2
    rows = beamwidth_xlsx.compute_for_file(horizontal, 1, 8)[0]
    assert float(headers["MDGAIN"]) == pytest.approx(rows[0][17], abs=0.01)


def test_adf_write_failure_keeps_previously_published_outputs(tmp_path):
    source, output = tmp_path / "sample_H.ffs", tmp_path / "Example.xlsx"
    _write_ffs(source, "H")
    output.write_bytes(b"previous workbook")
    adf = tmp_path / beamwidth_xlsx.RADIATION_PATTERN_FILES_DIR / "adf" / "Example.adf"
    adf.parent.mkdir(parents=True)
    adf.write_bytes(b"previous ADF")
    with (
        mock.patch.object(sys, "argv", ["beamwidth_xlsx.py", str(output), str(source)]),
        mock.patch.object(beamwidth_xlsx, "write_adf_file", side_effect=OSError("write failed")),
    ):
        with pytest.raises(OSError, match="write failed"):
            beamwidth_xlsx.main()
    assert output.read_bytes() == b"previous workbook"
    assert adf.read_bytes() == b"previous ADF"
