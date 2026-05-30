"""Heading-aware Markdown chunking for RAG pipelines (zero-dependency).

``chunk_markdown`` splits a parsed Markdown document into retrieval-sized chunks
that preserve heading context — matching the RAG-friendliness of LlamaParse /
Unstructured without any dependency.
"""

from __future__ import annotations

import re

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def _slug(text: str) -> str:
    text = (text or "doc").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "doc"


def _split_by_size(text: str, max_chars: int) -> list:
    """Split text into <= max_chars pieces on paragraph boundaries (hard-split if needed)."""
    if len(text) <= max_chars:
        return [text]
    pieces: list = []
    current = ""
    for para in text.split("\n\n"):
        if len(para) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            for i in range(0, len(para), max_chars):
                pieces.append(para[i:i + max_chars])
        elif not current:
            current = para
        elif len(current) + len(para) + 2 <= max_chars:
            current = f"{current}\n\n{para}"
        else:
            pieces.append(current)
            current = para
    if current:
        pieces.append(current)
    return pieces


def chunk_markdown(markdown: str, *, max_chars: int = 2000, source: str = "") -> list:
    """Chunk Markdown by heading, size-splitting long sections.

    Returns ``[{id, index, heading, text, chars, source}, ...]`` where ``heading``
    is the ``H1 > H2 > H3`` breadcrumb for the chunk.
    """
    lines = markdown.replace("\r\n", "\n").split("\n")
    chunks: list = []
    stack: list = []  # (level, text) heading breadcrumb
    buf: list = []
    base = _slug(source)

    def breadcrumb() -> str:
        return " > ".join(t for _, t in stack)

    def flush():
        text = "\n".join(buf).strip()
        buf.clear()
        if not text:
            return
        head = breadcrumb()
        for piece in _split_by_size(text, max_chars):
            idx = len(chunks)
            chunks.append({
                "id": f"{base}-{idx}",
                "index": idx,
                "heading": head,
                "text": piece,
                "chars": len(piece),
                "source": source,
            })

    for line in lines:
        match = _HEADING.match(line.strip())
        if match:
            flush()  # close the previous section under its own breadcrumb
            level = len(match.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, match.group(2)))
        buf.append(line)
    flush()
    return chunks
