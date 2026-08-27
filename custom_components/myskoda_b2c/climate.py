"""Climate entities for the MyŠkoda B2C integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    AIR_CONDITIONING_STATES_ACTIVE,
    AUX_START_MODE_HEATING,
    AUX_START_MODE_VENTILATION,
    AUXILIARY_HEATING_STATES_ACTIVE,
    MAX_TARGET_TEMPERATURE,
    MIN_TARGET_TEMPERATURE,
    TARGET_TEMPERATURE_STEP,
)
from .coordinator import MySkodaB2CConfigEntry
from .entity import MySkodaEntityDescriptionMixin, MySkodaVehicleEntity, entity_exists
from .helpers import async_start_air_conditioning, async_start_auxiliary_heating
from .utils import clean_value

TEMPERATURE_UNITS = {
    "CELSIUS": UnitOfTemperature.CELSIUS,
    "FAHRENHEIT": UnitOfTemperature.FAHRENHEIT,
}

#: Maps the reported air-conditioning state onto what the system is doing.
AIR_CONDITIONING_ACTIONS = {
    "OFF": HVACAction.OFF,
    "COOLING": HVACAction.COOLING,
    "HEATING": HVACAction.HEATING,
    "HEATING_AUXILIARY": HVACAction.HEATING,
    "VENTILATION": HVACAction.FAN,
    "COMPLETED": HVACAction.IDLE,
}

AUXILIARY_HEATING_ACTIONS = {
    "OFF": HVACAction.OFF,
    "PREHEATING": HVACAction.PREHEATING,
    "HEATING_AUXILIARY": HVACAction.HEATING,
    "VENTILATION": HVACAction.FAN,
}

PRESET_HEATING = "heating"
PRESET_VENTILATION = "ventilation"
START_MODE_PRESETS = {
    AUX_START_MODE_HEATING: PRESET_HEATING,
    AUX_START_MODE_VENTILATION: PRESET_VENTILATION,
}
PRESET_START_MODES = {value: key for key, value in START_MODE_PRESETS.items()}


@dataclass(frozen=True, kw_only=True)
class MySkodaClimateDescription(
    ClimateEntityDescription, MySkodaEntityDescriptionMixin
):
    """Describes a MyŠkoda climate entity."""


AIR_CONDITIONING_DESCRIPTION = MySkodaClimateDescription(
    key="air_conditioning",
    translation_key="air_conditioning",
    part="airConditioning",
)

AUXILIARY_HEATING_DESCRIPTION = MySkodaClimateDescription(
    key="auxiliary_heating",
    translation_key="auxiliary_heating",
    part="auxiliaryHeating",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MySkodaB2CConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the climate platform."""
    coordinator = entry.runtime_data
    entities: list[ClimateEntity] = []
    for vin, state in coordinator.vehicles.items():
        if entity_exists(state, AIR_CONDITIONING_DESCRIPTION):
            entities.append(
                MySkodaAirConditioning(coordinator, vin, AIR_CONDITIONING_DESCRIPTION)
            )
        if entity_exists(state, AUXILIARY_HEATING_DESCRIPTION):
            entities.append(
                MySkodaAuxiliaryHeating(coordinator, vin, AUXILIARY_HEATING_DESCRIPTION)
            )
    async_add_entities(entities)


class MySkodaClimateBase(MySkodaVehicleEntity, ClimateEntity):
    """Shared behaviour of the two climate entities."""

    _attr_min_temp = MIN_TARGET_TEMPERATURE
    _attr_max_temp = MAX_TARGET_TEMPERATURE
    _attr_target_temperature_step = TARGET_TEMPERATURE_STEP
    _attr_precision = TARGET_TEMPERATURE_STEP

    #: Dotted path to the temperature this entity reflects.
    temperature_path: str

    @property
    def coordinator_settings(self) -> Any:
        """Locally held command parameters for this vehicle."""
        return self.coordinator.settings(self.vin)

    @property
    def temperature_unit(self) -> str:
        """Follow the unit the vehicle reports, defaulting to Celsius."""
        reported = self.get(f"{self.temperature_path}.unit")
        return TEMPERATURE_UNITS.get(str(reported), UnitOfTemperature.CELSIUS)

    @property
    def target_temperature(self) -> float | None:
        """Prefer the vehicle's own target, falling back to what we will send."""
        reported = self.get(f"{self.temperature_path}.value")
        if isinstance(reported, (int, float)):
            return float(reported)
        return self.coordinator_settings.target_temperature

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Store the new target and re-issue the command if it is running."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self.coordinator_settings.target_temperature = float(temperature)
        self.async_write_ha_state()
        if self.hvac_mode != HVACMode.OFF:
            await self._async_start()

    async def _async_start(self) -> None:
        """Send the start command for this entity."""
        raise NotImplementedError

    async def _async_stop(self) -> None:
        """Send the stop command for this entity."""
        raise NotImplementedError

    async def async_turn_on(self) -> None:
        """Start the climate function."""
        await self._async_start()

    async def async_turn_off(self) -> None:
        """Stop the climate function."""
        await self._async_stop()


class MySkodaAirConditioning(MySkodaClimateBase):
    """Air conditioning as a climate entity.

    The API only offers start and stop plus a target temperature, so the entity
    exposes a single active mode next to off.
    """

    temperature_path = "airConditioning.targetTemperature"
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT_COOL]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Whether air conditioning is currently running."""
        state = clean_value(self.get("airConditioning.state"))
        if state is None:
            return None
        return (
            HVACMode.HEAT_COOL
            if state in AIR_CONDITIONING_STATES_ACTIVE
            else HVACMode.OFF
        )

    @property
    def hvac_action(self) -> HVACAction | None:
        """What the air conditioning is doing right now."""
        state = clean_value(self.get("airConditioning.state"))
        if state is None:
            return None
        return AIR_CONDITIONING_ACTIONS.get(str(state))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Start or stop air conditioning."""
        if hvac_mode == HVACMode.OFF:
            await self._async_stop()
        else:
            await self._async_start()

    async def _async_start(self) -> None:
        """Start air conditioning with the current target temperature."""
        await self.coordinator.async_send_command(
            self.vin,
            lambda: async_start_air_conditioning(self.coordinator, self.vin),
            "Starting air conditioning",
        )

    async def _async_stop(self) -> None:
        """Stop air conditioning."""
        await self.coordinator.async_send_command(
            self.vin,
            lambda: self.coordinator.api.async_stop_air_conditioning(self.vin),
            "Stopping air conditioning",
        )


class MySkodaAuxiliaryHeating(MySkodaClimateBase):
    """Auxiliary heating as a climate entity.

    Starting it needs the S-PIN, which is configured in the integration options.
    The preset selects whether the heater runs in heating or ventilation mode.
    """

    temperature_path = "auxiliaryHeating.targetTemperature"
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes = [PRESET_HEATING, PRESET_VENTILATION]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Whether auxiliary heating is currently running."""
        state = clean_value(self.get("auxiliaryHeating.state"))
        if state is None:
            return None
        return (
            HVACMode.HEAT if state in AUXILIARY_HEATING_STATES_ACTIVE else HVACMode.OFF
        )

    @property
    def hvac_action(self) -> HVACAction | None:
        """What the auxiliary heater is doing right now."""
        state = clean_value(self.get("auxiliaryHeating.state"))
        if state is None:
            return None
        return AUXILIARY_HEATING_ACTIONS.get(str(state))

    @property
    def preset_mode(self) -> str | None:
        """The mode the heater will start in."""
        return START_MODE_PRESETS.get(
            self.coordinator_settings.auxiliary_heating_start_mode
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Choose heating or ventilation for the next start."""
        if (start_mode := PRESET_START_MODES.get(preset_mode)) is None:
            return
        self.coordinator_settings.auxiliary_heating_start_mode = start_mode
        self.async_write_ha_state()
        if self.hvac_mode not in (None, HVACMode.OFF):
            await self._async_start()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Start or stop auxiliary heating."""
        if hvac_mode == HVACMode.OFF:
            await self._async_stop()
        else:
            await self._async_start()

    async def _async_start(self) -> None:
        """Start auxiliary heating with the current parameters."""
        await self.coordinator.async_send_command(
            self.vin,
            lambda: async_start_auxiliary_heating(self.coordinator, self.vin),
            "Starting auxiliary heating",
        )

    async def _async_stop(self) -> None:
        """Stop auxiliary heating."""
        await self.coordinator.async_send_command(
            self.vin,
            lambda: self.coordinator.api.async_stop_auxiliary_heating(self.vin),
            "Stopping auxiliary heating",
        )
