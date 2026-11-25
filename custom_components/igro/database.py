"""SQLite database layer for iGro.

Uses Python's built-in sqlite3 in WAL mode inside Home Assistant's executor pool
so there are zero external dependencies and zero event-loop blocking.
Stored as a dedicated `igro.db` alongside Home Assistant's `home-assistant_v2.db`
to avoid recorder lock contention or schema conflicts.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import secrets
import sqlite3
from typing import Any
import uuid

from .const import (
    DEFAULT_LEAF_TEMP_OFFSET_C,
    GROW_STAGES,
    LOG_TYPE_STAGE_CHANGE,
    STAGE_GERMINATION,
)

SCHEMA_VERSION = 2


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
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE CASCADE,
                    FOREIGN KEY (environment_id) REFERENCES environments(id) ON DELETE SET NULL
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

                CREATE INDEX IF NOT EXISTS idx_plants_env ON plants(environment_id);
                CREATE INDEX IF NOT EXISTS idx_stage_history_plant ON stage_history(plant_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_logs_plant_logged ON logs(plant_id, logged_at DESC);
                CREATE INDEX IF NOT EXISTS idx_logs_env_logged ON logs(environment_id, logged_at DESC);
                CREATE INDEX IF NOT EXISTS idx_logs_logged ON logs(logged_at DESC);
                CREATE INDEX IF NOT EXISTS idx_photos_plant_taken ON photos(plant_id, taken_at DESC);
                CREATE INDEX IF NOT EXISTS idx_photos_taken ON photos(taken_at DESC);
                CREATE INDEX IF NOT EXISTS idx_presets_stage ON nutrient_presets(stage, week_start);
                """
            )
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
                    "SELECT * FROM logs ORDER BY logged_at DESC, created_at DESC LIMIT 60"
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

            # Per-plant aggregates
            plant_stats: dict[str, dict[str, Any]] = {}
            for p in plants:
                pid = p["id"]
                last_water = conn.execute(
                    """
                    SELECT logged_at, water_volume_ml, ph, ec
                    FROM logs
                    WHERE plant_id = ? AND log_type IN ('water', 'feed', 'flush')
                    ORDER BY logged_at DESC LIMIT 1
                    """,
                    (pid,),
                ).fetchone()
                last_feed = conn.execute(
                    """
                    SELECT logged_at, ph, ec, ppm
                    FROM logs
                    WHERE plant_id = ? AND log_type = 'feed'
                    ORDER BY logged_at DESC LIMIT 1
                    """,
                    (pid,),
                ).fetchone()
                last_ph_ec = conn.execute(
                    """
                    SELECT ph, ec, ppm, logged_at
                    FROM logs
                    WHERE plant_id = ? AND (ph IS NOT NULL OR ec IS NOT NULL)
                    ORDER BY logged_at DESC LIMIT 1
                    """,
                    (pid,),
                ).fetchone()
                last_height = conn.execute(
                    """
                    SELECT height_cm, logged_at
                    FROM logs
                    WHERE plant_id = ? AND height_cm IS NOT NULL
                    ORDER BY logged_at DESC LIMIT 1
                    """,
                    (pid,),
                ).fetchone()
                log_count = conn.execute(
                    "SELECT COUNT(*) FROM logs WHERE plant_id = ?", (pid,)
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
                    "photo_count": photo_count,
                    "cover_photo": cover_photo,
                }

            total_logs = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
            total_photos = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]

            return {
                "environments": environments,
                "plants": plants,
                "stage_history": stage_rows,
                "plant_stats": plant_stats,
                "recent_logs": recent_logs,
                "recent_photos": recent_photos,
                "nutrient_presets": nutrient_presets,
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

        now = changed_at or utc_now_iso()
        old_stage = existing["stage"]
        if old_stage == stage:
            return dict(existing)

        # Close open stage_history entry
        conn.execute(
            """
            UPDATE stage_history
            SET ended_at = ?
            WHERE plant_id = ? AND ended_at IS NULL
            """,
            (now, plant_id),
        )
        # Insert new stage_history entry
        conn.execute(
            """
            INSERT INTO stage_history (id, plant_id, stage, started_at, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (uuid.uuid4().hex[:12], plant_id, stage, now, notes),
        )
        # Update plant row
        conn.execute(
            """
            UPDATE plants
            SET stage = ?, stage_started_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (stage, now, utc_now_iso(), plant_id),
        )
        # Automatically add a journal entry for the stage transition
        conn.execute(
            """
            INSERT INTO logs (
                id, plant_id, environment_id, log_type, title, notes, logged_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex[:12],
                plant_id,
                existing["environment_id"],
                LOG_TYPE_STAGE_CHANGE,
                f"Stage changed: {old_stage.title()} → {stage.title()}",
                notes,
                now,
                utc_now_iso(),
            ),
        )
        row = conn.execute("SELECT * FROM plants WHERE id = ?", (plant_id,)).fetchone()
        return _row_to_dict(row)

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
        nutrients = data.get("nutrients")
        nutrients_json = json.dumps(nutrients) if nutrients else None

        record = {
            "id": log_id,
            "plant_id": data.get("plant_id") or None,
            "environment_id": data.get("environment_id") or None,
            "log_type": data.get("log_type") or "note",
            "title": data.get("title") or None,
            "notes": data.get("notes") or None,
            "logged_at": data.get("logged_at") or now,
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

    async def async_list_logs(
        self,
        plant_id: str | None = None,
        environment_id: str | None = None,
        log_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query journal logs with optional filters."""
        return await self._run(
            self._list_logs_sync, plant_id, environment_id, log_type, limit, offset
        )

    def _list_logs_sync(
        self,
        plant_id: str | None,
        environment_id: str | None,
        log_type: str | None,
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
