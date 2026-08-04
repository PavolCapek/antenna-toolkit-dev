from __future__ import annotations

import math
from dataclasses import dataclass


ETSI_EDITION = "ETSI EN 302 217-4 V2.2.1 (2025-07)"
ETSI_SOURCE_URL = (
    "https://www.etsi.org/deliver/etsi_EN/302200_302299/30221704/"
    "02.02.01_60/en_30221704v020201p.pdf"
)
ETSI_SECTOR_EDITION = "ETSI EN 302 326-3 V2.1.1 (2021-09)"
ETSI_SECTOR_SOURCE_URL = (
    "https://www.etsi.org/deliver/etsi_en/302300_302399/30232603/"
    "02.01.01_60/en_30232603v020101p.pdf"
)
FCC_EDITION = "47 CFR 101.115 (eCFR snapshot 2026-07-27)"
FCC_SOURCE_URL = (
    "https://www.ecfr.gov/current/title-47/chapter-I/subchapter-D/"
    "part-101/subpart-C/section-101.115"
)

Point = tuple[float, float]


@dataclass(frozen=True)
class ETSIRPEProfile:
    range_key: str
    frequency_min_ghz: float
    frequency_max_ghz: float
    class_name: str
    co_points: tuple[Point, ...]
    cross_points: tuple[Point, ...]
    co_h_points: tuple[Point, ...] = ()
    co_v_points: tuple[Point, ...] = ()
    elevation_points: tuple[Point, ...] = ()
    polarization_restriction: str = ""


@dataclass(frozen=True)
class FCCProfile:
    frequency_min_mhz: float
    frequency_max_mhz: float
    standard: str
    max_beamwidth_deg: float | None
    min_gain_dbi: float | None
    suppression_db: tuple[float | None, ...]
    cross_suppression_db: tuple[float | None, ...] = ()
    xpd_min_db: float | None = None
    note: str = ""


@dataclass(frozen=True)
class ETSISectorProfile:
    range_key: str
    frequency_min_ghz: float
    frequency_max_ghz: float
    class_name: str
    co_points: tuple[Point, ...]
    cross_points: tuple[Point, ...]
    elevation_co_points: tuple[Point, ...]
    elevation_cross_points: tuple[Point, ...]
    sector_width_min_deg: float = 15.0
    sector_width_max_deg: float = 180.0


FCC_ANGLE_BINS: tuple[tuple[float, float], ...] = (
    (5.0, 10.0),
    (10.0, 15.0),
    (15.0, 20.0),
    (20.0, 30.0),
    (30.0, 100.0),
    (100.0, 140.0),
    (140.0, 180.0),
)


def _r(
    range_key: str,
    fmin: float,
    fmax: float,
    class_name: str,
    co: tuple[Point, ...],
    cross: tuple[Point, ...],
    **kwargs,
) -> ETSIRPEProfile:
    return ETSIRPEProfile(range_key, fmin, fmax, class_name, co, cross, **kwargs)


# Corner points transcribed from figures 5 through 44. Repeated angles encode
# deliberate vertical steps in the published masks and are preserved here.
ETSI_RPE_PROFILES: tuple[ETSIRPEProfile, ...] = (
    _r("0 (1-3 GHz)", 1, 3, "1A", ((20, 16), (50, 6), (100, 6), (140, -5), (180, -5)), ((20, 0), (30, 0), (50, -6), (180, -6))),
    _r("0 (1-3 GHz)", 1, 3, "1B", ((15, 20), (40, 6), (100, 6), (140, -5), (180, -5)), ((20, 0), (30, 0), (50, -6), (180, -6))),
    _r("0 (1-3 GHz)", 1, 3, "1C", ((20, 12), (40, 4), (110, -7), (180, -7)), ((20, 0), (30, 0), (100, -10), (180, -10)), elevation_points=((20, 15), (60, 1), (90, -4))),
    _r("0 (1-3 GHz)", 1, 3, "2", ((20, 12), (40, 4), (90, 4), (120, -12), (180, -12)), ((20, 0), (30, 0), (100, -15), (180, -15))),
    _r("0 (1-3 GHz)", 1, 3, "3", ((10, 18), (30, 3), (80, 2), (110, -18), (180, -18)), ((20, 0), (30, 0), (100, -20), (180, -20))),
    _r("1 (3-14 GHz)", 3, 14, "1", ((5, 26), (10, 20), (20, 12), (50, 5), (110, 5), (140, -8), (170, -8), (170, -6), (180, -6)), ((5, 10), (8, 7), (15, 5), (30, -2), (70, -2), (100, -5), (120, -8), (180, -8))),
    _r("1 (3-14 GHz)", 3, 14, "2", ((5, 26), (10, 20), (20, 12), (50, 5), (65, 2), (80, 2), (105, -20), (180, -20)), ((5, 10), (10, 5), (15, 5), (30, -3), (70, -3), (100, -20), (180, -20))),
    _r("1 (3-14 GHz)", 3, 14, "3", ((5, 20), (20, 8), (70, -5), (100, -25), (180, -25)), ((5, 5), (10, 0), (13, -5), (20, -5), (40, -6), (50, -10), (75, -15), (95, -25), (180, -25))),
    _r("1 (3-14 GHz)", 3, 14, "4", ((5, 16), (10, 5), (20, -7), (50, -18), (70, -20), (85, -24), (105, -30), (180, -30)), ((5, 5), (10, 0), (13, -5), (20, -15), (30, -20), (40, -24), (45, -24), (70, -25), (85, -25), (105, -33), (180, -33))),
    _r("2 (14-20 GHz)", 14, 20, "1", ((5, 25), (15, 15), (25, 10), (110, 4), (140, -8), (170, -8), (170, -6), (180, -6)), ((5, 10), (15, 3), (20, 3), (30, 0), (45, 0), (55, -3), (90, -3), (120, -8), (180, -8))),
    _r("2 (14-20 GHz)", 14, 20, "2", ((5, 25), (15, 13), (20, 10), (70, 0), (80, -8), (100, -18), (160, -20), (180, -20)), ((5, 10), (7, 7), (15, 2), (20, 2), (25, -1), (45, -1), (70, -10), (90, -20), (180, -20))),
    _r("2 (14-20 GHz)", 14, 20, "3", ((5, 18), (10, 9), (25, 2), (60, -4), (95, -27), (180, -27)), ((5, 5), (10, 1), (30, -13), (50, -15), (85, -25), (95, -31), (180, -31))),
    _r("2 (14-20 GHz)", 14, 20, "4", ((5, 18), (10, 9), (20, -4), (40, -13), (80, -25), (100, -30), (180, -30)), ((5, -3), (13, -7), (20, -15), (30, -20), (65, -22), (95, -31), (180, -31))),
    _r("3 (20-24 GHz)", 20, 24, "1", ((5, 20), (10, 12), (20, 12), (80, 2), (100, -7), (180, -10)), ((5, 0), (10, -5), (20, -5), (100, -7), (180, -10))),
    _r("3 (20-24 GHz)", 20, 24, "2", ((5, 20), (10, 12), (20, 10), (50, 2), (70, 0), (100, -20), (180, -20)), ((5, -5), (20, -5), (35, -7), (100, -25), (180, -25))),
    _r("3 (20-24 GHz)", 20, 24, "3", ((5, 20), (10, 12), (20, 7), (40, 3), (50, 0), (100, -23), (180, -23)), ((5, -5), (10, -5), (15, -8), (35, -8), (100, -30), (180, -30))),
    _r("3 (20-24 GHz)", 20, 24, "4", ((5, 18), (10, 9), (20, -4), (40, -13), (80, -25), (100, -30), (180, -30)), ((5, -5), (13, -7), (20, -15), (30, -20), (65, -22), (95, -31), (180, -31))),
    _r("4 (24-30 GHz)", 24, 30, "1", ((5, 20), (10, 15), (50, 5), (80, 2), (100, -7), (180, -10)), ((5, 0), (20, 0), (100, -7), (180, -10))),
    _r("4 (24-30 GHz)", 24, 30, "2", ((5, 23), (12, 13), (30, 4), (70, -1), (100, -18), (180, -18)), ((5, 2), (15, 2), (25, -4), (80, -20), (180, -20))),
    _r("4 (24-30 GHz)", 24, 30, "3", ((5, 20), (20, 5), (55, 0), (100, -23), (180, -25)), ((5, -3), (20, -3), (80, -25), (180, -25))),
    _r("4 (24-30 GHz)", 24, 30, "4", ((5, 18), (10, 9), (20, -4), (40, -13), (80, -25), (100, -30), (180, -30)), ((5, -3), (13, -7), (20, -15), (30, -20), (65, -22), (95, -31), (180, -31))),
    _r("5 (30-47 GHz)", 30, 47, "1", ((5, 25), (10, 17), (15, 14), (40, 8), (110, 2), (125, -10), (175, -10), (180, -7)), ((5, 5), (15, 5), (20, 0), (80, -5), (95, -10), (180, -10))),
    _r("5 (30-47 GHz)", 30, 47, "2", ((5, 25), (10, 17), (15, 13), (25, 8), (30, 4), (70, -4), (90, -17), (180, -17)), ((5, 5), (15, 5), (20, 0), (25, -4), (55, -6), (75, -18), (180, -18))),
    _r("5 (30-47 GHz)", 30, 47, "3A", ((5, 16), (10, 9), (15, 5), (20, 0), (40, -7), (50, -8), (65, -10), (75, -10), (90, -17), (180, -17)), ((5, 5), (15, 5), (20, 0), (40, -7), (50, -8), (65, -10), (75, -10), (90, -17), (180, -17)), polarization_restriction="V"),
    _r("5 (30-47 GHz)", 30, 47, "3B", (), ((5, -2), (8, -5), (12, -10), (20, -10), (30, -12), (50, -15), (70, -17), (180, -17)), co_h_points=((5, 20), (10, 11), (15, 6), (20, 0), (50, -1), (70, -4), (90, -17), (180, -17)), co_v_points=((5, 16), (10, 9), (15, 5), (20, 0), (40, -7), (50, -8), (65, -10), (75, -10), (90, -17), (180, -17))),
    _r("5 (30-47 GHz)", 30, 47, "3C", (), ((5, -4), (9, -8), (10, -10), (15, -10), (20, -10), (30, -10), (40, -10), (45, -13), (55, -13), (70, -18), (180, -18)), co_h_points=((5, 20), (10, 11), (15, 6), (20, 0), (50, -1), (70, -4), (90, -17), (180, -17)), co_v_points=((5, 12), (9, 9), (10, 6), (15, 2), (20, 0), (30, -4), (40, -7), (45, -9), (60, -14), (70, -18), (180, -18))),
    _r("5 (30-47 GHz)", 30, 47, "4", ((5, 12), (10, 5), (20, -4), (40, -13), (90, -24), (180, -24)), ((5, -4), (10, -10), (30, -20), (70, -22), (100, -27), (180, -27))),
    _r("6 (47-71 GHz)", 47, 71, "1", ((5, 25), (10, 17), (15, 14), (40, 8), (110, 2), (125, -10), (175, -10), (180, -7)), ((5, 5), (15, 5), (20, 0), (80, -5), (95, -10), (180, -10))),
    _r("6 (47-71 GHz)", 47, 71, "2", ((5, 25), (10, 17), (15, 14), (40, 2), (70, -2), (90, -18), (180, -18)), ((5, 5), (15, 5), (20, 0), (60, -8), (75, -18), (180, -18))),
    _r("6 (47-71 GHz)", 47, 71, "3A", ((5, 16), (10, 9), (15, 5), (20, 0), (40, -7), (50, -8), (65, -10), (75, -10), (90, -17), (180, -17)), ((5, 5), (15, 5), (20, 0), (40, -7), (50, -8), (65, -10), (75, -10), (90, -17), (180, -17)), polarization_restriction="V"),
    _r("6 (47-71 GHz)", 47, 71, "3B", (), ((5, -4), (10, -8), (40, -8), (65, -10), (75, -18), (180, -18)), co_h_points=((5, 16), (10, 6), (20, 1), (75, -10), (90, -17), (180, -17)), co_v_points=((5, 16), (10, 9), (15, 5), (20, 0), (40, -7), (50, -8), (65, -10), (75, -10), (90, -17), (180, -17))),
    _r("7 (71-86 GHz)", 71, 86.0000001, "1", ((5, 25), (10, 17), (15, 14), (40, 3), (70, 0), (100, 0), (100, -5), (180, -5)), ((5, 5), (15, 5), (20, 0), (80, -5), (180, -5))),
    _r("7 (71-86 GHz)", 71, 86.0000001, "2", ((5, 25), (15, 10), (20, 7), (40, 2), (70, -2), (88.75, -7), (100, -7), (100, -10), (180, -10)), ((5, 5), (15, 5), (20, 0), (60, -8), (100, -10), (180, -10))),
    _r("7 (71-86 GHz)", 71, 86.0000001, "3", ((5, 16), (10, 9), (20, 1), (50, -1), (70, -4), (90, -17), (180, -17)), ((5, 3), (15, 3), (20, -2), (60, -10), (90, -17), (180, -17))),
    _r("7 (71-86 GHz)", 71, 86.0000001, "4", ((5, 12), (10, 5), (20, -4), (90, -21), (180, -21)), ((5, 0), (15, 0), (20, -4), (90, -21), (180, -21))),
    _r("8 (92-114.25 GHz)", 92, 114.2500001, "2", ((5, 25), (15, 10), (20, 7), (40, 2), (70, -2), (88.75, -7), (100, -7), (100, -10), (180, -10)), ((5, 5), (15, 5), (20, 0), (60, -8), (100, -10), (180, -10))),
    _r("8 (92-114.25 GHz)", 92, 114.2500001, "3", ((5, 16), (10, 9), (20, 1), (50, -1), (70, -4), (90, -17), (180, -17)), ((5, 3), (15, 3), (20, -2), (60, -10), (90, -17), (180, -17))),
    _r("9 (130-175.8 GHz)", 130, 175.8000001, "2", ((5, 25), (15, 10), (20, 7), (40, 2), (70, -2), (88.75, -7), (100, -7), (100, -10), (180, -10)), ((5, 5), (15, 5), (20, 0), (60, -8), (100, -10), (180, -10))),
    _r("9 (130-175.8 GHz)", 130, 175.8000001, "3", ((5, 16), (10, 9), (20, 1), (50, -1), (70, -4), (90, -17), (180, -17)), ((5, 3), (15, 3), (20, -2), (60, -10), (90, -17), (180, -17))),
)


def etsi_profiles_for_frequency(frequency_ghz: float) -> tuple[ETSIRPEProfile, ...]:
    return tuple(
        profile
        for profile in ETSI_RPE_PROFILES
        if profile.frequency_min_ghz <= frequency_ghz < profile.frequency_max_ghz
    )


def _floor(value: float) -> float:
    """Apply the lower-integer rounding required by EN 302 326-3 clause 4.4.2.1."""
    return float(math.floor(value + 1e-12))


def _sector_profile(
    range_key: str,
    fmin: float,
    fmax: float,
    class_name: str,
    co: tuple[Point, ...],
    cross: tuple[Point, ...],
    elevation_base: tuple[Point, ...],
    *,
    sector_width_max_deg: float = 180.0,
) -> ETSISectorProfile:
    co_180 = next(value for angle, value in reversed(co) if angle <= 180.0 + 1e-9)
    cross_0 = next(value for angle, value in cross if angle >= -1e-9)
    cross_180 = next(value for angle, value in reversed(cross) if angle <= 180.0 + 1e-9)
    elevation_co = (*elevation_base, (180.0, co_180))
    elevation_cross = ((0.0, cross_0), (180.0, cross_180))
    return ETSISectorProfile(
        range_key,
        fmin,
        fmax,
        class_name,
        co,
        cross,
        elevation_co,
        elevation_cross,
        sector_width_max_deg=sector_width_max_deg,
    )


def etsi_sector_profiles(
    frequency_ghz: float,
    center_frequency_ghz: float,
    sector_width_deg: float,
) -> tuple[ETSISectorProfile, ...]:
    """Return linear, single-beam sector RPE profiles from EN 302 326-3 tables 13, 15 and 17-19."""
    f0 = float(center_frequency_ghz)
    alpha = float(sector_width_deg) / 2.0
    def a(offset: float) -> float:
        return _floor(alpha + offset)

    twice_a = _floor(2.0 * alpha)

    if 1.0 <= frequency_ghz < 3.0:
        final = _floor(-1.4 * f0 - 20.0)
        co = (
            (0.0, 0.0),
            (a(5.0), 0.0),
            (a(105.0 - 7.0 * f0), _floor(-0.7 * f0 - 16.0)),
            (_floor(184.4 - 4.4 * f0), final),
            (180.0, final),
        )
        cross = (
            (0.0, -20.0),
            (a(57.5 - 5.0 * f0), -20.0),
            (a(87.5 - 5.0 * f0), final),
            (180.0, final),
        )
        return (
            _sector_profile(
                "1-3 GHz",
                1.0,
                3.0,
                "SS",
                co,
                cross,
                ((0.0, 0.0), (12.0, 0.0), (12.0, -3.0), (14.0, -5.0), (20.0, -5.0), (60.0, -13.0), (60.0, -18.0), (90.0, -18.0)),
            ),
        )

    if 3.0 <= frequency_ghz <= 11.0:
        elevation = ((0.0, 0.0), (10.0, 0.0), (25.0, -15.0), (90.0, -19.0))
        ss1_co = ((0.0, 0.0), (a(5.0), 0.0), (160.0, -20.0), (180.0, -20.0))
        ss1_cross = ((0.0, -12.0), (a(5.0), -15.0), (160.0, -20.0), (180.0, -20.0))
        ss2_co = (
            (0.0, 0.0),
            (a(5.0), 0.0),
            (a(105.0 - 7.0 * f0), -20.0),
            (_floor(195.0 - 7.0 * f0), -20.0),
            (180.0, -25.0),
        )
        ss2_cross = (
            (0.0, -20.0),
            (a(57.5 - 5.0 * f0), -20.0),
            (a(87.5 - 5.0 * f0), -25.0),
            (_floor(186.0 - 4.4 * f0), -25.0),
            (180.0, -25.0),
        )
        ss3_cross_limit = _floor(-1.4 * f0 - 20.0)
        ss3_cross_start = _floor(-0.7 * f0 - 17.5)
        ss3_co = (
            (0.0, 0.0),
            (a(20.0 - 1.4 * f0), 0.0),
            (a(75.0 - 4.3 * f0), -23.0),
            (_floor(165.0 - 4.3 * f0), -23.0),
            (150.0, ss3_cross_limit),
            (180.0, ss3_cross_limit),
        )
        ss3_cross = (
            (0.0, ss3_cross_start),
            (a(20.0 - 1.4 * f0), ss3_cross_start),
            (a(75.0 - 4.3 * f0), ss3_cross_limit),
            (150.0, ss3_cross_limit),
            (180.0, ss3_cross_limit),
        )
        return (
            _sector_profile("3-11 GHz", 3.0, 11.0, "SS1", ss1_co, ss1_cross, elevation),
            _sector_profile("3-11 GHz", 3.0, 11.0, "SS2", ss2_co, ss2_cross, elevation),
            _sector_profile("3-11 GHz", 3.0, 11.0, "SS3", ss3_co, ss3_cross, elevation),
        )

    if 24.25 <= frequency_ghz <= 40.5:
        elevation = (
            ((0.0, 0.0), (6.0, 0.0), (15.0, -15.0), (90.0, -25.0))
            if frequency_ghz <= 30.0
            else ((0.0, 0.0), (6.0, 0.0), (10.0, -10.0), (90.0, -20.0))
        )
        profiles = (
            ("SS1", ((0.0, 0.0), (a(5.0), 0.0), (_floor(2.0 * alpha + 5.0), -10.0), (135.0, -12.0), (155.0, -15.0), (180.0, -25.0)), ((0.0, -20.0), (_floor(alpha), -20.0), (a(15.0), -25.0), (180.0, -25.0)), 130.0),
            ("SS2a", ((0.0, 0.0), (a(5.0), 0.0), (twice_a, -20.0), (180.0, -30.0)), ((0.0, -20.0), (_floor(alpha), -20.0), (twice_a, -25.0), (180.0, -30.0)), 180.0),
            ("SS2b", ((0.0, 0.0), (a(5.0), 0.0), (twice_a, -20.0), (180.0, -30.0)), ((0.0, -25.0), (_floor(alpha), -25.0), (a(5.0), -25.0), (twice_a, -30.0), (180.0, -30.0)), 180.0),
            ("SS3", ((0.0, 0.0), (a(5.0), 0.0), (a(30.0), -20.0), (110.0, -23.0), (140.0, -35.0), (180.0, -35.0)), ((0.0, -25.0), (_floor(alpha), -25.0), (a(30.0), -30.0), (105.0, -30.0), (140.0, -35.0), (180.0, -35.0)), 180.0),
            ("SS4", ((0.0, 0.0), (a(5.0), 0.0), (a(15.0), -20.0), (110.0, -23.0), (140.0, -35.0), (180.0, -35.0)), ((0.0, -25.0), (_floor(alpha), -25.0), (a(15.0), -30.0), (105.0, -30.0), (140.0, -35.0), (180.0, -35.0)), 180.0),
        )
        return tuple(
            _sector_profile("24.25-40.5 GHz", 24.25, 40.5, name, co, cross, elevation, sector_width_max_deg=max_width)
            for name, co, cross, max_width in profiles
        )

    if 40.5 < frequency_ghz <= 43.5:
        elevation = ((0.0, 0.0), (6.0, 0.0), (15.0, -15.0), (90.0, -25.0))
        profiles = (
            ("SS1", ((0.0, 0.0), (a(5.0), 0.0), (_floor(2.0 * alpha + 5.0), -10.0), (135.0, -12.0), (155.0, -15.0), (180.0, -25.0)), ((0.0, -22.0), (_floor(alpha), -22.0), (a(15.0), -25.0), (180.0, -25.0)), 130.0),
            ("SS2", ((0.0, 0.0), (a(5.0), 0.0), (a(15.0), -20.0), (110.0, -23.0), (140.0, -35.0), (180.0, -35.0)), ((0.0, -25.0), (_floor(alpha), -25.0), (a(15.0), -30.0), (105.0, -30.0), (140.0, -35.0), (180.0, -35.0)), 180.0),
            ("SS3", ((0.0, 0.0), (a(5.0), 0.0), (twice_a, -20.0), (180.0, -30.0)), ((0.0, -25.0), (_floor(alpha), -25.0), (twice_a, -30.0), (180.0, -30.0)), 180.0),
        )
        return tuple(
            _sector_profile("40.5-43.5 GHz", 40.5, 43.5, name, co, cross, elevation, sector_width_max_deg=max_width)
            for name, co, cross, max_width in profiles
        )
    return ()


def _f(
    fmin: float,
    fmax: float,
    standard: str,
    beam: float | None,
    gain: float | None,
    suppression: tuple[float | None, ...],
    **kwargs,
) -> FCCProfile:
    return FCCProfile(fmin, fmax, standard, beam, gain, suppression, **kwargs)


FCC_PROFILES: tuple[FCCProfile, ...] = (
    _f(932.5, 935, "A", 14.0, None, (None, None, 6, 11, 14, 17, 20)),
    _f(932.5, 935, "B", 20.0, None, (None, None, None, 6, 10, 13, 15)),
    _f(941.5, 944, "A", 14.0, None, (None, None, 6, 11, 14, 17, 20)),
    _f(941.5, 944, "B", 20.0, None, (None, None, None, 6, 10, 13, 15)),
    _f(952, 960, "A", 14.0, None, (None, None, 6, 11, 14, 17, 20)),
    _f(952, 960, "B", 20.0, None, (None, None, None, 6, 10, 13, 15)),
    _f(1850, 2500, "A", 5.0, None, (12, 18, 22, 25, 29, 33, 39)),
    _f(1850, 2500, "B", 8.0, None, (5, 18, 20, 20, 25, 28, 36)),
    _f(3700, 4200, "A", 2.7, 36, (23, 29, 33, 36, 42, 55, 55)),
    _f(3700, 4200, "B1", 2.7, 36, (20, 24, 28, 32, 32, 32, 32)),
    _f(3700, 4200, "B2", 2.2, 38, (21, 25, 29, 32, 35, 39, 45)),
    _f(5925, 6425, "A", 2.2, 38, (25, 29, 33, 36, 42, 55, 55)),
    _f(5925, 6425, "B1", 2.2, 38, (21, 25, 29, 32, 35, 39, 45)),
    _f(5925, 6425, "B2", 4.1, 32, (15, 20, 23, 28, 29, 60, 60)),
    _f(6525, 6875, "A", 2.2, 38, (25, 29, 33, 36, 42, 55, 55)),
    _f(6525, 6875, "B1", 2.2, 38, (21, 25, 29, 32, 35, 39, 45)),
    _f(6525, 6875, "B2", 4.1, 32, (15, 20, 23, 28, 29, 60, 60)),
    _f(6875, 7125, "A", 2.2, 38, (25, 29, 33, 36, 42, 55, 55)),
    _f(6875, 7125, "B1", 2.2, 38, (21, 25, 29, 32, 35, 39, 45)),
    _f(6875, 7125, "B2", 4.1, 32, (15, 20, 23, 28, 29, 60, 60)),
    _f(10550, 10680, "A", 3.5, 33.5, (18, 24, 28, 32, 35, 55, 55)),
    _f(10550, 10680, "B", 3.5, 33.5, (17, 24, 28, 32, 35, 40, 45)),
    _f(10700, 11700, "A", 2.2, 38, (25, 29, 33, 36, 42, 55, 55)),
    _f(10700, 11700, "B", 3.5, 33.5, (17, 24, 28, 32, 35, 40, 45), note="Standard B is permitted in any area under paragraph (f)."),
    _f(12200, 13250, "A", 1.0, None, (23, 28, 35, 39, 41, 42, 50)),
    _f(12200, 13250, "B", 2.0, None, (20, 25, 28, 30, 32, 37, 47)),
    _f(17700, 18820, "A", 2.2, 38, (25, 29, 33, 36, 42, 55, 55)),
    _f(17700, 18820, "B1", 2.2, 38, (20, 24, 28, 32, 35, 36, 36)),
    _f(17700, 18820, "B2", 3.3, 33.5, (18, 22, 29, 31, 35, 55, 55)),
    _f(18920, 19700, "A", 2.2, 38, (25, 29, 33, 36, 42, 55, 55)),
    _f(18920, 19700, "B1", 2.2, 38, (20, 24, 28, 32, 35, 36, 36)),
    _f(18920, 19700, "B2", 3.3, 33.5, (18, 22, 29, 31, 35, 55, 55)),
    _f(21200, 23600, "A", 3.3, 33.5, (18, 26, 26, 33, 33, 55, 55)),
    _f(21200, 23600, "B1", 3.3, 33.5, (17, 24, 24, 29, 29, 40, 50)),
    _f(21200, 23600, "B2", 4.5, 30.5, (14, 19, 22, 24, 29, 52, 52)),
    _f(24250, 25250, "A", 2.8, 38, (25, 29, 33, 36, 42, 55, 60)),
    _f(24250, 25250, "B", 2.8, 38, (20, 24, 28, 32, 35, 36, 45)),
    _f(31000, 31300, "B", None, 38, (20, 24, 28, 32, 35, 36, 36), note="Mobile stations other than aeronautical mobile are exempt."),
    _f(71000, 76000, "Band requirement", 2.2, 38, (22, 28, 32, 35, 37, 55, 55), cross_suppression_db=(35, 35, 40, 42, 47, 55, 55), xpd_min_db=21),
    _f(81000, 86000, "Band requirement", 2.2, 38, (22, 28, 32, 35, 37, 55, 55), cross_suppression_db=(35, 35, 40, 42, 47, 55, 55), xpd_min_db=21),
    _f(92000, 95000, "Band requirement", 0.6, 50, (36, 40, 45, 50, 55, 55, 55)),
)


def fcc_profiles_for_frequency(frequency_mhz: float) -> tuple[FCCProfile, ...]:
    matches = tuple(
        profile
        for profile in FCC_PROFILES
        if profile.frequency_min_mhz <= frequency_mhz <= profile.frequency_max_mhz
    )
    boundary_starts = tuple(
        profile
        for profile in matches
        if abs(profile.frequency_min_mhz - frequency_mhz) <= 1e-9
    )
    return boundary_starts or matches


ETSI_XPD_REQUIREMENTS: dict[str, tuple[float | None, float | None, float | None]] = {
    "0": (None, 25, None),
    "1": (27, 30, 35),
    "2": (27, 27, 30),
    "3": (27, 27, 30),
    "4": (27, 27, 30),
    "5": (27, 27, 30),
    "6a": (27, None, None),
    "6b": (None, None, None),
    "7": (25, 27, None),
    "8": (25, 27, None),
    "9": (None, None, None),
}


def etsi_xpd_requirements(frequency_ghz: float) -> tuple[float | None, float | None, float | None]:
    if 1 <= frequency_ghz < 3:
        return ETSI_XPD_REQUIREMENTS["0"]
    if 3 <= frequency_ghz < 14:
        return ETSI_XPD_REQUIREMENTS["1"]
    if 14 <= frequency_ghz < 20:
        return ETSI_XPD_REQUIREMENTS["2"]
    if 20 <= frequency_ghz < 24:
        return ETSI_XPD_REQUIREMENTS["3"]
    if 24 <= frequency_ghz < 30:
        return ETSI_XPD_REQUIREMENTS["4"]
    if 30 <= frequency_ghz < 47:
        return ETSI_XPD_REQUIREMENTS["5"]
    if 47 <= frequency_ghz < 57:
        return ETSI_XPD_REQUIREMENTS["6a"]
    if 57 <= frequency_ghz < 71:
        return ETSI_XPD_REQUIREMENTS["6b"]
    if 71 <= frequency_ghz <= 86:
        return ETSI_XPD_REQUIREMENTS["7"]
    if 92 <= frequency_ghz <= 114.25:
        return ETSI_XPD_REQUIREMENTS["8"]
    if 130 <= frequency_ghz <= 175.8:
        return ETSI_XPD_REQUIREMENTS["9"]
    return (None, None, None)
