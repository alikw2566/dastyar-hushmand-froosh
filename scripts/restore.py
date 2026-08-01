#!/usr/bin/env python3
"""Verify and restore backups created by scripts/backup.py."""

from __future__ import annotations

import argparse
import hmac
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from scripts.backup import SERVICE, sha256_file, verify_archive
except ModuleNotFoundError:  # direct execution from scripts/
    from backup import SERVICE, sha256_file, verify_archive


def verify_sidecar(archive: Path) -> None:
    sidecar = archive.with_suffix(archive.suffix + ".sha256")
    if not sidecar.is_file():
        raise ValueError(f"checksum sidecar is missing: {sidecar}")
    parts = sidecar.read_text(encoding="ascii").strip().split()
    if len(parts) < 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
        raise ValueError("invalid checksum sidecar")
    if parts[-1] != archive.name:
        raise ValueError("checksum sidecar references a different archive")
    if not hmac.compare_digest(parts[0].lower(), sha256_file(archive)):
        raise ValueError("archive checksum does not match sidecar")


def safe_destination(root: Path, member_name: str) -> Path:
    parts = PurePosixPath(member_name).parts
    if not parts or PurePosixPath(member_name).is_absolute() or ".." in parts:
        raise ValueError(f"unsafe archive path: {member_name}")
    destination = root.joinpath(*parts).resolve()
    if destination != root and root not in destination.parents:
        raise ValueError(f"archive path escapes target: {member_name}")
    return destination


def extract_payload(archive: Path, temporary: Path) -> None:
    root = temporary.resolve()
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            if not member.isfile() or not member.name.startswith("payload/"):
                continue
            destination = safe_destination(root, member.name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise ValueError(f"cannot read archive member: {member.name}")
            with destination.open("wb") as output:
                shutil.copyfileobj(source, output)


def artifact_bytes(archive: Path, member_name: str) -> bytes:
    with tarfile.open(archive, "r:gz") as bundle:
        try:
            member = bundle.getmember(member_name)
        except KeyError as exc:
            raise ValueError(f"backup does not contain {member_name}") from exc
        stream = bundle.extractfile(member)
        if stream is None:
            raise ValueError(f"cannot read {member_name}")
        return stream.read()


def run_restore(command: list[str], content: bytes) -> None:
    try:
        completed = subprocess.run(
            command, input=content, capture_output=True, check=False
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"required executable is unavailable: {command[0]}") from exc
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace")[-2000:]
        raise RuntimeError(f"restore command failed ({completed.returncode}): {detail}")


def restore_backup(
    archive: Path,
    target: Path,
    *,
    apply: bool = False,
    overwrite: bool = False,
    verify_checksum: bool = True,
    compose_file: Path | None = None,
    restore_postgres: bool = False,
    restore_minio: bool = False,
    postgres_service: str = "postgres",
    postgres_user: str = "mokalemeban",
    postgres_database: str = "mokalemeban",
    minio_service: str = "minio",
    confirm_database: str | None = None,
    confirm_object_storage: str | None = None,
) -> dict[str, Any]:
    archive = archive.resolve()
    target = target.resolve()
    if verify_checksum:
        verify_sidecar(archive)
    manifest = verify_archive(archive)
    payload = [
        item for item in manifest["files"] if item["path"].startswith("payload/")
    ]
    summary: dict[str, Any] = {
        "dry_run": not apply,
        "archive": str(archive),
        "target": str(target),
        "payload_files": len(payload),
        "source_labels": manifest.get("source_labels", []),
        "database_available": bool(manifest.get("artifacts", {}).get("postgres")),
        "object_storage_available": bool(
            manifest.get("artifacts", {}).get("object_storage")
        ),
        "integrity_verified": True,
    }
    if not apply:
        return summary
    if restore_postgres and confirm_database != postgres_database:
        raise ValueError("--confirm-database must exactly match --postgres-database")
    if restore_minio and confirm_object_storage != "RESTORE":
        raise ValueError("--confirm-object-storage RESTORE is required")
    if (restore_postgres or restore_minio) and compose_file is None:
        raise ValueError("--compose-file is required for service restore")
    for service in (postgres_service, minio_service):
        if not SERVICE.fullmatch(service):
            raise ValueError("invalid Docker service name")

    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mokalemeban-restore-") as temporary:
        extracted = Path(temporary)
        extract_payload(archive, extracted)
        payload_root = extracted / "payload"
        if payload_root.exists():
            copies = [
                (
                    source,
                    safe_destination(
                        target, source.relative_to(payload_root).as_posix()
                    ),
                )
                for source in sorted(payload_root.rglob("*"))
                if source.is_file()
            ]
            conflicts = [
                destination for _, destination in copies if destination.exists()
            ]
            if conflicts and not overwrite:
                preview = ", ".join(str(item) for item in conflicts[:3])
                raise FileExistsError(
                    f"restore target exists; use --overwrite: {preview}"
                )
            for source, destination in copies:
                if destination.exists() and not overwrite:
                    raise FileExistsError(
                        f"restore target exists; use --overwrite: {destination}"
                    )
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)

    compose = (
        ["docker", "compose", "-f", str(compose_file.resolve())] if compose_file else []
    )
    if restore_postgres:
        dump = artifact_bytes(archive, "artifacts/postgres.dump")
        run_restore(
            compose
            + [
                "exec",
                "-T",
                postgres_service,
                "pg_restore",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-acl",
                "-U",
                postgres_user,
                "-d",
                postgres_database,
            ],
            dump,
        )
        summary["database_restored"] = True
    if restore_minio:
        data = artifact_bytes(archive, "artifacts/minio-data.tar")
        run_restore(
            compose + ["exec", "-T", minio_service, "sh", "-c", "tar -C /data -xf -"],
            data,
        )
        summary["object_storage_restored"] = True
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument(
        "--apply", action="store_true", help="perform restore; default is dry-run"
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--ignore-sidecar", action="store_true")
    parser.add_argument("--compose-file", type=Path)
    parser.add_argument("--restore-postgres", action="store_true")
    parser.add_argument("--restore-minio", action="store_true")
    parser.add_argument("--postgres-service", default="postgres")
    parser.add_argument("--postgres-user", default="mokalemeban")
    parser.add_argument("--postgres-database", default="mokalemeban")
    parser.add_argument("--minio-service", default="minio")
    parser.add_argument("--confirm-database")
    parser.add_argument("--confirm-object-storage")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = restore_backup(
            args.archive,
            args.target,
            apply=args.apply,
            overwrite=args.overwrite,
            verify_checksum=not args.ignore_sidecar,
            compose_file=args.compose_file,
            restore_postgres=args.restore_postgres,
            restore_minio=args.restore_minio,
            postgres_service=args.postgres_service,
            postgres_user=args.postgres_user,
            postgres_database=args.postgres_database,
            minio_service=args.minio_service,
            confirm_database=args.confirm_database,
            confirm_object_storage=args.confirm_object_storage,
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
