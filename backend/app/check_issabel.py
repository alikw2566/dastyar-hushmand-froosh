"""Fail-safe connectivity check for the read-only Issabel integrations."""

from __future__ import annotations

import asyncio

import asyncssh
from sqlalchemy.exc import SQLAlchemyError

from .config import get_settings
from .services.cdr import IssabelCdrMatcher
from .services.watcher import DatabaseWatcherRepository, SftpRecordingWatcher


async def check() -> int:
    settings = get_settings()
    if settings.issabel_import_mode != "sftp":
        print("ERROR: ISSABEL_IMPORT_MODE must be sftp")
        return 2

    cdr = IssabelCdrMatcher()
    try:
        cdr_ok = await cdr.health()
    except (SQLAlchemyError, OSError) as exc:
        print(f"CDR: FAILED ({type(exc).__name__})")
        cdr_ok = False
    else:
        print("CDR: OK (read-only connection)")

    tenant_id = settings.issabel_default_tenant_id
    if not tenant_id:
        print("SFTP: SKIPPED (ISSABEL_DEFAULT_TENANT_ID is missing)")
        return 2

    from uuid import UUID

    watcher = SftpRecordingWatcher(
        settings,
        DatabaseWatcherRepository(UUID(tenant_id), mode="sftp"),
    )
    try:
        sftp_ok = await watcher.health()
    except (asyncssh.Error, OSError) as exc:
        print(f"SFTP: FAILED ({type(exc).__name__})")
        sftp_ok = False
    else:
        print("SFTP: OK (remote recording path is readable)")

    return 0 if cdr_ok and sftp_ok else 1


def main() -> None:
    raise SystemExit(asyncio.run(check()))


if __name__ == "__main__":
    main()
