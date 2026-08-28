"""Command helpers that combine API calls with locally held parameters.

The public API has no endpoints for writing vehicle settings; parameters such
as the target temperature or the auxiliary-heating duration are only accepted
as part of a start command. They are therefore kept in Home Assistant (see
``CommandSettings``) and merged in here.
"""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError

from .coordinator import MySkodaCoordinator
from .utils import nested_get

TEMPERATURE_UNITS = {"CELSIUS", "FAHRENHEIT"}


def resolve_temperature_unit(coordinator: MySkodaCoordinator, vin: str) -> str:
    """Return the temperature unit to send, following the vehicle if it reports one."""
    state = coordinator.vehicles[vin]
    if state.data is not None:
        for path in (
            "airConditioning.targetTemperature.unit",
            "auxiliaryHeating.targetTemperature.unit",
        ):
            reported = nested_get(state.data.raw, path)
            if isinstance(reported, str) and reported in TEMPERATURE_UNITS:
                return reported
    return state.settings.temperature_unit


async def async_start_air_conditioning(
    coordinator: MySkodaCoordinator,
    vin: str,
    *,
    temperature: float | None = None,
    without_external_power: bool | None = None,
) -> None:
    """Start air conditioning using the locally configured parameters."""
    settings = coordinator.settings(vin)
    await coordinator.api.async_start_air_conditioning(
        vin,
        target_temperature=(
            temperature if temperature is not None else settings.target_temperature
        ),
        temperature_unit=resolve_temperature_unit(coordinator, vin),
        without_external_power=(
            without_external_power
            if without_external_power is not None
            else settings.air_conditioning_without_external_power
        ),
    )


async def async_start_auxiliary_heating(
    coordinator: MySkodaCoordinator,
    vin: str,
    *,
    temperature: float | None = None,
    duration_minutes: int | None = None,
    start_mode: str | None = None,
    spin: str | None = None,
) -> None:
    """Start auxiliary heating. Requires the S-PIN.

    The S-PIN is not asked for during setup -- only the API key is -- so it has
    to be supplied either in the integration options or with the service call.
    """
    settings = coordinator.settings(vin)
    pin = spin or coordinator.spin
    if not pin:
        raise HomeAssistantError(
            "Auxiliary heating requires the S-PIN. Add it in the integration options "
            "(Settings > Devices & services > MySkoda PublicAPI > Configure), or pass it to "
            "the myskoda_publicapi.start_auxiliary_heating action."
        )

    duration = (
        duration_minutes
        if duration_minutes is not None
        else settings.auxiliary_heating_duration_minutes
    )
    await coordinator.api.async_start_auxiliary_heating(
        vin,
        spin=pin,
        target_temperature=(
            temperature if temperature is not None else settings.target_temperature
        ),
        temperature_unit=resolve_temperature_unit(coordinator, vin),
        duration_in_seconds=int(duration) * 60,
        start_mode=start_mode or settings.auxiliary_heating_start_mode,
    )
