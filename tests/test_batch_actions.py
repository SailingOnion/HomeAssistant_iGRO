"""Unit tests for Batch Actions (Multi-Plant / Whole-Tent Logging & Transitions)."""

from __future__ import annotations

from pathlib import Path

import pytest

from custom_components.igro.database import IGroDatabase


@pytest.mark.asyncio
async def test_batch_create_logs_split_and_per_plant_volume(tmp_path: Path) -> None:
    """Batch logging creates entries for all target plants and optionally splits volume."""
    db = IGroDatabase(tmp_path / "igro_batch.db")
    await db.async_initialize()

    env = await db.async_create_environment({"name": "4x4 Tent"})
    p1 = await db.async_create_plant({"name": "Plant A", "environment_id": env["id"]})
    p2 = await db.async_create_plant({"name": "Plant B", "environment_id": env["id"]})
    p3 = await db.async_create_plant({"name": "Plant C", "environment_id": env["id"]})
    plant_ids = [p1["id"], p2["id"], p3["id"]]

    # 1. Split 6000 mL across 3 plants -> 2000 mL each + rescaled nutrients
    split_logs = await db.async_create_logs_batch(
        plant_ids,
        {
            "log_type": "feed",
            "title": "Whole Tent Feed",
            "water_volume_ml": 6000.0,
            "ph": 6.1,
            "ec": 1.4,
            "nutrients": [{"name": "Grow A", "amount": "2", "unit": "mL/L"}],
        },
        split_water_volume=True,
        env_readings_by_plant={
            p1["id"]: {"temp_c": 24.5, "humidity": 60.0, "vpd_kpa": 1.05}
        },
    )
    assert len(split_logs) == 3
    for lg in split_logs:
        assert lg["water_volume_ml"] == 2000.0
        assert lg["ph"] == 6.1
        assert lg["nutrients"][0]["total_amount"] == 4.0
        assert lg["nutrients"][0]["total_unit"] == "mL"
    assert split_logs[0]["temp_c"] == 24.5

    # 2. Per-plant volume (split_water_volume=False) applies full 1500 mL to each plant
    per_plant_logs = await db.async_create_logs_batch(
        [p1["id"], p2["id"]],
        {"log_type": "water", "water_volume_ml": 1500.0, "notes": "Plain water"},
        split_water_volume=False,
    )
    assert len(per_plant_logs) == 2
    assert all(lg["water_volume_ml"] == 1500.0 for lg in per_plant_logs)


@pytest.mark.asyncio
async def test_batch_set_stage_and_batch_move_plants(tmp_path: Path) -> None:
    """Batch stage transitions and bulk environment moves update all selected plants."""
    db = IGroDatabase(tmp_path / "igro_batch_stage.db")
    await db.async_initialize()

    veg_tent = await db.async_create_environment({"name": "Veg Tent"})
    flower_tent = await db.async_create_environment({"name": "Flower Tent"})
    p1 = await db.async_create_plant(
        {
            "name": "NL #1",
            "environment_id": veg_tent["id"],
            "stage": "vegetative",
            "started_at": "2026-03-01",
        }
    )
    p2 = await db.async_create_plant(
        {
            "name": "NL #2",
            "environment_id": veg_tent["id"],
            "stage": "vegetative",
            "started_at": "2026-03-01",
        }
    )

    # Bulk move both plants to Flower Tent
    moved = await db.async_batch_move_plants([p1["id"], p2["id"]], flower_tent["id"])
    assert len(moved) == 2
    assert all(p["environment_id"] == flower_tent["id"] for p in moved)

    # Bulk flip both plants to Flowering with backdated timestamp
    flipped = await db.async_batch_set_plant_stage(
        [p1["id"], p2["id"]],
        "flowering",
        notes="Flipped tent to 12/12",
        changed_at="2026-04-15",
    )
    assert len(flipped) == 2
    assert all(p["stage"] == "flowering" for p in flipped)

    # Unassign one plant via batch_move(None)
    unassigned = await db.async_batch_move_plants([p1["id"]], None)
    assert len(unassigned) == 1
    assert unassigned[0]["environment_id"] is None
