"""Diagnostics for the MyŠkoda B2C integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY, CONF_SPIN, CONF_VINS
from .coordinator import MySkodaB2CConfigEntry

TO_REDACT = {
    CONF_API_KEY,
    CONF_SPIN,
    CONF_VINS,
    "vin",
    "licensePlate",
    "formattedAddress",
    "gpsCoordinates",
    "renderUrl",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MySkodaB2CConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "api": {
            "rate_limit": coordinator.api.rate_limit.as_dict(),
            "api_key_expires_at": (
                coordinator.api.key_expires_at.isoformat()
                if coordinator.api.key_expires_at
                else None
            ),
        },
        "vehicles": [
            {
                "vin": "**REDACTED**",
                "last_error": state.last_error,
                "fetched_at": (
                    state.data.fetched_at.isoformat()
                    if state.data and state.data.fetched_at
                    else None
                ),
                "errors": state.data.errors if state.data else [],
                "raw": async_redact_data(state.data.raw, TO_REDACT)
                if state.data
                else None,
                "command_settings": {
                    "target_temperature": state.settings.target_temperature,
                    "temperature_unit": state.settings.temperature_unit,
                    "air_conditioning_without_external_power": (
                        state.settings.air_conditioning_without_external_power
                    ),
                    "auxiliary_heating_duration_minutes": (
                        state.settings.auxiliary_heating_duration_minutes
                    ),
                    "auxiliary_heating_start_mode": (
                        state.settings.auxiliary_heating_start_mode
                    ),
                },
            }
            for state in coordinator.vehicles.values()
        ],
    }
