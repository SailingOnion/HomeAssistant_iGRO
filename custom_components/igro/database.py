"""SQLite database layer for iGro.

Uses Python's built-in sqlite3 in WAL mode inside Home Assistant's executor pool
so there are zero external dependencies and zero event-loop blocking.
Stored as a dedicated `igro.db` alongside Home Assistant's `home-assistant_v2.db`
to avoid recorder lock contention or schema conflicts.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import secrets
import sqlite3
from typing import Any
import uuid

from .calculations import (
    calculate_seed_maturity_date,
    is_timestamp_in_future,
    parse_iso_datetime,
    scale_nutrients_for_volume,
)
from .const import (
    DEFAULT_LEAF_TEMP_OFFSET_C,
    GROW_STAGES,
    LOG_TYPE_STAGE_CHANGE,
    LOG_TYPES,
    STAGE_GERMINATION,
)

SCHEMA_VERSION = 7


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _deserialize_log(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    raw = data.pop("nutrients_json", None)
    if raw:
        try:
            data["nutrients"] = json.loads(raw)
        except (ValueError, TypeError):
            data["nutrients"] = []
    else:
        data["nutrients"] = []
    return data


def _deserialize_preset(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    raw = data.pop("nutrients_json", None)
    if raw:
        try:
            data["nutrients"] = json.loads(raw)
        except (ValueError, TypeError):
            data["nutrients"] = []
    else:
        data["nutrients"] = []
    return data


class IGroDatabase:
    """Async wrapper around a dedicated SQLite database for iGro."""

    def __init__(self, db_path: str | Path) -> None:
        """Initialize database manager."""
        self.db_path = Path(db_path)
        self._lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    async def _run(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute a synchronous DB function inside an async lock & thread."""
        async with self._lock:
            return await asyncio.to_thread(func, *args, **kwargs)

    # ------------------------------------------------------------------
    # Schema initialization & migrations
    # ------------------------------------------------------------------
    async def async_initialize(self) -> None:
        """Initialize database tables and pragmas."""
        await self._run(self._initialize_sync)

    def _initialize_sync(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS environments (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    env_type TEXT NOT NULL DEFAULT 'tent',
                    dimensions TEXT,
                    light_schedule TEXT,
                    light_wattage REAL,
                    temp_entity_id TEXT,
                    humidity_entity_id TEXT,
                    co2_entity_id TEXT,
                    light_entity_id TEXT,
                    exhaust_entity_id TEXT,
                    humidifier_entity_id TEXT,
                    camera_entity_id TEXT,
                    leaf_temp_offset_c REAL NOT NULL DEFAULT -2.0,
                    target_temp_min_c REAL,
                    target_temp_max_c REAL,
                    target_humidity_min REAL,
                    target_humidity_max REAL,
                    target_vpd_min REAL,
                    target_vpd_max REAL,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plants (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    strain TEXT,
                    breeder TEXT,
                    plant_type TEXT NOT NULL DEFAULT 'photoperiod',
                    medium TEXT NOT NULL DEFAULT 'soil',
                    pot_size TEXT,
                    environment_id TEXT,
                    grow_cycle_id TEXT,
                    stage TEXT NOT NULL DEFAULT 'germination',
                    started_at TEXT NOT NULL,
                    stage_started_at TEXT NOT NULL,
                    soil_moisture_entity_id TEXT,
                    camera_entity_id TEXT,
                    cover_photo_id TEXT,
                    expected_flower_days INTEGER,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (environment_id) REFERENCES environments(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS stage_history (
                    id TEXT PRIMARY KEY,
                    plant_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    notes TEXT,
                    FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS logs (
                    id TEXT PRIMARY KEY,
                    plant_id TEXT,
                    environment_id TEXT,
                    log_type TEXT NOT NULL,
                    title TEXT,
                    notes TEXT,
                    logged_at TEXT NOT NULL,
                    water_volume_ml REAL,
                    ph REAL,
                    ec REAL,
                    ppm REAL,
                    runoff_ph REAL,
                    runoff_ec REAL,
                    water_temp_c REAL,
                    nutrients_json TEXT,
                    height_cm REAL,
                    training_method TEXT,
                    temp_c REAL,
                    humidity REAL,
                    vpd_kpa REAL,
                    status TEXT NOT NULL DEFAULT 'completed',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE,
                    FOREIGN KEY (environment_id) REFERENCES environments(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS scheduled_stage_changes (
                    id TEXT PRIMARY KEY,
                    plant_id TEXT NOT NULL,
                    target_stage TEXT NOT NULL,
                    scheduled_for TEXT NOT NULL,
                    auto_apply INTEGER NOT NULL DEFAULT 1,
                    notes TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    applied_at TEXT,
                    FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS photos (
                    id TEXT PRIMARY KEY,
                    plant_id TEXT,
                    environment_id TEXT,
                    log_id TEXT,
                    stage TEXT,
                    filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    access_token TEXT NOT NULL,
                    caption TEXT,
                    source TEXT NOT NULL DEFAULT 'upload',
                    taken_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE,
                    FOREIGN KEY (environment_id) REFERENCES environments(id) ON DELETE SET NULL,
                    FOREIGN KEY (log_id) REFERENCES logs(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS nutrient_presets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    stage TEXT,
                    week_start INTEGER,
                    week_end INTEGER,
                    target_ph REAL,
                    target_ec REAL,
                    target_ppm REAL,
                    nutrients_json TEXT NOT NULL DEFAULT '[]',
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS grow_cycles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS harvests (
                    id TEXT PRIMARY KEY,
                    plant_id TEXT NOT NULL UNIQUE,
                    grow_cycle_id TEXT,
                    harvested_at TEXT NOT NULL,
                    wet_weight_g REAL,
                    dry_weight_g REAL,
                    trim_weight_g REAL,
                    dry_days INTEGER,
                    cure_start_at TEXT,
                    cure_rh_pct REAL,
                    light_wattage_override REAL,
                    aroma_notes TEXT,
                    effect_notes TEXT,
                    rating INTEGER,
                    is_keeper INTEGER NOT NULL DEFAULT 0,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE,
                    FOREIGN KEY (grow_cycle_id) REFERENCES grow_cycles(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS curing_logs (
                    id TEXT PRIMARY KEY,
                    harvest_id TEXT NOT NULL,
                    logged_at TEXT NOT NULL,
                    jar_rh_pct REAL,
                    jar_temp_c REAL,
                    burped INTEGER NOT NULL DEFAULT 1,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (harvest_id) REFERENCES harvests(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS reminders (
                    id TEXT PRIMARY KEY,
                    plant_id TEXT,
                    environment_id TEXT,
                    title TEXT NOT NULL,
                    action_type TEXT NOT NULL DEFAULT 'water',
                    due_at TEXT NOT NULL,
                    recurrence_days INTEGER,
                    moisture_threshold REAL,
                    auto_log_on_complete INTEGER NOT NULL DEFAULT 1,
                    preset_id TEXT,
                    notes TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    last_completed_at TEXT,
                    last_notified_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE,
                    FOREIGN KEY (environment_id) REFERENCES environments(id) ON DELETE SET NULL,
                    FOREIGN KEY (preset_id) REFERENCES nutrient_presets(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS pollen_batches (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    donor_plant_id TEXT,
                    donor_strain TEXT,
                    donor_type TEXT NOT NULL DEFAULT 'male',
                    collected_at TEXT NOT NULL,
                    storage_method TEXT,
                    storage_location TEXT,
                    viability TEXT NOT NULL DEFAULT 'high',
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (donor_plant_id) REFERENCES plants(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS seed_batches (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    breeder TEXT,
                    generation TEXT,
                    seed_type TEXT NOT NULL DEFAULT 'regular',
                    seed_count INTEGER NOT NULL DEFAULT 0,
                    breeding_cross_id TEXT,
                    mother_name TEXT,
                    father_name TEXT,
                    lineage_summary TEXT,
                    harvested_at TEXT,
                    storage_location TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS breeding_crosses (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    mother_plant_id TEXT,
                    mother_name TEXT,
                    mother_cross_id TEXT,
                    father_plant_id TEXT,
                    father_name TEXT,
                    father_cross_id TEXT,
                    pollen_batch_id TEXT,
                    generation TEXT NOT NULL DEFAULT 'F1',
                    pollination_date TEXT NOT NULL,
                    pollination_scope TEXT NOT NULL DEFAULT 'branch',
                    branch_tag TEXT,
                    expected_maturity_date TEXT,
                    seed_harvested_at TEXT,
                    seed_count INTEGER,
                    minted_seed_batch_id TEXT,
                    status TEXT NOT NULL DEFAULT 'pollinated',
                    goals TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (mother_plant_id) REFERENCES plants(id) ON DELETE SET NULL,
                    FOREIGN KEY (father_plant_id) REFERENCES plants(id) ON DELETE SET NULL,
                    FOREIGN KEY (pollen_batch_id) REFERENCES pollen_batches(id) ON DELETE SET NULL,
                    FOREIGN KEY (minted_seed_batch_id) REFERENCES seed_batches(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS pheno_hunts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    breeding_cross_id TEXT,
                    seed_batch_id TEXT,
                    strain TEXT,
                    breeder TEXT,
                    started_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    selection_goals TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (breeding_cross_id) REFERENCES breeding_crosses(id) ON DELETE SET NULL,
                    FOREIGN KEY (seed_batch_id) REFERENCES seed_batches(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS pheno_scores (
                    id TEXT PRIMARY KEY,
                    pheno_hunt_id TEXT NOT NULL,
                    plant_id TEXT NOT NULL,
                    pheno_code TEXT,
                    status TEXT NOT NULL DEFAULT 'evaluating',
                    vigor INTEGER,
                    stretch_factor REAL,
                    internode_spacing TEXT,
                    resin_density INTEGER,
                    pest_mold_resistance INTEGER,
                    aroma_score INTEGER,
                    terpene_notes TEXT,
                    flower_days INTEGER,
                    yield_g REAL,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (pheno_hunt_id, plant_id),
                    FOREIGN KEY (pheno_hunt_id) REFERENCES pheno_hunts(id) ON DELETE CASCADE,
                    FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS reservoirs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    environment_id TEXT,
                    capacity_l REAL NOT NULL DEFAULT 40.0,
                    current_volume_l REAL,
                    ec_entity_id TEXT,
                    ph_entity_id TEXT,
                    water_temp_entity_id TEXT,
                    level_entity_id TEXT,
                    low_level_entity_id TEXT,
                    leak_entity_id TEXT,
                    ro_fill_entity_id TEXT,
                    circ_pump_entity_id TEXT,
                    master_feed_pump_entity_id TEXT,
                    target_ec REAL,
                    target_ph REAL,
                    ec_tolerance REAL NOT NULL DEFAULT 0.1,
                    ph_tolerance REAL NOT NULL DEFAULT 0.15,
                    auto_trim_enabled INTEGER NOT NULL DEFAULT 0,
                    auto_ro_topoff INTEGER NOT NULL DEFAULT 0,
                    settle_delay_s INTEGER NOT NULL DEFAULT 180,
                    ph_min_bound REAL NOT NULL DEFAULT 3.5,
                    ph_max_bound REAL NOT NULL DEFAULT 9.5,
                    ec_max_bound REAL NOT NULL DEFAULT 5.0,
                    status TEXT NOT NULL DEFAULT 'idle',
                    last_error TEXT,
                    last_mixed_at TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (environment_id) REFERENCES environments(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS dosing_channels (
                    id TEXT PRIMARY KEY,
                    reservoir_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'additive',
                    nutrient_name TEXT,
                    entity_id TEXT,
                    control_type TEXT NOT NULL DEFAULT 'switch',
                    esphome_service TEXT,
                    flow_rate_ml_s REAL NOT NULL DEFAULT 1.0,
                    mix_order INTEGER NOT NULL DEFAULT 60,
                    stir_delay_s INTEGER NOT NULL DEFAULT 30,
                    bottle_capacity_ml REAL NOT NULL DEFAULT 1000.0,
                    bottle_remaining_ml REAL NOT NULL DEFAULT 1000.0,
                    low_bottle_alert_ml REAL NOT NULL DEFAULT 100.0,
                    max_dose_per_cycle_ml REAL NOT NULL DEFAULT 50.0,
                    max_daily_dose_ml REAL NOT NULL DEFAULT 200.0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (reservoir_id) REFERENCES reservoirs(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS dosing_runs (
                    id TEXT PRIMARY KEY,
                    reservoir_id TEXT NOT NULL,
                    channel_id TEXT,
                    preset_id TEXT,
                    run_type TEXT NOT NULL DEFAULT 'batch_mix',
                    status TEXT NOT NULL DEFAULT 'completed',
                    target_volume_l REAL,
                    dosed_ml REAL NOT NULL DEFAULT 0.0,
                    steps_json TEXT NOT NULL DEFAULT '[]',
                    start_ph REAL,
                    start_ec REAL,
                    end_ph REAL,
                    end_ec REAL,
                    abort_reason TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    FOREIGN KEY (reservoir_id) REFERENCES reservoirs(id) ON DELETE CASCADE,
                    FOREIGN KEY (channel_id) REFERENCES dosing_channels(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS fertigation_schedules (
                    id TEXT PRIMARY KEY,
                    plant_id TEXT NOT NULL UNIQUE,
                    reservoir_id TEXT,
                    mode TEXT NOT NULL DEFAULT 'off',
                    schedule_type TEXT NOT NULL DEFAULT 'high_frequency',
                    pump_entity_id TEXT,
                    valve_entity_id TEXT,
                    use_shared_pump INTEGER NOT NULL DEFAULT 0,
                    esphome_watchdog_entity_id TEXT,
                    flow_rate_ml_s REAL NOT NULL DEFAULT 10.0,
                    feeds_per_day INTEGER NOT NULL DEFAULT 4,
                    shot_duration_s REAL NOT NULL DEFAULT 15.0,
                    target_shot_ml REAL,
                    window_start TEXT NOT NULL DEFAULT '08:00',
                    window_end TEXT NOT NULL DEFAULT '20:00',
                    p1_ramp_shots INTEGER NOT NULL DEFAULT 2,
                    p1_interval_min INTEGER NOT NULL DEFAULT 30,
                    p3_dryback_cutoff_min INTEGER NOT NULL DEFAULT 120,
                    interval_hours REAL NOT NULL DEFAULT 6.0,
                    fixed_times_json TEXT NOT NULL DEFAULT '[]',
                    moisture_threshold_pct REAL NOT NULL DEFAULT 35.0,
                    moisture_cooldown_min INTEGER NOT NULL DEFAULT 90,
                    max_shot_duration_s REAL NOT NULL DEFAULT 60.0,
                    max_daily_volume_ml REAL NOT NULL DEFAULT 4000.0,
                    leak_entity_id TEXT,
                    auto_log_action TEXT NOT NULL DEFAULT 'feed',
                    last_fed_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE,
                    FOREIGN KEY (reservoir_id) REFERENCES reservoirs(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS fertigation_events (
                    id TEXT PRIMARY KEY,
                    plant_id TEXT NOT NULL,
                    schedule_id TEXT,
                    reservoir_id TEXT,
                    trigger_type TEXT NOT NULL DEFAULT 'manual',
                    duration_s REAL NOT NULL DEFAULT 0.0,
                    volume_ml REAL NOT NULL DEFAULT 0.0,
                    status TEXT NOT NULL DEFAULT 'completed',
                    block_reason TEXT,
                    reservoir_ph REAL,
                    reservoir_ec REAL,
                    logged_at TEXT NOT NULL,
                    FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE,
                    FOREIGN KEY (schedule_id) REFERENCES fertigation_schedules(id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_plants_env ON plants(environment_id);
                CREATE INDEX IF NOT EXISTS idx_stage_history_plant ON stage_history(plant_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_logs_plant_logged ON logs(plant_id, logged_at DESC);
                CREATE INDEX IF NOT EXISTS idx_logs_env_logged ON logs(environment_id, logged_at DESC);
                CREATE INDEX IF NOT EXISTS idx_logs_logged ON logs(logged_at DESC);
                CREATE INDEX IF NOT EXISTS idx_photos_plant_taken ON photos(plant_id, taken_at DESC);
                CREATE INDEX IF NOT EXISTS idx_photos_taken ON photos(taken_at DESC);
                CREATE INDEX IF NOT EXISTS idx_presets_stage ON nutrient_presets(stage, week_start);
                CREATE INDEX IF NOT EXISTS idx_sched_stage_pending ON scheduled_stage_changes(status, scheduled_for);
                CREATE INDEX IF NOT EXISTS idx_harvests_date ON harvests(harvested_at DESC);
                CREATE INDEX IF NOT EXISTS idx_curing_harvest ON curing_logs(harvest_id, logged_at DESC);
                CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, due_at ASC);
                CREATE INDEX IF NOT EXISTS idx_pollen_collected ON pollen_batches(collected_at DESC);
                CREATE INDEX IF NOT EXISTS idx_crosses_date ON breeding_crosses(pollination_date DESC);
                CREATE INDEX IF NOT EXISTS idx_pheno_scores_hunt ON pheno_scores(pheno_hunt_id);
                CREATE INDEX IF NOT EXISTS idx_dosing_channels_res ON dosing_channels(reservoir_id, mix_order ASC);
                CREATE INDEX IF NOT EXISTS idx_dosing_runs_res ON dosing_runs(reservoir_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_fert_events_plant ON fertigation_events(plant_id, logged_at DESC);
                """
            )
            # Safe additive migrations for pre-v6 databases
            log_cols = {
                r["name"] for r in conn.execute("PRAGMA table_info(logs)").fetchall()
            }
            if "status" not in log_cols:
                conn.execute(
                    "ALTER TABLE logs ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'"
                )
            env_cols = {
                r["name"]
                for r in conn.execute("PRAGMA table_info(environments)").fetchall()
            }
            if "light_wattage" not in env_cols:
                conn.execute("ALTER TABLE environments ADD COLUMN light_wattage REAL")
            plant_cols = {
                r["name"] for r in conn.execute("PRAGMA table_info(plants)").fetchall()
            }
            if "grow_cycle_id" not in plant_cols:
                conn.execute("ALTER TABLE plants ADD COLUMN grow_cycle_id TEXT")
            if "breeding_cross_id" not in plant_cols:
                conn.execute("ALTER TABLE plants ADD COLUMN breeding_cross_id TEXT")
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    # ------------------------------------------------------------------
    # Full snapshot query (fast single-connection read for coordinator)
    # ------------------------------------------------------------------
    async def async_get_snapshot(self) -> dict[str, Any]:
        """Fetch environments, plants, per-plant metrics, recent logs, and photos."""
        return await self._run(self._get_snapshot_sync)

    def _get_snapshot_sync(self) -> dict[str, Any]:
        with self._connect() as conn:
            environments = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM environments ORDER BY created_at ASC"
                ).fetchall()
            ]
            plants = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM plants ORDER BY created_at ASC"
                ).fetchall()
            ]
            stage_rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM stage_history ORDER BY started_at ASC"
                ).fetchall()
            ]
            recent_logs = [
                _deserialize_log(r)
                for r in conn.execute(
                    """
                    SELECT * FROM logs
                    WHERE status = 'completed'
                    ORDER BY logged_at DESC, created_at DESC LIMIT 60
                    """
                ).fetchall()
            ]
            planned_logs = [
                _deserialize_log(r)
                for r in conn.execute(
                    """
                    SELECT * FROM logs
                    WHERE status = 'planned'
                    ORDER BY logged_at ASC, created_at ASC LIMIT 60
                    """
                ).fetchall()
            ]
            scheduled_stage_changes = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT * FROM scheduled_stage_changes
                    WHERE status = 'pending'
                    ORDER BY scheduled_for ASC
                    """
                ).fetchall()
            ]
            recent_photos = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM photos ORDER BY taken_at DESC, created_at DESC LIMIT 60"
                ).fetchall()
            ]
            nutrient_presets = [
                _deserialize_preset(r)
                for r in conn.execute(
                    """
                    SELECT * FROM nutrient_presets
                    ORDER BY stage IS NULL ASC, stage ASC, week_start IS NULL ASC, week_start ASC, name ASC
                    """
                ).fetchall()
            ]
            grow_cycles = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM grow_cycles ORDER BY started_at DESC, created_at DESC"
                ).fetchall()
            ]
            harvests = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM harvests ORDER BY harvested_at DESC, created_at DESC"
                ).fetchall()
            ]
            curing_logs = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM curing_logs ORDER BY logged_at DESC, created_at DESC"
                ).fetchall()
            ]
            reminders = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM reminders ORDER BY status ASC, due_at ASC, created_at ASC"
                ).fetchall()
            ]
            pollen_batches = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM pollen_batches ORDER BY collected_at DESC, created_at DESC"
                ).fetchall()
            ]
            seed_batches = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM seed_batches ORDER BY created_at DESC"
                ).fetchall()
            ]
            breeding_crosses = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM breeding_crosses ORDER BY pollination_date DESC, created_at DESC"
                ).fetchall()
            ]
            pheno_hunts = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM pheno_hunts ORDER BY started_at DESC, created_at DESC"
                ).fetchall()
            ]
            pheno_scores = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM pheno_scores ORDER BY pheno_code ASC, created_at ASC"
                ).fetchall()
            ]
            reservoirs = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM reservoirs ORDER BY created_at ASC"
                ).fetchall()
            ]
            dosing_channels = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM dosing_channels ORDER BY reservoir_id ASC, mix_order ASC, name ASC"
                ).fetchall()
            ]
            dosing_runs = []
            for r in conn.execute(
                "SELECT * FROM dosing_runs ORDER BY started_at DESC LIMIT 60"
            ).fetchall():
                item = dict(r)
                raw_steps = item.pop("steps_json", "[]")
                try:
                    item["steps"] = json.loads(raw_steps) if raw_steps else []
                except (ValueError, TypeError):
                    item["steps"] = []
                dosing_runs.append(item)

            fertigation_schedules = []
            for r in conn.execute(
                "SELECT * FROM fertigation_schedules ORDER BY created_at ASC"
            ).fetchall():
                item = dict(r)
                raw_times = item.pop("fixed_times_json", "[]")
                try:
                    item["fixed_times"] = json.loads(raw_times) if raw_times else []
                except (ValueError, TypeError):
                    item["fixed_times"] = []
                fertigation_schedules.append(item)

            fertigation_events = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM fertigation_events ORDER BY logged_at DESC LIMIT 80"
                ).fetchall()
            ]

            today_prefix = utc_now_iso()[:10]
            daily_fert_vol: dict[str, float] = {}
            for r in conn.execute(
                """
                SELECT plant_id, COALESCE(SUM(volume_ml), 0) AS total_ml
                FROM fertigation_events
                WHERE status = 'completed' AND logged_at >= ?
                GROUP BY plant_id
                """,
                (today_prefix,),
            ).fetchall():
                daily_fert_vol[r["plant_id"]] = round(float(r["total_ml"]), 1)

            daily_channel_dose: dict[str, float] = {}
            for r in conn.execute(
                """
                SELECT steps_json FROM dosing_runs
                WHERE status = 'completed' AND started_at >= ?
                """,
                (today_prefix,),
            ).fetchall():
                try:
                    steps = json.loads(r["steps_json"] or "[]")
                except (ValueError, TypeError):
                    steps = []
                for st in steps:
                    cid = st.get("channel_id")
                    if cid:
                        daily_channel_dose[cid] = round(
                            daily_channel_dose.get(cid, 0.0)
                            + float(st.get("dose_ml") or 0.0),
                            2,
                        )

            # Per-plant aggregates (completed logs only — planned future entries excluded)
            plant_stats: dict[str, dict[str, Any]] = {}
            for p in plants:
                pid = p["id"]
                last_water = conn.execute(
                    """
                    SELECT logged_at, water_volume_ml, ph, ec
                    FROM logs
                    WHERE plant_id = ? AND status = 'completed'
                      AND log_type IN ('water', 'feed', 'flush')
                    ORDER BY logged_at DESC LIMIT 1
                    """,
                    (pid,),
                ).fetchone()
                last_feed = conn.execute(
                    """
                    SELECT logged_at, ph, ec, ppm
                    FROM logs
                    WHERE plant_id = ? AND status = 'completed' AND log_type = 'feed'
                    ORDER BY logged_at DESC LIMIT 1
                    """,
                    (pid,),
                ).fetchone()
                last_ph_ec = conn.execute(
                    """
                    SELECT ph, ec, ppm, logged_at
                    FROM logs
                    WHERE plant_id = ? AND status = 'completed'
                      AND (ph IS NOT NULL OR ec IS NOT NULL)
                    ORDER BY logged_at DESC LIMIT 1
                    """,
                    (pid,),
                ).fetchone()
                last_height = conn.execute(
                    """
                    SELECT height_cm, logged_at
                    FROM logs
                    WHERE plant_id = ? AND status = 'completed'
                      AND height_cm IS NOT NULL
                    ORDER BY logged_at DESC LIMIT 1
                    """,
                    (pid,),
                ).fetchone()
                log_count = conn.execute(
                    "SELECT COUNT(*) FROM logs WHERE plant_id = ? AND status = 'completed'",
                    (pid,),
                ).fetchone()[0]
                planned_log_count = conn.execute(
                    "SELECT COUNT(*) FROM logs WHERE plant_id = ? AND status = 'planned'",
                    (pid,),
                ).fetchone()[0]
                photo_count = conn.execute(
                    "SELECT COUNT(*) FROM photos WHERE plant_id = ?", (pid,)
                ).fetchone()[0]

                cover_photo = None
                if p.get("cover_photo_id"):
                    cover_photo = _row_to_dict(
                        conn.execute(
                            "SELECT id, access_token FROM photos WHERE id = ?",
                            (p["cover_photo_id"],),
                        ).fetchone()
                    )
                if cover_photo is None:
                    cover_photo = _row_to_dict(
                        conn.execute(
                            """
                            SELECT id, access_token FROM photos
                            WHERE plant_id = ?
                            ORDER BY taken_at DESC, created_at DESC LIMIT 1
                            """,
                            (pid,),
                        ).fetchone()
                    )

                plant_stats[pid] = {
                    "last_watered_at": last_water["logged_at"] if last_water else None,
                    "last_water_volume_ml": (
                        last_water["water_volume_ml"] if last_water else None
                    ),
                    "last_fed_at": last_feed["logged_at"] if last_feed else None,
                    "last_ph": last_ph_ec["ph"] if last_ph_ec else None,
                    "last_ec": last_ph_ec["ec"] if last_ph_ec else None,
                    "last_ppm": last_ph_ec["ppm"] if last_ph_ec else None,
                    "latest_height_cm": (
                        last_height["height_cm"] if last_height else None
                    ),
                    "log_count": log_count,
                    "planned_log_count": planned_log_count,
                    "photo_count": photo_count,
                    "cover_photo": cover_photo,
                }

            total_logs = conn.execute(
                "SELECT COUNT(*) FROM logs WHERE status = 'completed'"
            ).fetchone()[0]
            total_photos = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]

            return {
                "environments": environments,
                "plants": plants,
                "stage_history": stage_rows,
                "plant_stats": plant_stats,
                "recent_logs": recent_logs,
                "planned_logs": planned_logs,
                "scheduled_stage_changes": scheduled_stage_changes,
                "recent_photos": recent_photos,
                "nutrient_presets": nutrient_presets,
                "grow_cycles": grow_cycles,
                "harvests": harvests,
                "curing_logs": curing_logs,
                "reminders": reminders,
                "pollen_batches": pollen_batches,
                "seed_batches": seed_batches,
                "breeding_crosses": breeding_crosses,
                "pheno_hunts": pheno_hunts,
                "pheno_scores": pheno_scores,
                "reservoirs": reservoirs,
                "dosing_channels": dosing_channels,
                "dosing_runs": dosing_runs,
                "fertigation_schedules": fertigation_schedules,
                "fertigation_events": fertigation_events,
                "daily_fert_vol": daily_fert_vol,
                "daily_channel_dose": daily_channel_dose,
                "totals": {
                    "logs": total_logs,
                    "photos": total_photos,
                },
            }

    # ------------------------------------------------------------------
    # Environments CRUD
    # ------------------------------------------------------------------
    async def async_create_environment(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new grow environment (tent/room)."""
        return await self._run(self._create_environment_sync, data)

    def _create_environment_sync(self, data: dict[str, Any]) -> dict[str, Any]:
        env_id = data.get("id") or uuid.uuid4().hex[:12]
        now = utc_now_iso()
        record = {
            "id": env_id,
            "name": (data.get("name") or "Grow Tent").strip(),
            "env_type": data.get("env_type") or "tent",
            "dimensions": data.get("dimensions"),
            "light_schedule": data.get("light_schedule") or "18/6",
            "light_wattage": data.get("light_wattage"),
            "temp_entity_id": data.get("temp_entity_id") or None,
            "humidity_entity_id": data.get("humidity_entity_id") or None,
            "co2_entity_id": data.get("co2_entity_id") or None,
            "light_entity_id": data.get("light_entity_id") or None,
            "exhaust_entity_id": data.get("exhaust_entity_id") or None,
            "humidifier_entity_id": data.get("humidifier_entity_id") or None,
            "camera_entity_id": data.get("camera_entity_id") or None,
            "leaf_temp_offset_c": (
                float(data["leaf_temp_offset_c"])
                if data.get("leaf_temp_offset_c") is not None
                else DEFAULT_LEAF_TEMP_OFFSET_C
            ),
            "target_temp_min_c": data.get("target_temp_min_c"),
            "target_temp_max_c": data.get("target_temp_max_c"),
            "target_humidity_min": data.get("target_humidity_min"),
            "target_humidity_max": data.get("target_humidity_max"),
            "target_vpd_min": data.get("target_vpd_min"),
            "target_vpd_max": data.get("target_vpd_max"),
            "notes": data.get("notes"),
            "created_at": now,
            "updated_at": now,
        }
        cols = ", ".join(record.keys())
        placeholders = ", ".join(["?"] * len(record))
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO environments ({cols}) VALUES ({placeholders})",
                list(record.values()),
            )
        return record

    async def async_update_environment(
        self, env_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update an existing environment."""
        return await self._run(self._update_environment_sync, env_id, data)

    def _update_environment_sync(
        self, env_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "name",
            "env_type",
            "dimensions",
            "light_schedule",
            "light_wattage",
            "temp_entity_id",
            "humidity_entity_id",
            "co2_entity_id",
            "light_entity_id",
            "exhaust_entity_id",
            "humidifier_entity_id",
            "camera_entity_id",
            "leaf_temp_offset_c",
            "target_temp_min_c",
            "target_temp_max_c",
            "target_humidity_min",
            "target_humidity_max",
            "target_vpd_min",
            "target_vpd_max",
            "notes",
        }
        updates = {k: v for k, v in data.items() if k in allowed}
        if "name" in updates and not updates["name"]:
            updates.pop("name")
        if "env_type" in updates and not updates["env_type"]:
            updates.pop("env_type")
        if "leaf_temp_offset_c" in updates and updates["leaf_temp_offset_c"] is None:
            updates["leaf_temp_offset_c"] = DEFAULT_LEAF_TEMP_OFFSET_C
        if not updates:
            return self._get_environment_sync(env_id)
        updates["updated_at"] = utc_now_iso()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE environments SET {set_clause} WHERE id = ?",
                [*updates.values(), env_id],
            )
            row = conn.execute(
                "SELECT * FROM environments WHERE id = ?", (env_id,)
            ).fetchone()
            return _row_to_dict(row)

    def _get_environment_sync(self, env_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM environments WHERE id = ?", (env_id,)
            ).fetchone()
            return _row_to_dict(row)

    async def async_delete_environment(self, env_id: str) -> bool:
        """Delete an environment (plants keep existing with environment_id=NULL)."""
        return await self._run(self._delete_environment_sync, env_id)

    def _delete_environment_sync(self, env_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM environments WHERE id = ?", (env_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Plants CRUD & Stage Management
    # ------------------------------------------------------------------
    async def async_create_plant(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new plant and initial stage_history record."""
        return await self._run(self._create_plant_sync, data)

    def _create_plant_sync(self, data: dict[str, Any]) -> dict[str, Any]:
        plant_id = data.get("id") or uuid.uuid4().hex[:12]
        now = utc_now_iso()
        started_at = data.get("started_at") or now
        stage = data.get("stage") or STAGE_GERMINATION
        if stage not in GROW_STAGES:
            stage = STAGE_GERMINATION
        stage_started_at = data.get("stage_started_at") or started_at

        record = {
            "id": plant_id,
            "name": (data.get("name") or "New Plant").strip(),
            "strain": data.get("strain") or None,
            "breeder": data.get("breeder") or None,
            "plant_type": data.get("plant_type") or "photoperiod",
            "medium": data.get("medium") or "soil",
            "pot_size": data.get("pot_size") or None,
            "environment_id": data.get("environment_id") or None,
            "grow_cycle_id": data.get("grow_cycle_id") or None,
            "stage": stage,
            "started_at": started_at,
            "stage_started_at": stage_started_at,
            "soil_moisture_entity_id": data.get("soil_moisture_entity_id") or None,
            "camera_entity_id": data.get("camera_entity_id") or None,
            "cover_photo_id": data.get("cover_photo_id") or None,
            "expected_flower_days": data.get("expected_flower_days"),
            "notes": data.get("notes") or None,
            "created_at": now,
            "updated_at": now,
        }
        cols = ", ".join(record.keys())
        placeholders = ", ".join(["?"] * len(record))
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO plants ({cols}) VALUES ({placeholders})",
                list(record.values()),
            )
            conn.execute(
                """
                INSERT INTO stage_history (id, plant_id, stage, started_at, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (uuid.uuid4().hex[:12], plant_id, stage, stage_started_at, "Initial stage"),
            )
        return record

    async def async_get_plant(self, plant_id: str) -> dict[str, Any] | None:
        """Fetch a single plant by ID."""
        return await self._run(self._get_plant_sync, plant_id)

    def _get_plant_sync(self, plant_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM plants WHERE id = ?", (plant_id,)
            ).fetchone()
            return _row_to_dict(row)

    async def async_update_plant(
        self, plant_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update plant metadata (if stage changes, records stage_history too)."""
        return await self._run(self._update_plant_sync, plant_id, data)

    def _update_plant_sync(
        self, plant_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "name",
            "strain",
            "breeder",
            "plant_type",
            "medium",
            "pot_size",
            "environment_id",
            "grow_cycle_id",
            "started_at",
            "stage_started_at",
            "soil_moisture_entity_id",
            "camera_entity_id",
            "cover_photo_id",
            "expected_flower_days",
            "notes",
        }
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM plants WHERE id = ?", (plant_id,)
            ).fetchone()
            if not existing:
                return None

            new_stage = data.get("stage")
            if new_stage and new_stage in GROW_STAGES and new_stage != existing["stage"]:
                self._set_stage_in_conn(
                    conn,
                    plant_id,
                    new_stage,
                    notes=data.get("stage_notes"),
                    changed_at=data.get("stage_started_at"),
                )

            updates = {k: v for k, v in data.items() if k in allowed}
            for non_null in ("name", "plant_type", "medium", "started_at", "stage_started_at"):
                if non_null in updates and not updates[non_null]:
                    updates.pop(non_null)
            if updates:
                updates["updated_at"] = utc_now_iso()
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE plants SET {set_clause} WHERE id = ?",
                    [*updates.values(), plant_id],
                )

            row = conn.execute(
                "SELECT * FROM plants WHERE id = ?", (plant_id,)
            ).fetchone()
            return _row_to_dict(row)

    async def async_set_plant_stage(
        self,
        plant_id: str,
        stage: str,
        notes: str | None = None,
        changed_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Transition a plant to a new grow stage and log the stage change."""
        if stage not in GROW_STAGES:
            raise ValueError(f"Invalid grow stage: {stage}")
        return await self._run(
            self._set_plant_stage_sync, plant_id, stage, notes, changed_at
        )

    def _recalculate_plant_stage_from_history(
        self, conn: sqlite3.Connection, plant_id: str
    ) -> dict[str, Any] | None:
        """Sort stage_history chronologically, chain ended_at, and sync plant.stage."""
        rows = conn.execute(
            "SELECT rowid, * FROM stage_history WHERE plant_id = ?", (plant_id,)
        ).fetchall()
        if not rows:
            row = conn.execute("SELECT * FROM plants WHERE id = ?", (plant_id,)).fetchone()
            return _row_to_dict(row)

        def _sort_key(r: sqlite3.Row) -> tuple[float, int]:
            dt = parse_iso_datetime(r["started_at"])
            return (dt.timestamp() if dt else 0.0, int(r["rowid"]))

        ordered = sorted(rows, key=_sort_key)
        for idx, item in enumerate(ordered):
            next_start = ordered[idx + 1]["started_at"] if idx + 1 < len(ordered) else None
            if item["ended_at"] != next_start:
                conn.execute(
                    "UPDATE stage_history SET ended_at = ? WHERE id = ?",
                    (next_start, item["id"]),
                )

        latest = ordered[-1]
        conn.execute(
            """
            UPDATE plants
            SET stage = ?, stage_started_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (latest["stage"], latest["started_at"], utc_now_iso(), plant_id),
        )
        row = conn.execute("SELECT * FROM plants WHERE id = ?", (plant_id,)).fetchone()
        return _row_to_dict(row)

    def _set_stage_in_conn(
        self,
        conn: sqlite3.Connection,
        plant_id: str,
        stage: str,
        notes: str | None = None,
        changed_at: str | None = None,
    ) -> dict[str, Any] | None:
        existing = conn.execute(
            "SELECT * FROM plants WHERE id = ?", (plant_id,)
        ).fetchone()
        if not existing:
            return None

        when = changed_at or utc_now_iso()
        old_stage = existing["stage"]
        if old_stage == stage and not changed_at:
            return dict(existing)

        # Insert stage_history entry and chronologically recalculate chain
        conn.execute(
            """
            INSERT INTO stage_history (id, plant_id, stage, started_at, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (uuid.uuid4().hex[:12], plant_id, stage, when, notes),
        )
        updated = self._recalculate_plant_stage_from_history(conn, plant_id)

        # Automatically add a journal entry for the stage transition
        conn.execute(
            """
            INSERT INTO logs (
                id, plant_id, environment_id, log_type, title, notes, logged_at, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', ?)
            """,
            (
                uuid.uuid4().hex[:12],
                plant_id,
                existing["environment_id"],
                LOG_TYPE_STAGE_CHANGE,
                f"Stage changed: {old_stage.title()} → {stage.title()}",
                notes,
                when,
                utc_now_iso(),
            ),
        )
        return updated

    # ------------------------------------------------------------------
    # Retrospective Stage History CRUD
    # ------------------------------------------------------------------
    async def async_add_stage_history(
        self,
        plant_id: str,
        stage: str,
        started_at: str,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        """Insert a retrospective stage history entry and recalculate timeline."""
        if stage not in GROW_STAGES:
            raise ValueError(f"Invalid grow stage: {stage}")
        return await self._run(
            self._add_stage_history_sync, plant_id, stage, started_at, notes
        )

    def _add_stage_history_sync(
        self, plant_id: str, stage: str, started_at: str, notes: str | None
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM plants WHERE id = ?", (plant_id,)
            ).fetchone()
            if not existing:
                return None
            hist_id = uuid.uuid4().hex[:12]
            conn.execute(
                """
                INSERT INTO stage_history (id, plant_id, stage, started_at, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (hist_id, plant_id, stage, started_at, notes),
            )
            self._recalculate_plant_stage_from_history(conn, plant_id)
            row = conn.execute(
                "SELECT * FROM stage_history WHERE id = ?", (hist_id,)
            ).fetchone()
            return _row_to_dict(row)

    async def async_update_stage_history(
        self, history_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update a stage history entry and recalculate the plant's stage chain."""
        return await self._run(self._update_stage_history_sync, history_id, data)

    def _update_stage_history_sync(
        self, history_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM stage_history WHERE id = ?", (history_id,)
            ).fetchone()
            if not existing:
                return None

            updates: dict[str, Any] = {}
            if "stage" in data and data["stage"] in GROW_STAGES:
                updates["stage"] = data["stage"]
            if "started_at" in data and data["started_at"]:
                updates["started_at"] = data["started_at"]
            if "notes" in data:
                updates["notes"] = data["notes"] or None

            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE stage_history SET {set_clause} WHERE id = ?",
                    [*updates.values(), history_id],
                )
                self._recalculate_plant_stage_from_history(conn, existing["plant_id"])

            row = conn.execute(
                "SELECT * FROM stage_history WHERE id = ?", (history_id,)
            ).fetchone()
            return _row_to_dict(row)

    async def async_delete_stage_history(self, history_id: str) -> bool:
        """Delete a stage history entry (if >1 remains) and recalculate timeline."""
        return await self._run(self._delete_stage_history_sync, history_id)

    def _delete_stage_history_sync(self, history_id: str) -> bool:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT plant_id FROM stage_history WHERE id = ?", (history_id,)
            ).fetchone()
            if not existing:
                return False
            plant_id = existing["plant_id"]
            count = conn.execute(
                "SELECT COUNT(*) FROM stage_history WHERE plant_id = ?", (plant_id,)
            ).fetchone()[0]
            if count <= 1:
                raise ValueError("Cannot delete the only stage history entry for a plant")
            conn.execute("DELETE FROM stage_history WHERE id = ?", (history_id,))
            self._recalculate_plant_stage_from_history(conn, plant_id)
            return True

    # ------------------------------------------------------------------
    # Scheduled Future Stage Changes CRUD & Auto-Apply
    # ------------------------------------------------------------------
    async def async_schedule_stage_change(
        self,
        plant_id: str,
        target_stage: str,
        scheduled_for: str,
        auto_apply: bool = True,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Schedule a future stage transition for a plant."""
        if target_stage not in GROW_STAGES:
            raise ValueError(f"Invalid grow stage: {target_stage}")
        return await self._run(
            self._schedule_stage_change_sync,
            plant_id,
            target_stage,
            scheduled_for,
            auto_apply,
            notes,
        )

    def _schedule_stage_change_sync(
        self,
        plant_id: str,
        target_stage: str,
        scheduled_for: str,
        auto_apply: bool,
        notes: str | None,
    ) -> dict[str, Any]:
        sched_id = uuid.uuid4().hex[:12]
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scheduled_stage_changes (
                    id, plant_id, target_stage, scheduled_for, auto_apply, notes, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    sched_id,
                    plant_id,
                    target_stage,
                    scheduled_for,
                    1 if auto_apply else 0,
                    notes,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM scheduled_stage_changes WHERE id = ?", (sched_id,)
            ).fetchone()
            return dict(row)

    async def async_cancel_scheduled_stage_change(self, schedule_id: str) -> bool:
        """Cancel a pending scheduled stage change."""
        return await self._run(self._cancel_scheduled_stage_change_sync, schedule_id)

    def _cancel_scheduled_stage_change_sync(self, schedule_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE scheduled_stage_changes SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
                (schedule_id,),
            )
            return cur.rowcount > 0

    async def async_apply_scheduled_stage_change(
        self, schedule_id: str
    ) -> dict[str, Any] | None:
        """Apply a pending scheduled stage change immediately."""
        return await self._run(self._apply_scheduled_stage_change_sync, schedule_id)

    def _apply_scheduled_stage_change_sync(
        self, schedule_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM scheduled_stage_changes WHERE id = ? AND status = 'pending'",
                (schedule_id,),
            ).fetchone()
            if not row:
                return None
            now = utc_now_iso()
            self._set_stage_in_conn(
                conn,
                row["plant_id"],
                row["target_stage"],
                notes=row["notes"],
                changed_at=now,
            )
            conn.execute(
                "UPDATE scheduled_stage_changes SET status = 'applied', applied_at = ? WHERE id = ?",
                (now, schedule_id),
            )
            return {
                "schedule_id": schedule_id,
                "plant_id": row["plant_id"],
                "stage": row["target_stage"],
            }

    async def async_process_due_stage_changes(
        self, now_iso: str | None = None
    ) -> list[dict[str, Any]]:
        """Auto-apply all pending scheduled stage changes whose scheduled_for <= now."""
        return await self._run(self._process_due_stage_changes_sync, now_iso)

    def _process_due_stage_changes_sync(
        self, now_iso: str | None
    ) -> list[dict[str, Any]]:
        now_dt = parse_iso_datetime(now_iso) or datetime.now(UTC)
        now_str = now_dt.replace(microsecond=0).isoformat()
        applied: list[dict[str, Any]] = []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM scheduled_stage_changes
                WHERE status = 'pending' AND auto_apply = 1
                ORDER BY scheduled_for ASC
                """
            ).fetchall()
            for row in rows:
                sched_dt = parse_iso_datetime(row["scheduled_for"])
                if sched_dt is None or sched_dt > now_dt:
                    continue
                self._set_stage_in_conn(
                    conn,
                    row["plant_id"],
                    row["target_stage"],
                    notes=row["notes"] or "Scheduled stage transition",
                    changed_at=row["scheduled_for"],
                )
                conn.execute(
                    "UPDATE scheduled_stage_changes SET status = 'applied', applied_at = ? WHERE id = ?",
                    (now_str, row["id"]),
                )
                applied.append(
                    {
                        "schedule_id": row["id"],
                        "plant_id": row["plant_id"],
                        "stage": row["target_stage"],
                    }
                )
        return applied

    def _set_plant_stage_sync(
        self,
        plant_id: str,
        stage: str,
        notes: str | None,
        changed_at: str | None,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._set_stage_in_conn(conn, plant_id, stage, notes, changed_at)

    async def async_delete_plant(self, plant_id: str) -> list[str]:
        """Delete a plant and return filenames of any cascade-deleted photos."""
        return await self._run(self._delete_plant_sync, plant_id)

    def _delete_plant_sync(self, plant_id: str) -> list[str]:
        with self._connect() as conn:
            photos = conn.execute(
                "SELECT filename FROM photos WHERE plant_id = ?", (plant_id,)
            ).fetchall()
            filenames = [r["filename"] for r in photos]
            conn.execute("DELETE FROM plants WHERE id = ?", (plant_id,))
            return filenames

    # ------------------------------------------------------------------
    # Logs / Journal CRUD
    # ------------------------------------------------------------------
    async def async_create_log(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a grow journal log entry."""
        return await self._run(self._create_log_sync, data)

    def _create_log_sync(self, data: dict[str, Any]) -> dict[str, Any]:
        log_id = data.get("id") or uuid.uuid4().hex[:12]
        now = utc_now_iso()
        logged_at = data.get("logged_at") or now
        status = data.get("status")
        if status not in ("completed", "planned"):
            status = "planned" if is_timestamp_in_future(logged_at) else "completed"
        nutrients = data.get("nutrients")
        nutrients_json = json.dumps(nutrients) if nutrients else None

        record = {
            "id": log_id,
            "plant_id": data.get("plant_id") or None,
            "environment_id": data.get("environment_id") or None,
            "log_type": data.get("log_type") or "note",
            "title": data.get("title") or None,
            "notes": data.get("notes") or None,
            "logged_at": logged_at,
            "water_volume_ml": data.get("water_volume_ml"),
            "ph": data.get("ph"),
            "ec": data.get("ec"),
            "ppm": data.get("ppm"),
            "runoff_ph": data.get("runoff_ph"),
            "runoff_ec": data.get("runoff_ec"),
            "water_temp_c": data.get("water_temp_c"),
            "nutrients_json": nutrients_json,
            "height_cm": data.get("height_cm"),
            "training_method": data.get("training_method") or None,
            "temp_c": data.get("temp_c"),
            "humidity": data.get("humidity"),
            "vpd_kpa": data.get("vpd_kpa"),
            "status": status,
            "created_at": now,
        }
        cols = ", ".join(record.keys())
        placeholders = ", ".join(["?"] * len(record))
        with self._connect() as conn:
            # Fill environment_id automatically from plant if omitted
            if record["plant_id"] and not record["environment_id"]:
                row = conn.execute(
                    "SELECT environment_id FROM plants WHERE id = ?",
                    (record["plant_id"],),
                ).fetchone()
                if row:
                    record["environment_id"] = row["environment_id"]
            conn.execute(
                f"INSERT INTO logs ({cols}) VALUES ({placeholders})",
                list(record.values()),
            )
            created = conn.execute(
                "SELECT * FROM logs WHERE id = ?", (log_id,)
            ).fetchone()
            return _deserialize_log(created)

    async def async_update_log(
        self, log_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update an existing journal log entry (retrospective edit or rescheduling)."""
        return await self._run(self._update_log_sync, log_id, data)

    def _update_log_sync(
        self, log_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "plant_id",
            "environment_id",
            "log_type",
            "title",
            "notes",
            "logged_at",
            "water_volume_ml",
            "ph",
            "ec",
            "ppm",
            "runoff_ph",
            "runoff_ec",
            "water_temp_c",
            "height_cm",
            "training_method",
            "status",
        }
        updates: dict[str, Any] = {k: v for k, v in data.items() if k in allowed}
        if "log_type" in updates and not updates["log_type"]:
            updates.pop("log_type")
        if "logged_at" in updates and not updates["logged_at"]:
            updates.pop("logged_at")
        if "status" in updates and updates["status"] not in ("completed", "planned"):
            updates.pop("status")
        if "nutrients" in data:
            nuts = data.get("nutrients")
            updates["nutrients_json"] = json.dumps(nuts) if nuts else None

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM logs WHERE id = ?", (log_id,)
            ).fetchone()
            if not existing:
                return None
            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE logs SET {set_clause} WHERE id = ?",
                    [*updates.values(), log_id],
                )
            row = conn.execute("SELECT * FROM logs WHERE id = ?", (log_id,)).fetchone()
            return _deserialize_log(row) if row else None

    async def async_complete_log(
        self, log_id: str, overrides: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Mark a planned journal entry as completed, applying optional overrides."""
        return await self._run(self._complete_log_sync, log_id, overrides or {})

    def _complete_log_sync(
        self, log_id: str, overrides: dict[str, Any]
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM logs WHERE id = ?", (log_id,)
            ).fetchone()
            if not existing:
                return None
            data = dict(overrides)
            data["status"] = "completed"
            if not data.get("logged_at") and is_timestamp_in_future(
                existing["logged_at"]
            ):
                data["logged_at"] = utc_now_iso()
        return self._update_log_sync(log_id, data)

    async def async_list_logs(
        self,
        plant_id: str | None = None,
        environment_id: str | None = None,
        log_type: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query journal logs with optional filters."""
        return await self._run(
            self._list_logs_sync,
            plant_id,
            environment_id,
            log_type,
            status,
            limit,
            offset,
        )

    def _list_logs_sync(
        self,
        plant_id: str | None,
        environment_id: str | None,
        log_type: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if plant_id:
            clauses.append("plant_id = ?")
            params.append(plant_id)
        if environment_id:
            clauses.append("environment_id = ?")
            params.append(environment_id)
        if log_type:
            clauses.append("log_type = ?")
            params.append(log_type)
        if status in ("completed", "planned"):
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([max(1, min(limit, 500)), max(0, offset)])
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM logs
                {where}
                ORDER BY logged_at DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
            return [_deserialize_log(r) for r in rows]

    async def async_delete_log(self, log_id: str) -> bool:
        """Delete a journal log entry."""
        return await self._run(self._delete_log_sync, log_id)

    def _delete_log_sync(self, log_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM logs WHERE id = ?", (log_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Photos CRUD
    # ------------------------------------------------------------------
    async def async_create_photo(self, data: dict[str, Any]) -> dict[str, Any]:
        """Record a saved photo in SQLite."""
        return await self._run(self._create_photo_sync, data)

    def _create_photo_sync(self, data: dict[str, Any]) -> dict[str, Any]:
        photo_id = data.get("id") or uuid.uuid4().hex[:12]
        now = utc_now_iso()
        access_token = data.get("access_token") or secrets.token_urlsafe(24)

        plant_id = data.get("plant_id") or None
        environment_id = data.get("environment_id") or None
        stage = data.get("stage") or None

        with self._connect() as conn:
            if plant_id and (not stage or not environment_id):
                prow = conn.execute(
                    "SELECT stage, environment_id FROM plants WHERE id = ?",
                    (plant_id,),
                ).fetchone()
                if prow:
                    stage = stage or prow["stage"]
                    environment_id = environment_id or prow["environment_id"]

            record = {
                "id": photo_id,
                "plant_id": plant_id,
                "environment_id": environment_id,
                "log_id": data.get("log_id") or None,
                "stage": stage,
                "filename": data["filename"],
                "mime_type": data.get("mime_type") or "image/jpeg",
                "access_token": access_token,
                "caption": data.get("caption") or None,
                "source": data.get("source") or "upload",
                "taken_at": data.get("taken_at") or now,
                "created_at": now,
            }
            cols = ", ".join(record.keys())
            placeholders = ", ".join(["?"] * len(record))
            conn.execute(
                f"INSERT INTO photos ({cols}) VALUES ({placeholders})",
                list(record.values()),
            )
        return record

    async def async_get_photo(self, photo_id: str) -> dict[str, Any] | None:
        """Fetch photo metadata by ID."""
        return await self._run(self._get_photo_sync, photo_id)

    def _get_photo_sync(self, photo_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM photos WHERE id = ?", (photo_id,)
            ).fetchone()
            return _row_to_dict(row)

    async def async_list_photos(
        self,
        plant_id: str | None = None,
        environment_id: str | None = None,
        stage: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List photos with optional plant/environment/stage filters."""
        return await self._run(
            self._list_photos_sync, plant_id, environment_id, stage, limit
        )

    def _list_photos_sync(
        self,
        plant_id: str | None,
        environment_id: str | None,
        stage: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if plant_id:
            clauses.append("plant_id = ?")
            params.append(plant_id)
        if environment_id:
            clauses.append("environment_id = ?")
            params.append(environment_id)
        if stage:
            clauses.append("stage = ?")
            params.append(stage)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 500)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM photos
                {where}
                ORDER BY taken_at DESC, created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    async def async_delete_photo(self, photo_id: str) -> str | None:
        """Delete a photo record and return its filename for disk cleanup."""
        return await self._run(self._delete_photo_sync, photo_id)

    def _delete_photo_sync(self, photo_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT filename FROM photos WHERE id = ?", (photo_id,)
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE plants SET cover_photo_id = NULL WHERE cover_photo_id = ?",
                (photo_id,),
            )
            conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
            return row["filename"]

    # ------------------------------------------------------------------
    # Nutrient Presets & Feeding Schedules CRUD
    # ------------------------------------------------------------------
    async def async_list_nutrient_presets(
        self, stage: str | None = None
    ) -> list[dict[str, Any]]:
        """List saved nutrient presets, optionally filtered by grow stage."""
        return await self._run(self._list_nutrient_presets_sync, stage)

    def _list_nutrient_presets_sync(
        self, stage: str | None
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if stage:
                rows = conn.execute(
                    """
                    SELECT * FROM nutrient_presets
                    WHERE stage = ? OR stage IS NULL
                    ORDER BY stage IS NULL ASC, week_start IS NULL ASC, week_start ASC, name ASC
                    """,
                    (stage,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM nutrient_presets
                    ORDER BY stage IS NULL ASC, stage ASC, week_start IS NULL ASC, week_start ASC, name ASC
                    """
                ).fetchall()
            return [_deserialize_preset(r) for r in rows]

    async def async_get_nutrient_preset(
        self, preset_id: str
    ) -> dict[str, Any] | None:
        """Fetch a single nutrient preset by ID."""
        return await self._run(self._get_nutrient_preset_sync, preset_id)

    def _get_nutrient_preset_sync(self, preset_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM nutrient_presets WHERE id = ?", (preset_id,)
            ).fetchone()
            return _deserialize_preset(row) if row else None

    async def async_create_nutrient_preset(
        self, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a reusable nutrient preset recipe."""
        return await self._run(self._create_nutrient_preset_sync, data)

    def _create_nutrient_preset_sync(self, data: dict[str, Any]) -> dict[str, Any]:
        preset_id = data.get("id") or uuid.uuid4().hex[:12]
        now = utc_now_iso()
        stage = data.get("stage") or None
        if stage and stage not in GROW_STAGES:
            stage = None
        nutrients = data.get("nutrients") or []
        record = {
            "id": preset_id,
            "name": (data.get("name") or "Nutrient Preset").strip(),
            "stage": stage,
            "week_start": (
                int(data["week_start"]) if data.get("week_start") is not None else None
            ),
            "week_end": (
                int(data["week_end"]) if data.get("week_end") is not None else None
            ),
            "target_ph": data.get("target_ph"),
            "target_ec": data.get("target_ec"),
            "target_ppm": data.get("target_ppm"),
            "nutrients_json": json.dumps(nutrients),
            "notes": data.get("notes") or None,
            "created_at": now,
            "updated_at": now,
        }
        cols = ", ".join(record.keys())
        placeholders = ", ".join(["?"] * len(record))
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO nutrient_presets ({cols}) VALUES ({placeholders})",
                list(record.values()),
            )
            created = conn.execute(
                "SELECT * FROM nutrient_presets WHERE id = ?", (preset_id,)
            ).fetchone()
            return _deserialize_preset(created)

    async def async_update_nutrient_preset(
        self, preset_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update an existing nutrient preset recipe."""
        return await self._run(self._update_nutrient_preset_sync, preset_id, data)

    def _update_nutrient_preset_sync(
        self, preset_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "name",
            "stage",
            "week_start",
            "week_end",
            "target_ph",
            "target_ec",
            "target_ppm",
            "notes",
        }
        updates: dict[str, Any] = {k: v for k, v in data.items() if k in allowed}
        if "name" in updates and not updates["name"]:
            updates.pop("name")
        if "stage" in updates and updates["stage"] and updates["stage"] not in GROW_STAGES:
            updates["stage"] = None
        if "week_start" in updates and updates["week_start"] is not None:
            updates["week_start"] = int(updates["week_start"])
        if "week_end" in updates and updates["week_end"] is not None:
            updates["week_end"] = int(updates["week_end"])
        if "nutrients" in data:
            updates["nutrients_json"] = json.dumps(data.get("nutrients") or [])

        if not updates:
            return self._get_nutrient_preset_sync(preset_id)

        updates["updated_at"] = utc_now_iso()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE nutrient_presets SET {set_clause} WHERE id = ?",
                [*updates.values(), preset_id],
            )
            row = conn.execute(
                "SELECT * FROM nutrient_presets WHERE id = ?", (preset_id,)
            ).fetchone()
            return _deserialize_preset(row) if row else None

    async def async_delete_nutrient_preset(self, preset_id: str) -> bool:
        """Delete a nutrient preset."""
        return await self._run(self._delete_nutrient_preset_sync, preset_id)

    def _delete_nutrient_preset_sync(self, preset_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM nutrient_presets WHERE id = ?", (preset_id,)
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Grow Cycles CRUD
    # ------------------------------------------------------------------
    async def async_create_grow_cycle(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a named grow cycle (e.g. Winter 2026 Run)."""
        return await self._run(self._create_grow_cycle_sync, data)

    def _create_grow_cycle_sync(self, data: dict[str, Any]) -> dict[str, Any]:
        cycle_id = data.get("id") or uuid.uuid4().hex[:12]
        now = utc_now_iso()
        status = data.get("status") or "active"
        if status not in ("active", "completed", "archived"):
            status = "active"
        record = {
            "id": cycle_id,
            "name": (data.get("name") or "Grow Cycle").strip(),
            "started_at": data.get("started_at") or now,
            "ended_at": data.get("ended_at") or None,
            "status": status,
            "notes": data.get("notes") or None,
            "created_at": now,
            "updated_at": now,
        }
        cols = ", ".join(record.keys())
        placeholders = ", ".join(["?"] * len(record))
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO grow_cycles ({cols}) VALUES ({placeholders})",
                list(record.values()),
            )
            row = conn.execute(
                "SELECT * FROM grow_cycles WHERE id = ?", (cycle_id,)
            ).fetchone()
            return dict(row)

    async def async_update_grow_cycle(
        self, cycle_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update a grow cycle."""
        return await self._run(self._update_grow_cycle_sync, cycle_id, data)

    def _update_grow_cycle_sync(
        self, cycle_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {"name", "started_at", "ended_at", "status", "notes"}
        updates = {k: v for k, v in data.items() if k in allowed}
        if "name" in updates and not updates["name"]:
            updates.pop("name")
        if "status" in updates and updates["status"] not in (
            "active",
            "completed",
            "archived",
        ):
            updates.pop("status")
        if not updates:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM grow_cycles WHERE id = ?", (cycle_id,)
                ).fetchone()
                return _row_to_dict(row)
        updates["updated_at"] = utc_now_iso()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE grow_cycles SET {set_clause} WHERE id = ?",
                [*updates.values(), cycle_id],
            )
            row = conn.execute(
                "SELECT * FROM grow_cycles WHERE id = ?", (cycle_id,)
            ).fetchone()
            return _row_to_dict(row)

    async def async_delete_grow_cycle(self, cycle_id: str) -> bool:
        """Delete a grow cycle (plants/harvests stay intact with grow_cycle_id=NULL)."""
        return await self._run(self._delete_grow_cycle_sync, cycle_id)

    def _delete_grow_cycle_sync(self, cycle_id: str) -> bool:
        with self._connect() as conn:
            conn.execute(
                "UPDATE plants SET grow_cycle_id = NULL WHERE grow_cycle_id = ?",
                (cycle_id,),
            )
            cur = conn.execute("DELETE FROM grow_cycles WHERE id = ?", (cycle_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Harvests & Curing Logs CRUD
    # ------------------------------------------------------------------
    async def async_upsert_harvest(
        self, plant_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Create or update a plant's harvest & yield record."""
        return await self._run(self._upsert_harvest_sync, plant_id, data)

    def _upsert_harvest_sync(
        self, plant_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            plant = conn.execute(
                "SELECT * FROM plants WHERE id = ?", (plant_id,)
            ).fetchone()
            if not plant:
                return None

            existing = conn.execute(
                "SELECT * FROM harvests WHERE plant_id = ?", (plant_id,)
            ).fetchone()
            now = utc_now_iso()

            rating = data.get("rating")
            if rating is not None and rating != "":
                rating = max(1, min(5, int(rating)))
            else:
                rating = None

            is_keeper = 1 if data.get("is_keeper") else 0
            dry_days = (
                int(data["dry_days"])
                if data.get("dry_days") not in (None, "")
                else None
            )
            grow_cycle_id = data.get("grow_cycle_id")
            if grow_cycle_id is None:
                grow_cycle_id = plant["grow_cycle_id"]

            if existing is None:
                harvest_id = data.get("id") or uuid.uuid4().hex[:12]
                record = {
                    "id": harvest_id,
                    "plant_id": plant_id,
                    "grow_cycle_id": grow_cycle_id or None,
                    "harvested_at": data.get("harvested_at") or now,
                    "wet_weight_g": data.get("wet_weight_g"),
                    "dry_weight_g": data.get("dry_weight_g"),
                    "trim_weight_g": data.get("trim_weight_g"),
                    "dry_days": dry_days,
                    "cure_start_at": data.get("cure_start_at") or None,
                    "cure_rh_pct": data.get("cure_rh_pct"),
                    "light_wattage_override": data.get("light_wattage_override"),
                    "aroma_notes": data.get("aroma_notes") or None,
                    "effect_notes": data.get("effect_notes") or None,
                    "rating": rating,
                    "is_keeper": is_keeper,
                    "notes": data.get("notes") or None,
                    "created_at": now,
                    "updated_at": now,
                }
                cols = ", ".join(record.keys())
                placeholders = ", ".join(["?"] * len(record))
                conn.execute(
                    f"INSERT INTO harvests ({cols}) VALUES ({placeholders})",
                    list(record.values()),
                )
            else:
                harvest_id = existing["id"]
                updates: dict[str, Any] = {
                    "grow_cycle_id": grow_cycle_id or None,
                    "harvested_at": data.get("harvested_at") or existing["harvested_at"],
                    "wet_weight_g": data.get("wet_weight_g"),
                    "dry_weight_g": data.get("dry_weight_g"),
                    "trim_weight_g": data.get("trim_weight_g"),
                    "dry_days": dry_days,
                    "cure_start_at": data.get("cure_start_at") or None,
                    "cure_rh_pct": data.get("cure_rh_pct"),
                    "light_wattage_override": data.get("light_wattage_override"),
                    "aroma_notes": data.get("aroma_notes") or None,
                    "effect_notes": data.get("effect_notes") or None,
                    "rating": rating,
                    "is_keeper": is_keeper,
                    "notes": data.get("notes") or None,
                    "updated_at": now,
                }
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE harvests SET {set_clause} WHERE id = ?",
                    [*updates.values(), harvest_id],
                )

            # Optional automatic stage transition when recording a harvest
            set_stage = data.get("set_plant_stage")
            if set_stage and set_stage in GROW_STAGES and plant["stage"] != set_stage:
                self._set_stage_in_conn(
                    conn,
                    plant_id,
                    set_stage,
                    notes="Harvest recorded",
                    changed_at=data.get("harvested_at") or now,
                )

            row = conn.execute(
                "SELECT * FROM harvests WHERE id = ?", (harvest_id,)
            ).fetchone()
            return dict(row)

    async def async_delete_harvest(self, harvest_id: str) -> bool:
        """Delete a harvest record and its curing logs."""
        return await self._run(self._delete_harvest_sync, harvest_id)

    def _delete_harvest_sync(self, harvest_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM harvests WHERE id = ?", (harvest_id,))
            return cur.rowcount > 0

    async def async_add_curing_log(
        self, harvest_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Log a curing jar RH/burp check and sync latest cure_rh_pct onto harvest."""
        return await self._run(self._add_curing_log_sync, harvest_id, data)

    def _add_curing_log_sync(
        self, harvest_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            harvest = conn.execute(
                "SELECT id FROM harvests WHERE id = ?", (harvest_id,)
            ).fetchone()
            if not harvest:
                return None

            clog_id = uuid.uuid4().hex[:12]
            now = utc_now_iso()
            logged_at = data.get("logged_at") or now
            jar_rh = data.get("jar_rh_pct")
            jar_temp = data.get("jar_temp_c")
            burped = 1 if data.get("burped", True) else 0
            conn.execute(
                """
                INSERT INTO curing_logs (
                    id, harvest_id, logged_at, jar_rh_pct, jar_temp_c, burped, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clog_id,
                    harvest_id,
                    logged_at,
                    jar_rh,
                    jar_temp,
                    burped,
                    data.get("notes") or None,
                    now,
                ),
            )
            if jar_rh is not None:
                conn.execute(
                    "UPDATE harvests SET cure_rh_pct = ?, updated_at = ? WHERE id = ?",
                    (jar_rh, now, harvest_id),
                )
            row = conn.execute(
                "SELECT * FROM curing_logs WHERE id = ?", (clog_id,)
            ).fetchone()
            return dict(row)

    async def async_delete_curing_log(self, curing_log_id: str) -> bool:
        """Delete a curing jar log entry."""
        return await self._run(self._delete_curing_log_sync, curing_log_id)

    def _delete_curing_log_sync(self, curing_log_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM curing_logs WHERE id = ?", (curing_log_id,)
            )
            return cur.rowcount > 0

    async def async_get_plant_report_data(
        self, plant_id: str
    ) -> dict[str, Any] | None:
        """Collect complete plant history, logs, harvest, and curing logs for export."""
        return await self._run(self._get_plant_report_data_sync, plant_id)

    def _get_plant_report_data_sync(self, plant_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            plant = conn.execute(
                "SELECT * FROM plants WHERE id = ?", (plant_id,)
            ).fetchone()
            if not plant:
                return None
            plant_dict = dict(plant)
            env = None
            if plant_dict.get("environment_id"):
                env = _row_to_dict(
                    conn.execute(
                        "SELECT * FROM environments WHERE id = ?",
                        (plant_dict["environment_id"],),
                    ).fetchone()
                )
            cycle = None
            if plant_dict.get("grow_cycle_id"):
                cycle = _row_to_dict(
                    conn.execute(
                        "SELECT * FROM grow_cycles WHERE id = ?",
                        (plant_dict["grow_cycle_id"],),
                    ).fetchone()
                )
            stage_history = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM stage_history WHERE plant_id = ? ORDER BY started_at ASC",
                    (plant_id,),
                ).fetchall()
            ]
            logs = [
                _deserialize_log(r)
                for r in conn.execute(
                    "SELECT * FROM logs WHERE plant_id = ? ORDER BY logged_at ASC",
                    (plant_id,),
                ).fetchall()
            ]
            harvest_row = conn.execute(
                "SELECT * FROM harvests WHERE plant_id = ?", (plant_id,)
            ).fetchone()
            harvest = dict(harvest_row) if harvest_row else None
            curing_logs = (
                [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM curing_logs WHERE harvest_id = ? ORDER BY logged_at ASC",
                        (harvest["id"],),
                    ).fetchall()
                ]
                if harvest
                else []
            )
            return {
                "plant": plant_dict,
                "environment": env,
                "grow_cycle": cycle,
                "stage_history": stage_history,
                "logs": logs,
                "harvest": harvest,
                "curing_logs": curing_logs,
            }

    # ------------------------------------------------------------------
    # Reminders & Schedules CRUD
    # ------------------------------------------------------------------
    async def async_list_reminders(
        self,
        status: str | None = None,
        plant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List reminders with optional status or plant filter."""
        return await self._run(self._list_reminders_sync, status, plant_id)

    def _list_reminders_sync(
        self, status: str | None, plant_id: str | None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if plant_id:
            clauses.append("plant_id = ?")
            params.append(plant_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM reminders {where} ORDER BY status ASC, due_at ASC",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    async def async_create_reminder(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a recurring or one-time grow reminder."""
        return await self._run(self._create_reminder_sync, data)

    def _create_reminder_sync(self, data: dict[str, Any]) -> dict[str, Any]:
        rem_id = data.get("id") or uuid.uuid4().hex[:12]
        now = utc_now_iso()
        rec_raw = data.get("recurrence_days")
        rec_days = int(rec_raw) if rec_raw not in (None, "", 0, "0") else None
        if rec_days is not None and rec_days <= 0:
            rec_days = None

        status = data.get("status") or "active"
        if status not in ("active", "completed", "paused"):
            status = "active"

        record = {
            "id": rem_id,
            "plant_id": data.get("plant_id") or None,
            "environment_id": data.get("environment_id") or None,
            "title": (data.get("title") or "Grow Reminder").strip(),
            "action_type": data.get("action_type") or "water",
            "due_at": data.get("due_at") or now,
            "recurrence_days": rec_days,
            "moisture_threshold": (
                float(data["moisture_threshold"])
                if data.get("moisture_threshold") not in (None, "")
                else None
            ),
            "auto_log_on_complete": 1 if data.get("auto_log_on_complete", True) else 0,
            "preset_id": data.get("preset_id") or None,
            "notes": data.get("notes") or None,
            "status": status,
            "last_completed_at": None,
            "last_notified_at": None,
            "created_at": now,
            "updated_at": now,
        }
        with self._connect() as conn:
            if record["plant_id"] and not record["environment_id"]:
                prow = conn.execute(
                    "SELECT environment_id FROM plants WHERE id = ?",
                    (record["plant_id"],),
                ).fetchone()
                if prow:
                    record["environment_id"] = prow["environment_id"]
            cols = ", ".join(record.keys())
            placeholders = ", ".join(["?"] * len(record))
            conn.execute(
                f"INSERT INTO reminders ({cols}) VALUES ({placeholders})",
                list(record.values()),
            )
            row = conn.execute(
                "SELECT * FROM reminders WHERE id = ?", (rem_id,)
            ).fetchone()
            return dict(row)

    async def async_update_reminder(
        self, reminder_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update an existing reminder."""
        return await self._run(self._update_reminder_sync, reminder_id, data)

    def _update_reminder_sync(
        self, reminder_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "plant_id",
            "environment_id",
            "title",
            "action_type",
            "due_at",
            "recurrence_days",
            "moisture_threshold",
            "auto_log_on_complete",
            "preset_id",
            "notes",
            "status",
        }
        updates: dict[str, Any] = {k: v for k, v in data.items() if k in allowed}
        if "title" in updates and not updates["title"]:
            updates.pop("title")
        if "due_at" in updates and not updates["due_at"]:
            updates.pop("due_at")
        if "recurrence_days" in updates:
            raw = updates["recurrence_days"]
            updates["recurrence_days"] = (
                int(raw) if raw not in (None, "", 0, "0") and int(raw) > 0 else None
            )
        if "moisture_threshold" in updates:
            raw = updates["moisture_threshold"]
            updates["moisture_threshold"] = (
                float(raw) if raw not in (None, "") else None
            )
        if "auto_log_on_complete" in updates:
            updates["auto_log_on_complete"] = (
                1 if updates["auto_log_on_complete"] else 0
            )
        if "status" in updates and updates["status"] not in (
            "active",
            "completed",
            "paused",
        ):
            updates.pop("status")
        if "due_at" in updates:
            updates["last_notified_at"] = None

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
            ).fetchone()
            if not existing:
                return None
            if updates:
                updates["updated_at"] = utc_now_iso()
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE reminders SET {set_clause} WHERE id = ?",
                    [*updates.values(), reminder_id],
                )
            row = conn.execute(
                "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
            ).fetchone()
            return dict(row)

    async def async_complete_reminder(
        self,
        reminder_id: str,
        create_log: bool | None = None,
        now_iso: str | None = None,
    ) -> dict[str, Any] | None:
        """Complete a reminder, advancing recurrence if repeating & optionally auto-logging."""
        return await self._run(
            self._complete_reminder_sync, reminder_id, create_log, now_iso
        )

    def _complete_reminder_sync(
        self,
        reminder_id: str,
        create_log: bool | None,
        now_iso: str | None,
    ) -> dict[str, Any] | None:
        now_dt = parse_iso_datetime(now_iso) or datetime.now(UTC)
        now_str = now_dt.replace(microsecond=0).isoformat()

        with self._connect() as conn:
            rem = conn.execute(
                "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
            ).fetchone()
            if not rem:
                return None

            should_log = (
                bool(create_log)
                if create_log is not None
                else bool(rem["auto_log_on_complete"])
            )
            created_log: dict[str, Any] | None = None
            if should_log and rem["action_type"] in LOG_TYPES:
                log_id = uuid.uuid4().hex[:12]
                nutrients_json = None
                ph = None
                ec = None
                ppm = None
                if rem["preset_id"]:
                    pr = conn.execute(
                        "SELECT * FROM nutrient_presets WHERE id = ?",
                        (rem["preset_id"],),
                    ).fetchone()
                    if pr:
                        nutrients_json = pr["nutrients_json"]
                        ph = pr["target_ph"]
                        ec = pr["target_ec"]
                        ppm = pr["target_ppm"]
                conn.execute(
                    """
                    INSERT INTO logs (
                        id, plant_id, environment_id, log_type, title, notes,
                        logged_at, ph, ec, ppm, nutrients_json, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?)
                    """,
                    (
                        log_id,
                        rem["plant_id"],
                        rem["environment_id"],
                        rem["action_type"],
                        rem["title"],
                        rem["notes"] or "Completed from reminder",
                        now_str,
                        ph,
                        ec,
                        ppm,
                        nutrients_json,
                        now_str,
                    ),
                )
                lrow = conn.execute(
                    "SELECT * FROM logs WHERE id = ?", (log_id,)
                ).fetchone()
                created_log = _deserialize_log(lrow)

            rec_days = rem["recurrence_days"]
            if rec_days and int(rec_days) > 0:
                next_due = (
                    (now_dt + timedelta(days=int(rec_days)))
                    .replace(microsecond=0)
                    .isoformat()
                )
                conn.execute(
                    """
                    UPDATE reminders
                    SET due_at = ?, last_completed_at = ?, last_notified_at = NULL,
                        status = 'active', updated_at = ?
                    WHERE id = ?
                    """,
                    (next_due, now_str, now_str, reminder_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE reminders
                    SET status = 'completed', last_completed_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (now_str, now_str, reminder_id),
                )

            updated = conn.execute(
                "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
            ).fetchone()
            return {"reminder": dict(updated), "created_log": created_log}

    async def async_mark_reminders_notified(
        self, reminder_ids: list[str], now_iso: str | None = None
    ) -> None:
        """Record notification timestamp on due reminders to prevent duplicate events."""
        if not reminder_ids:
            return
        await self._run(self._mark_reminders_notified_sync, reminder_ids, now_iso)

    def _mark_reminders_notified_sync(
        self, reminder_ids: list[str], now_iso: str | None
    ) -> None:
        now_str = now_iso or utc_now_iso()
        with self._connect() as conn:
            conn.executemany(
                "UPDATE reminders SET last_notified_at = ? WHERE id = ?",
                [(now_str, rid) for rid in reminder_ids],
            )

    async def async_delete_reminder(self, reminder_id: str) -> bool:
        """Delete a reminder."""
        return await self._run(self._delete_reminder_sync, reminder_id)

    def _delete_reminder_sync(self, reminder_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Pollen Vault CRUD
    # ------------------------------------------------------------------
    async def async_list_pollen_batches(self) -> list[dict[str, Any]]:
        """List all stored pollen batches."""
        return await self._run(self._list_pollen_batches_sync)

    def _list_pollen_batches_sync(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pollen_batches ORDER BY collected_at DESC, created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    async def async_create_pollen_batch(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a pollen vault batch."""
        return await self._run(self._create_pollen_batch_sync, data)

    def _create_pollen_batch_sync(self, data: dict[str, Any]) -> dict[str, Any]:
        batch_id = data.get("id") or uuid.uuid4().hex[:12]
        now = utc_now_iso()
        donor_plant_id = data.get("donor_plant_id") or None
        donor_strain = data.get("donor_strain") or None

        with self._connect() as conn:
            if donor_plant_id and not donor_strain:
                prow = conn.execute(
                    "SELECT strain, name FROM plants WHERE id = ?", (donor_plant_id,)
                ).fetchone()
                if prow:
                    donor_strain = prow["strain"] or prow["name"]

            record = {
                "id": batch_id,
                "name": (data.get("name") or "Pollen Batch").strip(),
                "donor_plant_id": donor_plant_id,
                "donor_strain": donor_strain,
                "donor_type": data.get("donor_type") or "male",
                "collected_at": data.get("collected_at") or now[:10],
                "storage_method": data.get("storage_method") or None,
                "storage_location": data.get("storage_location") or None,
                "viability": data.get("viability") or "high",
                "notes": data.get("notes") or None,
                "created_at": now,
                "updated_at": now,
            }
            cols = ", ".join(record.keys())
            placeholders = ", ".join(["?"] * len(record))
            conn.execute(
                f"INSERT INTO pollen_batches ({cols}) VALUES ({placeholders})",
                list(record.values()),
            )
            row = conn.execute(
                "SELECT * FROM pollen_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            return dict(row)

    async def async_update_pollen_batch(
        self, batch_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update an existing pollen batch."""
        return await self._run(self._update_pollen_batch_sync, batch_id, data)

    def _update_pollen_batch_sync(
        self, batch_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "name",
            "donor_plant_id",
            "donor_strain",
            "donor_type",
            "collected_at",
            "storage_method",
            "storage_location",
            "viability",
            "notes",
        }
        updates = {k: v for k, v in data.items() if k in allowed}
        if "name" in updates and not updates["name"]:
            updates.pop("name")
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM pollen_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if not existing:
                return None
            if updates:
                updates["updated_at"] = utc_now_iso()
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE pollen_batches SET {set_clause} WHERE id = ?",
                    [*updates.values(), batch_id],
                )
            row = conn.execute(
                "SELECT * FROM pollen_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            return dict(row)

    async def async_delete_pollen_batch(self, batch_id: str) -> bool:
        """Delete a pollen vault batch."""
        return await self._run(self._delete_pollen_batch_sync, batch_id)

    def _delete_pollen_batch_sync(self, batch_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM pollen_batches WHERE id = ?", (batch_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Breeding Crosses & Seed Harvesting (Auto-Mint to Seedbank)
    # ------------------------------------------------------------------
    async def async_list_breeding_crosses(self) -> list[dict[str, Any]]:
        """List all breeding crosses."""
        return await self._run(self._list_breeding_crosses_sync)

    def _list_breeding_crosses_sync(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM breeding_crosses ORDER BY pollination_date DESC, created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    async def async_create_breeding_cross(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a breeding cross / pollination project."""
        return await self._run(self._create_breeding_cross_sync, data)

    def _create_breeding_cross_sync(self, data: dict[str, Any]) -> dict[str, Any]:
        cross_id = data.get("id") or uuid.uuid4().hex[:12]
        now = utc_now_iso()
        poll_date = data.get("pollination_date") or now[:10]
        exp_maturity = data.get("expected_maturity_date") or calculate_seed_maturity_date(
            poll_date, weeks=6
        )

        record = {
            "id": cross_id,
            "name": (data.get("name") or "New Cross").strip(),
            "mother_plant_id": data.get("mother_plant_id") or None,
            "mother_name": data.get("mother_name") or None,
            "mother_cross_id": data.get("mother_cross_id") or None,
            "father_plant_id": data.get("father_plant_id") or None,
            "father_name": data.get("father_name") or None,
            "father_cross_id": data.get("father_cross_id") or None,
            "pollen_batch_id": data.get("pollen_batch_id") or None,
            "generation": data.get("generation") or "F1",
            "pollination_date": poll_date,
            "pollination_scope": data.get("pollination_scope") or "branch",
            "branch_tag": data.get("branch_tag") or None,
            "expected_maturity_date": exp_maturity,
            "seed_harvested_at": data.get("seed_harvested_at") or None,
            "seed_count": (
                int(data["seed_count"])
                if data.get("seed_count") not in (None, "")
                else None
            ),
            "minted_seed_batch_id": None,
            "status": data.get("status") or "pollinated",
            "goals": data.get("goals") or None,
            "notes": data.get("notes") or None,
            "created_at": now,
            "updated_at": now,
        }
        cols = ", ".join(record.keys())
        placeholders = ", ".join(["?"] * len(record))
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO breeding_crosses ({cols}) VALUES ({placeholders})",
                list(record.values()),
            )
            row = conn.execute(
                "SELECT * FROM breeding_crosses WHERE id = ?", (cross_id,)
            ).fetchone()
            return dict(row)

    async def async_update_breeding_cross(
        self, cross_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update an existing breeding cross."""
        return await self._run(self._update_breeding_cross_sync, cross_id, data)

    def _update_breeding_cross_sync(
        self, cross_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "name",
            "mother_plant_id",
            "mother_name",
            "mother_cross_id",
            "father_plant_id",
            "father_name",
            "father_cross_id",
            "pollen_batch_id",
            "generation",
            "pollination_date",
            "pollination_scope",
            "branch_tag",
            "expected_maturity_date",
            "seed_harvested_at",
            "seed_count",
            "status",
            "goals",
            "notes",
        }
        updates: dict[str, Any] = {k: v for k, v in data.items() if k in allowed}
        if "name" in updates and not updates["name"]:
            updates.pop("name")
        if "seed_count" in updates:
            raw = updates["seed_count"]
            updates["seed_count"] = int(raw) if raw not in (None, "") else None
        if (
            "pollination_date" in updates
            and updates["pollination_date"]
            and "expected_maturity_date" not in updates
        ):
            updates["expected_maturity_date"] = calculate_seed_maturity_date(
                updates["pollination_date"], weeks=6
            )

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM breeding_crosses WHERE id = ?", (cross_id,)
            ).fetchone()
            if not existing:
                return None
            if updates:
                updates["updated_at"] = utc_now_iso()
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE breeding_crosses SET {set_clause} WHERE id = ?",
                    [*updates.values(), cross_id],
                )
            row = conn.execute(
                "SELECT * FROM breeding_crosses WHERE id = ?", (cross_id,)
            ).fetchone()
            return dict(row)

    async def async_harvest_cross_seeds(
        self, cross_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Harvest mature seeds from a cross and auto-mint a Seedbank batch."""
        return await self._run(self._harvest_cross_seeds_sync, cross_id, data)

    def _harvest_cross_seeds_sync(
        self, cross_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        now = utc_now_iso()
        harvested_at = data.get("harvested_at") or now[:10]
        seed_count = (
            int(data["seed_count"]) if data.get("seed_count") not in (None, "") else 0
        )
        mint_seedbank = bool(data.get("mint_seedbank", True))

        with self._connect() as conn:
            cross = conn.execute(
                "SELECT * FROM breeding_crosses WHERE id = ?", (cross_id,)
            ).fetchone()
            if not cross:
                return None

            # Resolve human-readable parent names
            mother_label = cross["mother_name"]
            if not mother_label and cross["mother_plant_id"]:
                prow = conn.execute(
                    "SELECT name, strain FROM plants WHERE id = ?",
                    (cross["mother_plant_id"],),
                ).fetchone()
                if prow:
                    mother_label = prow["strain"] or prow["name"]
            if not mother_label and cross["mother_cross_id"]:
                crow = conn.execute(
                    "SELECT name FROM breeding_crosses WHERE id = ?",
                    (cross["mother_cross_id"],),
                ).fetchone()
                if crow:
                    mother_label = crow["name"]

            father_label = cross["father_name"]
            pollen_donor_type = None
            if cross["pollen_batch_id"]:
                pb = conn.execute(
                    "SELECT name, donor_strain, donor_type FROM pollen_batches WHERE id = ?",
                    (cross["pollen_batch_id"],),
                ).fetchone()
                if pb:
                    pollen_donor_type = pb["donor_type"]
                    father_label = father_label or pb["donor_strain"] or pb["name"]
            if not father_label and cross["father_plant_id"]:
                prow = conn.execute(
                    "SELECT name, strain FROM plants WHERE id = ?",
                    (cross["father_plant_id"],),
                ).fetchone()
                if prow:
                    father_label = prow["strain"] or prow["name"]
            if not father_label and cross["father_cross_id"]:
                crow = conn.execute(
                    "SELECT name FROM breeding_crosses WHERE id = ?",
                    (cross["father_cross_id"],),
                ).fetchone()
                if crow:
                    father_label = crow["name"]

            inferred_seed_type = data.get("seed_type")
            if not inferred_seed_type:
                if cross["generation"] == "S1" or pollen_donor_type in (
                    "reversed_sts",
                    "reversed_cs",
                ):
                    inferred_seed_type = "feminized"
                else:
                    inferred_seed_type = "regular"

            lineage = f"{mother_label or 'Unknown'} × {father_label or 'Unknown'} ({cross['generation']})"

            seed_batch: dict[str, Any] | None = None
            batch_id = cross["minted_seed_batch_id"]
            if mint_seedbank:
                if batch_id:
                    conn.execute(
                        """
                        UPDATE seed_batches
                        SET seed_count = ?, seed_type = ?, harvested_at = ?,
                            storage_location = COALESCE(?, storage_location),
                            notes = COALESCE(?, notes), updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            seed_count,
                            inferred_seed_type,
                            harvested_at,
                            data.get("storage_location") or None,
                            data.get("notes") or None,
                            now,
                            batch_id,
                        ),
                    )
                else:
                    batch_id = uuid.uuid4().hex[:12]
                    batch_record = {
                        "id": batch_id,
                        "name": (data.get("batch_name") or cross["name"]).strip(),
                        "breeder": data.get("breeder") or "Homebred (iGro)",
                        "generation": cross["generation"],
                        "seed_type": inferred_seed_type,
                        "seed_count": seed_count,
                        "breeding_cross_id": cross_id,
                        "mother_name": mother_label,
                        "father_name": father_label,
                        "lineage_summary": lineage,
                        "harvested_at": harvested_at,
                        "storage_location": data.get("storage_location") or None,
                        "notes": data.get("notes") or cross["notes"],
                        "created_at": now,
                        "updated_at": now,
                    }
                    bcols = ", ".join(batch_record.keys())
                    bph = ", ".join(["?"] * len(batch_record))
                    conn.execute(
                        f"INSERT INTO seed_batches ({bcols}) VALUES ({bph})",
                        list(batch_record.values()),
                    )
                srow = conn.execute(
                    "SELECT * FROM seed_batches WHERE id = ?", (batch_id,)
                ).fetchone()
                seed_batch = dict(srow) if srow else None

            conn.execute(
                """
                UPDATE breeding_crosses
                SET status = 'harvested', seed_harvested_at = ?, seed_count = ?,
                    minted_seed_batch_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (harvested_at, seed_count, batch_id if mint_seedbank else cross["minted_seed_batch_id"], now, cross_id),
            )
            updated_cross = conn.execute(
                "SELECT * FROM breeding_crosses WHERE id = ?", (cross_id,)
            ).fetchone()
            return {"cross": dict(updated_cross), "seed_batch": seed_batch}

    async def async_delete_breeding_cross(self, cross_id: str) -> bool:
        """Delete a breeding cross."""
        return await self._run(self._delete_breeding_cross_sync, cross_id)

    def _delete_breeding_cross_sync(self, cross_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM breeding_crosses WHERE id = ?", (cross_id,))
            return cur.rowcount > 0

    async def async_list_seed_batches(self) -> list[dict[str, Any]]:
        """List minted seed batches."""
        return await self._run(self._list_seed_batches_sync)

    def _list_seed_batches_sync(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM seed_batches ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    async def async_delete_seed_batch(self, batch_id: str) -> bool:
        """Delete a seed batch."""
        return await self._run(self._delete_seed_batch_sync, batch_id)

    def _delete_seed_batch_sync(self, batch_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM seed_batches WHERE id = ?", (batch_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Pheno-Hunts & Sibling Phenotype Scorecards CRUD
    # ------------------------------------------------------------------
    async def async_list_pheno_hunts(self) -> list[dict[str, Any]]:
        """List all pheno hunts."""
        return await self._run(self._list_pheno_hunts_sync)

    def _list_pheno_hunts_sync(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pheno_hunts ORDER BY started_at DESC, created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    async def async_create_pheno_hunt(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a pheno-hunt session."""
        return await self._run(self._create_pheno_hunt_sync, data)

    def _create_pheno_hunt_sync(self, data: dict[str, Any]) -> dict[str, Any]:
        hunt_id = data.get("id") or uuid.uuid4().hex[:12]
        now = utc_now_iso()
        cross_id = data.get("breeding_cross_id") or None
        strain = data.get("strain") or None

        with self._connect() as conn:
            if cross_id and not strain:
                crow = conn.execute(
                    "SELECT name FROM breeding_crosses WHERE id = ?", (cross_id,)
                ).fetchone()
                if crow:
                    strain = crow["name"]

            record = {
                "id": hunt_id,
                "name": (data.get("name") or "Pheno Hunt").strip(),
                "breeding_cross_id": cross_id,
                "seed_batch_id": data.get("seed_batch_id") or None,
                "strain": strain,
                "breeder": data.get("breeder") or None,
                "started_at": data.get("started_at") or now[:10],
                "status": data.get("status") or "active",
                "selection_goals": data.get("selection_goals") or None,
                "notes": data.get("notes") or None,
                "created_at": now,
                "updated_at": now,
            }
            cols = ", ".join(record.keys())
            placeholders = ", ".join(["?"] * len(record))
            conn.execute(
                f"INSERT INTO pheno_hunts ({cols}) VALUES ({placeholders})",
                list(record.values()),
            )
            row = conn.execute(
                "SELECT * FROM pheno_hunts WHERE id = ?", (hunt_id,)
            ).fetchone()
            return dict(row)

    async def async_update_pheno_hunt(
        self, hunt_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update a pheno-hunt session."""
        return await self._run(self._update_pheno_hunt_sync, hunt_id, data)

    def _update_pheno_hunt_sync(
        self, hunt_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "name",
            "breeding_cross_id",
            "seed_batch_id",
            "strain",
            "breeder",
            "started_at",
            "status",
            "selection_goals",
            "notes",
        }
        updates = {k: v for k, v in data.items() if k in allowed}
        if "name" in updates and not updates["name"]:
            updates.pop("name")
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM pheno_hunts WHERE id = ?", (hunt_id,)
            ).fetchone()
            if not existing:
                return None
            if updates:
                updates["updated_at"] = utc_now_iso()
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE pheno_hunts SET {set_clause} WHERE id = ?",
                    [*updates.values(), hunt_id],
                )
            row = conn.execute(
                "SELECT * FROM pheno_hunts WHERE id = ?", (hunt_id,)
            ).fetchone()
            return dict(row)

    async def async_delete_pheno_hunt(self, hunt_id: str) -> bool:
        """Delete a pheno hunt and its sibling scores."""
        return await self._run(self._delete_pheno_hunt_sync, hunt_id)

    def _delete_pheno_hunt_sync(self, hunt_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM pheno_hunts WHERE id = ?", (hunt_id,))
            return cur.rowcount > 0

    async def async_upsert_pheno_score(
        self, pheno_hunt_id: str, plant_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create or update a phenotype trait scorecard for a sibling plant."""
        return await self._run(
            self._upsert_pheno_score_sync, pheno_hunt_id, plant_id, data
        )

    def _upsert_pheno_score_sync(
        self, pheno_hunt_id: str, plant_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        now = utc_now_iso()

        def _int_or_none(val: Any) -> int | None:
            return int(val) if val not in (None, "") else None

        def _float_or_none(val: Any) -> float | None:
            return float(val) if val not in (None, "") else None

        status = data.get("status") or "evaluating"
        if status not in ("evaluating", "keeper", "breeder", "cull"):
            status = "evaluating"

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM pheno_scores WHERE pheno_hunt_id = ? AND plant_id = ?",
                (pheno_hunt_id, plant_id),
            ).fetchone()
            if existing:
                score_id = existing["id"]
                conn.execute(
                    """
                    UPDATE pheno_scores
                    SET pheno_code = ?, status = ?, vigor = ?, stretch_factor = ?,
                        internode_spacing = ?, resin_density = ?, pest_mold_resistance = ?,
                        aroma_score = ?, terpene_notes = ?, flower_days = ?, yield_g = ?,
                        notes = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        data.get("pheno_code") or existing["pheno_code"],
                        status,
                        _int_or_none(data.get("vigor")),
                        _float_or_none(data.get("stretch_factor")),
                        data.get("internode_spacing") or None,
                        _int_or_none(data.get("resin_density")),
                        _int_or_none(data.get("pest_mold_resistance")),
                        _int_or_none(data.get("aroma_score")),
                        data.get("terpene_notes") or None,
                        _int_or_none(data.get("flower_days")),
                        _float_or_none(data.get("yield_g")),
                        data.get("notes") or None,
                        now,
                        score_id,
                    ),
                )
            else:
                score_id = data.get("id") or uuid.uuid4().hex[:12]
                count = conn.execute(
                    "SELECT COUNT(*) FROM pheno_scores WHERE pheno_hunt_id = ?",
                    (pheno_hunt_id,),
                ).fetchone()[0]
                record = {
                    "id": score_id,
                    "pheno_hunt_id": pheno_hunt_id,
                    "plant_id": plant_id,
                    "pheno_code": data.get("pheno_code") or f"#{count + 1}",
                    "status": status,
                    "vigor": _int_or_none(data.get("vigor")),
                    "stretch_factor": _float_or_none(data.get("stretch_factor")),
                    "internode_spacing": data.get("internode_spacing") or None,
                    "resin_density": _int_or_none(data.get("resin_density")),
                    "pest_mold_resistance": _int_or_none(
                        data.get("pest_mold_resistance")
                    ),
                    "aroma_score": _int_or_none(data.get("aroma_score")),
                    "terpene_notes": data.get("terpene_notes") or None,
                    "flower_days": _int_or_none(data.get("flower_days")),
                    "yield_g": _float_or_none(data.get("yield_g")),
                    "notes": data.get("notes") or None,
                    "created_at": now,
                    "updated_at": now,
                }
                cols = ", ".join(record.keys())
                placeholders = ", ".join(["?"] * len(record))
                conn.execute(
                    f"INSERT INTO pheno_scores ({cols}) VALUES ({placeholders})",
                    list(record.values()),
                )
            row = conn.execute(
                "SELECT * FROM pheno_scores WHERE id = ?", (score_id,)
            ).fetchone()
            return dict(row)

    async def async_delete_pheno_score(self, score_id: str) -> bool:
        """Remove a plant's scorecard from a pheno hunt."""
        return await self._run(self._delete_pheno_score_sync, score_id)

    def _delete_pheno_score_sync(self, score_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM pheno_scores WHERE id = ?", (score_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Reservoirs, Dosing Channels & Dosing Runs CRUD (Issue #11)
    # ------------------------------------------------------------------
    async def async_create_reservoir(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a managed nutrient reservoir."""
        return await self._run(self._create_reservoir_sync, data)

    def _create_reservoir_sync(self, data: dict[str, Any]) -> dict[str, Any]:
        res_id = data.get("id") or uuid.uuid4().hex[:12]
        now = utc_now_iso()
        record = {
            "id": res_id,
            "name": (data.get("name") or "Nutrient Reservoir").strip(),
            "environment_id": data.get("environment_id") or None,
            "capacity_l": float(data.get("capacity_l") or 40.0),
            "current_volume_l": (
                float(data["current_volume_l"])
                if data.get("current_volume_l") not in (None, "")
                else None
            ),
            "ec_entity_id": data.get("ec_entity_id") or None,
            "ph_entity_id": data.get("ph_entity_id") or None,
            "water_temp_entity_id": data.get("water_temp_entity_id") or None,
            "level_entity_id": data.get("level_entity_id") or None,
            "low_level_entity_id": data.get("low_level_entity_id") or None,
            "leak_entity_id": data.get("leak_entity_id") or None,
            "ro_fill_entity_id": data.get("ro_fill_entity_id") or None,
            "circ_pump_entity_id": data.get("circ_pump_entity_id") or None,
            "master_feed_pump_entity_id": data.get("master_feed_pump_entity_id") or None,
            "target_ec": (
                float(data["target_ec"])
                if data.get("target_ec") not in (None, "")
                else None
            ),
            "target_ph": (
                float(data["target_ph"])
                if data.get("target_ph") not in (None, "")
                else None
            ),
            "ec_tolerance": float(data.get("ec_tolerance") or 0.1),
            "ph_tolerance": float(data.get("ph_tolerance") or 0.15),
            "auto_trim_enabled": 1 if data.get("auto_trim_enabled") else 0,
            "auto_ro_topoff": 1 if data.get("auto_ro_topoff") else 0,
            "settle_delay_s": int(data.get("settle_delay_s") or 180),
            "ph_min_bound": float(data.get("ph_min_bound") or 3.5),
            "ph_max_bound": float(data.get("ph_max_bound") or 9.5),
            "ec_max_bound": float(data.get("ec_max_bound") or 5.0),
            "status": data.get("status") or "idle",
            "last_error": None,
            "last_mixed_at": None,
            "notes": data.get("notes") or None,
            "created_at": now,
            "updated_at": now,
        }
        cols = ", ".join(record.keys())
        ph = ", ".join(["?"] * len(record))
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO reservoirs ({cols}) VALUES ({ph})",
                list(record.values()),
            )
            row = conn.execute(
                "SELECT * FROM reservoirs WHERE id = ?", (res_id,)
            ).fetchone()
            return dict(row)

    async def async_update_reservoir(
        self, reservoir_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update a reservoir configuration or status."""
        return await self._run(self._update_reservoir_sync, reservoir_id, data)

    def _update_reservoir_sync(
        self, reservoir_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "name",
            "environment_id",
            "capacity_l",
            "current_volume_l",
            "ec_entity_id",
            "ph_entity_id",
            "water_temp_entity_id",
            "level_entity_id",
            "low_level_entity_id",
            "leak_entity_id",
            "ro_fill_entity_id",
            "circ_pump_entity_id",
            "master_feed_pump_entity_id",
            "target_ec",
            "target_ph",
            "ec_tolerance",
            "ph_tolerance",
            "auto_trim_enabled",
            "auto_ro_topoff",
            "settle_delay_s",
            "ph_min_bound",
            "ph_max_bound",
            "ec_max_bound",
            "status",
            "last_error",
            "last_mixed_at",
            "notes",
        }
        updates: dict[str, Any] = {k: v for k, v in data.items() if k in allowed}
        if "name" in updates and not updates["name"]:
            updates.pop("name")
        for bf in ("auto_trim_enabled", "auto_ro_topoff"):
            if bf in updates:
                updates[bf] = 1 if updates[bf] else 0
        for ff in (
            "capacity_l",
            "current_volume_l",
            "target_ec",
            "target_ph",
            "ec_tolerance",
            "ph_tolerance",
            "ph_min_bound",
            "ph_max_bound",
            "ec_max_bound",
        ):
            if ff in updates:
                updates[ff] = (
                    float(updates[ff]) if updates[ff] not in (None, "") else None
                )
        if "settle_delay_s" in updates and updates["settle_delay_s"] not in (None, ""):
            updates["settle_delay_s"] = int(updates["settle_delay_s"])

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM reservoirs WHERE id = ?", (reservoir_id,)
            ).fetchone()
            if not existing:
                return None
            if updates:
                updates["updated_at"] = utc_now_iso()
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE reservoirs SET {set_clause} WHERE id = ?",
                    [*updates.values(), reservoir_id],
                )
            row = conn.execute(
                "SELECT * FROM reservoirs WHERE id = ?", (reservoir_id,)
            ).fetchone()
            return dict(row)

    async def async_delete_reservoir(self, reservoir_id: str) -> bool:
        """Delete a reservoir and its dosing channels."""
        return await self._run(self._delete_reservoir_sync, reservoir_id)

    def _delete_reservoir_sync(self, reservoir_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM reservoirs WHERE id = ?", (reservoir_id,))
            return cur.rowcount > 0

    async def async_create_dosing_channel(
        self, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a peristaltic dosing pump channel."""
        return await self._run(self._create_dosing_channel_sync, data)

    def _create_dosing_channel_sync(self, data: dict[str, Any]) -> dict[str, Any]:
        ch_id = data.get("id") or uuid.uuid4().hex[:12]
        now = utc_now_iso()
        role = data.get("role") or "additive"
        default_orders = {
            "silica": 10,
            "cal_mag": 20,
            "base_a": 30,
            "base_b": 40,
            "bloom_pk": 50,
            "additive": 60,
            "ph_down": 90,
            "ph_up": 95,
        }
        cap = float(data.get("bottle_capacity_ml") or 1000.0)
        rem = (
            float(data["bottle_remaining_ml"])
            if data.get("bottle_remaining_ml") not in (None, "")
            else cap
        )
        record = {
            "id": ch_id,
            "reservoir_id": data["reservoir_id"],
            "name": (data.get("name") or "Dosing Channel").strip(),
            "role": role,
            "nutrient_name": data.get("nutrient_name") or data.get("name") or None,
            "entity_id": data.get("entity_id") or None,
            "control_type": data.get("control_type") or "switch",
            "esphome_service": data.get("esphome_service") or None,
            "flow_rate_ml_s": max(0.05, float(data.get("flow_rate_ml_s") or 1.0)),
            "mix_order": (
                int(data["mix_order"])
                if data.get("mix_order") not in (None, "")
                else default_orders.get(role, 60)
            ),
            "stir_delay_s": int(data.get("stir_delay_s") or 30),
            "bottle_capacity_ml": cap,
            "bottle_remaining_ml": rem,
            "low_bottle_alert_ml": float(data.get("low_bottle_alert_ml") or 100.0),
            "max_dose_per_cycle_ml": float(data.get("max_dose_per_cycle_ml") or 50.0),
            "max_daily_dose_ml": float(data.get("max_daily_dose_ml") or 200.0),
            "enabled": 1 if data.get("enabled", True) else 0,
            "notes": data.get("notes") or None,
            "created_at": now,
            "updated_at": now,
        }
        cols = ", ".join(record.keys())
        ph = ", ".join(["?"] * len(record))
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO dosing_channels ({cols}) VALUES ({ph})",
                list(record.values()),
            )
            row = conn.execute(
                "SELECT * FROM dosing_channels WHERE id = ?", (ch_id,)
            ).fetchone()
            return dict(row)

    async def async_update_dosing_channel(
        self, channel_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update a dosing pump channel."""
        return await self._run(self._update_dosing_channel_sync, channel_id, data)

    def _update_dosing_channel_sync(
        self, channel_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "name",
            "role",
            "nutrient_name",
            "entity_id",
            "control_type",
            "esphome_service",
            "flow_rate_ml_s",
            "mix_order",
            "stir_delay_s",
            "bottle_capacity_ml",
            "bottle_remaining_ml",
            "low_bottle_alert_ml",
            "max_dose_per_cycle_ml",
            "max_daily_dose_ml",
            "enabled",
            "notes",
        }
        updates: dict[str, Any] = {k: v for k, v in data.items() if k in allowed}
        if "name" in updates and not updates["name"]:
            updates.pop("name")
        if "enabled" in updates:
            updates["enabled"] = 1 if updates["enabled"] else 0
        for ff in (
            "flow_rate_ml_s",
            "bottle_capacity_ml",
            "bottle_remaining_ml",
            "low_bottle_alert_ml",
            "max_dose_per_cycle_ml",
            "max_daily_dose_ml",
        ):
            if ff in updates and updates[ff] not in (None, ""):
                updates[ff] = float(updates[ff])
        for intf in ("mix_order", "stir_delay_s"):
            if intf in updates and updates[intf] not in (None, ""):
                updates[intf] = int(updates[intf])

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM dosing_channels WHERE id = ?", (channel_id,)
            ).fetchone()
            if not existing:
                return None
            if updates:
                updates["updated_at"] = utc_now_iso()
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE dosing_channels SET {set_clause} WHERE id = ?",
                    [*updates.values(), channel_id],
                )
            row = conn.execute(
                "SELECT * FROM dosing_channels WHERE id = ?", (channel_id,)
            ).fetchone()
            return dict(row)

    async def async_consume_channel_bottle(
        self, channel_id: str, dosed_ml: float
    ) -> dict[str, Any] | None:
        """Subtract dosed volume from a channel's remaining bottle inventory."""
        return await self._run(self._consume_channel_bottle_sync, channel_id, dosed_ml)

    def _consume_channel_bottle_sync(
        self, channel_id: str, dosed_ml: float
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT bottle_remaining_ml FROM dosing_channels WHERE id = ?",
                (channel_id,),
            ).fetchone()
            if not row:
                return None
            new_rem = max(0.0, round(float(row["bottle_remaining_ml"]) - dosed_ml, 2))
            conn.execute(
                "UPDATE dosing_channels SET bottle_remaining_ml = ?, updated_at = ? WHERE id = ?",
                (new_rem, utc_now_iso(), channel_id),
            )
            updated = conn.execute(
                "SELECT * FROM dosing_channels WHERE id = ?", (channel_id,)
            ).fetchone()
            return dict(updated)

    async def async_delete_dosing_channel(self, channel_id: str) -> bool:
        """Delete a dosing channel."""
        return await self._run(self._delete_dosing_channel_sync, channel_id)

    def _delete_dosing_channel_sync(self, channel_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM dosing_channels WHERE id = ?", (channel_id,)
            )
            return cur.rowcount > 0

    async def async_record_dosing_run(self, data: dict[str, Any]) -> dict[str, Any]:
        """Record a batch-mix, auto-trim, or manual dosing run audit log."""
        return await self._run(self._record_dosing_run_sync, data)

    def _record_dosing_run_sync(self, data: dict[str, Any]) -> dict[str, Any]:
        run_id = data.get("id") or uuid.uuid4().hex[:12]
        now = utc_now_iso()
        steps = data.get("steps") or []
        record = {
            "id": run_id,
            "reservoir_id": data["reservoir_id"],
            "channel_id": data.get("channel_id") or None,
            "preset_id": data.get("preset_id") or None,
            "run_type": data.get("run_type") or "batch_mix",
            "status": data.get("status") or "completed",
            "target_volume_l": data.get("target_volume_l"),
            "dosed_ml": float(data.get("dosed_ml") or 0.0),
            "steps_json": json.dumps(steps),
            "start_ph": data.get("start_ph"),
            "start_ec": data.get("start_ec"),
            "end_ph": data.get("end_ph"),
            "end_ec": data.get("end_ec"),
            "abort_reason": data.get("abort_reason") or None,
            "started_at": data.get("started_at") or now,
            "completed_at": data.get("completed_at") or now,
        }
        cols = ", ".join(record.keys())
        ph = ", ".join(["?"] * len(record))
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO dosing_runs ({cols}) VALUES ({ph})",
                list(record.values()),
            )
            row = conn.execute(
                "SELECT * FROM dosing_runs WHERE id = ?", (run_id,)
            ).fetchone()
            out = dict(row)
            out["steps"] = json.loads(out.pop("steps_json", "[]") or "[]")
            return out

    async def async_get_daily_channel_dose(self, channel_id: str) -> float:
        """Return total mL dosed on a channel today (UTC)."""
        return await self._run(self._get_daily_channel_dose_sync, channel_id)

    def _get_daily_channel_dose_sync(self, channel_id: str) -> float:
        today_prefix = utc_now_iso()[:10]
        total = 0.0
        with self._connect() as conn:
            for r in conn.execute(
                "SELECT steps_json FROM dosing_runs WHERE status = 'completed' AND started_at >= ?",
                (today_prefix,),
            ).fetchall():
                try:
                    steps = json.loads(r["steps_json"] or "[]")
                except (ValueError, TypeError):
                    steps = []
                for st in steps:
                    if st.get("channel_id") == channel_id:
                        total += float(st.get("dose_ml") or 0.0)
        return round(total, 2)

    # ------------------------------------------------------------------
    # Per-Plant Fertigation Schedules & Events CRUD (Issue #10)
    # ------------------------------------------------------------------
    async def async_upsert_fertigation_schedule(
        self, plant_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create or update a plant's high-frequency fertigation schedule."""
        return await self._run(
            self._upsert_fertigation_schedule_sync, plant_id, data
        )

    def _upsert_fertigation_schedule_sync(
        self, plant_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        now = utc_now_iso()
        allowed = {
            "reservoir_id",
            "mode",
            "schedule_type",
            "pump_entity_id",
            "valve_entity_id",
            "use_shared_pump",
            "esphome_watchdog_entity_id",
            "flow_rate_ml_s",
            "feeds_per_day",
            "shot_duration_s",
            "target_shot_ml",
            "window_start",
            "window_end",
            "p1_ramp_shots",
            "p1_interval_min",
            "p3_dryback_cutoff_min",
            "interval_hours",
            "moisture_threshold_pct",
            "moisture_cooldown_min",
            "max_shot_duration_s",
            "max_daily_volume_ml",
            "leak_entity_id",
            "auto_log_action",
            "last_fed_at",
            "last_error",
        }
        updates: dict[str, Any] = {k: v for k, v in data.items() if k in allowed}
        if "fixed_times" in data:
            updates["fixed_times_json"] = json.dumps(data["fixed_times"] or [])
        if "use_shared_pump" in updates:
            updates["use_shared_pump"] = 1 if updates["use_shared_pump"] else 0
        for ff in (
            "flow_rate_ml_s",
            "shot_duration_s",
            "target_shot_ml",
            "interval_hours",
            "moisture_threshold_pct",
            "max_shot_duration_s",
            "max_daily_volume_ml",
        ):
            if ff in updates:
                updates[ff] = (
                    float(updates[ff]) if updates[ff] not in (None, "") else None
                )
        for intf in (
            "feeds_per_day",
            "p1_ramp_shots",
            "p1_interval_min",
            "p3_dryback_cutoff_min",
            "moisture_cooldown_min",
        ):
            if intf in updates and updates[intf] not in (None, ""):
                updates[intf] = int(updates[intf])

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM fertigation_schedules WHERE plant_id = ?", (plant_id,)
            ).fetchone()
            if existing:
                sched_id = existing["id"]
                if updates:
                    updates["updated_at"] = now
                    set_clause = ", ".join(f"{k} = ?" for k in updates)
                    conn.execute(
                        f"UPDATE fertigation_schedules SET {set_clause} WHERE id = ?",
                        [*updates.values(), sched_id],
                    )
            else:
                sched_id = data.get("id") or uuid.uuid4().hex[:12]
                record: dict[str, Any] = {
                    "id": sched_id,
                    "plant_id": plant_id,
                    "reservoir_id": None,
                    "mode": "off",
                    "schedule_type": "high_frequency",
                    "pump_entity_id": None,
                    "valve_entity_id": None,
                    "use_shared_pump": 0,
                    "esphome_watchdog_entity_id": None,
                    "flow_rate_ml_s": 10.0,
                    "feeds_per_day": 4,
                    "shot_duration_s": 15.0,
                    "target_shot_ml": None,
                    "window_start": "08:00",
                    "window_end": "20:00",
                    "p1_ramp_shots": 2,
                    "p1_interval_min": 30,
                    "p3_dryback_cutoff_min": 120,
                    "interval_hours": 6.0,
                    "fixed_times_json": "[]",
                    "moisture_threshold_pct": 35.0,
                    "moisture_cooldown_min": 90,
                    "max_shot_duration_s": 60.0,
                    "max_daily_volume_ml": 4000.0,
                    "leak_entity_id": None,
                    "auto_log_action": "feed",
                    "last_fed_at": None,
                    "last_error": None,
                    "created_at": now,
                    "updated_at": now,
                }
                for k, v in updates.items():
                    if v is not None or k in (
                        "reservoir_id",
                        "pump_entity_id",
                        "valve_entity_id",
                        "esphome_watchdog_entity_id",
                        "target_shot_ml",
                        "leak_entity_id",
                        "last_fed_at",
                        "last_error",
                    ):
                        record[k] = v
                cols = ", ".join(record.keys())
                ph = ", ".join(["?"] * len(record))
                conn.execute(
                    f"INSERT INTO fertigation_schedules ({cols}) VALUES ({ph})",
                    list(record.values()),
                )

            row = conn.execute(
                "SELECT * FROM fertigation_schedules WHERE id = ?", (sched_id,)
            ).fetchone()
            out = dict(row)
            out["fixed_times"] = json.loads(out.pop("fixed_times_json", "[]") or "[]")
            return out

    async def async_delete_fertigation_schedule(self, plant_id: str) -> bool:
        """Delete a plant's fertigation schedule."""
        return await self._run(self._delete_fertigation_schedule_sync, plant_id)

    def _delete_fertigation_schedule_sync(self, plant_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM fertigation_schedules WHERE plant_id = ?", (plant_id,)
            )
            return cur.rowcount > 0

    async def async_record_fertigation_event(
        self, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Record a fertigation shot or safety-blocked attempt."""
        return await self._run(self._record_fertigation_event_sync, data)

    def _record_fertigation_event_sync(self, data: dict[str, Any]) -> dict[str, Any]:
        ev_id = data.get("id") or uuid.uuid4().hex[:12]
        now = data.get("logged_at") or utc_now_iso()
        record = {
            "id": ev_id,
            "plant_id": data["plant_id"],
            "schedule_id": data.get("schedule_id") or None,
            "reservoir_id": data.get("reservoir_id") or None,
            "trigger_type": data.get("trigger_type") or "manual",
            "duration_s": float(data.get("duration_s") or 0.0),
            "volume_ml": float(data.get("volume_ml") or 0.0),
            "status": data.get("status") or "completed",
            "block_reason": data.get("block_reason") or None,
            "reservoir_ph": data.get("reservoir_ph"),
            "reservoir_ec": data.get("reservoir_ec"),
            "logged_at": now,
        }
        cols = ", ".join(record.keys())
        ph = ", ".join(["?"] * len(record))
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO fertigation_events ({cols}) VALUES ({ph})",
                list(record.values()),
            )
            row = conn.execute(
                "SELECT * FROM fertigation_events WHERE id = ?", (ev_id,)
            ).fetchone()
            return dict(row)

    async def async_get_daily_fertigation_volume(self, plant_id: str) -> float:
        """Return total automated fertigation volume (mL) delivered today (UTC)."""
        return await self._run(self._get_daily_fertigation_volume_sync, plant_id)

    def _get_daily_fertigation_volume_sync(self, plant_id: str) -> float:
        today_prefix = utc_now_iso()[:10]
        with self._connect() as conn:
            val = conn.execute(
                """
                SELECT COALESCE(SUM(volume_ml), 0)
                FROM fertigation_events
                WHERE plant_id = ? AND status = 'completed' AND logged_at >= ?
                """,
                (plant_id, today_prefix),
            ).fetchone()[0]
            return round(float(val or 0.0), 1)

    # ------------------------------------------------------------------
    # Batch Multi-Plant / Whole-Tent Operations (Issue #9)
    # ------------------------------------------------------------------
    async def async_create_logs_batch(
        self,
        plant_ids: list[str],
        data: dict[str, Any],
        *,
        split_water_volume: bool = False,
        env_readings_by_plant: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Create journal entries across multiple plants in one batch operation."""
        return await self._run(
            self._create_logs_batch_sync,
            plant_ids,
            data,
            split_water_volume,
            env_readings_by_plant or {},
        )

    def _create_logs_batch_sync(
        self,
        plant_ids: list[str],
        data: dict[str, Any],
        split_water_volume: bool,
        env_readings_by_plant: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        unique_ids = list(dict.fromkeys(pid for pid in plant_ids if pid))
        if not unique_ids:
            return []

        base = dict(data)
        raw_vol = base.get("water_volume_ml")
        per_plant_vol = raw_vol
        if split_water_volume and raw_vol is not None:
            per_plant_vol = round(float(raw_vol) / len(unique_ids), 1)

        base_nutrients = base.get("nutrients")
        if split_water_volume and base_nutrients and per_plant_vol is not None:
            base_nutrients = scale_nutrients_for_volume(base_nutrients, per_plant_vol)

        created: list[dict[str, Any]] = []
        for pid in unique_ids:
            entry = {**base, "plant_id": pid}
            if per_plant_vol is not None:
                entry["water_volume_ml"] = per_plant_vol
            if base_nutrients is not None:
                entry["nutrients"] = base_nutrients
            readings = env_readings_by_plant.get(pid) or {}
            for k in ("temp_c", "humidity", "vpd_kpa"):
                if entry.get(k) is None and readings.get(k) is not None:
                    entry[k] = readings[k]
            created.append(self._create_log_sync(entry))
        return created

    async def async_batch_set_plant_stage(
        self,
        plant_ids: list[str],
        stage: str,
        notes: str | None = None,
        changed_at: str | None = None,
    ) -> list[dict[str, Any]]:
        """Transition multiple plants to a target growth stage."""
        return await self._run(
            self._batch_set_plant_stage_sync, plant_ids, stage, notes, changed_at
        )

    def _batch_set_plant_stage_sync(
        self,
        plant_ids: list[str],
        stage: str,
        notes: str | None,
        changed_at: str | None,
    ) -> list[dict[str, Any]]:
        updated: list[dict[str, Any]] = []
        for pid in dict.fromkeys(p for p in plant_ids if p):
            res = self._set_plant_stage_sync(pid, stage, notes, changed_at)
            if res is not None:
                updated.append(res)
        return updated

    async def async_batch_move_plants(
        self, plant_ids: list[str], environment_id: str | None
    ) -> list[dict[str, Any]]:
        """Bulk-assign multiple plants to a target environment (or unassign)."""
        return await self._run(self._batch_move_plants_sync, plant_ids, environment_id)

    def _batch_move_plants_sync(
        self, plant_ids: list[str], environment_id: str | None
    ) -> list[dict[str, Any]]:
        unique_ids = list(dict.fromkeys(p for p in plant_ids if p))
        if not unique_ids:
            return []
        now = utc_now_iso()
        target_env = environment_id or None
        updated: list[dict[str, Any]] = []
        with self._connect() as conn:
            for pid in unique_ids:
                conn.execute(
                    "UPDATE plants SET environment_id = ?, updated_at = ? WHERE id = ?",
                    (target_env, now, pid),
                )
                row = conn.execute(
                    "SELECT * FROM plants WHERE id = ?", (pid,)
                ).fetchone()
                if row:
                    updated.append(dict(row))
        return updated
