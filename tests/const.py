"""Constants for unit tests."""

import json
import pathlib

from yarl import URL

RESOURCES_ROOT = pathlib.Path(__file__).parent / "resources"

RAW_GITHUB_RELEASES = (RESOURCES_ROOT / "github_releases.json").read_text()
RAW_MANIFEST_JSON = (RESOURCES_ROOT / "manifest.json").read_text()

GITHUB_RELEASES = json.loads(RAW_GITHUB_RELEASES)
MANIFEST_JSON = json.loads(RAW_MANIFEST_JSON)

# Use the latest stable release (v2025.09.30 at index 1, after prerelease)
GITHUB_API_RESPONSE = GITHUB_RELEASES[1]

assert GITHUB_API_RESPONSE["assets"][0]["name"] == "manifest.json"

MANIFEST_URL = URL(GITHUB_API_RESPONSE["assets"][0]["browser_download_url"])
MANIFEST_HTML_URL = URL(GITHUB_API_RESPONSE["html_url"])
