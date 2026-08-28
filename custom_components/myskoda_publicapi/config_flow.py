"""Config flow for the MySkoda PublicAPI integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    MySkodaApiError,
    MySkodaAuthError,
    MySkodaConnectionError,
    MySkodaForbiddenError,
    MySkodaNotFoundError,
    MySkodaPublicApi,
    MySkodaRateLimitError,
)
from .const import (
    CONF_API_KEY,
    CONF_POLL_INTERVAL,
    CONF_REFRESH_AFTER_COMMAND,
    CONF_SPIN,
    CONF_VINS,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_REFRESH_AFTER_COMMAND,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

VIN_LENGTH = 17

API_KEY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    }
)

VINS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_VINS): SelectSelector(
            SelectSelectorConfig(
                options=[],
                multiple=True,
                custom_value=True,
                mode=SelectSelectorMode.LIST,
            )
        )
    }
)


def _normalise_vins(raw: Any) -> list[str]:
    """Accept a list or a comma separated string and return clean VINs."""
    if isinstance(raw, str):
        parts = raw.replace(";", ",").replace("\n", ",").split(",")
    elif isinstance(raw, list):
        parts = [str(item) for item in raw]
    else:
        return []
    return [part.strip().upper() for part in parts if part.strip()]


class MySkodaPublicApiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow.

    Setup asks for the API key only. The public API has no endpoint that lists
    the vehicles a key covers, so when the optional discovery probe finds none,
    a second step asks for the VINs. Should Škoda add a listing endpoint, that
    step disappears on its own.
    """

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._api_key: str | None = None
        self._vins: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the API key."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._api_key = user_input[CONF_API_KEY].strip()
            api = MySkodaPublicApi(async_get_clientsession(self.hass), self._api_key)
            # A single probe both checks the key and looks for a listing
            # endpoint. 401 and 403 responses do not consume the request quota.
            try:
                discovered = await api.async_discover_vins()
            except MySkodaAuthError as err:
                errors["base"] = "expired_api_key" if err.expired else "invalid_api_key"
            except MySkodaRateLimitError:
                errors["base"] = "rate_limited"
            except MySkodaConnectionError:
                errors["base"] = "cannot_connect"
            except MySkodaApiError as err:
                # No listing endpoint exists today; fall back to asking for VINs.
                _LOGGER.debug("Vehicle discovery is not available: %s", err)
                return await self.async_step_vehicles()
            else:
                if discovered:
                    self._vins = discovered
                    return await self._async_create_entry()
                return await self.async_step_vehicles()

        return self.async_show_form(
            step_id="user",
            data_schema=API_KEY_SCHEMA,
            errors=errors,
            description_placeholders={"url": "https://go.skoda.eu/api-keys"},
        )

    async def async_step_vehicles(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the VINs the API key was created for."""
        errors: dict[str, str] = {}

        if user_input is not None:
            vins = _normalise_vins(user_input.get(CONF_VINS))
            if not vins:
                errors["base"] = "no_vehicles"
            elif any(len(vin) != VIN_LENGTH for vin in vins):
                errors["base"] = "invalid_vin"
            else:
                assert self._api_key is not None
                api = MySkodaPublicApi(
                    async_get_clientsession(self.hass), self._api_key
                )
                error = await self._async_check_vehicles(api, vins)
                if error:
                    errors["base"] = error
                else:
                    self._vins = vins
                    return await self._async_create_entry()

        return self.async_show_form(
            step_id="vehicles",
            data_schema=VINS_SCHEMA,
            errors=errors,
        )

    async def _async_check_vehicles(
        self, api: MySkodaPublicApi, vins: list[str]
    ) -> str | None:
        """Verify every VIN is reachable with this key, returning an error key."""
        for vin in vins:
            try:
                await api.async_get_vehicle(vin, include=["info"])
            except MySkodaAuthError as err:
                return "expired_api_key" if err.expired else "invalid_api_key"
            except MySkodaForbiddenError:
                return "vehicle_not_authorized"
            except MySkodaNotFoundError:
                return "vehicle_not_found"
            except MySkodaRateLimitError:
                return "rate_limited"
            except MySkodaConnectionError:
                return "cannot_connect"
            except MySkodaApiError:
                return "unknown"
        return None

    async def _async_create_entry(self) -> ConfigFlowResult:
        """Store the validated configuration."""
        await self.async_set_unique_id(",".join(sorted(self._vins)))
        data = {CONF_API_KEY: self._api_key, CONF_VINS: self._vins}

        if self.source == SOURCE_RECONFIGURE:
            self._abort_if_unique_id_mismatch(reason="different_vehicles")
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data=data
            )

        self._abort_if_unique_id_configured()
        title = (
            f"MyŠkoda ({self._vins[0]})"
            if len(self._vins) == 1
            else f"MyŠkoda ({len(self._vins)} vehicles)"
        )
        return self.async_create_entry(title=title, data=data)

    # --- Re-authentication ---------------------------------------------------

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Start re-authentication after the API key expired or was revoked."""
        self._vins = list(entry_data.get(CONF_VINS, []))
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a fresh API key."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            api = MySkodaPublicApi(async_get_clientsession(self.hass), api_key)
            error = await self._async_check_vehicles(
                api, list(entry.data.get(CONF_VINS, []))
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: api_key}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=API_KEY_SCHEMA,
            errors=errors,
            description_placeholders={"url": "https://go.skoda.eu/api-keys"},
        )

    # --- Reconfiguration -----------------------------------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the API key and the list of vehicles."""
        entry = self._get_reconfigure_entry()
        self._api_key = entry.data[CONF_API_KEY]
        self._vins = list(entry.data.get(CONF_VINS, []))
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return MySkodaPublicApiOptionsFlow()


class MySkodaPublicApiOptionsFlow(OptionsFlow):
    """Handle the integration options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage polling, the S-PIN and post-command refreshes."""
        errors: dict[str, str] = {}

        if user_input is not None:
            spin = str(user_input.get(CONF_SPIN, "")).strip()
            if spin and not spin.isdigit():
                errors[CONF_SPIN] = "invalid_spin"
            else:
                return self.async_create_entry(
                    data={
                        CONF_POLL_INTERVAL: int(user_input[CONF_POLL_INTERVAL]),
                        CONF_SPIN: spin,
                        CONF_REFRESH_AFTER_COMMAND: user_input[
                            CONF_REFRESH_AFTER_COMMAND
                        ],
                    }
                )

        options = self.config_entry.options
        vehicle_count = max(len(self.config_entry.data.get(CONF_VINS, [])), 1)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_POLL_INTERVAL,
                    default=options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_POLL_INTERVAL,
                        max=MAX_POLL_INTERVAL,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Optional(
                    CONF_SPIN, default=options.get(CONF_SPIN, "")
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                vol.Required(
                    CONF_REFRESH_AFTER_COMMAND,
                    default=options.get(
                        CONF_REFRESH_AFTER_COMMAND, DEFAULT_REFRESH_AFTER_COMMAND
                    ),
                ): BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "vehicles": str(vehicle_count),
                "requests_per_hour": str(
                    round(
                        60
                        / max(options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL), 1)
                        * vehicle_count,
                        1,
                    )
                ),
            },
        )
