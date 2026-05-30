"""Small, dependency-free Markdown utilities used by sinks.

These are intentionally pragmatic, not a full CommonMark implementation: they
cover the constructs MinerU emits (headings, emphasis, code, lists, tables,
blockquotes, links, images) well enough to deliver faithful content to tools
that require HTML (Confluence, OneNote) or an outline (Logseq).
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Optional

_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<ref>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
_ILLEGAL_FS = re.compile(r'[\\/:*?"<>|#^\[\]]+')


def slugify(text: str, default: str = "document") -> str:
    """Filesystem/URL-safe slug."""
    text = text.strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^a-z0-9\-]+", "", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or default


def safe_filename(title: str, default: str = "document") -> str:
    """Clean a title into a safe note filename (keeps unicode, drops illegal chars)."""
    name = _ILLEGAL_FS.sub(" ", title).strip()
    name = re.sub(r"\s{2,}", " ", name)
    return name[:120] or default


def is_remote(ref: str) -> bool:
    return ref.startswith("http://") or ref.startswith("https://") or ref.startswith("data:")


def find_local_images(markdown: str, base_dir) -> list:
    """Return ``[(alt, ref, Path)]`` for image refs that point at existing local files."""
    base = Path(base_dir) if base_dir else None
    found = []
    seen = set()
    for match in _IMAGE_RE.finditer(markdown):
        ref = match.group("ref")
        if is_remote(ref) or ref in seen:
            continue
        path = Path(ref)
        if not path.is_absolute() and base is not None:
            path = base / ref
        if path.is_file():
            found.append((match.group("alt"), ref, path))
            seen.add(ref)
    return found


def rewrite_images(markdown: str, mapping: dict) -> str:
    """Rewrite local image refs using ``{old_ref: new_ref}``."""
    def repl(match):
        ref = match.group("ref")
        if ref in mapping:
            return f"![{match.group('alt')}]({mapping[ref]})"
        return match.group(0)

    return _IMAGE_RE.sub(repl, markdown)


def yaml_frontmatter(props: dict) -> str:
    """Render a YAML frontmatter block. List values become ``- item`` lines."""
    lines = ["---"]
    for key, value in props.items():
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Inline + block Markdown -> HTML (pragmatic, XHTML-safe)
# --------------------------------------------------------------------------- #
def _inline(text: str) -> str:
    """Convert inline Markdown to HTML on already-escaped text."""
    # images first, then links
    text = _IMAGE_RE.sub(
        lambda m: f'<img src="{html.escape(m.group("ref"), quote=True)}" alt="{m.group("alt")}" />',
        text,
    )
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>', text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    return text


def md_to_html(markdown: str) -> str:
    """Convert a Markdown document to a pragmatic, XHTML-safe HTML fragment."""
    out = []
    lines = markdown.replace("\r\n", "\n").split("\n")
    i = 0
    n = len(lines)
    in_code = False
    code_buf: list = []
    list_stack: list = []  # 'ul' / 'ol'

    def close_lists():
        while list_stack:
            out.append(f"</{list_stack.pop()}>")

    while i < n:
        line = lines[i]
        fence = line.strip().startswith("```")
        if fence and not in_code:
            close_lists()
            in_code = True
            code_buf = []
            i += 1
            continue
        if fence and in_code:
            out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
            in_code = False
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        stripped = line.strip()
        if not stripped:
            close_lists()
            i += 1
            continue

        # table block
        if "|" in stripped and i + 1 < n and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]):
            close_lists()
            header = [c.strip() for c in stripped.strip("|").split("|")]
            rows = []
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table><thead><tr>"
                       + "".join(f"<th>{_inline(html.escape(c))}</th>" for c in header)
                       + "</tr></thead><tbody>")
            for row in rows:
                out.append("<tr>" + "".join(f"<td>{_inline(html.escape(c))}</td>" for c in row) + "</tr>")
            out.append("</tbody></table>")
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            close_lists()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(html.escape(heading.group(2)))}</h{level}>")
            i += 1
            continue

        if stripped.startswith(">"):
            close_lists()
            out.append(f"<blockquote>{_inline(html.escape(stripped[1:].strip()))}</blockquote>")
            i += 1
            continue

        if re.match(r"^([-*+])\s+", stripped):
            if not list_stack or list_stack[-1] != "ul":
                close_lists()
                list_stack.append("ul")
                out.append("<ul>")
            item = re.sub(r"^([-*+])\s+", "", stripped)
            out.append(f"<li>{_inline(html.escape(item))}</li>")
            i += 1
            continue

        if re.match(r"^\d+\.\s+", stripped):
            if not list_stack or list_stack[-1] != "ol":
                close_lists()
                list_stack.append("ol")
                out.append("<ol>")
            item = re.sub(r"^\d+\.\s+", "", stripped)
            out.append(f"<li>{_inline(html.escape(item))}</li>")
            i += 1
            continue

        if re.match(r"^([-*_])\1{2,}$", stripped):
            close_lists()
            out.append("<hr />")
            i += 1
            continue

        close_lists()
        out.append(f"<p>{_inline(html.escape(stripped))}</p>")
        i += 1

    if in_code:
        out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
    close_lists()
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Markdown -> Logseq outline
# --------------------------------------------------------------------------- #
def md_to_logseq(markdown: str, properties: Optional[dict] = None) -> str:
    """Convert flat Markdown into a Logseq outline.

    Every line becomes a ``- `` block. Headings are top-level blocks; the content
    that follows a heading nests one level beneath it. Page properties
    (``key:: value``) go on the first block, as Logseq requires.
    """
    out = []
    if properties:
        prop_lines = []
        for key, value in properties.items():
            if not value:
                continue
            if isinstance(value, (list, tuple)):
                value = ", ".join(str(v) for v in value)
            prop_lines.append(f"{key}:: {value}")
        if prop_lines:
            out.append("- " + prop_lines[0])
            out.extend(f"  {p}" for p in prop_lines[1:])

    have_heading = False
    for raw in markdown.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^#{1,6}\s+", line):
            out.append(f"- {line}")
            have_heading = True
        elif have_heading:
            out.append(f"\t- {line}")
        else:
            out.append(f"- {line}")
    return "\n".join(out)
