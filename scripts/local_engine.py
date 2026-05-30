"""Optional fully-offline parsing backend for born-digital PDFs.

Our single biggest honest gap is being cloud-only. ``--engine local`` parses a
PDF **entirely offline** with the optional, lightweight ``pymupdf4llm`` library
(no GPU, no cloud, no upload caps) — ideal for confidential or born-digital PDFs
where MinerU's cloud VLM is overkill. Scanned/complex docs still want the cloud
engine, so ``--engine auto`` only uses local when the PDF has real text.

    pip install "mineru-skill[local]"   # i.e. pip install pymupdf4llm
"""

from __future__ import annotations

from pathlib import Path

_HINT = (
    "--engine local needs pymupdf4llm — pip install 'mineru-skill[local]' "
    "(i.e. pip install pymupdf4llm)"
)


class LocalEngineError(Exception):
    """Raised when local parsing is requested but cannot be performed."""


def available() -> bool:
    try:
        import pymupdf4llm  # noqa: F401
        return True
    except ImportError:
        return False


def is_born_digital(path, min_chars: int = 200) -> bool:
    """True if the PDF has extractable text (so local parsing is appropriate)."""
    try:
        import pymupdf
    except ImportError:
        return False
    doc = pymupdf.open(str(path))
    total = 0
    for page in doc:
        total += len(page.get_text().strip())
        if total >= min_chars:
            return True
    return total >= min_chars


def parse_local(path, output_dir=None) -> str:
    """Parse a PDF to Markdown fully offline. Returns the Markdown string."""
    try:
        import pymupdf4llm
    except ImportError as exc:
        raise LocalEngineError(_HINT) from exc
    if output_dir is not None:
        images = Path(output_dir) / "images"
        images.mkdir(parents=True, exist_ok=True)
        return pymupdf4llm.to_markdown(str(path), write_images=True, image_path=str(images))
    return pymupdf4llm.to_markdown(str(path))
