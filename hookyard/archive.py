"""Portable, versioned archives for a single bin.

Archives are plain JSON so they can travel with a bug report, a chat message,
or a git repository. They contain captured payloads (and therefore possibly
secrets), so treat them like the data file itself.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .store import MemoryStore, RequestRecord, record_from_dict

ARCHIVE_VERSION = 1
ARCHIVE_FORMAT = "hookyard-bin"
MAX_BIN_ID = 64
BIN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class ArchiveError(ValueError):
    """A malformed, unsupported, or unwritable archive."""


@dataclass(frozen=True)
class Archive:
    bin_id: str
    records: list[RequestRecord]
    exported_at: str | None = None


def export_payload(
    bin_id: str,
    records: Iterable[RequestRecord],
    *,
    exported_at: str | None = None,
) -> dict[str, Any]:
    """Build the JSON payload for one bin without touching the filesystem."""
    if not isinstance(bin_id, str) or not BIN_ID_RE.fullmatch(bin_id):
        raise ArchiveError(
            f"invalid 'bin' {bin_id!r}; must match [A-Za-z0-9._-]{{1,64}}"
        )
    return {
        "format": ARCHIVE_FORMAT,
        "version": ARCHIVE_VERSION,
        "bin": bin_id,
        "exported_at": exported_at
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "requests": [record.to_dict() for record in records],
    }


def write_archive(
    path: str | Path, bin_id: str, records: Iterable[RequestRecord]
) -> None:
    """Write an archive via a temporary file, then atomically replace the target."""
    target = Path(path)
    temporary = target.with_name(target.name + ".tmp")
    payload = export_payload(bin_id, records)
    try:
        temporary.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(target)
    except OSError as error:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise ArchiveError(
            f"cannot write archive {target}: {error.strerror or error}"
        ) from error


def load_archive(path: str | Path) -> Archive:
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ArchiveError(f"{file} is not valid UTF-8: {error}") from error
    except OSError as error:
        raise ArchiveError(
            f"cannot read archive {file}: {error.strerror or error}"
        ) from error
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise ArchiveError(
            f"{file} is not valid JSON: {error.msg} (line {error.lineno})"
        ) from error
    return parse_archive(raw, source=str(file))


def parse_archive(raw: Any, *, source: str | None = None) -> Archive:
    """Validate an archive document and turn it into records."""

    def fail(message: str) -> None:
        prefix = f"{source}: " if source else ""
        raise ArchiveError(prefix + message)

    if not isinstance(raw, dict):
        fail("archive is not a JSON object")

    version = raw.get("version")
    if version is None:
        fail("missing 'version'")
    if isinstance(version, bool) or not isinstance(version, int):
        fail("'version' must be an integer")
    if version != ARCHIVE_VERSION:
        fail(
            f"unsupported archive version {version}; "
            f"supported: {ARCHIVE_VERSION}"
        )

    archive_format = raw.get("format")
    if archive_format is not None and archive_format != ARCHIVE_FORMAT:
        fail(f"'format' must be {ARCHIVE_FORMAT!r}")

    if "bin" not in raw:
        fail("missing 'bin'")
    bin_id = raw["bin"]
    if not isinstance(bin_id, str) or not BIN_ID_RE.fullmatch(bin_id):
        fail(f"invalid 'bin' {bin_id!r}; must match [A-Za-z0-9._-]{{1,64}}")

    if "requests" not in raw:
        fail("missing 'requests'")
    requests = raw["requests"]
    if not isinstance(requests, list):
        fail("'requests' must be a list")

    exported_at = raw.get("exported_at")
    if exported_at is not None and not isinstance(exported_at, str):
        fail("'exported_at' must be a string")

    records: list[RequestRecord] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(requests, start=1):
        if not isinstance(item, dict):
            fail(f"request #{index} must be an object")
        try:
            record = record_from_dict(bin_id, item, strict=True)
        except (TypeError, ValueError) as error:
            fail(f"request #{index}: {error}")
        if record.id in seen_ids:
            fail(f"request #{index}: duplicate request id {record.id!r}")
        seen_ids.add(record.id)
        records.append(record)

    return Archive(bin_id=bin_id, records=records, exported_at=exported_at)


def unique_bin_id(existing: Iterable[str], base: str) -> str:
    """Return ``base`` or the first free ``base-N`` suffix that still fits."""
    taken = set(existing)
    if base not in taken:
        return base
    for number in range(2, 10_000):
        suffix = f"-{number}"
        candidate = base[: max(1, MAX_BIN_ID - len(suffix))] + suffix
        if candidate not in taken:
            return candidate
    raise ArchiveError(f"cannot find a free bin name for {base!r}")


def import_archive(
    store: MemoryStore, archive: Archive, *, rename: bool = False
) -> str:
    """Import all records from an archive and return the destination bin id."""
    if archive.bin_id in store.bins():
        if not rename:
            raise ArchiveError(
                f"bin {archive.bin_id!r} already exists; "
                "pass rename=True (CLI: --rename) to import under a new name"
            )
        destination = unique_bin_id(store.bins(), archive.bin_id)
    else:
        destination = archive.bin_id
    store.import_bin(destination, archive.records)
    return destination
