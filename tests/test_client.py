import copy
import json

from aiohttp import ClientSession
from aioresponses import aioresponses
import pytest
from yarl import URL

from ha_silabs_firmware_client.client import FirmwareUpdateClient, ManifestMissing

from .const import GITHUB_API_RESPONSE, RESOURCES_ROOT

API_URL = (
    "https://api.github.com/repos/NabuCasa/silabs-firmware-builder/releases/latest"
)


async def test_firmware_update_client() -> None:
    """Test the firmware update client loads manifests."""
    async with ClientSession() as session:
        with aioresponses() as http:
            # Mock all assets
            http.get(API_URL, body=json.dumps(GITHUB_API_RESPONSE))

            for asset in GITHUB_API_RESPONSE["assets"]:
                assert (RESOURCES_ROOT / asset["name"]).is_relative_to(RESOURCES_ROOT)
                http.get(
                    asset["browser_download_url"],
                    body=(RESOURCES_ROOT / asset["name"]).read_bytes(),
                )

            client = FirmwareUpdateClient(API_URL, session)
            manifest = await client.async_update_data()

            assert manifest.url == URL(
                "https://github.com/NabuCasa/silabs-firmware-builder/releases/download/v2024.10.21/manifest.json"
            )
            assert manifest.html_url == URL(
                "https://github.com/NabuCasa/silabs-firmware-builder/releases/tag/v2024.10.21"
            )
            assert len(manifest.firmwares) == 7

            # All firmwares validate
            for fw in manifest.firmwares:
                async with session.get(fw.url, raise_for_status=True) as rsp:
                    data = await rsp.read()
                    fw.validate_firmware(data)

            # Load things again
            http.get(API_URL, body=json.dumps(GITHUB_API_RESPONSE))

            new_manifest = await client.async_update_data()
            assert manifest is new_manifest

            # Because the cached URL did not change, we did not need to download again


async def test_firmware_update_client_manifest_missing() -> None:
    """Test the firmware update client handles missing manifests."""
    api_response = copy.deepcopy(GITHUB_API_RESPONSE)
    api_response["assets"] = [
        a for a in api_response["assets"] if a["name"] != "manifest.json"
    ]

    async with ClientSession() as session:
        with aioresponses() as http:
            http.get(API_URL, body=json.dumps(api_response))
            client = FirmwareUpdateClient(API_URL, session)

            with pytest.raises(ManifestMissing):
                await client.async_update_data()
