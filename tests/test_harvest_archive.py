"""Unit tests for harvest & yield tracking, curing logs, grow cycles, and report exports."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.igro.calculations import compute_harvest_metrics
from custom_components.igro.database import IGroDatabase
from custom_components.igro.websocket_api import _format_plant_report_markdown


def test_compute_harvest_metrics() -> None:
    now = datetime(2026, 12, 15, 12, 0, tzinfo=UTC)
    metrics = compute_harvest_metrics(
        {
            "wet_weight_g": 400.0,
            "dry_weight_g": 100.0,
            "trim_weight_g": 25.0,
            "cure_start_at": "2026-12-01T12:00:00+00:00",
        },
        env_light_wattage=400.0,
        env_plant_count=4,
        now=now,
    )
    assert metrics["retention_pct"] == 25.0
    assert metrics["dry_weight_oz"] == 3.53
    assert metrics["total_dry_output_g"] == 125.0
    assert metrics["effective_wattage"] == 100.0
    assert metrics["grams_per_watt"] == 1.0
    assert metrics["curing_days"] == 14

    # Explicit wattage override takes precedence over tent share
    override = compute_harvest_metrics(
        {"dry_weight_g": 150.0, "light_wattage_override": 200.0},
        env_light_wattage=600.0,
        env_plant_count=2,
    )
    assert override["grams_per_watt"] == 0.75


def test_database_harvest_curing_cycles_and_export() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = IGroDatabase(Path(tmp) / "igro.db")
            await db.async_initialize()

            env = await db.async_create_environment(
                {"name": "4x4 Flower", "light_wattage": 480}
            )
            assert env["light_wattage"] == 480

            cycle = await db.async_create_grow_cycle(
                {"name": "Winter 2026 Run", "started_at": "2026-09-01"}
            )
            assert cycle["name"] == "Winter 2026 Run"

            plant = await db.async_create_plant(
                {
                    "name": "White Widow #1",
                    "strain": "White Widow",
                    "breeder": "Green House",
                    "environment_id": env["id"],
                    "grow_cycle_id": cycle["id"],
                    "stage": "flowering",
                    "started_at": "2026-09-01",
                }
            )

            harvest = await db.async_upsert_harvest(
                plant["id"],
                {
                    "harvested_at": "2026-11-15",
                    "wet_weight_g": 500.0,
                    "dry_weight_g": 120.0,
                    "trim_weight_g": 30.0,
                    "dry_days": 10,
                    "cure_start_at": "2026-11-25",
                    "rating": 5,
                    "is_keeper": True,
                    "aroma_notes": "Pine, earthy, spice",
                    "effect_notes": "Uplifting and balanced",
                    "set_plant_stage": "curing",
                },
            )
            assert harvest is not None
            assert harvest["dry_weight_g"] == 120.0
            assert harvest["rating"] == 5
            assert harvest["is_keeper"] == 1

            # Plant stage automatically moved to curing
            p_after = await db.async_get_plant(plant["id"])
            assert p_after is not None
            assert p_after["stage"] == "curing"

            # Add curing jar check -> updates harvest.cure_rh_pct
            clog = await db.async_add_curing_log(
                harvest["id"],
                {"jar_rh_pct": 62.5, "jar_temp_c": 19.0, "burped": True, "notes": "Smells fire"},
            )
            assert clog is not None
            assert clog["jar_rh_pct"] == 62.5

            snap = await db.async_get_snapshot()
            assert len(snap["grow_cycles"]) == 1
            assert len(snap["harvests"]) == 1
            assert snap["harvests"][0]["cure_rh_pct"] == 62.5
            assert len(snap["curing_logs"]) == 1

            # Export report (JSON + Markdown)
            report = await db.async_get_plant_report_data(plant["id"])
            assert report is not None
            md = _format_plant_report_markdown(report)
            assert "# Grow Report: White Widow #1" in md
            assert "120.0 g" in md
            assert "62.5% RH" in md
            assert "(Keeper)" in md

            # Clean up curing log, harvest, cycle
            assert await db.async_delete_curing_log(clog["id"]) is True
            assert await db.async_delete_harvest(harvest["id"]) is True
            assert await db.async_delete_grow_cycle(cycle["id"]) is True

    asyncio.run(_run())
