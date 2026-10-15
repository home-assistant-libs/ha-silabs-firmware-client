import collections
from collections.abc import AsyncIterator, Awaitable, Callable
import copy
import dataclasses
import hashlib
from typing import Any

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
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

RELEASE_TAG_URL = "https://github.com/NabuCasa/silabs-firmware-builder/releases/tag"

StartServer = Callable[..., Awaitable[TestServer]]

RELEASES = web.AppKey[list[dict[str, Any]]]("releases")
ASSETS = web.AppKey[dict[str, bytes]]("assets")
ASSET_REQUESTS = web.AppKey[collections.Counter[str]]("asset_requests")


async def _handle_releases(request: web.Request) -> web.Response:
    """Serve the releases API, pointing asset downloads back at this server."""
    releases = copy.deepcopy(request.app[RELEASES])
    base = request.url.origin()

    for release in releases:
        for asset in release["assets"]:
            asset["browser_download_url"] = str(
                base / "download" / release["tag_name"] / asset["name"]
            )

    return web.json_response(releases)


async def _handle_asset(request: web.Request) -> web.Response:
    """Serve a release asset."""
    name = request.match_info["name"]
    assets = request.app[ASSETS]

    if name not in assets:
        raise web.HTTPNotFound

    request.app[ASSET_REQUESTS][name] += 1

    return web.Response(body=assets[name])


@pytest.fixture
async def start_server() -> AsyncIterator[StartServer]:
    """Start local servers standing in for the GitHub API and its release assets.

    Serving over a real aiohttp server keeps the tests honest against whatever
    aiohttp version is installed, instead of a mock that has to track its internals.
    """
    servers: list[TestServer] = []

    async def start(
        releases: list[dict[str, Any]],
        assets: dict[str, bytes] | None = None,
    ) -> TestServer:
        app = web.Application()
        app[RELEASES] = releases
        app[ASSETS] = {
            "manifest.json": RAW_MANIFEST_JSON.encode(),
            **(assets or {}),
        }
        app[ASSET_REQUESTS] = collections.Counter[str]()
        app.router.add_get("/releases", _handle_releases)
        app.router.add_get("/download/{tag}/{name}", _handle_asset)

        server = TestServer(app)
        await server.start_server()
        servers.append(server)

        return server

    yield start

    for server in servers:
        await server.close()


async def test_firmware_update_client(start_server: StartServer) -> None:
    """Test the firmware update client loads manifests."""
    server = await start_server(GITHUB_RELEASES)

    async with ClientSession() as session:
        client = FirmwareUpdateClient(str(server.make_url("/releases")), session)
        manifest = await client.async_update_data()

        assert manifest.url == server.make_url("/download/v2026.02.23/manifest.json")
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
        new_manifest = await client.async_update_data()
        assert manifest is new_manifest

        # Because the cached URL did not change, we did not download the manifest again
        assert server.app[ASSET_REQUESTS]["manifest.json"] == 1


async def test_firmware_update_client_manifest_missing(
    start_server: StartServer,
) -> None:
    """Test the firmware update client handles missing manifests."""
    releases = copy.deepcopy(GITHUB_RELEASES)
    latest = next(
        r for r in releases if r["tag_name"] == GITHUB_API_RESPONSE["tag_name"]
    )
    latest["assets"] = [a for a in latest["assets"] if a["name"] != "manifest.json"]

    server = await start_server(releases)

    async with ClientSession() as session:
        client = FirmwareUpdateClient(str(server.make_url("/releases")), session)

        with pytest.raises(ManifestMissing):
            await client.async_update_data()


async def test_manifest_missing_falls_back_to_cache(start_server: StartServer) -> None:
    """Test that a release whose assets are still uploading reuses the last manifest."""
    published = copy.deepcopy(GITHUB_RELEASES)
    latest = next(
        r for r in published if r["tag_name"] == GITHUB_API_RESPONSE["tag_name"]
    )

    # A newer release exists, but its build has not finished uploading assets yet
    pending = copy.deepcopy(latest)
    pending["tag_name"] = "v2026.03.01"
    pending["html_url"] = f"{RELEASE_TAG_URL}/v2026.03.01"
    pending["assets"] = []

    server = await start_server(published)

    async with ClientSession() as session:
        client = FirmwareUpdateClient(str(server.make_url("/releases")), session)
        manifest = await client.async_update_data()
        assert manifest.html_url == URL(f"{RELEASE_TAG_URL}/v2026.02.23")

        # The half-published release does not invalidate what we already have
        published.append(pending)
        assert await client.async_update_data() is manifest

        # Once its assets land, it is picked up
        pending["assets"] = copy.deepcopy(latest["assets"])
        new_manifest = await client.async_update_data()
        assert new_manifest.html_url == URL(f"{RELEASE_TAG_URL}/v2026.03.01")


async def test_fetch_firmware(start_server: StartServer) -> None:
    """Test fetching firmware."""
    firmware = b"Test firmware"
    server = await start_server(GITHUB_RELEASES, assets={"test_firmware.gbl": firmware})

    meta = FirmwareMetadata(
        filename="test_firmware.gbl",
        checksum=f"sha3-256:{hashlib.sha3_256(firmware).hexdigest()}",
        size=len(firmware),
        release_notes=None,
        metadata={"fw_type": "zigbee_ncp"},
        url=server.make_url("/download/v2026.02.23/test_firmware.gbl"),
    )

    async with ClientSession() as session:
        client = FirmwareUpdateClient(str(server.make_url("/releases")), session)
        assert await client.async_fetch_firmware(meta) == firmware

        # Invalid firmwares are caught during fetching
        corrupted = dataclasses.replace(
            meta,
            checksum="sha3-256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )

        with pytest.raises(ValueError, match="Invalid firmware checksum"):
            await client.async_fetch_firmware(corrupted)


async def test_update_prerelease_flag(start_server: StartServer) -> None:
    """Test that update_prerelease() correctly toggles between stable and prerelease."""
    # The newest release in this subset is a prerelease, so the flag decides which
    # release is picked
    server = await start_server(OLDER_GITHUB_RELEASES)

    async with ClientSession() as session:
        # Start with prerelease=False (default)
        client = FirmwareUpdateClient(str(server.make_url("/releases")), session)
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
