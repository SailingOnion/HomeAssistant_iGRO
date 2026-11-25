"""Unit tests for nutrient preset recipes, volume scaling, and stage suggestions."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.igro.calculations import (
    scale_nutrients_for_volume,
    suggest_presets_for_plant,
)
from custom_components.igro.database import IGroDatabase


def test_scale_nutrients_for_volume() -> None:
    nutrients = [
        {"name": "Cal-Mag", "amount": 2, "unit": "mL/L"},
        {"name": "Bloom A", "amount": "3.5", "unit": "mL/L"},
        {"name": "Dry Booster", "amount": 4, "unit": "g/gal"},
        {"name": "Flat Additive", "amount": 5, "unit": "mL"},
    ]

    # 4000 mL = 4.0 L (~1.0567 US gal)
    scaled = scale_nutrients_for_volume(nutrients, 4000)
    assert scaled[0]["total_amount"] == 8.0
    assert scaled[0]["total_unit"] == "mL"
    assert scaled[1]["total_amount"] == 14.0
    assert scaled[1]["total_unit"] == "mL"
    assert 4.2 <= scaled[2]["total_amount"] <= 4.3
    assert scaled[2]["total_unit"] == "g"
    assert scaled[3]["total_amount"] == 5.0
    assert scaled[3]["total_unit"] == "mL"

    # Without volume, returns entries without total_amount
    unscaled = scale_nutrients_for_volume(nutrients, None)
    assert "total_amount" not in unscaled[0]


def test_suggest_presets_for_plant() -> None:
    presets = [
        {"id": "any", "name": "Universal Cal-Mag", "stage": None, "week_start": None, "week_end": None},
        {"id": "veg_all", "name": "General Veg", "stage": "vegetative", "week_start": None, "week_end": None},
        {"id": "veg_w2_4", "name": "Veg Week 2-4", "stage": "vegetative", "week_start": 2, "week_end": 4},
        {"id": "veg_w5", "name": "Late Veg", "stage": "vegetative", "week_start": 5, "week_end": 8},
        {"id": "flower", "name": "Bloom Base", "stage": "flowering", "week_start": 1, "week_end": 4},
    ]

    plant = {"stage": "vegetative", "stage_week": 3}
    suggested = suggest_presets_for_plant(plant, presets)
    ids = [p["id"] for p in suggested]
    assert ids == ["veg_w2_4", "veg_all", "any"]


def test_database_nutrient_presets_crud() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = IGroDatabase(Path(tmp) / "igro.db")
            await db.async_initialize()

            created = await db.async_create_nutrient_preset(
                {
                    "name": "Veg Week 2-4 Base",
                    "stage": "vegetative",
                    "week_start": 2,
                    "week_end": 4,
                    "target_ph": 6.0,
                    "target_ec": 1.4,
                    "target_ppm": 700,
                    "nutrients": [
                        {"name": "Cal-Mag", "amount": 2, "unit": "mL/L"},
                        {"name": "Grow A", "amount": 3, "unit": "mL/L"},
                    ],
                    "notes": "Mix Cal-Mag first",
                }
            )
            assert created["name"] == "Veg Week 2-4 Base"
            assert len(created["nutrients"]) == 2
            assert created["week_start"] == 2

            # List & snapshot include the preset
            listed = await db.async_list_nutrient_presets(stage="vegetative")
            assert len(listed) == 1
            snap = await db.async_get_snapshot()
            assert len(snap["nutrient_presets"]) == 1

            # Update preset
            updated = await db.async_update_nutrient_preset(
                created["id"],
                {
                    "target_ec": 1.6,
                    "nutrients": [
                        {"name": "Cal-Mag", "amount": 2, "unit": "mL/L"},
                        {"name": "Grow A", "amount": 4, "unit": "mL/L"},
                    ],
                },
            )
            assert updated is not None
            assert updated["target_ec"] == 1.6
            assert updated["nutrients"][1]["amount"] == 4

            # Delete preset
            assert await db.async_delete_nutrient_preset(created["id"]) is True
            assert await db.async_get_nutrient_preset(created["id"]) is None

    asyncio.run(_run())
