"""The MySkoda PublicAPI integration.

Talks to the official MyŠkoda Public API
(https://public.api.connect.skoda-auto.cz/docs) with an API key created in the
MyŠkoda app. No account credentials and no private endpoints are involved.
"""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import MySkodaCoordinator, MySkodaPublicApiConfigEntry
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.DEVICE_TRACKER,
    Platform.IMAGE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(
    hass: HomeAssistant, entry: MySkodaPublicApiConfigEntry
) -> bool:
    """Set up MySkoda PublicAPI from a config entry."""
    coordinator = MySkodaCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: MySkodaPublicApiConfigEntry
) -> bool:
    """Unload a config entry."""
    entry.runtime_data.async_cancel_pending_refresh()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_update_options(
    hass: HomeAssistant, entry: MySkodaPublicApiConfigEntry
) -> None:
    """Apply changed options without reloading the entry.

    The S-PIN and the post-command refresh are read from the options on every
    use, so only the polling interval needs applying.
    """
    await entry.runtime_data.async_apply_options()


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: MySkodaPublicApiConfigEntry, device_entry: object
) -> bool:
    """Allow removing a vehicle device that is no longer configured."""
    identifiers = getattr(device_entry, "identifiers", set())
    known = {(DOMAIN, entry.entry_id)} | {
        (DOMAIN, vin) for vin in entry.runtime_data.vins
    }
    return not (identifiers & known)
