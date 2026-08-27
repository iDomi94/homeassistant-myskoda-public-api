"""Data update coordinator for the MyŠkoda B2C integration."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    MySkodaApiError,
    MySkodaAuthError,
    MySkodaConnectionError,
    MySkodaForbiddenError,
    MySkodaNotFoundError,
    MySkodaOperationNotPossibleError,
    MySkodaPublicApi,
    MySkodaRateLimitError,
    VehicleData,
)
from .const import (
    AUX_START_MODE_HEATING,
    CONF_API_KEY,
    CONF_POLL_INTERVAL,
    CONF_REFRESH_AFTER_COMMAND,
    CONF_SPIN,
    CONF_VINS,
    DEFAULT_AUX_HEATING_DURATION,
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_REFRESH_AFTER_COMMAND,
    DEFAULT_TARGET_TEMPERATURE,
    DOMAIN,
    REFRESH_AFTER_COMMAND_DELAY,
    REFRESH_AFTER_COMMAND_MIN_QUOTA,
)

_LOGGER = logging.getLogger(__name__)

type MySkodaB2CConfigEntry = ConfigEntry[MySkodaCoordinator]


@dataclass
class CommandSettings:
    """Parameters used when a remote command is sent.

    The API exposes no endpoint for writing vehicle settings, so these live in
    Home Assistant and are applied at the moment a command is issued. They are
    surfaced as number/select/switch entities and restored across restarts.
    """

    target_temperature: float = DEFAULT_TARGET_TEMPERATURE
    temperature_unit: str = "CELSIUS"
    air_conditioning_without_external_power: bool | None = None
    auxiliary_heating_duration_minutes: int = DEFAULT_AUX_HEATING_DURATION
    auxiliary_heating_start_mode: str = AUX_START_MODE_HEATING


@dataclass
class VehicleState:
    """Everything the integration knows about one vehicle."""

    vin: str
    data: VehicleData | None = None
    last_error: str | None = None
    settings: CommandSettings = field(default_factory=CommandSettings)

    @property
    def available(self) -> bool:
        """Whether usable data has been received at least once."""
        return self.data is not None


class MySkodaCoordinator(DataUpdateCoordinator[dict[str, VehicleState]]):
    """Polls every configured vehicle while respecting the shared quota.

    The documented limit is 20 requests per hour *per API key*, shared by all
    vehicles and all remote commands. One coordinator for the whole config entry
    therefore polls the vehicles sequentially and applies a single backoff.
    """

    config_entry: MySkodaB2CConfigEntry

    def __init__(self, hass: HomeAssistant, entry: MySkodaB2CConfigEntry) -> None:
        """Initialise the coordinator from the config entry."""
        self.api = MySkodaPublicApi(
            async_get_clientsession(hass), entry.data[CONF_API_KEY]
        )
        self.vins: list[str] = list(entry.data.get(CONF_VINS, []))
        self.vehicles: dict[str, VehicleState] = {
            vin: VehicleState(vin=vin) for vin in self.vins
        }
        self._backoff_until: datetime | None = None
        self._pending_refresh_cancel: Callable[[], None] | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(
                minutes=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ),
        )

    # --- Configuration -------------------------------------------------------

    @property
    def poll_interval(self) -> int:
        """Configured polling interval in minutes."""
        return self.config_entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)

    @property
    def spin(self) -> str | None:
        """The S-PIN, required for auxiliary heating."""
        return self.config_entry.options.get(CONF_SPIN) or None

    @property
    def refresh_after_command(self) -> bool:
        """Whether a command schedules a follow-up poll."""
        return self.config_entry.options.get(
            CONF_REFRESH_AFTER_COMMAND, DEFAULT_REFRESH_AFTER_COMMAND
        )

    def settings(self, vin: str) -> CommandSettings:
        """Command parameters for one vehicle."""
        return self.vehicles[vin].settings

    # --- Polling -------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, VehicleState]:
        """Fetch every vehicle, keeping partial results on partial failures."""
        if self._backoff_until and dt_util.utcnow() < self._backoff_until:
            if any(state.available for state in self.vehicles.values()):
                _LOGGER.debug(
                    "Skipping poll, backing off until %s", self._backoff_until
                )
                return self.vehicles
            raise UpdateFailed(
                "Rate limit exceeded; waiting for the quota to replenish"
            )

        failures: list[str] = []
        for vin, state in self.vehicles.items():
            try:
                state.data = await self.api.async_get_vehicle(vin)
                state.last_error = None
            except MySkodaAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except MySkodaRateLimitError as err:
                self._apply_backoff(err)
                state.last_error = str(err)
                failures.append(f"{vin}: {err}")
                break
            except MySkodaApiError as err:
                state.last_error = str(err)
                failures.append(f"{vin}: {err}")
                _LOGGER.debug("Failed to update %s: %s", vin, err)

        self._backoff_until = None if not failures else self._backoff_until

        if failures and not any(state.available for state in self.vehicles.values()):
            raise UpdateFailed("; ".join(failures))
        return self.vehicles

    def _apply_backoff(self, err: MySkodaRateLimitError) -> None:
        """Pause polling for as long as the API asked."""
        delay = err.retry_after or self.api.rate_limit.reset_in_seconds
        delay = delay or DEFAULT_BACKOFF_SECONDS
        self._backoff_until = dt_util.utcnow() + timedelta(seconds=delay)
        _LOGGER.warning(
            "MyŠkoda rate limit hit; pausing updates for %s seconds. The public API "
            "allows %s requests per hour per API key -- consider a longer polling "
            "interval",
            delay,
            self.api.rate_limit.limit or 20,
        )

    @callback
    def async_update_poll_interval(self) -> None:
        """Apply a changed polling interval from the options."""
        self.update_interval = timedelta(minutes=self.poll_interval)

    # --- Commands ------------------------------------------------------------

    async def async_send_command(
        self, vin: str, command: Callable[[], Awaitable[None]], description: str
    ) -> None:
        """Run a remote command and translate failures for the UI."""
        try:
            await command()
        except MySkodaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MySkodaRateLimitError as err:
            self._apply_backoff(err)
            raise HomeAssistantError(
                f"{description} was rejected: {err}. The MyŠkoda API allows "
                f"{self.api.rate_limit.limit or 20} requests per hour per API key."
            ) from err
        except MySkodaOperationNotPossibleError as err:
            raise HomeAssistantError(
                f"{description} is not possible for {vin}: {err}"
            ) from err
        except MySkodaForbiddenError as err:
            raise HomeAssistantError(
                f"{description} was refused for {vin}: {err}"
            ) from err
        except MySkodaNotFoundError as err:
            raise HomeAssistantError(f"Vehicle {vin} was not found: {err}") from err
        except (MySkodaConnectionError, MySkodaApiError) as err:
            raise HomeAssistantError(f"{description} failed for {vin}: {err}") from err

        self._async_schedule_refresh_after_command()

    @callback
    def _async_schedule_refresh_after_command(self) -> None:
        """Poll once shortly after a command, if the quota allows it.

        Commands are answered with ``202 Accepted``; the new state only shows up
        in a later poll. The refresh is skipped when little quota is left, so a
        convenience poll never blocks a command the user actually wants to send.
        """
        if not self.refresh_after_command:
            return

        remaining = self.api.rate_limit.remaining
        if remaining is not None and remaining < REFRESH_AFTER_COMMAND_MIN_QUOTA:
            _LOGGER.debug(
                "Skipping post-command refresh, only %s requests left in the quota",
                remaining,
            )
            return

        if self._pending_refresh_cancel is not None:
            self._pending_refresh_cancel()

        async def _refresh(_now: Any) -> None:
            self._pending_refresh_cancel = None
            await self.async_request_refresh()

        self._pending_refresh_cancel = async_call_later(
            self.hass, REFRESH_AFTER_COMMAND_DELAY, _refresh
        )

    @callback
    def async_cancel_pending_refresh(self) -> None:
        """Drop a scheduled post-command refresh, e.g. when unloading."""
        if self._pending_refresh_cancel is not None:
            self._pending_refresh_cancel()
            self._pending_refresh_cancel = None

    # --- Diagnostics ---------------------------------------------------------

    @property
    def diagnostic_attributes(self) -> dict[str, Any]:
        """Quota and key expiry, for the hub diagnostic entities."""
        return {
            **self.api.rate_limit.as_dict(),
            "api_key_expires_at": (
                self.api.key_expires_at.isoformat() if self.api.key_expires_at else None
            ),
            "poll_interval_in_minutes": self.poll_interval,
            "vehicles": self.vins,
        }
