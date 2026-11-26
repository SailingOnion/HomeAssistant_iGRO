"""Button platform for one-tap plant actions (quick water & camera photo)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    EVENT_LOG_CREATED,
    LOG_TYPE_WATER,
    SIGNAL_ENTITIES_CHANGED,
)
from .coordinator import IGroCoordinator
from .entity import IGroPlantEntity, IGroReservoirEntity
from .http_api import async_capture_camera_photo


class IGroQuickWaterButton(IGroPlantEntity, ButtonEntity):
    """Button that logs a quick watering action for a plant."""

    _attr_name = "Log Watering"
    _attr_icon = "mdi:watering-can"

    def __init__(self, coordinator: IGroCoordinator, plant_id: str) -> None:
        super().__init__(coordinator, plant_id)
        self._attr_unique_id = f"{DOMAIN}_plant_{plant_id}_quick_water"

    async def async_press(self) -> None:
        env_readings = self.coordinator.get_environment_readings_for_plant(
            self._plant_id
        )
        created = await self.coordinator.db.async_create_log(
            {
                "plant_id": self._plant_id,
                "log_type": LOG_TYPE_WATER,
                "title": "Quick watering",
                **env_readings,
            }
        )
        self.hass.bus.async_fire(
            EVENT_LOG_CREATED,
            {
                "log_id": created["id"],
                "plant_id": self._plant_id,
                "log_type": LOG_TYPE_WATER,
            },
        )
        await self.coordinator.async_request_refresh()


class IGroCapturePhotoButton(IGroPlantEntity, ButtonEntity):
    """Button that captures a photo from the plant's or environment's linked camera."""

    _attr_name = "Capture Photo"
    _attr_icon = "mdi:camera"

    def __init__(self, coordinator: IGroCoordinator, plant_id: str) -> None:
        super().__init__(coordinator, plant_id)
        self._attr_unique_id = f"{DOMAIN}_plant_{plant_id}_capture_photo"

    async def async_press(self) -> None:
        plant = self._plant
        camera_entity_id = (plant or {}).get("effective_camera_entity_id")
        if not camera_entity_id:
            raise HomeAssistantError(
                "No camera entity is linked to this plant or its environment"
            )
        await async_capture_camera_photo(
            self.hass,
            self.coordinator,
            camera_entity_id,
            plant_id=self._plant_id,
            caption="Quick camera snapshot",
        )


class IGroManualPulseFeedButton(IGroPlantEntity, ButtonEntity):
    """Button that fires a single manual fertigation shot for a plant."""

    _attr_name = "Manual Pulse Feed"
    _attr_icon = "mdi:water-pump"

    def __init__(self, coordinator: IGroCoordinator, plant_id: str) -> None:
        super().__init__(coordinator, plant_id)
        self._attr_unique_id = f"{DOMAIN}_plant_{plant_id}_manual_feed_shot"

    async def async_press(self) -> None:
        try:
            await self.coordinator.fertigation.async_run_fertigation_shot(
                self._plant_id, trigger_type="manual"
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err


class IGroReservoirEmergencyStopButton(IGroReservoirEntity, ButtonEntity):
    """Emergency kill-switch button halting all pumps, valves & dosers."""

    _attr_name = "Emergency Stop"
    _attr_icon = "mdi:octagon-outline"

    def __init__(self, coordinator: IGroCoordinator, reservoir_id: str) -> None:
        super().__init__(coordinator, reservoir_id)
        self._attr_unique_id = f"{DOMAIN}_res_{reservoir_id}_emergency_stop"

    async def async_press(self) -> None:
        res = self._reservoir
        name = res["name"] if res else self._reservoir_id
        await self.coordinator.fertigation.async_emergency_stop(
            f"Emergency stop button pressed on {name}"
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iGro button entities dynamically."""
    coordinator: IGroCoordinator = hass.data[DOMAIN]["coordinator"]
    tracked_plants: set[str] = set()
    tracked_reservoirs: set[str] = set()

    @callback
    def _sync_entities() -> None:
        data = coordinator.data or {}
        current_plants = set(data.get("plants", {}).keys())
        current_reservoirs = set(data.get("reservoirs", {}).keys())

        new_entities: list[ButtonEntity] = []
        for pid in current_plants - tracked_plants:
            new_entities.append(IGroQuickWaterButton(coordinator, pid))
            new_entities.append(IGroCapturePhotoButton(coordinator, pid))
            new_entities.append(IGroManualPulseFeedButton(coordinator, pid))
            tracked_plants.add(pid)

        for rid in current_reservoirs - tracked_reservoirs:
            new_entities.append(IGroReservoirEmergencyStopButton(coordinator, rid))
            tracked_reservoirs.add(rid)

        if new_entities:
            async_add_entities(new_entities)

        removed_plants = tracked_plants - current_plants
        removed_res = tracked_reservoirs - current_reservoirs
        if removed_plants or removed_res:
            ent_reg = er.async_get(hass)
            for pid in removed_plants:
                tracked_plants.discard(pid)
                for suffix in ("quick_water", "capture_photo", "manual_feed_shot"):
                    uid = f"{DOMAIN}_plant_{pid}_{suffix}"
                    if ent_id := ent_reg.async_get_entity_id("button", DOMAIN, uid):
                        ent_reg.async_remove(ent_id)
            for rid in removed_res:
                tracked_reservoirs.discard(rid)
                uid = f"{DOMAIN}_res_{rid}_emergency_stop"
                if ent_id := ent_reg.async_get_entity_id("button", DOMAIN, uid):
                    ent_reg.async_remove(ent_id)

    _sync_entities()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_ENTITIES_CHANGED, _sync_entities)
    )
