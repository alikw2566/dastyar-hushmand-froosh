from __future__ import annotations

import logging
import mimetypes
import os
import posixpath
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import paramiko
import pymysql
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("mokalemeban-bridge")

DB_HOST = os.environ["ISSABEL_DB_HOST"]
DB_PORT = int(os.getenv("ISSABEL_DB_PORT", "3306"))
DB_NAME = os.getenv("ISSABEL_DB_NAME", "asteriskcdrdb")
DB_USER = os.environ["ISSABEL_DB_USER"]
DB_PASSWORD = os.environ["ISSABEL_DB_PASSWORD"]

SFTP_HOST = os.getenv("ISSABEL_SFTP_HOST", DB_HOST)
SFTP_PORT = int(os.getenv("ISSABEL_SFTP_PORT", "22"))
SFTP_USER = os.environ["ISSABEL_SFTP_USER"]
SFTP_PASSWORD = os.environ["ISSABEL_SFTP_PASSWORD"]
SFTP_ROOT = os.getenv("ISSABEL_SFTP_ROOT", "/recordings").rstrip("/") or "/"

API_URL = os.environ["MOKALEMEBAN_API_URL"].rstrip("/")
BEARER_TOKEN = os.getenv("MOKALEMEBAN_BEARER_TOKEN", "").strip()
POLL_INTERVAL = max(10, int(os.getenv("POLL_INTERVAL_SECONDS", "60")))
STABILITY_SECONDS = max(2, int(os.getenv("RECORDING_STABILITY_SECONDS", "5")))
OVERLAP_MINUTES = max(1, int(os.getenv("QUERY_OVERLAP_MINUTES", "10")))
STATE_DB_PATH = Path(os.getenv("STATE_DB_PATH", "bridge_state.sqlite3"))
TEMP_DIR = Path(os.getenv("TEMP_DIR", "tmp_audio"))
BATCH_LIMIT = max(1, min(500, int(os.getenv("BATCH_LIMIT", "100"))))

AUDIO_EXTENSIONS = {".wav", ".mp3", ".gsm", ".m4a", ".ogg", ".flac"}


def init_state() -> None:
    STATE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(STATE_DB_PATH) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_calls (
                uniqueid TEXT PRIMARY KEY,
                calldate TEXT NOT NULL,
                recordingfile TEXT NOT NULL,
                uploaded_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS bridge_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        db.commit()


def is_processed(uniqueid: str) -> bool:
    with sqlite3.connect(STATE_DB_PATH) as db:
        row = db.execute(
            "SELECT 1 FROM processed_calls WHERE uniqueid = ? LIMIT 1", (uniqueid,)
        ).fetchone()
    return row is not None


def mark_processed(row: dict[str, Any]) -> None:
    with sqlite3.connect(STATE_DB_PATH) as db:
        db.execute(
            """
            INSERT OR IGNORE INTO processed_calls(uniqueid, calldate, recordingfile, uploaded_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                str(row["uniqueid"]),
                str(row["calldate"]),
                str(row["recordingfile"]),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        db.execute(
            """
            INSERT INTO bridge_meta(key, value) VALUES ('last_success_calldate', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(row["calldate"]),),
        )
        db.commit()


def last_success_calldate() -> datetime:
    with sqlite3.connect(STATE_DB_PATH) as db:
        row = db.execute(
            "SELECT value FROM bridge_meta WHERE key='last_success_calldate'"
        ).fetchone()
    if not row:
        return datetime.now() - timedelta(minutes=OVERLAP_MINUTES)
    try:
        parsed = datetime.fromisoformat(str(row[0]))
    except ValueError:
        return datetime.now() - timedelta(minutes=OVERLAP_MINUTES)
    return parsed - timedelta(minutes=OVERLAP_MINUTES)


def db_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=15,
        write_timeout=5,
        autocommit=True,
    )


def fetch_new_calls() -> list[dict[str, Any]]:
    since = last_success_calldate()
    sql = """
        SELECT
            uniqueid, calldate, src, dst, duration, billsec, disposition,
            recordingfile, channel, dstchannel
        FROM cdr
        WHERE recordingfile IS NOT NULL
          AND recordingfile <> ''
          AND uniqueid IS NOT NULL
          AND uniqueid <> ''
          AND calldate >= %s
        ORDER BY calldate ASC
        LIMIT %s
    """
    with closing(db_connection()) as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, (since, BATCH_LIMIT))
            return list(cursor.fetchall())


def open_sftp():
    transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
    transport.banner_timeout = 10
    transport.auth_timeout = 10
    transport.connect(username=SFTP_USER, password=SFTP_PASSWORD)
    return transport, paramiko.SFTPClient.from_transport(transport)


def _candidate_remote_paths(recordingfile: str, calldate: datetime | None) -> list[str]:
    raw = str(recordingfile).replace("\\", "/").strip()
    name = posixpath.basename(raw)
    candidates: list[str] = []
    if raw.startswith("/"):
        candidates.append(raw)
    else:
        candidates.append(posixpath.join(SFTP_ROOT, raw))
        candidates.append(posixpath.join(SFTP_ROOT, name))
    if calldate:
        year = calldate.strftime("%Y")
        month = calldate.strftime("%m")
        day = calldate.strftime("%d")
        for parts in ((year, month, day), (year, month), (year, month, day, name)):
            path = posixpath.join(SFTP_ROOT, *parts)
            if not path.endswith(name):
                path = posixpath.join(path, name)
            candidates.append(path)
    # preserve order while removing duplicates
    return list(dict.fromkeys(candidates))


def _is_regular_file(sftp: paramiko.SFTPClient, remote_path: str) -> bool:
    try:
        attrs = sftp.stat(remote_path)
    except OSError:
        return False
    return (attrs.st_mode & 0o170000) == 0o100000


def _find_recursive(
    sftp: paramiko.SFTPClient, root: str, basename: str, max_depth: int = 5
) -> str | None:
    stack: list[tuple[str, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = sftp.listdir_attr(current)
        except OSError:
            continue
        for entry in entries:
            path = posixpath.join(current, entry.filename)
            mode = entry.st_mode & 0o170000
            if mode == 0o100000 and entry.filename == basename:
                return path
            if mode == 0o040000 and depth < max_depth and entry.filename not in {".", ".."}:
                stack.append((path, depth + 1))
    return None


def locate_recording(
    sftp: paramiko.SFTPClient, recordingfile: str, calldate: datetime | None
) -> str | None:
    for candidate in _candidate_remote_paths(recordingfile, calldate):
        if _is_regular_file(sftp, candidate):
            return candidate
    return _find_recursive(sftp, SFTP_ROOT, posixpath.basename(str(recordingfile)))


def wait_until_stable(sftp: paramiko.SFTPClient, remote_path: str) -> bool:
    try:
        first = sftp.stat(remote_path)
        if first.st_size <= 0:
            return False
        time.sleep(STABILITY_SECONDS)
        second = sftp.stat(remote_path)
    except OSError:
        return False
    return first.st_size == second.st_size and first.st_mtime == second.st_mtime


def download_temp(sftp: paramiko.SFTPClient, remote_path: str) -> Path:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(remote_path).suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        raise ValueError(f"unsupported recording extension: {suffix or '<none>'}")
    fd, temp_name = tempfile.mkstemp(prefix="issabel-", suffix=suffix, dir=TEMP_DIR)
    os.close(fd)
    target = Path(temp_name)
    try:
        sftp.get(remote_path, str(target))
        if target.stat().st_size <= 0:
            raise ValueError("downloaded recording is empty")
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def upload_to_mokalemeban(row: dict[str, Any], audio_path: Path) -> requests.Response:
    headers = {"Idempotency-Key": str(row["uniqueid"])}
    if BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {BEARER_TOKEN}"

    mime = mimetypes.guess_type(audio_path.name)[0] or "audio/wav"
    with audio_path.open("rb") as handle:
        response = requests.post(
            f"{API_URL}/api/v1/calls",
            headers=headers,
            data={"recording_consent": "true"},
            files={"audio": (Path(str(row["recordingfile"])).name, handle, mime)},
            timeout=(10, 300),
        )
    return response


def process_row(sftp: paramiko.SFTPClient, row: dict[str, Any]) -> bool:
    uniqueid = str(row.get("uniqueid") or "").strip()
    recordingfile = str(row.get("recordingfile") or "").strip()
    if not uniqueid or not recordingfile or is_processed(uniqueid):
        return False

    calldate = row.get("calldate")
    if not isinstance(calldate, datetime):
        try:
            calldate = datetime.fromisoformat(str(calldate))
        except ValueError:
            calldate = None

    remote = locate_recording(sftp, recordingfile, calldate)
    if not remote:
        logger.warning("recording_not_found uniqueid=%s recordingfile=%s", uniqueid, recordingfile)
        return False
    if not wait_until_stable(sftp, remote):
        logger.info("recording_not_stable_yet uniqueid=%s path=%s", uniqueid, remote)
        return False

    local_path: Path | None = None
    try:
        local_path = download_temp(sftp, remote)
        response = upload_to_mokalemeban(row, local_path)
        if response.status_code in {200, 201, 202}:
            mark_processed(row)
            logger.info(
                "uploaded uniqueid=%s src=%s dst=%s status=%s",
                uniqueid,
                row.get("src"),
                row.get("dst"),
                response.status_code,
            )
            return True
        logger.error(
            "upload_failed uniqueid=%s status=%s body=%s",
            uniqueid,
            response.status_code,
            response.text[:500],
        )
        return False
    finally:
        if local_path:
            local_path.unlink(missing_ok=True)


def scan_once() -> dict[str, int]:
    rows = fetch_new_calls()
    stats = {"seen": len(rows), "uploaded": 0, "skipped": 0, "errors": 0}
    if not rows:
        return stats

    transport = None
    sftp = None
    try:
        transport, sftp = open_sftp()
        for row in rows:
            try:
                if process_row(sftp, row):
                    stats["uploaded"] += 1
                else:
                    stats["skipped"] += 1
            except Exception:
                stats["errors"] += 1
                logger.exception("call_processing_failed uniqueid=%s", row.get("uniqueid"))
    finally:
        if sftp:
            sftp.close()
        if transport:
            transport.close()
    return stats


def main() -> None:
    init_state()
    logger.info(
        "bridge_started db=%s:%s/%s sftp=%s:%s root=%s api=%s poll=%ss",
        DB_HOST,
        DB_PORT,
        DB_NAME,
        SFTP_HOST,
        SFTP_PORT,
        SFTP_ROOT,
        API_URL,
        POLL_INTERVAL,
    )
    while True:
        started = time.monotonic()
        try:
            stats = scan_once()
            logger.info("scan_complete %s", stats)
        except KeyboardInterrupt:
            raise
        except Exception:
            logger.exception("scan_failed")
        elapsed = time.monotonic() - started
        time.sleep(max(1, POLL_INTERVAL - elapsed))


if __name__ == "__main__":
    main()
