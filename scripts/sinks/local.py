"""Local-first sinks: Obsidian and Logseq (filesystem writes, no auth).

Both tools are folders of Markdown files. The native ingestion is a filesystem
write following each tool's conventions:

* Obsidian — a flat note with YAML frontmatter; images in a per-note assets
  folder, referenced with relative Markdown embeds.
* Logseq — an outline (every line a ``- `` block) with ``key:: value`` page
  properties on the first block; images in ``assets/`` referenced as
  ``![](../assets/x.png)``.
"""

from __future__ import annotations

from pathlib import Path

from . import _md
from .base import ParsedDoc, Sink, SinkError, SinkResult, register


def _copy_images(doc: ParsedDoc, dest_dir: Path, ref_prefix: str) -> dict:
    """Copy referenced local images into ``dest_dir``; return ``{old_ref: new_ref}``."""
    base = Path(doc.markdown_path).parent if doc.markdown_path else None
    mapping = {}
    images = _md.find_local_images(doc.markdown, base)
    if images:
        dest_dir.mkdir(parents=True, exist_ok=True)
    for _alt, ref, path in images:
        target = dest_dir / path.name
        target.write_bytes(path.read_bytes())
        mapping[ref] = f"{ref_prefix}{path.name}"
    return mapping


@register
class ObsidianSink(Sink):
    name = "obsidian"
    aliases = ("ob",)
    requires = ("OBSIDIAN_VAULT",)
    label = "Obsidian vault (local Markdown)"
    local = True

    def deliver(self, doc: ParsedDoc) -> SinkResult:
        vault = Path(self.env("OBSIDIAN_VAULT")).expanduser()
        if not vault.is_dir():
            raise SinkError(f"Obsidian vault not found: {vault}")
        subdir = self.env("OBSIDIAN_SUBDIR", "") or ""
        note_dir = vault / subdir if subdir else vault
        note_dir.mkdir(parents=True, exist_ok=True)

        stem = _md.safe_filename(doc.title)
        assets = note_dir / f"{stem}.assets"
        mapping = _copy_images(doc, assets, f"{stem}.assets/")
        body = _md.rewrite_images(doc.markdown, mapping)

        front = _md.yaml_frontmatter({
            "title": doc.title,
            "source": doc.source,
            "modality": doc.modality,
            "tags": ["mineru", "parsed"],
        })
        note_path = note_dir / f"{stem}.md"
        note_path.write_text(f"{front}\n\n{body}\n", encoding="utf-8")
        return SinkResult(sink=self.name, ok=True, url=str(note_path),
                          detail=f"{len(mapping)} image(s)")


@register
class LogseqSink(Sink):
    name = "logseq"
    requires = ("LOGSEQ_GRAPH",)
    label = "Logseq graph (local outline)"
    local = True

    def deliver(self, doc: ParsedDoc) -> SinkResult:
        graph = Path(self.env("LOGSEQ_GRAPH")).expanduser()
        if not graph.is_dir():
            raise SinkError(f"Logseq graph not found: {graph}")
        pages = graph / "pages"
        assets = graph / "assets"
        pages.mkdir(parents=True, exist_ok=True)

        stem = _md.safe_filename(doc.title)
        # Namespace asset names by page slug to avoid collisions in the shared assets/.
        prefix = _md.slugify(doc.title)
        mapping = {}
        base = Path(doc.markdown_path).parent if doc.markdown_path else None
        images = _md.find_local_images(doc.markdown, base)
        if images:
            assets.mkdir(parents=True, exist_ok=True)
        for _alt, ref, path in images:
            new_name = f"{prefix}-{path.name}"
            (assets / new_name).write_bytes(path.read_bytes())
            mapping[ref] = f"../assets/{new_name}"
        body = _md.rewrite_images(doc.markdown, mapping)

        outline = _md.md_to_logseq(body, properties={
            "title": doc.title,
            "source": doc.source,
            "tags": "mineru, parsed",
        })
        page_path = pages / f"{stem}.md"
        page_path.write_text(outline + "\n", encoding="utf-8")
        return SinkResult(sink=self.name, ok=True, url=str(page_path),
                          detail=f"{len(mapping)} image(s)")
