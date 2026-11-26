"""Unit tests for breeding program, pollen vault, seed minting, pedigree & pheno hunts."""

from __future__ import annotations

from pathlib import Path

import pytest

from custom_components.igro.calculations import (
    build_pedigree_tree,
    calculate_seed_maturity_date,
    compute_pheno_overall_score,
)
from custom_components.igro.database import IGroDatabase


@pytest.mark.asyncio
async def test_pollen_vault_cross_seed_minting_and_journal_types(
    tmp_path: Path,
) -> None:
    """Pollen batch, breeding cross, seed harvest auto-minting, and pollination/reversal logs."""
    db = IGroDatabase(tmp_path / "igro_breeding.db")
    await db.async_initialize()

    mother = await db.async_create_plant(
        {"name": "Blueberry Muffin #1", "strain": "Blueberry Muffin", "stage": "flowering"}
    )
    donor = await db.async_create_plant(
        {"name": "Northern Lights #3", "strain": "Northern Lights", "stage": "flowering"}
    )

    # New journal action types: reversal & pollination
    rev_log = await db.async_create_log(
        {
            "plant_id": donor["id"],
            "log_type": "reversal",
            "title": "STS Spray #1",
            "notes": "Sprayed lower branch at flip",
        }
    )
    poll_log = await db.async_create_log(
        {
            "plant_id": mother["id"],
            "log_type": "pollination",
            "title": "Dusted lower branch",
        }
    )
    assert rev_log["log_type"] == "reversal"
    assert poll_log["log_type"] == "pollination"

    # Pollen Vault batch linked to reversed donor plant
    pollen = await db.async_create_pollen_batch(
        {
            "name": "NL #3 Reversed Pollen",
            "donor_plant_id": donor["id"],
            "donor_type": "reversed_sts",
            "collected_at": "2026-04-01",
            "storage_method": "Freezer vial w/ silica",
            "storage_location": "Freezer Box A-1",
            "viability": "high",
        }
    )
    assert pollen["donor_strain"] == "Northern Lights"
    assert pollen["donor_type"] == "reversed_sts"

    # Create cross -> auto-calculates +6 weeks expected maturity
    cross = await db.async_create_breeding_cross(
        {
            "name": "Blueberry Lights F1",
            "mother_plant_id": mother["id"],
            "pollen_batch_id": pollen["id"],
            "generation": "F1",
            "pollination_date": "2026-04-10",
            "pollination_scope": "branch",
            "branch_tag": "Yellow tag lower-left",
        }
    )
    assert cross["expected_maturity_date"] == "2026-05-22"
    assert cross["status"] == "pollinated"

    # Harvest seeds -> auto-mints feminized Seedbank batch with lineage
    harvested = await db.async_harvest_cross_seeds(
        cross["id"],
        {
            "harvested_at": "2026-05-24",
            "seed_count": 85,
            "storage_location": "Fridge Vial #9",
            "mint_seedbank": True,
        },
    )
    assert harvested is not None
    assert harvested["cross"]["status"] == "harvested"
    assert harvested["cross"]["seed_count"] == 85
    batch = harvested["seed_batch"]
    assert batch is not None
    assert batch["seed_type"] == "feminized"
    assert batch["seed_count"] == 85
    assert batch["generation"] == "F1"
    assert "Blueberry Muffin" in batch["lineage_summary"]
    assert "Northern Lights" in batch["lineage_summary"]

    # Snapshot includes all new breeding collections
    snap = await db.async_get_snapshot()
    assert len(snap["pollen_batches"]) == 1
    assert len(snap["breeding_crosses"]) == 1
    assert len(snap["seed_batches"]) == 1


@pytest.mark.asyncio
async def test_pheno_hunt_and_sibling_scorecards(tmp_path: Path) -> None:
    """Create pheno hunt, upsert sibling trait scores, and compute overall ratings."""
    db = IGroDatabase(tmp_path / "igro_pheno.db")
    await db.async_initialize()

    p1 = await db.async_create_plant({"name": "Haze #1", "strain": "Northern Haze"})
    p2 = await db.async_create_plant({"name": "Haze #2", "strain": "Northern Haze"})

    hunt = await db.async_create_pheno_hunt(
        {
            "name": "Northern Haze 2-Plant Hunt",
            "strain": "Northern Haze",
            "selection_goals": "Heavy resin and short flower time",
        }
    )
    sc1 = await db.async_upsert_pheno_score(
        hunt["id"],
        p1["id"],
        {
            "pheno_code": "#1",
            "status": "keeper",
            "vigor": 5,
            "stretch_factor": 1.6,
            "internode_spacing": "tight",
            "resin_density": 5,
            "pest_mold_resistance": 4,
            "aroma_score": 5,
            "terpene_notes": "Pine & blueberry gas",
            "flower_days": 58,
            "yield_g": 112.5,
        },
    )
    sc2 = await db.async_upsert_pheno_score(
        hunt["id"],
        p2["id"],
        {
            "status": "cull",
            "vigor": 3,
            "resin_density": 2,
            "pest_mold_resistance": 3,
            "aroma_score": 2,
        },
    )
    assert sc1["pheno_code"] == "#1"
    assert sc2["pheno_code"] == "#2"
    assert compute_pheno_overall_score(sc1) == 4.75
    assert compute_pheno_overall_score(sc2) == 2.5

    # Upserting same plant updates existing scorecard rather than duplicating
    sc1_updated = await db.async_upsert_pheno_score(
        hunt["id"],
        p1["id"],
        {"status": "breeder", "vigor": 5, "resin_density": 5, "pest_mold_resistance": 5, "aroma_score": 5},
    )
    assert sc1_updated["id"] == sc1["id"]
    assert sc1_updated["status"] == "breeder"
    assert compute_pheno_overall_score(sc1_updated) == 5.0

    assert await db.async_delete_pheno_score(sc2["id"]) is True
    assert await db.async_delete_pheno_hunt(hunt["id"]) is True


def test_multi_generation_pedigree_tree_and_cycle_guard() -> None:
    """Build multi-generation pedigree tree and safely terminate cyclic references."""
    assert calculate_seed_maturity_date("2026-01-01", weeks=6) == "2026-02-12"

    crosses = {
        "c_f1": {
            "id": "c_f1",
            "name": "Grandparent F1",
            "generation": "F1",
            "mother_name": "Northern Lights",
            "father_name": "Haze",
        },
        "c_s1": {
            "id": "c_s1",
            "name": "Blueberry S1",
            "generation": "S1",
            "mother_name": "Blueberry",
            "father_name": "Blueberry (STS)",
        },
        "c_f2": {
            "id": "c_f2",
            "name": "Northern Berry",
            "generation": "Polyhybrid",
            "mother_cross_id": "c_f1",
            "father_cross_id": "c_s1",
        },
    }
    tree = build_pedigree_tree("c_f2", crosses, {})
    assert tree is not None
    assert tree["name"] == "Northern Berry"
    assert tree["mother"]["name"] == "Grandparent F1"
    assert tree["mother"]["mother"]["name"] == "Northern Lights"
    assert tree["mother"]["father"]["name"] == "Haze"
    assert tree["father"]["name"] == "Blueberry S1"
    assert tree["father"]["mother"]["name"] == "Blueberry"

    # Cycle guard should not recurse infinitely
    cyclic = {
        "a": {"id": "a", "name": "A", "mother_cross_id": "b"},
        "b": {"id": "b", "name": "B", "mother_cross_id": "a"},
    }
    cy_tree = build_pedigree_tree("a", cyclic, {})
    assert cy_tree is not None
    assert cy_tree["mother"]["name"] == "B"
    assert cy_tree["mother"]["mother"]["mother"] is None
