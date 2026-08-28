"""Thin async client for the MyŠkoda Public API.

The whole contract is documented at
https://public.api.connect.skoda-auto.cz/docs -- this module deliberately keeps
the payloads as plain dictionaries. The API is still in beta and new fields are
expected; passing the raw payload through means new data shows up as entity
attributes without a code change.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any, Self

from aiohttp import ClientError, ClientResponse, ClientSession
from homeassistant.util import dt as dt_util

from .const import (
    API_BASE_URL,
    API_KEY_EXPIRES_HEADER,
    API_KEY_HEADER,
    HEADER_RATELIMIT_LIMIT,
    HEADER_RATELIMIT_REMAINING,
    HEADER_RATELIMIT_RESET,
    HEADER_RETRY_AFTER,
    PROBLEM_API_KEY_EXPIRED,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30


class MySkodaApiError(Exception):
    """Base error raised for any failed API interaction."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        problem_type: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Initialise the error with the RFC 9457 problem details, if any."""
        super().__init__(message)
        self.status = status
        self.problem_type = problem_type
        self.detail = detail


class MySkodaConnectionError(MySkodaApiError):
    """The API could not be reached at all."""


class MySkodaAuthError(MySkodaApiError):
    """The API key is invalid or has expired (HTTP 401)."""

    def __init__(self, *args: Any, expired: bool = False, **kwargs: Any) -> None:
        """Initialise and remember whether the key merely expired."""
        super().__init__(*args, **kwargs)
        self.expired = expired


class MySkodaForbiddenError(MySkodaApiError):
    """The key does not cover the vehicle, or the vehicle refused (HTTP 403)."""


class MySkodaNotFoundError(MySkodaApiError):
    """No vehicle exists for the given VIN (HTTP 404)."""


class MySkodaOperationNotPossibleError(MySkodaApiError):
    """The vehicle cannot execute the operation (HTTP 422). Retrying will not help."""


class MySkodaRateLimitError(MySkodaApiError):
    """The quota is exhausted, or the vehicle declined for now (HTTP 429)."""

    def __init__(
        self, *args: Any, retry_after: int | None = None, **kwargs: Any
    ) -> None:
        """Initialise and remember how long the caller should wait."""
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after


@dataclass(slots=True)
class RateLimit:
    """Latest state of the ``RateLimit-*`` headers.

    The quota is per API key and shared by every vehicle and every command, so
    a single instance is kept on the client rather than per vehicle.
    """

    limit: int | None = None
    remaining: int | None = None
    reset_in_seconds: int | None = None
    updated_at: datetime | None = None

    @property
    def resets_at(self) -> datetime | None:
        """Absolute time at which the quota replenishes."""
        if self.updated_at is None or self.reset_in_seconds is None:
            return None
        return self.updated_at + timedelta(seconds=self.reset_in_seconds)

    def update_from_headers(self, headers: Any) -> None:
        """Absorb the rate-limit headers of a response."""
        limit = _header_int(headers, HEADER_RATELIMIT_LIMIT)
        remaining = _header_int(headers, HEADER_RATELIMIT_REMAINING)
        reset = _header_int(headers, HEADER_RATELIMIT_RESET)
        if limit is None and remaining is None and reset is None:
            return
        if limit is not None:
            self.limit = limit
        if remaining is not None:
            self.remaining = remaining
        if reset is not None:
            self.reset_in_seconds = reset
        self.updated_at = dt_util.utcnow()

    def as_dict(self) -> dict[str, Any]:
        """Return a serialisable view, e.g. for entity attributes."""
        resets_at = self.resets_at
        return {
            "limit": self.limit,
            "remaining": self.remaining,
            "reset_in_seconds": self.reset_in_seconds,
            "resets_at": resets_at.isoformat() if resets_at else None,
        }


def _header_int(headers: Any, name: str) -> int | None:
    """Read a header as an int, tolerating anything unexpected."""
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class VehicleData:
    """A single ``GET /api/v1/vehicles/{vin}`` response.

    ``raw`` is kept verbatim. Every accessor works on it, which keeps the
    integration forward compatible with new fields.
    """

    vin: str
    raw: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    fetched_at: datetime | None = None

    @classmethod
    def from_response(cls, vin: str, payload: dict[str, Any]) -> Self:
        """Build from the ``VehicleResponse`` envelope."""
        vehicle = payload.get("vehicle")
        if not isinstance(vehicle, dict):
            vehicle = {}
        errors = payload.get("errors")
        if not isinstance(errors, list):
            errors = []
        return cls(
            vin=vehicle.get("vin") or vin,
            raw=vehicle,
            errors=[e for e in errors if isinstance(e, dict)],
            fetched_at=dt_util.utcnow(),
        )

    def part(self, name: str) -> dict[str, Any] | None:
        """Return one top-level part of the payload, if present."""
        value = self.raw.get(name)
        return value if isinstance(value, dict) else None

    @property
    def error_types(self) -> list[str]:
        """Machine-readable ``type`` of every reported error."""
        return [str(e.get("type")) for e in self.errors if e.get("type")]

    def has_error(self, *types: str) -> bool:
        """Whether any of the given error types was reported."""
        reported = set(self.error_types)
        return any(t in reported for t in types)


class MySkodaPublicApi:
    """Client for the MyŠkoda Public API, authenticated with an API key."""

    def __init__(self, session: ClientSession, api_key: str) -> None:
        """Initialise the client on a shared aiohttp session."""
        self._session = session
        self._api_key = api_key
        self.rate_limit = RateLimit()
        self.key_expires_at: datetime | None = None
        #: Serialises requests so a burst of commands cannot race past the quota.
        self._lock = asyncio.Lock()

    @property
    def api_key(self) -> str:
        """The API key in use."""
        return self._api_key

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform one request and translate failures into typed errors."""
        url = f"{API_BASE_URL}{path}"
        headers = {API_KEY_HEADER: self._api_key, "Accept": "application/json"}

        async with self._lock:
            try:
                async with self._session.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                    timeout=REQUEST_TIMEOUT,
                ) as response:
                    self._absorb_headers(response)
                    body = await _read_body(response)
                    if response.status >= HTTPStatus.BAD_REQUEST:
                        raise _error_for(response, body)
                    return body if isinstance(body, dict) else {}
            except TimeoutError as err:
                raise MySkodaConnectionError(
                    f"Timeout while calling {method} {path}"
                ) from err
            except ClientError as err:
                raise MySkodaConnectionError(
                    f"Error while calling {method} {path}: {err}"
                ) from err

    def _absorb_headers(self, response: ClientResponse) -> None:
        """Remember quota and key expiry advertised by a response."""
        self.rate_limit.update_from_headers(response.headers)
        if raw_expiry := response.headers.get(API_KEY_EXPIRES_HEADER):
            if parsed := dt_util.parse_datetime(raw_expiry):
                self.key_expires_at = parsed

    # --- Vehicle data --------------------------------------------------------

    async def async_get_vehicle(
        self, vin: str, include: Iterable[str] | None = None
    ) -> VehicleData:
        """Fetch a vehicle and its current state.

        ``include`` is omitted by default: without it, parts the vehicle does
        not support are simply absent instead of being reported as errors.
        """
        params: dict[str, Any] | None = None
        if include is not None:
            params = {"include": ",".join(include)}
        payload = await self._request("GET", f"/api/v1/vehicles/{vin}", params=params)
        return VehicleData.from_response(vin, payload)

    async def async_discover_vins(self) -> list[str] | None:
        """Try to list the vehicles the API key covers.

        The public API does not document a listing endpoint, so this is a
        best-effort probe of ``GET /api/v1/vehicles``. It returns ``None`` when
        no such endpoint exists, which is the situation today -- the config flow
        then asks for the VINs instead. Should Škoda add the endpoint, discovery
        starts working without any further change.
        """
        try:
            payload = await self._request("GET", "/api/v1/vehicles")
        except (MySkodaNotFoundError, MySkodaForbiddenError):
            return None
        except MySkodaApiError as err:
            if err.status in (HTTPStatus.BAD_REQUEST, HTTPStatus.METHOD_NOT_ALLOWED):
                return None
            raise

        return _extract_vins(payload)

    # --- Remote commands -----------------------------------------------------

    async def async_start_charging(self, vin: str) -> None:
        """Start charging."""
        await self._request("POST", f"/api/v1/vehicles/{vin}/charging/start")

    async def async_stop_charging(self, vin: str) -> None:
        """Stop charging."""
        await self._request("POST", f"/api/v1/vehicles/{vin}/charging/stop")

    async def async_start_air_conditioning(
        self,
        vin: str,
        *,
        target_temperature: float | None = None,
        temperature_unit: str = "CELSIUS",
        without_external_power: bool | None = None,
    ) -> None:
        """Start air conditioning, optionally with a target temperature."""
        body: dict[str, Any] = {}
        if target_temperature is not None:
            body["targetTemperature"] = {
                "value": target_temperature,
                "unit": temperature_unit,
            }
        if without_external_power is not None:
            body["airConditioningWithoutExternalPower"] = without_external_power
        await self._request(
            "POST", f"/api/v1/vehicles/{vin}/air-conditioning/start", json=body
        )

    async def async_stop_air_conditioning(self, vin: str) -> None:
        """Stop air conditioning."""
        await self._request("POST", f"/api/v1/vehicles/{vin}/air-conditioning/stop")

    async def async_start_auxiliary_heating(
        self,
        vin: str,
        *,
        spin: str,
        target_temperature: float | None = None,
        temperature_unit: str = "CELSIUS",
        duration_in_seconds: int | None = None,
        start_mode: str | None = None,
    ) -> None:
        """Start auxiliary heating. The S-PIN is mandatory for this command."""
        body: dict[str, Any] = {"spin": spin}
        if target_temperature is not None:
            body["targetTemperature"] = {
                "value": target_temperature,
                "unit": temperature_unit,
            }
        if duration_in_seconds is not None:
            body["durationInSeconds"] = duration_in_seconds
        if start_mode is not None:
            body["startMode"] = start_mode
        await self._request(
            "POST", f"/api/v1/vehicles/{vin}/auxiliary-heating/start", json=body
        )

    async def async_stop_auxiliary_heating(self, vin: str) -> None:
        """Stop auxiliary heating."""
        await self._request("POST", f"/api/v1/vehicles/{vin}/auxiliary-heating/stop")

    async def async_start_active_ventilation(self, vin: str) -> None:
        """Start active ventilation."""
        await self._request("POST", f"/api/v1/vehicles/{vin}/active-ventilation/start")

    async def async_stop_active_ventilation(self, vin: str) -> None:
        """Stop active ventilation."""
        await self._request("POST", f"/api/v1/vehicles/{vin}/active-ventilation/stop")


async def _read_body(response: ClientResponse) -> Any:
    """Read a JSON body, tolerating empty and non-JSON responses."""
    if response.status == HTTPStatus.NO_CONTENT:
        return {}
    try:
        return await response.json(content_type=None)
    except (ValueError, ClientError):
        return {}


def _error_for(response: ClientResponse, body: Any) -> MySkodaApiError:
    """Map an HTTP error response onto the matching exception type."""
    problem = body if isinstance(body, dict) else {}
    problem_type = problem.get("type")
    detail = problem.get("detail") or problem.get("title")
    status = response.status
    message = detail or f"HTTP {status} from {response.url.path}"
    kwargs: dict[str, Any] = {
        "status": status,
        "problem_type": problem_type,
        "detail": detail,
    }

    if status == HTTPStatus.UNAUTHORIZED:
        return MySkodaAuthError(
            message, expired=problem_type == PROBLEM_API_KEY_EXPIRED, **kwargs
        )
    if status == HTTPStatus.FORBIDDEN:
        return MySkodaForbiddenError(message, **kwargs)
    if status == HTTPStatus.NOT_FOUND:
        return MySkodaNotFoundError(message, **kwargs)
    if status == HTTPStatus.UNPROCESSABLE_ENTITY:
        return MySkodaOperationNotPossibleError(message, **kwargs)
    if status == HTTPStatus.TOO_MANY_REQUESTS:
        return MySkodaRateLimitError(
            message,
            retry_after=_header_int(response.headers, HEADER_RETRY_AFTER),
            **kwargs,
        )
    return MySkodaApiError(message, **kwargs)


def _extract_vins(payload: Any) -> list[str] | None:
    """Pull VINs out of whatever shape a listing endpoint might return."""
    candidates: Any = payload
    if isinstance(payload, dict):
        for key in ("vehicles", "items", "data", "vins"):
            if key in payload:
                candidates = payload[key]
                break
        else:
            return None

    if not isinstance(candidates, list):
        return None

    vins: list[str] = []
    for item in candidates:
        if isinstance(item, str):
            vins.append(item)
        elif isinstance(item, dict) and isinstance(item.get("vin"), str):
            vins.append(item["vin"])
    return vins or None
