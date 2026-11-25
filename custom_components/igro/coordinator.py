"""DataUpdateCoordinator for iGro combining SQLite data and live HA sensors."""

from __future__ import annotations

from datetime import timedelta
import logging
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .calculations import (
    calculate_dew_point_c,
    calculate_vpd_kpa,
    compute_plant_day_metrics,
    days_since,
    evaluate_range_status,
    get_effective_vpd_targets,
    suggest_presets_for_plant,
    to_celsius,
)
from .const import (
    ACTIVE_STAGES,
    DEFAULT_LEAF_TEMP_OFFSET_C,
    DOMAIN,
    EVENT_STAGE_CHANGED,
    SIGNAL_ENTITIES_CHANGED,
    VPD_STATUS_HIGH,
    VPD_STATUS_LOW,
)
from .database import IGroDatabase

_LOGGER = logging.getLogger(__name__)


def photo_url(photo_id: str, access_token: str) -> str:
    """Build authenticated/tokenized URL for a stored photo."""
    return f"/api/{DOMAIN}/photos/{photo_id}?token={access_token}"


class IGroCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinates iGro SQLite persistence with real-time Home Assistant sensor states."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        db: IGroDatabase,
        media_dir: Path,
    ) -> None:
        """Initialize the iGro coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=60),
        )
        self.entry = entry
        self.db = db
        self.media_dir = media_dir
        self._tracked_entities: set[str] = set()
        self._unsub_state_listener: CALLBACK_TYPE | None = None

    def _read_float_state(self, entity_id: str | None) -> tuple[float | None, str | None]:
        """Read numeric state and unit_of_measurement from a bound HA entity."""
        if not entity_id:
            return None, None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable", "", "None"):
            return None, None
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            return None, state.attributes.get("unit_of_measurement")
        return value, state.attributes.get("unit_of_measurement")

    def _read_raw_state(self, entity_id: str | None) -> str | None:
        """Read string state from a bound HA entity (e.g. switch, light, fan)."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        return state.state

    @callback
    def _rebind_state_listeners(self, entity_ids: set[str]) -> None:
        """Subscribe to HA state changes for all bound environment/plant entities."""
        if entity_ids == self._tracked_entities:
            return

        if self._unsub_state_listener is not None:
            self._unsub_state_listener()
            self._unsub_state_listener = None

        self._tracked_entities = set(entity_ids)
        if not self._tracked_entities:
            return

        @callback
        def _handle_state_change(event: Event) -> None:
            self.hass.async_create_task(self.async_request_refresh())

        self._unsub_state_listener = async_track_state_change_event(
            self.hass,
            sorted(self._tracked_entities),
            _handle_state_change,
        )

    @callback
    def async_shutdown_listeners(self) -> None:
        """Remove state change listeners on unload."""
        if self._unsub_state_listener is not None:
            self._unsub_state_listener()
            self._unsub_state_listener = None
        self._tracked_entities.clear()

    async def async_notify_structure_changed(self) -> None:
        """Refresh coordinator data and notify entity platforms of added/removed items."""
        await self.async_refresh()
        async_dispatcher_send(self.hass, SIGNAL_ENTITIES_CHANGED)

    async def _async_update_data(self) -> dict[str, Any]:
        """Load SQLite snapshot and merge live HA sensor readings & VPD calculations."""
        # Auto-apply any due scheduled stage transitions before reading the snapshot
        applied_transitions = await self.db.async_process_due_stage_changes()
        for item in applied_transitions:
            self.hass.bus.async_fire(
                EVENT_STAGE_CHANGED,
                {
                    "plant_id": item["plant_id"],
                    "stage": item["stage"],
                    "scheduled": True,
                },
            )

        snapshot = await self.db.async_get_snapshot()

        raw_envs: list[dict[str, Any]] = snapshot["environments"]
        raw_plants: list[dict[str, Any]] = snapshot["plants"]
        stage_rows: list[dict[str, Any]] = snapshot["stage_history"]
        plant_stats: dict[str, dict[str, Any]] = snapshot["plant_stats"]
        nutrient_presets: list[dict[str, Any]] = snapshot.get("nutrient_presets", [])
        raw_sched_stages: list[dict[str, Any]] = snapshot.get(
            "scheduled_stage_changes", []
        )

        # Group stage history & pending scheduled stage changes by plant
        history_by_plant: dict[str, list[dict[str, Any]]] = {}
        for row in stage_rows:
            history_by_plant.setdefault(row["plant_id"], []).append(row)

        sched_by_plant: dict[str, list[dict[str, Any]]] = {}
        for sched in raw_sched_stages:
            sched_by_plant.setdefault(sched["plant_id"], []).append(sched)

        # Group plants by environment
        plants_by_env: dict[str, list[dict[str, Any]]] = {}
        env_name_map: dict[str, str] = {e["id"]: e["name"] for e in raw_envs}
        env_camera_map: dict[str, str | None] = {
            e["id"]: e.get("camera_entity_id") for e in raw_envs
        }

        tracked_entity_ids: set[str] = set()

        # Enrich plants
        plants_map: dict[str, dict[str, Any]] = {}
        active_plant_count = 0

        for p in raw_plants:
            pid = p["id"]
            if p.get("environment_id"):
                plants_by_env.setdefault(p["environment_id"], []).append(p)
            if p.get("stage") in ACTIVE_STAGES:
                active_plant_count += 1

            soil_entity = p.get("soil_moisture_entity_id")
            if soil_entity:
                tracked_entity_ids.add(soil_entity)
            soil_val, soil_unit = self._read_float_state(soil_entity)

            day_metrics = compute_plant_day_metrics(p)
            stats = plant_stats.get(pid, {})
            cover = stats.get("cover_photo")
            cover_url = (
                photo_url(cover["id"], cover["access_token"]) if cover else None
            )

            suggested_presets = suggest_presets_for_plant(
                {**p, **day_metrics}, nutrient_presets
            )

            enriched_plant = {
                **p,
                **day_metrics,
                "environment_name": env_name_map.get(p.get("environment_id") or ""),
                "effective_camera_entity_id": (
                    p.get("camera_entity_id")
                    or env_camera_map.get(p.get("environment_id") or "")
                ),
                "soil_moisture": soil_val,
                "soil_moisture_unit": soil_unit or "%",
                "last_watered_at": stats.get("last_watered_at"),
                "days_since_watered": days_since(stats.get("last_watered_at")),
                "last_water_volume_ml": stats.get("last_water_volume_ml"),
                "last_fed_at": stats.get("last_fed_at"),
                "last_ph": stats.get("last_ph"),
                "last_ec": stats.get("last_ec"),
                "last_ppm": stats.get("last_ppm"),
                "latest_height_cm": stats.get("latest_height_cm"),
                "log_count": stats.get("log_count", 0),
                "planned_log_count": stats.get("planned_log_count", 0),
                "photo_count": stats.get("photo_count", 0),
                "cover_photo_url": cover_url,
                "stage_history": history_by_plant.get(pid, []),
                "scheduled_stage_changes": sched_by_plant.get(pid, []),
                "suggested_preset_ids": [pr["id"] for pr in suggested_presets],
            }
            plants_map[pid] = enriched_plant

        # Enrich environments with live HA sensors + VPD
        envs_map: dict[str, dict[str, Any]] = {}
        alerts_count = 0

        for env in raw_envs:
            eid = env["id"]
            for key in (
                "temp_entity_id",
                "humidity_entity_id",
                "co2_entity_id",
                "light_entity_id",
                "exhaust_entity_id",
                "humidifier_entity_id",
            ):
                ent_id = env.get(key)
                if ent_id:
                    tracked_entity_ids.add(ent_id)

            raw_temp, temp_unit = self._read_float_state(env.get("temp_entity_id"))
            temp_c = (
                round(to_celsius(raw_temp, temp_unit), 1)
                if raw_temp is not None
                else None
            )
            humidity, _ = self._read_float_state(env.get("humidity_entity_id"))
            if humidity is not None:
                humidity = round(humidity, 1)
            co2, _ = self._read_float_state(env.get("co2_entity_id"))

            leaf_offset = env.get("leaf_temp_offset_c")
            if leaf_offset is None:
                leaf_offset = DEFAULT_LEAF_TEMP_OFFSET_C

            vpd_kpa = calculate_vpd_kpa(temp_c, humidity, float(leaf_offset))
            dew_point_c = calculate_dew_point_c(temp_c, humidity)

            env_plants = plants_by_env.get(eid, [])
            active_env_plants = [
                p for p in env_plants if p.get("stage") in ACTIVE_STAGES
            ]
            vpd_min, vpd_max = get_effective_vpd_targets(env, active_env_plants)

            vpd_status = evaluate_range_status(vpd_kpa, vpd_min, vpd_max)
            temp_status = evaluate_range_status(
                temp_c, env.get("target_temp_min_c"), env.get("target_temp_max_c")
            )
            humidity_status = evaluate_range_status(
                humidity, env.get("target_humidity_min"), env.get("target_humidity_max")
            )

            vpd_alert = vpd_status in (VPD_STATUS_LOW, VPD_STATUS_HIGH)
            temp_alert = temp_status in (VPD_STATUS_LOW, VPD_STATUS_HIGH)
            humidity_alert = humidity_status in (VPD_STATUS_LOW, VPD_STATUS_HIGH)
            if vpd_alert:
                alerts_count += 1
            if temp_alert:
                alerts_count += 1
            if humidity_alert:
                alerts_count += 1

            envs_map[eid] = {
                **env,
                "temperature_c": temp_c,
                "temperature_raw": raw_temp,
                "temperature_unit": temp_unit or "°C",
                "humidity": humidity,
                "vpd_kpa": vpd_kpa,
                "dew_point_c": dew_point_c,
                "co2": co2,
                "light_state": self._read_raw_state(env.get("light_entity_id")),
                "exhaust_state": self._read_raw_state(env.get("exhaust_entity_id")),
                "humidifier_state": self._read_raw_state(
                    env.get("humidifier_entity_id")
                ),
                "effective_vpd_min": vpd_min,
                "effective_vpd_max": vpd_max,
                "vpd_status": vpd_status,
                "temp_status": temp_status,
                "humidity_status": humidity_status,
                "vpd_alert": vpd_alert,
                "temp_alert": temp_alert,
                "humidity_alert": humidity_alert,
                "plant_count": len(active_env_plants),
                "total_plant_count": len(env_plants),
                "plant_ids": [p["id"] for p in env_plants],
            }

        # Attach photo URLs to recent_photos
        recent_photos = [
            {
                **ph,
                "url": photo_url(ph["id"], ph["access_token"]),
                "plant_name": (
                    plants_map[ph["plant_id"]]["name"]
                    if ph.get("plant_id") in plants_map
                    else None
                ),
                "environment_name": env_name_map.get(ph.get("environment_id") or ""),
            }
            for ph in snapshot["recent_photos"]
        ]

        # Enrich recent_logs & planned_logs with plant & environment names
        recent_logs = [
            {
                **lg,
                "plant_name": (
                    plants_map[lg["plant_id"]]["name"]
                    if lg.get("plant_id") in plants_map
                    else None
                ),
                "environment_name": env_name_map.get(lg.get("environment_id") or ""),
            }
            for lg in snapshot["recent_logs"]
        ]
        planned_logs = [
            {
                **lg,
                "plant_name": (
                    plants_map[lg["plant_id"]]["name"]
                    if lg.get("plant_id") in plants_map
                    else None
                ),
                "environment_name": env_name_map.get(lg.get("environment_id") or ""),
            }
            for lg in snapshot.get("planned_logs", [])
        ]
        scheduled_stage_changes = [
            {
                **sc,
                "plant_name": (
                    plants_map[sc["plant_id"]]["name"]
                    if sc.get("plant_id") in plants_map
                    else None
                ),
            }
            for sc in raw_sched_stages
        ]

        self._rebind_state_listeners(tracked_entity_ids)

        return {
            "environments": envs_map,
            "plants": plants_map,
            "recent_logs": recent_logs,
            "planned_logs": planned_logs,
            "scheduled_stage_changes": scheduled_stage_changes,
            "recent_photos": recent_photos,
            "nutrient_presets": nutrient_presets,
            "summary": {
                "active_plants": active_plant_count,
                "total_plants": len(plants_map),
                "total_environments": len(envs_map),
                "alerts_count": alerts_count,
                "total_logs": snapshot["totals"]["logs"],
                "total_photos": snapshot["totals"]["photos"],
            },
        }

    def get_environment_readings_for_plant(self, plant_id: str | None) -> dict[str, Any]:
        """Return current temp_c/humidity/vpd_kpa of a plant's environment for log snapshots."""
        if not plant_id or not self.data:
            return {}
        plant = self.data.get("plants", {}).get(plant_id)
        if not plant or not plant.get("environment_id"):
            return {}
        env = self.data.get("environments", {}).get(plant["environment_id"])
        if not env:
            return {}
        return {
            "temp_c": env.get("temperature_c"),
            "humidity": env.get("humidity"),
            "vpd_kpa": env.get("vpd_kpa"),
        }
