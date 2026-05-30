"""OneNote sink: create a page from the parsed Markdown via Microsoft Graph.

OneNote pages are created by POSTing an HTML document to a section's ``pages``
endpoint with a pre-obtained Microsoft Graph access token (OAuth). Delivery
converts the Markdown to a full HTML document and creates the page.

Only remote images render — Graph fetches ``<img src>`` URLs, so local image
paths emitted by MinerU would need to be public URLs.
"""

from __future__ import annotations

import html
import json

from . import _http, _md
from .base import ParsedDoc, Sink, SinkError, SinkResult, register


@register
class OneNoteSink(Sink):
    name = "onenote"
    aliases = ("msonenote",)
    requires = ("ONENOTE_TOKEN", "ONENOTE_SECTION_ID")
    label = "OneNote section page (Microsoft Graph)"

    def deliver(self, doc: ParsedDoc) -> SinkResult:
        token = self.env("ONENOTE_TOKEN")
        section = self.env("ONENOTE_SECTION_ID")

        body_html = _md.md_to_html(doc.markdown)
        page = (
            "<!DOCTYPE html><html><head>"
            f"<title>{html.escape(doc.title)}</title>"
            f"</head><body>{body_html}</body></html>"
        )

        status, raw = _http.http_request(
            "POST",
            f"https://graph.microsoft.com/v1.0/me/onenote/sections/{section}/pages",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "text/html",
            },
            data=page.encode("utf-8"),
        )
        if status >= 400:
            preview = raw.decode("utf-8", "replace") if raw else ""
            raise SinkError(f"OneNote HTTP {status}: {preview[:200]}")
        if status != 201:
            raise SinkError(f"OneNote unexpected response (HTTP {status})")

        parsed = {}
        if raw:
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                parsed = {}
        links = parsed.get("links") or {}
        web = links.get("oneNoteWebUrl") or {}
        url = web.get("href")

        return SinkResult(
            sink=self.name, ok=True, url=url,
            detail="converted Markdown->HTML (remote images only; OAuth token required)",
        )
