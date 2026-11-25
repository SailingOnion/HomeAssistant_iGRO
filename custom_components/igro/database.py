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

from .calculations import is_timestamp_in_future, parse_iso_datetime
from .const import (
    DEFAULT_LEAF_TEMP_OFFSET_C,
    GROW_STAGES,
    LOG_TYPE_STAGE_CHANGE,
    LOG_TYPES,
    STAGE_GERMINATION,
)

SCHEMA_VERSION = 5


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
                """
            )
            # Safe additive migrations for pre-v4 databases
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
