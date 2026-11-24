"""Unit tests for iGro environmental and lifecycle calculations."""

from __future__ import annotations

from datetime import datetime, timezone
import sys
from pathlib import Path

# Allow running tests without installing package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.igro.calculations import (
    calculate_dew_point_c,
    calculate_vpd_kpa,
    compute_plant_day_metrics,
    evaluate_range_status,
    get_effective_vpd_targets,
    to_celsius,
)


def test_to_celsius() -> None:
    assert round(to_celsius(77.0, "°F"), 2) == 25.0
    assert to_celsius(25.0, "°C") == 25.0
    assert to_celsius(22.5, None) == 22.5


def test_calculate_vpd_kpa() -> None:
    # 25°C air, 60% RH, -2°C leaf offset -> leaf 23°C
    # SVP(23) ≈ 2.81 kPa, AVP(25, 60%) ≈ 3.167 * 0.60 = 1.90 kPa -> VPD ≈ 0.91 kPa
    vpd = calculate_vpd_kpa(25.0, 60.0, leaf_temp_offset_c=-2.0)
    assert vpd is not None
    assert 0.85 <= vpd <= 0.95

    # Zero offset (air VPD): 25°C, 50% RH -> ~1.58 kPa
    air_vpd = calculate_vpd_kpa(25.0, 50.0, leaf_temp_offset_c=0.0)
    assert air_vpd is not None
    assert 1.50 <= air_vpd <= 1.65

    # Invalid inputs return None
    assert calculate_vpd_kpa(None, 50.0) is None
    assert calculate_vpd_kpa(25.0, None) is None
    assert calculate_vpd_kpa(25.0, 120.0) is None


def test_dew_point() -> None:
    dp = calculate_dew_point_c(25.0, 60.0)
    assert dp is not None
    assert 16.0 <= dp <= 17.5


def test_evaluate_range_status() -> None:
    assert evaluate_range_status(1.0, 0.8, 1.2) == "optimal"
    assert evaluate_range_status(0.5, 0.8, 1.2) == "low"
    assert evaluate_range_status(1.5, 0.8, 1.2) == "high"
    assert evaluate_range_status(None, 0.8, 1.2) == "unknown"


def test_effective_vpd_targets() -> None:
    # Explicit override takes precedence
    assert get_effective_vpd_targets(
        {"target_vpd_min": 0.9, "target_vpd_max": 1.3},
        [{"stage": "flowering"}],
    ) == (0.9, 1.3)

    # Auto stage target: flowering prioritizes over vegetative
    assert get_effective_vpd_targets(
        {}, [{"stage": "vegetative"}, {"stage": "flowering"}]
    ) == (1.2, 1.6)

    # Empty environment defaults to vegetative range
    assert get_effective_vpd_targets({}, []) == (0.8, 1.2)


def test_plant_day_metrics() -> None:
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    metrics = compute_plant_day_metrics(
        {
            "started_at": "2026-05-01T12:00:00+00:00",
            "stage_started_at": "2026-06-01T12:00:00+00:00",
        },
        now=now,
    )
    assert metrics["total_days"] == 45
    assert metrics["stage_days"] == 14
    assert metrics["stage_week"] == 3
