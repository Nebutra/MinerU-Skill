"""Yuque (语雀) sink: create a Markdown doc in a repository via the open API.

Yuque's open API (``https://www.yuque.com/api/v2``) authenticates with an
``X-Auth-Token`` header and creates docs under a repository namespace. The body
is posted as raw Markdown.

Yuque's open API has no asset-upload endpoint, so local image refs are left
untouched — host images at a public URL for them to render.
"""

from __future__ import annotations

from pathlib import Path

from . import _http, _md
from .base import ParsedDoc, Sink, SinkError, SinkResult, register

API = "https://www.yuque.com/api/v2"


@register
class YuqueSink(Sink):
    name = "yuque"
    aliases = ("语雀",)
    requires = ("YUQUE_TOKEN", "YUQUE_NAMESPACE")
    label = "Yuque doc (open API)"

    def deliver(self, doc: ParsedDoc) -> SinkResult:
        token = self.env("YUQUE_TOKEN")
        namespace = self.env("YUQUE_NAMESPACE")
        headers = {
            "X-Auth-Token": token,
            "User-Agent": "MinerU-Skill/3.0",
            "Content-Type": "application/json",
        }

        base_dir = Path(doc.markdown_path).parent if doc.markdown_path else None
        n_images = len(_md.find_local_images(doc.markdown, base_dir))

        status, parsed = _http.request_json(
            "POST", f"{API}/repos/{namespace}/docs", headers=headers, payload={
                "title": doc.title,
                "slug": _md.slugify(doc.title),
                "public": 0,
                "format": "markdown",
                "body": doc.markdown,
            },
        )

        data = parsed.get("data")
        if not data:
            if status >= 400 or parsed.get("message"):
                raise SinkError(parsed.get("message") or f"HTTP {status}")
            raise SinkError(f"Yuque returned no doc data (HTTP {status})")

        slug = data.get("slug")
        if n_images:
            detail = f"text only ({n_images} local image(s); host images publicly to embed)"
        else:
            detail = "text only"
        return SinkResult(
            sink=self.name, ok=True,
            url=f"https://www.yuque.com/{namespace}/{slug}",
            detail=detail,
        )
