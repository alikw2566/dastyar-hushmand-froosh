"""Polling watchers for mounted folders and read-only Issabel SFTP accounts."""

from __future__ import annotations

import hashlib
import mimetypes
import posixpath
import shutil
import socket
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncssh
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from ..config import Settings
from ..database import tenant_session
from ..models import Call, CallStatus, CdrMatch, SourceImport, WatcherHeartbeat
from ..tasks import process_call
from .audio import validate_audio
from .cdr import cdr_matcher
from .filename_parser import CallFileMetadata, parse_issabel_filename
from .pipeline import PipelineFailure
from .storage import storage


@dataclass(frozen=True, slots=True)
class ImportResult:
    status: str
    call_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class DurableObservation:
    stable: bool
    detected_at: datetime


@dataclass(frozen=True, slots=True)
class RemoteRecording:
    path: str
    name: str
    size: int
    mtime_ns: int


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class WatcherRepository(Protocol):
    async def observe(
        self,
        source_identifier: str,
        path: Path,
        observed_at: datetime,
        stability_seconds: int,
    ) -> DurableObservation: ...
    async def observe_source(
        self,
        source_identifier: str,
        file_name: str,
        size: int,
        mtime_ns: int,
        observed_at: datetime,
        stability_seconds: int,
    ) -> DurableObservation: ...
    async def is_source_processed(self, source_identifier: str) -> bool: ...
    async def is_duplicate(self, source_identifier: str, sha256: str) -> bool: ...
    async def mark_duplicate(self, source_identifier: str, sha256: str) -> None: ...
    async def import_file(
        self,
        path: Path,
        source_identifier: str,
        sha256: str,
        detected_at: datetime,
        metadata: CallFileMetadata,
    ) -> ImportResult: ...
    async def quarantine(
        self,
        path: Path,
        source_identifier: str,
        sha256: str,
        detected_at: datetime,
        error: PipelineFailure,
        quarantine_path: Path,
    ) -> None: ...
    async def heartbeat(self, status: str, metrics: dict, error: str | None = None) -> None: ...


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_file_name(path: Path, source_identifier: str) -> str:
    if source_identifier.startswith("sftp://"):
        return PurePosixPath(urlsplit(source_identifier).path).name
    return path.name


class LocalRecordingWatcher:
    def __init__(
        self,
        settings: Settings,
        repository: WatcherRepository,
    ):
        self.settings = settings
        self.repository = repository
        self.root = Path(settings.issabel_recordings_path).expanduser().resolve()
        self.quarantine_root = Path(settings.issabel_quarantine_path).expanduser().resolve()
        self.metrics = {
            "discovered": 0,
            "imported": 0,
            "duplicates": 0,
            "quarantined": 0,
            "waiting": 0,
            "errors": 0,
        }

    def _candidate_paths(self) -> list[Path]:
        if not self.root.is_dir():
            raise FileNotFoundError(f"recordings path does not exist: {self.root}")
        temporary = {
            item if item.startswith(".") else f".{item}"
            for item in (
                part.strip().lower()
                for part in self.settings.issabel_temporary_extensions.split(",")
            )
            if item
        }
        paths = []
        for path in self.root.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            resolved = path.resolve()
            if self.root not in resolved.parents or self.quarantine_root in resolved.parents:
                continue
            suffix = path.suffix.lower()
            if suffix in temporary or suffix not in self.settings.issabel_extensions:
                continue
            paths.append(resolved)
        return sorted(paths)

    async def scan_once(self) -> dict:
        scan_started = datetime.now(UTC)
        self.metrics["waiting"] = 0
        try:
            for path in self._candidate_paths():
                self.metrics["discovered"] += 1
                observation = await self.repository.observe(
                    str(path), path, datetime.now(UTC), self.settings.issabel_file_stability_seconds
                )
                if not observation.stable:
                    self.metrics["waiting"] += 1
                    continue
                source_identifier = str(path)
                digest = sha256_file(path)
                if await self.repository.is_duplicate(source_identifier, digest):
                    self.metrics["duplicates"] += 1
                    continue
                detected_at = observation.detected_at
                try:
                    validate_audio(
                        path,
                        allowed_extensions=self.settings.issabel_extensions,
                        max_bytes=self.settings.max_audio_bytes,
                        min_duration_seconds=self.settings.audio_min_duration_seconds,
                        ffprobe_path=self.settings.audio_ffprobe_path,
                    )
                    metadata = parse_issabel_filename(
                        path.name, self.settings.issabel_filename_pattern
                    )
                    result = await self.repository.import_file(
                        path, source_identifier, digest, detected_at, metadata
                    )
                    if result.status == "imported":
                        self.metrics["imported"] += 1
                    else:
                        self.metrics["duplicates"] += 1
                except PipelineFailure as exc:
                    await self.repository.quarantine(
                        path,
                        source_identifier,
                        digest,
                        detected_at,
                        exc,
                        self.quarantine_root,
                    )
                    self.metrics["quarantined"] += 1
            await self.repository.heartbeat(
                "healthy", {**self.metrics, "scan_started_at": scan_started.isoformat()}
            )
        except Exception as exc:
            self.metrics["errors"] += 1
            await self.repository.heartbeat("degraded", self.metrics.copy(), str(exc)[:1000])
            raise
        return self.metrics.copy()


class SftpRecordingWatcher:
    """Read recordings over SFTP without requesting shell or write access."""

    def __init__(self, settings: Settings, repository: WatcherRepository):
        self.settings = settings
        self.repository = repository
        self.staging_root = Path(settings.issabel_sftp_staging_path).expanduser().resolve()
        self.quarantine_root = Path(settings.issabel_quarantine_path).expanduser().resolve()
        self.metrics = {
            "discovered": 0,
            "downloaded": 0,
            "imported": 0,
            "duplicates": 0,
            "quarantined": 0,
            "waiting": 0,
            "errors": 0,
        }

    @property
    def _temporary_extensions(self) -> frozenset[str]:
        return frozenset(
            item if item.startswith(".") else f".{item}"
            for item in (
                part.strip().lower()
                for part in self.settings.issabel_temporary_extensions.split(",")
            )
            if item
        )

    async def _candidate_recordings(self, sftp) -> list[RemoteRecording]:
        root = str(PurePosixPath(self.settings.issabel_sftp_remote_path))
        pending = [(root, 0)]
        recordings: list[RemoteRecording] = []
        while pending and len(recordings) < self.settings.issabel_sftp_max_files_per_scan:
            current, depth = pending.pop()
            async for entry in sftp.scandir(current):
                name = entry.filename
                if name in {".", ".."} or PurePosixPath(name).name != name:
                    continue
                remote_path = posixpath.join(current, name)
                mode = entry.attrs.permissions or 0
                file_type = entry.attrs.type
                is_directory = stat.S_ISDIR(mode) or file_type == asyncssh.FILEXFER_TYPE_DIRECTORY
                is_regular = stat.S_ISREG(mode) or file_type == asyncssh.FILEXFER_TYPE_REGULAR
                if is_directory:
                    if depth < self.settings.issabel_sftp_max_depth:
                        pending.append((remote_path, depth + 1))
                    continue
                if not is_regular:
                    continue
                suffix = PurePosixPath(name).suffix.lower()
                if (
                    suffix in self._temporary_extensions
                    or suffix not in self.settings.issabel_extensions
                ):
                    continue
                recordings.append(
                    RemoteRecording(
                        path=remote_path,
                        name=name,
                        size=int(entry.attrs.size or 0),
                        mtime_ns=int(entry.attrs.mtime or 0) * 1_000_000_000,
                    )
                )
                if len(recordings) >= self.settings.issabel_sftp_max_files_per_scan:
                    break
        return sorted(recordings, key=lambda item: item.path)

    async def _scan_client(self, sftp) -> None:
        self.staging_root.mkdir(parents=True, exist_ok=True)
        for remote in await self._candidate_recordings(sftp):
            self.metrics["discovered"] += 1
            source_identifier = (
                f"sftp://{self.settings.issabel_sftp_host}:"
                f"{self.settings.issabel_sftp_port}{remote.path}"
            )
            if await self.repository.is_source_processed(source_identifier):
                self.metrics["duplicates"] += 1
                continue
            observation = await self.repository.observe_source(
                source_identifier,
                remote.name,
                remote.size,
                remote.mtime_ns,
                datetime.now(UTC),
                self.settings.issabel_file_stability_seconds,
            )
            if not observation.stable:
                self.metrics["waiting"] += 1
                continue
            local_path = self.staging_root / f"{uuid4().hex}-{remote.name}"
            try:
                await sftp.get(remote.path, str(local_path), preserve=False)
                self.metrics["downloaded"] += 1
                digest = sha256_file(local_path)
                if await self.repository.is_duplicate(source_identifier, digest):
                    await self.repository.mark_duplicate(source_identifier, digest)
                    self.metrics["duplicates"] += 1
                    continue
                try:
                    validate_audio(
                        local_path,
                        allowed_extensions=self.settings.issabel_extensions,
                        max_bytes=self.settings.max_audio_bytes,
                        min_duration_seconds=self.settings.audio_min_duration_seconds,
                        ffprobe_path=self.settings.audio_ffprobe_path,
                    )
                    metadata = parse_issabel_filename(
                        remote.name, self.settings.issabel_filename_pattern
                    )
                    result = await self.repository.import_file(
                        local_path, source_identifier, digest, observation.detected_at, metadata
                    )
                    self.metrics["imported" if result.status == "imported" else "duplicates"] += 1
                except PipelineFailure as exc:
                    await self.repository.quarantine(
                        local_path,
                        source_identifier,
                        digest,
                        observation.detected_at,
                        exc,
                        self.quarantine_root,
                    )
                    self.metrics["quarantined"] += 1
            finally:
                local_path.unlink(missing_ok=True)

    def _connection_options(self) -> dict:
        known_hosts = None
        if not self.settings.issabel_sftp_allow_insecure_host_key:
            known_hosts_path = Path(self.settings.issabel_sftp_known_hosts)
            if not known_hosts_path.is_file():
                raise FileNotFoundError(f"SFTP known_hosts file not found: {known_hosts_path}")
            known_hosts = str(known_hosts_path)
        return {
            "port": self.settings.issabel_sftp_port,
            "username": self.settings.issabel_sftp_username,
            "password": self.settings.resolved_issabel_sftp_password or None,
            "client_keys": [self.settings.issabel_sftp_private_key]
            if self.settings.issabel_sftp_private_key
            else None,
            "known_hosts": known_hosts,
            "login_timeout": 10,
        }

    async def health(self) -> bool:
        async with (
            asyncssh.connect(
                self.settings.issabel_sftp_host, **self._connection_options()
            ) as connection,
            connection.start_sftp_client() as sftp,
        ):
            await sftp.stat(self.settings.issabel_sftp_remote_path)
        return True

    async def scan_once(self) -> dict:
        scan_started = datetime.now(UTC)
        self.metrics["waiting"] = 0
        try:
            async with (
                asyncssh.connect(
                    self.settings.issabel_sftp_host,
                    **self._connection_options(),
                ) as connection,
                connection.start_sftp_client() as sftp,
            ):
                await self._scan_client(sftp)
            await self.repository.heartbeat(
                "healthy", {**self.metrics, "scan_started_at": scan_started.isoformat()}
            )
        except Exception as exc:
            self.metrics["errors"] += 1
            await self.repository.heartbeat("degraded", self.metrics.copy(), str(exc)[:1000])
            raise
        return self.metrics.copy()


class DatabaseWatcherRepository:
    def __init__(
        self,
        tenant_id: UUID,
        *,
        watcher_id: str | None = None,
        mode: str = "local",
        session_provider=None,
    ):
        self.tenant_id = tenant_id
        self.watcher_id = watcher_id or f"{socket.gethostname()}-issabel"
        self.mode = mode
        self.session_provider = session_provider or tenant_session

    async def is_source_processed(self, source_identifier: str) -> bool:
        async for session in self.session_provider(str(self.tenant_id)):
            row = await session.scalar(
                select(SourceImport.id).where(
                    SourceImport.tenant_id == self.tenant_id,
                    SourceImport.source_identifier == source_identifier,
                    SourceImport.status.in_(["imported", "quarantined"]),
                )
            )
            return row is not None
        return False

    async def is_duplicate(self, source_identifier: str, sha256: str) -> bool:
        async for session in self.session_provider(str(self.tenant_id)):
            row = await session.scalar(
                select(SourceImport.id).where(
                    SourceImport.tenant_id == self.tenant_id,
                    SourceImport.status.in_(["imported", "quarantined"]),
                    or_(
                        SourceImport.source_identifier == source_identifier,
                        SourceImport.sha256 == sha256,
                    ),
                )
            )
            return row is not None
        return False

    async def observe(
        self,
        source_identifier: str,
        path: Path,
        observed_at: datetime,
        stability_seconds: int,
    ) -> DurableObservation:
        stat = path.stat()
        return await self.observe_source(
            source_identifier,
            path.name,
            stat.st_size,
            stat.st_mtime_ns,
            observed_at,
            stability_seconds,
        )

    async def observe_source(
        self,
        source_identifier: str,
        file_name: str,
        size: int,
        mtime_ns: int,
        observed_at: datetime,
        stability_seconds: int,
    ) -> DurableObservation:
        async for session in self.session_provider(str(self.tenant_id)):
            row = await session.scalar(
                select(SourceImport).where(
                    SourceImport.tenant_id == self.tenant_id,
                    SourceImport.source_identifier == source_identifier,
                )
            )
            if row is None:
                row = SourceImport(
                    tenant_id=self.tenant_id,
                    source_identifier=source_identifier,
                    source_path=source_identifier,
                    file_name=file_name,
                    size_bytes=size,
                    sha256=None,
                    observed_size=size,
                    observed_mtime_ns=mtime_ns,
                    stable_since=observed_at,
                    status="waiting_for_file",
                    detected_at=observed_at,
                )
                session.add(row)
                await session.commit()
                return DurableObservation(False, observed_at)
            if row.status in {"imported", "quarantined"}:
                return DurableObservation(True, _as_utc(row.detected_at))
            if row.observed_size != size or row.observed_mtime_ns != mtime_ns:
                row.size_bytes = size
                row.observed_size = size
                row.observed_mtime_ns = mtime_ns
                row.stable_since = observed_at
                row.status = "waiting_for_file"
                await session.commit()
                return DurableObservation(False, _as_utc(row.detected_at))
            stable_since = _as_utc(row.stable_since or observed_at)
            stable = (_as_utc(observed_at) - stable_since).total_seconds() >= stability_seconds
            row.status = "discovered" if stable else "waiting_for_file"
            await session.commit()
            return DurableObservation(stable, _as_utc(row.detected_at))
        raise RuntimeError("database session unavailable")

    async def mark_duplicate(self, source_identifier: str, sha256: str) -> None:
        async for session in self.session_provider(str(self.tenant_id)):
            existing = await session.scalar(
                select(SourceImport).where(
                    SourceImport.tenant_id == self.tenant_id,
                    SourceImport.sha256 == sha256,
                    SourceImport.status == "imported",
                )
            )
            source = await session.scalar(
                select(SourceImport).where(
                    SourceImport.tenant_id == self.tenant_id,
                    SourceImport.source_identifier == source_identifier,
                )
            )
            if source is not None:
                source.sha256 = sha256
                source.call_id = existing.call_id if existing else None
                source.status = "imported"
                source.imported_at = datetime.now(UTC)
                await session.commit()
            return

    async def import_file(
        self,
        path: Path,
        source_identifier: str,
        sha256: str,
        detected_at: datetime,
        metadata: CallFileMetadata,
    ) -> ImportResult:
        original_name = source_file_name(path, source_identifier)
        cdr = await cdr_matcher.match(metadata, recording_file=original_name)
        cdr_row = cdr.row or {}
        agent_extension = metadata.agent_extension or cdr_matcher.extension(
            cdr_row.get("dstchannel") or cdr_row.get("channel")
        )
        async for session in self.session_provider(str(self.tenant_id)):
            call = Call(
                tenant_id=self.tenant_id,
                external_id=str(
                    cdr_row.get("uniqueid") or metadata.unique_call_id or f"issabel:{sha256}"
                ),
                original_file_name=original_name,
                object_key="pending",
                mime_type=mimetypes.guess_type(original_name)[0] or "application/octet-stream",
                size_bytes=path.stat().st_size,
                source="issabel",
                source_path=source_identifier,
                source_hash=sha256,
                detected_at=detected_at,
                imported_at=datetime.now(UTC),
                call_started_at=cdr_row.get("calldate") or metadata.call_started_at,
                caller_number=str(cdr_row.get("src") or metadata.caller_number or "") or None,
                destination_number=str(cdr_row.get("dst") or metadata.destination_number or "")
                or None,
                extension=metadata.extension,
                agent_extension=agent_extension,
                direction=metadata.direction,
                queue_name=metadata.queue,
                status=CallStatus.uploaded,
            )
            session.add(call)
            try:
                await session.flush()
                session.add(
                    CdrMatch(
                        tenant_id=self.tenant_id,
                        call_id=call.id,
                        status=cdr.status,
                        match_method=cdr.method,
                        candidate_count=cdr.candidates,
                        uniqueid=str(cdr_row.get("uniqueid") or "") or None,
                        cdr_json={
                            key: str(value) if value is not None else None
                            for key, value in cdr_row.items()
                        }
                        or None,
                        error_message=cdr.error,
                    )
                )
                with path.open("rb") as handle:
                    call.object_key = await storage.upload(
                        self.tenant_id, call.id, original_name, call.mime_type, handle
                    )
                call.status = CallStatus.queued
                source = await session.scalar(
                    select(SourceImport).where(
                        SourceImport.tenant_id == self.tenant_id,
                        SourceImport.source_identifier == source_identifier,
                    )
                )
                if source is None:
                    source = SourceImport(
                        tenant_id=self.tenant_id,
                        source_identifier=source_identifier,
                        source_path=source_identifier,
                        file_name=path.name,
                        detected_at=detected_at,
                    )
                    session.add(source)
                source.call_id = call.id
                source.size_bytes = path.stat().st_size
                source.observed_size = source.size_bytes
                source.observed_mtime_ns = path.stat().st_mtime_ns
                source.sha256 = sha256
                source.status = "imported"
                source.imported_at = call.imported_at
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return ImportResult("duplicate", reason="database_unique_constraint")
            process_call.delay(str(call.id), str(self.tenant_id), "resume")
            return ImportResult("imported", str(call.id))
        raise RuntimeError("database session unavailable")

    async def quarantine(
        self,
        path: Path,
        source_identifier: str,
        sha256: str,
        detected_at: datetime,
        error: PipelineFailure,
        quarantine_path: Path,
    ) -> None:
        quarantine_path.mkdir(parents=True, exist_ok=True)
        target = (quarantine_path / f"{sha256[:12]}-{path.name}").resolve()
        if quarantine_path.resolve() not in target.parents:
            raise RuntimeError("unsafe quarantine target")
        shutil.move(str(path), str(target))
        async for session in self.session_provider(str(self.tenant_id)):
            source = await session.scalar(
                select(SourceImport).where(
                    SourceImport.tenant_id == self.tenant_id,
                    SourceImport.source_identifier == source_identifier,
                )
            )
            if source is None:
                source = SourceImport(
                    tenant_id=self.tenant_id,
                    source_identifier=source_identifier,
                    source_path=source_identifier,
                    file_name=path.name,
                    detected_at=detected_at,
                )
                session.add(source)
            source.size_bytes = target.stat().st_size
            source.observed_size = source.size_bytes
            source.sha256 = sha256
            source.status = "quarantined"
            source.imported_at = datetime.now(UTC)
            source.quarantine_path = str(target)
            source.error_code = error.descriptor.code
            source.error_message = str(error)
            await session.commit()

    async def heartbeat(self, status: str, metrics: dict, error: str | None = None) -> None:
        async for session in self.session_provider(str(self.tenant_id)):
            row = await session.get(WatcherHeartbeat, self.watcher_id)
            now = datetime.now(UTC)
            if row is None:
                row = WatcherHeartbeat(
                    watcher_id=self.watcher_id,
                    tenant_id=self.tenant_id,
                    host=socket.gethostname(),
                    mode=self.mode,
                )
                session.add(row)
            row.status = status
            row.last_scan_at = now
            if status == "healthy":
                row.last_success_at = now
            row.last_error = error
            row.metrics_json = metrics
            await session.commit()
