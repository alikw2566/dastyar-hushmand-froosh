"""Configurable metadata extraction for common Issabel/Asterisk filenames."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .persian import normalize_phone


@dataclass(frozen=True, slots=True)
class CallFileMetadata:
    caller_number: str | None = None
    destination_number: str | None = None
    extension: str | None = None
    direction: str | None = None
    call_started_at: datetime | None = None
    unique_call_id: str | None = None
    queue: str | None = None
    agent_extension: str | None = None
    parser_name: str = "fallback"

    def as_dict(self) -> dict:
        return asdict(self)


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "asterisk-monitor",
        re.compile(
            r"^(?P<direction>in|out|inbound|outbound)[-_]"
            r"(?P<caller>\+?\d+)[-_](?P<destination>\+?\d+)[-_]"
            r"(?P<date>\d{4}-?\d{2}-?\d{2})[-_](?P<time>\d{2}-?\d{2}-?\d{2})"
            r"(?:[-_](?P<unique>[\w.-]+))?$",
            re.IGNORECASE,
        ),
    ),
    (
        "queue-agent",
        re.compile(
            r"^(?:q|queue)[-_](?P<queue>[\w.-]+?)[-_](?:agent[-_])?(?P<agent>\d+)"
            r"[-_](?P<caller>\+?\d+)[-_](?P<date>\d{8})[-_](?P<time>\d{6})"
            r"(?:[-_](?P<unique>[\w.-]+))?$",
            re.IGNORECASE,
        ),
    ),
    (
        "asterisk-uniqueid",
        re.compile(
            r"^(?P<date>\d{8})[-_](?P<time>\d{6})[-_]"
            r"(?P<caller>\+?\d+)[-_](?P<destination>\+?\d+)"
            r"(?:[-_](?P<unique>[\d.]+))?$"
        ),
    ),
)


def _parse_datetime(date_value: str | None, time_value: str | None) -> datetime | None:
    if not date_value or not time_value:
        return None
    compact = re.sub(r"\D", "", date_value + time_value)
    try:
        return datetime.strptime(compact, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _to_metadata(groups: dict[str, str | None], parser_name: str) -> CallFileMetadata:
    direction = groups.get("direction")
    if direction:
        direction = "inbound" if direction.lower() in {"in", "inbound"} else "outbound"
    agent = groups.get("agent")
    destination = groups.get("destination")
    extension = agent or (destination if destination and len(destination) <= 6 else None)
    return CallFileMetadata(
        caller_number=normalize_phone(groups.get("caller")) or groups.get("caller"),
        destination_number=normalize_phone(destination) or destination,
        extension=extension,
        direction=direction,
        call_started_at=_parse_datetime(groups.get("date"), groups.get("time")),
        unique_call_id=groups.get("unique"),
        queue=groups.get("queue"),
        agent_extension=agent,
        parser_name=parser_name,
    )


def parse_issabel_filename(file_name: str, custom_pattern: str = "") -> CallFileMetadata:
    stem = Path(file_name).stem
    if custom_pattern:
        try:
            custom = re.fullmatch(custom_pattern, stem, flags=re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"invalid ISSABEL_FILENAME_PATTERN: {exc}") from exc
        if custom:
            return _to_metadata(custom.groupdict(), "custom")
    for name, pattern in _PATTERNS:
        match = pattern.fullmatch(stem)
        if match:
            return _to_metadata(match.groupdict(), name)
    # Unknown names are intentionally retained; callers can still use filesystem metadata.
    unique = stem if len(stem) <= 160 else None
    return CallFileMetadata(unique_call_id=unique, parser_name="fallback")
