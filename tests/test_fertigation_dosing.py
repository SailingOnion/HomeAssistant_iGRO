"""Unit tests for High-Frequency Fertigation (#10) & Reservoir Dosing (#11)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from custom_components.igro.database import IGroDatabase
from custom_components.igro.fertigation import (
    compute_auto_trim_dose,
    compute_high_frequency_shot_times,
    compute_next_fertigation_time,
    evaluate_probe_sanity,
    plan_ordered_batch_mix,
    validate_fertigation_safety,
)


def test_high_frequency_crop_steering_shot_times() -> None:
    """P1 ramp shots + P2 maintenance spacing respect P3 overnight dryback cutoff."""
    times = compute_high_frequency_shot_times(
        window_start="08:00",
        window_end="20:00",
        feeds_per_day=5,
        p1_ramp_shots=2,
        p1_interval_min=30,
        p3_dryback_cutoff_min=120,
    )
    # Active end = 18:00 (20:00 - 120m). P1 = 08:00, 08:30. P2 spreads 3 shots from 09:00..18:00
    assert len(times) == 5
    assert times[0] == "08:00"
    assert times[1] == "08:30"
    assert times[-1] == "18:00"


def test_compute_next_fertigation_time_modes() -> None:
    """Next fertigation timestamp handles high_frequency, interval, fixed_times & off."""
    now = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    assert compute_next_fertigation_time({"mode": "off"}, now) is None

    fixed_sched = {
        "mode": "scheduled",
        "schedule_type": "fixed_times",
        "fixed_times": ["08:00", "12:30", "16:00"],
    }
    assert compute_next_fertigation_time(fixed_sched, now) == "2026-05-01T12:30:00+00:00"

    interval_sched = {
        "mode": "scheduled",
        "schedule_type": "interval",
        "interval_hours": 4.0,
        "last_fed_at": "2026-05-01T08:00:00+00:00",
    }
    assert (
        compute_next_fertigation_time(interval_sched, now)
        == "2026-05-01T12:00:00+00:00"
    )


def test_fertigation_safety_interlocks_and_caps() -> None:
    """Safety validator enforces leak kill-switch, dry-run float, single-shot & daily caps."""
    sched = {
        "flow_rate_ml_s": 10.0,
        "max_shot_duration_s": 45.0,
        "max_daily_volume_ml": 1000.0,
    }
    ok, reason, vol = validate_fertigation_safety(sched, 20.0, 200.0)
    assert ok is True
    assert reason is None
    assert vol == 200.0

    # Leak detector blocks immediately
    ok_leak, reason_leak, _ = validate_fertigation_safety(
        sched, 15.0, 0.0, leak_detected=True
    )
    assert ok_leak is False
    assert "Leak" in (reason_leak or "")

    # Low-level reservoir float blocks dry-run
    ok_low, reason_low, _ = validate_fertigation_safety(
        sched, 15.0, 0.0, reservoir_low=True
    )
    assert ok_low is False
    assert "low-level" in (reason_low or "")

    # Exceeding single-shot duration cap blocks
    ok_shot, reason_shot, _ = validate_fertigation_safety(sched, 60.0, 0.0)
    assert ok_shot is False
    assert "max safety cap" in (reason_shot or "")

    # Exceeding daily total volume cap blocks
    ok_day, reason_day, _ = validate_fertigation_safety(sched, 30.0, 800.0)
    assert ok_day is False
    assert "Daily volume cap" in (reason_day or "")


def test_ordered_batch_mix_sequence_and_safety_caps() -> None:
    """Ordered batch mixer scales mL for reservoir volume and enforces Silica -> Cal-Mag -> A -> B."""
    preset = {
        "name": "Coco Veg Base",
        "nutrients": [
            {"name": "Base B", "amount": "2", "unit": "mL/L"},
            {"name": "Silica", "amount": "0.5", "unit": "mL/L"},
            {"name": "Base A", "amount": "2", "unit": "mL/L"},
            {"name": "Cal-Mag", "amount": "1", "unit": "mL/L"},
        ],
    }
    channels = [
        {
            "id": "ch_b",
            "name": "Pump Base B",
            "role": "base_b",
            "nutrient_name": "Base B",
            "mix_order": 40,
            "flow_rate_ml_s": 2.0,
            "stir_delay_s": 30,
            "bottle_remaining_ml": 500,
            "max_dose_per_cycle_ml": 100,
            "max_daily_dose_ml": 300,
            "enabled": 1,
        },
        {
            "id": "ch_si",
            "name": "Pump Silica",
            "role": "silica",
            "nutrient_name": "Silica",
            "mix_order": 10,
            "flow_rate_ml_s": 1.0,
            "stir_delay_s": 60,
            "bottle_remaining_ml": 10,  # Low bottle warning!
            "max_dose_per_cycle_ml": 50,
            "max_daily_dose_ml": 100,
            "enabled": 1,
        },
        {
            "id": "ch_cm",
            "name": "Pump Cal-Mag",
            "role": "cal_mag",
            "nutrient_name": "Cal-Mag",
            "mix_order": 20,
            "flow_rate_ml_s": 1.0,
            "stir_delay_s": 30,
            "bottle_remaining_ml": 500,
            "max_dose_per_cycle_ml": 100,
            "max_daily_dose_ml": 200,
            "enabled": 1,
        },
        {
            "id": "ch_a",
            "name": "Pump Base A",
            "role": "base_a",
            "nutrient_name": "Base A",
            "mix_order": 30,
            "flow_rate_ml_s": 2.0,
            "stir_delay_s": 30,
            "bottle_remaining_ml": 500,
            "max_dose_per_cycle_ml": 100,
            "max_daily_dose_ml": 300,
            "enabled": 1,
        },
    ]

    plan = plan_ordered_batch_mix(preset, 30.0, channels)
    assert plan["valid"] is True
    assert [s["role"] for s in plan["steps"]] == ["silica", "cal_mag", "base_a", "base_b"]
    assert [s["dose_ml"] for s in plan["steps"]] == [15.0, 30.0, 60.0, 60.0]
    assert plan["total_ml"] == 165.0
    assert len(plan["warnings"]) == 1  # Silica bottle low

    # Exceeding per-cycle safety cap aborts plan
    too_big = plan_ordered_batch_mix(preset, 100.0, channels)
    assert too_big["valid"] is False
    assert any("max cycle cap" in err for err in too_big["errors"])


def test_probe_sanity_and_auto_trim_guardrails() -> None:
    """Auto-trim calculates micro-doses and aborts on bad probe readings or daily cap."""
    res = {
        "capacity_l": 40.0,
        "target_ph": 5.8,
        "ph_tolerance": 0.15,
        "target_ec": 1.6,
        "ec_tolerance": 0.1,
        "ph_min_bound": 3.5,
        "ph_max_bound": 9.5,
        "ec_max_bound": 5.0,
    }
    channels = [
        {
            "id": "ch_phd",
            "name": "pH Down",
            "role": "ph_down",
            "enabled": 1,
            "max_dose_per_cycle_ml": 10.0,
            "max_daily_dose_ml": 25.0,
        },
        {
            "id": "ch_a",
            "name": "Base A",
            "role": "base_a",
            "mix_order": 30,
            "enabled": 1,
            "max_dose_per_cycle_ml": 20.0,
            "max_daily_dose_ml": 100.0,
        },
    ]

    # Probe out of bounds raises ValueError
    ok, _ = evaluate_probe_sanity(12.4, 1.5, res)
    assert ok is False
    with pytest.raises(ValueError, match="out of safe bounds"):
        compute_auto_trim_dose(res, channels, {}, 12.4, 1.5)

    # High pH triggers pH Down micro-dose
    act = compute_auto_trim_dose(res, channels, {}, 6.4, 1.6)
    assert act is not None
    assert act["run_type"] == "auto_ph_trim"
    assert act["channel"]["id"] == "ch_phd"
    assert act["dose_ml"] > 0

    # Daily cap lockout raises ValueError
    with pytest.raises(ValueError, match="daily cap"):
        compute_auto_trim_dose(res, channels, {"ch_phd": 24.5}, 6.4, 1.6)

    # Within tolerance returns None
    assert compute_auto_trim_dose(res, channels, {}, 5.85, 1.58) is None


@pytest.mark.asyncio
async def test_database_reservoir_dosing_and_fertigation_lifecycle(
    tmp_path: Path,
) -> None:
    """Full SQLite CRUD for reservoirs, channels, bottle tracking, dosing runs & schedules."""
    db = IGroDatabase(tmp_path / "igro_fert.db")
    await db.async_initialize()

    env = await db.async_create_environment({"name": "4x4 Coco Tent"})
    plant = await db.async_create_plant(
        {"name": "Coco Girl #1", "environment_id": env["id"], "medium": "coco"}
    )

    res = await db.async_create_reservoir(
        {
            "name": "Flower Res 60L",
            "environment_id": env["id"],
            "capacity_l": 60.0,
            "target_ph": 5.8,
            "target_ec": 1.6,
            "auto_trim_enabled": True,
        }
    )
    ch = await db.async_create_dosing_channel(
        {
            "reservoir_id": res["id"],
            "name": "Silica Pump",
            "role": "silica",
            "flow_rate_ml_s": 1.25,
            "bottle_capacity_ml": 1000.0,
            "bottle_remaining_ml": 1000.0,
        }
    )
    assert ch["mix_order"] == 10

    # Bottle consumption & dosing run audit + daily total
    updated_ch = await db.async_consume_channel_bottle(ch["id"], 25.0)
    assert updated_ch is not None
    assert updated_ch["bottle_remaining_ml"] == 975.0

    await db.async_record_dosing_run(
        {
            "reservoir_id": res["id"],
            "channel_id": ch["id"],
            "run_type": "batch_mix",
            "status": "completed",
            "dosed_ml": 25.0,
            "steps": [{"channel_id": ch["id"], "dose_ml": 25.0}],
        }
    )
    assert await db.async_get_daily_channel_dose(ch["id"]) == 25.0

    # Per-plant fertigation schedule & event tracking
    sched = await db.async_upsert_fertigation_schedule(
        plant["id"],
        {
            "reservoir_id": res["id"],
            "mode": "scheduled",
            "feeds_per_day": 6,
            "shot_duration_s": 20.0,
            "flow_rate_ml_s": 10.0,
            "fixed_times": ["08:00", "12:00"],
        },
    )
    assert sched["mode"] == "scheduled"
    assert sched["feeds_per_day"] == 6
    assert sched["fixed_times"] == ["08:00", "12:00"]

    await db.async_record_fertigation_event(
        {
            "plant_id": plant["id"],
            "schedule_id": sched["id"],
            "reservoir_id": res["id"],
            "trigger_type": "scheduled",
            "duration_s": 20.0,
            "volume_ml": 200.0,
            "status": "completed",
            "reservoir_ph": 5.8,
            "reservoir_ec": 1.6,
        }
    )
    assert await db.async_get_daily_fertigation_volume(plant["id"]) == 200.0

    snap = await db.async_get_snapshot()
    assert len(snap["reservoirs"]) == 1
    assert len(snap["dosing_channels"]) == 1
    assert len(snap["dosing_runs"]) == 1
    assert len(snap["fertigation_schedules"]) == 1
    assert len(snap["fertigation_events"]) == 1
    assert snap["daily_fert_vol"][plant["id"]] == 200.0
    assert snap["daily_channel_dose"][ch["id"]] == 25.0
