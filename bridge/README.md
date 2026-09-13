# Mokalemeban Issabel Bridge

This bridge runs **inside the company LAN**. It never modifies Issabel.

It performs this loop:

1. `SELECT` new CDR rows from Issabel MariaDB.
2. Reads `recordingfile` from each CDR row.
3. Downloads the corresponding recording over **read-only SFTP**.
4. Waits until the recording file is stable.
5. Uploads the audio to Mokalemeban with `uniqueid` as the idempotency key.
6. Records successful uploads in a local SQLite state database so calls are not uploaded twice.

## Security model

- MariaDB access: read-only `SELECT` user.
- SFTP access: read-only account, no shell, no upload/delete.
- No Issabel port needs to be exposed to the internet.
- The bridge makes only outbound HTTPS requests to the Mokalemeban API.
- Never commit the real `.env` file.

## Windows setup

Install Python 3.12+, then from this directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python bridge.py
```

## Linux setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
python bridge.py
```

## Required configuration

Set the following in `.env`:

```env
ISSABEL_DB_HOST=192.168.1.14
ISSABEL_DB_PORT=3306
ISSABEL_DB_NAME=asteriskcdrdb
ISSABEL_DB_USER=issabel_reader
ISSABEL_DB_PASSWORD=...

ISSABEL_SFTP_HOST=192.168.1.14
ISSABEL_SFTP_PORT=22
ISSABEL_SFTP_USER=issabel_audio
ISSABEL_SFTP_PASSWORD=...
ISSABEL_SFTP_ROOT=/recordings

MOKALEMEBAN_API_URL=https://YOUR-RAILWAY-API-DOMAIN
MOKALEMEBAN_BEARER_TOKEN=

POLL_INTERVAL_SECONDS=60
RECORDING_STABILITY_SECONDS=5
```

For the first Railway pilot, when the backend is running with `ENVIRONMENT=development` and `AUTH_DISABLED=true`, the bearer token can stay blank.

For production, enable authentication and configure a dedicated service credential/token for the bridge.

## First test

1. Start the bridge.
2. Make one short real/consented test call through Issabel.
3. Wait for the CDR and recording to be finalized.
4. Within roughly one polling interval, the bridge log should show:

```text
uploaded uniqueid=... src=... dst=... status=202
```

5. The call should appear in Mokalemeban and enter the processing queue.

## Notes

- `uniqueid` is sent as `Idempotency-Key`, so retries should not create duplicate calls.
- The bridge queries with an overlap window and also keeps local processed state, which makes restarts safer.
- If Issabel stores recordings under dated subdirectories, the bridge first checks common date-based paths and then falls back to a bounded recursive lookup.
- The original remote recording is never renamed, deleted, moved, or modified.
