"""Actions exposed by the MySkoda PublicAPI integration."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    ATTR_DURATION,
    ATTR_SPIN,
    ATTR_START_MODE,
    ATTR_TEMPERATURE,
    ATTR_VIN,
    ATTR_WITHOUT_EXTERNAL_POWER,
    AUX_START_MODES,
    DOMAIN,
    MAX_AUX_HEATING_DURATION,
    MAX_TARGET_TEMPERATURE,
    MIN_AUX_HEATING_DURATION,
    MIN_TARGET_TEMPERATURE,
    SERVICE_REFRESH,
    SERVICE_START_ACTIVE_VENTILATION,
    SERVICE_START_AIR_CONDITIONING,
    SERVICE_START_AUXILIARY_HEATING,
    SERVICE_START_CHARGING,
    SERVICE_STOP_ACTIVE_VENTILATION,
    SERVICE_STOP_AIR_CONDITIONING,
    SERVICE_STOP_AUXILIARY_HEATING,
    SERVICE_STOP_CHARGING,
)
from .coordinator import MySkodaCoordinator
from .helpers import async_start_air_conditioning, async_start_auxiliary_heating

_LOGGER = logging.getLogger(__name__)

VIN_LENGTH = 17


def _as_list(value: object) -> list[str]:
    """Normalise a target selector value into a list of ids."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


TARGET_SCHEMA = {
    vol.Optional(ATTR_VIN): cv.string,
    vol.Optional("device_id"): vol.Any(cv.string, [cv.string]),
    vol.Optional("entity_id"): vol.Any(cv.string, [cv.string]),
}

# Targets arrive as device_id/entity_id/area_id depending on how the action is
# called, so unknown selector keys are tolerated rather than rejected.
BASE_SCHEMA = vol.Schema(TARGET_SCHEMA, extra=vol.ALLOW_EXTRA)

AIR_CONDITIONING_SCHEMA = vol.Schema(
    {
        **TARGET_SCHEMA,
        vol.Optional(ATTR_TEMPERATURE): vol.All(
            vol.Coerce(float),
            vol.Range(min=MIN_TARGET_TEMPERATURE, max=MAX_TARGET_TEMPERATURE),
        ),
        vol.Optional(ATTR_WITHOUT_EXTERNAL_POWER): cv.boolean,
    },
    extra=vol.ALLOW_EXTRA,
)

AUXILIARY_HEATING_SCHEMA = vol.Schema(
    {
        **TARGET_SCHEMA,
        vol.Optional(ATTR_TEMPERATURE): vol.All(
            vol.Coerce(float),
            vol.Range(min=MIN_TARGET_TEMPERATURE, max=MAX_TARGET_TEMPERATURE),
        ),
        vol.Optional(ATTR_DURATION): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_AUX_HEATING_DURATION, max=MAX_AUX_HEATING_DURATION),
        ),
        vol.Optional(ATTR_START_MODE): vol.In([m.lower() for m in AUX_START_MODES]),
        vol.Optional(ATTR_SPIN): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)


def _resolve_targets(
    hass: HomeAssistant, call: ServiceCall
) -> list[tuple[MySkodaCoordinator, str]]:
    """Resolve the call's targets to (coordinator, vin) pairs.

    A call may name a VIN directly or target vehicle devices. Without either,
    it applies to every configured vehicle.
    """
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]
    if not entries:
        raise HomeAssistantError("No MySkoda PublicAPI config entry is loaded")

    wanted: set[str] = set()
    if vin := call.data.get(ATTR_VIN):
        wanted.add(str(vin).strip().upper())

    device_ids = _as_list(call.data.get("device_id"))
    entity_ids = _as_list(call.data.get("entity_id"))
    if entity_ids:
        entities = er.async_get(hass)
        for entity_id in entity_ids:
            entity = entities.async_get(entity_id)
            if entity is not None and entity.device_id:
                device_ids.append(entity.device_id)

    if device_ids:
        devices = dr.async_get(hass)
        for device_id in device_ids:
            device = devices.async_get(device_id)
            if device is None:
                continue
            for domain, identifier in device.identifiers:
                # The hub device uses the entry id, vehicles use their VIN.
                if domain == DOMAIN and len(identifier) == VIN_LENGTH:
                    wanted.add(identifier)

    targets: list[tuple[MySkodaCoordinator, str]] = []
    for entry in entries:
        coordinator: MySkodaCoordinator = entry.runtime_data
        for candidate in coordinator.vins:
            if not wanted or candidate in wanted:
                targets.append((coordinator, candidate))

    if not targets:
        raise HomeAssistantError(
            "None of the targets belong to a configured MyŠkoda vehicle"
        )
    return targets


def _simple(
    command: Callable[[MySkodaCoordinator, str], Awaitable[None]], description: str
) -> Callable[[ServiceCall], Awaitable[None]]:
    """Build a handler that runs one command for every resolved target."""

    async def handler(call: ServiceCall) -> None:
        for coordinator, vin in _resolve_targets(call.hass, call):
            await coordinator.async_send_command(
                vin, lambda c=coordinator, v=vin: command(c, v), description
            )

    return handler


async def _handle_refresh(call: ServiceCall) -> None:
    """Poll the API immediately.

    The coordinator polls every vehicle of an entry in one pass, so each entry
    is refreshed at most once no matter how many vehicles the call targets.
    """
    refreshed: list[MySkodaCoordinator] = []
    for coordinator, _vin in _resolve_targets(call.hass, call):
        if coordinator not in refreshed:
            refreshed.append(coordinator)
            await coordinator.async_request_refresh()


async def _handle_start_air_conditioning(call: ServiceCall) -> None:
    """Start air conditioning with the parameters given in the call."""
    for coordinator, vin in _resolve_targets(call.hass, call):
        await coordinator.async_send_command(
            vin,
            lambda c=coordinator, v=vin: async_start_air_conditioning(
                c,
                v,
                temperature=call.data.get(ATTR_TEMPERATURE),
                without_external_power=call.data.get(ATTR_WITHOUT_EXTERNAL_POWER),
            ),
            "Starting air conditioning",
        )


async def _handle_start_auxiliary_heating(call: ServiceCall) -> None:
    """Start auxiliary heating with the parameters given in the call."""
    start_mode = call.data.get(ATTR_START_MODE)
    for coordinator, vin in _resolve_targets(call.hass, call):
        await coordinator.async_send_command(
            vin,
            lambda c=coordinator, v=vin: async_start_auxiliary_heating(
                c,
                v,
                temperature=call.data.get(ATTR_TEMPERATURE),
                duration_minutes=call.data.get(ATTR_DURATION),
                start_mode=start_mode.upper() if start_mode else None,
                spin=call.data.get(ATTR_SPIN),
            ),
            "Starting auxiliary heating",
        )


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the integration's actions once."""
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        return

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, _handle_refresh, BASE_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_CHARGING,
        _simple(lambda c, vin: c.api.async_start_charging(vin), "Starting charging"),
        BASE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_CHARGING,
        _simple(lambda c, vin: c.api.async_stop_charging(vin), "Stopping charging"),
        BASE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_AIR_CONDITIONING,
        _handle_start_air_conditioning,
        AIR_CONDITIONING_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_AIR_CONDITIONING,
        _simple(
            lambda c, vin: c.api.async_stop_air_conditioning(vin),
            "Stopping air conditioning",
        ),
        BASE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_AUXILIARY_HEATING,
        _handle_start_auxiliary_heating,
        AUXILIARY_HEATING_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_AUXILIARY_HEATING,
        _simple(
            lambda c, vin: c.api.async_stop_auxiliary_heating(vin),
            "Stopping auxiliary heating",
        ),
        BASE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_ACTIVE_VENTILATION,
        _simple(
            lambda c, vin: c.api.async_start_active_ventilation(vin),
            "Starting active ventilation",
        ),
        BASE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_ACTIVE_VENTILATION,
        _simple(
            lambda c, vin: c.api.async_stop_active_ventilation(vin),
            "Stopping active ventilation",
        ),
        BASE_SCHEMA,
    )
