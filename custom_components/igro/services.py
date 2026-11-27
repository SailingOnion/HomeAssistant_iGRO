"""Home Assistant services for iGro automations."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .calculations import (
    is_timestamp_in_future,
    is_timestamp_near_now,
    scale_nutrients_for_volume,
)
from .const import (
    ACTIVE_STAGES,
    DOMAIN,
    EVENT_HARVEST_RECORDED,
    EVENT_LOG_CREATED,
    EVENT_STAGE_CHANGED,
    GROW_STAGES,
    LOG_TYPES,
    SERVICE_ADVANCE_STAGE,
    SERVICE_CAPTURE_PHOTO,
    SERVICE_COMPLETE_REMINDER,
    SERVICE_CREATE_PLANT,
    SERVICE_CREATE_REMINDER,
    SERVICE_DOSE_CHANNEL,
    SERVICE_EMERGENCY_STOP,
    SERVICE_FERTIGATE_PLANT,
    SERVICE_LOG_ACTION,
    SERVICE_MIX_RESERVOIR_BATCH,
    SERVICE_RECORD_HARVEST,
    SERVICE_SET_STAGE,
)
from .coordinator import IGroCoordinator
from .http_api import async_capture_camera_photo

_LOGGER = logging.getLogger(__name__)


def _get_coordinator(hass: HomeAssistant) -> IGroCoordinator:
    domain_data = hass.data.get(DOMAIN)
    if not domain_data or "coordinator" not in domain_data:
        raise HomeAssistantError("iGro integration is not loaded")
    return domain_data["coordinator"]


def _resolve_plant_id(coordinator: IGroCoordinator, identifier: str) -> str:
    """Resolve a plant by ID or case-insensitive name."""
    plants = (coordinator.data or {}).get("plants", {})
    if identifier in plants:
        return identifier
    lowered = identifier.strip().lower()
    for pid, plant in plants.items():
        if plant["name"].strip().lower() == lowered:
            return pid
    raise HomeAssistantError(f"Plant '{identifier}' not found")


def _resolve_preset(
    coordinator: IGroCoordinator, identifier: str
) -> dict[str, object]:
    """Resolve a nutrient preset by ID or case-insensitive name."""
    presets = (coordinator.data or {}).get("nutrient_presets", [])
    lowered = identifier.strip().lower()
    for preset in presets:
        if preset["id"] == identifier or preset["name"].strip().lower() == lowered:
            return preset
    raise HomeAssistantError(f"Nutrient preset '{identifier}' not found")


def _resolve_environment_id(coordinator: IGroCoordinator, identifier: str) -> str:
    """Resolve an environment by ID or case-insensitive name."""
    envs = (coordinator.data or {}).get("environments", {})
    if identifier in envs:
        return identifier
    lowered = identifier.strip().lower()
    for eid, env in envs.items():
        if env["name"].strip().lower() == lowered:
            return eid
    raise HomeAssistantError(f"Environment '{identifier}' not found")


def _resolve_target_plant_ids(
    coordinator: IGroCoordinator,
    *,
    plant_ref: str | None = None,
    plant_refs: list[str] | None = None,
    environment_ref: str | None = None,
) -> list[str]:
    """Resolve target plant IDs from single plant, list of plants, or environment."""
    if plant_refs:
        return [_resolve_plant_id(coordinator, ref) for ref in plant_refs]
    if plant_ref:
        return [_resolve_plant_id(coordinator, plant_ref)]
    if environment_ref:
        env_id = _resolve_environment_id(coordinator, environment_ref)
        plants = (coordinator.data or {}).get("plants", {})
        active = [
            pid
            for pid, p in plants.items()
            if p.get("environment_id") == env_id and p.get("stage") in ACTIVE_STAGES
        ]
        if active:
            return active
        return [pid for pid, p in plants.items() if p.get("environment_id") == env_id]
    return []


async def async_register_services(hass: HomeAssistant) -> None:
    """Register iGro Home Assistant services."""

    async def handle_log_action(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        data = dict(call.data)
        plant_ref = data.pop("plant", None)
        plant_refs = data.pop("plants", None)
        env_ref = data.get("environment_id")
        split_vol = bool(data.pop("split_water_volume", False))

        target_ids = _resolve_target_plant_ids(
            coordinator,
            plant_ref=plant_ref,
            plant_refs=plant_refs,
            environment_ref=env_ref if not plant_ref and not plant_refs else None,
        )
        preset_ref = data.pop("preset", None)
        preset = _resolve_preset(coordinator, preset_ref) if preset_ref else None

        nutrients = data.get("nutrients")
        water_volume_ml = data.get("water_volume_ml")
        title = data.get("title")
        ph = data.get("ph")
        ec = data.get("ec")
        ppm = data.get("ppm")

        if preset is not None:
            if not nutrients:
                nutrients = scale_nutrients_for_volume(
                    preset.get("nutrients") or [], water_volume_ml
                )
            if not title:
                title = f"Feed: {preset['name']}"
            if ph is None:
                ph = preset.get("target_ph")
            if ec is None:
                ec = preset.get("target_ec")
            if ppm is None:
                ppm = preset.get("target_ppm")

        logged_at = data.get("logged_at")
        status = data.get("status")
        is_planned = status == "planned" or (
            status is None and is_timestamp_in_future(logged_at)
        )
        should_snapshot = not is_planned and is_timestamp_near_now(logged_at)

        payload = {
            "environment_id": (
                _resolve_environment_id(coordinator, env_ref) if env_ref else None
            ),
            "log_type": data["log_type"],
            "title": title,
            "notes": data.get("notes"),
            "logged_at": logged_at,
            "status": status,
            "water_volume_ml": water_volume_ml,
            "ph": ph,
            "ec": ec,
            "ppm": ppm,
            "runoff_ph": data.get("runoff_ph"),
            "runoff_ec": data.get("runoff_ec"),
            "height_cm": data.get("height_cm"),
            "training_method": data.get("training_method"),
            "nutrients": nutrients,
        }

        if target_ids:
            readings_map = (
                {
                    pid: coordinator.get_environment_readings_for_plant(pid)
                    for pid in target_ids
                }
                if should_snapshot
                else {}
            )
            created_list = await coordinator.db.async_create_logs_batch(
                target_ids,
                payload,
                split_water_volume=split_vol,
                env_readings_by_plant=readings_map,
            )
            for created in created_list:
                hass.bus.async_fire(
                    EVENT_LOG_CREATED,
                    {
                        "log_id": created["id"],
                        "plant_id": created.get("plant_id"),
                        "log_type": created["log_type"],
                        "status": created.get("status"),
                    },
                )
            await coordinator.async_request_refresh()
            return

        created = await coordinator.db.async_create_log(payload)
        hass.bus.async_fire(
            EVENT_LOG_CREATED,
            {
                "log_id": created["id"],
                "plant_id": None,
                "log_type": created["log_type"],
                "status": created.get("status"),
            },
        )
        await coordinator.async_request_refresh()

    async def handle_set_stage(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        target_ids = _resolve_target_plant_ids(
            coordinator,
            plant_ref=call.data.get("plant"),
            plant_refs=call.data.get("plants"),
            environment_ref=call.data.get("environment_id"),
        )
        if not target_ids:
            raise HomeAssistantError(
                "Provide 'plant', 'plants', or 'environment_id' to set stage"
            )
        stage = call.data["stage"]
        changed_at = call.data.get("changed_at")
        if changed_at and is_timestamp_in_future(changed_at):
            for pid in target_ids:
                await coordinator.db.async_schedule_stage_change(
                    pid,
                    stage,
                    changed_at,
                    auto_apply=call.data.get("auto_apply", True),
                    notes=call.data.get("notes"),
                )
            await coordinator.async_request_refresh()
            return
        updated = await coordinator.db.async_batch_set_plant_stage(
            target_ids, stage, notes=call.data.get("notes"), changed_at=changed_at
        )
        for item in updated:
            hass.bus.async_fire(
                EVENT_STAGE_CHANGED, {"plant_id": item["id"], "stage": stage}
            )
        await coordinator.async_request_refresh()

    async def handle_advance_stage(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        plant_id = _resolve_plant_id(coordinator, call.data["plant"])
        plant = (coordinator.data or {}).get("plants", {}).get(plant_id)
        if not plant:
            raise HomeAssistantError(f"Plant '{plant_id}' not found")
        cur_stage = plant["stage"]
        idx = GROW_STAGES.index(cur_stage) if cur_stage in GROW_STAGES else 0
        if idx + 1 >= len(GROW_STAGES):
            raise HomeAssistantError(f"Plant is already at final stage '{cur_stage}'")
        next_stage = GROW_STAGES[idx + 1]
        await coordinator.db.async_set_plant_stage(
            plant_id, next_stage, notes=call.data.get("notes")
        )
        hass.bus.async_fire(
            EVENT_STAGE_CHANGED, {"plant_id": plant_id, "stage": next_stage}
        )
        await coordinator.async_request_refresh()

    async def handle_capture_photo(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        plant_ref = call.data.get("plant")
        plant_id = _resolve_plant_id(coordinator, plant_ref) if plant_ref else None
        camera_entity_id = call.data.get("camera_entity_id")

        if not camera_entity_id and plant_id:
            plant = (coordinator.data or {}).get("plants", {}).get(plant_id)
            camera_entity_id = (plant or {}).get("effective_camera_entity_id")

        if not camera_entity_id:
            raise HomeAssistantError(
                "No camera_entity_id provided and none linked to the plant or its environment"
            )

        await async_capture_camera_photo(
            hass,
            coordinator,
            camera_entity_id,
            plant_id=plant_id,
            environment_id=call.data.get("environment_id"),
            caption=call.data.get("caption"),
        )

    async def handle_create_plant(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        await coordinator.db.async_create_plant(dict(call.data))
        await coordinator.async_notify_structure_changed()

    async def handle_record_harvest(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        data = dict(call.data)
        plant_id = _resolve_plant_id(coordinator, data.pop("plant"))
        harvest = await coordinator.db.async_upsert_harvest(plant_id, data)
        if harvest is None:
            raise HomeAssistantError(f"Plant '{plant_id}' not found")
        hass.bus.async_fire(
            EVENT_HARVEST_RECORDED,
            {
                "harvest_id": harvest["id"],
                "plant_id": plant_id,
                "dry_weight_g": harvest.get("dry_weight_g"),
                "wet_weight_g": harvest.get("wet_weight_g"),
            },
        )
        await coordinator.async_request_refresh()

    async def handle_create_reminder(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        data = dict(call.data)
        plant_ref = data.pop("plant", None)
        if plant_ref:
            data["plant_id"] = _resolve_plant_id(coordinator, plant_ref)
        await coordinator.db.async_create_reminder(data)
        await coordinator.async_request_refresh()

    async def handle_complete_reminder(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        result = await coordinator.db.async_complete_reminder(
            call.data["reminder_id"],
            create_log=call.data.get("create_log"),
        )
        if result is None:
            raise HomeAssistantError(
                f"Reminder '{call.data['reminder_id']}' not found"
            )
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_LOG_ACTION,
        handle_log_action,
        schema=vol.Schema(
            {
                vol.Optional("plant"): cv.string,
                vol.Optional("plants"): [cv.string],
                vol.Optional("environment_id"): cv.string,
                vol.Optional("split_water_volume", default=False): cv.boolean,
                vol.Required("log_type"): vol.In(LOG_TYPES),
                vol.Optional("title"): cv.string,
                vol.Optional("notes"): cv.string,
                vol.Optional("water_volume_ml"): vol.Coerce(float),
                vol.Optional("ph"): vol.Coerce(float),
                vol.Optional("ec"): vol.Coerce(float),
                vol.Optional("ppm"): vol.Coerce(float),
                vol.Optional("runoff_ph"): vol.Coerce(float),
                vol.Optional("runoff_ec"): vol.Coerce(float),
                vol.Optional("height_cm"): vol.Coerce(float),
                vol.Optional("training_method"): cv.string,
                vol.Optional("nutrients"): list,
                vol.Optional("preset"): cv.string,
                vol.Optional("logged_at"): cv.string,
                vol.Optional("status"): vol.In(["completed", "planned"]),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_STAGE,
        handle_set_stage,
        schema=vol.Schema(
            {
                vol.Optional("plant"): cv.string,
                vol.Optional("plants"): [cv.string],
                vol.Optional("environment_id"): cv.string,
                vol.Required("stage"): vol.In(GROW_STAGES),
                vol.Optional("notes"): cv.string,
                vol.Optional("changed_at"): cv.string,
                vol.Optional("auto_apply", default=True): cv.boolean,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADVANCE_STAGE,
        handle_advance_stage,
        schema=vol.Schema(
            {
                vol.Required("plant"): cv.string,
                vol.Optional("notes"): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CAPTURE_PHOTO,
        handle_capture_photo,
        schema=vol.Schema(
            {
                vol.Optional("plant"): cv.string,
                vol.Optional("environment_id"): cv.string,
                vol.Optional("camera_entity_id"): cv.entity_id,
                vol.Optional("caption"): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_PLANT,
        handle_create_plant,
        schema=vol.Schema(
            {
                vol.Required("name"): cv.string,
                vol.Optional("strain"): cv.string,
                vol.Optional("breeder"): cv.string,
                vol.Optional("plant_type", default="photoperiod"): cv.string,
                vol.Optional("medium", default="soil"): cv.string,
                vol.Optional("pot_size"): cv.string,
                vol.Optional("environment_id"): cv.string,
                vol.Optional("stage", default="germination"): vol.In(GROW_STAGES),
                vol.Optional("notes"): cv.string,
            }
        ),
    )


    hass.services.async_register(
        DOMAIN,
        SERVICE_RECORD_HARVEST,
        handle_record_harvest,
        schema=vol.Schema(
            {
                vol.Required("plant"): cv.string,
                vol.Optional("harvested_at"): cv.string,
                vol.Optional("wet_weight_g"): vol.Coerce(float),
                vol.Optional("dry_weight_g"): vol.Coerce(float),
                vol.Optional("trim_weight_g"): vol.Coerce(float),
                vol.Optional("dry_days"): vol.Coerce(int),
                vol.Optional("cure_rh_pct"): vol.Coerce(float),
                vol.Optional("aroma_notes"): cv.string,
                vol.Optional("effect_notes"): cv.string,
                vol.Optional("rating"): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=5)
                ),
                vol.Optional("is_keeper", default=False): cv.boolean,
                vol.Optional("set_plant_stage"): vol.In(GROW_STAGES),
                vol.Optional("notes"): cv.string,
            }
        ),
    )


    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_REMINDER,
        handle_create_reminder,
        schema=vol.Schema(
            {
                vol.Required("title"): cv.string,
                vol.Optional("plant"): cv.string,
                vol.Optional("environment_id"): cv.string,
                vol.Optional("action_type", default="water"): cv.string,
                vol.Optional("due_at"): cv.string,
                vol.Optional("recurrence_days"): vol.Coerce(int),
                vol.Optional("moisture_threshold"): vol.Coerce(float),
                vol.Optional("auto_log_on_complete", default=True): cv.boolean,
                vol.Optional("notes"): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPLETE_REMINDER,
        handle_complete_reminder,
        schema=vol.Schema(
            {
                vol.Required("reminder_id"): cv.string,
                vol.Optional("create_log"): cv.boolean,
            }
        ),
    )

    async def handle_fertigate_plant(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        plant_id = _resolve_plant_id(coordinator, call.data["plant"])
        try:
            await coordinator.fertigation.async_run_fertigation_shot(
                plant_id,
                trigger_type="manual",
                duration_s=call.data.get("duration_s"),
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def handle_mix_reservoir_batch(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        preset = _resolve_preset(coordinator, call.data["preset"])
        try:
            await coordinator.fertigation.async_run_batch_mix(
                call.data["reservoir_id"],
                str(preset["id"]),
                float(call.data["target_volume_l"]),
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def handle_dose_channel(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        try:
            await coordinator.fertigation.async_dose_channel(
                call.data["channel_id"],
                float(call.data["dose_ml"]),
                run_type=call.data.get("run_type", "manual_dose"),
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def handle_emergency_stop(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        await coordinator.fertigation.async_emergency_stop(
            call.data.get("reason") or "Emergency stop service called"
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_FERTIGATE_PLANT,
        handle_fertigate_plant,
        schema=vol.Schema(
            {
                vol.Required("plant"): cv.string,
                vol.Optional("duration_s"): vol.Coerce(float),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_MIX_RESERVOIR_BATCH,
        handle_mix_reservoir_batch,
        schema=vol.Schema(
            {
                vol.Required("reservoir_id"): cv.string,
                vol.Required("preset"): cv.string,
                vol.Required("target_volume_l"): vol.Coerce(float),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DOSE_CHANNEL,
        handle_dose_channel,
        schema=vol.Schema(
            {
                vol.Required("channel_id"): cv.string,
                vol.Required("dose_ml"): vol.Coerce(float),
                vol.Optional("run_type", default="manual_dose"): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_EMERGENCY_STOP,
        handle_emergency_stop,
        schema=vol.Schema({vol.Optional("reason"): cv.string}),
    )


async def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister iGro services on unload."""
    for svc in (
        SERVICE_LOG_ACTION,
        SERVICE_SET_STAGE,
        SERVICE_ADVANCE_STAGE,
        SERVICE_CAPTURE_PHOTO,
        SERVICE_CREATE_PLANT,
        SERVICE_RECORD_HARVEST,
        SERVICE_CREATE_REMINDER,
        SERVICE_COMPLETE_REMINDER,
        SERVICE_FERTIGATE_PLANT,
        SERVICE_MIX_RESERVOIR_BATCH,
        SERVICE_DOSE_CHANNEL,
        SERVICE_EMERGENCY_STOP,
    ):
        if hass.services.has_service(DOMAIN, svc):
            hass.services.async_remove(DOMAIN, svc)
