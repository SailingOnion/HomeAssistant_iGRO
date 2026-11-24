"""Home Assistant services for iGro automations."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    EVENT_LOG_CREATED,
    EVENT_STAGE_CHANGED,
    GROW_STAGES,
    LOG_TYPES,
    SERVICE_ADVANCE_STAGE,
    SERVICE_CAPTURE_PHOTO,
    SERVICE_CREATE_PLANT,
    SERVICE_LOG_ACTION,
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


async def async_register_services(hass: HomeAssistant) -> None:
    """Register iGro Home Assistant services."""

    async def handle_log_action(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        data = dict(call.data)
        plant_ref = data.pop("plant", None)
        plant_id = _resolve_plant_id(coordinator, plant_ref) if plant_ref else None

        payload = {
            "plant_id": plant_id,
            "environment_id": data.get("environment_id"),
            "log_type": data["log_type"],
            "title": data.get("title"),
            "notes": data.get("notes"),
            "water_volume_ml": data.get("water_volume_ml"),
            "ph": data.get("ph"),
            "ec": data.get("ec"),
            "ppm": data.get("ppm"),
            "runoff_ph": data.get("runoff_ph"),
            "runoff_ec": data.get("runoff_ec"),
            "height_cm": data.get("height_cm"),
            "training_method": data.get("training_method"),
            "nutrients": data.get("nutrients"),
        }
        env_readings = coordinator.get_environment_readings_for_plant(plant_id)
        payload.update(
            {k: v for k, v in env_readings.items() if v is not None}
        )

        created = await coordinator.db.async_create_log(payload)
        hass.bus.async_fire(
            EVENT_LOG_CREATED,
            {
                "log_id": created["id"],
                "plant_id": plant_id,
                "log_type": created["log_type"],
            },
        )
        await coordinator.async_request_refresh()

    async def handle_set_stage(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        plant_id = _resolve_plant_id(coordinator, call.data["plant"])
        stage = call.data["stage"]
        await coordinator.db.async_set_plant_stage(
            plant_id, stage, notes=call.data.get("notes")
        )
        hass.bus.async_fire(
            EVENT_STAGE_CHANGED, {"plant_id": plant_id, "stage": stage}
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

    hass.services.async_register(
        DOMAIN,
        SERVICE_LOG_ACTION,
        handle_log_action,
        schema=vol.Schema(
            {
                vol.Optional("plant"): cv.string,
                vol.Optional("environment_id"): cv.string,
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
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_STAGE,
        handle_set_stage,
        schema=vol.Schema(
            {
                vol.Required("plant"): cv.string,
                vol.Required("stage"): vol.In(GROW_STAGES),
                vol.Optional("notes"): cv.string,
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


async def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister iGro services on unload."""
    for svc in (
        SERVICE_LOG_ACTION,
        SERVICE_SET_STAGE,
        SERVICE_ADVANCE_STAGE,
        SERVICE_CAPTURE_PHOTO,
        SERVICE_CREATE_PLANT,
    ):
        if hass.services.has_service(DOMAIN, svc):
            hass.services.async_remove(DOMAIN, svc)
