"""Select platform for changing plant grow stages directly in Home Assistant."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, EVENT_STAGE_CHANGED, GROW_STAGES, SIGNAL_ENTITIES_CHANGED
from .coordinator import IGroCoordinator
from .entity import IGroPlantEntity


class IGroPlantStageSelect(IGroPlantEntity, SelectEntity):
    """Select entity to view and change a plant's grow stage."""

    _attr_name = "Stage"
    _attr_icon = "mdi:sprout"
    _attr_options = list(GROW_STAGES)

    def __init__(self, coordinator: IGroCoordinator, plant_id: str) -> None:
        super().__init__(coordinator, plant_id)
        self._attr_unique_id = f"{DOMAIN}_plant_{plant_id}_stage_select"

    @property
    def current_option(self) -> str | None:
        plant = self._plant
        if plant is None:
            return None
        return plant.get("stage")

    async def async_select_option(self, option: str) -> None:
        """Change the plant's grow stage."""
        await self.coordinator.db.async_set_plant_stage(self._plant_id, option)
        self.hass.bus.async_fire(
            EVENT_STAGE_CHANGED,
            {"plant_id": self._plant_id, "stage": option},
        )
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iGro stage select entities dynamically."""
    coordinator: IGroCoordinator = hass.data[DOMAIN]["coordinator"]
    tracked_plants: set[str] = set()

    @callback
    def _sync_entities() -> None:
        data = coordinator.data or {}
        current_plants = set(data.get("plants", {}).keys())

        new_entities = [
            IGroPlantStageSelect(coordinator, pid)
            for pid in current_plants - tracked_plants
        ]
        tracked_plants.update(current_plants - tracked_plants)
        if new_entities:
            async_add_entities(new_entities)

        removed = tracked_plants - current_plants
        if removed:
            ent_reg = er.async_get(hass)
            for pid in removed:
                tracked_plants.discard(pid)
                uid = f"{DOMAIN}_plant_{pid}_stage_select"
                if ent_id := ent_reg.async_get_entity_id("select", DOMAIN, uid):
                    ent_reg.async_remove(ent_id)

    _sync_entities()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_ENTITIES_CHANGED, _sync_entities)
    )
