#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///
"""MinerU CLI — parse PDF / Office / image files into clean Markdown.

Zero-dependency (Python standard library only) and AI-Native. The tool picks the
right MinerU backend automatically:

  * no token              -> Agent API   (free, no login; <=10 MB, <=20 pages)
  * token + small file    -> Agent API   (fast & free, auto-escalates on limits)
  * token + big/batch/fmt -> Standard v4 (<=200 MB, <=200 pages, docx/html/latex)

Token:  https://mineru.net/apiManage/token
Docs:   https://mineru.net/apiManage/docs

Examples
--------
    # Zero-config single file (no token needed)
    python3 mineru.py paper.pdf

    # Pipe the Markdown straight back to an agent
    python3 mineru.py paper.pdf --stdout

    # Batch a directory with a token (Standard API, parallel)
    export MINERU_TOKEN=...
    python3 mineru.py ./pdfs/ --output ./out/ --workers 8 --resume

    # Parse a remote URL and also export DOCX
    python3 mineru.py https://example.com/doc.pdf --format docx
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import random
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Optional

__version__ = "3.3.1"

# --------------------------------------------------------------------------- #
# Constants (kept in sync with https://mineru.net/apiManage/docs)
# --------------------------------------------------------------------------- #
STANDARD_API = "https://mineru.net/api/v4"
AGENT_API = "https://mineru.net/api/v1/agent"

AGENT_MAX_BYTES = 10 * 1024 * 1024      # 10 MB
AGENT_MAX_PAGES = 20
STANDARD_MAX_BYTES = 200 * 1024 * 1024  # 200 MB
STANDARD_MAX_PAGES = 200
BATCH_MAX_FILES = 50                    # per Standard batch request
FREE_DAILY_PAGES = 1000                 # highest-priority quota / day

USER_AGENT = f"MinerU-Skill/{__version__}"

# Reliability tuning ---------------------------------------------------------- #
# Transient HTTP statuses worth a backed-off retry (never business code != 0).
RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}
RETRY_MAX_ATTEMPTS = 4                  # total tries per request (1 + 3 retries)
RETRY_BASE_DELAY = 0.5                  # seconds; doubles each attempt
RETRY_MAX_DELAY = 20.0                  # backoff ceiling
DEFAULT_POLL_INTERVAL = 2.0             # seconds between status polls
POLL_INTERVAL_CAP = 15.0                # adaptive backoff ceiling while polling
DEFAULT_WORKERS = 8                     # decoupled submit/poll lifts the old thread-bound ceiling
# Cap for poll/submit network calls. A single stalled request must not wedge the
# single-threaded poll loop for the whole per-parse budget — that budget lives in
# job.deadline; the per-request socket timeout is bounded here. Downloads/uploads
# (large zips) keep the full timeout.
REQUEST_TIMEOUT_CAP = 30.0

# Business-layer API codes that are worth a bounded retry. Authentication,
# quota, and file-limit failures are intentionally absent: those need user action
# or a different input, so retrying only burns time/quota.
RETRYABLE_API_CODES = {-10001, -60001, -60007, -60009}
FATAL_API_CODES = {"A0202", "A0211", -60005, -60006, -60017, -60018, -60019}
# Daily-quota / retry-limit codes. Once any submit hits one of these the whole run
# is doomed for the day, so trip a circuit breaker and skip the remaining submits
# instead of firing N more doomed requests (FREE_DAILY_PAGES informs the message).
QUOTA_EXHAUSTED_CODES = {-60017, -60018, -60019}

# Input modalities MinerU understands, grouped so the CLI can report what it sees
# and so support stays single-sourced. The Agent API additionally rejects HTML.
MODALITY_SUFFIXES = {
    "pdf": {".pdf"},
    "image": {".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp"},
    "word": {".doc", ".docx"},
    "slides": {".ppt", ".pptx"},
    "sheet": {".xls", ".xlsx"},
    "html": {".html"},
}
SUPPORTED_SUFFIXES = {suf for group in MODALITY_SUFFIXES.values() for suf in group}

# Error code -> actionable hint. Mirrors the official docs error tables.
ERROR_HINTS = {
    "A0202": "Invalid token — check it or create a new one at https://mineru.net/apiManage/token",
    "A0211": "Token expired — create a new one at https://mineru.net/apiManage/token",
    -500: "Parameter error — check request parameters and Content-Type",
    -10001: "Service error — please retry later",
    -10002: "Invalid request parameters",
    -60001: "Failed to generate upload URL — retry later",
    -60002: "Unsupported file format — use a correct file extension",
    -60003: "Failed to read file — the file may be corrupted",
    -60004: "Empty file — upload a valid file",
    -60005: "File too large — Standard API max is 200 MB",
    -60006: "Too many pages — Standard API max is 200 pages, split the file",
    -60007: "Model service temporarily unavailable — retry later",
    -60008: "File read timeout — ensure the URL is reachable",
    -60009: "Task queue is full — retry later",
    -60010: "Parse failed — retry later",
    -60011: "Failed to get a valid file — ensure the file was uploaded",
    -60012: "Task not found — check the task_id",
    -60013: "No permission to access this task",
    -60014: "Cannot delete a running task",
    -60015: "File conversion failed — try converting to PDF first",
    -60016: "Format conversion failed — try another export format",
    -60017: "Retry limit reached — try again after a model upgrade",
    -60018: "Daily parse quota reached — try again tomorrow",
    -60019: "Insufficient HTML parse quota — try again tomorrow",
    -60020: "File split failed — retry later",
    -60021: "Failed to read page count — retry later",
    -60022: "Web page read failed — possibly rate-limited, retry later",
    # Agent (lightweight) API specific codes
    -30001: "File exceeds Agent API 10 MB limit — set MINERU_TOKEN to use the Standard API",
    -30002: "Agent API does not support this file type — use PDF/image/Doc/PPT/Excel",
    -30003: "Pages exceed Agent API 20-page limit — set MINERU_TOKEN or pass --pages",
    -30004: "Invalid request parameters — check required fields",
}

# Agent-API error codes that a Standard-API retry can recover from.
AGENT_ESCALATABLE = {-30001, -30003}

# Terminal/transient task states (Standard + Agent share most of these).
STATE_DONE = "done"
STATE_FAILED = "failed"
ACTIVE_STATES = {"pending", "running", "converting", "uploading", "waiting-file"}


class MinerUError(Exception):
    """Raised when the API returns a non-zero ``code`` or an unrecoverable error."""

    def __init__(self, message: str, code=None):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- #
# Options / results
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ParseOptions:
    model: str = "vlm"
    language: str = "ch"
    is_ocr: bool = False
    enable_formula: bool = True
    enable_table: bool = True
    page_ranges: Optional[str] = None
    extra_formats: tuple = ()


@dataclass
class ParseResult:
    name: str
    source: str
    api: str = "agent"
    modality: str = "unknown"
    state: str = STATE_FAILED
    output_dir: Optional[str] = None
    markdown_path: Optional[str] = None
    markdown: Optional[str] = None
    task_id: Optional[str] = None
    elapsed: Optional[float] = None
    error: Optional[str] = None
    sinks: list = field(default_factory=list)
    chunks: Optional[list] = None

    def to_status(self) -> dict:
        """Machine-readable status used by ``--json`` (omits the full markdown body)."""
        status = {
            "name": self.name,
            "source": self.source,
            "api": self.api,
            "modality": self.modality,
            "state": self.state,
            "output_dir": self.output_dir,
            "markdown_path": self.markdown_path,
            "task_id": self.task_id,
            "elapsed": self.elapsed,
            "error": self.error,
            "sinks": self.sinks,
        }
        if self.chunks is not None:
            status["chunks"] = self.chunks
        return status


# --------------------------------------------------------------------------- #
# Pure helpers (heavily unit-tested)
# --------------------------------------------------------------------------- #
def is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def safe_stem(source: str) -> str:
    """Derive a clean output folder name from a file path or URL."""
    tail = source.split("?", 1)[0].rstrip("/")
    name = tail.rsplit("/", 1)[-1] if is_url(source) else Path(source).name
    stem = Path(name).stem or "document"
    return stem


def unique_out_stems(sources) -> list:
    """On-disk folder/file stem per source, disambiguated ONLY on collision.

    Distinct basenames keep their bare stem (the documented output-dir contract).
    When two inputs share a basename (``a/report.pdf`` + ``b/report.pdf``) the
    later ones get a ``-2``/``-3`` suffix so neither silently overwrites the other
    on disk or via ``--resume``. Stable for a given input order, so resume keeps
    matching across re-runs.
    """
    out, seen = [], {}
    for src in sources:
        base = safe_stem(src)
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.append(base if n == 0 else f"{base}-{n + 1}")
    return out


def safe_data_id(stem: str) -> str:
    """data_id allows [A-Za-z0-9_.-], <=128 chars."""
    cleaned = "".join(c if (c.isalnum() or c in "_.-") else "-" for c in stem)
    return cleaned[:128] or "document"


def suffix_of(source: str) -> str:
    tail = source.split("?", 1)[0]
    return Path(tail).suffix.lower()


def is_supported(source: str) -> bool:
    return suffix_of(source) in SUPPORTED_SUFFIXES


def is_html(source: str) -> bool:
    return suffix_of(source) == ".html"


def detect_modality(source: str) -> str:
    """Classify the input modality (pdf/image/word/slides/sheet/html/url/unknown)."""
    suffix = suffix_of(source)
    if not suffix and is_url(source):
        return "url"
    for modality, suffixes in MODALITY_SUFFIXES.items():
        if suffix in suffixes:
            return modality
    return "unknown"


def to_agent_page_range(page_ranges: Optional[str]) -> Optional[str]:
    """Agent API only supports ``from-to`` or a single page (no commas)."""
    if not page_ranges:
        return None
    first = page_ranges.split(",", 1)[0].strip()
    return first or None


def error_hint(code) -> str:
    """Human-friendly hint for an API error code (falls back to the raw code)."""
    if code in ERROR_HINTS:
        return ERROR_HINTS[code]
    return f"API error (code {code})"


def _result_error(data: dict, default: str = "Parse failed") -> str:
    """Best available parse-task failure message, preserving documented codes."""
    msg = data.get("err_msg") or data.get("msg")
    code = data.get("err_code") or data.get("code")
    if msg:
        return msg
    if code is not None:
        return error_hint(code)
    return default


def choose_api(
    *,
    token: Optional[str],
    source: str,
    size_bytes: Optional[int],
    batch: bool,
    extra_formats,
    explicit: str = "auto",
) -> str:
    """Decide which backend to use. ``explicit`` of 'agent'/'standard' wins."""
    if explicit in ("agent", "standard"):
        return explicit
    # HTML is Standard-only (MinerU-HTML model); Agent API rejects it.
    if is_html(source):
        return "standard"
    if not token:
        return "agent"
    if batch or extra_formats:
        return "standard"
    if size_bytes is not None and size_bytes > AGENT_MAX_BYTES:
        return "standard"
    return "agent"


def _pdf_page_count_if_available(source: str) -> Optional[int]:
    """Best-effort local PDF page count.

    The core stays zero-dependency, so this only runs when the optional ``pypdf``
    module is installed. If it is unavailable or cannot read the PDF, callers
    fall back to the API-side validation.
    """
    if is_url(source) or suffix_of(source) != ".pdf":
        return None
    try:
        import pypdf  # type: ignore
    except ImportError:
        return None
    try:
        return len(pypdf.PdfReader(str(source)).pages)
    except Exception:
        return None


def _precheck_limits(source: str, api_kind: str, opts: ParseOptions) -> Optional[str]:
    """Return a local limit error, or ``None`` when submission is allowed."""
    if is_url(source):
        return None
    try:
        size = os.path.getsize(source)
    except OSError as exc:
        return str(exc)
    if size <= 0:
        return "Empty file — upload a valid file"
    if api_kind == "standard" and size > STANDARD_MAX_BYTES:
        return ERROR_HINTS[-60005]
    if api_kind == "agent" and size > AGENT_MAX_BYTES:
        return ERROR_HINTS[-30001]

    # A page range may intentionally select a capped subset, so avoid rejecting
    # locally unless we know the full document must be sent.
    if opts.page_ranges:
        return None
    pages = _pdf_page_count_if_available(source)
    if pages is None:
        return None
    if api_kind == "standard" and pages > STANDARD_MAX_PAGES:
        return ERROR_HINTS[-60006]
    if api_kind == "agent" and pages > AGENT_MAX_PAGES:
        return ERROR_HINTS[-30003]
    return None


def _agent_page_limit_exceeded(source: str, opts: ParseOptions) -> bool:
    if opts.page_ranges:
        return False
    pages = _pdf_page_count_if_available(source)
    return pages is not None and pages > AGENT_MAX_PAGES


# --------------------------------------------------------------------------- #
# HTTP seam
# --------------------------------------------------------------------------- #
# Two layers:
#   * ``_send_once``  — one keep-alive request (reuses a per-thread connection so
#                       the frequent poll traffic stops re-doing the TLS handshake).
#   * ``_http``       — retry/backoff wrapper around ``_send_once``. This is the
#                       single place the unit tests monkeypatch, so the retry and
#                       keep-alive machinery is transparent to them; the retry path
#                       is exercised separately by patching ``_send_once``.
_conn_local = threading.local()


def _backoff_delay(attempt: int, retry_after=None) -> float:
    """Exponential backoff with jitter; honors a server ``Retry-After`` if given."""
    if retry_after is not None:
        try:
            return min(float(retry_after), RETRY_MAX_DELAY)
        except (TypeError, ValueError):
            pass
    ceiling = min(RETRY_MAX_DELAY, RETRY_BASE_DELAY * (2 ** attempt))
    return ceiling * (0.5 + random.random() / 2)  # jitter in [0.5x, 1.0x]


def _next_poll_interval(interval, *, progressed, base) -> float:
    """Adaptive poll backoff for ONE group: reset to ``base`` on progress, else
    grow geometrically toward ``POLL_INTERVAL_CAP``. Kept per-group so a fast batch
    cannot reset (or a stuck batch inflate) the polling cadence of an unrelated one."""
    if progressed:
        return base
    return min(interval * 1.5, POLL_INTERVAL_CAP)


def _should_retry_status(status) -> bool:
    return status in RETRY_STATUSES


def _is_retryable_api_error(exc: MinerUError) -> bool:
    if exc.code in FATAL_API_CODES:
        return False
    return exc.code == 429 or exc.code in RETRYABLE_API_CODES


def _conn_pool() -> dict:
    pool = getattr(_conn_local, "pool", None)
    if pool is None:
        pool = {}
        _conn_local.pool = pool
    return pool


def _drop_conn(key) -> None:
    conn = _conn_pool().pop(key, None)
    if conn is not None:
        try:
            conn.close()
        except OSError:
            pass


def _get_conn(scheme, host, port, timeout):
    key = (scheme, host, port)
    pool = _conn_pool()
    conn = pool.get(key)
    if conn is None:
        if scheme == "https":
            conn = http.client.HTTPSConnection(host, port or 443, timeout=timeout)
        else:
            conn = http.client.HTTPConnection(host, port or 80, timeout=timeout)
        pool[key] = conn
    else:
        conn.timeout = timeout
    return conn, key


def _content_length(data):
    try:
        return len(data)
    except (TypeError, AttributeError):
        return None


def _send_once(method, url, *, headers=None, data=None, timeout=60, _redirects=5):
    """One HTTP request over a reused keep-alive connection.

    Returns ``(status_code, body_bytes, retry_after)``. Raises ``urllib.error.URLError``
    on a network-level failure (so the retry layer can back off).
    """
    parts = urllib.parse.urlsplit(url)
    scheme, host, port = parts.scheme, parts.hostname, parts.port
    path = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, "")) or "/"
    send_headers = dict(headers or {})
    send_headers.setdefault("User-Agent", USER_AGENT)
    if data is not None and "Content-Length" not in send_headers:
        length = _content_length(data)
        if length is not None:
            send_headers["Content-Length"] = str(length)

    # Try once on the pooled (possibly stale) connection; on a connection-level
    # error reconnect once before surfacing it to the retry layer.
    for stale_attempt in (0, 1):
        conn, key = _get_conn(scheme, host, port, timeout)
        try:
            conn.request(method, path, body=data, headers=send_headers)
            resp = conn.getresponse()
            status = resp.status
            body = resp.read()
            if resp.getheader("Connection", "").lower() == "close" or resp.version == 10:
                _drop_conn(key)
            if status in (301, 302, 303, 307, 308) and _redirects > 0:
                location = resp.getheader("Location")
                if location:
                    nxt = urllib.parse.urljoin(url, location)
                    nmethod = "GET" if status in (301, 302, 303) and method != "HEAD" else method
                    ndata = None if nmethod != method else data
                    if ndata is not None and hasattr(ndata, "seek"):
                        try:
                            ndata.seek(0)
                        except OSError:
                            pass
                    return _send_once(nmethod, nxt, headers=headers, data=ndata,
                                      timeout=timeout, _redirects=_redirects - 1)
            return status, body, resp.getheader("Retry-After")
        except (http.client.HTTPException, ConnectionError, OSError) as exc:
            _drop_conn(key)
            if stale_attempt == 0:
                if hasattr(data, "seek"):
                    try:
                        data.seek(0)
                    except OSError:
                        pass
                continue  # pooled connection was stale — reconnect and retry once
            raise urllib.error.URLError(exc)
    raise urllib.error.URLError("connection failed")  # pragma: no cover - defensive


def _http(method, url, *, headers=None, data=None, timeout=60):
    """Perform one HTTP request with bounded exponential backoff on transient
    failures (429/5xx/network). Returns ``(status_code, body_bytes)``.

    Business errors (HTTP 200 with ``code != 0``) are *not* retried here — that is
    the caller's concern in :func:`_api_json`.
    """
    for attempt in range(RETRY_MAX_ATTEMPTS):
        if hasattr(data, "seek"):
            try:
                data.seek(0)
            except OSError:
                pass
        status = None
        retry_after = None
        last_exc = None
        try:
            status, body, retry_after = _send_once(
                method, url, headers=headers, data=data, timeout=timeout
            )
        except urllib.error.URLError as exc:
            last_exc = exc
        if status is not None and not _should_retry_status(status):
            return status, body
        if attempt + 1 < RETRY_MAX_ATTEMPTS:
            time.sleep(_backoff_delay(attempt, retry_after if status is not None else None))
            continue
        # Retries exhausted.
        if status == 429:
            raise MinerUError(
                "Rate limited (HTTP 429) — slow down, lower --workers, or set a token",
                code=429,
            )
        if status is not None:
            return status, body  # surface the last 5xx body so _api_json can report it
        raise MinerUError(f"Network error after {RETRY_MAX_ATTEMPTS} attempts: {last_exc}")


def _api_json(method, url, *, token=None, payload=None, timeout=60) -> dict:
    """Call a MinerU JSON endpoint and return ``data``, raising on ``code != 0``."""
    headers = {"Accept": "*/*"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(RETRY_MAX_ATTEMPTS):
        status, raw = _http(method, url, headers=headers, data=body, timeout=timeout)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise MinerUError(f"Non-JSON response (HTTP {status}) from {url}")
        # MinerU returns two envelopes: the business layer uses {code, data, msg}
        # while the auth/gateway layer uses {success, msgCode, msg} (e.g. on a bad
        # token). Handle both so credential errors surface clearly.
        if parsed.get("success") is False:
            code = parsed.get("msgCode") or parsed.get("code")
            hint = ERROR_HINTS.get(code) or parsed.get("msg") or error_hint(code)
            raise MinerUError(hint, code=code)
        code = parsed.get("code")
        if not (200 <= status < 300) and code in (0, None):
            raise MinerUError(f"HTTP {status} from {url}", code=status)
        if code not in (0, None):
            if code in RETRYABLE_API_CODES and attempt + 1 < RETRY_MAX_ATTEMPTS:
                time.sleep(_backoff_delay(attempt))
                continue
            raise MinerUError(error_hint(code), code=code)
        data = parsed.get("data")
        if data is None and code is None and "success" not in parsed:
            raise MinerUError(f"Unexpected response (HTTP {status}) from {url}")
        return data or {}
    raise MinerUError(f"API retry exhausted for {url}")  # pragma: no cover - defensive


def _put_file(upload_url: str, path: str, timeout=300) -> None:
    """Upload a local file to a signed OSS URL (no Content-Type per docs)."""
    headers = {"Content-Length": str(os.path.getsize(path))}
    with open(path, "rb") as handle:
        status, _ = _http("PUT", upload_url, headers=headers, data=handle, timeout=timeout)
    if status not in (200, 201, 203):
        raise MinerUError(f"Upload failed (HTTP {status})")


def _download(url: str, timeout=300) -> bytes:
    status, raw = _http("GET", url, timeout=timeout)
    if status != 200:
        raise MinerUError(f"Download failed (HTTP {status})")
    return raw


def _download_to_path(url: str, dest: Path, *, timeout=300) -> Path:
    """Stream a (potentially large) download straight to disk in chunks.

    Used for result zips so a batch worker never buffers the whole archive in RAM.
    Retries transient failures with backoff, mirroring :func:`_http`.
    """
    for attempt in range(RETRY_MAX_ATTEMPTS):
        try:
            req = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.getcode() != 200:
                    raise MinerUError(f"Download failed (HTTP {resp.getcode()})")
                with open(dest, "wb") as handle:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        handle.write(chunk)
            return dest
        except urllib.error.HTTPError as exc:
            if _should_retry_status(exc.code) and attempt + 1 < RETRY_MAX_ATTEMPTS:
                time.sleep(_backoff_delay(attempt, exc.headers.get("Retry-After")))
                continue
            raise MinerUError(f"Download failed (HTTP {exc.code})", code=exc.code)
        except urllib.error.URLError as exc:
            if attempt + 1 < RETRY_MAX_ATTEMPTS:
                time.sleep(_backoff_delay(attempt))
                continue
            raise MinerUError(f"Download failed: {exc}")
    raise MinerUError("Download failed after retries")  # pragma: no cover - defensive


# --------------------------------------------------------------------------- #
# Agent API (lightweight, no token)
# --------------------------------------------------------------------------- #
def _agent_payload(opts: ParseOptions) -> dict:
    payload = {
        "language": opts.language,
        "enable_table": opts.enable_table,
        "is_ocr": opts.is_ocr,
        "enable_formula": opts.enable_formula,
    }
    page_range = to_agent_page_range(opts.page_ranges)
    if page_range:
        payload["page_range"] = page_range
    return payload


def agent_parse(source: str, opts: ParseOptions, *, poll_interval=3, timeout=600):
    """Parse one URL or file via the Agent API. Returns the Markdown text."""
    if is_url(source):
        payload = {"url": source, **_agent_payload(opts)}
        data = _api_json("POST", f"{AGENT_API}/parse/url", payload=payload)
        task_id = data["task_id"]
    else:
        payload = {"file_name": Path(source).name, **_agent_payload(opts)}
        data = _api_json("POST", f"{AGENT_API}/parse/file", payload=payload)
        task_id = data["task_id"]
        _put_file(data["file_url"], source, timeout=timeout)
    markdown = _agent_poll(task_id, poll_interval=poll_interval, timeout=timeout)
    return markdown, task_id


def _agent_poll(task_id, *, poll_interval, timeout) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = _api_json("GET", f"{AGENT_API}/parse/{task_id}", timeout=timeout)
        state = data.get("state")
        if state == STATE_DONE:
            return _download(data["markdown_url"], timeout=timeout).decode("utf-8", errors="replace")
        if state == STATE_FAILED:
            raise MinerUError(
                data.get("err_msg") or error_hint(data.get("err_code")),
                code=data.get("err_code"),
            )
        time.sleep(poll_interval)
    raise MinerUError("Agent parse timed out")


# --------------------------------------------------------------------------- #
# Standard API (v4, token required)
# --------------------------------------------------------------------------- #
def _standard_model(opts: ParseOptions, source: str) -> str:
    return "MinerU-HTML" if is_html(source) else opts.model


def _standard_submit_and_poll(source, opts, token, *, poll_interval=3, timeout=600):
    """Submit one URL/file to the Standard API and poll to completion.

    Returns ``(full_zip_url, task_or_batch_id)`` — the caller decides whether to
    buffer (small) or stream (large) the result zip. The submit POST uses a capped
    socket timeout; the full ``timeout`` stays the parse budget for polling.
    """
    model = _standard_model(opts, source)
    req_timeout = min(timeout, REQUEST_TIMEOUT_CAP)
    if is_url(source):
        payload = {
            "url": source,
            "model_version": model,
            "is_ocr": opts.is_ocr,
            "enable_formula": opts.enable_formula,
            "enable_table": opts.enable_table,
            "language": opts.language,
        }
        if opts.page_ranges:
            payload["page_ranges"] = opts.page_ranges
        if opts.extra_formats:
            payload["extra_formats"] = list(opts.extra_formats)
        data = _api_json("POST", f"{STANDARD_API}/extract/task", token=token,
                         payload=payload, timeout=req_timeout)
        zip_url = _standard_poll_task(data["task_id"], token, poll_interval=poll_interval, timeout=timeout)
        return zip_url, data["task_id"]

    # Local file: request a signed upload URL, PUT the bytes, then poll the batch.
    file_entry = {"name": Path(source).name, "data_id": safe_data_id(safe_stem(source))}
    if opts.is_ocr:
        file_entry["is_ocr"] = True
    if opts.page_ranges:
        file_entry["page_ranges"] = opts.page_ranges
    payload = {
        "files": [file_entry],
        "model_version": model,
        "enable_formula": opts.enable_formula,
        "enable_table": opts.enable_table,
        "language": opts.language,
    }
    if opts.extra_formats:
        payload["extra_formats"] = list(opts.extra_formats)
    data = _api_json("POST", f"{STANDARD_API}/file-urls/batch", token=token,
                     payload=payload, timeout=req_timeout)
    batch_id = data["batch_id"]
    _put_file(data["file_urls"][0], source, timeout=timeout)
    zip_url = _standard_poll_batch(batch_id, token, Path(source).name, poll_interval=poll_interval, timeout=timeout)
    return zip_url, batch_id


def standard_parse(
    source: str, opts: ParseOptions, token: str, *, poll_interval=3, timeout=600
):
    """Parse one URL or file via the Standard API. Returns ``(zip_bytes, id)``."""
    zip_url, task_id = _standard_submit_and_poll(
        source, opts, token, poll_interval=poll_interval, timeout=timeout
    )
    return _download(zip_url, timeout=timeout), task_id


def _standard_parse_to_dir(source, opts, token, out_stem, output_dir, *, poll_interval=3, timeout=600):
    """Standard parse of a single input, streaming the result zip to disk rather
    than buffering the whole archive in RAM. Returns ``(md_path, id)``."""
    zip_url, task_id = _standard_submit_and_poll(
        source, opts, token, poll_interval=poll_interval, timeout=timeout
    )
    target_dir = output_dir / out_stem
    target_dir.mkdir(parents=True, exist_ok=True)
    zip_path = target_dir / "._result.zip.partial"
    _download_to_path(zip_url, zip_path, timeout=timeout)
    md_path = extract_zip_path(out_stem, zip_path, output_dir)
    try:
        zip_path.unlink()
    except OSError:
        pass
    return md_path, task_id


def _standard_poll_task(task_id, token, *, poll_interval, timeout) -> str:
    deadline = time.monotonic() + timeout
    req_timeout = min(timeout, REQUEST_TIMEOUT_CAP)
    while time.monotonic() < deadline:
        data = _api_json("GET", f"{STANDARD_API}/extract/task/{task_id}", token=token,
                         timeout=req_timeout)
        state = data.get("state")
        if state == STATE_DONE:
            return data["full_zip_url"]
        if state == STATE_FAILED:
            raise MinerUError(_result_error(data), code=data.get("err_code"))
        time.sleep(poll_interval)
    raise MinerUError("Standard parse timed out")


def _standard_poll_batch(batch_id, token, file_name, *, poll_interval, timeout) -> str:
    deadline = time.monotonic() + timeout
    req_timeout = min(timeout, REQUEST_TIMEOUT_CAP)
    while time.monotonic() < deadline:
        data = _api_json("GET", f"{STANDARD_API}/extract-results/batch/{batch_id}",
                         token=token, timeout=req_timeout)
        for entry in data.get("extract_result", []):
            if entry.get("file_name") != file_name:
                continue
            state = entry.get("state")
            if state == STATE_DONE:
                return entry["full_zip_url"]
            if state == STATE_FAILED:
                raise MinerUError(_result_error(entry), code=entry.get("err_code"))
        time.sleep(poll_interval)
    raise MinerUError("Standard parse timed out")


# --------------------------------------------------------------------------- #
# Output writing
# --------------------------------------------------------------------------- #
def write_markdown(stem: str, markdown: str, output_dir: Path) -> Path:
    """Write a bare Markdown string (Agent API result) to ``<dir>/<stem>/<stem>.md``.

    The write is atomic (temp file + ``os.replace``) so an interrupted run can never
    leave a half-written ``.md`` that ``--resume`` would mistake for a finished file.
    """
    target_dir = output_dir / stem
    target_dir.mkdir(parents=True, exist_ok=True)
    md_path = target_dir / f"{stem}.md"
    tmp_path = target_dir / f".{stem}.md.partial"
    tmp_path.write_text(markdown, encoding="utf-8")
    os.replace(tmp_path, md_path)
    return md_path


def _finalize_zip_dir(target_dir: Path, stem: str) -> Path:
    """Rename the archive's ``full.md`` to ``<stem>.md``.

    With no ``full.md`` (and no already-correct ``<stem>.md``), pick the largest
    ``*.md`` — the most likely full body — tie-broken by name, so the choice is
    deterministic instead of filesystem ``glob`` order.
    """
    full_md = target_dir / "full.md"
    md_path = target_dir / f"{stem}.md"
    if full_md.exists():
        full_md.replace(md_path)
    elif not md_path.exists():
        candidates = sorted(target_dir.glob("*.md"), key=lambda p: (-p.stat().st_size, p.name))
        if candidates:
            candidates[0].replace(md_path)
    return md_path


def _validate_zip_member(info: zipfile.ZipInfo) -> None:
    name = info.filename
    parts = PurePosixPath(name).parts
    if PurePosixPath(name).is_absolute() or ".." in parts:
        raise MinerUError(f"Unsafe zip member path: {name}")
    file_type = (info.external_attr >> 16) & 0o170000
    if file_type == 0o120000:
        raise MinerUError(f"Unsafe zip symlink: {name}")


def _safe_extract_zip(archive: zipfile.ZipFile, target_dir: Path) -> None:
    for info in archive.infolist():
        _validate_zip_member(info)
    archive.extractall(target_dir)


def write_zip(stem: str, zip_bytes: bytes, output_dir: Path) -> Path:
    """Extract a Standard API result zip and return the path to the renamed Markdown."""
    target_dir = output_dir / stem
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BytesIO(zip_bytes)) as archive:
        _safe_extract_zip(archive, target_dir)
    return _finalize_zip_dir(target_dir, stem)


def extract_zip_path(stem: str, zip_path: Path, output_dir: Path) -> Path:
    """Extract a result zip already on disk (streamed download) without buffering it."""
    target_dir = output_dir / stem
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        _safe_extract_zip(archive, target_dir)
    return _finalize_zip_dir(target_dir, stem)


def copy_to_obsidian(md_path: Path, stem: str, vault: Path) -> Path:
    """Copy the parsed Markdown (and sibling images) into an Obsidian vault folder."""
    vault.mkdir(parents=True, exist_ok=True)
    dest = vault / f"{stem}.md"
    dest.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    images = md_path.parent / "images"
    if images.is_dir():
        dest_images = vault / "images"
        dest_images.mkdir(exist_ok=True)
        for img in images.iterdir():
            if img.is_file():
                (dest_images / img.name).write_bytes(img.read_bytes())
    return dest


# --------------------------------------------------------------------------- #
# Per-input orchestration
# --------------------------------------------------------------------------- #
def process_one(
    source: str,
    opts: ParseOptions,
    *,
    token: Optional[str],
    output_dir: Path,
    api: str = "auto",
    obsidian: Optional[Path] = None,
    resume: bool = False,
    poll_interval: float = 3,
    timeout: float = 600,
    engine: str = "cloud",
    out_stem: Optional[str] = None,
) -> ParseResult:
    """Parse a single input end to end, choosing the backend and writing output."""
    stem = safe_stem(source)
    out_stem = out_stem or stem  # on-disk identity (disambiguated by the caller on collision)
    result = ParseResult(name=stem, source=source, modality=detect_modality(source))
    started = time.monotonic()

    if resume and (output_dir / out_stem / f"{out_stem}.md").exists():
        result.state = "skipped"
        result.output_dir = str(output_dir / out_stem)
        result.markdown_path = str(output_dir / out_stem / f"{out_stem}.md")
        return result

    if engine in ("local", "auto") and not is_url(source) and suffix_of(source) == ".pdf":
        local = _load_local_engine()
        use_local = engine == "local"
        if engine == "auto" and local is not None:
            try:
                use_local = local.available() and local.is_born_digital(source)
            except Exception:
                use_local = False
        if use_local and local is not None:
            try:
                markdown = local.parse_local(source)
                md_path = write_markdown(out_stem, markdown, output_dir)
                result.api = "local"
                result.markdown = markdown
                return _finalize(result, out_stem, output_dir, md_path, obsidian, started)
            except Exception as exc:  # LocalEngineError or parse failure
                if engine == "local":
                    result.state = STATE_FAILED
                    result.error = str(exc)
                    return result
                # auto: fall through to the cloud engine

    size_bytes = None
    if not is_url(source):
        try:
            size_bytes = os.path.getsize(source)
        except OSError:
            pass

    chosen = choose_api(
        token=token,
        source=source,
        size_bytes=size_bytes,
        batch=False,
        extra_formats=opts.extra_formats,
        explicit=api,
    )
    if chosen == "agent" and api == "auto" and token and _agent_page_limit_exceeded(source, opts):
        chosen = "standard"

    precheck_error = _precheck_limits(source, chosen, opts)
    if precheck_error:
        result.api = chosen
        result.state = STATE_FAILED
        result.error = precheck_error
        return result

    try:
        result.api = chosen
        if chosen == "standard":
            if not token:
                raise MinerUError(
                    "Standard API needs a token — set MINERU_TOKEN "
                    "(https://mineru.net/apiManage/token)"
                )
            md_path, task_id = _standard_parse_to_dir(
                source, opts, token, out_stem, output_dir,
                poll_interval=poll_interval, timeout=timeout
            )
            result.task_id = task_id
            result.markdown = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
        else:
            try:
                markdown, task_id = agent_parse(
                    source, opts, poll_interval=poll_interval, timeout=timeout
                )
            except MinerUError as exc:
                # Auto-escalate to the Standard API when a token is available.
                if api == "auto" and token and exc.code in AGENT_ESCALATABLE:
                    result.api = "standard"
                    md_path, task_id = _standard_parse_to_dir(
                        source, opts, token, out_stem, output_dir,
                        poll_interval=poll_interval, timeout=timeout
                    )
                    result.task_id = task_id
                    result.markdown = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
                    return _finalize(result, out_stem, output_dir, md_path, obsidian, started)
                raise
            result.task_id = task_id
            md_path = write_markdown(out_stem, markdown, output_dir)
            result.markdown = markdown
        return _finalize(result, out_stem, output_dir, md_path, obsidian, started)
    except MinerUError as exc:
        result.state = STATE_FAILED
        result.error = str(exc)
        return result
    except (OSError, urllib.error.URLError) as exc:
        result.state = STATE_FAILED
        result.error = str(exc)
        return result
    except Exception as exc:  # noqa: BLE001 - one malformed response must not abort the batch
        result.state = STATE_FAILED
        result.error = f"{type(exc).__name__}: {exc}"
        return result


def _finalize(result, out_stem, output_dir, md_path, obsidian, started=None) -> ParseResult:
    # A result that yielded no markdown on disk is a failure, not a silent "done"
    # pointing at a nonexistent/empty body.
    if md_path is None or not Path(md_path).exists():
        result.state = STATE_FAILED
        result.error = result.error or "no markdown in result"
        return result
    result.state = STATE_DONE
    result.output_dir = str(output_dir / out_stem)
    result.markdown_path = str(md_path)
    if started is not None:
        result.elapsed = round(time.monotonic() - started, 2)
    if obsidian is not None:
        copy_to_obsidian(md_path, out_stem, obsidian)
    return result


# --------------------------------------------------------------------------- #
# Multi-input pipeline: decoupled submit -> poll -> download
# --------------------------------------------------------------------------- #
# The single-file primitives above each block a thread for the whole parse
# (submit, then ``time.sleep`` poll loop). That caps real concurrency at the
# worker count and wastes threads sleeping. For batches we instead:
#   1. submit every input up front (Standard local files coalesced into one
#      ``/file-urls/batch`` call of up to 50 files — the endpoint's real purpose),
#   2. poll all outstanding tickets from one place with adaptive backoff (a single
#      batch poll returns the state of every file in that batch), and
#   3. download + extract completed results in a small pool as soon as each is done.
# Nothing sleeps holding a parse slot, and Standard API/poll traffic collapses ~Nx.
@dataclass
class _Job:
    source: str
    stem: str
    api: str
    is_url: bool
    result: ParseResult
    out_stem: str = ""
    data_id: str = ""
    file_name: str = ""
    poll_kind: str = ""        # "agent" | "task" | "batch"
    poll_id: str = ""
    download_url: str = ""
    download_kind: str = ""    # "md" | "zip"
    deadline: float = 0.0
    started: float = 0.0
    finished: bool = False     # resolved during planning/submit (skip or hard-fail)


def _plan_jobs(sources, opts, *, token, output_dir, api, resume, batch_mode=False) -> list:
    """Resolve each source's backend and short-circuit already-parsed inputs."""
    jobs = []
    out_stems = unique_out_stems(sources)
    for idx, src in enumerate(sources):
        stem = safe_stem(src)
        out_stem = out_stems[idx]
        res = ParseResult(name=stem, source=src, modality=detect_modality(src))
        url = is_url(src)
        job = _Job(
            source=src, stem=stem, out_stem=out_stem, api="agent", is_url=url, result=res,
            file_name=(safe_stem(src) if url else Path(src).name),
            data_id=f"{safe_data_id(stem)}-{idx}",
        )
        if resume and (output_dir / out_stem / f"{out_stem}.md").exists():
            res.state = "skipped"
            res.output_dir = str(output_dir / out_stem)
            res.markdown_path = str(output_dir / out_stem / f"{out_stem}.md")
            job.finished = True
            jobs.append(job)
            continue
        size_bytes = None
        if not url:
            try:
                size_bytes = os.path.getsize(src)
            except OSError:
                pass
        job.api = choose_api(
            token=token, source=src, size_bytes=size_bytes, batch=batch_mode,
            extra_formats=opts.extra_formats, explicit=api,
        )
        if job.api == "agent" and api == "auto" and token and _agent_page_limit_exceeded(src, opts):
            job.api = "standard"
        res.api = job.api
        precheck_error = _precheck_limits(src, job.api, opts)
        if precheck_error:
            res.state = STATE_FAILED
            res.error = precheck_error
            job.finished = True
        jobs.append(job)
    return jobs


def _reserve_single(job, opts, token, timeout) -> list:
    """Submit one non-batch input; return upload work ``[(job, url)]`` (empty for URLs)."""
    src = job.source
    job.deadline = time.monotonic() + timeout
    req_timeout = min(timeout, REQUEST_TIMEOUT_CAP)
    if job.api == "agent":
        if job.is_url:
            data = _api_json("POST", f"{AGENT_API}/parse/url",
                             payload={"url": src, **_agent_payload(opts)}, timeout=req_timeout)
            job.poll_kind, job.poll_id = "agent", data["task_id"]
            job.result.task_id = data["task_id"]
            return []
        data = _api_json("POST", f"{AGENT_API}/parse/file",
                         payload={"file_name": Path(src).name, **_agent_payload(opts)},
                         timeout=req_timeout)
        job.poll_kind, job.poll_id = "agent", data["task_id"]
        job.result.task_id = data["task_id"]
        return [(job, data["file_url"])]
    # Standard API URL -> single extract task (only local files coalesce into batches).
    model = _standard_model(opts, src)
    payload = {
        "url": src, "model_version": model, "is_ocr": opts.is_ocr,
        "enable_formula": opts.enable_formula, "enable_table": opts.enable_table,
        "language": opts.language,
    }
    if opts.page_ranges:
        payload["page_ranges"] = opts.page_ranges
    if opts.extra_formats:
        payload["extra_formats"] = list(opts.extra_formats)
    data = _api_json("POST", f"{STANDARD_API}/extract/task", token=token,
                     payload=payload, timeout=req_timeout)
    job.poll_kind, job.poll_id = "task", data["task_id"]
    job.result.task_id = data["task_id"]
    return []


def _reserve_batch(batch_jobs, opts, token, timeout) -> list:
    """Submit one ``/file-urls/batch`` of up to 50 files; return upload work list."""
    model = _standard_model(opts, batch_jobs[0].source)
    files = []
    for job in batch_jobs:
        entry = {"name": Path(job.source).name, "data_id": job.data_id}
        if opts.is_ocr:
            entry["is_ocr"] = True
        if opts.page_ranges:
            entry["page_ranges"] = opts.page_ranges
        files.append(entry)
    payload = {
        "files": files, "model_version": model,
        "enable_formula": opts.enable_formula, "enable_table": opts.enable_table,
        "language": opts.language,
    }
    if opts.extra_formats:
        payload["extra_formats"] = list(opts.extra_formats)
    data = _api_json("POST", f"{STANDARD_API}/file-urls/batch", token=token,
                     payload=payload, timeout=min(timeout, REQUEST_TIMEOUT_CAP))
    batch_id = data["batch_id"]
    urls = data["file_urls"]
    if len(urls) != len(batch_jobs):
        raise MinerUError(
            f"Batch upload URL count mismatch: requested {len(batch_jobs)}, got {len(urls)}"
        )
    deadline = time.monotonic() + timeout
    uploads = []
    for job, url in zip(batch_jobs, urls):
        if isinstance(url, dict):
            url = url.get("url") or url.get("file_url") or url.get("upload_url")
        if not url:
            raise MinerUError(f"Missing upload URL for {job.file_name or job.source}")
        job.poll_kind, job.poll_id = "batch", batch_id
        job.result.task_id = batch_id
        job.deadline = deadline
        uploads.append((job, url))
    return uploads


def _reserve_url_batch(batch_jobs, opts, token, timeout) -> list:
    """Submit one Standard ``/extract/task/batch`` for URL inputs."""
    model = _standard_model(opts, batch_jobs[0].source)
    files = [{"url": job.source, "data_id": job.data_id} for job in batch_jobs]
    payload = {"files": files, "model_version": model}
    data = _api_json("POST", f"{STANDARD_API}/extract/task/batch", token=token,
                     payload=payload, timeout=min(timeout, REQUEST_TIMEOUT_CAP))
    batch_id = data["batch_id"]
    deadline = time.monotonic() + timeout
    for job in batch_jobs:
        job.poll_kind, job.poll_id = "batch", batch_id
        job.result.task_id = batch_id
        job.deadline = deadline
    return []


def _can_batch_standard_urls(opts: ParseOptions) -> bool:
    """URL batch endpoint has a narrower documented payload than single URL tasks."""
    return (
        not opts.is_ocr
        and opts.enable_formula
        and opts.enable_table
        and opts.language == "ch"
        and not opts.page_ranges
        and not opts.extra_formats
    )


def _chunk_standard_jobs(std_jobs, opts, batch_size) -> list:
    """Group Standard-API jobs into batches, splitting by model_version."""
    by_model: dict = {}
    for job in std_jobs:
        by_model.setdefault(_standard_model(opts, job.source), []).append(job)
    chunks = []
    size = max(1, min(batch_size, BATCH_MAX_FILES))
    for group in by_model.values():
        for i in range(0, len(group), size):
            chunks.append(group[i:i + size])
    return chunks


def _chunk_standard_files(std_jobs, opts, batch_size) -> list:
    """Backward-compatible wrapper for tests/importers."""
    return _chunk_standard_jobs(std_jobs, opts, batch_size)


def _poll_group(kind, poll_id, group, token, *, timeout=60):
    """Poll one ticket; return ``(completed_jobs, failed_jobs)`` (state set on each)."""
    completed, failed = [], []
    if kind == "agent":
        data = _api_json("GET", f"{AGENT_API}/parse/{poll_id}", timeout=timeout)
        job = group[0]
        state = data.get("state")
        if state == STATE_DONE:
            job.download_url, job.download_kind = data["markdown_url"], "md"
            completed.append(job)
        elif state == STATE_FAILED:
            job.result.error = _result_error(data)
            failed.append(job)
    elif kind == "task":
        data = _api_json("GET", f"{STANDARD_API}/extract/task/{poll_id}", token=token,
                         timeout=timeout)
        job = group[0]
        state = data.get("state")
        if state == STATE_DONE:
            job.download_url, job.download_kind = data["full_zip_url"], "zip"
            completed.append(job)
        elif state == STATE_FAILED:
            job.result.error = _result_error(data)
            failed.append(job)
    else:  # batch — one GET reports every file in the batch
        data = _api_json("GET", f"{STANDARD_API}/extract-results/batch/{poll_id}",
                         token=token, timeout=timeout)
        by_data, by_name = {}, {}
        for entry in data.get("extract_result", []):
            if entry.get("data_id"):
                by_data[entry["data_id"]] = entry
            if entry.get("file_name"):
                by_name.setdefault(entry["file_name"], entry)
        group_name_counts = {}
        for job in group:
            group_name_counts[job.file_name] = group_name_counts.get(job.file_name, 0) + 1
        for job in group:
            entry = by_data.get(job.data_id)
            if entry is None and group_name_counts.get(job.file_name) == 1:
                entry = by_name.get(job.file_name)
            if not entry:
                continue
            state = entry.get("state")
            if state == STATE_DONE:
                job.download_url, job.download_kind = entry["full_zip_url"], "zip"
                completed.append(job)
            elif state == STATE_FAILED:
                job.result.error = _result_error(entry)
                failed.append(job)
    return completed, failed


def _download_and_write(job, opts, output_dir, *, obsidian, want_markdown, timeout=300):
    """Download a completed result, write it, and finalize the job's ParseResult."""
    try:
        if job.download_kind == "md":
            markdown = _download(job.download_url, timeout=timeout).decode("utf-8", errors="replace")
            md_path = write_markdown(job.out_stem, markdown, output_dir)
            if want_markdown:
                job.result.markdown = markdown
        else:
            target_dir = output_dir / job.out_stem
            target_dir.mkdir(parents=True, exist_ok=True)
            zip_path = target_dir / "._result.zip.partial"
            _download_to_path(job.download_url, zip_path, timeout=timeout)
            md_path = extract_zip_path(job.out_stem, zip_path, output_dir)
            try:
                zip_path.unlink()
            except OSError:
                pass
            if want_markdown and md_path.exists():
                job.result.markdown = md_path.read_text(encoding="utf-8", errors="replace")
        _finalize(job.result, job.out_stem, output_dir, md_path, obsidian,
                  started=job.started or None)
    except Exception as exc:  # noqa: BLE001 - isolate a single bad result
        job.result.state = STATE_FAILED
        job.result.error = f"{type(exc).__name__}: {exc}"


def _poll_until_done(active, opts, token, output_dir, *, poll_interval, obsidian,
                     want_markdown, download_pool, on_done, timeout=60):
    """Decoupled poll loop: dispatch downloads as results complete.

    Each batch/task ticket carries its OWN adaptive backoff and next-due time, so
    one batch's cadence never resets or inflates another's. The per-request socket
    timeout is capped (a stalled poll can't wedge the loop for the whole parse
    budget — that lives in ``job.deadline``), and any unexpected error in one
    ticket fails only that ticket instead of aborting the whole batch.
    """
    poll_req_timeout = min(timeout, REQUEST_TIMEOUT_CAP)
    now0 = time.monotonic()
    groups: dict = {}  # poll_id -> {kind, jobs, interval, due}
    for job in active:
        st = groups.setdefault(
            job.poll_id, {"kind": job.poll_kind, "jobs": [], "interval": poll_interval, "due": now0}
        )
        st["jobs"].append(job)
    dl_futures = []
    while groups:
        now = time.monotonic()
        due_ids = [pid for pid, st in groups.items() if st["due"] <= now]
        if not due_ids:
            time.sleep(max(0.0, min(st["due"] for st in groups.values()) - now))
            continue
        for poll_id in due_ids:
            st = groups[poll_id]
            group = st["jobs"]
            try:
                completed, failed = _poll_group(st["kind"], poll_id, group, token, timeout=poll_req_timeout)
            except MinerUError as exc:
                completed = []
                if _is_retryable_api_error(exc):
                    failed = []  # transient poll error — try again next cycle
                else:
                    failed = list(group)
                    for job in failed:
                        job.result.error = str(exc)
            except Exception as exc:  # noqa: BLE001 - a malformed ticket must not abort the batch
                completed = []
                failed = list(group)
                for job in failed:
                    job.result.error = f"poll error: {type(exc).__name__}: {exc}"
            for job in group:
                if job in completed or job in failed:
                    continue
                if now > job.deadline:
                    job.result.state = STATE_FAILED
                    job.result.error = "parse timed out"
                    failed.append(job)
            for job in completed:
                group.remove(job)
                dl_futures.append(
                    download_pool.submit(
                        _download_and_write, job, opts, output_dir,
                        obsidian=obsidian, want_markdown=want_markdown, timeout=timeout,
                    )
                )
            for job in failed:
                group.remove(job)
                on_done(job)
            progressed = bool(completed or failed)
            if not group:
                del groups[poll_id]
            else:
                st["interval"] = _next_poll_interval(st["interval"], progressed=progressed, base=poll_interval)
                st["due"] = now + st["interval"]
    for future in dl_futures:
        future.result()  # _download_and_write swallows its own errors into the result
    # Notify every resolved job after downloads finish (the guard de-dupes earlier
    # poll-failure notifications); includes jobs that failed *inside* the download
    # step, so none are silently left unreported.
    for job in active:
        on_done(job)


def run_pipeline(sources, opts, *, token, output_dir, api, resume, poll_interval,
                 timeout, batch_size, workers, obsidian=None, want_markdown=False,
                 on_result=None) -> list:
    """Parse many inputs with decoupled submit/poll/download. Returns ParseResults."""
    batch_mode = len(sources) > 1
    jobs = _plan_jobs(sources, opts, token=token, output_dir=output_dir,
                      api=api, resume=resume, batch_mode=batch_mode)
    started = time.monotonic()
    for job in jobs:
        job.started = started

    def _notify(job):
        if on_result is not None and not getattr(job, "_notified", False):
            job._notified = True
            on_result(job.result)

    for job in jobs:
        if job.finished:  # resume-skipped
            _notify(job)

    pending = [j for j in jobs if not j.finished]
    std_files = [j for j in pending if j.api == "standard" and not j.is_url]
    std_urls = [j for j in pending if j.api == "standard" and j.is_url]
    batchable_urls = std_urls if _can_batch_standard_urls(opts) else []
    single_urls = [] if _can_batch_standard_urls(opts) else std_urls
    single_url_ids = {id(j) for j in single_urls}
    singles = [
        j for j in pending
        if j.api != "standard" or (j.is_url and id(j) in single_url_ids)
    ]

    if not token:
        for job in pending:
            if job.api == "standard":
                job.result.state = STATE_FAILED
                job.result.error = ("Standard API needs a token — set MINERU_TOKEN "
                                    "(https://mineru.net/apiManage/token)")
                job.finished = True
                _notify(job)
        std_files = [j for j in std_files if not j.finished]
        batchable_urls = [j for j in batchable_urls if not j.finished]
        single_urls = [j for j in single_urls if not j.finished]
        singles = [j for j in singles if not j.finished]

    file_batches = _chunk_standard_jobs(std_files, opts, batch_size)
    url_batches = _chunk_standard_jobs(batchable_urls, opts, batch_size)

    quota_tripped = threading.Event()

    def _reserve_guarded(fn, *fn_args):
        # Daily quota / retry-limit is terminal for the whole run; once tripped,
        # skip the remaining submits instead of firing more doomed requests.
        if quota_tripped.is_set():
            raise MinerUError(
                f"daily quota reached ({FREE_DAILY_PAGES} free pages/day) — submit skipped; retry tomorrow",
                code=-60018,
            )
        try:
            return fn(*fn_args)
        except MinerUError as exc:
            if exc.code in QUOTA_EXHAUSTED_CODES:
                quota_tripped.set()
            raise

    with ThreadPoolExecutor(max_workers=workers) as submit_pool, \
            ThreadPoolExecutor(max_workers=workers) as download_pool:
        # Phase 1 — reserve (parallel): one POST per single input / per batch.
        reserve = {}
        for job in singles:
            reserve[submit_pool.submit(_reserve_guarded, _reserve_single, job, opts, token, timeout)] = ("single", job)
        for chunk in file_batches:
            reserve[submit_pool.submit(_reserve_guarded, _reserve_batch, chunk, opts, token, timeout)] = ("batch", chunk)
        for chunk in url_batches:
            reserve[submit_pool.submit(_reserve_guarded, _reserve_url_batch, chunk, opts, token, timeout)] = ("batch", chunk)

        uploads = []
        for future in as_completed(reserve):
            kind, payload = reserve[future]
            affected = payload if kind == "batch" else [payload]
            try:
                uploads.extend(future.result())
            except Exception as exc:  # noqa: BLE001 - submit failure isolated per ticket
                msg = str(exc) if isinstance(exc, MinerUError) else f"{type(exc).__name__}: {exc}"
                for job in affected:
                    if job.result.state != STATE_DONE:
                        job.result.state = STATE_FAILED
                        job.result.error = f"submit failed: {msg}"
                        job.finished = True
                        _notify(job)

        # Phase 2 — upload (parallel): PUT each reserved file to its signed URL.
        up_futures = {}
        for job, url in uploads:
            up_futures[submit_pool.submit(_put_file, url, job.source, timeout)] = job
        for future in as_completed(up_futures):
            job = up_futures[future]
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001
                job.result.state = STATE_FAILED
                job.result.error = f"upload failed: {exc}"
                job.finished = True
                _notify(job)

        # Phase 3 — poll + download (decoupled). Gate on the ``finished`` flag, NOT
        # result.state: a freshly submitted job's ParseResult still carries its default
        # ``failed`` state, so a state-based filter would drop every in-flight job and
        # skip polling entirely — reporting the whole batch as failed.
        active = [j for j in pending if j.poll_id and not j.finished]
        if active:
            _poll_until_done(
                active, opts, token, output_dir, poll_interval=poll_interval,
                obsidian=obsidian, want_markdown=want_markdown,
                download_pool=download_pool, on_done=_notify, timeout=timeout,
            )

    return [job.result for job in jobs]


# --------------------------------------------------------------------------- #
# Input expansion + CLI
# --------------------------------------------------------------------------- #
_IMG_REF = re.compile(r"(!\[[^\]]*\]\()([^)\s]+)(\))")


def _load_splitter():
    script_dir = str(Path(__file__).resolve().parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    import splitter
    return splitter


def _load_local_engine():
    """Import the optional offline-engine module; return it or None."""
    try:
        script_dir = str(Path(__file__).resolve().parent)
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        import local_engine
        return local_engine
    except Exception:  # pragma: no cover
        return None


def split_cap(token, api, override=None) -> int:
    """Pages per part: explicit override, else the cap of the backend that will run."""
    if override:
        return override
    if api == "standard" or (api == "auto" and token):
        return STANDARD_MAX_PAGES
    return AGENT_MAX_PAGES


def _merge_parts(part_results, stem: str, final_dir: Path) -> tuple:
    """Merge part Markdown + images into ``final_dir``; return (markdown, image_count)."""
    images_dir = final_dir / "images"
    bodies = []
    image_count = 0
    for n, res in enumerate(part_results, start=1):
        if res.state != STATE_DONE or not res.markdown:
            continue
        part_md_dir = Path(res.markdown_path).parent if res.markdown_path else None
        prefix = f"part{n:03d}_"

        def repl(match, _dir=part_md_dir, _pfx=prefix):
            nonlocal image_count
            ref = match.group(2)
            if ref.startswith("http://") or ref.startswith("https://") or _dir is None:
                return match.group(0)
            src = (_dir / ref)
            if not src.is_file():
                return match.group(0)
            images_dir.mkdir(parents=True, exist_ok=True)
            new_name = _pfx + Path(ref).name
            (images_dir / new_name).write_bytes(src.read_bytes())
            image_count += 1
            return f"{match.group(1)}images/{new_name}{match.group(3)}"

        bodies.append(_IMG_REF.sub(repl, res.markdown))
    merged = ("\n\n---\n\n").join(bodies)
    final_dir.mkdir(parents=True, exist_ok=True)
    (final_dir / f"{stem}.md").write_text(merged, encoding="utf-8")
    return merged, image_count


def process_split(source, opts, *, token, output_dir, api, resume, timeout, cap, engine="cloud", out_stem=None):
    """Split an oversized local PDF, parse each part, and merge. Returns a ParseResult,
    or None when no split is needed (caller falls back to process_one)."""
    if is_url(source) or suffix_of(source) != ".pdf":
        return None
    stem = safe_stem(source)
    out_stem = out_stem or stem
    result = ParseResult(name=stem, source=source, modality="pdf")
    try:
        splitter = _load_splitter()
        pages = splitter.pdf_page_count(source)
    except Exception as exc:  # SplitError (pypdf missing) or unreadable PDF
        result.state = STATE_FAILED
        result.error = str(exc)
        return result
    if pages <= cap:
        return None  # fits — let normal processing handle it

    final_dir = output_dir / out_stem
    if resume and (final_dir / f"{out_stem}.md").exists():
        result.state = "skipped"
        result.output_dir = str(final_dir)
        result.markdown_path = str(final_dir / f"{out_stem}.md")
        return result

    started = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        parts = splitter.split_pdf(source, cap, tmp)
        part_out = Path(tmp) / "out"
        part_results = [
            process_one(str(p), opts, token=token, output_dir=part_out,
                        api=api, resume=False, timeout=timeout, engine=engine)
            for p in parts
        ]
        failed = [r for r in part_results if r.state == STATE_FAILED]
        if failed:
            result.state = STATE_FAILED
            result.error = f"part failed: {failed[0].error}"
            return result
        merged, n_images = _merge_parts(part_results, out_stem, final_dir)

    result.state = STATE_DONE
    result.api = part_results[0].api if part_results else api
    result.output_dir = str(final_dir)
    result.markdown_path = str(final_dir / f"{out_stem}.md")
    result.markdown = merged
    result.elapsed = round(time.monotonic() - started, 2)
    result.task_id = f"split:{len(parts)}parts"
    return result


def expand_inputs(raw_inputs) -> list:
    """Expand directories into supported files; pass through URLs and files.

    De-duplicates while preserving order: identical files (by resolved real path)
    and repeated URLs collapse to one, so a file passed twice — or matched by both
    an explicit path and a directory scan — is parsed once, not N times.
    """
    expanded, seen = [], set()

    def _add(display, key):
        if key not in seen:
            seen.add(key)
            expanded.append(display)

    for item in raw_inputs:
        if is_url(item):
            _add(item, item)
            continue
        path = Path(item)
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_file() and is_supported(child.name):
                    _add(str(child), str(child.resolve()))
        else:
            key = str(path.resolve()) if path.exists() else str(path)
            _add(item, key)
    return expanded


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mineru",
        description="Parse PDF / Office / image files into Markdown via MinerU.",
    )
    parser.add_argument("inputs", nargs="*", help="File(s), a directory, or a URL")
    parser.add_argument("--output", "-o", default="./output", help="Output directory (default: ./output)")
    parser.add_argument("--token", help="MinerU API token (or set MINERU_TOKEN)")
    parser.add_argument("--api", choices=["auto", "agent", "standard"], default="auto",
                        help="Cloud backend selection (default: auto)")
    parser.add_argument("--engine", choices=["cloud", "local", "auto"], default="cloud",
                        help="cloud (MinerU API) | local (offline pymupdf4llm, born-digital PDFs) | "
                             "auto (local if the PDF has text, else cloud). Default: cloud")
    parser.add_argument("--model", choices=["pipeline", "vlm", "MinerU-HTML"], default="vlm",
                        help="Standard API model (default: vlm)")
    parser.add_argument("--format", dest="formats", action="append", default=[],
                        choices=["docx", "html", "latex"], help="Extra export format (repeatable; forces Standard API)")
    parser.add_argument("--lang", default="ch", help="Document language code (default: ch)")
    parser.add_argument("--ocr", action="store_true", help="Enable OCR for scanned documents")
    parser.add_argument("--no-formula", action="store_true", help="Disable formula recognition")
    parser.add_argument("--no-table", action="store_true", help="Disable table recognition")
    parser.add_argument("--pages", help="Page range, e.g. '1-10' or '2,4-6' (Standard only)")
    parser.add_argument("--workers", "-w", type=int, default=DEFAULT_WORKERS,
                        help=f"Concurrent submit/upload/download slots (default: {DEFAULT_WORKERS})")
    parser.add_argument("--batch-size", type=int, default=BATCH_MAX_FILES,
                        help=f"Max files per Standard batch submit (default/max: {BATCH_MAX_FILES})")
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL,
                        help=f"Seconds between status polls (default: {DEFAULT_POLL_INTERVAL}, adaptive backoff)")
    parser.add_argument("--resume", action="store_true", help="Skip inputs already parsed")
    parser.add_argument("--obsidian", help="Shortcut for --to obsidian with this vault path")
    parser.add_argument("--to", dest="to", action="append", default=[], metavar="SINK",
                        help="Deliver parsed Markdown to a content tool (repeatable): "
                             "obsidian, logseq, siyuan, notion, linear, yuque, coda, slack, "
                             "feishu, confluence, onenote, ticktick, dingtalk, airtable, wecom")
    parser.add_argument("--list-sinks", action="store_true", help="List available delivery targets and exit")
    parser.add_argument("--doctor", action="store_true", help="Run an environment self-check and exit")
    parser.add_argument("--chunk", action="store_true", help="Also emit heading-aware RAG chunks (JSON sidecar + --json)")
    parser.add_argument("--chunk-size", type=int, default=2000, help="Max characters per chunk (default: 2000)")
    parser.add_argument("--split", action="store_true",
                        help="Split oversized PDFs past the page caps, parse parts, merge (needs pypdf)")
    parser.add_argument("--split-pages", type=int, help="Pages per split part (default: backend cap, 20 or 200)")
    parser.add_argument("--stdout", action="store_true", help="Print Markdown to stdout (single input)")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Print machine-readable status to stdout")
    parser.add_argument("--timeout", type=int, default=600, help="Per-input timeout in seconds (default: 600)")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress progress output")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def options_from_args(args) -> ParseOptions:
    return ParseOptions(
        model=args.model,
        language=args.lang,
        is_ocr=args.ocr,
        enable_formula=not args.no_formula,
        enable_table=not args.no_table,
        page_ranges=args.pages,
        extra_formats=tuple(args.formats),
    )


def _log(message, *, quiet):
    if not quiet:
        print(message, file=sys.stderr, flush=True)


def _load_sinks():
    """Import the optional ``sinks`` delivery package; return the module or None."""
    try:
        script_dir = str(Path(__file__).resolve().parent)
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        import sinks
        return sinks
    except Exception:  # pragma: no cover - sinks are optional
        return None


def _print_sinks() -> int:
    sinks = _load_sinks()
    if sinks is None:
        print("Delivery sinks unavailable (scripts/sinks not importable).", file=sys.stderr)
        return 1
    print("Available delivery targets (use --to NAME, repeatable):\n")
    for name in sinks.sink_names():
        sink = sinks.get_sink(name)
        req = ", ".join(sink.requires) if sink.requires else "(no config needed)"
        print(f"  {name:11} — {sink.label}\n{'':14}env: {req}")
    return 0


def _check_network() -> tuple:
    try:
        status, _ = _http("GET", "https://mineru.net/", timeout=8)
        return True, f"reachable (HTTP {status})"
    except Exception as exc:  # noqa: BLE001
        return False, f"unreachable ({type(exc).__name__})"


def _check_token(token: str) -> tuple:
    try:
        _api_json("POST", f"{STANDARD_API}/extract/task", token=token, payload={})
        return True, "accepted"
    except MinerUError as exc:
        if exc.code in ("A0202", "A0211"):
            return False, f"invalid/expired ({exc.code}) — refresh at https://mineru.net/apiManage/token"
        return True, "accepted (token authenticates; a parameter error is expected here)"
    except Exception as exc:  # noqa: BLE001
        return False, f"check failed ({type(exc).__name__})"


def _module_present(module: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _doctor(as_json: bool = False) -> int:
    """Environment self-check: Python, API reachability, token, optional extras, sinks."""
    import platform

    py_ok = sys.version_info >= (3, 8)
    net_ok, net_detail = _check_network()
    token = os.environ.get("MINERU_TOKEN")
    if not token:
        tok_ok, tok_detail = True, "not set (Agent API works token-free)"
    else:
        tok_ok, tok_detail = _check_token(token)

    extras = {
        "pypdf (--split)": _module_present("pypdf"),
        "pymupdf4llm (--engine local)": _module_present("pymupdf4llm"),
        "html-for-docx (wps sink)": _module_present("html4docx"),
        "roam-client (roam sink)": _module_present("roam_client"),
    }

    sinks = _load_sinks()
    if sinks is not None:
        names = sinks.sink_names()
        configured = [n for n in names if sinks.get_sink(n).is_configured()]
        sinks_detail = f"{len(names)} registered · {len(configured)} configured"
    else:
        sinks_detail = "unavailable"

    report = {
        "version": __version__,
        "python": {"ok": py_ok, "detail": platform.python_version()},
        "network": {"ok": net_ok, "detail": net_detail},
        "token": {"ok": tok_ok, "detail": tok_detail},
        "optional_extras": extras,
        "sinks": sinks_detail,
        "healthy": py_ok and net_ok and tok_ok,
    }

    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        mark = lambda ok: "✅" if ok else "❌"  # noqa: E731
        print(f"MinerU Skill doctor (v{__version__})\n")
        print(f"  {mark(py_ok)} Python            {report['python']['detail']}")
        print(f"  {mark(net_ok)} MinerU API        {net_detail}")
        print(f"  {mark(tok_ok)} MINERU_TOKEN      {tok_detail}")
        print("  · Optional extras:")
        for label, present in extras.items():
            print(f"      {mark(present)} {label}")
        print(f"  · Sinks: {sinks_detail}")
        print(f"\n{'✅ healthy' if report['healthy'] else '❌ issues found'}")
    return 0 if report["healthy"] else 1


def _deliver(results, names, sinks, *, quiet):
    """Deliver each completed result's Markdown to the requested sinks."""
    for res in results:
        if res.state != STATE_DONE or not res.markdown:
            continue
        doc = sinks.ParsedDoc(
            title=res.name, markdown=res.markdown, source=res.source,
            modality=res.modality, markdown_path=res.markdown_path,
        )
        for outcome in sinks.deliver_all(doc, names):
            res.sinks.append(outcome.to_status())
            if outcome.ok:
                _log(f"     📤 {res.name} → {outcome.sink}: {outcome.url or outcome.detail or 'ok'}",
                     quiet=quiet)
            else:
                _log(f"     ⚠️  {res.name} → {outcome.sink}: {outcome.error}", quiet=quiet)


def _chunk_results(results, *, max_chars, quiet):
    """Attach heading-aware RAG chunks to each result and write a JSON sidecar."""
    try:
        script_dir = str(Path(__file__).resolve().parent)
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        import chunking
    except Exception:  # pragma: no cover - chunking is stdlib, should always import
        _log("⚠️  --chunk requested but the chunking module is unavailable.", quiet=quiet)
        return
    for res in results:
        if res.state != STATE_DONE or not res.markdown:
            continue
        res.chunks = chunking.chunk_markdown(res.markdown, max_chars=max_chars, source=res.source)
        if res.markdown_path:
            sidecar = Path(res.markdown_path).with_suffix(".chunks.json")
            try:
                sidecar.write_text(json.dumps(res.chunks, ensure_ascii=False, indent=2), encoding="utf-8")
                _log(f"     🧩 {res.name}: {len(res.chunks)} chunk(s) → {sidecar}", quiet=quiet)
            except OSError:
                pass


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.doctor:
        return _doctor(as_json=args.as_json)

    if args.list_sinks:
        return _print_sinks()

    if args.obsidian:
        os.environ["OBSIDIAN_VAULT"] = str(Path(args.obsidian).expanduser())
        if "obsidian" not in args.to:
            args.to.append("obsidian")

    token = args.token or os.environ.get("MINERU_TOKEN")
    opts = options_from_args(args)
    output_dir = Path(args.output)

    sources = expand_inputs(args.inputs)
    if not sources:
        _log("No supported inputs found.", quiet=args.quiet)
        return 1

    unsupported = [s for s in sources if not is_url(s) and not is_supported(s)]
    if unsupported:
        _log(f"Unsupported file type(s): {', '.join(unsupported)}", quiet=args.quiet)
        return 1

    if (args.stdout or args.as_json) and len(sources) > 1:
        # Keep stdout machine-clean: route progress to stderr only (already does).
        pass

    workers = max(1, min(args.workers, len(sources)))
    _log(
        f"📚 {len(sources)} input(s) · workers={workers} · "
        f"{'token set' if token else 'no token (Agent API)'}",
        quiet=args.quiet,
    )

    cap = split_cap(token, args.api, args.split_pages)

    def log_result(res):
        icon = {"done": "✅", "skipped": "⏭️", "failed": "❌"}.get(res.state, "•")
        timing = f" ({res.elapsed}s)" if res.elapsed else ""
        _log(
            f"  {icon} [{res.api}/{res.modality}] {res.name}{timing}"
            + (f" — {res.error}" if res.error else ""),
            quiet=args.quiet,
        )

    results: list = []
    use_pipeline = args.engine == "cloud" and not args.split and len(sources) > 1

    if use_pipeline:
        results = run_pipeline(
            sources,
            opts,
            token=token,
            output_dir=output_dir,
            api=args.api,
            resume=args.resume,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
            batch_size=args.batch_size,
            workers=workers,
            want_markdown=bool(args.to) or args.chunk or args.stdout,
            on_result=log_result,
        )
    else:
        out_stem_of = dict(zip(sources, unique_out_stems(sources)))

        def run(source):
            res = None
            if args.split and args.engine != "local":
                res = process_split(
                    source, opts, token=token, output_dir=output_dir, api=args.api,
                    resume=args.resume, timeout=args.timeout, cap=cap, engine=args.engine,
                    out_stem=out_stem_of[source],
                )
            if res is None:
                res = process_one(
                    source, opts, token=token, output_dir=output_dir, api=args.api,
                    obsidian=None, resume=args.resume, timeout=args.timeout, engine=args.engine,
                    out_stem=out_stem_of[source],
                )
            log_result(res)
            return res

        if workers == 1:
            results = [run(s) for s in sources]
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(run, s): s for s in sources}
                for future in as_completed(futures):
                    results.append(future.result())

    done = [r for r in results if r.state == STATE_DONE]
    skipped = [r for r in results if r.state == "skipped"]
    failed = [r for r in results if r.state == STATE_FAILED]

    if args.to:
        sinks = _load_sinks()
        if sinks is None:
            _log("⚠️  --to requested but the sinks package is unavailable.", quiet=args.quiet)
        else:
            _deliver(results, args.to, sinks, quiet=args.quiet)

    if args.chunk:
        _chunk_results(results, max_chars=args.chunk_size, quiet=args.quiet)

    if args.as_json:
        print(json.dumps({
            "total": len(results),
            "done": len(done),
            "skipped": len(skipped),
            "failed": len(failed),
            "results": [r.to_status() for r in results],
        }, ensure_ascii=False, indent=2))
    elif args.stdout:
        for r in results:
            if r.markdown is not None:
                print(r.markdown)

    _log(
        f"\n{'='*48}\n✅ {len(done)} · ⏭️ {len(skipped)} · ❌ {len(failed)}"
        + (f"\n📁 {output_dir}" if done else ""),
        quiet=args.quiet,
    )
    if failed:
        _log("Failed: " + ", ".join(f"{r.name} ({r.error})" for r in failed), quiet=args.quiet)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
