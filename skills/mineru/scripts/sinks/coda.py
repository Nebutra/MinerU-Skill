"""Coda sink: deliver Markdown as a page, into an existing doc or a new one.

Coda's API (``https://coda.io/apis/v1``) authenticates with a Bearer token.
Markdown is delivered as canvas page content. If ``CODA_DOC_ID`` is set, a new
page is added to that doc; otherwise a new doc is created with the content as its
initial page.

Coda canvas content embeds images by URL only, so local image refs are left
untouched — host images at a public URL for them to render.
"""

from __future__ import annotations

from pathlib import Path

from . import _http, _md
from .base import ParsedDoc, Sink, SinkError, SinkResult, register

API = "https://coda.io/apis/v1"


def _canvas(markdown: str) -> dict:
    return {"type": "canvas", "canvasContent": {"format": "markdown", "content": markdown}}


@register
class CodaSink(Sink):
    name = "coda"
    requires = ("CODA_API_TOKEN",)
    label = "Coda page (REST API)"

    def deliver(self, doc: ParsedDoc) -> SinkResult:
        token = self.env("CODA_API_TOKEN")
        doc_id = self.env("CODA_DOC_ID")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        base_dir = Path(doc.markdown_path).parent if doc.markdown_path else None
        n_images = len(_md.find_local_images(doc.markdown, base_dir))

        if doc_id:
            status, parsed = _http.request_json(
                "POST", f"{API}/docs/{doc_id}/pages", headers=headers, payload={
                    "name": doc.title,
                    "pageContent": _canvas(doc.markdown),
                },
            )
        else:
            status, parsed = _http.request_json(
                "POST", f"{API}/docs", headers=headers, payload={
                    "title": doc.title,
                    "initialPage": {
                        "name": doc.title,
                        "pageContent": _canvas(doc.markdown),
                    },
                },
            )

        if status >= 400:
            raise SinkError(parsed.get("message") or f"HTTP {status}")

        if n_images:
            detail = f"text only ({n_images} local image(s); Coda embeds images by URL)"
        else:
            detail = "text only"
        return SinkResult(
            sink=self.name, ok=True,
            url=parsed.get("browserLink"),
            detail=detail,
        )
