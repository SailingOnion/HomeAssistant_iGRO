"""Shared entity base classes for iGro."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import IGroCoordinator


class IGroSummaryEntity(CoordinatorEntity[IGroCoordinator]):
    """Base entity for global iGro summary device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: IGroCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "igro_hub")},
            name="iGro Grow Manager",
            manufacturer="iGro",
            model="Grow Cycle Controller",
        )


class IGroEnvironmentEntity(CoordinatorEntity[IGroCoordinator]):
    """Base entity tied to a specific grow environment (tent/room)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: IGroCoordinator, env_id: str) -> None:
        super().__init__(coordinator)
        self._env_id = env_id

    @property
    def _env(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("environments", {}).get(self._env_id)

    @property
    def available(self) -> bool:
        return super().available and self._env is not None

    @property
    def device_info(self) -> DeviceInfo:
        env = self._env or {}
        return DeviceInfo(
            identifiers={(DOMAIN, f"env_{self._env_id}")},
            name=env.get("name") or f"Environment {self._env_id}",
            manufacturer="iGro",
            model=(env.get("env_type") or "tent").replace("_", " ").title(),
            via_device=(DOMAIN, "igro_hub"),
        )


class IGroPlantEntity(CoordinatorEntity[IGroCoordinator]):
    """Base entity tied to a specific plant."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: IGroCoordinator, plant_id: str) -> None:
        super().__init__(coordinator)
        self._plant_id = plant_id

    @property
    def _plant(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("plants", {}).get(self._plant_id)

    @property
    def available(self) -> bool:
        return super().available and self._plant is not None

    @property
    def device_info(self) -> DeviceInfo:
        plant = self._plant or {}
        strain = plant.get("strain")
        model = f"{strain} ({plant.get('plant_type', 'plant')})" if strain else (
            plant.get("plant_type") or "Plant"
        ).title()
        via = (
            (DOMAIN, f"env_{plant['environment_id']}")
            if plant.get("environment_id")
            else (DOMAIN, "igro_hub")
        )
        return DeviceInfo(
            identifiers={(DOMAIN, f"plant_{self._plant_id}")},
            name=plant.get("name") or f"Plant {self._plant_id}",
            manufacturer=plant.get("breeder") or "iGro",
            model=model,
            via_device=via,
        )
