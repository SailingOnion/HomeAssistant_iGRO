"""WebSocket API for the iGro Home Assistant sidebar panel."""

from __future__ import annotations

from typing import Any

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
import voluptuous as vol

from .calculations import (
    compute_harvest_metrics,
    is_timestamp_in_future,
    is_timestamp_near_now,
)
from .const import (
    BREEDING_GENERATIONS,
    DOMAIN,
    DOSING_CHANNEL_ROLES,
    ENVIRONMENT_TYPES,
    EVENT_HARVEST_RECORDED,
    EVENT_LOG_CREATED,
    EVENT_STAGE_CHANGED,
    FERTIGATION_MODES,
    FERTIGATION_SCHEDULE_TYPES,
    GROW_MEDIUMS,
    GROW_STAGES,
    LOG_TYPES,
    PHENO_STATUSES,
    PLANT_TYPES,
    POLLEN_DONOR_TYPES,
    POLLEN_VIABILITIES,
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
        ws_update_log,
        ws_complete_log,
        ws_delete_log,
        ws_add_stage_history,
        ws_update_stage_history,
        ws_delete_stage_history,
        ws_schedule_stage_change,
        ws_apply_scheduled_stage_change,
        ws_cancel_scheduled_stage_change,
        ws_list_photos,
        ws_capture_camera_photo,
        ws_delete_photo,
        ws_set_cover_photo,
        ws_list_presets,
        ws_create_preset,
        ws_update_preset,
        ws_delete_preset,
        ws_create_grow_cycle,
        ws_update_grow_cycle,
        ws_delete_grow_cycle,
        ws_upsert_harvest,
        ws_delete_harvest,
        ws_add_curing_log,
        ws_delete_curing_log,
        ws_export_plant_report,
        ws_list_reminders,
        ws_create_reminder,
        ws_update_reminder,
        ws_complete_reminder,
        ws_delete_reminder,
        ws_create_pollen_batch,
        ws_update_pollen_batch,
        ws_delete_pollen_batch,
        ws_create_breeding_cross,
        ws_update_breeding_cross,
        ws_harvest_cross_seeds,
        ws_delete_breeding_cross,
        ws_delete_seed_batch,
        ws_create_pheno_hunt,
        ws_update_pheno_hunt,
        ws_delete_pheno_hunt,
        ws_upsert_pheno_score,
        ws_delete_pheno_score,
        ws_create_reservoir,
        ws_update_reservoir,
        ws_delete_reservoir,
        ws_mix_reservoir_batch,
        ws_auto_trim_reservoir,
        ws_emergency_stop,
        ws_clear_reservoir_lockout,
        ws_create_dosing_channel,
        ws_update_dosing_channel,
        ws_delete_dosing_channel,
        ws_dose_channel,
        ws_refill_channel,
        ws_upsert_fertigation_schedule,
        ws_delete_fertigation_schedule,
        ws_run_fertigation_shot,
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
            "planned_logs": data.get("planned_logs", []),
            "scheduled_stage_changes": data.get("scheduled_stage_changes", []),
            "recent_photos": data.get("recent_photos", []),
            "nutrient_presets": data.get("nutrient_presets", []),
            "grow_cycles": data.get("grow_cycles", []),
            "harvests": data.get("harvests", []),
            "reminders": data.get("reminders", []),
            "pollen_batches": data.get("pollen_batches", []),
            "breeding_crosses": data.get("breeding_crosses", []),
            "seed_batches": data.get("seed_batches", []),
            "pheno_hunts": data.get("pheno_hunts", []),
            "reservoirs": list(data.get("reservoirs", {}).values()),
            "dosing_channels": data.get("dosing_channels", []),
            "dosing_runs": data.get("dosing_runs", []),
            "fertigation_schedules": list(
                data.get("fertigation_schedules", {}).values()
            ),
            "fertigation_events": data.get("fertigation_events", []),
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
                "breeding_generations": BREEDING_GENERATIONS,
                "pollen_donor_types": POLLEN_DONOR_TYPES,
                "pollen_viabilities": POLLEN_VIABILITIES,
                "pheno_statuses": PHENO_STATUSES,
                "fertigation_modes": FERTIGATION_MODES,
                "fertigation_schedule_types": FERTIGATION_SCHEDULE_TYPES,
                "dosing_channel_roles": DOSING_CHANNEL_ROLES,
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
    sensors: list[dict[str, str]] = []
    binary_sensors: list[dict[str, str]] = []
    numbers: list[dict[str, str]] = []

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
        elif domain in (
            "light",
            "switch",
            "valve",
            "fan",
            "humidifier",
            "climate",
            "input_boolean",
        ):
            controls.append(item)
        elif domain == "binary_sensor":
            binary_sensors.append(item)
        elif domain in ("number", "input_number"):
            numbers.append(item)
        elif domain == "sensor":
            sensors.append(item)
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
            "sensors": sensors,
            "binary_sensors": binary_sensors,
            "numbers": numbers,
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
        vol.Optional("status"): vol.Any(str, None),
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
        status=msg.get("status"),
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
    """Create a journal log entry, snapshotting live climate only when near now."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return

    payload = dict(msg["data"])
    logged_at = payload.get("logged_at")
    status = payload.get("status")
    is_planned = status == "planned" or (
        status is None and is_timestamp_in_future(logged_at)
    )
    if not is_planned and is_timestamp_near_now(logged_at):
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
            "status": created.get("status"),
        },
    )
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"log": created})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/logs/update",
        vol.Required("log_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_update_log(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update an existing journal log entry."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    updated = await coordinator.db.async_update_log(msg["log_id"], msg["data"])
    if updated is None:
        connection.send_error(msg["id"], "not_found", "Log entry not found")
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"log": updated})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/logs/complete",
        vol.Required("log_id"): str,
        vol.Optional("data"): dict,
    }
)
@websocket_api.async_response
async def ws_complete_log(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Mark a planned journal entry as completed."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    updated = await coordinator.db.async_complete_log(
        msg["log_id"], msg.get("data")
    )
    if updated is None:
        connection.send_error(msg["id"], "not_found", "Log entry not found")
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"log": updated})


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
# Stage History & Scheduled Stage Change WS commands
# ------------------------------------------------------------------
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/stage_history/add",
        vol.Required("plant_id"): str,
        vol.Required("stage"): vol.In(GROW_STAGES),
        vol.Required("started_at"): str,
        vol.Optional("notes"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_add_stage_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Add a retrospective stage history entry and recalculate timeline."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    created = await coordinator.db.async_add_stage_history(
        msg["plant_id"], msg["stage"], msg["started_at"], msg.get("notes")
    )
    if created is None:
        connection.send_error(msg["id"], "not_found", "Plant not found")
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"history": created})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/stage_history/update",
        vol.Required("history_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_update_stage_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update a stage history entry's stage, date, or notes."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    updated = await coordinator.db.async_update_stage_history(
        msg["history_id"], msg["data"]
    )
    if updated is None:
        connection.send_error(msg["id"], "not_found", "Stage history entry not found")
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"history": updated})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/stage_history/delete",
        vol.Required("history_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_stage_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a stage history entry and recalculate timeline."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    try:
        deleted = await coordinator.db.async_delete_stage_history(msg["history_id"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_operation", str(err))
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"deleted": deleted})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/stage_schedule/create",
        vol.Required("plant_id"): str,
        vol.Required("target_stage"): vol.In(GROW_STAGES),
        vol.Required("scheduled_for"): str,
        vol.Optional("auto_apply", default=True): bool,
        vol.Optional("notes"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_schedule_stage_change(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Schedule a future stage transition for a plant."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    created = await coordinator.db.async_schedule_stage_change(
        msg["plant_id"],
        msg["target_stage"],
        msg["scheduled_for"],
        auto_apply=msg.get("auto_apply", True),
        notes=msg.get("notes"),
    )
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"schedule": created})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/stage_schedule/apply",
        vol.Required("schedule_id"): str,
    }
)
@websocket_api.async_response
async def ws_apply_scheduled_stage_change(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Apply a scheduled stage transition immediately."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    applied = await coordinator.db.async_apply_scheduled_stage_change(
        msg["schedule_id"]
    )
    if applied is None:
        connection.send_error(msg["id"], "not_found", "Scheduled transition not found")
        return
    hass.bus.async_fire(
        EVENT_STAGE_CHANGED,
        {"plant_id": applied["plant_id"], "stage": applied["stage"]},
    )
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"applied": applied})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/stage_schedule/cancel",
        vol.Required("schedule_id"): str,
    }
)
@websocket_api.async_response
async def ws_cancel_scheduled_stage_change(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Cancel a pending scheduled stage transition."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    cancelled = await coordinator.db.async_cancel_scheduled_stage_change(
        msg["schedule_id"]
    )
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"cancelled": cancelled})


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


# ------------------------------------------------------------------
# Nutrient Presets WS commands
# ------------------------------------------------------------------
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/presets/list",
        vol.Optional("stage"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_list_presets(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List saved nutrient presets."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    presets = await coordinator.db.async_list_nutrient_presets(stage=msg.get("stage"))
    connection.send_result(msg["id"], {"presets": presets})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/presets/create",
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_create_preset(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a nutrient preset recipe."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    created = await coordinator.db.async_create_nutrient_preset(msg["data"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"preset": created})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/presets/update",
        vol.Required("preset_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_update_preset(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update a nutrient preset recipe."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    updated = await coordinator.db.async_update_nutrient_preset(
        msg["preset_id"], msg["data"]
    )
    if updated is None:
        connection.send_error(msg["id"], "not_found", "Preset not found")
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"preset": updated})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/presets/delete",
        vol.Required("preset_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_preset(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a nutrient preset."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    deleted = await coordinator.db.async_delete_nutrient_preset(msg["preset_id"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"deleted": deleted})


# ------------------------------------------------------------------
# Grow Cycles, Harvests, Curing & Export WS commands
# ------------------------------------------------------------------
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/cycles/create",
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_create_grow_cycle(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a grow cycle."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    created = await coordinator.db.async_create_grow_cycle(msg["data"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"cycle": created})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/cycles/update",
        vol.Required("cycle_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_update_grow_cycle(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update a grow cycle."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    updated = await coordinator.db.async_update_grow_cycle(
        msg["cycle_id"], msg["data"]
    )
    if updated is None:
        connection.send_error(msg["id"], "not_found", "Grow cycle not found")
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"cycle": updated})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/cycles/delete",
        vol.Required("cycle_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_grow_cycle(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a grow cycle."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    deleted = await coordinator.db.async_delete_grow_cycle(msg["cycle_id"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"deleted": deleted})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/harvests/upsert",
        vol.Required("plant_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_upsert_harvest(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Record or update harvest & yield metrics for a plant."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    harvest = await coordinator.db.async_upsert_harvest(msg["plant_id"], msg["data"])
    if harvest is None:
        connection.send_error(msg["id"], "not_found", "Plant not found")
        return
    hass.bus.async_fire(
        EVENT_HARVEST_RECORDED,
        {
            "harvest_id": harvest["id"],
            "plant_id": msg["plant_id"],
            "dry_weight_g": harvest.get("dry_weight_g"),
            "wet_weight_g": harvest.get("wet_weight_g"),
        },
    )
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"harvest": harvest})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/harvests/delete",
        vol.Required("harvest_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_harvest(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a harvest record."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    deleted = await coordinator.db.async_delete_harvest(msg["harvest_id"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"deleted": deleted})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/curing/add",
        vol.Required("harvest_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_add_curing_log(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Add a curing jar check / burp log entry."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    created = await coordinator.db.async_add_curing_log(msg["harvest_id"], msg["data"])
    if created is None:
        connection.send_error(msg["id"], "not_found", "Harvest not found")
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"curing_log": created})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/curing/delete",
        vol.Required("curing_log_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_curing_log(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a curing jar log entry."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    deleted = await coordinator.db.async_delete_curing_log(msg["curing_log_id"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"deleted": deleted})


def _format_plant_report_markdown(report: dict[str, Any]) -> str:
    """Format a plant's full grow & harvest summary as clean Markdown."""
    plant = report["plant"]
    env = report.get("environment")
    cycle = report.get("grow_cycle")
    harvest = report.get("harvest")
    lines = [
        f"# Grow Report: {plant['name']}",
        "",
        f"- **Strain:** {plant.get('strain') or '—'}",
        f"- **Breeder:** {plant.get('breeder') or '—'}",
        f"- **Type / Medium:** {plant.get('plant_type') or '—'} / {plant.get('medium') or '—'}",
        f"- **Pot Size:** {plant.get('pot_size') or '—'}",
        f"- **Environment:** {env['name'] if env else '—'}",
        f"- **Grow Cycle:** {cycle['name'] if cycle else '—'}",
        f"- **Started:** {plant.get('started_at') or '—'}",
        f"- **Current Stage:** {plant.get('stage') or '—'}",
        "",
    ]
    if harvest:
        metrics = compute_harvest_metrics(
            harvest,
            env_light_wattage=env.get("light_wattage") if env else None,
        )
        lines.extend(
            [
                "## Harvest & Yield",
                f"- **Harvested:** {harvest.get('harvested_at') or '—'}",
                f"- **Wet Weight:** {harvest.get('wet_weight_g') if harvest.get('wet_weight_g') is not None else '—'} g",
                f"- **Dry Weight:** {harvest.get('dry_weight_g') if harvest.get('dry_weight_g') is not None else '—'} g ({metrics.get('dry_weight_oz') or '—'} oz)",
                f"- **Trim / Larf:** {harvest.get('trim_weight_g') if harvest.get('trim_weight_g') is not None else '—'} g",
                f"- **Wet → Dry Retention:** {metrics.get('retention_pct') if metrics.get('retention_pct') is not None else '—'}%",
                f"- **Efficiency:** {metrics.get('grams_per_watt') if metrics.get('grams_per_watt') is not None else '—'} g/W",
                f"- **Rating:** {'★' * (harvest.get('rating') or 0) or '—'}{' (Keeper)' if harvest.get('is_keeper') else ''}",
                f"- **Aroma:** {harvest.get('aroma_notes') or '—'}",
                f"- **Effects:** {harvest.get('effect_notes') or '—'}",
                "",
            ]
        )
    if report.get("stage_history"):
        lines.append("## Stage History")
        for st in report["stage_history"]:
            end = st.get("ended_at") or "Current"
            note = f" — {st['notes']}" if st.get("notes") else ""
            lines.append(f"- **{st['stage'].title()}**: {st['started_at']} → {end}{note}")
        lines.append("")
    if report.get("curing_logs"):
        lines.append("## Curing Log")
        for cl in report["curing_logs"]:
            rh = f"{cl['jar_rh_pct']}% RH" if cl.get("jar_rh_pct") is not None else "—"
            burp = "Burped" if cl.get("burped") else "Checked"
            note = f" — {cl['notes']}" if cl.get("notes") else ""
            lines.append(f"- {cl['logged_at']}: {rh} ({burp}){note}")
        lines.append("")
    if report.get("logs"):
        lines.append(f"## Grow Journal ({len(report['logs'])} entries)")
        for lg in report["logs"]:
            title = lg.get("title") or lg.get("log_type", "note").title()
            note = f": {lg['notes']}" if lg.get("notes") else ""
            lines.append(f"- [{lg['logged_at']}] **{title}**{note}")
    return "\n".join(lines) + "\n"


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reports/export",
        vol.Required("plant_id"): str,
    }
)
@websocket_api.async_response
async def ws_export_plant_report(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Export a plant's full grow & harvest report in JSON and Markdown formats."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    report = await coordinator.db.async_get_plant_report_data(msg["plant_id"])
    if report is None:
        connection.send_error(msg["id"], "not_found", "Plant not found")
        return
    safe_slug = "".join(
        c if c.isalnum() or c in ("-", "_") else "_"
        for c in report["plant"]["name"].lower()
    ).strip("_") or "plant"
    connection.send_result(
        msg["id"],
        {
            "filename_base": f"igro_report_{safe_slug}",
            "json_data": report,
            "markdown": _format_plant_report_markdown(report),
        },
    )


# ------------------------------------------------------------------
# Reminders & Schedules WS commands
# ------------------------------------------------------------------
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reminders/list",
        vol.Optional("status"): vol.Any(str, None),
        vol.Optional("plant_id"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_list_reminders(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List reminders."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    reminders = await coordinator.db.async_list_reminders(
        status=msg.get("status"), plant_id=msg.get("plant_id")
    )
    connection.send_result(msg["id"], {"reminders": reminders})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reminders/create",
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_create_reminder(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a reminder."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    created = await coordinator.db.async_create_reminder(msg["data"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"reminder": created})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reminders/update",
        vol.Required("reminder_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_update_reminder(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update a reminder."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    updated = await coordinator.db.async_update_reminder(
        msg["reminder_id"], msg["data"]
    )
    if updated is None:
        connection.send_error(msg["id"], "not_found", "Reminder not found")
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"reminder": updated})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reminders/complete",
        vol.Required("reminder_id"): str,
        vol.Optional("create_log"): vol.Any(bool, None),
    }
)
@websocket_api.async_response
async def ws_complete_reminder(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Complete a reminder (advances recurring due_at & optionally creates log)."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    result = await coordinator.db.async_complete_reminder(
        msg["reminder_id"], create_log=msg.get("create_log")
    )
    if result is None:
        connection.send_error(msg["id"], "not_found", "Reminder not found")
        return
    if result.get("created_log"):
        lg = result["created_log"]
        hass.bus.async_fire(
            EVENT_LOG_CREATED,
            {
                "log_id": lg["id"],
                "plant_id": lg.get("plant_id"),
                "log_type": lg.get("log_type"),
                "status": lg.get("status"),
            },
        )
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reminders/delete",
        vol.Required("reminder_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_reminder(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a reminder."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    deleted = await coordinator.db.async_delete_reminder(msg["reminder_id"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"deleted": deleted})


# ------------------------------------------------------------------
# Breeding Program, Pollen Vault, Seed Minting & Pheno-Hunt WS commands
# ------------------------------------------------------------------
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/pollen/create",
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_create_pollen_batch(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a stored pollen batch."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    created = await coordinator.db.async_create_pollen_batch(msg["data"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"pollen_batch": created})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/pollen/update",
        vol.Required("batch_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_update_pollen_batch(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update a pollen batch."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    updated = await coordinator.db.async_update_pollen_batch(
        msg["batch_id"], msg["data"]
    )
    if updated is None:
        connection.send_error(msg["id"], "not_found", "Pollen batch not found")
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"pollen_batch": updated})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/pollen/delete",
        vol.Required("batch_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_pollen_batch(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a pollen batch."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    deleted = await coordinator.db.async_delete_pollen_batch(msg["batch_id"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"deleted": deleted})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/crosses/create",
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_create_breeding_cross(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a breeding cross / pollination project."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    created = await coordinator.db.async_create_breeding_cross(msg["data"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"cross": created})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/crosses/update",
        vol.Required("cross_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_update_breeding_cross(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update a breeding cross."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    updated = await coordinator.db.async_update_breeding_cross(
        msg["cross_id"], msg["data"]
    )
    if updated is None:
        connection.send_error(msg["id"], "not_found", "Breeding cross not found")
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"cross": updated})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/crosses/harvest_seeds",
        vol.Required("cross_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_harvest_cross_seeds(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Harvest seeds from a cross and auto-mint a Seedbank batch."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    result = await coordinator.db.async_harvest_cross_seeds(
        msg["cross_id"], msg["data"]
    )
    if result is None:
        connection.send_error(msg["id"], "not_found", "Breeding cross not found")
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/crosses/delete",
        vol.Required("cross_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_breeding_cross(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a breeding cross."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    deleted = await coordinator.db.async_delete_breeding_cross(msg["cross_id"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"deleted": deleted})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/seed_batches/delete",
        vol.Required("batch_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_seed_batch(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a minted seed batch."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    deleted = await coordinator.db.async_delete_seed_batch(msg["batch_id"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"deleted": deleted})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/pheno_hunts/create",
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_create_pheno_hunt(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a pheno-hunt session."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    created = await coordinator.db.async_create_pheno_hunt(msg["data"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"pheno_hunt": created})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/pheno_hunts/update",
        vol.Required("hunt_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_update_pheno_hunt(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update a pheno-hunt session."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    updated = await coordinator.db.async_update_pheno_hunt(
        msg["hunt_id"], msg["data"]
    )
    if updated is None:
        connection.send_error(msg["id"], "not_found", "Pheno hunt not found")
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"pheno_hunt": updated})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/pheno_hunts/delete",
        vol.Required("hunt_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_pheno_hunt(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a pheno-hunt session."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    deleted = await coordinator.db.async_delete_pheno_hunt(msg["hunt_id"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"deleted": deleted})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/pheno_scores/upsert",
        vol.Required("pheno_hunt_id"): str,
        vol.Required("plant_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_upsert_pheno_score(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create or update a sibling phenotype trait scorecard."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    score = await coordinator.db.async_upsert_pheno_score(
        msg["pheno_hunt_id"], msg["plant_id"], msg["data"]
    )
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"score": score})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/pheno_scores/delete",
        vol.Required("score_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_pheno_score(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a phenotype scorecard."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    deleted = await coordinator.db.async_delete_pheno_score(msg["score_id"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"deleted": deleted})


# ------------------------------------------------------------------
# Reservoirs, Dosing Pumps & High-Frequency Fertigation WS commands
# ------------------------------------------------------------------
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reservoirs/create",
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_create_reservoir(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a nutrient reservoir."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    created = await coordinator.db.async_create_reservoir(msg["data"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"reservoir": created})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reservoirs/update",
        vol.Required("reservoir_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_update_reservoir(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update a nutrient reservoir."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    updated = await coordinator.db.async_update_reservoir(
        msg["reservoir_id"], msg["data"]
    )
    if updated is None:
        connection.send_error(msg["id"], "not_found", "Reservoir not found")
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"reservoir": updated})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reservoirs/delete",
        vol.Required("reservoir_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_reservoir(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a nutrient reservoir."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    deleted = await coordinator.db.async_delete_reservoir(msg["reservoir_id"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"deleted": deleted})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reservoirs/mix_batch",
        vol.Required("reservoir_id"): str,
        vol.Required("preset_id"): str,
        vol.Required("target_volume_l"): vol.Coerce(float),
    }
)
@websocket_api.async_response
async def ws_mix_reservoir_batch(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Run an ordered batch mix from a Nutrient Preset into a reservoir."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    try:
        result = await coordinator.fertigation.async_run_batch_mix(
            msg["reservoir_id"], msg["preset_id"], float(msg["target_volume_l"])
        )
    except Exception as err:
        connection.send_error(msg["id"], "mix_failed", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reservoirs/auto_trim",
        vol.Required("reservoir_id"): str,
    }
)
@websocket_api.async_response
async def ws_auto_trim_reservoir(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Trigger one closed-loop pH/EC trim cycle on a reservoir."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    try:
        result = await coordinator.fertigation.async_run_auto_trim(msg["reservoir_id"])
    except Exception as err:
        connection.send_error(msg["id"], "trim_failed", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reservoirs/emergency_stop",
        vol.Optional("reason"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_emergency_stop(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Trigger emergency stop across all pumps, valves, and dosing channels."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    result = await coordinator.fertigation.async_emergency_stop(
        msg.get("reason") or "Manual emergency stop from iGro panel"
    )
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reservoirs/clear_lockout",
        vol.Required("reservoir_id"): str,
    }
)
@websocket_api.async_response
async def ws_clear_reservoir_lockout(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Reset a reservoir from locked_out/emergency_stop back to idle."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    updated = await coordinator.db.async_update_reservoir(
        msg["reservoir_id"], {"status": "idle", "last_error": None}
    )
    if updated is None:
        connection.send_error(msg["id"], "not_found", "Reservoir not found")
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"reservoir": updated})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/dosing_channels/create",
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_create_dosing_channel(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a peristaltic dosing channel."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    created = await coordinator.db.async_create_dosing_channel(msg["data"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"channel": created})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/dosing_channels/update",
        vol.Required("channel_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_update_dosing_channel(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update a peristaltic dosing channel (including calibration mL/s)."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    updated = await coordinator.db.async_update_dosing_channel(
        msg["channel_id"], msg["data"]
    )
    if updated is None:
        connection.send_error(msg["id"], "not_found", "Dosing channel not found")
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"channel": updated})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/dosing_channels/delete",
        vol.Required("channel_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_dosing_channel(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a dosing channel."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    deleted = await coordinator.db.async_delete_dosing_channel(msg["channel_id"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"deleted": deleted})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/dosing_channels/dose",
        vol.Required("channel_id"): str,
        vol.Required("dose_ml"): vol.Coerce(float),
        vol.Optional("run_type", default="manual_dose"): str,
    }
)
@websocket_api.async_response
async def ws_dose_channel(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Dose or prime a single peristaltic channel."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    try:
        result = await coordinator.fertigation.async_dose_channel(
            msg["channel_id"],
            float(msg["dose_ml"]),
            run_type=msg.get("run_type", "manual_dose"),
            check_caps=msg.get("run_type") != "prime",
        )
    except Exception as err:
        connection.send_error(msg["id"], "dose_failed", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/dosing_channels/refill",
        vol.Required("channel_id"): str,
        vol.Optional("remaining_ml"): vol.Any(vol.Coerce(float), None),
    }
)
@websocket_api.async_response
async def ws_refill_channel(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Refill a dosing channel's bottle back to full (or specified mL)."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    ch = next(
        (
            c
            for c in (coordinator.data or {}).get("dosing_channels", [])
            if c["id"] == msg["channel_id"]
        ),
        None,
    )
    if ch is None:
        connection.send_error(msg["id"], "not_found", "Dosing channel not found")
        return
    target = (
        float(msg["remaining_ml"])
        if msg.get("remaining_ml") is not None
        else float(ch.get("bottle_capacity_ml") or 1000.0)
    )
    updated = await coordinator.db.async_update_dosing_channel(
        msg["channel_id"], {"bottle_remaining_ml": target}
    )
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"channel": updated})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/fertigation/upsert",
        vol.Required("plant_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_upsert_fertigation_schedule(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create or update a plant's fertigation schedule."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    sched = await coordinator.db.async_upsert_fertigation_schedule(
        msg["plant_id"], msg["data"]
    )
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"schedule": sched})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/fertigation/delete",
        vol.Required("plant_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_fertigation_schedule(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a plant's fertigation schedule."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    deleted = await coordinator.db.async_delete_fertigation_schedule(msg["plant_id"])
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"deleted": deleted})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/fertigation/run_shot",
        vol.Required("plant_id"): str,
        vol.Optional("duration_s"): vol.Any(vol.Coerce(float), None),
    }
)
@websocket_api.async_response
async def ws_run_fertigation_shot(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Execute an immediate manual fertigation shot for a plant."""
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_ready", "iGro not initialized")
        return
    try:
        result = await coordinator.fertigation.async_run_fertigation_shot(
            msg["plant_id"],
            trigger_type="manual",
            duration_s=msg.get("duration_s"),
        )
    except Exception as err:
        connection.send_error(msg["id"], "fertigation_failed", str(err))
        return
    connection.send_result(msg["id"], result)
