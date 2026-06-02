"""Confluence sink: create a page from the parsed Markdown via the Cloud REST API.

Confluence Cloud ingests content as *storage-format* HTML. Delivery converts the
Markdown to HTML and creates a page with the v2 REST API
(``POST /wiki/api/v2/pages``) using Basic auth (email + API token).

Local images are not attached — Confluence storage HTML references attachments by
filename, which would require a separate upload step.
"""

from __future__ import annotations

import base64

from . import _http, _md
from .base import ParsedDoc, Sink, SinkError, SinkResult, register


@register
class ConfluenceSink(Sink):
    name = "confluence"
    requires = (
        "CONFLUENCE_BASE_URL",
        "CONFLUENCE_EMAIL",
        "CONFLUENCE_API_TOKEN",
        "CONFLUENCE_SPACE_ID",
    )
    label = "Confluence Cloud page (storage HTML)"

    def deliver(self, doc: ParsedDoc) -> SinkResult:
        base = self.env("CONFLUENCE_BASE_URL").rstrip("/")
        email = self.env("CONFLUENCE_EMAIL")
        token = self.env("CONFLUENCE_API_TOKEN")
        space = self.env("CONFLUENCE_SPACE_ID")

        auth = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
        headers = {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        }

        html = _md.md_to_html(doc.markdown)
        status, parsed = _http.request_json(
            "POST",
            f"{base}/wiki/api/v2/pages",
            headers=headers,
            payload={
                "spaceId": space,
                "status": "current",
                "title": doc.title,
                "body": {"representation": "storage", "value": html},
            },
        )
        if status >= 400:
            raise SinkError(
                parsed.get("title")
                or parsed.get("message")
                or f"Confluence HTTP {status}"
            )

        webui = (parsed.get("_links") or {}).get("webui")
        url = base + webui if webui else None
        return SinkResult(
            sink=self.name, ok=True, url=url,
            detail="converted Markdown->storage HTML (local images not attached)",
        )
