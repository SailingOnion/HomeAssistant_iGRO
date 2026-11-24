"""Unit tests for the iGro SQLite database layer."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.igro.database import IGroDatabase


def test_database_full_lifecycle() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = IGroDatabase(Path(tmp) / "igro.db")
            await db.async_initialize()

            # Create environment
            env = await db.async_create_environment(
                {
                    "name": "4x4 Tent",
                    "env_type": "tent",
                    "light_schedule": "18/6",
                    "temp_entity_id": "sensor.tent_temp",
                    "humidity_entity_id": "sensor.tent_rh",
                }
            )
            assert env["name"] == "4x4 Tent"

            # Create plant inside environment
            plant = await db.async_create_plant(
                {
                    "name": "Blue Dream #1",
                    "strain": "Blue Dream",
                    "breeder": "Humboldt",
                    "environment_id": env["id"],
                    "stage": "seedling",
                }
            )
            assert plant["stage"] == "seedling"

            # Transition stage -> creates stage_history & stage_change log
            updated = await db.async_set_plant_stage(
                plant["id"], "vegetative", notes="Transplanted to 5 gal"
            )
            assert updated is not None
            assert updated["stage"] == "vegetative"

            # Log a nutrient feed
            log = await db.async_create_log(
                {
                    "plant_id": plant["id"],
                    "log_type": "feed",
                    "water_volume_ml": 2000,
                    "ph": 6.3,
                    "ec": 1.4,
                    "nutrients": [
                        {"name": "Grow A", "amount": "2", "unit": "mL/L"},
                        {"name": "Cal-Mag", "amount": "1", "unit": "mL/L"},
                    ],
                }
            )
            assert log["environment_id"] == env["id"]
            assert len(log["nutrients"]) == 2

            # Create a photo
            photo = await db.async_create_photo(
                {
                    "plant_id": plant["id"],
                    "filename": "abc123.jpg",
                    "mime_type": "image/jpeg",
                    "caption": "Week 1 veg",
                }
            )
            assert photo["stage"] == "vegetative"
            assert photo["access_token"]

            # Snapshot verifies aggregates
            snap = await db.async_get_snapshot()
            assert len(snap["environments"]) == 1
            assert len(snap["plants"]) == 1
            stats = snap["plant_stats"][plant["id"]]
            assert stats["last_ph"] == 6.3
            assert stats["last_ec"] == 1.4
            assert stats["photo_count"] == 1
            assert stats["log_count"] == 2  # stage_change + feed
            assert stats["cover_photo"]["id"] == photo["id"]

            # Delete plant cascades and returns filenames for disk cleanup
            deleted_files = await db.async_delete_plant(plant["id"])
            assert deleted_files == ["abc123.jpg"]

            snap2 = await db.async_get_snapshot()
            assert len(snap2["plants"]) == 0
            assert len(snap2["recent_photos"]) == 0

    asyncio.run(_run())
