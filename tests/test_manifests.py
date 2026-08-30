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


def test_every_service_field_is_translated() -> None:
    """An untranslated field fails the hassfest SERVICES check."""
    import yaml

    services = yaml.safe_load((COMPONENT / "services.yaml").read_text())
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))

    problems = []
    for name, body in services.items():
        declared = set(body.get("fields", {}))
        translated = set(strings["services"][name].get("fields", {}))
        if missing := declared - translated:
            problems.append(f"{name}: untranslated {sorted(missing)}")
        if extra := translated - declared:
            problems.append(f"{name}: translated but absent {sorted(extra)}")
    assert not problems, problems


def test_no_service_uses_a_device_filter_on_target() -> None:
    """Targets do not accept device filters; use a device selector field.

    Home Assistant rejects `target: {device: {integration: ...}}`, so the
    actions carry a device_id field instead.
    """
    import yaml

    services = yaml.safe_load((COMPONENT / "services.yaml").read_text())
    offenders = [
        name
        for name, body in services.items()
        if isinstance(body.get("target"), dict) and "device" in body["target"]
    ]
    assert not offenders, offenders


def test_brand_assets_are_present_and_sized_correctly() -> None:
    """HACS looks for brand assets here before falling back to the brands repo.

    Wrong dimensions fail the check as surely as missing files.
    """
    import struct

    for name, expected in (("icon.png", (256, 256)), ("icon@2x.png", (512, 512))):
        data = (COMPONENT / "brand" / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{name} is not a PNG"
        assert struct.unpack(">II", data[16:24]) == expected, name
