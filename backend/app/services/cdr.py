"""Read-only matching against Issabel/Asterisk CDR metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from ..config import get_settings
from .filename_parser import CallFileMetadata


@dataclass(frozen=True, slots=True)
class CdrMatchResult:
    status: str
    method: str
    candidates: int
    row: dict | None = None
    error: str | None = None


class IssabelCdrMatcher:
    def __init__(self):
        self.settings = get_settings()
        self.engine = (
            create_async_engine(
                self.settings.issabel_cdr_database_url,
                pool_pre_ping=True,
                connect_args={"connect_timeout": 5},
            )
            if self.settings.issabel_cdr_database_url
            else None
        )

    async def match(self, metadata: CallFileMetadata) -> CdrMatchResult:
        if self.engine is None:
            return CdrMatchResult("unmatched", "cdr_not_configured", 0)
        table = self.settings.issabel_cdr_table
        try:
            async with self.engine.connect() as connection:
                if metadata.unique_call_id:
                    rows = (
                        (
                            await connection.execute(
                                text(
                                    f"SELECT uniqueid, src, dst, calldate, duration, disposition, "
                                    f"channel, dstchannel FROM `{table}` WHERE uniqueid=:uniqueid LIMIT 2"
                                ),
                                {"uniqueid": metadata.unique_call_id},
                            )
                        )
                        .mappings()
                        .all()
                    )
                    if len(rows) == 1:
                        return CdrMatchResult("matched", "uniqueid", 1, dict(rows[0]))
                    if len(rows) > 1:
                        return CdrMatchResult("ambiguous", "uniqueid", len(rows))
                if metadata.call_started_at and (
                    metadata.caller_number or metadata.destination_number
                ):
                    window = timedelta(seconds=self.settings.issabel_cdr_match_window_seconds)
                    rows = (
                        (
                            await connection.execute(
                                text(
                                    f"SELECT uniqueid, src, dst, calldate, duration, disposition, "
                                    f"channel, dstchannel FROM `{table}` "
                                    "WHERE calldate BETWEEN :start AND :end "
                                    "AND (:src IS NULL OR src=:src) AND (:dst IS NULL OR dst=:dst) "
                                    "ORDER BY ABS(TIMESTAMPDIFF(SECOND, calldate, :at)) LIMIT 3"
                                ),
                                {
                                    "start": metadata.call_started_at - window,
                                    "end": metadata.call_started_at + window,
                                    "at": metadata.call_started_at,
                                    "src": metadata.caller_number,
                                    "dst": metadata.destination_number,
                                },
                            )
                        )
                        .mappings()
                        .all()
                    )
                    if len(rows) == 1:
                        return CdrMatchResult("matched", "time_and_numbers", 1, dict(rows[0]))
                    if len(rows) > 1:
                        return CdrMatchResult("ambiguous", "time_and_numbers", len(rows))
        except (SQLAlchemyError, OSError) as exc:
            return CdrMatchResult("unmatched", "cdr_error", 0, error=str(exc)[:1000])
        return CdrMatchResult("unmatched", "no_candidate", 0)

    async def health(self) -> bool:
        if self.engine is None:
            return False
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True

    @staticmethod
    def extension(channel: object) -> str | None:
        match = re.search(r"/(\d+)(?:[-@]|$)", str(channel or ""))
        return match.group(1) if match else None


cdr_matcher = IssabelCdrMatcher()
