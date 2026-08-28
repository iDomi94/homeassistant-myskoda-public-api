"""Switches for the MySkoda PublicAPI integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    ACTIVE_VENTILATION_STATES_ACTIVE,
    AIR_CONDITIONING_STATES_ACTIVE,
    AUXILIARY_HEATING_STATES_ACTIVE,
    CHARGING_STATES_ACTIVE,
)
from .coordinator import MySkodaCoordinator, MySkodaPublicApiConfigEntry, VehicleState
from .entity import (
    MySkodaEntityDescriptionMixin,
    MySkodaVehicleEntity,
    entity_exists,
)
from .helpers import async_start_air_conditioning, async_start_auxiliary_heating
from .utils import is_one_of, nested_get


@dataclass(frozen=True, kw_only=True)
class MySkodaSwitchDescription(SwitchEntityDescription, MySkodaEntityDescriptionMixin):
    """Describes a MyŠkoda switch backed by a remote command."""

    value_fn: Callable[[VehicleState], bool | None]
    turn_on_fn: Callable[[MySkodaCoordinator, str], Awaitable[None]]
    turn_off_fn: Callable[[MySkodaCoordinator, str], Awaitable[None]]
    #: Human readable name of the operation, used in error messages.
    operation: str


def _state_in(
    path: str, allowed: frozenset[str]
) -> Callable[[VehicleState], bool | None]:
    """Build a value function testing whether an operation is running."""

    def value(state: VehicleState) -> bool | None:
        if state.data is None:
            return None
        return is_one_of(nested_get(state.data.raw, path), allowed)

    return value


SWITCHES: tuple[MySkodaSwitchDescription, ...] = (
    MySkodaSwitchDescription(
        key="charging",
        translation_key="charging",
        part="charging",
        device_class=SwitchDeviceClass.SWITCH,
        icon="mdi:ev-station",
        operation="Charging",
        value_fn=_state_in("charging.status.state", CHARGING_STATES_ACTIVE),
        turn_on_fn=lambda c, vin: c.api.async_start_charging(vin),
        turn_off_fn=lambda c, vin: c.api.async_stop_charging(vin),
    ),
    MySkodaSwitchDescription(
        key="air_conditioning",
        translation_key="air_conditioning",
        part="airConditioning",
        device_class=SwitchDeviceClass.SWITCH,
        icon="mdi:air-conditioner",
        operation="Air conditioning",
        value_fn=_state_in("airConditioning.state", AIR_CONDITIONING_STATES_ACTIVE),
        turn_on_fn=async_start_air_conditioning,
        turn_off_fn=lambda c, vin: c.api.async_stop_air_conditioning(vin),
    ),
    MySkodaSwitchDescription(
        key="auxiliary_heating",
        translation_key="auxiliary_heating",
        part="auxiliaryHeating",
        device_class=SwitchDeviceClass.SWITCH,
        icon="mdi:radiator",
        operation="Auxiliary heating",
        value_fn=_state_in("auxiliaryHeating.state", AUXILIARY_HEATING_STATES_ACTIVE),
        turn_on_fn=async_start_auxiliary_heating,
        turn_off_fn=lambda c, vin: c.api.async_stop_auxiliary_heating(vin),
    ),
    MySkodaSwitchDescription(
        key="active_ventilation",
        translation_key="active_ventilation",
        part="activeVentilation",
        device_class=SwitchDeviceClass.SWITCH,
        icon="mdi:fan",
        operation="Active ventilation",
        value_fn=_state_in("activeVentilation.state", ACTIVE_VENTILATION_STATES_ACTIVE),
        turn_on_fn=lambda c, vin: c.api.async_start_active_ventilation(vin),
        turn_off_fn=lambda c, vin: c.api.async_stop_active_ventilation(vin),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MySkodaPublicApiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform."""
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = []
    for vin, state in coordinator.vehicles.items():
        entities.extend(
            MySkodaSwitch(coordinator, vin, description)
            for description in SWITCHES
            if entity_exists(state, description)
        )
        if entity_exists(state, _WITHOUT_EXTERNAL_POWER):
            entities.append(
                MySkodaWithoutExternalPowerSwitch(
                    coordinator, vin, _WITHOUT_EXTERNAL_POWER
                )
            )
    async_add_entities(entities)


class MySkodaSwitch(MySkodaVehicleEntity, SwitchEntity):
    """A switch that starts and stops a remote operation."""

    entity_description: MySkodaSwitchDescription

    @property
    def is_on(self) -> bool | None:
        """Whether the operation is currently running."""
        return self.entity_description.value_fn(self.vehicle)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the operation."""
        description = self.entity_description
        await self.coordinator.async_send_command(
            self.vin,
            lambda: description.turn_on_fn(self.coordinator, self.vin),
            f"Starting {description.operation.lower()}",
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the operation."""
        description = self.entity_description
        await self.coordinator.async_send_command(
            self.vin,
            lambda: description.turn_off_fn(self.coordinator, self.vin),
            f"Stopping {description.operation.lower()}",
        )


_WITHOUT_EXTERNAL_POWER = MySkodaSwitchDescription(
    key="air_conditioning_without_external_power_setting",
    translation_key="air_conditioning_without_external_power_setting",
    part="airConditioning",
    expose_raw=False,
    entity_category=EntityCategory.CONFIG,
    icon="mdi:power-plug-off-outline",
    operation="Air conditioning without external power",
    value_fn=lambda state: state.settings.air_conditioning_without_external_power,
    turn_on_fn=lambda c, vin: _unsupported(),
    turn_off_fn=lambda c, vin: _unsupported(),
)


async def _unsupported() -> None:
    """Guard for descriptions whose command functions are never called."""
    raise HomeAssistantError("This switch does not send a command")


class MySkodaWithoutExternalPowerSwitch(
    MySkodaVehicleEntity, SwitchEntity, RestoreEntity
):
    """Whether the next air-conditioning start may run off the battery.

    The API accepts this flag only as part of the start command and offers no
    endpoint to change the vehicle's stored setting, so the switch holds the
    value Home Assistant will send next. It is restored across restarts and
    defaults to whatever the vehicle currently reports.
    """

    entity_description: MySkodaSwitchDescription
    _attr_entity_category = EntityCategory.CONFIG

    async def async_added_to_hass(self) -> None:
        """Restore the previously chosen value."""
        await super().async_added_to_hass()
        settings = self.coordinator.settings(self.vin)
        if settings.air_conditioning_without_external_power is None:
            reported = self.get("airConditioning.airConditioningWithoutExternalPower")
            if isinstance(reported, bool):
                settings.air_conditioning_without_external_power = reported
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state in ("on", "off"):
                settings.air_conditioning_without_external_power = (
                    last_state.state == "on"
                )

    @property
    def is_on(self) -> bool | None:
        """The value that will be sent with the next start command."""
        return self.coordinator.settings(
            self.vin
        ).air_conditioning_without_external_power

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Allow air conditioning without external power."""
        self.coordinator.settings(
            self.vin
        ).air_conditioning_without_external_power = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Require external power for air conditioning."""
        self.coordinator.settings(
            self.vin
        ).air_conditioning_without_external_power = False
        self.async_write_ha_state()
