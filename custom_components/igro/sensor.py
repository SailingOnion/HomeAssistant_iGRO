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
from homeassistant.const import (
    PERCENTAGE,
    UnitOfLength,
    UnitOfMass,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_ENTITIES_CHANGED
from .coordinator import IGroCoordinator
from .entity import (
    IGroEnvironmentEntity,
    IGroPlantEntity,
    IGroReservoirEntity,
    IGroSummaryEntity,
)


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
            "total_harvests": d.get("summary", {}).get("total_harvests", 0),
            "total_dry_yield_g": d.get("summary", {}).get("total_dry_yield_g", 0),
            "avg_dry_yield_g": d.get("summary", {}).get("avg_dry_yield_g"),
            "keeper_count": d.get("summary", {}).get("keeper_count", 0),
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
    IGroSensorDesc(
        key="total_dry_yield",
        name="Total Dry Yield",
        icon="mdi:scale",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfMass.GRAMS,
        value_fn=lambda d: d.get("summary", {}).get("total_dry_yield_g", 0),
        attrs_fn=lambda d: {
            "total_harvests": d.get("summary", {}).get("total_harvests", 0),
            "avg_dry_yield_g": d.get("summary", {}).get("avg_dry_yield_g"),
            "keeper_count": d.get("summary", {}).get("keeper_count", 0),
        },
    ),
    IGroSensorDesc(
        key="due_reminders",
        name="Due Reminders",
        icon="mdi:bell-ring-outline",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("summary", {}).get("due_reminders", 0),
        attrs_fn=lambda d: {
            "active_reminders": d.get("summary", {}).get("active_reminders", 0),
        },
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
    IGroSensorDesc(
        key="dry_yield",
        name="Dry Yield",
        icon="mdi:scale",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfMass.GRAMS,
        value_fn=lambda p: (p.get("harvest") or {}).get("dry_weight_g"),
        attrs_fn=lambda p: {
            "wet_weight_g": (p.get("harvest") or {}).get("wet_weight_g"),
            "trim_weight_g": (p.get("harvest") or {}).get("trim_weight_g"),
            "retention_pct": (p.get("harvest") or {}).get("retention_pct"),
            "grams_per_watt": (p.get("harvest") or {}).get("grams_per_watt"),
            "cure_rh_pct": (p.get("harvest") or {}).get("cure_rh_pct"),
            "rating": (p.get("harvest") or {}).get("rating"),
            "is_keeper": (p.get("harvest") or {}).get("is_keeper"),
        },
    ),
    IGroSensorDesc(
        key="next_fertigation",
        name="Next Feed",
        icon="mdi:clock-outline",
        value_fn=lambda p: (p.get("fertigation") or {}).get("next_fertigation_at"),
        attrs_fn=lambda p: {
            "mode": (p.get("fertigation") or {}).get("mode"),
            "feeds_per_day": (p.get("fertigation") or {}).get("feeds_per_day"),
            "shot_times": (p.get("fertigation") or {}).get("shot_times"),
        },
    ),
    IGroSensorDesc(
        key="daily_fertigation_ml",
        name="Daily Fertigation Volume",
        icon="mdi:water-pump",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
        value_fn=lambda p: (p.get("fertigation") or {}).get("daily_volume_ml", 0.0),
        attrs_fn=lambda p: {
            "max_daily_volume_ml": (p.get("fertigation") or {}).get(
                "max_daily_volume_ml"
            ),
            "last_fed_at": (p.get("fertigation") or {}).get("last_fed_at"),
        },
    ),
)

RESERVOIR_SENSORS: tuple[IGroSensorDesc, ...] = (
    IGroSensorDesc(
        key="ph",
        name="pH",
        icon="mdi:ph",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda r: r.get("ph"),
        attrs_fn=lambda r: {"target_ph": r.get("target_ph")},
    ),
    IGroSensorDesc(
        key="ec",
        name="EC",
        icon="mdi:flash-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="mS/cm",
        value_fn=lambda r: r.get("ec"),
        attrs_fn=lambda r: {"target_ec": r.get("target_ec")},
    ),
    IGroSensorDesc(
        key="water_temp",
        name="Water Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda r: r.get("water_temp_c"),
    ),
    IGroSensorDesc(
        key="level",
        name="Water Level",
        icon="mdi:cup-water",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda r: r.get("level_pct"),
        attrs_fn=lambda r: {
            "capacity_l": r.get("capacity_l"),
            "current_volume_l": r.get("current_volume_l"),
            "low_level": r.get("low_level"),
        },
    ),
    IGroSensorDesc(
        key="status",
        name="Status",
        icon="mdi:flask-round-bottom",
        value_fn=lambda r: r.get("status") or "idle",
        attrs_fn=lambda r: {
            "auto_trim_enabled": r.get("auto_trim_enabled"),
            "last_mixed_at": r.get("last_mixed_at"),
            "last_error": r.get("last_error"),
            "low_bottle_channels": r.get("low_bottle_count", 0),
        },
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


class IGroReservoirSensor(IGroReservoirEntity, SensorEntity):
    """Reservoir-scoped sensor (pH, EC, Water Temp, Level, Status)."""

    entity_description: IGroSensorDesc

    def __init__(
        self, coordinator: IGroCoordinator, reservoir_id: str, desc: IGroSensorDesc
    ) -> None:
        super().__init__(coordinator, reservoir_id)
        self.entity_description = desc
        self._attr_unique_id = f"{DOMAIN}_res_{reservoir_id}_{desc.key}"

    @property
    def native_value(self) -> Any:
        res = self._reservoir
        if res is None:
            return None
        return self.entity_description.value_fn(res)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        res = self._reservoir
        if res is None or not self.entity_description.attrs_fn:
            return None
        return self.entity_description.attrs_fn(res)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iGro sensor entities dynamically."""
    coordinator: IGroCoordinator = hass.data[DOMAIN]["coordinator"]

    tracked_envs: set[str] = set()
    tracked_plants: set[str] = set()
    tracked_reservoirs: set[str] = set()

    # Add global summary sensors once
    async_add_entities(
        [IGroSummarySensor(coordinator, desc) for desc in SUMMARY_SENSORS]
    )

    @callback
    def _sync_entities() -> None:
        data = coordinator.data or {}
        current_envs = set(data.get("environments", {}).keys())
        current_plants = set(data.get("plants", {}).keys())
        current_reservoirs = set(data.get("reservoirs", {}).keys())

        new_entities: list[SensorEntity] = []
        for eid in current_envs - tracked_envs:
            for desc in ENVIRONMENT_SENSORS:
                new_entities.append(IGroEnvironmentSensor(coordinator, eid, desc))
            tracked_envs.add(eid)

        for pid in current_plants - tracked_plants:
            for desc in PLANT_SENSORS:
                new_entities.append(IGroPlantSensor(coordinator, pid, desc))
            tracked_plants.add(pid)

        for rid in current_reservoirs - tracked_reservoirs:
            for desc in RESERVOIR_SENSORS:
                new_entities.append(IGroReservoirSensor(coordinator, rid, desc))
            tracked_reservoirs.add(rid)

        if new_entities:
            async_add_entities(new_entities)

        # Clean up deleted environments / plants / reservoirs from registries
        removed_envs = tracked_envs - current_envs
        removed_plants = tracked_plants - current_plants
        removed_res = tracked_reservoirs - current_reservoirs
        if removed_envs or removed_plants or removed_res:
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
            for rid in removed_res:
                tracked_reservoirs.discard(rid)
                for desc in RESERVOIR_SENSORS:
                    uid = f"{DOMAIN}_res_{rid}_{desc.key}"
                    if ent_id := ent_reg.async_get_entity_id("sensor", DOMAIN, uid):
                        ent_reg.async_remove(ent_id)
                if dev := dev_reg.async_get_device(identifiers={(DOMAIN, f"res_{rid}")}):
                    dev_reg.async_remove_device(dev.id)

    _sync_entities()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_ENTITIES_CHANGED, _sync_entities)
    )
