"""Linear sink: create an issue from Markdown via the GraphQL API.

Linear's API is GraphQL at ``https://api.linear.app/graphql`` and authenticates
with a raw API key in the ``Authorization`` header (no ``Bearer`` prefix). The
issue description is Markdown; Linear renders inline ``data:`` image URIs, so
local images are read and embedded as base64 data URIs before delivery.
"""

from __future__ import annotations

import base64
from pathlib import Path

from . import _http, _md
from .base import ParsedDoc, Sink, SinkError, SinkResult, register

API = "https://api.linear.app/graphql"

_MUTATION = (
    "mutation IssueCreate($input: IssueCreateInput!)"
    "{issueCreate(input:$input){success issue{id url identifier}}}"
)

_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _data_uri(path: Path) -> str:
    mime = _MIME.get(path.suffix.lower(), "image/png")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


@register
class LinearSink(Sink):
    name = "linear"
    requires = ("LINEAR_API_KEY", "LINEAR_TEAM_ID")
    label = "Linear issue (GraphQL API)"

    def deliver(self, doc: ParsedDoc) -> SinkResult:
        key = self.env("LINEAR_API_KEY")
        team = self.env("LINEAR_TEAM_ID")
        headers = {"Authorization": key, "Content-Type": "application/json"}

        base_dir = Path(doc.markdown_path).parent if doc.markdown_path else None
        images = _md.find_local_images(doc.markdown, base_dir)
        mapping = {ref: _data_uri(path) for _alt, ref, path in images}
        body = _md.rewrite_images(doc.markdown, mapping)

        status, parsed = _http.request_json("POST", API, headers=headers, payload={
            "query": _MUTATION,
            "variables": {"input": {
                "teamId": team,
                "title": doc.title,
                "description": body,
            }},
        })
        if parsed.get("errors"):
            raise SinkError(str(parsed["errors"]))

        result = ((parsed.get("data") or {}).get("issueCreate")) or {}
        if not result.get("success"):
            raise SinkError(f"Linear did not create the issue (HTTP {status})")
        issue = result.get("issue") or {}

        return SinkResult(
            sink=self.name, ok=True,
            url=issue.get("url"),
            detail=f"{len(mapping)} image(s) inlined",
        )
