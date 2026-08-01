#!/usr/bin/env python3
"""Create an integrity-checked backup without copying common secret files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

ARCHIVE_PREFIX = "mokalemeban-backup-"
SCHEMA_VERSION = "1.0"
IGNORED_DIRECTORIES = {
    ".git",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".wrangler",
    "__pycache__",
    "dist",
    "node_modules",
}
SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
}
SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".jks", ".keystore"}
SECRET_ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|private[_-]?key)"
    r"\s*[:=]\s*[\"']?([^\s#\"',}]+)"
)
SAFE_PLACEHOLDERS = {
    "",
    "changeme",
    "change-me",
    "change-me-now",
    "example",
    "placeholder",
    "replace-me",
    "your-key-here",
}
LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
SERVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return sha256_stream(stream)


def sensitive_reason(path: Path) -> str | None:
    name = path.name.lower()
    if name in SENSITIVE_NAMES or (name.startswith(".env.") and name != ".env.example"):
        return "sensitive_filename"
    if path.suffix.lower() in SENSITIVE_SUFFIXES:
        return "sensitive_extension"
    if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
    for match in SECRET_ASSIGNMENT.finditer(content):
        value = match.group(1).strip().lower()
        if value not in SAFE_PLACEHOLDERS and not value.startswith("${"):
            return "likely_secret_assignment"
    return None


def parse_sources(specifications: Iterable[str]) -> list[tuple[str, Path]]:
    sources: list[tuple[str, Path]] = []
    used: set[str] = set()
    for specification in specifications:
        if "=" not in specification:
            raise ValueError(f"source must be LABEL=PATH: {specification}")
        label, raw_path = specification.split("=", 1)
        if not LABEL.fullmatch(label) or label in used:
            raise ValueError(f"invalid or duplicate source label: {label}")
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            raise ValueError(f"source does not exist: {path}")
        sources.append((label, path))
        used.add(label)
    if not sources:
        raise ValueError("at least one --source LABEL=PATH is required")
    return sources


def iter_source_files(
    label: str, source: Path
) -> Iterable[tuple[Path, PurePosixPath, str | None]]:
    if source.is_symlink():
        yield source, PurePosixPath("payload", label, source.name), "symlink"
        return
    if source.is_file():
        yield (
            source,
            PurePosixPath("payload", label, source.name),
            sensitive_reason(source),
        )
        return
    for root, directories, files in os.walk(source, followlinks=False):
        root_path = Path(root)
        kept_directories: list[str] = []
        for directory in sorted(directories):
            candidate = root_path / directory
            if directory in IGNORED_DIRECTORIES:
                continue
            if candidate.is_symlink():
                continue
            kept_directories.append(directory)
        directories[:] = kept_directories
        for filename in sorted(files):
            path = root_path / filename
            relative = path.relative_to(source)
            archive_path = PurePosixPath("payload", label, *relative.parts)
            reason = "symlink" if path.is_symlink() else sensitive_reason(path)
            yield path, archive_path, reason


def run_binary(
    command: list[str], destination: Path, input_bytes: bytes | None = None
) -> None:
    try:
        with destination.open("wb") as stream:
            completed = subprocess.run(
                command,
                input=input_bytes,
                stdout=stream,
                stderr=subprocess.PIPE,
                check=False,
            )
    except FileNotFoundError as exc:
        raise RuntimeError(f"required executable is unavailable: {command[0]}") from exc
    if completed.returncode:
        message = completed.stderr.decode("utf-8", errors="replace")[-2000:]
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"backup command failed ({completed.returncode}): {message}")


def compose_command(compose_file: Path, *arguments: str) -> list[str]:
    return ["docker", "compose", "-f", str(compose_file), *arguments]


def add_compose_artifacts(
    staging: Path,
    compose_file: Path,
    include_postgres: bool,
    include_minio: bool,
    postgres_service: str,
    postgres_user: str,
    postgres_database: str,
    minio_service: str,
) -> None:
    artifacts = staging / "artifacts"
    artifacts.mkdir(exist_ok=True)
    if include_postgres:
        if not SERVICE.fullmatch(postgres_service):
            raise ValueError("invalid PostgreSQL service name")
        run_binary(
            compose_command(
                compose_file,
                "exec",
                "-T",
                postgres_service,
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "-U",
                postgres_user,
                postgres_database,
            ),
            artifacts / "postgres.dump",
        )
    if include_minio:
        if not SERVICE.fullmatch(minio_service):
            raise ValueError("invalid MinIO service name")
        run_binary(
            compose_command(
                compose_file,
                "exec",
                "-T",
                minio_service,
                "sh",
                "-c",
                "tar -C /data -cf - .",
            ),
            artifacts / "minio-data.tar",
        )


def inventory(staging: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(
        item
        for item in staging.rglob("*")
        if item.is_file() and item.name != "manifest.json"
    ):
        entries.append(
            {
                "path": path.relative_to(staging).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return entries


def verify_archive(archive: Path) -> dict[str, Any]:
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or member.issym()
                or member.islnk()
            ):
                raise ValueError(f"unsafe archive member: {member.name}")
        try:
            manifest_member = bundle.getmember("manifest.json")
        except KeyError as exc:
            raise ValueError("manifest.json is missing") from exc
        manifest_stream = bundle.extractfile(manifest_member)
        if manifest_stream is None:
            raise ValueError("manifest.json cannot be read")
        manifest = json.load(manifest_stream)
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported manifest schema")
        member_map = {member.name: member for member in members if member.isfile()}
        for entry in manifest.get("files", []):
            member = member_map.get(entry["path"])
            if member is None:
                raise ValueError(f"missing archived file: {entry['path']}")
            stream = bundle.extractfile(member)
            if (
                stream is None
                or sha256_stream(stream) != entry["sha256"]
                or member.size != entry["size_bytes"]
            ):
                raise ValueError(f"integrity failure: {entry['path']}")
    return manifest


def create_backup(
    output_dir: Path,
    sources: list[tuple[str, Path]],
    *,
    dry_run: bool = False,
    retention_days: int = 30,
    compose_file: Path | None = None,
    include_postgres: bool = False,
    include_minio: bool = False,
    postgres_service: str = "postgres",
    postgres_user: str = "mokalemeban",
    postgres_database: str = "mokalemeban",
    minio_service: str = "minio",
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    for _, source in sources:
        if source.is_dir() and (output_dir == source or source in output_dir.parents):
            raise ValueError("output directory must not be inside a source directory")
    if retention_days < 1:
        raise ValueError("retention_days must be positive")
    if (include_postgres or include_minio) and compose_file is None:
        raise ValueError("--compose-file is required for Docker service backups")

    selected: list[tuple[Path, PurePosixPath]] = []
    exclusions: list[dict[str, str]] = []
    for label, source in sources:
        for path, archive_path, reason in iter_source_files(label, source):
            if reason:
                exclusions.append({"path": archive_path.as_posix(), "reason": reason})
            else:
                selected.append((path, archive_path))

    created = utc_now()
    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "selected_files": len(selected),
        "excluded_files": exclusions,
        "include_postgres": include_postgres,
        "include_minio": include_minio,
        "retention_days": retention_days,
    }
    if dry_run:
        return summary

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = created.strftime("%Y%m%dT%H%M%SZ")
    archive = output_dir / f"{ARCHIVE_PREFIX}{timestamp}.tar.gz"
    if archive.exists():
        raise FileExistsError(f"backup already exists: {archive}")
    with tempfile.TemporaryDirectory(prefix="mokalemeban-backup-") as temporary:
        staging = Path(temporary)
        for source, archive_path in selected:
            destination = staging.joinpath(*archive_path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        if compose_file:
            add_compose_artifacts(
                staging,
                compose_file.resolve(),
                include_postgres,
                include_minio,
                postgres_service,
                postgres_user,
                postgres_database,
                minio_service,
            )
        files = inventory(staging)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "created_at": created.isoformat(),
            "retention_days": retention_days,
            "expires_at": (created + timedelta(days=retention_days)).isoformat(),
            "source_labels": [label for label, _ in sources],
            "secret_exclusion_policy": {
                "enabled": True,
                "excluded": exclusions,
                "warning": "Content scanning is defensive, not proof that every custom secret format was detected.",
            },
            "artifacts": {
                "postgres": "artifacts/postgres.dump" if include_postgres else None,
                "object_storage": "artifacts/minio-data.tar" if include_minio else None,
            },
            "files": files,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        with tarfile.open(archive, "w:gz") as bundle:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    bundle.add(
                        path,
                        arcname=path.relative_to(staging).as_posix(),
                        recursive=False,
                    )
    verify_archive(archive)
    archive_hash = sha256_file(archive)
    sidecar = archive.with_suffix(archive.suffix + ".sha256")
    sidecar.write_text(
        f"{archive_hash}  {archive.name}\n", encoding="ascii", newline="\n"
    )
    summary.update(
        {
            "archive": str(archive),
            "archive_sha256": archive_hash,
            "sidecar": str(sidecar),
            "archived_files": len(files),
            "integrity_verified": True,
        }
    )
    return summary


def prune_expired(
    output_dir: Path, retention_days: int, now: datetime | None = None
) -> list[str]:
    output_dir = output_dir.resolve()
    if retention_days < 1 or not output_dir.is_dir():
        return []
    threshold = (now or utc_now()).timestamp() - retention_days * 86400
    removed: list[str] = []
    for archive in output_dir.glob(f"{ARCHIVE_PREFIX}*.tar.gz"):
        if archive.is_file() and archive.stat().st_mtime < threshold:
            sidecar = archive.with_suffix(archive.suffix + ".sha256")
            archive.unlink()
            sidecar.unlink(missing_ok=True)
            removed.append(archive.name)
    return removed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source", action="append", default=[], metavar="LABEL=PATH")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--prune-expired", action="store_true")
    parser.add_argument("--compose-file", type=Path)
    parser.add_argument("--include-postgres", action="store_true")
    parser.add_argument("--include-minio", action="store_true")
    parser.add_argument("--postgres-service", default="postgres")
    parser.add_argument("--postgres-user", default="mokalemeban")
    parser.add_argument("--postgres-database", default="mokalemeban")
    parser.add_argument("--minio-service", default="minio")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = create_backup(
            args.output_dir,
            parse_sources(args.source),
            dry_run=args.dry_run,
            retention_days=args.retention_days,
            compose_file=args.compose_file,
            include_postgres=args.include_postgres,
            include_minio=args.include_minio,
            postgres_service=args.postgres_service,
            postgres_user=args.postgres_user,
            postgres_database=args.postgres_database,
            minio_service=args.minio_service,
        )
        if args.prune_expired and not args.dry_run:
            summary["pruned_archives"] = prune_expired(
                args.output_dir, args.retention_days
            )
    except (OSError, ValueError, RuntimeError, tarfile.TarError) as exc:
        print(
            json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    print(json.dumps({"status": "ok", **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
