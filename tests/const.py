"""Constants for unit tests."""

import json
import pathlib

from yarl import URL

RESOURCES_ROOT = pathlib.Path(__file__).parent / "resources"

RAW_GITHUB_API_RESPONSE = (RESOURCES_ROOT / "github_latest.json").read_text()
RAW_MANIFEST_JSON = (RESOURCES_ROOT / "manifest.json").read_text()

GITHUB_API_RESPONSE = json.loads(RAW_GITHUB_API_RESPONSE)
MANIFEST_JSON = json.loads(RAW_MANIFEST_JSON)

assert GITHUB_API_RESPONSE["assets"][0]["name"] == "manifest.json"

MANIFEST_URL = URL(GITHUB_API_RESPONSE["assets"][0]["browser_download_url"])
MANIFEST_HTML_URL = URL(GITHUB_API_RESPONSE["html_url"])
