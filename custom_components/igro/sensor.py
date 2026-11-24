"""Sensor platform for iGro environments, plants, and summary KPIs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfLength, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_ENTITIES_CHANGED
from .coordinator import IGroCoordinator
from .entity import IGroEnvironmentEntity, IGroPlantEntity, IGroSummaryEntity


@dataclass(frozen=True, kw_only=True)
class IGroSensorDesc(SensorEntityDescription):
    """Describes an iGro sensor with value and attribute extractors."""

    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


SUMMARY_SENSORS: tuple[IGroSensorDesc, ...] = (
    IGroSensorDesc(
        key="active_plants",
        name="Active Plants",
        icon="mdi:sprout",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("summary", {}).get("active_plants", 0),
        attrs_fn=lambda d: {
            "total_plants": d.get("summary", {}).get("total_plants", 0),
            "total_logs": d.get("summary", {}).get("total_logs", 0),
            "total_photos": d.get("summary", {}).get("total_photos", 0),
        },
    ),
    IGroSensorDesc(
        key="total_environments",
        name="Environments",
        icon="mdi:tent",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("summary", {}).get("total_environments", 0),
    ),
    IGroSensorDesc(
        key="active_alerts",
        name="Active Alerts",
        icon="mdi:alert-circle-outline",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("summary", {}).get("alerts_count", 0),
    ),
)

ENVIRONMENT_SENSORS: tuple[IGroSensorDesc, ...] = (
    IGroSensorDesc(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda e: e.get("temperature_c"),
        attrs_fn=lambda e: {
            "source_entity": e.get("temp_entity_id"),
            "target_min_c": e.get("target_temp_min_c"),
            "target_max_c": e.get("target_temp_max_c"),
            "status": e.get("temp_status"),
        },
    ),
    IGroSensorDesc(
        key="humidity",
        name="Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda e: e.get("humidity"),
        attrs_fn=lambda e: {
            "source_entity": e.get("humidity_entity_id"),
            "target_min": e.get("target_humidity_min"),
            "target_max": e.get("target_humidity_max"),
            "dew_point_c": e.get("dew_point_c"),
            "status": e.get("humidity_status"),
        },
    ),
    IGroSensorDesc(
        key="vpd",
        name="VPD",
        icon="mdi:water-thermometer",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="kPa",
        value_fn=lambda e: e.get("vpd_kpa"),
        attrs_fn=lambda e: {
            "status": e.get("vpd_status"),
            "target_min_kpa": e.get("effective_vpd_min"),
            "target_max_kpa": e.get("effective_vpd_max"),
            "leaf_temp_offset_c": e.get("leaf_temp_offset_c"),
            "dew_point_c": e.get("dew_point_c"),
        },
    ),
    IGroSensorDesc(
        key="vpd_status",
        name="VPD Status",
        icon="mdi:gauge",
        value_fn=lambda e: e.get("vpd_status"),
    ),
    IGroSensorDesc(
        key="plant_count",
        name="Active Plants",
        icon="mdi:sprout",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda e: e.get("plant_count", 0),
        attrs_fn=lambda e: {"light_schedule": e.get("light_schedule")},
    ),
)

PLANT_SENSORS: tuple[IGroSensorDesc, ...] = (
    IGroSensorDesc(
        key="stage",
        name="Grow Stage",
        icon="mdi:sprout",
        value_fn=lambda p: p.get("stage"),
        attrs_fn=lambda p: {
            "strain": p.get("strain"),
            "breeder": p.get("breeder"),
            "plant_type": p.get("plant_type"),
            "medium": p.get("medium"),
            "pot_size": p.get("pot_size"),
            "environment": p.get("environment_name"),
            "started_at": p.get("started_at"),
            "stage_started_at": p.get("stage_started_at"),
            "stage_week": p.get("stage_week"),
        },
    ),
    IGroSensorDesc(
        key="total_days",
        name="Total Grow Days",
        icon="mdi:calendar-clock",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.DAYS,
        value_fn=lambda p: p.get("total_days"),
        attrs_fn=lambda p: {"total_week": p.get("total_week")},
    ),
    IGroSensorDesc(
        key="stage_days",
        name="Stage Days",
        icon="mdi:calendar-today",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.DAYS,
        value_fn=lambda p: p.get("stage_days"),
        attrs_fn=lambda p: {
            "stage": p.get("stage"),
            "stage_week": p.get("stage_week"),
        },
    ),
    IGroSensorDesc(
        key="days_since_watered",
        name="Days Since Watered",
        icon="mdi:watering-can-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.DAYS,
        value_fn=lambda p: p.get("days_since_watered"),
        attrs_fn=lambda p: {
            "last_watered_at": p.get("last_watered_at"),
            "last_water_volume_ml": p.get("last_water_volume_ml"),
            "last_fed_at": p.get("last_fed_at"),
        },
    ),
    IGroSensorDesc(
        key="last_ph",
        name="Last pH",
        icon="mdi:ph",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda p: p.get("last_ph"),
    ),
    IGroSensorDesc(
        key="last_ec",
        name="Last EC",
        icon="mdi:flash-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="mS/cm",
        value_fn=lambda p: p.get("last_ec"),
        attrs_fn=lambda p: {"last_ppm": p.get("last_ppm")},
    ),
    IGroSensorDesc(
        key="soil_moisture",
        name="Soil Moisture",
        device_class=SensorDeviceClass.MOISTURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda p: p.get("soil_moisture"),
        attrs_fn=lambda p: {"source_entity": p.get("soil_moisture_entity_id")},
    ),
    IGroSensorDesc(
        key="height",
        name="Height",
        icon="mdi:ruler",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.CENTIMETERS,
        value_fn=lambda p: p.get("latest_height_cm"),
    ),
)


class IGroSummarySensor(IGroSummaryEntity, SensorEntity):
    """Global iGro KPI sensor."""

    entity_description: IGroSensorDesc

    def __init__(self, coordinator: IGroCoordinator, desc: IGroSensorDesc) -> None:
        super().__init__(coordinator)
        self.entity_description = desc
        self._attr_unique_id = f"{DOMAIN}_summary_{desc.key}"

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn:
            return self.entity_description.attrs_fn(self.coordinator.data or {})
        return None


class IGroEnvironmentSensor(IGroEnvironmentEntity, SensorEntity):
    """Environment-scoped sensor (Temp, Humidity, VPD, etc.)."""

    entity_description: IGroSensorDesc

    def __init__(
        self, coordinator: IGroCoordinator, env_id: str, desc: IGroSensorDesc
    ) -> None:
        super().__init__(coordinator, env_id)
        self.entity_description = desc
        self._attr_unique_id = f"{DOMAIN}_env_{env_id}_{desc.key}"

    @property
    def native_value(self) -> Any:
        env = self._env
        if env is None:
            return None
        return self.entity_description.value_fn(env)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        env = self._env
        if env is None or not self.entity_description.attrs_fn:
            return None
        return self.entity_description.attrs_fn(env)


class IGroPlantSensor(IGroPlantEntity, SensorEntity):
    """Plant-scoped sensor (Stage, Days, pH, EC, Moisture, Height)."""

    entity_description: IGroSensorDesc

    def __init__(
        self, coordinator: IGroCoordinator, plant_id: str, desc: IGroSensorDesc
    ) -> None:
        super().__init__(coordinator, plant_id)
        self.entity_description = desc
        self._attr_unique_id = f"{DOMAIN}_plant_{plant_id}_{desc.key}"

    @property
    def native_value(self) -> Any:
        plant = self._plant
        if plant is None:
            return None
        return self.entity_description.value_fn(plant)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        plant = self._plant
        if plant is None or not self.entity_description.attrs_fn:
            return None
        return self.entity_description.attrs_fn(plant)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iGro sensor entities dynamically."""
    coordinator: IGroCoordinator = hass.data[DOMAIN]["coordinator"]

    tracked_envs: set[str] = set()
    tracked_plants: set[str] = set()

    # Add global summary sensors once
    async_add_entities(
        [IGroSummarySensor(coordinator, desc) for desc in SUMMARY_SENSORS]
    )

    @callback
    def _sync_entities() -> None:
        data = coordinator.data or {}
        current_envs = set(data.get("environments", {}).keys())
        current_plants = set(data.get("plants", {}).keys())

        new_entities: list[SensorEntity] = []
        for eid in current_envs - tracked_envs:
            for desc in ENVIRONMENT_SENSORS:
                new_entities.append(IGroEnvironmentSensor(coordinator, eid, desc))
            tracked_envs.add(eid)

        for pid in current_plants - tracked_plants:
            for desc in PLANT_SENSORS:
                new_entities.append(IGroPlantSensor(coordinator, pid, desc))
            tracked_plants.add(pid)

        if new_entities:
            async_add_entities(new_entities)

        # Clean up deleted environments / plants from registries
        removed_envs = tracked_envs - current_envs
        removed_plants = tracked_plants - current_plants
        if removed_envs or removed_plants:
            ent_reg = er.async_get(hass)
            dev_reg = dr.async_get(hass)
            for eid in removed_envs:
                tracked_envs.discard(eid)
                for desc in ENVIRONMENT_SENSORS:
                    uid = f"{DOMAIN}_env_{eid}_{desc.key}"
                    if ent_id := ent_reg.async_get_entity_id("sensor", DOMAIN, uid):
                        ent_reg.async_remove(ent_id)
                if dev := dev_reg.async_get_device(identifiers={(DOMAIN, f"env_{eid}")}):
                    dev_reg.async_remove_device(dev.id)
            for pid in removed_plants:
                tracked_plants.discard(pid)
                for desc in PLANT_SENSORS:
                    uid = f"{DOMAIN}_plant_{pid}_{desc.key}"
                    if ent_id := ent_reg.async_get_entity_id("sensor", DOMAIN, uid):
                        ent_reg.async_remove(ent_id)
                if dev := dev_reg.async_get_device(identifiers={(DOMAIN, f"plant_{pid}")}):
                    dev_reg.async_remove_device(dev.id)

    _sync_entities()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_ENTITIES_CHANGED, _sync_entities)
    )
