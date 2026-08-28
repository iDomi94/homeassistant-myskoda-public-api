"""Sensors for the MySkoda PublicAPI integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfLength,
    UnitOfPower,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import MySkodaCoordinator, MySkodaPublicApiConfigEntry, VehicleState
from .entity import (
    MySkodaEntityDescriptionMixin,
    MySkodaHubEntity,
    MySkodaVehicleEntity,
    entity_exists,
)
from .utils import clean_value, nested_get, parse_timestamp

_LOGGER = logging.getLogger(__name__)

TEMPERATURE_UNITS = {
    "CELSIUS": UnitOfTemperature.CELSIUS,
    "FAHRENHEIT": UnitOfTemperature.FAHRENHEIT,
}


@dataclass(frozen=True, kw_only=True)
class MySkodaSensorDescription(SensorEntityDescription, MySkodaEntityDescriptionMixin):
    """Describes a MyŠkoda sensor."""

    value_fn: Callable[[VehicleState], Any]
    unit_fn: Callable[[VehicleState], str | None] | None = None


def _path(path: str) -> Callable[[VehicleState], Any]:
    """Build a value function reading a dotted path from the payload."""

    def value(state: VehicleState) -> Any:
        if state.data is None:
            return None
        return clean_value(nested_get(state.data.raw, path))

    return value


def _timestamp(path: str) -> Callable[[VehicleState], Any]:
    """Build a value function parsing a dotted path as a timestamp."""

    def value(state: VehicleState) -> Any:
        if state.data is None:
            return None
        return parse_timestamp(nested_get(state.data.raw, path))

    return value


def _temperature_unit(path: str) -> Callable[[VehicleState], str | None]:
    """Read the unit the vehicle reports alongside a temperature."""

    def unit(state: VehicleState) -> str | None:
        if state.data is None:
            return UnitOfTemperature.CELSIUS
        raw = nested_get(state.data.raw, path)
        return TEMPERATURE_UNITS.get(str(raw), UnitOfTemperature.CELSIUS)

    return unit


# Closed vocabularies. Values outside them are surfaced as ``raw_value``
# attributes instead of breaking the enum device class -- the API documents that
# new values may be added over time.
DOORS_LOCKED_OPTIONS = ["YES", "NO", "OPENED", "TRUNK_OPENED"]
LOCKED_OPTIONS = ["YES", "NO"]
OPEN_CLOSED_OPTIONS = ["OPEN", "CLOSED"]
ON_OFF_OPTIONS = ["ON", "OFF"]
RELIABLE_LOCK_OPTIONS = ["LOCKED", "UNLOCKED"]
CHARGING_STATE_OPTIONS = [
    "CONNECT_CABLE",
    "CHARGING",
    "CONSERVING",
    "READY_FOR_CHARGING",
    "DISCHARGING",
    "CHARGING_INTERRUPTED",
]
CHARGE_TYPE_OPTIONS = ["AC", "DC", "OFF"]
CAR_TYPE_OPTIONS = ["HYBRID", "GASOLINE", "DIESEL", "CNG", "LPG"]
ENGINE_TYPE_OPTIONS = ["ELECTRIC", "GASOLINE", "DIESEL", "CNG", "LPG"]
AIR_CONDITIONING_STATE_OPTIONS = [
    "OFF",
    "COOLING",
    "HEATING",
    "HEATING_AUXILIARY",
    "VENTILATION",
    "COMPLETED",
]
AUXILIARY_HEATING_STATE_OPTIONS = [
    "OFF",
    "PREHEATING",
    "HEATING_AUXILIARY",
    "VENTILATION",
]
ACTIVE_VENTILATION_STATE_OPTIONS = ["OFF", "PREHEATING", "VENTILATION"]
START_MODE_OPTIONS = ["HEATING", "VENTILATION"]
PARKING_STATE_OPTIONS = ["IN_MOTION", "PARKED"]
CHARGE_MODE_OPTIONS = [
    "MANUAL",
    "TIMER",
    "TIMER_CHARGING_WITH_CLIMATISATION",
    "PREFERRED_CHARGING_TIMES",
    "ONLY_OWN_CURRENT",
    "IMMEDIATE_DISCHARGING",
    "HOME_STORAGE_CHARGING",
]
CARE_MODE_OPTIONS = ["ACTIVATED", "DEACTIVATED"]
PLUG_UNLOCK_OPTIONS = ["PERMANENT", "OFF"]
MAX_CHARGE_CURRENT_OPTIONS = ["REDUCED", "MAXIMUM"]


def _enum(key: str, options: list[str], **kwargs: Any) -> MySkodaSensorDescription:
    """Shorthand for an enum sensor over a documented vocabulary."""
    return MySkodaSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENUM,
        options=options,
        **kwargs,
    )


VEHICLE_SENSORS: tuple[MySkodaSensorDescription, ...] = (
    # --- Identification --------------------------------------------------
    MySkodaSensorDescription(
        key="license_plate",
        translation_key="license_plate",
        part=None,
        expose_raw=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_path("licensePlate"),
    ),
    MySkodaSensorDescription(
        key="vin",
        translation_key="vin",
        part=None,
        expose_raw=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda state: state.vin,
    ),
    # --- Odometer --------------------------------------------------------
    MySkodaSensorDescription(
        key="mileage",
        translation_key="mileage",
        part="odometer",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_fn=_path("odometer.mileageInKm"),
    ),
    MySkodaSensorDescription(
        key="odometer_captured_at",
        translation_key="odometer_captured_at",
        part="odometer",
        expose_raw=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_timestamp("odometer.carCapturedTimestamp"),
    ),
    # --- Fuel status -----------------------------------------------------
    _enum(
        "car_type",
        CAR_TYPE_OPTIONS,
        part="fuelStatus",
        value_fn=_path("fuelStatus.carType"),
    ),
    MySkodaSensorDescription(
        key="total_range",
        translation_key="total_range",
        part="fuelStatus",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_path("fuelStatus.totalRangeInKm"),
    ),
    MySkodaSensorDescription(
        key="adblue_range",
        translation_key="adblue_range",
        part="fuelStatus",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_path("fuelStatus.adBlueRange"),
    ),
    _enum(
        "primary_engine_type",
        ENGINE_TYPE_OPTIONS,
        part="fuelStatus",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_path("fuelStatus.primaryEngineRange.engineType"),
    ),
    MySkodaSensorDescription(
        key="primary_engine_range",
        translation_key="primary_engine_range",
        part="fuelStatus",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_path("fuelStatus.primaryEngineRange.remainingRangeInKm"),
    ),
    MySkodaSensorDescription(
        key="primary_engine_fuel_level",
        translation_key="primary_engine_fuel_level",
        part="fuelStatus",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:gas-station",
        value_fn=_path("fuelStatus.primaryEngineRange.currentFuelLevelInPercent"),
    ),
    MySkodaSensorDescription(
        key="primary_engine_soc",
        translation_key="primary_engine_soc",
        part="fuelStatus",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_path("fuelStatus.primaryEngineRange.currentSoCInPercent"),
    ),
    _enum(
        "secondary_engine_type",
        ENGINE_TYPE_OPTIONS,
        part="fuelStatus",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_path("fuelStatus.secondaryEngineRange.engineType"),
    ),
    MySkodaSensorDescription(
        key="secondary_engine_range",
        translation_key="secondary_engine_range",
        part="fuelStatus",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_path("fuelStatus.secondaryEngineRange.remainingRangeInKm"),
    ),
    MySkodaSensorDescription(
        key="secondary_engine_fuel_level",
        translation_key="secondary_engine_fuel_level",
        part="fuelStatus",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:gas-station",
        value_fn=_path("fuelStatus.secondaryEngineRange.currentFuelLevelInPercent"),
    ),
    MySkodaSensorDescription(
        key="secondary_engine_soc",
        translation_key="secondary_engine_soc",
        part="fuelStatus",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_path("fuelStatus.secondaryEngineRange.currentSoCInPercent"),
    ),
    MySkodaSensorDescription(
        key="fuel_status_captured_at",
        translation_key="fuel_status_captured_at",
        part="fuelStatus",
        expose_raw=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_timestamp("fuelStatus.carCapturedTimestamp"),
    ),
    # --- Charging --------------------------------------------------------
    _enum(
        "charging_state",
        CHARGING_STATE_OPTIONS,
        part="charging",
        value_fn=_path("charging.status.state"),
    ),
    _enum(
        "charge_type",
        CHARGE_TYPE_OPTIONS,
        part="charging",
        value_fn=_path("charging.status.chargeType"),
    ),
    MySkodaSensorDescription(
        key="charging_power",
        translation_key="charging_power",
        part="charging",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_path("charging.status.chargePowerInKw"),
    ),
    MySkodaSensorDescription(
        key="charging_rate",
        translation_key="charging_rate",
        part="charging",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_path("charging.status.chargingRateInKilometersPerHour"),
    ),
    MySkodaSensorDescription(
        key="remaining_charging_time",
        translation_key="remaining_charging_time",
        part="charging",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_path("charging.status.remainingTimeToFullyChargedInMinutes"),
    ),
    MySkodaSensorDescription(
        key="fully_charged_at",
        translation_key="fully_charged_at",
        part="charging",
        expose_raw=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_timestamp("charging.status.fullyChargedAt"),
    ),
    MySkodaSensorDescription(
        key="battery_soc",
        translation_key="battery_soc",
        part="charging",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_path("charging.status.battery.stateOfChargeInPercent"),
    ),
    MySkodaSensorDescription(
        key="battery_range",
        translation_key="battery_range",
        part="charging",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        suggested_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_path("charging.status.battery.remainingCruisingRangeInMeters"),
    ),
    MySkodaSensorDescription(
        key="target_soc",
        translation_key="target_soc",
        part="charging",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:battery-charging-80",
        value_fn=_path("charging.settings.targetStateOfChargeInPercent"),
    ),
    MySkodaSensorDescription(
        key="battery_care_target_soc",
        translation_key="battery_care_target_soc",
        part="charging",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:battery-heart-variant",
        value_fn=_path("charging.settings.batteryCareModeTargetValueInPercent"),
    ),
    _enum(
        "preferred_charge_mode",
        CHARGE_MODE_OPTIONS,
        part="charging",
        entity_category=EntityCategory.DIAGNOSTIC,
        attrs_fn=lambda state: {
            "available_charge_modes": nested_get(
                state.data.raw if state.data else {},
                "charging.settings.availableChargeModes",
            )
        },
        value_fn=_path("charging.settings.preferredChargeMode"),
    ),
    _enum(
        "charging_care_mode",
        CARE_MODE_OPTIONS,
        part="charging",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_path("charging.settings.chargingCareMode"),
    ),
    _enum(
        "auto_unlock_plug",
        PLUG_UNLOCK_OPTIONS,
        part="charging",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_path("charging.settings.autoUnlockPlugWhenCharged"),
    ),
    _enum(
        "max_charge_current",
        MAX_CHARGE_CURRENT_OPTIONS,
        part="charging",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_path("charging.settings.maxChargeCurrentAc"),
    ),
    MySkodaSensorDescription(
        key="max_charge_current_ampere",
        translation_key="max_charge_current_ampere",
        part="charging",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_path("charging.settings.maxChargeCurrentAcAmpere"),
    ),
    MySkodaSensorDescription(
        key="charging_captured_at",
        translation_key="charging_captured_at",
        part="charging",
        expose_raw=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_timestamp("charging.carCapturedTimestamp"),
    ),
    # --- Air conditioning ------------------------------------------------
    _enum(
        "air_conditioning_state",
        AIR_CONDITIONING_STATE_OPTIONS,
        part="airConditioning",
        value_fn=_path("airConditioning.state"),
    ),
    MySkodaSensorDescription(
        key="air_conditioning_target_temperature",
        translation_key="air_conditioning_target_temperature",
        part="airConditioning",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_path("airConditioning.targetTemperature.value"),
        unit_fn=_temperature_unit("airConditioning.targetTemperature.unit"),
    ),
    MySkodaSensorDescription(
        key="air_conditioning_target_reached_at",
        translation_key="air_conditioning_target_reached_at",
        part="airConditioning",
        expose_raw=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_timestamp("airConditioning.estimatedReachOfTargetTemperatureAt"),
    ),
    _enum(
        "window_heating_front",
        ON_OFF_OPTIONS,
        part="airConditioning",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_path("airConditioning.windowHeating.front"),
    ),
    _enum(
        "window_heating_rear",
        ON_OFF_OPTIONS,
        part="airConditioning",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_path("airConditioning.windowHeating.rear"),
    ),
    MySkodaSensorDescription(
        key="air_conditioning_captured_at",
        translation_key="air_conditioning_captured_at",
        part="airConditioning",
        expose_raw=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_timestamp("airConditioning.carCapturedTimestamp"),
    ),
    # --- Auxiliary heating -----------------------------------------------
    _enum(
        "auxiliary_heating_state",
        AUXILIARY_HEATING_STATE_OPTIONS,
        part="auxiliaryHeating",
        value_fn=_path("auxiliaryHeating.state"),
    ),
    _enum(
        "auxiliary_heating_start_mode",
        START_MODE_OPTIONS,
        part="auxiliaryHeating",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_path("auxiliaryHeating.startMode"),
    ),
    MySkodaSensorDescription(
        key="auxiliary_heating_duration",
        translation_key="auxiliary_heating_duration",
        part="auxiliaryHeating",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=_path("auxiliaryHeating.durationInSeconds"),
    ),
    MySkodaSensorDescription(
        key="auxiliary_heating_target_temperature",
        translation_key="auxiliary_heating_target_temperature",
        part="auxiliaryHeating",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_path("auxiliaryHeating.targetTemperature.value"),
        unit_fn=_temperature_unit("auxiliaryHeating.targetTemperature.unit"),
    ),
    MySkodaSensorDescription(
        key="auxiliary_heating_target_reached_at",
        translation_key="auxiliary_heating_target_reached_at",
        part="auxiliaryHeating",
        expose_raw=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_timestamp("auxiliaryHeating.estimatedReachOfTargetTemperatureAt"),
    ),
    MySkodaSensorDescription(
        key="auxiliary_heating_captured_at",
        translation_key="auxiliary_heating_captured_at",
        part="auxiliaryHeating",
        expose_raw=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_timestamp("auxiliaryHeating.carCapturedTimestamp"),
    ),
    # --- Active ventilation ----------------------------------------------
    _enum(
        "active_ventilation_state",
        ACTIVE_VENTILATION_STATE_OPTIONS,
        part="activeVentilation",
        value_fn=_path("activeVentilation.state"),
    ),
    MySkodaSensorDescription(
        key="active_ventilation_duration",
        translation_key="active_ventilation_duration",
        part="activeVentilation",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=_path("activeVentilation.durationInSeconds"),
    ),
    MySkodaSensorDescription(
        key="active_ventilation_captured_at",
        translation_key="active_ventilation_captured_at",
        part="activeVentilation",
        expose_raw=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_timestamp("activeVentilation.carCapturedTimestamp"),
    ),
    # --- Vehicle status --------------------------------------------------
    _enum(
        "doors_locked_state",
        DOORS_LOCKED_OPTIONS,
        part="status",
        value_fn=_path("status.overall.doorsLocked"),
    ),
    _enum(
        "locked_state",
        LOCKED_OPTIONS,
        part="status",
        value_fn=_path("status.overall.locked"),
    ),
    _enum(
        "doors_state",
        OPEN_CLOSED_OPTIONS,
        part="status",
        value_fn=_path("status.overall.doors"),
    ),
    _enum(
        "windows_state",
        OPEN_CLOSED_OPTIONS,
        part="status",
        value_fn=_path("status.overall.windows"),
    ),
    _enum(
        "lights_state",
        ON_OFF_OPTIONS,
        part="status",
        value_fn=_path("status.overall.lights"),
    ),
    _enum(
        "reliable_lock_status",
        RELIABLE_LOCK_OPTIONS,
        part="status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_path("status.overall.reliableLockStatus"),
    ),
    _enum(
        "sunroof_state",
        OPEN_CLOSED_OPTIONS,
        part="status",
        value_fn=_path("status.detail.sunroof"),
    ),
    _enum(
        "trunk_state",
        OPEN_CLOSED_OPTIONS,
        part="status",
        value_fn=_path("status.detail.trunk"),
    ),
    _enum(
        "bonnet_state",
        OPEN_CLOSED_OPTIONS,
        part="status",
        value_fn=_path("status.detail.bonnet"),
    ),
    MySkodaSensorDescription(
        key="status_captured_at",
        translation_key="status_captured_at",
        part="status",
        expose_raw=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_timestamp("status.carCapturedTimestamp"),
    ),
    # --- Parking position ------------------------------------------------
    _enum(
        "parking_state",
        PARKING_STATE_OPTIONS,
        part="parkingPosition",
        value_fn=_path("parkingPosition.state"),
    ),
    MySkodaSensorDescription(
        key="parking_address",
        translation_key="parking_address",
        part="parkingPosition",
        icon="mdi:map-marker",
        value_fn=_path("parkingPosition.formattedAddress"),
    ),
    # --- Charging profiles -----------------------------------------------
    MySkodaSensorDescription(
        key="charging_profiles",
        translation_key="charging_profiles",
        part="chargingProfiles",
        expose_raw=False,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-multiple",
        entity_category=EntityCategory.DIAGNOSTIC,
        attrs_fn=lambda state: {
            "profiles": nested_get(
                state.data.raw if state.data else {}, "chargingProfiles.profiles"
            )
        },
        value_fn=lambda state: len(
            nested_get(
                state.data.raw if state.data else {}, "chargingProfiles.profiles"
            )
            or []
        ),
    ),
    MySkodaSensorDescription(
        key="current_charging_profile",
        translation_key="current_charging_profile",
        part="chargingProfiles",
        expose_raw=False,
        icon="mdi:map-marker-check",
        attrs_fn=lambda state: nested_get(
            state.data.raw if state.data else {},
            "chargingProfiles.currentVehiclePositionProfile",
        ),
        value_fn=_path("chargingProfiles.currentVehiclePositionProfile.name"),
    ),
    MySkodaSensorDescription(
        key="current_charging_profile_target_soc",
        translation_key="current_charging_profile_target_soc",
        part="chargingProfiles",
        expose_raw=False,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_path(
            "chargingProfiles.currentVehiclePositionProfile.targetStateOfChargeInPercent"
        ),
    ),
    MySkodaSensorDescription(
        key="next_charging_time",
        translation_key="next_charging_time",
        part="chargingProfiles",
        expose_raw=False,
        icon="mdi:clock-outline",
        value_fn=_path(
            "chargingProfiles.currentVehiclePositionProfile.nextChargingTime"
        ),
    ),
    MySkodaSensorDescription(
        key="charging_profiles_captured_at",
        translation_key="charging_profiles_captured_at",
        part="chargingProfiles",
        expose_raw=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_timestamp("chargingProfiles.carCapturedTimestamp"),
    ),
    # --- Per-vehicle diagnostics ------------------------------------------
    MySkodaSensorDescription(
        key="last_updated",
        translation_key="last_updated",
        part=None,
        expose_raw=False,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.data.fetched_at if state.data else None,
    ),
    MySkodaSensorDescription(
        key="data_errors",
        translation_key="data_errors",
        part=None,
        expose_raw=False,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-circle-outline",
        attrs_fn=lambda state: {
            "errors": state.data.errors if state.data else [],
            "error_types": state.data.error_types if state.data else [],
            "last_error": state.last_error,
        },
        value_fn=lambda state: len(state.data.errors) if state.data else None,
    ),
)


@dataclass(frozen=True, kw_only=True)
class MySkodaHubSensorDescription(SensorEntityDescription):
    """Describes a sensor about the API connection itself."""

    value_fn: Callable[[MySkodaCoordinator], Any]
    attrs_fn: Callable[[MySkodaCoordinator], dict[str, Any] | None] | None = None


HUB_SENSORS: tuple[MySkodaHubSensorDescription, ...] = (
    MySkodaHubSensorDescription(
        key="rate_limit_remaining",
        translation_key="rate_limit_remaining",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:speedometer-slow",
        value_fn=lambda c: c.api.rate_limit.remaining,
        attrs_fn=lambda c: c.diagnostic_attributes,
    ),
    MySkodaHubSensorDescription(
        key="rate_limit",
        translation_key="rate_limit",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:speedometer",
        value_fn=lambda c: c.api.rate_limit.limit,
    ),
    MySkodaHubSensorDescription(
        key="rate_limit_resets_at",
        translation_key="rate_limit_resets_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.api.rate_limit.resets_at,
    ),
    MySkodaHubSensorDescription(
        key="api_key_expires_at",
        translation_key="api_key_expires_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:key-alert-outline",
        value_fn=lambda c: c.api.key_expires_at,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MySkodaPublicApiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        MySkodaSensor(coordinator, vin, description)
        for vin, state in coordinator.vehicles.items()
        for description in VEHICLE_SENSORS
        if entity_exists(state, description)
    ]
    entities.extend(
        MySkodaHubSensor(coordinator, description) for description in HUB_SENSORS
    )
    async_add_entities(entities)


class MySkodaSensor(MySkodaVehicleEntity, SensorEntity):
    """A sensor reading one value out of the vehicle payload."""

    entity_description: MySkodaSensorDescription

    @property
    def native_value(self) -> Any:
        """Return the current value.

        Values outside a documented enum are reported as unknown rather than
        raising: the API states that new values may be added over time. The
        original string is still available as the ``raw_value`` attribute.
        """
        value = self.entity_description.value_fn(self.vehicle)
        options = self.entity_description.options
        if options is not None and value is not None and value not in options:
            _LOGGER.debug(
                "Unexpected value %r for %s; not in %s", value, self.entity_id, options
            )
            return None
        return value

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit, which for temperatures follows the vehicle."""
        if (unit_fn := self.entity_description.unit_fn) is not None:
            return unit_fn(self.vehicle)
        return super().native_unit_of_measurement

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Add the unmapped raw value for values outside a documented enum."""
        attributes = super().extra_state_attributes or {}
        options = self.entity_description.options
        if options is not None:
            raw = self.entity_description.value_fn(self.vehicle)
            if raw is not None and raw not in options:
                attributes = {**attributes, "raw_value": raw}
        return attributes or None


class MySkodaHubSensor(MySkodaHubEntity, SensorEntity):
    """A sensor about the API key and its quota."""

    entity_description: MySkodaHubSensorDescription

    @property
    def native_value(self) -> Any:
        """Return the current value."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def available(self) -> bool:
        """Quota information stays useful even when a poll failed."""
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes provided by the description."""
        if (attrs_fn := self.entity_description.attrs_fn) is not None:
            return attrs_fn(self.coordinator)
        return None
