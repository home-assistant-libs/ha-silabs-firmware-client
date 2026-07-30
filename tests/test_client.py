import copy
import dataclasses
import hashlib
import json
from typing import Any

from aiohttp import ClientSession
from aioresponses import aioresponses
import pytest
from yarl import URL

from ha_silabs_firmware_client.client import FirmwareUpdateClient, ManifestMissing
from ha_silabs_firmware_client.models import FirmwareMetadata

from .const import (
    GITHUB_API_RESPONSE,
    GITHUB_RELEASES,
    OLDER_GITHUB_RELEASES,
    OLDER_PRERELEASE_TAG,
    OLDER_STABLE_TAG,
    RAW_MANIFEST_JSON,
)

API_URL = "https://api.github.com/repos/NabuCasa/silabs-firmware-builder/releases"
RELEASE_TAG_URL = "https://github.com/NabuCasa/silabs-firmware-builder/releases/tag"


def mock_manifest_asset(
    http: aioresponses, release: dict[str, Any], **kwargs: Any
) -> None:
    """Mock a release's manifest.json asset.

    The firmware assets themselves are never mocked: the client treats firmware as
    opaque bytes, so there is nothing to gain from serving megabytes of real ones.
    `test_fetch_firmware` covers the download path with a synthetic payload instead.
    """
    # Releases from 2024 and earlier predate manifests entirely
    for asset in release["assets"]:
        if asset["name"] == "manifest.json":
            http.get(asset["browser_download_url"], body=RAW_MANIFEST_JSON, **kwargs)


async def test_firmware_update_client() -> None:
    """Test the firmware update client loads manifests."""
    async with ClientSession() as session:
        with aioresponses() as http:
            http.get(API_URL, body=json.dumps(GITHUB_RELEASES))
            mock_manifest_asset(http, GITHUB_API_RESPONSE)

            client = FirmwareUpdateClient(API_URL, session)
            manifest = await client.async_update_data()

            assert manifest.url == URL(
                "https://github.com/NabuCasa/silabs-firmware-builder/releases/download/v2026.02.23/manifest.json"
            )
            assert manifest.html_url == URL(f"{RELEASE_TAG_URL}/v2026.02.23")
            assert len(manifest.firmwares) == 11

            # Firmware URLs are resolved relative to the manifest's own URL
            fw = next(
                f
                for f in manifest.firmwares
                if f.filename == "yellow_zigbee_ncp_7.5.1.0.gbl"
            )
            assert fw.url == manifest.url.parent / fw.filename
            assert fw.version == "7.5.1.0"

            # Each firmware is given the changelog history for its own type
            assert fw.changelog == manifest.changelogs["zigbee_ncp"]

            # Load things again
            http.get(API_URL, body=json.dumps(GITHUB_RELEASES))

            new_manifest = await client.async_update_data()
            assert manifest is new_manifest

            # Because the cached URL did not change, we did not need to download again


async def test_firmware_update_client_manifest_missing() -> None:
    """Test the firmware update client handles missing manifests."""
    releases = copy.deepcopy(GITHUB_RELEASES)
    latest = next(
        r for r in releases if r["tag_name"] == GITHUB_API_RESPONSE["tag_name"]
    )
    latest["assets"] = [a for a in latest["assets"] if a["name"] != "manifest.json"]

    async with ClientSession() as session:
        with aioresponses() as http:
            http.get(API_URL, body=json.dumps(releases))
            client = FirmwareUpdateClient(API_URL, session)

            with pytest.raises(ManifestMissing):
                await client.async_update_data()


async def test_fetch_firmware() -> None:
    """Test fetching firmware."""
    firmware = b"Test firmware"
    url = URL("https://example.org/firmwares/test_firmware.gbl")

    meta = FirmwareMetadata(
        filename="test_firmware.gbl",
        checksum=f"sha3-256:{hashlib.sha3_256(firmware).hexdigest()}",
        size=len(firmware),
        release_notes=None,
        metadata={"fw_type": "zigbee_ncp"},
        url=url,
    )

    async with ClientSession() as session:
        with aioresponses() as http:
            http.get(url, body=firmware, repeat=True)

            client = FirmwareUpdateClient(API_URL, session)
            assert await client.async_fetch_firmware(meta) == firmware

            # Invalid firmwares are caught during fetching
            corrupted = dataclasses.replace(
                meta,
                checksum="sha3-256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )

            with pytest.raises(ValueError, match="Invalid firmware checksum"):
                await client.async_fetch_firmware(corrupted)


async def test_update_prerelease_flag() -> None:
    """Test that update_prerelease() correctly toggles between stable and prerelease."""
    async with ClientSession() as session:
        with aioresponses() as http:
            # The newest release in this subset is a prerelease, so the flag decides
            # which one is picked
            http.get(API_URL, body=json.dumps(OLDER_GITHUB_RELEASES), repeat=True)

            for release in OLDER_GITHUB_RELEASES:
                mock_manifest_asset(http, release, repeat=True)

            # Start with prerelease=False (default)
            client = FirmwareUpdateClient(API_URL, session)
            manifest = await client.async_update_data()

            # Should get stable release
            assert manifest.html_url == URL(f"{RELEASE_TAG_URL}/{OLDER_STABLE_TAG}")

            # Toggle to prerelease=True
            client.update_prerelease(True)
            manifest = await client.async_update_data()

            # Should now get prerelease
            assert manifest.html_url == URL(f"{RELEASE_TAG_URL}/{OLDER_PRERELEASE_TAG}")

            # Toggle back to prerelease=False
            client.update_prerelease(False)
            manifest = await client.async_update_data()

            # Should get stable release again
            assert manifest.html_url == URL(f"{RELEASE_TAG_URL}/{OLDER_STABLE_TAG}")
