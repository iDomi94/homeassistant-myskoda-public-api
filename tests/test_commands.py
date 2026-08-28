"""Tests of remote commands, error handling and the rate limit budget."""

import json
from datetime import timedelta
from http import HTTPStatus

import pytest
from api_mock import BASE, mock_vehicle, setup_integration, vehicle_url
from fixtures import BEV, RATE_LIMIT_HEADERS, VIN_BEV, VIN_ICE
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.myskoda_b2c.const import (
    CONF_REFRESH_AFTER_COMMAND,
    CONF_SPIN,
    DOMAIN,
    MANUAL_REFRESH_COOLDOWN,
    REFRESH_AFTER_COMMAND_DELAY,
)


def command_url(vin: str, path: str) -> str:
    """URL of a remote command."""
    return f"{BASE}/api/v1/vehicles/{vin}/{path}"


def sent_body(api, vin: str, path: str) -> dict:
    """Return the JSON body of the recorded request."""
    for key, calls in api.requests.items():
        if key[0] == "POST" and str(key[1]).endswith(f"/{vin}/{path}"):
            return calls[-1].kwargs.get("json") or {}
    raise AssertionError(f"{path} was not called")


def request_count(api) -> int:
    """Total number of requests recorded so far.

    ``aioresponses.clear()`` resets the registered responses but keeps the
    history, so callers compare against an earlier snapshot.
    """
    return sum(len(calls) for calls in api.requests.values())


def was_called(api, vin: str, path: str) -> bool:
    """Whether a command endpoint was called."""
    return any(
        key[0] == "POST" and str(key[1]).endswith(f"/{vin}/{path}")
        for key in api.requests
    )


# --------------------------------------------------------------------------
# Switches and climate
# --------------------------------------------------------------------------


async def test_switch_starts_and_stops_charging(hass: HomeAssistant, api) -> None:
    """The charging switch maps onto the start and stop endpoints."""
    await setup_integration(hass, api)
    api.post(command_url(VIN_BEV, "charging/start"), status=HTTPStatus.ACCEPTED)
    api.post(command_url(VIN_BEV, "charging/stop"), status=HTTPStatus.ACCEPTED)

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: "switch.my_enyaq_charging"}, blocking=True
    )
    await hass.services.async_call(
        "switch",
        "turn_off",
        {ATTR_ENTITY_ID: "switch.my_enyaq_charging"},
        blocking=True,
    )
    assert was_called(api, VIN_BEV, "charging/start")
    assert was_called(api, VIN_BEV, "charging/stop")


async def test_air_conditioning_sends_target_temperature(
    hass: HomeAssistant, api
) -> None:
    """Starting air conditioning carries the locally held parameters."""
    await setup_integration(hass, api)
    api.post(command_url(VIN_BEV, "air-conditioning/start"), status=HTTPStatus.ACCEPTED)

    await hass.services.async_call(
        "switch",
        "turn_on",
        {ATTR_ENTITY_ID: "switch.my_enyaq_air_conditioning"},
        blocking=True,
    )
    body = sent_body(api, VIN_BEV, "air-conditioning/start")
    # The vehicle reports Celsius and "without external power", so both are echoed.
    assert body["targetTemperature"]["unit"] == "CELSIUS"
    assert body["airConditioningWithoutExternalPower"] is True


async def test_climate_set_temperature_restarts_when_running(
    hass: HomeAssistant, api
) -> None:
    """Changing the target while running re-issues the start command."""
    await setup_integration(hass, api)
    api.post(
        command_url(VIN_BEV, "air-conditioning/start"),
        status=HTTPStatus.ACCEPTED,
        repeat=True,
    )

    await hass.services.async_call(
        "climate",
        "set_temperature",
        {ATTR_ENTITY_ID: "climate.my_enyaq_air_conditioning", "temperature": 19.5},
        blocking=True,
    )
    assert (
        sent_body(api, VIN_BEV, "air-conditioning/start")["targetTemperature"]["value"]
        == 19.5
    )


async def test_auxiliary_heating_requires_spin(hass: HomeAssistant, api) -> None:
    """Without an S-PIN the command is refused with a helpful message."""
    await setup_integration(hass, api)
    with pytest.raises(HomeAssistantError, match="S-PIN"):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {ATTR_ENTITY_ID: "switch.my_enyaq_auxiliary_heating"},
            blocking=True,
        )
    assert not was_called(api, VIN_BEV, "auxiliary-heating/start")


async def test_auxiliary_heating_uses_spin_and_duration(
    hass: HomeAssistant, api
) -> None:
    """The S-PIN from the options and the duration number are sent along."""
    await setup_integration(hass, api, options={CONF_SPIN: "1234"})
    api.post(
        command_url(VIN_BEV, "auxiliary-heating/start"), status=HTTPStatus.ACCEPTED
    )

    await hass.services.async_call(
        "number",
        "set_value",
        {
            ATTR_ENTITY_ID: "number.my_enyaq_auxiliary_heating_duration",
            "value": 35,
        },
        blocking=True,
    )
    await hass.services.async_call(
        "switch",
        "turn_on",
        {ATTR_ENTITY_ID: "switch.my_enyaq_auxiliary_heating"},
        blocking=True,
    )
    body = sent_body(api, VIN_BEV, "auxiliary-heating/start")
    assert body["spin"] == "1234"
    assert body["durationInSeconds"] == 35 * 60
    assert body["startMode"] == "HEATING"


async def test_auxiliary_heating_preset_selects_start_mode(
    hass: HomeAssistant, api
) -> None:
    """The climate preset chooses between heating and ventilation."""
    await setup_integration(hass, api, options={CONF_SPIN: "1234"})
    api.post(
        command_url(VIN_BEV, "auxiliary-heating/start"),
        status=HTTPStatus.ACCEPTED,
        repeat=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {
            ATTR_ENTITY_ID: "select.my_enyaq_auxiliary_heating_start_mode",
            "option": "ventilation",
        },
        blocking=True,
    )
    await hass.services.async_call(
        "climate",
        "turn_on",
        {ATTR_ENTITY_ID: "climate.my_enyaq_auxiliary_heating"},
        blocking=True,
    )
    assert (
        sent_body(api, VIN_BEV, "auxiliary-heating/start")["startMode"] == "VENTILATION"
    )


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------


async def test_service_targets_single_vin(hass: HomeAssistant, api) -> None:
    """A VIN in the call data limits the action to that vehicle."""
    await setup_integration(hass, api, vins=(VIN_BEV, VIN_ICE))
    api.post(
        command_url(VIN_BEV, "active-ventilation/start"), status=HTTPStatus.ACCEPTED
    )
    api.post(
        command_url(VIN_ICE, "active-ventilation/start"), status=HTTPStatus.ACCEPTED
    )

    await hass.services.async_call(
        DOMAIN, "start_active_ventilation", {"vin": VIN_BEV}, blocking=True
    )
    assert was_called(api, VIN_BEV, "active-ventilation/start")
    assert not was_called(api, VIN_ICE, "active-ventilation/start")


async def test_service_without_target_hits_all_vehicles(
    hass: HomeAssistant, api
) -> None:
    """Without a target the action applies to every configured vehicle."""
    await setup_integration(hass, api, vins=(VIN_BEV, VIN_ICE))
    api.post(command_url(VIN_BEV, "air-conditioning/stop"), status=HTTPStatus.ACCEPTED)
    api.post(command_url(VIN_ICE, "air-conditioning/stop"), status=HTTPStatus.ACCEPTED)

    await hass.services.async_call(DOMAIN, "stop_air_conditioning", {}, blocking=True)
    assert was_called(api, VIN_BEV, "air-conditioning/stop")
    assert was_called(api, VIN_ICE, "air-conditioning/stop")


async def test_service_spin_overrides_options(hass: HomeAssistant, api) -> None:
    """A call may carry its own S-PIN."""
    await setup_integration(hass, api, options={CONF_SPIN: "1111"})
    api.post(
        command_url(VIN_BEV, "auxiliary-heating/start"), status=HTTPStatus.ACCEPTED
    )

    await hass.services.async_call(
        DOMAIN,
        "start_auxiliary_heating",
        {
            "vin": VIN_BEV,
            "spin": "9999",
            "temperature": 24,
            "duration": 10,
            "start_mode": "ventilation",
        },
        blocking=True,
    )
    body = sent_body(api, VIN_BEV, "auxiliary-heating/start")
    assert body["spin"] == "9999"
    assert body["targetTemperature"]["value"] == 24
    assert body["durationInSeconds"] == 600
    assert body["startMode"] == "VENTILATION"


async def test_all_services_registered(hass: HomeAssistant, api) -> None:
    """Every documented operation is reachable as an action."""
    await setup_integration(hass, api)
    for service in (
        "refresh",
        "start_charging",
        "stop_charging",
        "start_air_conditioning",
        "stop_air_conditioning",
        "start_auxiliary_heating",
        "stop_auxiliary_heating",
        "start_active_ventilation",
        "stop_active_ventilation",
    ):
        assert hass.services.has_service(DOMAIN, service), service


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------


async def test_operation_not_supported_is_reported(hass: HomeAssistant, api) -> None:
    """A 422 explains that retrying will not help."""
    await setup_integration(hass, api)
    api.post(
        command_url(VIN_BEV, "charging/start"),
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
        payload={
            "type": f"{BASE}/problems/operation-not-supported",
            "detail": "Vehicle does not support charging.",
        },
    )
    with pytest.raises(HomeAssistantError, match="not possible"):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {ATTR_ENTITY_ID: "switch.my_enyaq_charging"},
            blocking=True,
        )


async def test_rate_limited_command_mentions_the_quota(
    hass: HomeAssistant, api
) -> None:
    """A 429 tells the user about the hourly limit."""
    await setup_integration(hass, api)
    api.post(
        command_url(VIN_BEV, "charging/stop"),
        status=HTTPStatus.TOO_MANY_REQUESTS,
        payload={"type": f"{BASE}/problems/rate-limit-exceeded"},
        headers={"Retry-After": "30", **RATE_LIMIT_HEADERS},
    )
    with pytest.raises(HomeAssistantError, match="requests per hour"):
        await hass.services.async_call(
            "switch",
            "turn_off",
            {ATTR_ENTITY_ID: "switch.my_enyaq_charging"},
            blocking=True,
        )


async def test_expired_key_starts_reauth(hass: HomeAssistant, api) -> None:
    """A 401 during polling triggers the reauth flow."""
    await setup_integration(hass, api)
    api.clear()
    api.get(
        vehicle_url(VIN_BEV),
        status=HTTPStatus.UNAUTHORIZED,
        payload={"type": f"{BASE}/problems/api-key-expired"},
        repeat=True,
    )
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=31))
    await hass.async_block_till_done()

    flows = [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["handler"] == DOMAIN and flow["context"]["source"] == "reauth"
    ]
    assert flows


async def test_rate_limit_pauses_polling(hass: HomeAssistant, api) -> None:
    """After a 429 the coordinator waits instead of hammering the API."""
    entry = await setup_integration(hass, api)
    coordinator = entry.runtime_data
    api.clear()
    api.get(
        vehicle_url(VIN_BEV),
        status=HTTPStatus.TOO_MANY_REQUESTS,
        payload={"type": f"{BASE}/problems/rate-limit-exceeded"},
        headers={"Retry-After": "3600"},
    )
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=31))
    await hass.async_block_till_done()
    assert coordinator._backoff_until is not None

    # The next scheduled poll is skipped, so no further request is made and the
    # last known data is kept.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=62))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.my_enyaq_mileage").state == "12753"


async def test_rate_limit_sensors(hass: HomeAssistant, api) -> None:
    """The quota headers become diagnostic entities."""
    await setup_integration(hass, api)
    assert (
        hass.states.get("sensor.myskoda_public_api_api_requests_remaining").state
        == "18"
    )
    assert hass.states.get("sensor.myskoda_public_api_api_request_limit").state == "20"
    assert (
        hass.states.get("binary_sensor.myskoda_public_api_rate_limit_reached").state
        == "off"
    )


async def test_refresh_after_command_is_scheduled(hass: HomeAssistant, api) -> None:
    """A command schedules one follow-up poll."""
    await setup_integration(hass, api)

    updated = json.loads(json.dumps(BEV))
    updated["vehicle"]["odometer"]["mileageInKm"] = 12800
    api.clear()
    api.post(command_url(VIN_BEV, "charging/start"), status=HTTPStatus.ACCEPTED)
    mock_vehicle(api, VIN_BEV, updated)

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: "switch.my_enyaq_charging"}, blocking=True
    )
    # The scheduled callback fires first, then the coordinator's own debouncer.
    for offset in (REFRESH_AFTER_COMMAND_DELAY + 5, REFRESH_AFTER_COMMAND_DELAY + 30):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=offset))
        await hass.async_block_till_done()
    assert hass.states.get("sensor.my_enyaq_mileage").state == "12800"


async def test_refresh_after_command_can_be_disabled(hass: HomeAssistant, api) -> None:
    """Turning the option off stops the extra poll."""
    await setup_integration(hass, api, options={CONF_REFRESH_AFTER_COMMAND: False})
    api.post(command_url(VIN_BEV, "charging/start"), status=HTTPStatus.ACCEPTED)
    api.clear()
    api.post(command_url(VIN_BEV, "charging/start"), status=HTTPStatus.ACCEPTED)

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: "switch.my_enyaq_charging"}, blocking=True
    )
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=REFRESH_AFTER_COMMAND_DELAY + 5)
    )
    await hass.async_block_till_done()
    # No GET was mocked, so a poll would have raised; the state is unchanged.
    assert hass.states.get("sensor.my_enyaq_mileage").state == "12753"


async def test_unload_entry(hass: HomeAssistant, api) -> None:
    """The entry unloads cleanly."""
    entry = await setup_integration(hass, api)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.my_enyaq_mileage").state == STATE_UNAVAILABLE


async def test_manual_refresh_is_throttled(hass: HomeAssistant, api) -> None:
    """Spamming the refresh action must not burn the hourly quota."""
    entry = await setup_integration(hass, api)
    coordinator = entry.runtime_data
    api.clear()
    mock_vehicle(api, VIN_BEV, BEV)

    before = request_count(api)

    for _ in range(10):
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    await hass.async_block_till_done()

    # The first request goes through immediately, the rest are debounced away.
    assert request_count(api) - before == 1

    # After the cooldown a further refresh is allowed again.
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=MANUAL_REFRESH_COOLDOWN + 5)
    )
    await hass.async_block_till_done()
    assert request_count(api) - before > 1
    assert coordinator.last_update_success


async def test_poll_interval_can_be_set_from_an_automation(
    hass: HomeAssistant, api
) -> None:
    """The interval is an entity, so number.set_value can change it."""
    entry = await setup_integration(hass, api)
    coordinator = entry.runtime_data
    entity_id = "number.myskoda_public_api_polling_interval"
    assert hass.states.get(entity_id).state == "30"

    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: entity_id, "value": 5},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert coordinator.update_interval == timedelta(minutes=5)
    assert hass.states.get(entity_id).state == "5"
    # The change is stored on the entry, so it survives a restart.
    assert entry.options["poll_interval_in_minutes"] == 5


async def test_shortening_rearms_the_timer_lengthening_is_free(
    hass: HomeAssistant, api
) -> None:
    """Only a shortened interval spends a request on re-arming the timer."""
    entry = await setup_integration(hass, api)
    entity_id = "number.myskoda_public_api_polling_interval"

    before = request_count(api)
    await hass.services.async_call(
        "number", "set_value", {ATTR_ENTITY_ID: entity_id, "value": 5}, blocking=True
    )
    await hass.async_block_till_done()
    assert request_count(api) - before == 1

    # Going back up re-arms itself at the next poll, which is already due soon.
    before = request_count(api)
    await hass.services.async_call(
        "number", "set_value", {ATTR_ENTITY_ID: entity_id, "value": 60}, blocking=True
    )
    await hass.async_block_till_done()
    assert request_count(api) - before == 0
    assert entry.runtime_data.update_interval == timedelta(minutes=60)
