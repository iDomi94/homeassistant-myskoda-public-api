"""Runs the integration against a real MyŠkoda API response.

The payload in ``fixture_real_enyaq.json`` was captured from a live Enyaq with
a real API key and anonymised: VIN, licence plate, render URL, parking position
and the names of the saved charging locations were replaced. Everything else --
which parts the vehicle reports, which fields it omits, the exact enum values
and timestamp formats -- is untouched, which is the point of the file.
"""

import json
from http import HTTPStatus
from pathlib import Path

from api_mock import LIST_URL, vehicle_url
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.myskoda_publicapi.const import CONF_API_KEY, CONF_VINS, DOMAIN
from custom_components.myskoda_publicapi.utils import nested_get, parse_timestamp

REAL = json.loads((Path(__file__).parent / "fixture_real_enyaq.json").read_text())
VIN = REAL["vehicle"]["vin"]

#: Headers exactly as the live API returned them, milliseconds included.
REAL_HEADERS = {
    "RateLimit-Limit": "20",
    "RateLimit-Remaining": "13",
    "RateLimit-Reset": "2487",
    "X-API-Key-Expires-At": "2027-02-26T11:02:57.912Z",
}


async def setup_real(hass: HomeAssistant, api) -> MockConfigEntry:
    """Set up the integration against the captured response."""
    api.get(
        vehicle_url(VIN),
        status=HTTPStatus.OK,
        payload=REAL,
        headers=REAL_HEADERS,
        repeat=True,
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "k", CONF_VINS: [VIN]},
        unique_id=VIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_real_payload_sets_up(hass: HomeAssistant, api) -> None:
    """The captured response must produce a working config entry."""
    entry = await setup_real(hass, api)
    assert entry.runtime_data.last_update_success
    assert hass.states.get("sensor.enyaq_mileage").state == "57336"
    assert hass.states.get("sensor.enyaq_battery").state == "75"
    assert hass.states.get("sensor.enyaq_charging_state").state == "connect_cable"
    assert hass.states.get("binary_sensor.enyaq_charging_cable").state == "off"
    assert hass.states.get("binary_sensor.enyaq_doors_locked").state == "off"


async def test_every_real_enum_value_is_known(hass: HomeAssistant, api) -> None:
    """No sensor may fall back to unknown because of an unmapped enum value.

    A raw_value attribute means the vehicle reported something outside the
    documented vocabulary, which would silently blank the entity.
    """
    await setup_real(hass, api)
    unmapped = {
        state.entity_id: state.attributes["raw_value"]
        for state in hass.states.async_all("sensor")
        if "raw_value" in state.attributes
    }
    assert not unmapped, unmapped


async def test_absent_parts_produce_no_entities(hass: HomeAssistant, api) -> None:
    """This Enyaq reports no fuel, auxiliary heating or active ventilation."""
    entry = await setup_real(hass, api)
    unique_ids = {
        e.unique_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    for absent in ("car_type", "auxiliary_heating_state", "active_ventilation_state"):
        assert f"{VIN}_{absent}" not in unique_ids, absent
    # ... while the parts it does report are there.
    for present in ("mileage", "charging_state", "air_conditioning_state"):
        assert f"{VIN}_{present}" in unique_ids, present


async def test_fields_the_vehicle_omits_stay_unknown(hass: HomeAssistant, api) -> None:
    """Missing fields inside a reported part must not break their entities."""
    await setup_real(hass, api)
    # The car reports charging, but neither charge type nor charging rate.
    assert hass.states.get("sensor.enyaq_charge_type").state == STATE_UNKNOWN
    assert hass.states.get("sensor.enyaq_charging_rate").state == STATE_UNKNOWN
    assert (
        hass.states.get("sensor.enyaq_maximum_charge_current_a").state == STATE_UNKNOWN
    )


async def test_in_motion_has_no_coordinates(hass: HomeAssistant, api) -> None:
    """A moving vehicle reports its state without a position."""
    await setup_real(hass, api)
    tracker = hass.states.get("device_tracker.enyaq_parking_position")
    assert tracker.attributes.get("latitude") is None
    assert tracker.attributes["parking_state"] == "IN_MOTION"
    assert hass.states.get("binary_sensor.enyaq_in_motion").state == "on"


async def test_missing_errors_key_is_tolerated(hass: HomeAssistant, api) -> None:
    """The live API omits `errors` entirely when there is nothing to report."""
    assert "errors" not in REAL
    entry = await setup_real(hass, api)
    assert entry.runtime_data.vehicles[VIN].data.errors == []
    assert hass.states.get("sensor.enyaq_data_errors").state == "0"


async def test_charging_profiles_are_exposed(hass: HomeAssistant, api) -> None:
    """All saved locations land on one sensor, details in its attributes."""
    await setup_real(hass, api)
    state = hass.states.get("sensor.enyaq_charging_profiles")
    assert state.state == "4"
    assert len(state.attributes["profiles"]) == 4
    assert state.attributes["profiles"][1]["timers"][1]["type"] == "ONE_OFF"
    # No saved location matched, so the current profile stays unknown.
    assert (
        hass.states.get("sensor.enyaq_current_charging_profile").state == STATE_UNKNOWN
    )


async def test_api_key_expiry_header_is_parsed(hass: HomeAssistant, api) -> None:
    """The live header carries milliseconds and a Z suffix."""
    entry = await setup_real(hass, api)
    expires_at = entry.runtime_data.api.key_expires_at
    assert expires_at == dt_util.parse_datetime("2027-02-26T11:02:57.912Z")
    assert (
        hass.states.get("binary_sensor.myskoda_publicapi_api_key_expiring").state
        == "off"
    )


async def test_rate_limit_headers_are_read(hass: HomeAssistant, api) -> None:
    """Quota tracking drives the backoff, so it has to parse the live headers."""
    entry = await setup_real(hass, api)
    rate_limit = entry.runtime_data.api.rate_limit
    assert (rate_limit.limit, rate_limit.remaining) == (20, 13)
    assert rate_limit.reset_in_seconds == 2487
    assert (
        hass.states.get("sensor.myskoda_publicapi_api_requests_remaining").state == "13"
    )


def test_millisecond_timestamps_are_parsed() -> None:
    """The vehicle mixes plain and millisecond ISO timestamps in one response."""
    with_ms = nested_get(REAL["vehicle"], "odometer.carCapturedTimestamp")
    without_ms = nested_get(REAL["vehicle"], "airConditioning.carCapturedTimestamp")
    assert "." in with_ms and "." not in without_ms
    assert parse_timestamp(with_ms) is not None
    assert parse_timestamp(without_ms) is not None


# The live API answers ?include=info with these four fields and nothing else.
REAL_INFO = json.loads((Path(__file__).parent / "fixture_real_info.json").read_text())


async def test_config_flow_accepts_the_real_info_response(
    hass: HomeAssistant, api
) -> None:
    """The VIN check asks for ?include=info to keep the request cheap.

    The live response is 273 bytes and carries no `errors` key, so the flow has
    to be happy with just vin, name, licensePlate and renderUrl.
    """
    assert set(REAL_INFO["vehicle"]) == {"vin", "name", "licensePlate", "renderUrl"}

    api.get(LIST_URL, status=HTTPStatus.NOT_FOUND, payload={"title": "Not Found"})
    api.get(vehicle_url(VIN), status=HTTPStatus.OK, payload=REAL_INFO)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "k"}
    )
    assert result["step_id"] == "vehicles"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_VINS: [VIN]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_unknown_vin_is_reported_as_unauthorized(
    hass: HomeAssistant, api
) -> None:
    """The live API answers 403 for any VIN the key does not cover.

    It does not distinguish a typo from a vehicle that exists but is not
    covered, so 403 is the case the setup dialog has to explain well.
    """
    api.get(LIST_URL, status=HTTPStatus.NOT_FOUND, payload={"title": "Not Found"})
    api.get(
        vehicle_url("TMBJB9NY5RF000000"),
        status=HTTPStatus.FORBIDDEN,
        payload={
            "detail": "The API key is not authorized to execute this operation.",
            "instance": "/api/v1/vehicles/TMBJB9NY5RF000000",
            "status": 403,
            "title": "Forbidden",
            "type": "https://public.api.connect.skoda-auto.cz/problems/api-key-not-authorized",
        },
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "k"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_VINS: ["TMBJB9NY5RF000000"]}
    )
    assert result["errors"] == {"base": "vehicle_not_authorized"}
