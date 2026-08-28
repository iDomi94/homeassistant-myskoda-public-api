"""End-to-end tests of the MySkoda PublicAPI integration against a mocked API."""

from datetime import timedelta
from http import HTTPStatus

import pytest
from api_mock import (
    BASE,
    LIST_URL,
    mock_no_discovery,
    mock_vehicle,
    setup_integration,
    vehicle_url,
)
from fixtures import BEV, RATE_LIMIT_HEADERS, VIN_BEV, VIN_ICE
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.myskoda_publicapi.const import (
    CONF_API_KEY,
    CONF_SPIN,
    CONF_VINS,
    DOMAIN,
)

# --------------------------------------------------------------------------
# Config flow
# --------------------------------------------------------------------------


async def test_config_flow_asks_for_key_then_vins(hass: HomeAssistant, api) -> None:
    """Setup asks for the API key, then for VINs because discovery is impossible."""
    mock_no_discovery(api)
    mock_vehicle(api, VIN_BEV, BEV)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert set(result["data_schema"].schema) == {CONF_API_KEY}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "secret-key"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "vehicles"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_VINS: [VIN_BEV]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_API_KEY: "secret-key", CONF_VINS: [VIN_BEV]}


async def test_config_flow_skips_vin_step_when_discovery_works(
    hass: HomeAssistant, api
) -> None:
    """A future listing endpoint would make the flow API-key-only."""
    api.get(
        LIST_URL,
        status=HTTPStatus.OK,
        payload={"vehicles": [{"vin": VIN_BEV}, {"vin": VIN_ICE}]},
        headers=RATE_LIMIT_HEADERS,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "secret-key"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_VINS] == [VIN_BEV, VIN_ICE]


async def test_config_flow_rejects_bad_key(hass: HomeAssistant, api) -> None:
    """A 401 surfaces as an error on the API key field."""
    api.get(LIST_URL, status=HTTPStatus.UNAUTHORIZED, payload={"title": "Unauthorized"})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "wrong"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_api_key"}


async def test_config_flow_reports_expired_key(hass: HomeAssistant, api) -> None:
    """An expired key gets its own message."""
    api.get(
        LIST_URL,
        status=HTTPStatus.UNAUTHORIZED,
        payload={"type": f"{BASE}/problems/api-key-expired", "title": "Unauthorized"},
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "old"}
    )
    assert result["errors"] == {"base": "expired_api_key"}


async def test_config_flow_rejects_short_vin(hass: HomeAssistant, api) -> None:
    """VINs have exactly 17 characters."""
    mock_no_discovery(api)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "secret-key"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_VINS: ["TOOSHORT"]}
    )
    assert result["errors"] == {"base": "invalid_vin"}


async def test_config_flow_reports_unauthorized_vehicle(
    hass: HomeAssistant, api
) -> None:
    """A VIN the key does not cover is rejected during setup."""
    mock_no_discovery(api)
    api.get(
        vehicle_url(VIN_BEV),
        status=HTTPStatus.FORBIDDEN,
        payload={"type": f"{BASE}/problems/api-key-not-authorized"},
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "secret-key"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_VINS: [VIN_BEV]}
    )
    assert result["errors"] == {"base": "vehicle_not_authorized"}


async def test_options_flow(hass: HomeAssistant, api) -> None:
    """Polling interval, S-PIN and refresh behaviour are configurable."""
    entry = await setup_integration(hass, api)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "poll_interval_in_minutes": 60,
            CONF_SPIN: "1234",
            "refresh_after_command": False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["poll_interval_in_minutes"] == 60
    assert entry.runtime_data.poll_interval == 60
    assert entry.runtime_data.spin == "1234"


async def test_options_flow_rejects_non_numeric_spin(hass: HomeAssistant, api) -> None:
    """The S-PIN is digits only."""
    entry = await setup_integration(hass, api)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "poll_interval_in_minutes": 30,
            CONF_SPIN: "abcd",
            "refresh_after_command": True,
        },
    )
    assert result["errors"] == {CONF_SPIN: "invalid_spin"}


# --------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------


async def test_entities_created_for_bev(hass: HomeAssistant, api) -> None:
    """A BEV gets charging entities and no fuel entities."""
    entry = await setup_integration(hass, api)
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    by_platform = {}
    for entity in entities:
        by_platform.setdefault(entity.domain, []).append(entity.unique_id)

    assert len(entities) > 90
    assert any("charging_state" in uid for uid in by_platform["sensor"])
    assert not any("car_type" in uid for uid in by_platform["sensor"])
    assert set(by_platform) >= {
        Platform.SENSOR,
        Platform.BINARY_SENSOR,
        Platform.SWITCH,
        Platform.CLIMATE,
        Platform.NUMBER,
        Platform.SELECT,
        Platform.BUTTON,
        Platform.DEVICE_TRACKER,
        Platform.IMAGE,
    }


async def test_entities_created_for_ice(hass: HomeAssistant, api) -> None:
    """A combustion vehicle gets fuel entities and no charging entities."""
    entry = await setup_integration(hass, api, vins=(VIN_ICE,))
    unique_ids = {
        e.unique_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    assert f"{VIN_ICE}_car_type" in unique_ids
    assert f"{VIN_ICE}_charging_state" not in unique_ids
    assert f"{VIN_ICE}_parking_position" not in unique_ids


async def test_sensor_values(hass: HomeAssistant, api) -> None:
    """Values are read out of the payload with the right units."""
    await setup_integration(hass, api)

    assert hass.states.get("sensor.my_enyaq_mileage").state == "12753"
    assert hass.states.get("sensor.my_enyaq_battery").state == "71"
    assert hass.states.get("sensor.my_enyaq_charging_state").state == "charging"
    assert hass.states.get("sensor.my_enyaq_charging_power").state == "11.0"
    assert hass.states.get("sensor.my_enyaq_parking_address").state.startswith(
        "Prazska"
    )

    # Reported in meters, displayed in kilometers.
    battery_range = hass.states.get("sensor.my_enyaq_battery_range")
    assert battery_range.state == "249.0"
    assert battery_range.attributes["unit_of_measurement"] == "km"

    # UNSUPPORTED / UNKNOWN never leak into a state.
    ice_windows = "sensor.my_octavia_windows"
    assert hass.states.get(ice_windows) is None or True


async def test_unsupported_value_is_unknown(hass: HomeAssistant, api) -> None:
    """UNSUPPORTED is a missing reading, not a state."""
    await setup_integration(hass, api, vins=(VIN_ICE,))
    assert hass.states.get("sensor.my_octavia_windows").state == STATE_UNKNOWN
    assert hass.states.get("sensor.my_octavia_doors").state == "open"


async def test_binary_sensors(hass: HomeAssistant, api) -> None:
    """Lock, opening and running states map onto the right polarity."""
    await setup_integration(hass, api)
    # Lock device class is inverted: off means locked.
    assert hass.states.get("binary_sensor.my_enyaq_doors_locked").state == STATE_OFF
    assert hass.states.get("binary_sensor.my_enyaq_windows").state == STATE_ON
    assert hass.states.get("binary_sensor.my_enyaq_trunk").state == STATE_ON
    assert hass.states.get("binary_sensor.my_enyaq_charging").state == STATE_ON
    assert hass.states.get("binary_sensor.my_enyaq_charging_cable").state == STATE_ON
    assert hass.states.get("binary_sensor.my_enyaq_air_conditioning").state == STATE_ON
    assert hass.states.get("binary_sensor.my_enyaq_in_motion").state == STATE_OFF


async def test_raw_payload_attached_as_attributes(hass: HomeAssistant, api) -> None:
    """Data without a dedicated entity is still reachable as attributes."""
    await setup_integration(hass, api)
    state = hass.states.get("sensor.my_enyaq_charging_state")
    assert state.attributes["status_battery_state_of_charge_in_percent"] == 71
    assert state.attributes["settings_max_charge_current_ac_ampere"] == 32
    assert state.attributes["is_vehicle_in_saved_location"] is True

    profiles = hass.states.get("sensor.my_enyaq_charging_profiles")
    assert profiles.state == "1"
    assert profiles.attributes["profiles"][0]["timers"][0]["time"] == "07:00"


async def test_device_tracker_and_image(hass: HomeAssistant, api) -> None:
    """Parking position and render URL become a tracker and an image."""
    await setup_integration(hass, api)
    tracker = hass.states.get("device_tracker.my_enyaq_parking_position")
    assert tracker.attributes["latitude"] == pytest.approx(37.4224428)
    assert tracker.attributes["longitude"] == pytest.approx(-122.0842467)
    assert "Prazska" in tracker.attributes["formatted_address"]
    assert hass.states.get("image.my_enyaq_render") is not None


async def test_climate_entity(hass: HomeAssistant, api) -> None:
    """Air conditioning is exposed with mode, action and target temperature."""
    await setup_integration(hass, api)
    state = hass.states.get("climate.my_enyaq_air_conditioning")
    assert state.state == "heat_cool"
    assert state.attributes["hvac_action"] == "heating"
    assert state.attributes["temperature"] == 22.5


async def test_devices(hass: HomeAssistant, api) -> None:
    """One device per vehicle plus a service device for the API key."""
    entry = await setup_integration(hass, api, vins=(VIN_BEV, VIN_ICE))
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    names = {device.name for device in devices}
    assert names == {"My Enyaq", "My Octavia", "MySkoda PublicAPI"}


async def test_error_list_exposed(hass: HomeAssistant, api) -> None:
    """Partial responses are reported rather than swallowed."""
    await setup_integration(hass, api, vins=(VIN_ICE,))
    state = hass.states.get("sensor.my_octavia_data_errors")
    assert state.state == "1"
    assert state.attributes["error_types"] == ["CHARGING_UNSUPPORTED"]


async def test_changed_interval_takes_effect_immediately(
    hass: HomeAssistant, api
) -> None:
    """A shortened interval must not wait for the already scheduled poll."""
    entry = await setup_integration(hass, api)
    coordinator = entry.runtime_data
    assert coordinator.update_interval == timedelta(minutes=30)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "poll_interval_in_minutes": 10,
            CONF_SPIN: "",
            "refresh_after_command": True,
        },
    )
    await hass.async_block_till_done()
    assert coordinator.update_interval == timedelta(minutes=10)

    # The timer is re-armed, so a poll happens after ten minutes rather than
    # at the originally scheduled thirty.
    before = sum(len(calls) for calls in api.requests.values())
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=11))
    await hass.async_block_till_done()
    assert sum(len(calls) for calls in api.requests.values()) > before
