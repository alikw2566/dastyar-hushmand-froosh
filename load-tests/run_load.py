#!/usr/bin/env python3
"""Dependency-free HTTP load and soak harness for the Mokalemeban API."""

from __future__ import annotations

import argparse
import html
import json
import math
import mimetypes
import os
import platform
import shutil
import statistics
import sys
import threading
import time
import tracemalloc
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(percent / 100 * len(ordered)) - 1)
    return ordered[rank]


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def multipart(audio_path: Path, seller_email: str | None) -> tuple[bytes, str]:
    boundary = f"----mokalemeban-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    def field(name: str, value: str) -> None:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    field("recording_consent", "true")
    if seller_email:
        field("seller_email", seller_email)
    mime = mimetypes.guess_type(audio_path.name)[0] or "audio/wav"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="audio"; filename="{audio_path.name}"\r\n'.encode(),
            f"Content-Type: {mime}\r\n\r\n".encode(),
            audio_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class Runner:
    DASHBOARD_ENDPOINTS = (
        "/api/v1/overview",
        "/api/v1/calls?limit=50",
        "/api/v1/tasks",
        "/api/v1/messages",
    )

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.base_url = args.base_url.rstrip("/")
        self.results: list[dict[str, Any]] = []
        self.snapshots: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.counter = 0
        self.run_id = uuid.uuid4().hex[:12]
        self.stop = threading.Event()
        self.audio_body: tuple[bytes, str] | None = None
        if args.audio_file:
            self.audio_body = multipart(args.audio_file, args.seller_email)

    def headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "mokalemeban-load-harness/1.0",
        }
        if self.args.token:
            headers["Authorization"] = f"Bearer {self.args.token}"
        return headers

    def next_index(self) -> int:
        with self.lock:
            value = self.counter
            self.counter += 1
            return value

    def request_spec(self, index: int) -> tuple[str, str, bytes | None, dict[str, str]]:
        headers = self.headers()
        if self.args.scenario == "health":
            return "GET", "/health", None, headers
        if self.args.scenario == "dashboard":
            return (
                "GET",
                self.DASHBOARD_ENDPOINTS[index % len(self.DASHBOARD_ENDPOINTS)],
                None,
                headers,
            )
        if self.args.scenario == "upload":
            assert self.audio_body is not None
            body, content_type = self.audio_body
            headers.update(
                {
                    "Content-Type": content_type,
                    "Idempotency-Key": f"load-{self.run_id}-{index}",
                    "X-Recording-Consent": "true",
                }
            )
            return "POST", "/api/v1/calls", body, headers
        if self.args.scenario == "retry-storm":
            call_id = self.args.call_id[index % len(self.args.call_id)]
            return (
                "POST",
                f"/api/v1/calls/{urllib.parse.quote(call_id)}/reprocess",
                b"",
                headers,
            )
        endpoint = self.args.endpoint[index % len(self.args.endpoint)]
        return "GET", endpoint, None, headers

    def execute_one(self, index: int) -> None:
        method, endpoint, body, headers = self.request_spec(index)
        url = (
            f"{self.base_url}{endpoint if endpoint.startswith('/') else '/' + endpoint}"
        )
        started = time.perf_counter()
        status_code: int | None = None
        error: str | None = None
        response_bytes = 0
        try:
            request = urllib.request.Request(
                url, data=body, headers=headers, method=method
            )
            with urllib.request.urlopen(request, timeout=self.args.timeout) as response:
                status_code = response.status
                response_bytes = len(response.read())
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            response_bytes = len(exc.read())
            error = f"http_{exc.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error = type(exc).__name__
        latency_ms = (time.perf_counter() - started) * 1000
        with self.lock:
            self.results.append(
                {
                    "index": index,
                    "method": method,
                    "endpoint": endpoint,
                    "status_code": status_code,
                    "success": status_code is not None and 200 <= status_code < 400,
                    "latency_ms": round(latency_ms, 3),
                    "response_bytes": response_bytes,
                    "error": error,
                }
            )

    def worker(self, deadline: float | None) -> None:
        interval = (
            self.args.concurrency / self.args.rate_per_second
            if self.args.rate_per_second
            else 0
        )
        while not self.stop.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                return
            index = self.next_index()
            if self.args.requests is not None and index >= self.args.requests:
                return
            self.execute_one(index)
            if interval:
                self.stop.wait(interval)

    def metrics_sampler(self, deadline: float) -> None:
        while not self.stop.wait(self.args.metrics_interval):
            if time.monotonic() >= deadline:
                return
            snapshot: dict[str, Any] = {
                "at": datetime.now(timezone.utc).isoformat(),
                "harness_memory_bytes": tracemalloc.get_traced_memory()[0],
                "disk_free_bytes": shutil.disk_usage(Path.cwd()).free,
            }
            if self.args.metrics_url:
                try:
                    request = urllib.request.Request(
                        self.args.metrics_url, headers=self.headers(), method="GET"
                    )
                    with urllib.request.urlopen(
                        request, timeout=self.args.timeout
                    ) as response:
                        raw = response.read(64 * 1024).decode("utf-8", errors="replace")
                        snapshot["server_metrics_status"] = response.status
                        try:
                            snapshot["server_metrics"] = json.loads(raw)
                        except json.JSONDecodeError:
                            snapshot["server_metrics_text"] = raw
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    snapshot["server_metrics_error"] = type(exc).__name__
            with self.lock:
                self.snapshots.append(snapshot)

    def run(self) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        started = time.monotonic()
        deadline = (
            started + self.args.duration_seconds if self.args.duration_seconds else None
        )
        tracemalloc.start()
        sampler: threading.Thread | None = None
        if deadline is not None:
            sampler = threading.Thread(
                target=self.metrics_sampler, args=(deadline,), daemon=True
            )
            sampler.start()
        with ThreadPoolExecutor(max_workers=self.args.concurrency) as executor:
            futures = [
                executor.submit(self.worker, deadline)
                for _ in range(self.args.concurrency)
            ]
            for future in futures:
                future.result()
        self.stop.set()
        if sampler:
            sampler.join(timeout=2)
        current_memory, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        elapsed = time.monotonic() - started
        successes = sum(item["success"] for item in self.results)
        latencies = [item["latency_ms"] for item in self.results]
        statuses = Counter(
            str(item["status_code"] or item["error"] or "unknown")
            for item in self.results
        )
        total = len(self.results)
        error_rate = (total - successes) / total if total else None
        summary = {
            "requests": total,
            "successes": successes,
            "failures": total - successes,
            "error_rate": round(error_rate, 6) if error_rate is not None else None,
            "throughput_requests_per_second": round(total / elapsed, 3)
            if elapsed
            else None,
            "latency_ms": {
                "min": round(min(latencies), 3) if latencies else None,
                "mean": round(statistics.fmean(latencies), 3) if latencies else None,
                "p50": round(percentile(latencies, 50), 3) if latencies else None,
                "p95": round(percentile(latencies, 95), 3) if latencies else None,
                "p99": round(percentile(latencies, 99), 3) if latencies else None,
                "max": round(max(latencies), 3) if latencies else None,
            },
            "status_or_error_counts": dict(sorted(statuses.items())),
            "harness_memory_bytes": current_memory,
            "harness_peak_memory_bytes": peak_memory,
        }
        gates = {
            "max_error_rate": self.args.max_error_rate,
            "max_p95_ms": self.args.max_p95_ms,
            "passed": bool(
                total
                and error_rate is not None
                and error_rate <= self.args.max_error_rate
                and summary["latency_ms"]["p95"] <= self.args.max_p95_ms
            ),
        }
        return {
            "schema_version": "1.0",
            "status": "COMPLETED",
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 3),
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            "configuration": {
                "base_url": self.base_url,
                "scenario": self.args.scenario,
                "concurrency": self.args.concurrency,
                "requested_requests": self.args.requests,
                "requested_duration_seconds": self.args.duration_seconds,
                "rate_per_second": self.args.rate_per_second,
                "timeout_seconds": self.args.timeout,
                "token_present": bool(self.args.token),
                "audio_file": self.args.audio_file.name
                if self.args.audio_file
                else None,
            },
            "summary": summary,
            "gates": gates,
            "server_metrics_snapshots": self.snapshots,
            "requests": self.results,
            "claim_note": "Results apply only to this run and environment; they do not prove seven-day stability.",
        }


def render_html(report: dict[str, Any]) -> str:
    if report["status"] == "DRY_RUN":
        summary = (
            "این فایل فقط نمونه ساختار گزارش است و هیچ درخواست واقعی اجرا نشده است."
        )
        cards = ""
    else:
        metrics = report["summary"]
        summary = html.escape(report["claim_note"])
        cards = "".join(
            f'<div class="card"><strong>{label}</strong><div>{value}</div></div>'
            for label, value in (
                ("Requests", metrics["requests"]),
                ("Error rate", f"{metrics['error_rate']:.2%}"),
                ("p95", f"{metrics['latency_ms']['p95']:.1f} ms"),
                (
                    "Throughput",
                    f"{metrics['throughput_requests_per_second']:.2f} req/s",
                ),
            )
        )
    return f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Load/Soak report</title><style>body{{font-family:Tahoma,Arial;max-width:1000px;margin:2rem auto;padding:1rem;color:#14243b}}.notice{{background:#fff3cd;padding:1rem;border-right:5px solid #d28b00}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1rem}}.card{{border:1px solid #d9e1ea;border-radius:12px;padding:1rem}}code{{direction:ltr;unicode-bidi:embed}}</style></head><body><h1>گزارش آزمون فشار/پایداری</h1><p class="notice"><strong>{html.escape(report["status"])}</strong><br>{summary}</p><div class="grid">{cards}</div><pre>{html.escape(json.dumps(report.get("configuration", {}), ensure_ascii=False, indent=2))}</pre></body></html>"""


def validate_args(args: argparse.Namespace) -> None:
    parsed = urllib.parse.urlparse(args.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--base-url must be an absolute HTTP(S) URL")
    if args.concurrency < 1 or args.timeout <= 0 or args.metrics_interval <= 0:
        raise ValueError("concurrency and timeouts must be positive")
    if args.rate_per_second is not None and args.rate_per_second <= 0:
        raise ValueError("--rate-per-second must be positive")
    if not 0 <= args.max_error_rate <= 1 or args.max_p95_ms <= 0:
        raise ValueError("load gates are invalid")
    if args.requests is None and args.duration_seconds is None:
        raise ValueError("provide --requests or --duration-seconds")
    if args.requests is not None and args.requests < 1:
        raise ValueError("--requests must be positive")
    if args.duration_seconds is not None and args.duration_seconds <= 0:
        raise ValueError("--duration-seconds must be positive")
    if (
        args.scenario in {"dashboard", "upload", "retry-storm", "custom"}
        and not args.token
        and not args.dry_run
    ):
        raise ValueError(
            "authenticated scenario requires MOKALEMEBAN_TEST_TOKEN or --token"
        )
    if args.scenario == "upload" and (
        args.audio_file is None or not args.audio_file.is_file()
    ):
        raise ValueError("upload scenario requires an existing --audio-file")
    if args.scenario == "retry-storm" and (
        not args.allow_mutations or not args.call_id
    ):
        raise ValueError(
            "retry-storm requires --allow-mutations and at least one --call-id"
        )
    if args.scenario == "custom" and not args.endpoint:
        raise ValueError("custom scenario requires --endpoint")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--scenario",
        choices=["health", "dashboard", "upload", "retry-storm", "custom"],
        default="health",
    )
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--requests", type=int)
    parser.add_argument("--duration-seconds", type=float)
    parser.add_argument("--rate-per-second", type=float)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--metrics-url")
    parser.add_argument("--metrics-interval", type=float, default=30)
    parser.add_argument("--token", default=os.getenv("MOKALEMEBAN_TEST_TOKEN"))
    parser.add_argument("--audio-file", type=Path)
    parser.add_argument("--seller-email")
    parser.add_argument("--call-id", action="append", default=[])
    parser.add_argument("--endpoint", action="append", default=[])
    parser.add_argument("--allow-mutations", action="store_true")
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=2000)
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).resolve().parent / "results"
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_args(args)
        if args.dry_run:
            report = {
                "schema_version": "1.0",
                "status": "DRY_RUN",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "configuration": {
                    "base_url": args.base_url,
                    "scenario": args.scenario,
                    "concurrency": args.concurrency,
                    "requests": args.requests,
                    "duration_seconds": args.duration_seconds,
                    "token_present": bool(args.token),
                },
                "summary": None,
                "claim_note": "No HTTP request was executed; this is not a performance result.",
            }
        else:
            report = Runner(args).run()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        json_path = args.output_dir / f"load-report-{timestamp}.json"
        html_path = args.output_dir / f"load-report-{timestamp}.html"
        atomic_json(json_path, report)
        html_path.write_text(render_html(report), encoding="utf-8", newline="\n")
        latest_json = args.output_dir / "latest_report.json"
        latest_html = args.output_dir / "latest_report.html"
        atomic_json(latest_json, report)
        latest_html.write_text(render_html(report), encoding="utf-8", newline="\n")
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"load test failed: {exc}", file=sys.stderr)
        return 2
    print(f"report: {json_path}")
    if report["status"] == "COMPLETED" and not report["gates"]["passed"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
