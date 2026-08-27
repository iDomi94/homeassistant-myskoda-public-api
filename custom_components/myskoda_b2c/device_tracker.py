"""Device tracker for the MyŠkoda B2C integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.device_tracker import (
    TrackerEntity,
    TrackerEntityDescription,
)
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import MySkodaB2CConfigEntry
from .entity import MySkodaEntityDescriptionMixin, MySkodaVehicleEntity, entity_exists
from .utils import clean_value


@dataclass(frozen=True, kw_only=True)
class MySkodaTrackerDescription(
    TrackerEntityDescription, MySkodaEntityDescriptionMixin
):
    """Describes the MyŠkoda device tracker."""


PARKING_POSITION_DESCRIPTION = MySkodaTrackerDescription(
    key="parking_position",
    translation_key="parking_position",
    part="parkingPosition",
    expose_raw=False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MySkodaB2CConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the device tracker platform."""
    coordinator = entry.runtime_data
    async_add_entities(
        MySkodaDeviceTracker(coordinator, vin, PARKING_POSITION_DESCRIPTION)
        for vin, state in coordinator.vehicles.items()
        if entity_exists(state, PARKING_POSITION_DESCRIPTION)
    )


class MySkodaDeviceTracker(MySkodaVehicleEntity, TrackerEntity):
    """The vehicle's last known parking position.

    Coordinates are only reported while the vehicle is parked; in motion the
    API returns the state without a position, and the tracker then keeps
    showing the last known one.
    """

    entity_description: MySkodaTrackerDescription
    _attr_source_type = SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Latitude of the last known parking position."""
        value = self.get("parkingPosition.gpsCoordinates.latitude")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def longitude(self) -> float | None:
        """Longitude of the last known parking position."""
        value = self.get("parkingPosition.gpsCoordinates.longitude")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the resolved address and the parking state."""
        attributes: dict[str, Any] = {}
        if address := self.get("parkingPosition.formattedAddress"):
            attributes["formatted_address"] = address
        if state := clean_value(self.get("parkingPosition.state")):
            attributes["parking_state"] = state
        return attributes or None
