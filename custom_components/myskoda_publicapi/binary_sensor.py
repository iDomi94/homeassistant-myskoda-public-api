"""Binary sensors for the MySkoda PublicAPI integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    ACTIVE_VENTILATION_STATES_ACTIVE,
    AIR_CONDITIONING_STATES_ACTIVE,
    AUXILIARY_HEATING_STATES_ACTIVE,
    CHARGING_STATES_ACTIVE,
    CHARGING_STATES_CABLE_DISCONNECTED,
)
from .coordinator import MySkodaCoordinator, MySkodaPublicApiConfigEntry, VehicleState
from .entity import (
    MySkodaEntityDescriptionMixin,
    MySkodaHubEntity,
    MySkodaVehicleEntity,
    entity_exists,
)
from .utils import clean_value, is_one_of, nested_get

#: An API key is worth warning about this long before it lapses.
KEY_EXPIRY_WARNING = timedelta(days=7)


@dataclass(frozen=True, kw_only=True)
class MySkodaBinarySensorDescription(
    BinarySensorEntityDescription, MySkodaEntityDescriptionMixin
):
    """Describes a MyŠkoda binary sensor."""

    value_fn: Callable[[VehicleState], bool | None]


def _equals(path: str, *expected: str) -> Callable[[VehicleState], bool | None]:
    """Build a value function testing the value at ``path``."""

    def value(state: VehicleState) -> bool | None:
        if state.data is None:
            return None
        return is_one_of(nested_get(state.data.raw, path), frozenset(expected))

    return value


def _boolean(path: str) -> Callable[[VehicleState], bool | None]:
    """Read a boolean straight out of the payload."""

    def value(state: VehicleState) -> bool | None:
        if state.data is None:
            return None
        raw = nested_get(state.data.raw, path)
        return raw if isinstance(raw, bool) else None

    return value


def _cable_connected(state: VehicleState) -> bool | None:
    """Report whether a charging cable is plugged in.

    The API has no dedicated plug sensor; ``CONNECT_CABLE`` is the state that
    asks the user to plug one in, so anything else means it is connected.
    """
    if state.data is None:
        return None
    value = clean_value(nested_get(state.data.raw, "charging.status.state"))
    if value is None:
        return None
    return value not in CHARGING_STATES_CABLE_DISCONNECTED


VEHICLE_BINARY_SENSORS: tuple[MySkodaBinarySensorDescription, ...] = (
    # --- Vehicle status --------------------------------------------------
    MySkodaBinarySensorDescription(
        key="doors_locked",
        translation_key="doors_locked",
        part="status",
        device_class=BinarySensorDeviceClass.LOCK,
        # The lock device class is inverted: "on" means unlocked.
        value_fn=_equals("status.overall.doorsLocked", "NO", "OPENED", "TRUNK_OPENED"),
    ),
    MySkodaBinarySensorDescription(
        key="doors_open",
        translation_key="doors_open",
        part="status",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_equals("status.overall.doors", "OPEN"),
    ),
    MySkodaBinarySensorDescription(
        key="windows_open",
        translation_key="windows_open",
        part="status",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=_equals("status.overall.windows", "OPEN"),
    ),
    MySkodaBinarySensorDescription(
        key="lights_on",
        translation_key="lights_on",
        part="status",
        device_class=BinarySensorDeviceClass.LIGHT,
        value_fn=_equals("status.overall.lights", "ON"),
    ),
    MySkodaBinarySensorDescription(
        key="sunroof_open",
        translation_key="sunroof_open",
        part="status",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=_equals("status.detail.sunroof", "OPEN"),
    ),
    MySkodaBinarySensorDescription(
        key="trunk_open",
        translation_key="trunk_open",
        part="status",
        device_class=BinarySensorDeviceClass.OPENING,
        value_fn=_equals("status.detail.trunk", "OPEN"),
    ),
    MySkodaBinarySensorDescription(
        key="bonnet_open",
        translation_key="bonnet_open",
        part="status",
        device_class=BinarySensorDeviceClass.OPENING,
        value_fn=_equals("status.detail.bonnet", "OPEN"),
    ),
    # --- Charging --------------------------------------------------------
    MySkodaBinarySensorDescription(
        key="charging",
        translation_key="charging",
        part="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda state: is_one_of(
            nested_get(state.data.raw, "charging.status.state") if state.data else None,
            CHARGING_STATES_ACTIVE,
        ),
    ),
    MySkodaBinarySensorDescription(
        key="charging_cable_connected",
        translation_key="charging_cable_connected",
        part="charging",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=_cable_connected,
    ),
    MySkodaBinarySensorDescription(
        key="vehicle_in_saved_location",
        translation_key="vehicle_in_saved_location",
        part="charging",
        expose_raw=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:home-map-marker",
        value_fn=_boolean("charging.isVehicleInSavedLocation"),
    ),
    # --- Climate ---------------------------------------------------------
    MySkodaBinarySensorDescription(
        key="air_conditioning_running",
        translation_key="air_conditioning_running",
        part="airConditioning",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda state: is_one_of(
            nested_get(state.data.raw, "airConditioning.state") if state.data else None,
            AIR_CONDITIONING_STATES_ACTIVE,
        ),
    ),
    MySkodaBinarySensorDescription(
        key="window_heating_enabled",
        translation_key="window_heating_enabled",
        part="airConditioning",
        expose_raw=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:car-defrost-front",
        value_fn=_boolean("airConditioning.windowHeating.enabled"),
    ),
    MySkodaBinarySensorDescription(
        key="window_heating_front_on",
        translation_key="window_heating_front_on",
        part="airConditioning",
        expose_raw=False,
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=_equals("airConditioning.windowHeating.front", "ON"),
    ),
    MySkodaBinarySensorDescription(
        key="window_heating_rear_on",
        translation_key="window_heating_rear_on",
        part="airConditioning",
        expose_raw=False,
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=_equals("airConditioning.windowHeating.rear", "ON"),
    ),
    MySkodaBinarySensorDescription(
        key="air_conditioning_without_external_power",
        translation_key="air_conditioning_without_external_power",
        part="airConditioning",
        expose_raw=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:power-plug-off-outline",
        value_fn=_boolean("airConditioning.airConditioningWithoutExternalPower"),
    ),
    MySkodaBinarySensorDescription(
        key="air_conditioning_at_unlock",
        translation_key="air_conditioning_at_unlock",
        part="airConditioning",
        expose_raw=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:lock-open-variant-outline",
        value_fn=_boolean("airConditioning.airConditioningAtUnlock"),
    ),
    MySkodaBinarySensorDescription(
        key="auxiliary_heating_running",
        translation_key="auxiliary_heating_running",
        part="auxiliaryHeating",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda state: is_one_of(
            nested_get(state.data.raw, "auxiliaryHeating.state")
            if state.data
            else None,
            AUXILIARY_HEATING_STATES_ACTIVE,
        ),
    ),
    MySkodaBinarySensorDescription(
        key="active_ventilation_running",
        translation_key="active_ventilation_running",
        part="activeVentilation",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda state: is_one_of(
            nested_get(state.data.raw, "activeVentilation.state")
            if state.data
            else None,
            ACTIVE_VENTILATION_STATES_ACTIVE,
        ),
    ),
    # --- Parking ---------------------------------------------------------
    MySkodaBinarySensorDescription(
        key="in_motion",
        translation_key="in_motion",
        part="parkingPosition",
        expose_raw=False,
        device_class=BinarySensorDeviceClass.MOVING,
        value_fn=_equals("parkingPosition.state", "IN_MOTION"),
    ),
)


@dataclass(frozen=True, kw_only=True)
class MySkodaHubBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a binary sensor about the API connection itself."""

    value_fn: Callable[[MySkodaCoordinator], bool | None]


def _api_key_expiring(coordinator: MySkodaCoordinator) -> bool | None:
    """Report whether the API key lapses soon and should be renewed."""
    expires_at = coordinator.api.key_expires_at
    if expires_at is None:
        return None
    return expires_at - dt_util.utcnow() <= KEY_EXPIRY_WARNING


HUB_BINARY_SENSORS: tuple[MySkodaHubBinarySensorDescription, ...] = (
    MySkodaHubBinarySensorDescription(
        key="api_key_expiring",
        translation_key="api_key_expiring",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_api_key_expiring,
    ),
    MySkodaHubBinarySensorDescription(
        key="rate_limited",
        translation_key="rate_limited",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: (
            None
            if c.api.rate_limit.remaining is None
            else c.api.rate_limit.remaining <= 0
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MySkodaPublicApiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        MySkodaBinarySensor(coordinator, vin, description)
        for vin, state in coordinator.vehicles.items()
        for description in VEHICLE_BINARY_SENSORS
        if entity_exists(state, description)
    ]
    entities.extend(
        MySkodaHubBinarySensor(coordinator, description)
        for description in HUB_BINARY_SENSORS
    )
    async_add_entities(entities)


class MySkodaBinarySensor(MySkodaVehicleEntity, BinarySensorEntity):
    """A binary sensor derived from the vehicle payload."""

    entity_description: MySkodaBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the current state, or ``None`` if the vehicle did not report."""
        return self.entity_description.value_fn(self.vehicle)


class MySkodaHubBinarySensor(MySkodaHubEntity, BinarySensorEntity):
    """A binary sensor about the API key."""

    entity_description: MySkodaHubBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the current state."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def available(self) -> bool:
        """Key and quota information stays useful even when a poll failed."""
        return True
