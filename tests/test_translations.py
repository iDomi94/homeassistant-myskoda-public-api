"""Checks that mirror what hassfest enforces about translations.

Catching these locally is a lot faster than waiting for the CI job.
"""

import json
import re
from pathlib import Path

import pytest

from custom_components.myskoda_publicapi.sensor import HUB_SENSORS, VEHICLE_SENSORS

COMPONENT = Path("custom_components/myskoda_publicapi")
TRANSLATION_FILES = [
    COMPONENT / "strings.json",
    COMPONENT / "translations/en.json",
    COMPONENT / "translations/de.json",
]

#: hassfest rejects anything else as a translation key.
KEY_PATTERN = re.compile(r"^[a-z0-9-_]+$")


def all_keys(data: dict, prefix: str = "") -> set[str]:
    """Every dotted key path in a nested dictionary."""
    keys = set()
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        keys.add(path)
        if isinstance(value, dict):
            keys |= all_keys(value, path)
    return keys


@pytest.mark.parametrize("path", TRANSLATION_FILES, ids=lambda p: p.name)
def test_state_translation_keys_are_lowercase(path: Path) -> None:
    """Enum state keys must be lower case, or hassfest fails the build."""
    data = json.loads(path.read_text(encoding="utf-8"))
    offenders = [
        f"{platform}.{entity}.state.{state}"
        for platform, entities in data["entity"].items()
        for entity, entry in entities.items()
        for state in entry.get("state", {})
        if not KEY_PATTERN.match(state)
    ]
    assert not offenders, f"{path.name}: {offenders}"


def test_translations_cover_every_enum_option() -> None:
    """Every documented enum value needs a translated state, and vice versa."""
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    sensors = strings["entity"]["sensor"]

    problems = []
    for description in (*VEHICLE_SENSORS, *HUB_SENSORS):
        options = getattr(description, "options", None)
        if options is None:
            continue
        states = set(sensors.get(description.key, {}).get("state", {}))
        if missing := set(options) - states:
            problems.append(f"{description.key} missing states {sorted(missing)}")
        if extra := states - set(options):
            problems.append(f"{description.key} has unused states {sorted(extra)}")
    assert not problems, problems


def test_every_language_has_the_same_keys() -> None:
    """A missing German key would silently fall back to English."""
    reference = all_keys(json.loads(TRANSLATION_FILES[0].read_text(encoding="utf-8")))
    for path in TRANSLATION_FILES[1:]:
        keys = all_keys(json.loads(path.read_text(encoding="utf-8")))
        assert not reference - keys, (
            f"{path.name} is missing {sorted(reference - keys)}"
        )
        assert not keys - reference, f"{path.name} has extra {sorted(keys - reference)}"
