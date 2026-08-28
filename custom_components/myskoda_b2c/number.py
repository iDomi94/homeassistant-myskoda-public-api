"""Number entities for the MyŠkoda B2C integration.

The public API exposes no endpoints for writing vehicle settings, so the
per-vehicle numbers hold the parameters Home Assistant sends with the next
remote command; their values are restored across restarts. The polling
interval is here too, so automations can change it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_POLL_INTERVAL,
    MAX_AUX_HEATING_DURATION,
    MAX_POLL_INTERVAL,
    MAX_TARGET_TEMPERATURE,
    MIN_AUX_HEATING_DURATION,
    MIN_POLL_INTERVAL,
    MIN_TARGET_TEMPERATURE,
    TARGET_TEMPERATURE_STEP,
)
from .coordinator import CommandSettings, MySkodaB2CConfigEntry
from .entity import (
    MySkodaEntityDescriptionMixin,
    MySkodaHubEntity,
    MySkodaVehicleEntity,
    entity_exists,
)


@dataclass(frozen=True, kw_only=True)
class MySkodaNumberDescription(NumberEntityDescription, MySkodaEntityDescriptionMixin):
    """Describes a locally held command parameter."""

    value_fn: Callable[[CommandSettings], float]
    set_fn: Callable[[CommandSettings, float], None]


def _set_target_temperature(settings: CommandSettings, value: float) -> None:
    """Store the target temperature used by climate commands."""
    settings.target_temperature = value


def _set_aux_duration(settings: CommandSettings, value: float) -> None:
    """Store how long auxiliary heating should run."""
    settings.auxiliary_heating_duration_minutes = int(value)


NUMBERS: tuple[MySkodaNumberDescription, ...] = (
    MySkodaNumberDescription(
        key="target_temperature_setting",
        translation_key="target_temperature_setting",
        part=None,
        expose_raw=False,
        # Present whenever the vehicle has any climate function to command.
        exists_fn=lambda state: (
            state.data is not None
            and any(
                isinstance(state.data.raw.get(part), dict)
                for part in ("airConditioning", "auxiliaryHeating")
            )
        ),
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=MIN_TARGET_TEMPERATURE,
        native_max_value=MAX_TARGET_TEMPERATURE,
        native_step=TARGET_TEMPERATURE_STEP,
        mode=NumberMode.BOX,
        value_fn=lambda settings: settings.target_temperature,
        set_fn=_set_target_temperature,
    ),
    MySkodaNumberDescription(
        key="auxiliary_heating_duration_setting",
        translation_key="auxiliary_heating_duration_setting",
        part="auxiliaryHeating",
        expose_raw=False,
        entity_category=EntityCategory.CONFIG,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        native_min_value=MIN_AUX_HEATING_DURATION,
        native_max_value=MAX_AUX_HEATING_DURATION,
        native_step=5,
        mode=NumberMode.BOX,
        icon="mdi:timer-outline",
        value_fn=lambda settings: settings.auxiliary_heating_duration_minutes,
        set_fn=_set_aux_duration,
    ),
)


#: The polling interval lives on the config entry rather than on a vehicle, so
#: it is offered on the API device and can be changed from an automation --
#: poll more often while charging, and back off again afterwards.
POLL_INTERVAL_DESCRIPTION = NumberEntityDescription(
    key="polling_interval",
    translation_key="polling_interval",
    entity_category=EntityCategory.CONFIG,
    native_min_value=MIN_POLL_INTERVAL,
    native_max_value=MAX_POLL_INTERVAL,
    native_step=1,
    native_unit_of_measurement=UnitOfTime.MINUTES,
    mode=NumberMode.BOX,
    icon="mdi:timer-sync-outline",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MySkodaB2CConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number platform."""
    coordinator = entry.runtime_data
    entities: list[NumberEntity] = [
        MySkodaNumber(coordinator, vin, description)
        for vin, state in coordinator.vehicles.items()
        for description in NUMBERS
        if entity_exists(state, description)
    ]
    entities.append(MySkodaPollIntervalNumber(coordinator, POLL_INTERVAL_DESCRIPTION))
    async_add_entities(entities)


class MySkodaNumber(MySkodaVehicleEntity, RestoreNumber):
    """A command parameter kept in Home Assistant."""

    entity_description: MySkodaNumberDescription

    @property
    def available(self) -> bool:
        """Always available: the value lives in Home Assistant, not the vehicle."""
        return True

    async def async_added_to_hass(self) -> None:
        """Restore the value chosen before the restart.

        The plain state is used as a fallback when the extra restore data is
        missing, which happens for entities that predate it.
        """
        await super().async_added_to_hass()
        restored: float | None = None
        if (last := await self.async_get_last_number_data()) is not None:
            restored = last.native_value
        if (
            restored is None
            and (state := await self.async_get_last_state()) is not None
        ):
            try:
                restored = float(state.state)
            except (TypeError, ValueError):
                restored = None
        if restored is not None:
            self.entity_description.set_fn(
                self.coordinator.settings(self.vin), restored
            )

    @property
    def native_value(self) -> float:
        """The value that will be sent with the next command."""
        return self.entity_description.value_fn(self.coordinator.settings(self.vin))

    async def async_set_native_value(self, value: float) -> None:
        """Store a new value."""
        self.entity_description.set_fn(self.coordinator.settings(self.vin), value)
        self.async_write_ha_state()


class MySkodaPollIntervalNumber(MySkodaHubEntity, NumberEntity):
    """The polling interval, as an entity so automations can change it.

    Writing stores the value in the config entry options, which is the same
    place the options dialog writes to, so a change made from an automation
    survives a restart.
    """

    entity_description: NumberEntityDescription

    @property
    def available(self) -> bool:
        """Always available: the value is Home Assistant's, not the vehicle's."""
        return True

    @property
    def native_value(self) -> float:
        """The interval currently in use, in minutes."""
        return self.coordinator.poll_interval

    async def async_set_native_value(self, value: float) -> None:
        """Store a new interval and apply it to the running coordinator."""
        entry = self.coordinator.config_entry
        self.hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, CONF_POLL_INTERVAL: int(value)},
        )
