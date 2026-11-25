"""Unit tests for retrospective (backdated) & scheduled logs and stage changes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.igro.calculations import (
    is_timestamp_in_future,
    is_timestamp_near_now,
)
from custom_components.igro.database import IGroDatabase


def test_timestamp_helpers() -> None:
    now = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
    assert is_timestamp_near_now(None, now=now) is True
    assert is_timestamp_near_now((now - timedelta(minutes=5)).isoformat(), now=now) is True
    assert is_timestamp_near_now((now - timedelta(days=2)).isoformat(), now=now) is False
    assert is_timestamp_in_future((now + timedelta(hours=2)).isoformat(), now=now) is True
    assert is_timestamp_in_future((now - timedelta(hours=1)).isoformat(), now=now) is False


def test_backdated_and_planned_logs() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = IGroDatabase(Path(tmp) / "igro.db")
            await db.async_initialize()

            plant = await db.async_create_plant(
                {"name": "Gelato #1", "started_at": "2026-10-01T00:00:00+00:00"}
            )

            # Backdated completed watering
            past = await db.async_create_log(
                {
                    "plant_id": plant["id"],
                    "log_type": "water",
                    "logged_at": "2026-11-20T10:00:00+00:00",
                    "water_volume_ml": 1500,
                    "ph": 6.2,
                }
            )
            assert past["status"] == "completed"

            # Future planned feed (auto-detected as planned)
            future_ts = (datetime.now(UTC) + timedelta(days=5)).replace(microsecond=0).isoformat()
            planned = await db.async_create_log(
                {
                    "plant_id": plant["id"],
                    "log_type": "feed",
                    "logged_at": future_ts,
                    "water_volume_ml": 3000,
                    "ph": 6.5,
                }
            )
            assert planned["status"] == "planned"

            # Planned log must NOT pollute last_watered_at / last_ph stats
            snap = await db.async_get_snapshot()
            stats = snap["plant_stats"][plant["id"]]
            assert stats["last_watered_at"] == "2026-11-20T10:00:00+00:00"
            assert stats["last_ph"] == 6.2
            assert stats["planned_log_count"] == 1
            assert len(snap["planned_logs"]) == 1

            # Edit backdated log
            edited = await db.async_update_log(past["id"], {"ph": 6.4, "notes": "Corrected pH"})
            assert edited is not None
            assert edited["ph"] == 6.4

            # Complete planned log
            completed = await db.async_complete_log(planned["id"], {"ph": 6.1})
            assert completed is not None
            assert completed["status"] == "completed"
            assert completed["ph"] == 6.1

            snap2 = await db.async_get_snapshot()
            assert snap2["plant_stats"][plant["id"]]["planned_log_count"] == 0
            assert snap2["plant_stats"][plant["id"]]["last_ph"] == 6.1

    asyncio.run(_run())


def test_retrospective_stage_history_and_scheduled_transitions() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = IGroDatabase(Path(tmp) / "igro.db")
            await db.async_initialize()

            plant = await db.async_create_plant(
                {
                    "name": "OG Kush",
                    "stage": "vegetative",
                    "started_at": "2026-10-01",
                    "stage_started_at": "2026-10-20",
                }
            )

            # Retrospectively insert earlier germination & seedling stages
            germ = await db.async_add_stage_history(
                plant["id"], "germination", "2026-10-01", "Paper towel"
            )
            seedling = await db.async_add_stage_history(
                plant["id"], "seedling", "2026-10-06", "Sprouted"
            )
            assert germ is not None
            assert seedling is not None

            # Verify chronological chaining and that current stage stayed vegetative
            snap = await db.async_get_snapshot()
            hist = [h for h in snap["stage_history"] if h["plant_id"] == plant["id"]]
            assert [h["stage"] for h in hist] == ["germination", "seedling", "vegetative"]
            assert hist[0]["ended_at"] == "2026-10-06"
            assert hist[1]["ended_at"] == "2026-10-20"
            assert hist[2]["ended_at"] is None
            cur_plant = snap["plants"][0]
            assert cur_plant["stage"] == "vegetative"

            # Schedule a future flowering transition (auto_apply=True) and a manual drying transition
            sched_flower = await db.async_schedule_stage_change(
                plant["id"], "flowering", "2026-12-01", auto_apply=True, notes="Flip 12/12"
            )
            sched_dry = await db.async_schedule_stage_change(
                plant["id"], "drying", "2026-12-01", auto_apply=False, notes="Manual check"
            )

            # Before due date -> nothing applied
            assert await db.async_process_due_stage_changes("2026-11-28T00:00:00+00:00") == []

            # On due date -> auto_apply transition runs, manual one stays pending
            applied = await db.async_process_due_stage_changes("2026-12-01T12:00:00+00:00")
            assert len(applied) == 1
            assert applied[0]["schedule_id"] == sched_flower["id"]
            assert applied[0]["stage"] == "flowering"

            updated_plant = await db.async_get_plant(plant["id"])
            assert updated_plant is not None
            assert updated_plant["stage"] == "flowering"

            # Cancel the manual pending schedule
            assert await db.async_cancel_scheduled_stage_change(sched_dry["id"]) is True
            snap_end = await db.async_get_snapshot()
            assert len(snap_end["scheduled_stage_changes"]) == 0

    asyncio.run(_run())
