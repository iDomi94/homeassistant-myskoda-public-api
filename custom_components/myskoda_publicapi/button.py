"""Buttons for the MySkoda PublicAPI integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import MySkodaCoordinator, MySkodaPublicApiConfigEntry
from .entity import MySkodaEntityDescriptionMixin, MySkodaVehicleEntity, entity_exists
from .helpers import async_start_air_conditioning, async_start_auxiliary_heating


@dataclass(frozen=True, kw_only=True)
class MySkodaButtonDescription(ButtonEntityDescription, MySkodaEntityDescriptionMixin):
    """Describes a MyŠkoda button."""

    press_fn: Callable[[MySkodaCoordinator, str], Awaitable[None]]
    operation: str


#: The switch and climate entities cover the same commands, so the command
#: buttons are off by default -- they exist for scripts and dashboards that
#: prefer a stateless press.
BUTTONS: tuple[MySkodaButtonDescription, ...] = (
    MySkodaButtonDescription(
        key="start_charging",
        translation_key="start_charging",
        part="charging",
        expose_raw=False,
        entity_registry_enabled_default=False,
        icon="mdi:play",
        operation="Starting charging",
        press_fn=lambda c, vin: c.api.async_start_charging(vin),
    ),
    MySkodaButtonDescription(
        key="stop_charging",
        translation_key="stop_charging",
        part="charging",
        expose_raw=False,
        entity_registry_enabled_default=False,
        icon="mdi:stop",
        operation="Stopping charging",
        press_fn=lambda c, vin: c.api.async_stop_charging(vin),
    ),
    MySkodaButtonDescription(
        key="start_air_conditioning",
        translation_key="start_air_conditioning",
        part="airConditioning",
        expose_raw=False,
        entity_registry_enabled_default=False,
        icon="mdi:air-conditioner",
        operation="Starting air conditioning",
        press_fn=async_start_air_conditioning,
    ),
    MySkodaButtonDescription(
        key="stop_air_conditioning",
        translation_key="stop_air_conditioning",
        part="airConditioning",
        expose_raw=False,
        entity_registry_enabled_default=False,
        icon="mdi:air-conditioner",
        operation="Stopping air conditioning",
        press_fn=lambda c, vin: c.api.async_stop_air_conditioning(vin),
    ),
    MySkodaButtonDescription(
        key="start_auxiliary_heating",
        translation_key="start_auxiliary_heating",
        part="auxiliaryHeating",
        expose_raw=False,
        entity_registry_enabled_default=False,
        icon="mdi:radiator",
        operation="Starting auxiliary heating",
        press_fn=async_start_auxiliary_heating,
    ),
    MySkodaButtonDescription(
        key="stop_auxiliary_heating",
        translation_key="stop_auxiliary_heating",
        part="auxiliaryHeating",
        expose_raw=False,
        entity_registry_enabled_default=False,
        icon="mdi:radiator-off",
        operation="Stopping auxiliary heating",
        press_fn=lambda c, vin: c.api.async_stop_auxiliary_heating(vin),
    ),
    MySkodaButtonDescription(
        key="start_active_ventilation",
        translation_key="start_active_ventilation",
        part="activeVentilation",
        expose_raw=False,
        entity_registry_enabled_default=False,
        icon="mdi:fan",
        operation="Starting active ventilation",
        press_fn=lambda c, vin: c.api.async_start_active_ventilation(vin),
    ),
    MySkodaButtonDescription(
        key="stop_active_ventilation",
        translation_key="stop_active_ventilation",
        part="activeVentilation",
        expose_raw=False,
        entity_registry_enabled_default=False,
        icon="mdi:fan-off",
        operation="Stopping active ventilation",
        press_fn=lambda c, vin: c.api.async_stop_active_ventilation(vin),
    ),
)

REFRESH_DESCRIPTION = MySkodaButtonDescription(
    key="refresh",
    translation_key="refresh",
    part=None,
    expose_raw=False,
    entity_category=EntityCategory.DIAGNOSTIC,
    icon="mdi:refresh",
    operation="Refreshing vehicle data",
    press_fn=lambda c, vin: c.async_request_refresh(),
    exists_fn=lambda state: True,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MySkodaPublicApiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform."""
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = []
    for vin, state in coordinator.vehicles.items():
        entities.append(MySkodaRefreshButton(coordinator, vin, REFRESH_DESCRIPTION))
        entities.extend(
            MySkodaButton(coordinator, vin, description)
            for description in BUTTONS
            if entity_exists(state, description)
        )
    async_add_entities(entities)


class MySkodaButton(MySkodaVehicleEntity, ButtonEntity):
    """A button that sends one remote command."""

    entity_description: MySkodaButtonDescription

    async def async_press(self) -> None:
        """Send the command."""
        description = self.entity_description
        await self.coordinator.async_send_command(
            self.vin,
            lambda: description.press_fn(self.coordinator, self.vin),
            description.operation,
        )


class MySkodaRefreshButton(MySkodaVehicleEntity, ButtonEntity):
    """Polls the API immediately.

    Every poll counts against the shared hourly quota, so this is a manual
    action rather than something automations should call in a loop.
    """

    entity_description: MySkodaButtonDescription

    @property
    def available(self) -> bool:
        """Refreshing is possible even before the first successful poll."""
        return True

    async def async_press(self) -> None:
        """Request an immediate refresh."""
        await self.coordinator.async_request_refresh()
