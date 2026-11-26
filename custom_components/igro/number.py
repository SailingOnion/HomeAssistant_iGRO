"""Number platform for per-plant fertigation feeds/day and shot duration."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_ENTITIES_CHANGED
from .coordinator import IGroCoordinator
from .entity import IGroPlantEntity


class IGroPlantFeedsPerDayNumber(IGroPlantEntity, NumberEntity):
    """Number entity controlling automated fertigation feeds per day."""

    _attr_name = "Feeds Per Day"
    _attr_icon = "mdi:counter"
    _attr_native_min_value = 1
    _attr_native_max_value = 24
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: IGroCoordinator, plant_id: str) -> None:
        super().__init__(coordinator, plant_id)
        self._attr_unique_id = f"{DOMAIN}_plant_{plant_id}_feeds_per_day"

    @property
    def native_value(self) -> float | None:
        plant = self._plant
        if plant is None:
            return None
        sched = plant.get("fertigation") or {}
        return float(sched.get("feeds_per_day") or 4)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.db.async_upsert_fertigation_schedule(
            self._plant_id, {"feeds_per_day": int(round(value))}
        )
        await self.coordinator.async_request_refresh()


class IGroPlantShotDurationNumber(IGroPlantEntity, NumberEntity):
    """Number entity controlling automated fertigation shot duration in seconds."""

    _attr_name = "Feed Shot Duration"
    _attr_icon = "mdi:timer-outline"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_native_min_value = 1
    _attr_native_max_value = 300
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: IGroCoordinator, plant_id: str) -> None:
        super().__init__(coordinator, plant_id)
        self._attr_unique_id = f"{DOMAIN}_plant_{plant_id}_shot_duration_s"

    @property
    def native_value(self) -> float | None:
        plant = self._plant
        if plant is None:
            return None
        sched = plant.get("fertigation") or {}
        return float(sched.get("shot_duration_s") or 15.0)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.db.async_upsert_fertigation_schedule(
            self._plant_id, {"shot_duration_s": float(value)}
        )
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iGro number entities dynamically."""
    coordinator: IGroCoordinator = hass.data[DOMAIN]["coordinator"]
    tracked_plants: set[str] = set()

    @callback
    def _sync_entities() -> None:
        data = coordinator.data or {}
        current_plants = set(data.get("plants", {}).keys())

        new_entities: list[NumberEntity] = []
        for pid in current_plants - tracked_plants:
            new_entities.append(IGroPlantFeedsPerDayNumber(coordinator, pid))
            new_entities.append(IGroPlantShotDurationNumber(coordinator, pid))
            tracked_plants.add(pid)

        if new_entities:
            async_add_entities(new_entities)

        removed = tracked_plants - current_plants
        if removed:
            ent_reg = er.async_get(hass)
            for pid in removed:
                tracked_plants.discard(pid)
                for suffix in ("feeds_per_day", "shot_duration_s"):
                    uid = f"{DOMAIN}_plant_{pid}_{suffix}"
                    if ent_id := ent_reg.async_get_entity_id("number", DOMAIN, uid):
                        ent_reg.async_remove(ent_id)

    _sync_entities()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_ENTITIES_CHANGED, _sync_entities)
    )
