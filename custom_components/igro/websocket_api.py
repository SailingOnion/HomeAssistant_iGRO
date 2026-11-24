"""WebSocket API for the iGro Home Assistant sidebar panel."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import (
    DOMAIN,
    ENVIRONMENT_TYPES,
    EVENT_LOG_CREATED,
    EVENT_STAGE_CHANGED,
    GROW_MEDIUMS,
    GROW_STAGES,
    LOG_TYPES,
    PLANT_TYPES,
    STAGE_LABELS,
    STAGE_VPD_TARGETS,
)
from .coordinator import IGroCoordinator, photo_url
from .http_api import async_capture_camera_photo, async_remove_photo_file


def _get_coordinator(hass: HomeAssistant) -> IGroCoordinator | None:
    domain_data = hass.data.get(DOMAIN)
    if not domain_data:
        return None
    return domain_data.get("coordinator")


@callback
def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register all iGro WebSocket commands."""
    commands = [
        ws_get_state,
        ws_list_ha_entities,
        ws_create_environment,
        ws_update_environment,
        ws_delete_environment,
        ws_create_plant,
        ws_update_plant,
        ws_set_plant_stage,
        ws_delete_plant,
        ws_list_logs,
        ws_create_log,
        ws_delete_log,
        ws_list_photos,
        ws_capture_camera_photo,
        ws_delete_photo,
        ws_set_cover_photo,
    ]
    for cmd in commands:
        websocket_api.async_register_command(hass, cmd)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_state"})
@websocket_api.async_response
async def ws_get_state(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return full iGro state snapshot and schema metadata."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro is not initialized")
        return

    if coordinator.data is None:
        await coordinator.async_refresh()

    data = coordinator.data or {}
    connection.send_result(
        msg["id"],
        {
            "environments": list(data.get("environments", {}).values()),
            "plants": list(data.get("plants", {}).values()),
            "recent_logs": data.get("recent_logs", []),
            "recent_photos": data.get("recent_photos", []),
            "summary": data.get("summary", {}),
            "meta": {
                "stages": GROW_STAGES,
                "stage_labels": STAGE_LABELS,
                "stage_vpd_targets": {
                    k: {"min": v[0], "max": v[1]}
                    for k, v in STAGE_VPD_TARGETS.items()
                },
                "plant_types": PLANT_TYPES,
                "mediums": GROW_MEDIUMS,
                "environment_types": ENVIRONMENT_TYPES,
                "log_types": LOG_TYPES,
                "temperature_unit": hass.config.units.temperature_unit,
            },
        },
    )


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/list_ha_entities"})
@callback
def ws_list_ha_entities(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return categorized Home Assistant entities for sensor/device binding dropdowns."""
    temperature: list[dict[str, str]] = []
    humidity: list[dict[str, str]] = []
    moisture: list[dict[str, str]] = []
    co2: list[dict[str, str]] = []
    controls: list[dict[str, str]] = []
    cameras: list[dict[str, str]] = []

    for state in sorted(hass.states.async_all(), key=lambda s: s.entity_id):
        eid = state.entity_id
        if eid.startswith(f"sensor.{DOMAIN}_") or eid.startswith(
            f"binary_sensor.{DOMAIN}_"
        ):
            continue
        domain = eid.split(".", 1)[0]
        attrs = state.attributes
        dc = attrs.get("device_class")
        unit = (attrs.get("unit_of_measurement") or "").lower()
        name = attrs.get("friendly_name") or eid
        item = {"entity_id": eid, "name": name, "state": state.state}

        if domain == "camera":
            cameras.append(item)
        elif domain in ("light", "switch", "fan", "humidifier", "climate", "input_boolean"):
            controls.append(item)
        elif domain == "sensor":
            if dc == "temperature" or unit in ("°c", "°f", "c", "f"):
                temperature.append(item)
            if dc == "humidity" or "humidity" in eid or (unit == "%" and dc != "battery"):
                humidity.append(item)
            if dc == "moisture" or "moisture" in eid or "soil" in eid or unit == "%":
                moisture.append(item)
            if dc == "carbon_dioxide" or "co2" in eid or unit == "ppm":
                co2.append(item)

    connection.send_result(
        msg["id"],
        {
            "temperature": temperature,
            "humidity": humidity,
            "moisture": moisture,
            "co2": co2,
            "controls": controls,
            "cameras": cameras,
        },
    )


# ------------------------------------------------------------------
# Environments WS commands
# ------------------------------------------------------------------
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/environments/create",
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_create_environment(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a grow environment."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    created = await coordinator.db.async_create_environment(msg["data"])
    await coordinator.async_notify_structure_changed()
    connection.send_result(msg["id"], {"environment": created})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/environments/update",
        vol.Required("environment_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_update_environment(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update a grow environment."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    updated = await coordinator.db.async_update_environment(
        msg["environment_id"], msg["data"]
    )
    if updated is None:
        connection.send_error(msg["id"], "not_found", "Environment not found")
        return
    await coordinator.async_notify_structure_changed()
    connection.send_result(msg["id"], {"environment": updated})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/environments/delete",
        vol.Required("environment_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_environment(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a grow environment."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    deleted = await coordinator.db.async_delete_environment(msg["environment_id"])
    await coordinator.async_notify_structure_changed()
    connection.send_result(msg["id"], {"deleted": deleted})


# ------------------------------------------------------------------
# Plants WS commands
# ------------------------------------------------------------------
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/plants/create",
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_create_plant(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a new plant."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    created = await coordinator.db.async_create_plant(msg["data"])
    await coordinator.async_notify_structure_changed()
    connection.send_result(msg["id"], {"plant": created})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/plants/update",
        vol.Required("plant_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_update_plant(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update plant fields."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    updated = await coordinator.db.async_update_plant(msg["plant_id"], msg["data"])
    if updated is None:
        connection.send_error(msg["id"], "not_found", "Plant not found")
        return
    await coordinator.async_notify_structure_changed()
    connection.send_result(msg["id"], {"plant": updated})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/plants/set_stage",
        vol.Required("plant_id"): str,
        vol.Required("stage"): vol.In(GROW_STAGES),
        vol.Optional("notes"): vol.Any(str, None),
        vol.Optional("changed_at"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_set_plant_stage(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Change a plant's grow stage."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    updated = await coordinator.db.async_set_plant_stage(
        msg["plant_id"],
        msg["stage"],
        notes=msg.get("notes"),
        changed_at=msg.get("changed_at"),
    )
    if updated is None:
        connection.send_error(msg["id"], "not_found", "Plant not found")
        return
    hass.bus.async_fire(
        EVENT_STAGE_CHANGED,
        {"plant_id": msg["plant_id"], "stage": msg["stage"]},
    )
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"plant": updated})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/plants/delete",
        vol.Required("plant_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_plant(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a plant and its photo files."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    filenames = await coordinator.db.async_delete_plant(msg["plant_id"])
    for fname in filenames:
        await async_remove_photo_file(coordinator.media_dir, fname)
    await coordinator.async_notify_structure_changed()
    connection.send_result(msg["id"], {"deleted": True})


# ------------------------------------------------------------------
# Journal Logs WS commands
# ------------------------------------------------------------------
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/logs/list",
        vol.Optional("plant_id"): vol.Any(str, None),
        vol.Optional("environment_id"): vol.Any(str, None),
        vol.Optional("log_type"): vol.Any(str, None),
        vol.Optional("limit", default=100): int,
        vol.Optional("offset", default=0): int,
    }
)
@websocket_api.async_response
async def ws_list_logs(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List grow journal logs with optional filters."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    logs = await coordinator.db.async_list_logs(
        plant_id=msg.get("plant_id"),
        environment_id=msg.get("environment_id"),
        log_type=msg.get("log_type"),
        limit=msg.get("limit", 100),
        offset=msg.get("offset", 0),
    )
    plants = (coordinator.data or {}).get("plants", {})
    envs = (coordinator.data or {}).get("environments", {})
    enriched = [
        {
            **lg,
            "plant_name": (
                plants[lg["plant_id"]]["name"] if lg.get("plant_id") in plants else None
            ),
            "environment_name": (
                envs[lg["environment_id"]]["name"]
                if lg.get("environment_id") in envs
                else None
            ),
        }
        for lg in logs
    ]
    connection.send_result(msg["id"], {"logs": enriched})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/logs/create",
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_create_log(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a journal log entry, capturing current environment readings if omitted."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return

    payload = dict(msg["data"])
    env_readings = coordinator.get_environment_readings_for_plant(
        payload.get("plant_id")
    )
    for k in ("temp_c", "humidity", "vpd_kpa"):
        if payload.get(k) is None and env_readings.get(k) is not None:
            payload[k] = env_readings[k]

    created = await coordinator.db.async_create_log(payload)
    hass.bus.async_fire(
        EVENT_LOG_CREATED,
        {
            "log_id": created["id"],
            "plant_id": created.get("plant_id"),
            "log_type": created.get("log_type"),
        },
    )
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"log": created})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/logs/delete",
        vol.Required("log_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_log(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a journal log entry."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    deleted = await coordinator.db.async_delete_log(msg["log_id"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"deleted": deleted})


# ------------------------------------------------------------------
# Photos WS commands
# ------------------------------------------------------------------
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/photos/list",
        vol.Optional("plant_id"): vol.Any(str, None),
        vol.Optional("environment_id"): vol.Any(str, None),
        vol.Optional("stage"): vol.Any(str, None),
        vol.Optional("limit", default=120): int,
    }
)
@websocket_api.async_response
async def ws_list_photos(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List photos with URLs."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    photos = await coordinator.db.async_list_photos(
        plant_id=msg.get("plant_id"),
        environment_id=msg.get("environment_id"),
        stage=msg.get("stage"),
        limit=msg.get("limit", 120),
    )
    plants = (coordinator.data or {}).get("plants", {})
    envs = (coordinator.data or {}).get("environments", {})
    enriched = [
        {
            **ph,
            "url": photo_url(ph["id"], ph["access_token"]),
            "plant_name": (
                plants[ph["plant_id"]]["name"] if ph.get("plant_id") in plants else None
            ),
            "environment_name": (
                envs[ph["environment_id"]]["name"]
                if ph.get("environment_id") in envs
                else None
            ),
        }
        for ph in photos
    ]
    connection.send_result(msg["id"], {"photos": enriched})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/photos/capture_camera",
        vol.Required("camera_entity_id"): str,
        vol.Optional("plant_id"): vol.Any(str, None),
        vol.Optional("environment_id"): vol.Any(str, None),
        vol.Optional("stage"): vol.Any(str, None),
        vol.Optional("caption"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_capture_camera_photo(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Capture a photo from an HA camera entity."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    try:
        record = await async_capture_camera_photo(
            hass,
            coordinator,
            msg["camera_entity_id"],
            plant_id=msg.get("plant_id"),
            environment_id=msg.get("environment_id"),
            stage=msg.get("stage"),
            caption=msg.get("caption"),
        )
    except Exception as err:
        connection.send_error(msg["id"], "capture_failed", str(err))
        return
    connection.send_result(msg["id"], {"photo": record})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/photos/delete",
        vol.Required("photo_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_photo(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a photo from SQLite and disk."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    filename = await coordinator.db.async_delete_photo(msg["photo_id"])
    if filename:
        await async_remove_photo_file(coordinator.media_dir, filename)
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"deleted": filename is not None})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/photos/set_cover",
        vol.Required("plant_id"): str,
        vol.Required("photo_id"): str,
    }
)
@websocket_api.async_response
async def ws_set_cover_photo(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set a plant's cover photo."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    updated = await coordinator.db.async_update_plant(
        msg["plant_id"], {"cover_photo_id": msg["photo_id"]}
    )
    if updated is None:
        connection.send_error(msg["id"], "not_found", "Plant not found")
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"plant": updated})
