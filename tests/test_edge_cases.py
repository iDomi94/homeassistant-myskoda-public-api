"""Tests for the awkward corners: unknown values, partial data, restores."""

import json
from http import HTTPStatus

from api_mock import BASE, mock_vehicle, setup_integration, vehicle_url
from fixtures import BEV, VIN_BEV, VIN_ICE
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

from custom_components.myskoda_publicapi.const import CONF_API_KEY, CONF_VINS, DOMAIN
from custom_components.myskoda_publicapi.diagnostics import (
    async_get_config_entry_diagnostics,
)


def bev_with(**changes) -> dict:
    """Return a copy of the BEV payload with parts replaced."""
    payload = json.loads(json.dumps(BEV))
    for path, value in changes.items():
        target = payload["vehicle"]
        keys = path.split(".")
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value
    return payload


async def test_unknown_enum_value_is_kept_as_attribute(
    hass: HomeAssistant, api
) -> None:
    """A value the API adds later does not break the entity."""
    payload = bev_with(**{"charging.status.state": "SOMETHING_NEW"})
    mock_vehicle(api, VIN_BEV, payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "k", CONF_VINS: [VIN_BEV]},
        unique_id=VIN_BEV,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.my_enyaq_charging_state")
    assert state.state == STATE_UNKNOWN
    assert state.attributes["raw_value"] == "SOMETHING_NEW"


async def test_fahrenheit_is_followed(hass: HomeAssistant, api) -> None:
    """The unit reported by the vehicle is used for reading and writing."""
    payload = bev_with(
        **{"airConditioning.targetTemperature": {"value": 72.0, "unit": "FAHRENHEIT"}}
    )
    mock_vehicle(api, VIN_BEV, payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "k", CONF_VINS: [VIN_BEV]},
        unique_id=VIN_BEV,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    api.post(
        f"{BASE}/api/v1/vehicles/{VIN_BEV}/air-conditioning/start",
        status=HTTPStatus.ACCEPTED,
    )
    await hass.services.async_call(
        "switch",
        "turn_on",
        {ATTR_ENTITY_ID: "switch.my_enyaq_air_conditioning"},
        blocking=True,
    )
    body = next(
        calls[-1].kwargs["json"]
        for key, calls in api.requests.items()
        if key[0] == "POST"
    )
    assert body["targetTemperature"]["unit"] == "FAHRENHEIT"


async def test_missing_parking_position_keeps_other_entities(
    hass: HomeAssistant, api
) -> None:
    """A vehicle in motion reports a state without coordinates."""
    payload = bev_with(**{"parkingPosition": {"state": "IN_MOTION"}})
    mock_vehicle(api, VIN_BEV, payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "k", CONF_VINS: [VIN_BEV]},
        unique_id=VIN_BEV,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    tracker = hass.states.get("device_tracker.my_enyaq_parking_position")
    assert "latitude" not in tracker.attributes
    assert hass.states.get("binary_sensor.my_enyaq_in_motion").state == "on"
    assert hass.states.get("sensor.my_enyaq_mileage").state == "12753"


async def test_one_failing_vehicle_does_not_break_the_other(
    hass: HomeAssistant, api
) -> None:
    """A per-vehicle error leaves the remaining vehicles usable."""
    mock_vehicle(api, VIN_BEV, BEV)
    api.get(
        vehicle_url(VIN_ICE),
        status=HTTPStatus.INTERNAL_SERVER_ERROR,
        payload={"title": "Internal Server Error"},
        repeat=True,
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "k", CONF_VINS: [VIN_BEV, VIN_ICE]},
        unique_id=f"{VIN_BEV},{VIN_ICE}",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.my_enyaq_mileage").state == "12753"
    assert entry.runtime_data.vehicles[VIN_ICE].last_error is not None


async def test_local_settings_are_restored(hass: HomeAssistant, api) -> None:
    """Command parameters survive a restart."""
    mock_restore_cache(
        hass,
        (
            State("number.my_enyaq_auxiliary_heating_duration", "45"),
            State("select.my_enyaq_auxiliary_heating_start_mode", "ventilation"),
        ),
    )
    entry = await setup_integration(hass, api)
    settings = entry.runtime_data.settings(VIN_BEV)
    assert settings.auxiliary_heating_duration_minutes == 45
    assert settings.auxiliary_heating_start_mode == "VENTILATION"


async def test_reauth_updates_the_key(hass: HomeAssistant, api) -> None:
    """Entering a new API key repairs the entry in place."""
    entry = await setup_integration(hass, api)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "fresh-key"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "fresh-key"


async def test_diagnostics_redacts_identifiers(hass: HomeAssistant, api) -> None:
    """Diagnostics never leak the key, the VIN or the parking address."""
    entry = await setup_integration(hass, api)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(diagnostics)

    assert "secret-key" not in dumped
    assert VIN_BEV not in dumped
    assert "Prazska" not in dumped
    assert "1MB 1234" not in dumped
    # Useful content survives.
    assert diagnostics["api"]["rate_limit"]["limit"] == 20
    assert diagnostics["vehicles"][0]["raw"]["odometer"]["mileageInKm"] == 12753


async def test_duplicate_entry_is_rejected(hass: HomeAssistant, api) -> None:
    """The same set of vehicles cannot be added twice."""
    await setup_integration(hass, api)
    api.get(f"{BASE}/api/v1/vehicles", status=HTTPStatus.NOT_FOUND, payload={})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "another-key"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_VINS: [VIN_BEV]}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_vins_accept_lowercase_and_whitespace(hass: HomeAssistant, api) -> None:
    """VINs are normalised before they reach the API."""
    api.get(f"{BASE}/api/v1/vehicles", status=HTTPStatus.NOT_FOUND, payload={})
    mock_vehicle(api, VIN_BEV, BEV)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "k"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_VINS: [f"  {VIN_BEV.lower()} "]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_VINS] == [VIN_BEV]


async def test_disabled_part_produces_no_entities(hass: HomeAssistant, api) -> None:
    """A disabled service is absent from the payload and gets no entities."""
    payload = json.loads(json.dumps(BEV))
    del payload["vehicle"]["charging"]
    payload["errors"] = [{"type": "CHARGING_DISABLED", "description": "disabled"}]
    mock_vehicle(api, VIN_BEV, payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "k", CONF_VINS: [VIN_BEV]},
        unique_id=VIN_BEV,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.my_enyaq_charging_state") is None
    assert hass.states.get("switch.my_enyaq_charging") is None
    assert hass.states.get("sensor.my_enyaq_data_errors").state == "1"
    # Everything else still works.
    assert hass.states.get("sensor.my_enyaq_mileage").state == "12753"
