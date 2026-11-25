"""Environmental and lifecycle calculations for iGro."""

from __future__ import annotations

from datetime import UTC, datetime
import math
from typing import Any

from .const import (
    DEFAULT_LEAF_TEMP_OFFSET_C,
    STAGE_VPD_TARGETS,
    VPD_STATUS_HIGH,
    VPD_STATUS_LOW,
    VPD_STATUS_OPTIMAL,
    VPD_STATUS_UNKNOWN,
)


def to_celsius(value: float, unit: str | None) -> float:
    """Convert a temperature reading to Celsius."""
    if unit and ("f" in unit.lower()):
        return (value - 32.0) * 5.0 / 9.0
    return value


def saturation_vapor_pressure_kpa(temp_c: float) -> float:
    """Calculate saturation vapor pressure (SVP) in kPa using Tetens formula."""
    return 0.61078 * math.exp((17.27 * temp_c) / (temp_c + 237.3))


def calculate_vpd_kpa(
    air_temp_c: float | None,
    humidity_pct: float | None,
    leaf_temp_offset_c: float = DEFAULT_LEAF_TEMP_OFFSET_C,
) -> float | None:
    """Calculate Leaf Vapor Pressure Deficit (VPD) in kPa.

    Uses leaf temperature = air_temp_c + leaf_temp_offset_c.
    Returns None if inputs are missing or out of sane bounds.
    """
    if air_temp_c is None or humidity_pct is None:
        return None
    if not (0.0 <= humidity_pct <= 100.0):
        return None
    if not (-30.0 <= air_temp_c <= 80.0):
        return None

    leaf_temp_c = air_temp_c + leaf_temp_offset_c
    svp_leaf = saturation_vapor_pressure_kpa(leaf_temp_c)
    svp_air = saturation_vapor_pressure_kpa(air_temp_c)
    avp_air = svp_air * (humidity_pct / 100.0)
    vpd = max(0.0, svp_leaf - avp_air)
    return round(vpd, 2)


def calculate_dew_point_c(
    air_temp_c: float | None,
    humidity_pct: float | None,
) -> float | None:
    """Calculate dew point in Celsius using Magnus formula."""
    if air_temp_c is None or humidity_pct is None or humidity_pct <= 0.0:
        return None
    a = 17.27
    b = 237.7
    gamma = ((a * air_temp_c) / (b + air_temp_c)) + math.log(humidity_pct / 100.0)
    dew_point = (b * gamma) / (a - gamma)
    return round(dew_point, 1)


def evaluate_range_status(
    value: float | None,
    target_min: float | None,
    target_max: float | None,
) -> str:
    """Evaluate whether a numeric reading is low, high, optimal, or unknown."""
    if value is None:
        return VPD_STATUS_UNKNOWN
    if target_min is not None and value < target_min:
        return VPD_STATUS_LOW
    if target_max is not None and value > target_max:
        return VPD_STATUS_HIGH
    if target_min is None and target_max is None:
        return VPD_STATUS_UNKNOWN
    return VPD_STATUS_OPTIMAL


def get_effective_vpd_targets(
    env: dict[str, Any],
    plants_in_env: list[dict[str, Any]] | None = None,
) -> tuple[float | None, float | None]:
    """Return target (min_vpd, max_vpd) for an environment.

    Explicit environment overrides take precedence; otherwise falls back
    to the stage-based VPD targets of active plants inside the environment.
    """
    t_min = env.get("target_vpd_min")
    t_max = env.get("target_vpd_max")
    if t_min is not None or t_max is not None:
        return (t_min, t_max)

    if plants_in_env:
        # Prefer the most advanced active stage in the environment (e.g. flowering > veg)
        priority = ["flowering", "vegetative", "seedling", "germination", "drying", "curing"]
        stages_present = {p.get("stage") for p in plants_in_env}
        for stage in priority:
            if stage in stages_present and stage in STAGE_VPD_TARGETS:
                return STAGE_VPD_TARGETS[stage]

    return (0.8, 1.2)


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse an ISO-8601 date or datetime string into an aware UTC datetime."""
    if not value:
        return None
    try:
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return None


def days_since(iso_timestamp: str | None, now: datetime | None = None) -> int | None:
    """Compute whole days elapsed since an ISO date/datetime."""
    dt = parse_iso_datetime(iso_timestamp)
    if dt is None:
        return None
    ref = now or datetime.now(UTC)
    delta = ref - dt
    return max(0, delta.days)


def is_timestamp_in_future(
    iso_timestamp: str | None,
    now: datetime | None = None,
    grace_seconds: int = 300,
) -> bool:
    """Return True if an ISO timestamp is strictly in the future beyond grace_seconds."""
    dt = parse_iso_datetime(iso_timestamp)
    if dt is None:
        return False
    ref = now or datetime.now(UTC)
    return (dt - ref).total_seconds() > grace_seconds


def is_timestamp_near_now(
    iso_timestamp: str | None,
    now: datetime | None = None,
    tolerance_minutes: int = 15,
) -> bool:
    """Return True if timestamp is omitted or within tolerance_minutes of now."""
    if not iso_timestamp:
        return True
    dt = parse_iso_datetime(iso_timestamp)
    if dt is None:
        return True
    ref = now or datetime.now(UTC)
    return abs((dt - ref).total_seconds()) <= tolerance_minutes * 60


def compute_plant_day_metrics(
    plant: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, int | None]:
    """Compute total grow days, stage days, and 1-indexed stage week."""
    ref = now or datetime.now(UTC)
    total_days = days_since(plant.get("started_at"), ref)
    stage_days = days_since(plant.get("stage_started_at") or plant.get("started_at"), ref)
    stage_week = ((stage_days // 7) + 1) if stage_days is not None else None
    total_week = ((total_days // 7) + 1) if total_days is not None else None
    return {
        "total_days": total_days,
        "total_week": total_week,
        "stage_days": stage_days,
        "stage_week": stage_week,
    }


ML_PER_US_GALLON = 3785.411784


def scale_nutrients_for_volume(
    nutrients: list[dict[str, Any]],
    water_volume_ml: float | None,
) -> list[dict[str, Any]]:
    """Scale per-liter or per-gallon nutrient dosages to a target water volume.

    Returns a copy of each nutrient dict enriched with `total_amount` and `total_unit`
    when scaling applies (e.g. `mL/L`, `g/L`, `mL/gal`, `g/gal`, `tsp/gal`).
    """
    results: list[dict[str, Any]] = []
    liters = (water_volume_ml / 1000.0) if (water_volume_ml and water_volume_ml > 0) else None
    gallons = (
        (water_volume_ml / ML_PER_US_GALLON)
        if (water_volume_ml and water_volume_ml > 0)
        else None
    )

    for item in nutrients:
        entry = dict(item)
        raw_amount = item.get("amount")
        unit = (item.get("unit") or "").strip()
        unit_lower = unit.lower()

        try:
            qty = float(raw_amount) if raw_amount not in (None, "") else None
        except (ValueError, TypeError):
            qty = None

        if qty is not None and liters is not None and gallons is not None:
            if unit_lower.endswith("/l") or unit_lower.endswith("/liter"):
                base_unit = unit.split("/", 1)[0].strip() or "mL"
                entry["total_amount"] = round(qty * liters, 2)
                entry["total_unit"] = base_unit
            elif unit_lower.endswith("/gal") or unit_lower.endswith("/gallon"):
                base_unit = unit.split("/", 1)[0].strip() or "mL"
                entry["total_amount"] = round(qty * gallons, 2)
                entry["total_unit"] = base_unit
            else:
                entry["total_amount"] = round(qty, 2)
                entry["total_unit"] = unit

        results.append(entry)
    return results


def suggest_presets_for_plant(
    plant: dict[str, Any],
    presets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return matching nutrient presets ranked by specificity for a plant's stage & week."""
    plant_stage = plant.get("stage")
    stage_week = plant.get("stage_week")
    scored: list[tuple[int, str, dict[str, Any]]] = []

    for preset in presets:
        p_stage = preset.get("stage")
        w_start = preset.get("week_start")
        w_end = preset.get("week_end")

        if p_stage and p_stage != plant_stage:
            continue

        week_matched = False
        if w_start is not None or w_end is not None:
            if stage_week is None:
                continue
            low = w_start if w_start is not None else 1
            high = w_end if w_end is not None else 999
            if not (low <= stage_week <= high):
                continue
            week_matched = True

        # Lower score = higher priority: exact stage+week (0) > stage-only (1) > any-stage (2)
        if p_stage and week_matched:
            rank = 0
        elif p_stage:
            rank = 1
        else:
            rank = 2
        scored.append((rank, (preset.get("name") or "").lower(), preset))

    scored.sort(key=lambda t: (t[0], t[1]))
    return [item[2] for item in scored]
