"""Select entities for the MySkoda PublicAPI integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import AUX_START_MODE_HEATING, AUX_START_MODES
from .coordinator import MySkodaPublicApiConfigEntry
from .entity import MySkodaEntityDescriptionMixin, MySkodaVehicleEntity, entity_exists


@dataclass(frozen=True, kw_only=True)
class MySkodaSelectDescription(SelectEntityDescription, MySkodaEntityDescriptionMixin):
    """Describes a locally held command parameter offered as a select."""


START_MODE_DESCRIPTION = MySkodaSelectDescription(
    part="auxiliaryHeating",
    expose_raw=False,
    key="auxiliary_heating_start_mode_setting",
    translation_key="auxiliary_heating_start_mode_setting",
    entity_category=EntityCategory.CONFIG,
    icon="mdi:radiator",
    options=[mode.lower() for mode in AUX_START_MODES],
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MySkodaPublicApiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select platform."""
    coordinator = entry.runtime_data
    async_add_entities(
        MySkodaAuxiliaryHeatingStartMode(coordinator, vin, START_MODE_DESCRIPTION)
        for vin, state in coordinator.vehicles.items()
        if entity_exists(state, START_MODE_DESCRIPTION)
    )


class MySkodaAuxiliaryHeatingStartMode(
    MySkodaVehicleEntity, SelectEntity, RestoreEntity
):
    """Whether auxiliary heating starts in heating or ventilation mode.

    The API accepts the mode only as part of the start command, so the choice
    is held in Home Assistant and applied on the next start.
    """

    @property
    def available(self) -> bool:
        """Always available: the value lives in Home Assistant, not the vehicle."""
        return True

    async def async_added_to_hass(self) -> None:
        """Restore the mode chosen before the restart."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in (self.options or []):
            self.coordinator.settings(
                self.vin
            ).auxiliary_heating_start_mode = last_state.state.upper()

    @property
    def current_option(self) -> str | None:
        """The mode that will be used on the next start."""
        mode = self.coordinator.settings(self.vin).auxiliary_heating_start_mode
        return (mode or AUX_START_MODE_HEATING).lower()

    async def async_select_option(self, option: str) -> None:
        """Store a new start mode."""
        self.coordinator.settings(
            self.vin
        ).auxiliary_heating_start_mode = option.upper()
        self.async_write_ha_state()
