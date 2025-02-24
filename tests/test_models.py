import hashlib

import pytest

from ha_silabs_firmware_client.models import FirmwareManifest, FirmwareMetadata

from .const import MANIFEST_HTML_URL, MANIFEST_JSON, MANIFEST_URL


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
        "firmwares": [fw.as_dict() for fw in manifest.firmwares],
        "url": str(MANIFEST_URL),
        "html_url": str(MANIFEST_HTML_URL),
    }

    assert manifest.url == MANIFEST_URL
    assert manifest.html_url == MANIFEST_HTML_URL
    assert manifest.created_at.isoformat() == MANIFEST_JSON["metadata"]["created_at"]
    assert len(manifest.firmwares) == 7
    assert manifest.firmwares[0].filename == "skyconnect_zigbee_ncp_7.4.4.0.gbl"
    assert manifest.firmwares[1].filename == "skyconnect_bootloader_2.4.2.gbl"
