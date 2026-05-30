"""SiYuan sink: create a new document from Markdown via the local kernel API.

SiYuan (思源笔记) exposes a kernel HTTP API (default ``http://127.0.0.1:6806``)
authenticated with an API token. Delivery follows SiYuan's native ingestion path:

1. Resolve the target notebook (``SIYUAN_NOTEBOOK`` or the first listed notebook).
2. Upload each referenced local image via ``/api/asset/upload`` and rewrite the
   Markdown to point at the returned ``assets/...`` paths.
3. Create the document with ``/api/filetree/createDocWithMd``.

Every kernel response wraps its payload as ``{"code": 0, "msg": "", "data": ...}``;
a non-zero ``code`` is an error.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import _http, _md
from .base import ParsedDoc, Sink, SinkError, SinkResult, register


@register
class SiYuanSink(Sink):
    name = "siyuan"
    requires = ("SIYUAN_TOKEN",)
    label = "SiYuan notebook (local kernel API)"

    def _json_post(self, base: str, path: str, headers: dict, payload: dict):
        """POST JSON; return ``data`` after verifying ``code == 0``."""
        try:
            status, parsed = _http.request_json("POST", f"{base}{path}",
                                                headers=headers, payload=payload)
        except Exception as exc:  # noqa: BLE001
            raise self._unreachable(base, exc) from exc
        return self._unwrap(base, status, parsed)

    def _upload_post(self, base: str, headers: dict, content_type: str, body: bytes):
        """POST a multipart body; return ``data`` after verifying ``code == 0``."""
        hdrs = dict(headers)
        hdrs["Content-Type"] = content_type
        try:
            status, raw = _http.http_request("POST", f"{base}/api/asset/upload",
                                             headers=hdrs, data=body)
        except Exception as exc:  # noqa: BLE001
            raise self._unreachable(base, exc) from exc
        parsed: dict = {}
        if raw:
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                parsed = {}
        return self._unwrap(base, status, parsed)

    @staticmethod
    def _unreachable(base: str, exc=None) -> SinkError:
        suffix = f" ({exc})" if exc else ""
        return SinkError(
            f"SiYuan kernel not reachable at {base} — start SiYuan and enable "
            f"the API token{suffix}"
        )

    def _unwrap(self, base: str, status: int, parsed: dict):
        if status == 0:
            raise self._unreachable(base)
        if parsed.get("code") != 0:
            raise SinkError(parsed.get("msg") or f"SiYuan API error (HTTP {status})")
        return parsed.get("data")

    def deliver(self, doc: ParsedDoc) -> SinkResult:
        base = (self.env("SIYUAN_API_URL", "http://127.0.0.1:6806")
                or "http://127.0.0.1:6806").rstrip("/")
        token = self.env("SIYUAN_TOKEN")
        headers = {"Authorization": f"Token {token}"}

        notebook = self.env("SIYUAN_NOTEBOOK")
        if not notebook:
            data = self._json_post(base, "/api/notebook/lsNotebooks", headers, {})
            notebooks = (data or {}).get("notebooks") or []
            if not notebooks:
                raise SinkError("SiYuan has no notebooks — create one before delivering")
            notebook = notebooks[0]["id"]

        base_dir = Path(doc.markdown_path).parent if doc.markdown_path else None
        images = _md.find_local_images(doc.markdown, base_dir)
        mapping = {}
        for _alt, ref, path in images:
            content_type, body = _http.encode_multipart(
                fields={"assetsDirPath": "/assets/"},
                files=[("file[]", path.name, path.read_bytes())],
            )
            data = self._upload_post(base, headers, content_type, body)
            succ_map = (data or {}).get("succMap") or {}
            if path.name in succ_map:
                mapping[ref] = succ_map[path.name]
        body_md = _md.rewrite_images(doc.markdown, mapping)

        docid = self._json_post(base, "/api/filetree/createDocWithMd", headers, {
            "notebook": notebook,
            "path": "/" + _md.safe_filename(doc.title),
            "markdown": body_md,
        })
        if not docid:
            raise SinkError("SiYuan did not return a document id")

        return SinkResult(
            sink=self.name, ok=True,
            url=f"siyuan://blocks/{docid}",
            detail=f"{len(mapping)} image(s)",
        )
