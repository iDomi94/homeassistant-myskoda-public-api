"""Shared helpers for driving the mocked MyŠkoda API."""

import re
from http import HTTPStatus

from fixtures import BEV, ICE, RATE_LIMIT_HEADERS, VIN_BEV, VIN_ICE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.myskoda_publicapi.const import CONF_API_KEY, CONF_VINS, DOMAIN

BASE = "https://public.api.connect.skoda-auto.cz"
LIST_URL = f"{BASE}/api/v1/vehicles"


def vehicle_url(vin: str) -> re.Pattern:
    """Match the vehicle endpoint with or without query parameters."""
    return re.compile(rf"^{re.escape(BASE)}/api/v1/vehicles/{vin}(\?.*)?$")


def mock_no_discovery(api) -> None:
    """Answer the listing endpoint the way the real API does today."""
    api.get(LIST_URL, status=HTTPStatus.NOT_FOUND, payload={"title": "Not Found"})


def mock_vehicle(api, vin: str, payload: dict, repeat: bool = True) -> None:
    """Answer the vehicle endpoint with a payload."""
    api.get(
        vehicle_url(vin),
        status=HTTPStatus.OK,
        payload=payload,
        headers=RATE_LIMIT_HEADERS,
        repeat=repeat,
    )


async def setup_integration(hass: HomeAssistant, api, vins=(VIN_BEV,), options=None):
    """Set up a config entry with mocked vehicle data."""
    payloads = {VIN_BEV: BEV, VIN_ICE: ICE}
    for vin in vins:
        mock_vehicle(api, vin, payloads[vin])

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "secret-key", CONF_VINS: list(vins)},
        options=options or {},
        unique_id=",".join(sorted(vins)),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
