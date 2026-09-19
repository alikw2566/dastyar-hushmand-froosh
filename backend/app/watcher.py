"""Issabel watcher service with its own HTTP health surface on port 8010."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

import uvicorn
from fastapi import FastAPI, HTTPException, Response

from .config import get_settings
from .services.logging import configure_logging, get_logger
from .services.watcher import DatabaseWatcherRepository, LocalRecordingWatcher, SftpRecordingWatcher

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)
runtime = {"started_at": datetime.now(UTC), "last_scan_at": None, "last_error": None, "metrics": {}}


def build_watcher() -> LocalRecordingWatcher | SftpRecordingWatcher:
    tenant_value = settings.issabel_default_tenant_id
    if not tenant_value:
        raise RuntimeError(
            "ISSABEL_DEFAULT_TENANT_ID is required and must match DEFAULT_TENANT_ID used by bootstrap"
        )
    repository = DatabaseWatcherRepository(
        UUID(tenant_value), mode=settings.issabel_import_mode
    )
    if settings.issabel_import_mode == "sftp":
        return SftpRecordingWatcher(settings, repository)
    return LocalRecordingWatcher(settings, repository)


async def _scan_loop(watcher: LocalRecordingWatcher | SftpRecordingWatcher) -> None:
    while True:
        try:
            runtime["metrics"] = await watcher.scan_once()
            runtime["last_scan_at"] = datetime.now(UTC)
            runtime["last_error"] = None
        except Exception as exc:  # boundary logs and keeps the long-running service alive
            runtime["last_error"] = str(exc)[:1000]
            logger.exception("watcher_scan_failed")
        await asyncio.sleep(settings.issabel_poll_interval)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.issabel_import_mode == "disabled":
        task = None
    else:
        task = asyncio.create_task(_scan_loop(build_watcher()), name="issabel-scan-loop")
    try:
        yield
    finally:
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="Mokalemeban Issabel Watcher", lifespan=lifespan)


@app.get("/health/live")
async def live():
    return {"status": "ok", "service": "issabel-watcher"}


@app.get("/health/ready")
async def ready():
    if settings.issabel_import_mode == "disabled":
        raise HTTPException(status_code=503, detail="watcher_disabled")
    if runtime["last_error"]:
        raise HTTPException(status_code=503, detail="watcher_degraded")
    return {"status": "ready", "last_scan_at": runtime["last_scan_at"]}


@app.get("/metrics")
async def metrics():
    lines = [
        f"mokalemeban_watcher_{key} {value}"
        for key, value in runtime["metrics"].items()
        if isinstance(value, (int, float))
    ]
    lines.append(f"mokalemeban_watcher_up {0 if runtime['last_error'] else 1}")
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


def main() -> None:
    uvicorn.run("app.watcher:app", host="0.0.0.0", port=8010, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
