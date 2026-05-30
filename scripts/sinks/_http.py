"""Zero-dependency HTTP helpers shared by all sinks (stdlib urllib only).

``http_request`` is the single seam tests monkeypatch.
"""

from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.request
from typing import Optional

USER_AGENT = "MinerU-Skill-sink/1.0"


def http_request(method, url, *, headers=None, data=None, timeout=60):
    """Perform one HTTP request. Returns ``(status_code, body_bytes)``."""
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        return exc.code, body


def request_json(method, url, *, headers=None, payload=None, timeout=60):
    """JSON request helper. Returns ``(status_code, parsed_json_or_empty_dict)``."""
    hdrs = dict(headers or {})
    body = None
    if payload is not None:
        hdrs.setdefault("Content-Type", "application/json")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    status, raw = http_request(method, url, headers=hdrs, data=body, timeout=timeout)
    parsed: dict = {}
    if raw:
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            parsed = {}
    return status, parsed


def encode_multipart(fields=None, files=None):
    """Build a ``multipart/form-data`` body with stdlib only.

    ``fields``: dict of str -> str. ``files``: list of (field_name, filename, bytes).
    Returns ``(content_type, body_bytes)``.
    """
    boundary = "----MinerUSinkBoundary7MA4YWxkTrZu0gW"
    crlf = b"\r\n"
    parts = []
    for name, value in (fields or {}).items():
        parts.append(b"--" + boundary.encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        parts.append(b"")
        parts.append(str(value).encode("utf-8"))
    for field_name, filename, content in files or []:
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        parts.append(b"--" + boundary.encode())
        parts.append(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"'.encode()
        )
        parts.append(f"Content-Type: {ctype}".encode())
        parts.append(b"")
        parts.append(content)
    parts.append(b"--" + boundary.encode() + b"--")
    parts.append(b"")
    body = crlf.join(parts)
    return f"multipart/form-data; boundary={boundary}", body
