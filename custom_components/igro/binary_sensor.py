"""Binary sensor platform for iGro environment target alerts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_ENTITIES_CHANGED
from .coordinator import IGroCoordinator
from .entity import IGroEnvironmentEntity, IGroReservoirEntity


@dataclass(frozen=True, kw_only=True)
class IGroAlertDesc(BinarySensorEntityDescription):
    """Describes an environment alert binary sensor."""

    flag_key: str
    status_key: str


ALERT_SENSORS: tuple[IGroAlertDesc, ...] = (
    IGroAlertDesc(
        key="vpd_alert",
        name="VPD Alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:water-alert",
        flag_key="vpd_alert",
        status_key="vpd_status",
    ),
    IGroAlertDesc(
        key="temp_alert",
        name="Temperature Alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:thermometer-alert",
        flag_key="temp_alert",
        status_key="temp_status",
    ),
    IGroAlertDesc(
        key="humidity_alert",
        name="Humidity Alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:water-percent-alert",
        flag_key="humidity_alert",
        status_key="humidity_status",
    ),
)


class IGroEnvironmentAlertBinarySensor(IGroEnvironmentEntity, BinarySensorEntity):
    """Binary sensor indicating an environment metric is outside target range."""

    entity_description: IGroAlertDesc

    def __init__(
        self, coordinator: IGroCoordinator, env_id: str, desc: IGroAlertDesc
    ) -> None:
        super().__init__(coordinator, env_id)
        self.entity_description = desc
        self._attr_unique_id = f"{DOMAIN}_env_{env_id}_{desc.key}"

    @property
    def is_on(self) -> bool | None:
        env = self._env
        if env is None:
            return None
        return bool(env.get(self.entity_description.flag_key))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        env = self._env
        if env is None:
            return None
        return {
            "status": env.get(self.entity_description.status_key),
            "vpd_kpa": env.get("vpd_kpa"),
            "temperature_c": env.get("temperature_c"),
            "humidity": env.get("humidity"),
        }


class IGroReservoirSafetyBinarySensor(IGroReservoirEntity, BinarySensorEntity):
    """Binary sensor indicating a reservoir safety interlock or lockout is active."""

    _attr_name = "Safety Interlock"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:shield-alert"

    def __init__(self, coordinator: IGroCoordinator, reservoir_id: str) -> None:
        super().__init__(coordinator, reservoir_id)
        self._attr_unique_id = f"{DOMAIN}_res_{reservoir_id}_safety_alert"

    @property
    def is_on(self) -> bool | None:
        res = self._reservoir
        if res is None:
            return None
        return bool(res.get("safety_alert"))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        res = self._reservoir
        if res is None:
            return None
        return {
            "status": res.get("status"),
            "leak_detected": res.get("leak_detected"),
            "low_level": res.get("low_level"),
            "probe_ok": res.get("probe_ok"),
            "probe_error": res.get("probe_error"),
            "last_error": res.get("last_error"),
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iGro binary sensors dynamically."""
    coordinator: IGroCoordinator = hass.data[DOMAIN]["coordinator"]
    tracked_envs: set[str] = set()
    tracked_reservoirs: set[str] = set()

    @callback
    def _sync_entities() -> None:
        data = coordinator.data or {}
        current_envs = set(data.get("environments", {}).keys())
        current_reservoirs = set(data.get("reservoirs", {}).keys())

        new_entities: list[BinarySensorEntity] = []
        for eid in current_envs - tracked_envs:
            for desc in ALERT_SENSORS:
                new_entities.append(
                    IGroEnvironmentAlertBinarySensor(coordinator, eid, desc)
                )
            tracked_envs.add(eid)

        for rid in current_reservoirs - tracked_reservoirs:
            new_entities.append(IGroReservoirSafetyBinarySensor(coordinator, rid))
            tracked_reservoirs.add(rid)

        if new_entities:
            async_add_entities(new_entities)

        removed_envs = tracked_envs - current_envs
        removed_res = tracked_reservoirs - current_reservoirs
        if removed_envs or removed_res:
            ent_reg = er.async_get(hass)
            for eid in removed_envs:
                tracked_envs.discard(eid)
                for desc in ALERT_SENSORS:
                    uid = f"{DOMAIN}_env_{eid}_{desc.key}"
                    if ent_id := ent_reg.async_get_entity_id(
                        "binary_sensor", DOMAIN, uid
                    ):
                        ent_reg.async_remove(ent_id)
            for rid in removed_res:
                tracked_reservoirs.discard(rid)
                uid = f"{DOMAIN}_res_{rid}_safety_alert"
                if ent_id := ent_reg.async_get_entity_id("binary_sensor", DOMAIN, uid):
                    ent_reg.async_remove(ent_id)

    _sync_entities()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_ENTITIES_CHANGED, _sync_entities)
    )
