import copy
import dataclasses
import json

from aiohttp import ClientSession
from aioresponses import aioresponses
import pytest
from yarl import URL

from ha_silabs_firmware_client.client import FirmwareUpdateClient, ManifestMissing

from .const import GITHUB_API_RESPONSE, GITHUB_RELEASES, RESOURCES_ROOT

API_URL = "https://api.github.com/repos/NabuCasa/silabs-firmware-builder/releases"


async def test_firmware_update_client() -> None:
    """Test the firmware update client loads manifests."""
    async with ClientSession() as session:
        with aioresponses() as http:
            # Mock all assets
            http.get(API_URL, body=json.dumps(GITHUB_RELEASES))

            for asset in GITHUB_API_RESPONSE["assets"]:
                assert (RESOURCES_ROOT / asset["name"]).is_relative_to(RESOURCES_ROOT)
                http.get(
                    asset["browser_download_url"],
                    body=(RESOURCES_ROOT / asset["name"]).read_bytes(),
                )

            client = FirmwareUpdateClient(API_URL, session)
            manifest = await client.async_update_data()

            assert manifest.url == URL(
                "https://github.com/NabuCasa/silabs-firmware-builder/releases/download/v2025.09.30/manifest.json"
            )
            assert manifest.html_url == URL(
                "https://github.com/NabuCasa/silabs-firmware-builder/releases/tag/v2025.09.30"
            )
            assert len(manifest.firmwares) == 10

            # All firmwares validate
            for fw in manifest.firmwares:
                data = await client.async_fetch_firmware(fw)
                assert isinstance(data, bytes)

            # Load things again
            http.get(API_URL, body=json.dumps(GITHUB_RELEASES))

            new_manifest = await client.async_update_data()
            assert manifest is new_manifest

            # Because the cached URL did not change, we did not need to download again


async def test_firmware_update_client_manifest_missing() -> None:
    """Test the firmware update client handles missing manifests."""
    releases = copy.deepcopy(GITHUB_RELEASES)
    releases[1]["assets"] = [
        a for a in releases[1]["assets"] if a["name"] != "manifest.json"
    ]

    async with ClientSession() as session:
        with aioresponses() as http:
            http.get(API_URL, body=json.dumps(releases))
            client = FirmwareUpdateClient(API_URL, session)

            with pytest.raises(ManifestMissing):
                await client.async_update_data()


async def test_fetch_firmware() -> None:
    """Test fetching firmware."""
    async with ClientSession() as session:
        with aioresponses() as http:
            http.get(API_URL, body=json.dumps(GITHUB_RELEASES))

            for asset in GITHUB_API_RESPONSE["assets"]:
                assert (RESOURCES_ROOT / asset["name"]).is_relative_to(RESOURCES_ROOT)
                http.get(
                    asset["browser_download_url"],
                    body=(RESOURCES_ROOT / asset["name"]).read_bytes(),
                    repeat=True,
                )

            client = FirmwareUpdateClient(API_URL, session)
            manifest = await client.async_update_data()

            for meta in manifest.firmwares:
                data = await client.async_fetch_firmware(meta)
                assert isinstance(data, bytes)

            # Invalid firmwares are caught during fetching
            meta = dataclasses.replace(
                manifest.firmwares[0],
                checksum="sha3-256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )

            with pytest.raises(ValueError, match="Invalid firmware checksum"):
                await client.async_fetch_firmware(meta)


async def test_prerelease_flag() -> None:
    """Test that the prerelease flag correctly filters releases."""
    async with ClientSession() as session:
        with aioresponses() as http:
            # Mock releases
            http.get(API_URL, body=json.dumps(GITHUB_RELEASES))

            # Mock assets for the prerelease version (v2025.10.14 at index 0)
            prerelease = GITHUB_RELEASES[0]
            for asset in prerelease["assets"]:
                # Use stable release assets for testing (same files)
                asset_name = asset["name"]
                if (RESOURCES_ROOT / asset_name).exists():
                    http.get(
                        asset["browser_download_url"],
                        body=(RESOURCES_ROOT / asset_name).read_bytes(),
                    )

            # Client with prerelease=True should get the prerelease version
            client = FirmwareUpdateClient(API_URL, session, prerelease=True)
            manifest = await client.async_update_data()

            assert manifest.html_url == URL(
                "https://github.com/NabuCasa/silabs-firmware-builder/releases/tag/v2025.10.14"
            )

            # Test default behavior (prerelease=False)
            http.get(API_URL, body=json.dumps(GITHUB_RELEASES))

            for asset in GITHUB_API_RESPONSE["assets"]:
                http.get(
                    asset["browser_download_url"],
                    body=(RESOURCES_ROOT / asset["name"]).read_bytes(),
                )

            client_stable = FirmwareUpdateClient(API_URL, session)
            manifest_stable = await client_stable.async_update_data()

            # Should get the latest stable release (v2025.09.30)
            assert manifest_stable.html_url == URL(
                "https://github.com/NabuCasa/silabs-firmware-builder/releases/tag/v2025.09.30"
            )
