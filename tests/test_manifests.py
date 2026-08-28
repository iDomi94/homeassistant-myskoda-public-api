"""Checks on hacs.json and manifest.json that the CI jobs enforce remotely."""

import json
from pathlib import Path

COMPONENT = Path("custom_components/myskoda_publicapi")

#: Keys the HACS schema accepts. render_readme was removed from it and makes
#: the whole file invalid, which in turn fails the manifest check.
HACS_KEYS = {
    "name",
    "content_in_root",
    "zip_release",
    "filename",
    "hide_default_branch",
    "country",
    "homeassistant",
    "hacs",
    "persistent_directory",
}


def test_hacs_json_uses_only_supported_keys() -> None:
    """An unknown key makes HACS reject the whole file."""
    data = json.loads(Path("hacs.json").read_text(encoding="utf-8"))
    assert set(data) <= HACS_KEYS, f"unsupported: {sorted(set(data) - HACS_KEYS)}"
    assert data["name"]
    # filename is required whenever the content ships as a zipped release.
    if data.get("zip_release"):
        assert data.get("filename")


def test_manifest_key_order() -> None:
    """The hassfest job wants domain and name first, then the rest alphabetically."""
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    keys = list(manifest)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_manifest_domain_matches_the_folder() -> None:
    """A mismatch makes Home Assistant refuse to load the integration."""
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == COMPONENT.name
    assert manifest["loggers"] == [f"custom_components.{COMPONENT.name}"]


def test_services_and_icons_agree() -> None:
    """Every action needs an icon and a translation, and nothing extra."""
    import yaml

    services = set(yaml.safe_load((COMPONENT / "services.yaml").read_text()))
    icons = json.loads((COMPONENT / "icons.json").read_text(encoding="utf-8"))
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    assert set(icons["services"]) == services
    assert set(strings["services"]) == services
