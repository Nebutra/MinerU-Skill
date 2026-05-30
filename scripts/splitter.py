"""Split oversized PDFs into cap-sized parts so they clear the MinerU API limits.

The MinerU cloud caps at 20 pages (free Agent API) / 200 pages (Standard API).
``--split`` slices a larger PDF into parts locally, each is parsed, and the
Markdown is merged back — so we are no longer bound by those page caps (the same
trick mineru-converter uses). Uses the optional ``pypdf`` library, lazily
imported, so the core stays zero-dependency.

    pip install "mineru-skill[split]"   # i.e. pip install pypdf
"""

from __future__ import annotations

from pathlib import Path


class SplitError(Exception):
    """Raised when splitting is requested but cannot be performed."""


def _load_pypdf():
    try:
        import pypdf  # noqa: F401
        return pypdf
    except ImportError as exc:
        raise SplitError(
            "--split needs the pypdf library — pip install 'mineru-skill[split]' "
            "(i.e. pip install pypdf)"
        ) from exc


def pdf_page_count(path) -> int:
    """Return the page count of a local PDF (requires pypdf)."""
    pypdf = _load_pypdf()
    return len(pypdf.PdfReader(str(path)).pages)


def split_pdf(path, max_pages: int, out_dir) -> list:
    """Slice ``path`` into ``max_pages``-page parts under ``out_dir``.

    Returns the list of part paths (a single-element list pointing at the original
    file if it already fits).
    """
    if max_pages < 1:
        raise SplitError("max_pages must be >= 1")
    pypdf = _load_pypdf()
    reader = pypdf.PdfReader(str(path))
    total = len(reader.pages)
    if total <= max_pages:
        return [Path(path)]

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(path).stem
    parts = []
    for part_index, start in enumerate(range(0, total, max_pages), start=1):
        writer = pypdf.PdfWriter()
        for page in range(start, min(start + max_pages, total)):
            writer.add_page(reader.pages[page])
        part_path = out_dir / f"{stem}__part{part_index:03d}.pdf"
        with open(part_path, "wb") as handle:
            writer.write(handle)
        parts.append(part_path)
    return parts
