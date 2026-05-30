"""WPS / 金山文档 (Kingsoft kdocs) sink — optional dependency.

The native ingestion path is: Markdown → ``.docx`` → upload to the kdocs cloud
appspace. There is no official Python SDK, so:

* Markdown→DOCX uses the maintained, pure-pip ``html-for-docx`` package
  (reusing this project's Markdown→HTML), lazily imported so the core stays
  zero-dependency. Install with ``pip install mineru-skill[wps]``.
* The kdocs WPS-2 request signing (plain SHA-1) and multipart upload are done
  with the standard library — small and fully documented.

Cloud upload requires an approved kdocs developer app (``WPS_APP_ID`` /
``WPS_APP_SECRET``) and a provisioned appspace; it is opt-in and surfaces the
raw kdocs error on failure. Docs: https://developer.kdocs.cn/server/guide/signature.html
"""

from __future__ import annotations

import email.utils
import hashlib
import io
import json

from . import _http, _md
from .base import ParsedDoc, Sink, SinkError, SinkResult, register

KDOCS_UPLOAD = "https://developer.kdocs.cn/api/v1/openapi/appspace/files/upload"


def _markdown_to_docx_bytes(markdown: str) -> bytes:
    """Convert Markdown → HTML → DOCX bytes via the optional html-for-docx lib."""
    try:
        from html4docx import HtmlToDocx  # pip install html-for-docx
    except ImportError as exc:  # pragma: no cover - exercised via SinkError path
        raise SinkError(
            "WPS sink needs a Markdown→DOCX converter — "
            "pip install 'mineru-skill[wps]'  (i.e. pip install html-for-docx)"
        ) from exc
    html = _md.md_to_html(markdown)
    document = HtmlToDocx().parse_html_string(html)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _wps2_headers(app_id: str, app_secret: str, body: bytes, content_type: str) -> dict:
    """Build kdocs WPS-2 auth headers.

    signature = sha1(app_secret + content_md5 + content_type + date) hex.
    Content-Md5 / Content-Type must match the exact wire body and header sent.
    """
    content_md5 = hashlib.md5(body).hexdigest()
    date = email.utils.formatdate(usegmt=True)  # RFC1123 GMT
    signature = hashlib.sha1(
        (app_secret + content_md5 + content_type + date).encode("utf-8")
    ).hexdigest()
    return {
        "Date": date,
        "Content-Md5": content_md5,
        "Content-Type": content_type,
        "Authorization": f"WPS-2:{app_id}:{signature}",
    }


@register
class WpsSink(Sink):
    name = "wps"
    aliases = ("kdocs", "金山文档", "金山")
    requires = ("WPS_APP_ID", "WPS_APP_SECRET")
    label = "WPS / 金山文档 (Markdown→DOCX upload, optional dep)"

    def deliver(self, doc: ParsedDoc) -> SinkResult:
        app_id = self.env("WPS_APP_ID")
        app_secret = self.env("WPS_APP_SECRET")

        docx_bytes = _markdown_to_docx_bytes(doc.markdown)
        filename = _md.safe_filename(doc.title) + ".docx"

        fields = {}
        parent_path = self.env("WPS_PARENT_PATH")
        parent_token = self.env("WPS_PARENT_TOKEN")
        if parent_path:
            fields["parent_path"] = parent_path
        if parent_token:
            fields["parent_token"] = parent_token

        content_type, body = _http.encode_multipart(
            fields=fields, files=[("file", filename, docx_bytes)]
        )
        headers = _wps2_headers(app_id, app_secret, body, content_type)

        status, raw = _http.http_request("POST", KDOCS_UPLOAD, headers=headers, data=body)
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            parsed = {}
        if status >= 400 or parsed.get("code") not in (0, None):
            raise SinkError(parsed.get("message") or parsed.get("msg") or f"kdocs HTTP {status}")

        file_token = (parsed.get("data") or {}).get("file_token")
        return SinkResult(
            sink=self.name, ok=True, url=file_token,
            detail="Markdown→DOCX uploaded to 金山文档 (experimental; needs a provisioned appspace)",
        )
