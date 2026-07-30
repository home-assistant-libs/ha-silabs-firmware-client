"""Firmware update models."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
from typing import Any, Self, cast

from yarl import URL


def normalize_version(version: str) -> str:
    """Strip runtime-reported build suffixes so versions match changelog entries."""

    # Adapters report richer version strings than the ones recorded in the changelog:
    # EmberZNet appends ` build N (timestamp)` and OpenThread appends `; EFR32; <date>`.
    return version.partition(";")[0].partition(" build ")[0].strip()


def firmware_version(metadata: dict[str, Any]) -> str | None:
    """Extract the firmware version from its metadata, if it is versioned at all."""
    version_keys = {k for k in metadata if k.endswith("_version")} - {
        "sdk_version",
        "metadata_version",
    }

    # Some firmwares, such as the Zigbee router, carry no version of their own
    if not version_keys:
        return None

    (version_key,) = version_keys

    return cast(str, metadata[version_key])


def _manifest_firmware_version(data: dict[str, Any]) -> str | None:
    """Extract a firmware's version from its entry in a manifest."""
    if data["metadata"] is None:
        return None

    # Manifests predating the `version` field
    if "version" not in data:
        return firmware_version(data["metadata"])

    return cast("str | None", data["version"])


@dataclass(frozen=True)
class ChangelogEntry:
    """A single released version's changelog."""

    version: str
    summary: str
    notes: str | None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        """Construct from JSON data."""
        return cls(
            version=data["version"],
            summary=data["summary"],
            notes=data["notes"],
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the entry as a dict."""
        return {
            "version": self.version,
            "summary": self.summary,
            "notes": self.notes,
        }


def render_changelog(entries: Iterable[ChangelogEntry]) -> str | None:
    """Render changelog entries as a single markdown document."""
    sections = []

    for entry in entries:
        section = f"## {entry.version}\n\n{entry.summary}"

        if entry.notes is not None:
            section += f"\n\n{entry.notes}"

        sections.append(section)

    if not sections:
        return None

    return "\n\n".join(sections)


@dataclass(frozen=True)
class FirmwareMetadata:
    """Metadata for a remotely hosted firmware file."""

    filename: str
    checksum: str
    size: int
    release_notes: str | None
    metadata: dict[str, str | int | None]
    url: URL
    release_summary: str | None = None
    version: str | None = None
    # The full changelog history for this firmware's type, newest first
    changelog: tuple[ChangelogEntry, ...] = ()

    @classmethod
    def from_json(
        cls,
        data: dict[str, Any],
        *,
        url: URL,
        changelog: tuple[ChangelogEntry, ...] = (),
    ) -> Self:
        """Construct from JSON data."""
        return cls(
            filename=data["filename"],
            checksum=data["checksum"],
            size=data["size"],
            release_notes=data["release_notes"],
            metadata=data["metadata"],
            # The manifest does not contain the full URL so we pass it externally
            url=url,
            release_summary=data.get("release_summary"),
            version=_manifest_firmware_version(data),
            changelog=changelog,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return metadata as a dict."""
        return {
            "filename": self.filename,
            "version": self.version,
            "checksum": self.checksum,
            "size": self.size,
            "release_notes": self.release_notes,
            "metadata": self.metadata,
            "url": str(self.url),
            "release_summary": self.release_summary,
        }

    def changelog_since(
        self, current_version: str | None
    ) -> tuple[ChangelogEntry, ...]:
        """Return every changelog entry between `current_version` and this firmware.

        Entries are newest first, so the tuple starts with this firmware's own version
        and ends with the one released just after `current_version`. An unrecognized
        `current_version`, such as a custom build, yields only this firmware's entry.
        """
        if self.version is None or not self.changelog:
            return ()

        # Changelog order is authoritative: firmware versions are not comparable. The
        # builder refuses to publish a firmware missing its own entry, so this raises
        # rather than papering over a malformed manifest.
        versions = [normalize_version(e.version) for e in self.changelog]
        to_index = versions.index(normalize_version(self.version))

        if current_version is None:
            return (self.changelog[to_index],)

        try:
            from_index = versions.index(normalize_version(current_version))
        except ValueError:
            return (self.changelog[to_index],)

        # The current version is the same as or newer than this firmware
        if from_index <= to_index:
            return ()

        return self.changelog[to_index:from_index]

    def release_notes_since(self, current_version: str | None) -> str | None:
        """Return markdown release notes for every version since `current_version`."""
        return render_changelog(self.changelog_since(current_version))

    def validate_firmware(self, data: bytes) -> None:
        """Parse firmware bytes into a firmware image."""
        if len(data) != self.size:
            raise ValueError("Invalid firmware size")

        algorithm, _, digest = self.checksum.partition(":")
        hasher = hashlib.new(algorithm)
        hasher.update(data)

        if hasher.hexdigest() != digest:
            raise ValueError("Invalid firmware checksum")


def _firmware_changelog(
    data: dict[str, Any], changelogs: dict[str, tuple[ChangelogEntry, ...]]
) -> tuple[ChangelogEntry, ...]:
    """Pick a firmware's changelog, synthesizing one for manifests without any."""
    if data["metadata"] is None:
        return ()

    fw_type = data["metadata"]["fw_type"]

    if fw_type in changelogs:
        return changelogs[fw_type]

    # Manifests predating `changelogs` carry only the shipped version's entry, split
    # across two inverted fields: `release_notes` is the summary, `release_summary`
    # the detailed body. `release_notes` has existed in every published manifest,
    # but `release_summary` was only added in v2025.04.04, so it may be absent.
    version = _manifest_firmware_version(data)

    if version is None or data["release_notes"] is None:
        return ()

    return (
        ChangelogEntry(
            version=version,
            summary=data["release_notes"],
            notes=data.get("release_summary"),
        ),
    )


@dataclass(frozen=True)
class FirmwareManifest:
    """Manifest for a group of firmwares encompassing a firmware builder release."""

    url: URL
    html_url: URL
    created_at: datetime
    firmwares: tuple[FirmwareMetadata, ...]
    # Full changelog history, keyed by firmware type and ordered newest first
    changelogs: dict[str, tuple[ChangelogEntry, ...]] = field(default_factory=dict)

    @classmethod
    def from_json(
        cls,
        data: dict[str, Any],
        *,
        url: URL,
        html_url: URL,
    ) -> Self:
        """Construct from JSON data."""
        changelogs = {
            fw_type: tuple(ChangelogEntry.from_json(e) for e in entries)
            for fw_type, entries in data.get("changelogs", {}).items()
        }

        return cls(
            url=url,
            html_url=html_url,
            created_at=datetime.fromisoformat(data["metadata"]["created_at"]),
            firmwares=tuple(
                [
                    FirmwareMetadata.from_json(
                        f,
                        url=url.parent / f["filename"],
                        changelog=_firmware_changelog(f, changelogs),
                    )
                    for f in data["firmwares"]
                ]
            ),
            changelogs=changelogs,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return manifest as a dict."""
        return {
            "url": str(self.url),
            "html_url": str(self.html_url),
            "metadata": {
                "created_at": self.created_at.isoformat(),
            },
            "changelogs": {
                fw_type: [e.as_dict() for e in entries]
                for fw_type, entries in self.changelogs.items()
            },
            "firmwares": [f.as_dict() for f in self.firmwares],
        }
