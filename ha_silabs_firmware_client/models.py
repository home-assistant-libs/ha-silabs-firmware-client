"""Firmware update models."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
from typing import Any, Self

from yarl import URL


@dataclass(frozen=True)
class FirmwareMetadata:
    """Metadata for a remotely hosted firmware file."""

    filename: str
    checksum: str
    size: int
    release_notes: str | None
    metadata: dict[str, str | int | None]
    url: URL

    @classmethod
    def from_json(cls, data: dict[str, Any], *, url: URL) -> Self:
        """Construct from JSON data."""
        return cls(
            filename=data["filename"],
            checksum=data["checksum"],
            size=data["size"],
            release_notes=data["release_notes"],
            metadata=data["metadata"],
            # The manifest does not contain the full URL so we pass it externally
            url=url,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return metadata as a dict."""
        return {
            "filename": self.filename,
            "checksum": self.checksum,
            "size": self.size,
            "release_notes": self.release_notes,
            "metadata": self.metadata,
            "url": str(self.url),
        }

    def validate_firmware(self, data: bytes) -> None:
        """Parse firmware bytes into a firmware image."""
        if len(data) != self.size:
            raise ValueError("Invalid firmware size")

        algorithm, _, digest = self.checksum.partition(":")
        hasher = hashlib.new(algorithm)
        hasher.update(data)

        if hasher.hexdigest() != digest:
            raise ValueError("Invalid firmware checksum")


@dataclass(frozen=True)
class FirmwareManifest:
    """Manifest for a group of firmwares encompassing a firmware builder release."""

    url: URL
    html_url: URL
    created_at: datetime
    firmwares: tuple[FirmwareMetadata, ...]

    @classmethod
    def from_json(
        cls,
        data: dict[str, Any],
        *,
        url: URL,
        html_url: URL,
    ) -> Self:
        """Construct from JSON data."""
        return cls(
            url=url,
            html_url=html_url,
            created_at=datetime.fromisoformat(data["metadata"]["created_at"]),
            firmwares=tuple(
                [
                    FirmwareMetadata.from_json(f, url=url.parent / f["filename"])
                    for f in data["firmwares"]
                ]
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return manifest as a dict."""
        return {
            "url": str(self.url),
            "html_url": str(self.html_url),
            "metadata": {
                "created_at": self.created_at.isoformat(),
            },
            "firmwares": [f.as_dict() for f in self.firmwares],
        }
