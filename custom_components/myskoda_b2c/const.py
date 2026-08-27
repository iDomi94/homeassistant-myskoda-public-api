"""Constants for the MyŠkoda B2C (public API) integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "myskoda_b2c"
MANUFACTURER: Final = "Škoda"

# --- API ---------------------------------------------------------------------

API_BASE_URL: Final = "https://public.api.connect.skoda-auto.cz"
API_KEY_HEADER: Final = "X-API-Key"
API_KEY_EXPIRES_HEADER: Final = "X-API-Key-Expires-At"

HEADER_RATELIMIT_LIMIT: Final = "RateLimit-Limit"
HEADER_RATELIMIT_REMAINING: Final = "RateLimit-Remaining"
HEADER_RATELIMIT_RESET: Final = "RateLimit-Reset"
HEADER_RETRY_AFTER: Final = "Retry-After"

API_KEY_MANAGEMENT_URL: Final = "https://go.skoda.eu/api-keys"

#: All parts of the vehicle payload that can be requested via ``include``.
#: We normally omit ``include`` entirely so unsupported parts are silently
#: absent instead of producing ``*_UNSUPPORTED`` entries in ``errors``.
VEHICLE_PARTS: Final = (
    "info",
    "status",
    "fuelStatus",
    "odometer",
    "parkingPosition",
    "airConditioning",
    "auxiliaryHeating",
    "activeVentilation",
    "charging",
    "chargingProfiles",
)

# Problem types (RFC 9457) documented by the API.
PROBLEM_API_KEY_EXPIRED: Final = f"{API_BASE_URL}/problems/api-key-expired"
PROBLEM_API_KEY_NOT_AUTHORIZED: Final = (
    f"{API_BASE_URL}/problems/api-key-not-authorized"
)
PROBLEM_OPERATION_NOT_AUTHORIZED: Final = (
    f"{API_BASE_URL}/problems/operation-not-authorized"
)
PROBLEM_OPERATION_NOT_SUPPORTED: Final = (
    f"{API_BASE_URL}/problems/operation-not-supported"
)
PROBLEM_OPERATION_DISABLED: Final = f"{API_BASE_URL}/problems/operation-disabled"
PROBLEM_RATE_LIMIT_EXCEEDED: Final = f"{API_BASE_URL}/problems/rate-limit-exceeded"
PROBLEM_VEHICLE_NOT_ACCEPTING: Final = (
    f"{API_BASE_URL}/problems/vehicle-not-accepting-requests"
)

# --- Configuration -----------------------------------------------------------

CONF_API_KEY: Final = "api_key"
CONF_VINS: Final = "vins"
CONF_SPIN: Final = "spin"
CONF_POLL_INTERVAL: Final = "poll_interval_in_minutes"
CONF_REFRESH_AFTER_COMMAND: Final = "refresh_after_command"
CONF_READONLY: Final = "readonly"

#: The documented quota is 20 requests per hour *per API key* and is shared by
#: every vehicle and every command. 30 minutes leaves plenty of head room for
#: remote commands, which consume the same quota.
DEFAULT_POLL_INTERVAL: Final = 30
MIN_POLL_INTERVAL: Final = 5
MAX_POLL_INTERVAL: Final = 1440

DEFAULT_REFRESH_AFTER_COMMAND: Final = True
#: Vehicles answer a command asynchronously; give them a moment before polling.
REFRESH_AFTER_COMMAND_DELAY: Final = 30
#: Never spend the last few requests of the quota on an automatic refresh.
REFRESH_AFTER_COMMAND_MIN_QUOTA: Final = 3

#: Minimum spacing between two manually triggered refreshes.
MANUAL_REFRESH_COOLDOWN: Final = 60.0

#: Fallbacks used when the quota is exhausted and the API gives no Retry-After.
DEFAULT_BACKOFF_SECONDS: Final = 300

# --- Local (non-API) command parameters --------------------------------------

DEFAULT_TARGET_TEMPERATURE: Final = 21.0
MIN_TARGET_TEMPERATURE: Final = 16.0
MAX_TARGET_TEMPERATURE: Final = 29.5
TARGET_TEMPERATURE_STEP: Final = 0.5

DEFAULT_AUX_HEATING_DURATION: Final = 20
MIN_AUX_HEATING_DURATION: Final = 5
MAX_AUX_HEATING_DURATION: Final = 60

AUX_START_MODE_HEATING: Final = "HEATING"
AUX_START_MODE_VENTILATION: Final = "VENTILATION"
AUX_START_MODES: Final = (AUX_START_MODE_HEATING, AUX_START_MODE_VENTILATION)

# --- Services ----------------------------------------------------------------

SERVICE_REFRESH: Final = "refresh"
SERVICE_START_CHARGING: Final = "start_charging"
SERVICE_STOP_CHARGING: Final = "stop_charging"
SERVICE_START_AIR_CONDITIONING: Final = "start_air_conditioning"
SERVICE_STOP_AIR_CONDITIONING: Final = "stop_air_conditioning"
SERVICE_START_AUXILIARY_HEATING: Final = "start_auxiliary_heating"
SERVICE_STOP_AUXILIARY_HEATING: Final = "stop_auxiliary_heating"
SERVICE_START_ACTIVE_VENTILATION: Final = "start_active_ventilation"
SERVICE_STOP_ACTIVE_VENTILATION: Final = "stop_active_ventilation"

ATTR_VIN: Final = "vin"
ATTR_TEMPERATURE: Final = "temperature"
ATTR_WITHOUT_EXTERNAL_POWER: Final = "without_external_power"
ATTR_DURATION: Final = "duration"
ATTR_START_MODE: Final = "start_mode"
ATTR_SPIN: Final = "spin"

# --- Value vocabularies ------------------------------------------------------

CHARGING_STATES_ACTIVE: Final = frozenset({"CHARGING"})
CHARGING_STATES_CABLE_DISCONNECTED: Final = frozenset({"CONNECT_CABLE"})

AIR_CONDITIONING_STATES_ACTIVE: Final = frozenset(
    {"COOLING", "HEATING", "HEATING_AUXILIARY", "VENTILATION"}
)
AUXILIARY_HEATING_STATES_ACTIVE: Final = frozenset(
    {"PREHEATING", "HEATING_AUXILIARY", "VENTILATION"}
)
ACTIVE_VENTILATION_STATES_ACTIVE: Final = frozenset({"PREHEATING", "VENTILATION"})

#: Values that mean "the vehicle did not tell us" rather than a real state.
UNKNOWN_VALUES: Final = frozenset({"UNKNOWN", "UNSUPPORTED"})
