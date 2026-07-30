import hashlib

import pytest

from ha_silabs_firmware_client.models import (
    ChangelogEntry,
    FirmwareManifest,
    FirmwareMetadata,
    render_changelog,
)

from .const import LEGACY_MANIFEST_JSON, MANIFEST_HTML_URL, MANIFEST_JSON, MANIFEST_URL


def test_firmware_metadata() -> None:
    """Test FirmwareMetadata JSON serialization/deserialization."""
    firmware_data = MANIFEST_JSON["firmwares"][0]
    meta = FirmwareMetadata.from_json(
        firmware_data, url=MANIFEST_URL.parent / firmware_data["filename"]
    )

    assert meta.as_dict() == {
        **firmware_data,
        "url": meta.as_dict()["url"],
    }

    assert meta.filename == firmware_data["filename"]
    assert meta.checksum == firmware_data["checksum"]
    assert meta.size == firmware_data["size"]
    assert meta.metadata == firmware_data["metadata"]
    assert meta.release_notes == firmware_data["release_notes"]
    assert meta.url == MANIFEST_URL.parent / firmware_data["filename"]


def test_firmware_metadata_validate_firmware() -> None:
    """Test FirmwareMetadata firmware parsing."""
    firmware = b"Test firmware"

    meta = FirmwareMetadata.from_json(
        {
            "filename": "test_firmware.gbl",
            "checksum": f"sha3-256:{hashlib.sha3_256(firmware).hexdigest()}",
            "size": len(firmware),
            "metadata": {
                "baudrate": 115200,
                "ezsp_version": "7.4.4.0",
                "fw_type": "zigbee_ncp",
                "fw_variant": None,
                "metadata_version": 2,
                "sdk_version": "4.4.4",
            },
            "release_notes": None,
            "release_summary": None,
        },
        url=MANIFEST_URL.parent / "test_firmware.gbl",
    )

    meta.validate_firmware(firmware)

    # The firmware size is checked
    with pytest.raises(ValueError, match="Invalid firmware size"):
        meta.validate_firmware(firmware + b"\x00")

    # As is the checksum
    with pytest.raises(ValueError, match="Invalid firmware checksum"):
        meta.validate_firmware(firmware[:-1] + b"\x00")


def test_firmware_manifest() -> None:
    """Test FirmwareManifest."""
    manifest = FirmwareManifest.from_json(
        MANIFEST_JSON, url=MANIFEST_URL, html_url=MANIFEST_HTML_URL
    )

    assert manifest.as_dict() == {
        "metadata": {
            "created_at": MANIFEST_JSON["metadata"]["created_at"],
        },
        "changelogs": MANIFEST_JSON["changelogs"],
        "firmwares": [fw.as_dict() for fw in manifest.firmwares],
        "url": str(MANIFEST_URL),
        "html_url": str(MANIFEST_HTML_URL),
    }

    assert manifest.url == MANIFEST_URL
    assert manifest.html_url == MANIFEST_HTML_URL
    assert manifest.created_at.isoformat() == MANIFEST_JSON["metadata"]["created_at"]
    assert len(manifest.firmwares) == 11
    assert manifest.firmwares[0].filename == "skyconnect_bootloader_2.4.2.gbl"
    assert manifest.firmwares[-1].filename == "zwa2_controller_1.2.0.gbl"
    assert set(manifest.changelogs) == {"zigbee_ncp", "openthread_rcp"}


def _firmware(manifest: FirmwareManifest, filename: str) -> FirmwareMetadata:
    """Look up a firmware by filename."""
    return next(f for f in manifest.firmwares if f.filename == filename)


def test_changelog_since() -> None:
    """Test computing a changelog across multiple versions."""
    manifest = FirmwareManifest.from_json(
        MANIFEST_JSON, url=MANIFEST_URL, html_url=MANIFEST_HTML_URL
    )
    fw = _firmware(manifest, "skyconnect_zigbee_ncp_7.5.1.0.gbl")

    assert fw.version == "7.5.1.0"

    # Every entry newer than the installed version, up to the shipped one
    assert [e.version for e in fw.changelog_since("7.4.4.4")] == [
        "7.5.1.0",
        "7.5.0.0",
        "7.4.4.6",
        "7.4.4.5",
    ]

    # The runtime build suffix reported by the adapter is ignored
    assert [
        e.version for e in fw.changelog_since("7.4.4.6 build 0 (20260111175147)")
    ] == ["7.5.1.0", "7.5.0.0"]

    # An already up-to-date adapter has nothing to show
    assert fw.changelog_since("7.5.1.0") == ()

    # Neither does one running something newer
    assert fw.changelog_since("9.1.0.0") == ()

    # An unknown version only yields the shipped entry
    assert [e.version for e in fw.changelog_since("1.2.3.4")] == ["7.5.1.0"]
    assert [e.version for e in fw.changelog_since(None)] == ["7.5.1.0"]


def test_changelog_since_openthread() -> None:
    """Test that OpenThread's version strings are matched correctly."""
    manifest = FirmwareManifest.from_json(
        MANIFEST_JSON, url=MANIFEST_URL, html_url=MANIFEST_HTML_URL
    )
    fw = _firmware(
        manifest, "yellow_openthread_rcp_2.7.2.0_GitHub-fb0446f53_gsdk_2025.6.2.gbl"
    )

    assert fw.version == "SL-OPENTHREAD/2.7.2.0_GitHub-fb0446f53"

    # The `; EFR32; <build date>` suffix an RCP reports at runtime is ignored
    assert (
        fw.changelog_since(
            "SL-OPENTHREAD/2.7.2.0_GitHub-fb0446f53; EFR32; Dec  8 2025 10:23:13"
        )
        == ()
    )

    # Older entries predate the `SL-OPENTHREAD/` prefix, which does not stop them
    # from being matched
    assert [e.version for e in fw.changelog_since("2.4.6.0_GitHub-bdb394eb3")] == [
        "SL-OPENTHREAD/2.7.2.0_GitHub-fb0446f53",
        "2.4.7.0_GitHub-fb0446f53",
    ]


def test_changelog_without_version() -> None:
    """Test firmwares that have no version of their own."""
    manifest = FirmwareManifest.from_json(
        MANIFEST_JSON, url=MANIFEST_URL, html_url=MANIFEST_HTML_URL
    )

    # The Z-Wave controller carries no metadata at all
    zwave = _firmware(manifest, "zwa2_controller_1.2.0.gbl")
    assert zwave.metadata is None
    assert zwave.version is None
    assert zwave.changelog == ()
    assert zwave.release_notes_since("1.2.0") is None

    # The Zigbee router has metadata, but no version key within it
    router = _firmware(manifest, "zbt2_router_2025.6.2.gbl")
    assert router.metadata is not None
    assert router.version is None
    assert router.changelog_since(None) == ()


def test_release_notes_since() -> None:
    """Test rendering a multi-version changelog as markdown."""
    manifest = FirmwareManifest.from_json(
        MANIFEST_JSON, url=MANIFEST_URL, html_url=MANIFEST_HTML_URL
    )
    fw = _firmware(manifest, "skyconnect_zigbee_ncp_7.5.1.0.gbl")

    assert fw.release_notes_since("7.4.4.6") == (
        "## 7.5.1.0\n"
        "\n"
        "Built with Gecko SDK 4.5.0. This includes a new feature to restore routes on"
        " adapter startup, speeding up network responsiveness after a reset.\n"
        "\n"
        "## 7.5.0.0\n"
        "\n"
        "Built with Gecko SDK 4.4.6."
    )

    assert fw.release_notes_since("7.5.1.0") is None


def test_render_changelog() -> None:
    """Test that an entry's detail body is included below its summary."""
    assert render_changelog([]) is None

    assert render_changelog(
        [
            ChangelogEntry(
                version="9.1.0.0",
                summary="A summary line",
                notes="- First change\n- Second change",
            ),
            ChangelogEntry(version="9.0.2.0", summary="An older release", notes=None),
        ]
    ) == (
        "## 9.1.0.0\n"
        "\n"
        "A summary line\n"
        "\n"
        "- First change\n"
        "- Second change\n"
        "\n"
        "## 9.0.2.0\n"
        "\n"
        "An older release"
    )


def test_legacy_manifest() -> None:
    """Test that manifests without a changelog fall back to the shipped entry."""
    manifest = FirmwareManifest.from_json(
        LEGACY_MANIFEST_JSON, url=MANIFEST_URL, html_url=MANIFEST_HTML_URL
    )

    assert manifest.changelogs == {}

    fw = _firmware(manifest, "skyconnect_zigbee_ncp_7.5.1.0.gbl")

    # The version is derived from the metadata, as the manifest does not contain it
    assert fw.version == "7.5.1.0"

    # Only the shipped version's entry is available, no matter what is installed
    assert [e.version for e in fw.changelog_since("7.4.4.4")] == ["7.5.1.0"]
    assert fw.changelog_since("7.5.1.0") == ()

    # Firmwares with no release notes at all stay empty
    assert _firmware(manifest, "zwa2_controller_1.2.0.gbl").changelog == ()
    assert _firmware(manifest, "skyconnect_bootloader_2.4.2.gbl").changelog == ()
    assert _firmware(manifest, "zbt2_router_2025.6.2.gbl").changelog == ()
