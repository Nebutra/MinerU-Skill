"""Notion sink: create a page under a parent page from Markdown blocks.

Notion's native ingestion is the block API: each Markdown line becomes a typed
block (heading, quote, code, list item, paragraph). A page is created with up to
100 children inline; any remainder is appended in 100-block chunks via the
``/blocks/{id}/children`` PATCH endpoint.

Notion has no inline image-from-bytes path (images must be uploaded or hosted
separately), so local image refs are intentionally left untouched.
"""

from __future__ import annotations

from pathlib import Path

from . import _http, _md
from .base import ParsedDoc, Sink, SinkError, SinkResult, register

API = "https://api.notion.com/v1"
MAX_BLOCKS = 100
MAX_TEXT = 2000


def _rich(text: str) -> list:
    return [{"type": "text", "text": {"content": text[:MAX_TEXT]}}]


def _block(block_type: str, text: str, **extra) -> dict:
    inner = {"rich_text": _rich(text)}
    inner.update(extra)
    return {"object": "block", "type": block_type, block_type: inner}


def _is_numbered(text: str) -> bool:
    head = text.split(".", 1)
    return len(head) == 2 and head[0].isdigit() and head[1].startswith(" ")


def _blocks(markdown: str) -> list:
    """Convert flat Markdown lines into a list of Notion block dicts."""
    blocks = []
    in_code = False
    code_buf: list = []
    for raw in markdown.replace("\r\n", "\n").split("\n"):
        stripped = raw.strip()

        if stripped.startswith("```"):
            if in_code:
                blocks.append(_block("code", "\n".join(code_buf), language="plain text"))
                in_code = False
                code_buf = []
            else:
                in_code = True
                code_buf = []
            continue
        if in_code:
            code_buf.append(raw)
            continue

        if not stripped:
            continue
        if stripped.startswith("# "):
            blocks.append(_block("heading_1", stripped[2:].strip()))
        elif stripped.startswith("## "):
            blocks.append(_block("heading_2", stripped[3:].strip()))
        elif stripped.startswith("### "):
            blocks.append(_block("heading_3", stripped[4:].strip()))
        elif stripped.startswith("> "):
            blocks.append(_block("quote", stripped[2:].strip()))
        elif stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append(_block("bulleted_list_item", stripped[2:].strip()))
        elif _is_numbered(stripped):
            blocks.append(_block("numbered_list_item", stripped.split(".", 1)[1].strip()))
        else:
            blocks.append(_block("paragraph", stripped))

    if in_code:
        blocks.append(_block("code", "\n".join(code_buf), language="plain text"))
    return blocks


@register
class NotionSink(Sink):
    name = "notion"
    requires = ("NOTION_API_KEY", "NOTION_PARENT_PAGE_ID")
    label = "Notion page (blocks API)"

    def deliver(self, doc: ParsedDoc) -> SinkResult:
        key = self.env("NOTION_API_KEY")
        parent = self.env("NOTION_PARENT_PAGE_ID")
        version = self.env("NOTION_VERSION", "2022-06-28") or "2022-06-28"
        headers = {
            "Authorization": f"Bearer {key}",
            "Notion-Version": version,
            "Content-Type": "application/json",
        }

        # Count local images for the detail note (refs are left as-is).
        base_dir = Path(doc.markdown_path).parent if doc.markdown_path else None
        n_images = len(_md.find_local_images(doc.markdown, base_dir))

        blocks = _blocks(doc.markdown)
        status, parsed = _http.request_json("POST", f"{API}/pages", headers=headers, payload={
            "parent": {"page_id": parent},
            "properties": {"title": {"title": [{"text": {"content": doc.title}}]}},
            "children": blocks[:MAX_BLOCKS],
        })
        if parsed.get("object") == "error":
            raise SinkError(parsed.get("message") or f"Notion API error (HTTP {status})")
        created_id = parsed.get("id")
        if not created_id:
            raise SinkError(f"Notion did not return a page id (HTTP {status})")
        page_url = parsed.get("url")

        for start in range(MAX_BLOCKS, len(blocks), MAX_BLOCKS):
            chunk = blocks[start:start + MAX_BLOCKS]
            ch_status, ch_parsed = _http.request_json(
                "PATCH", f"{API}/blocks/{created_id}/children",
                headers=headers, payload={"children": chunk},
            )
            if ch_parsed.get("object") == "error":
                raise SinkError(ch_parsed.get("message")
                                or f"Notion block append failed (HTTP {ch_status})")

        if n_images:
            detail = (f"text+structure ({n_images} local images not embedded; "
                      f"Notion needs file upload)")
        else:
            detail = "text+structure"
        return SinkResult(sink=self.name, ok=True, url=page_url, detail=detail)
