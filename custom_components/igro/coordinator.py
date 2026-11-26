"""DataUpdateCoordinator for iGro combining SQLite data and live HA sensors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .calculations import (
    build_pedigree_tree,
    calculate_dew_point_c,
    calculate_vpd_kpa,
    compute_harvest_metrics,
    compute_pheno_overall_score,
    compute_plant_day_metrics,
    days_since,
    evaluate_range_status,
    get_effective_vpd_targets,
    parse_iso_datetime,
    suggest_presets_for_plant,
    to_celsius,
)
from .const import (
    ACTIVE_STAGES,
    DEFAULT_LEAF_TEMP_OFFSET_C,
    DOMAIN,
    EVENT_REMINDER_DUE,
    EVENT_STAGE_CHANGED,
    SIGNAL_ENTITIES_CHANGED,
    VPD_STATUS_HIGH,
    VPD_STATUS_LOW,
)
from .database import IGroDatabase
from .fertigation import (
    IGroFertigationController,
    compute_high_frequency_shot_times,
    compute_next_fertigation_time,
    evaluate_probe_sanity,
)

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
        self.fertigation = IGroFertigationController(hass, self)
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
        raw_cycles: list[dict[str, Any]] = snapshot.get("grow_cycles", [])
        raw_harvests: list[dict[str, Any]] = snapshot.get("harvests", [])
        raw_curing_logs: list[dict[str, Any]] = snapshot.get("curing_logs", [])

        # Group stage history, scheduled stage changes, and curing logs
        history_by_plant: dict[str, list[dict[str, Any]]] = {}
        for row in stage_rows:
            history_by_plant.setdefault(row["plant_id"], []).append(row)

        sched_by_plant: dict[str, list[dict[str, Any]]] = {}
        for sched in raw_sched_stages:
            sched_by_plant.setdefault(sched["plant_id"], []).append(sched)

        curing_by_harvest: dict[str, list[dict[str, Any]]] = {}
        for cl in raw_curing_logs:
            curing_by_harvest.setdefault(cl["harvest_id"], []).append(cl)

        cycle_name_map: dict[str, str] = {c["id"]: c["name"] for c in raw_cycles}
        env_wattage_map: dict[str, float | None] = {
            e["id"]: e.get("light_wattage") for e in raw_envs
        }
        env_total_plant_counts: dict[str, int] = {}
        for p in raw_plants:
            if p.get("environment_id"):
                env_total_plant_counts[p["environment_id"]] = (
                    env_total_plant_counts.get(p["environment_id"], 0) + 1
                )

        harvest_by_plant: dict[str, dict[str, Any]] = {}
        for h in raw_harvests:
            harvest_by_plant[h["plant_id"]] = h

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

            raw_harvest = harvest_by_plant.get(pid)
            enriched_harvest: dict[str, Any] | None = None
            if raw_harvest:
                env_id = p.get("environment_id")
                h_metrics = compute_harvest_metrics(
                    raw_harvest,
                    env_light_wattage=env_wattage_map.get(env_id or ""),
                    env_plant_count=env_total_plant_counts.get(env_id or "", 1),
                )
                enriched_harvest = {
                    **raw_harvest,
                    **h_metrics,
                    "is_keeper": bool(raw_harvest.get("is_keeper")),
                    "curing_logs": curing_by_harvest.get(raw_harvest["id"], []),
                    "plant_name": p["name"],
                    "strain": p.get("strain"),
                    "breeder": p.get("breeder"),
                    "medium": p.get("medium"),
                    "total_days": day_metrics.get("total_days"),
                    "cover_photo_url": cover_url,
                    "grow_cycle_name": cycle_name_map.get(
                        raw_harvest.get("grow_cycle_id") or p.get("grow_cycle_id") or ""
                    ),
                }

            enriched_plant = {
                **p,
                **day_metrics,
                "environment_name": env_name_map.get(p.get("environment_id") or ""),
                "grow_cycle_name": cycle_name_map.get(p.get("grow_cycle_id") or ""),
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
                "harvest": enriched_harvest,
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

        # Collect enriched harvests and grow cycle aggregates
        enriched_harvests = [
            plants_map[h["plant_id"]]["harvest"]
            for h in raw_harvests
            if h["plant_id"] in plants_map and plants_map[h["plant_id"]].get("harvest")
        ]
        dry_weights = [
            h["dry_weight_g"]
            for h in enriched_harvests
            if h.get("dry_weight_g") is not None
        ]
        total_dry_yield_g = round(sum(dry_weights), 1)
        avg_dry_yield_g = (
            round(total_dry_yield_g / len(dry_weights), 1) if dry_weights else None
        )
        keeper_count = sum(1 for h in enriched_harvests if h.get("is_keeper"))

        enriched_cycles = []
        for cyc in raw_cycles:
            cid = cyc["id"]
            cyc_plants = [p for p in plants_map.values() if p.get("grow_cycle_id") == cid]
            cyc_harvests = [
                h
                for h in enriched_harvests
                if h.get("grow_cycle_id") == cid
                or (
                    h.get("plant_id") in plants_map
                    and plants_map[h["plant_id"]].get("grow_cycle_id") == cid
                )
            ]
            cyc_dry = round(
                sum(
                    h["dry_weight_g"]
                    for h in cyc_harvests
                    if h.get("dry_weight_g") is not None
                ),
                1,
            )
            enriched_cycles.append(
                {
                    **cyc,
                    "plant_count": len(cyc_plants),
                    "harvest_count": len(cyc_harvests),
                    "total_dry_yield_g": cyc_dry,
                }
            )

        # Enrich reminders with due/overdue/moisture-trigger status & fire due events once
        now_utc = datetime.now(UTC)
        today_utc = now_utc.date()
        preset_name_map: dict[str, str] = {
            pr["id"]: pr["name"] for pr in nutrient_presets
        }
        raw_reminders: list[dict[str, Any]] = snapshot.get("reminders", [])
        enriched_reminders: list[dict[str, Any]] = []
        due_to_notify: list[dict[str, Any]] = []
        due_reminders_count = 0
        active_reminders_count = 0

        for rem in raw_reminders:
            is_active = rem.get("status") == "active"
            if is_active:
                active_reminders_count += 1
            due_dt = parse_iso_datetime(rem.get("due_at"))
            is_overdue = bool(is_active and due_dt is not None and due_dt <= now_utc)
            is_due_today = bool(
                is_active
                and due_dt is not None
                and (due_dt <= now_utc or due_dt.date() == today_utc)
            )
            plant_obj = plants_map.get(rem.get("plant_id") or "")
            moisture_thresh = rem.get("moisture_threshold")
            plant_moist = plant_obj.get("soil_moisture") if plant_obj else None
            is_moisture_triggered = bool(
                is_active
                and moisture_thresh is not None
                and plant_moist is not None
                and plant_moist <= float(moisture_thresh)
            )
            is_due = is_overdue or is_moisture_triggered
            if is_due:
                due_reminders_count += 1
                if not rem.get("last_notified_at"):
                    due_to_notify.append(rem)

            enriched_reminders.append(
                {
                    **rem,
                    "auto_log_on_complete": bool(rem.get("auto_log_on_complete")),
                    "plant_name": plant_obj["name"] if plant_obj else None,
                    "environment_name": env_name_map.get(
                        rem.get("environment_id") or ""
                    ),
                    "preset_name": preset_name_map.get(rem.get("preset_id") or ""),
                    "is_overdue": is_overdue,
                    "is_due_today": is_due_today,
                    "is_moisture_triggered": is_moisture_triggered,
                    "is_due": is_due,
                }
            )

        if due_to_notify:
            await self.db.async_mark_reminders_notified(
                [r["id"] for r in due_to_notify]
            )
            for rem in due_to_notify:
                self.hass.bus.async_fire(
                    EVENT_REMINDER_DUE,
                    {
                        "reminder_id": rem["id"],
                        "title": rem["title"],
                        "action_type": rem.get("action_type"),
                        "plant_id": rem.get("plant_id"),
                        "environment_id": rem.get("environment_id"),
                        "due_at": rem.get("due_at"),
                    },
                )

        # Enrich breeding program: pollen vault, crosses + pedigree trees, seed batches & pheno hunts
        raw_pollen: list[dict[str, Any]] = snapshot.get("pollen_batches", [])
        raw_crosses: list[dict[str, Any]] = snapshot.get("breeding_crosses", [])
        raw_seed_batches: list[dict[str, Any]] = snapshot.get("seed_batches", [])
        raw_pheno_hunts: list[dict[str, Any]] = snapshot.get("pheno_hunts", [])
        raw_pheno_scores: list[dict[str, Any]] = snapshot.get("pheno_scores", [])

        enriched_pollen = [
            {
                **pb,
                "donor_plant_name": (
                    plants_map[pb["donor_plant_id"]]["name"]
                    if pb.get("donor_plant_id") in plants_map
                    else None
                ),
            }
            for pb in raw_pollen
        ]
        pollen_by_id = {pb["id"]: pb for pb in enriched_pollen}
        crosses_by_id = {c["id"]: c for c in raw_crosses}
        seed_batches_by_id = {sb["id"]: sb for sb in raw_seed_batches}

        descendants_by_cross: dict[str, list[dict[str, Any]]] = {}
        for c in raw_crosses:
            for parent_col in ("mother_cross_id", "father_cross_id"):
                pid_c = c.get(parent_col)
                if pid_c:
                    descendants_by_cross.setdefault(pid_c, []).append(
                        {
                            "id": c["id"],
                            "name": c["name"],
                            "generation": c.get("generation"),
                        }
                    )

        enriched_crosses: list[dict[str, Any]] = []
        for c in raw_crosses:
            cid = c["id"]
            mother_plant = plants_map.get(c.get("mother_plant_id") or "")
            father_plant = plants_map.get(c.get("father_plant_id") or "")
            pollen_batch = pollen_by_id.get(c.get("pollen_batch_id") or "")
            mother_cross = crosses_by_id.get(c.get("mother_cross_id") or "")
            father_cross = crosses_by_id.get(c.get("father_cross_id") or "")

            mother_display = (
                (mother_plant["name"] if mother_plant else None)
                or (mother_cross["name"] if mother_cross else None)
                or c.get("mother_name")
                or "Unknown Mother"
            )
            father_display = (
                (pollen_batch["name"] if pollen_batch else None)
                or (father_plant["name"] if father_plant else None)
                or (father_cross["name"] if father_cross else None)
                or c.get("father_name")
                or "Unknown Donor"
            )
            days_poll = days_since(c.get("pollination_date"), now_utc)
            mat_dt = parse_iso_datetime(c.get("expected_maturity_date"))
            days_to_mat = (
                (mat_dt.date() - today_utc).days if mat_dt is not None else None
            )

            enriched_crosses.append(
                {
                    **c,
                    "mother_display": mother_display,
                    "father_display": father_display,
                    "pollen_batch_name": pollen_batch["name"] if pollen_batch else None,
                    "days_since_pollination": days_poll,
                    "days_to_maturity": days_to_mat,
                    "minted_seed_batch": seed_batches_by_id.get(
                        c.get("minted_seed_batch_id") or ""
                    ),
                    "pedigree_tree": build_pedigree_tree(
                        cid, crosses_by_id, plants_map, pollen_by_id
                    ),
                    "descendants": descendants_by_cross.get(cid, []),
                }
            )

        scores_by_hunt: dict[str, list[dict[str, Any]]] = {}
        for sc in raw_pheno_scores:
            plant_obj = plants_map.get(sc.get("plant_id") or "")
            harvest_yield = (
                plant_obj.get("harvest", {}).get("dry_weight_g")
                if plant_obj and plant_obj.get("harvest")
                else None
            )
            enriched_sc = {
                **sc,
                "plant_name": plant_obj["name"] if plant_obj else "Unknown Plant",
                "plant_stage": plant_obj.get("stage") if plant_obj else None,
                "plant_cover_photo_url": (
                    plant_obj.get("cover_photo_url") if plant_obj else None
                ),
                "effective_yield_g": (
                    sc["yield_g"] if sc.get("yield_g") is not None else harvest_yield
                ),
                "overall_score": compute_pheno_overall_score(sc),
            }
            scores_by_hunt.setdefault(sc["pheno_hunt_id"], []).append(enriched_sc)

        enriched_pheno_hunts: list[dict[str, Any]] = []
        for hunt in raw_pheno_hunts:
            h_scores = scores_by_hunt.get(hunt["id"], [])
            cross_obj = crosses_by_id.get(hunt.get("breeding_cross_id") or "")
            enriched_pheno_hunts.append(
                {
                    **hunt,
                    "breeding_cross_name": cross_obj["name"] if cross_obj else None,
                    "scores": h_scores,
                    "plant_count": len(h_scores),
                    "keeper_count": sum(
                        1 for s in h_scores if s.get("status") == "keeper"
                    ),
                    "breeder_count": sum(
                        1 for s in h_scores if s.get("status") == "breeder"
                    ),
                    "cull_count": sum(1 for s in h_scores if s.get("status") == "cull"),
                }
            )

        # Enrich reservoirs, dosing channels & fertigation schedules (Issues #10 & #11)
        raw_reservoirs: list[dict[str, Any]] = snapshot.get("reservoirs", [])
        raw_channels: list[dict[str, Any]] = snapshot.get("dosing_channels", [])
        raw_dosing_runs: list[dict[str, Any]] = snapshot.get("dosing_runs", [])
        raw_fert_scheds: list[dict[str, Any]] = snapshot.get("fertigation_schedules", [])
        raw_fert_events: list[dict[str, Any]] = snapshot.get("fertigation_events", [])
        daily_fert_vol: dict[str, float] = snapshot.get("daily_fert_vol", {})
        daily_channel_dose: dict[str, float] = snapshot.get("daily_channel_dose", {})

        res_name_map = {r["id"]: r["name"] for r in raw_reservoirs}

        enriched_channels: list[dict[str, Any]] = []
        channels_by_res: dict[str, list[dict[str, Any]]] = {}
        for ch in raw_channels:
            cap = max(1.0, float(ch.get("bottle_capacity_ml") or 1000.0))
            rem = max(0.0, float(ch.get("bottle_remaining_ml") or 0.0))
            low_thresh = float(ch.get("low_bottle_alert_ml") or 100.0)
            enriched_ch = {
                **ch,
                "enabled": bool(ch.get("enabled", 1)),
                "reservoir_name": res_name_map.get(ch["reservoir_id"]),
                "daily_dosed_ml": daily_channel_dose.get(ch["id"], 0.0),
                "bottle_pct": round(min(100.0, (rem / cap) * 100.0), 1),
                "is_low_bottle": rem <= low_thresh,
            }
            enriched_channels.append(enriched_ch)
            channels_by_res.setdefault(ch["reservoir_id"], []).append(enriched_ch)

        reservoirs_map: dict[str, dict[str, Any]] = {}
        res_names_by_env: dict[str, list[str]] = {}
        for r in raw_reservoirs:
            rid = r["id"]
            for key in (
                "ec_entity_id",
                "ph_entity_id",
                "water_temp_entity_id",
                "level_entity_id",
                "low_level_entity_id",
                "leak_entity_id",
                "ro_fill_entity_id",
                "circ_pump_entity_id",
                "master_feed_pump_entity_id",
            ):
                if r.get(key):
                    tracked_entity_ids.add(r[key])

            ph_val, _ = self._read_float_state(r.get("ph_entity_id"))
            ec_val, _ = self._read_float_state(r.get("ec_entity_id"))
            raw_wt, wt_unit = self._read_float_state(r.get("water_temp_entity_id"))
            water_temp_c = (
                round(to_celsius(raw_wt, wt_unit), 1) if raw_wt is not None else None
            )
            level_pct, _ = self._read_float_state(r.get("level_entity_id"))
            low_level = self._read_raw_state(r.get("low_level_entity_id")) in (
                "on",
                "true",
                "problem",
            )
            leak_detected = self._read_raw_state(r.get("leak_entity_id")) in (
                "on",
                "true",
                "wet",
                "problem",
            )
            probe_ok, probe_err = evaluate_probe_sanity(ph_val, ec_val, r)
            safety_alert = bool(
                leak_detected
                or low_level
                or not probe_ok
                or r.get("status") in ("locked_out", "emergency_stop")
            )
            r_channels = channels_by_res.get(rid, [])
            low_bottle_count = sum(1 for c in r_channels if c.get("is_low_bottle"))

            if r.get("environment_id"):
                res_names_by_env.setdefault(r["environment_id"], []).append(r["name"])

            reservoirs_map[rid] = {
                **r,
                "auto_trim_enabled": bool(r.get("auto_trim_enabled")),
                "auto_ro_topoff": bool(r.get("auto_ro_topoff")),
                "environment_name": env_name_map.get(r.get("environment_id") or ""),
                "ph": round(ph_val, 2) if ph_val is not None else None,
                "ec": round(ec_val, 2) if ec_val is not None else None,
                "water_temp_c": water_temp_c,
                "level_pct": round(level_pct, 1) if level_pct is not None else None,
                "low_level": low_level,
                "leak_detected": leak_detected,
                "ro_fill_state": self._read_raw_state(r.get("ro_fill_entity_id")),
                "circ_pump_state": self._read_raw_state(r.get("circ_pump_entity_id")),
                "master_feed_pump_state": self._read_raw_state(
                    r.get("master_feed_pump_entity_id")
                ),
                "probe_ok": probe_ok,
                "probe_error": probe_err,
                "safety_alert": safety_alert,
                "channels": r_channels,
                "channel_count": len(r_channels),
                "low_bottle_count": low_bottle_count,
            }

        for eid, env_obj in envs_map.items():
            env_obj["reservoir_names"] = res_names_by_env.get(eid, [])

        fert_by_plant: dict[str, dict[str, Any]] = {}
        for sched in raw_fert_scheds:
            pid = sched["plant_id"]
            if sched.get("leak_entity_id"):
                tracked_entity_ids.add(sched["leak_entity_id"])
            res_obj = reservoirs_map.get(sched.get("reservoir_id") or "")
            flow = max(0.1, float(sched.get("flow_rate_ml_s") or 10.0))
            shot_s = (
                round(float(sched["target_shot_ml"]) / flow, 2)
                if sched.get("target_shot_ml")
                else float(sched.get("shot_duration_s") or 15.0)
            )
            est_shot_ml = round(shot_s * flow, 1)
            shot_times = (
                sched.get("fixed_times") or []
                if sched.get("schedule_type") == "fixed_times"
                else compute_high_frequency_shot_times(
                    sched.get("window_start"),
                    sched.get("window_end"),
                    int(sched.get("feeds_per_day") or 4),
                    int(sched.get("p1_ramp_shots") or 2),
                    int(sched.get("p1_interval_min") or 30),
                    int(sched.get("p3_dryback_cutoff_min") or 120),
                )
                if (sched.get("schedule_type") or "high_frequency") == "high_frequency"
                else []
            )
            nxt = compute_next_fertigation_time(sched, now_utc)
            leak = self._read_raw_state(sched.get("leak_entity_id")) in (
                "on",
                "true",
                "wet",
                "problem",
            ) or bool(res_obj and res_obj.get("leak_detected"))

            enriched_sched = {
                **sched,
                "use_shared_pump": bool(sched.get("use_shared_pump")),
                "plant_name": (
                    plants_map[pid]["name"] if pid in plants_map else "Unknown Plant"
                ),
                "reservoir_name": res_obj["name"] if res_obj else None,
                "daily_volume_ml": daily_fert_vol.get(pid, 0.0),
                "estimated_shot_ml": est_shot_ml,
                "shot_times": shot_times,
                "next_fertigation_at": nxt,
                "leak_detected": leak,
                "reservoir_low": bool(res_obj and res_obj.get("low_level")),
            }
            fert_by_plant[pid] = enriched_sched
            if pid in plants_map:
                plants_map[pid]["fertigation"] = enriched_sched

        enriched_dosing_runs = [
            {
                **run,
                "reservoir_name": res_name_map.get(run["reservoir_id"]),
                "preset_name": preset_name_map.get(run.get("preset_id") or ""),
            }
            for run in raw_dosing_runs
        ]
        enriched_fert_events = [
            {
                **ev,
                "plant_name": (
                    plants_map[ev["plant_id"]]["name"]
                    if ev["plant_id"] in plants_map
                    else None
                ),
                "reservoir_name": res_name_map.get(ev.get("reservoir_id") or ""),
            }
            for ev in raw_fert_events
        ]

        self._rebind_state_listeners(tracked_entity_ids)

        result = {
            "environments": envs_map,
            "plants": plants_map,
            "recent_logs": recent_logs,
            "planned_logs": planned_logs,
            "scheduled_stage_changes": scheduled_stage_changes,
            "recent_photos": recent_photos,
            "nutrient_presets": nutrient_presets,
            "grow_cycles": enriched_cycles,
            "harvests": enriched_harvests,
            "reminders": enriched_reminders,
            "pollen_batches": enriched_pollen,
            "breeding_crosses": enriched_crosses,
            "seed_batches": raw_seed_batches,
            "pheno_hunts": enriched_pheno_hunts,
            "reservoirs": reservoirs_map,
            "dosing_channels": enriched_channels,
            "dosing_runs": enriched_dosing_runs,
            "fertigation_schedules": fert_by_plant,
            "fertigation_events": enriched_fert_events,
            "summary": {
                "active_plants": active_plant_count,
                "total_plants": len(plants_map),
                "total_environments": len(envs_map),
                "alerts_count": alerts_count,
                "total_logs": snapshot["totals"]["logs"],
                "total_photos": snapshot["totals"]["photos"],
                "total_harvests": len(enriched_harvests),
                "total_dry_yield_g": total_dry_yield_g,
                "avg_dry_yield_g": avg_dry_yield_g,
                "keeper_count": keeper_count,
                "total_grow_cycles": len(enriched_cycles),
                "active_reminders": active_reminders_count,
                "due_reminders": due_reminders_count,
                "pollen_batches": len(enriched_pollen),
                "breeding_crosses": len(enriched_crosses),
                "pheno_hunts": len(enriched_pheno_hunts),
                "seed_batches": len(raw_seed_batches),
                "reservoirs": len(reservoirs_map),
                "active_fertigation": sum(
                    1 for s in fert_by_plant.values() if s.get("mode") != "off"
                ),
            },
        }
        self.fertigation.schedule_background_check(result)
        return result

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
