"""Constants for unit tests."""

import json
import pathlib

from yarl import URL

RESOURCES_ROOT = pathlib.Path(__file__).parent / "resources"

RAW_GITHUB_RELEASES = (RESOURCES_ROOT / "github_releases.json").read_text()
RAW_MANIFEST_JSON = (RESOURCES_ROOT / "manifest.json").read_text()
RAW_LEGACY_MANIFEST_JSON = (RESOURCES_ROOT / "manifest_legacy.json").read_text()

GITHUB_RELEASES = json.loads(RAW_GITHUB_RELEASES)
MANIFEST_JSON = json.loads(RAW_MANIFEST_JSON)

# The v2026.02.23 manifest exactly as it was published, predating `changelogs`
LEGACY_MANIFEST_JSON = json.loads(RAW_LEGACY_MANIFEST_JSON)

# The latest stable release. Its assets are the firmwares vendored in `resources`, so
# it is the only release whose firmwares can actually be fetched in tests.
LATEST_STABLE_TAG = "v2026.02.23"
GITHUB_API_RESPONSE = next(
    r for r in GITHUB_RELEASES if r["tag_name"] == LATEST_STABLE_TAG
)

assert GITHUB_API_RESPONSE["assets"][0]["name"] == "manifest.json"

# Releases older than the latest stable one, where the newest of all is a prerelease.
# Toggling the prerelease flag over this subset changes which release is picked.
OLDER_GITHUB_RELEASES = [
    r for r in GITHUB_RELEASES if r["tag_name"] != LATEST_STABLE_TAG
]
OLDER_PRERELEASE_TAG = "v2026.01.11-beta2"
OLDER_STABLE_TAG = "v2025.11.24"

MANIFEST_URL = URL(GITHUB_API_RESPONSE["assets"][0]["browser_download_url"])
MANIFEST_HTML_URL = URL(GITHUB_API_RESPONSE["html_url"])
