"""Firmware update client."""

from __future__ import annotations

import logging

from aiohttp import ClientSession
from yarl import URL

from .models import FirmwareManifest

_LOGGER = logging.getLogger(__name__)


class ManifestMissing(Exception):
    """Manifest is missing from the GitHub release."""


class FirmwareUpdateClient:
    """Client to manage firmware updates."""

    def __init__(self, url: str, session: ClientSession) -> None:
        """Initialize the firmware update client."""
        self.url = url
        self.session = session

        self._latest_release_url: str | None = None
        self._latest_manifest: FirmwareManifest | None = None

    async def async_update_data(self) -> FirmwareManifest:
        # Fetch the latest release metadata
        async with self.session.get(
            self.url,
            headers={"X-GitHub-Api-Version": "2022-11-28"},
            raise_for_status=True,
        ) as rsp:
            obj = await rsp.json()

        release_url = obj["html_url"]

        if release_url == self._latest_release_url:
            _LOGGER.debug("GitHub release URL has not changed")
            assert self._latest_manifest is not None
            return self._latest_manifest

        try:
            manifest_asset = next(
                a for a in obj["assets"] if a["name"] == "manifest.json"
            )
        except StopIteration as exc:
            raise ManifestMissing(
                "GitHub release assets haven't been uploaded yet"
            ) from exc

        # Within the metadata, download the `manifest.json` file
        async with self.session.get(
            manifest_asset["browser_download_url"], raise_for_status=True
        ) as rsp:
            manifest_obj = await rsp.json(content_type=None)

        manifest = FirmwareManifest.from_json(
            manifest_obj,
            url=URL(manifest_asset["browser_download_url"]),
            html_url=URL(release_url),
        )

        # Only set the release URL down here to make sure that we don't invalidate
        # future requests if an exception is raised halfway through this method
        self._latest_manifest = manifest
        self._latest_release_url = release_url

        return self._latest_manifest
