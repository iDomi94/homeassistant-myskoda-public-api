"""Helpers shared by the MyŠkoda B2C platforms."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .const import UNKNOWN_VALUES


def nested_get(data: Any, path: str) -> Any:
    """Read a dotted path out of nested dictionaries.

    Returns ``None`` as soon as any step is missing, so callers never have to
    guard against parts of the payload the vehicle did not report.
    """
    current = data
    for key in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


def clean_value(value: Any) -> Any:
    """Turn the API's placeholder states into ``None``.

    ``UNKNOWN`` and ``UNSUPPORTED`` mean "no reading", which HA represents as an
    unknown state rather than as a literal string.
    """
    if isinstance(value, str) and value in UNKNOWN_VALUES:
        return None
    return value


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO 8601 timestamp from the API."""
    if not isinstance(value, str):
        return None
    return dt_util.parse_datetime(value)


def flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested dictionaries into ``a_b_c`` keys.

    Used to expose whole sections of the payload as entity attributes, so data
    the integration has no dedicated entity for is still available.
    """
    result: dict[str, Any] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            name = f"{prefix}_{_snake(key)}" if prefix else _snake(key)
            if isinstance(value, dict):
                result.update(flatten(value, name))
            else:
                result[name] = value
    elif prefix:
        result[prefix] = data
    return result


def _snake(name: str) -> str:
    """Convert a camelCase API key into snake_case."""
    out: list[str] = []
    for index, char in enumerate(name):
        if char.isupper():
            if index and (not name[index - 1].isupper() or _next_is_lower(name, index)):
                out.append("_")
            out.append(char.lower())
        else:
            out.append(char)
    return "".join(out)


def _next_is_lower(name: str, index: int) -> bool:
    """Whether the character after ``index`` is lower case."""
    return index + 1 < len(name) and name[index + 1].islower()


def is_one_of(value: Any, allowed: frozenset[str]) -> bool | None:
    """Check membership, mapping unreported values to ``None``.

    ``None`` keeps a binary sensor in the unknown state instead of claiming the
    feature is off when the vehicle simply did not answer.
    """
    cleaned = clean_value(value)
    if cleaned is None:
        return None
    return cleaned in allowed
