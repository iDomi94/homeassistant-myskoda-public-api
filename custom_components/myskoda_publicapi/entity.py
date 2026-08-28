"""Base entities for the MySkoda PublicAPI integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import MySkodaCoordinator, VehicleState
from .utils import flatten, nested_get


@dataclass(frozen=True, kw_only=True)
class MySkodaEntityDescriptionMixin:
    """Shared description fields for every MyŠkoda platform.

    ``part`` names the top-level section of the vehicle payload the entity is
    derived from. It decides whether the entity is created at all -- a vehicle
    that never reports ``charging`` gets no charging entities -- and which raw
    data is attached as attributes.
    """

    part: str | None = None
    #: Extra parts that must also be present for the entity to be created.
    required_parts: tuple[str, ...] = ()
    #: Attach the whole ``part`` section as flattened attributes.
    expose_raw: bool = True
    attrs_fn: Callable[[VehicleState], dict[str, Any] | None] | None = None
    #: Override the default "is the part present" check.
    exists_fn: Callable[[VehicleState], bool] | None = None


class MySkodaVehicleEntity(CoordinatorEntity[MySkodaCoordinator]):
    """Base class for entities that belong to one vehicle."""

    _attr_has_entity_name = True
    entity_description: EntityDescription

    def __init__(
        self,
        coordinator: MySkodaCoordinator,
        vin: str,
        description: EntityDescription,
    ) -> None:
        """Initialise the entity for a vehicle."""
        super().__init__(coordinator)
        self.vin = vin
        self.entity_description = description
        self._attr_unique_id = f"{vin}_{description.key}"

    @property
    def vehicle(self) -> VehicleState:
        """Runtime state of this entity's vehicle."""
        return self.coordinator.vehicles[self.vin]

    @property
    def raw(self) -> dict[str, Any]:
        """The raw vehicle payload."""
        data = self.vehicle.data
        return data.raw if data else {}

    def get(self, path: str) -> Any:
        """Read a dotted path out of the raw vehicle payload."""
        return nested_get(self.raw, path)

    @property
    def available(self) -> bool:
        """Whether the vehicle has usable data."""
        return super().available and self.vehicle.available

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the vehicle as a device."""
        name = self.raw.get("name") or self.vin
        info = DeviceInfo(
            identifiers={(DOMAIN, self.vin)},
            manufacturer=MANUFACTURER,
            name=name,
            model=name,
            serial_number=self.vin,
            via_device=(DOMAIN, self.coordinator.config_entry.entry_id),
        )
        if license_plate := self.raw.get("licensePlate"):
            info["model"] = f"{name} ({license_plate})"
        return info

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the underlying payload section plus description extras.

        The public API returns considerably more than there are sensible
        entities for, and it is still in beta. Attaching the raw section means
        no data is lost and new API fields appear without a code change.
        """
        description = self.entity_description
        attributes: dict[str, Any] = {}

        part = getattr(description, "part", None)
        expose_raw = getattr(description, "expose_raw", False)
        if expose_raw and part:
            section = self.raw.get(part)
            if isinstance(section, dict):
                attributes.update(flatten(section))

        attrs_fn = getattr(description, "attrs_fn", None)
        if attrs_fn is not None and (extra := attrs_fn(self.vehicle)):
            attributes.update(extra)

        return attributes or None


class MySkodaHubEntity(CoordinatorEntity[MySkodaCoordinator]):
    """Base class for entities that describe the API key rather than a vehicle."""

    _attr_has_entity_name = True
    entity_description: EntityDescription

    def __init__(
        self, coordinator: MySkodaCoordinator, description: EntityDescription
    ) -> None:
        """Initialise the hub-level entity."""
        super().__init__(coordinator)
        self.entity_description = description
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the API connection as a device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            manufacturer=MANUFACTURER,
            name="MySkoda PublicAPI",
            model="Public API",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://public.api.connect.skoda-auto.cz/docs",
        )


def entity_exists(state: VehicleState, description: Any) -> bool:
    """Whether an entity should be created for a vehicle.

    Parts a vehicle does not support are absent from the payload, which is how
    a diesel avoids charging entities and a BEV avoids fuel entities.
    """
    if (exists_fn := getattr(description, "exists_fn", None)) is not None:
        return exists_fn(state)

    data = state.data
    if data is None:
        return False

    parts = [p for p in (getattr(description, "part", None),) if p]
    parts.extend(getattr(description, "required_parts", ()))
    if not parts:
        return True
    return all(isinstance(data.raw.get(part), dict) for part in parts)
