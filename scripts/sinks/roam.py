"""Roam Research sink — optional dependency.

There is no library that ingests a Markdown document into Roam, but the official
``roam-client`` SDK correctly handles the parts that are easy to get wrong — the
307/308 peer-host redirect, the dual ``Authorization`` / ``x-authorization``
Bearer headers, and the ``/write`` plumbing. So we lazily depend on it for
transport and only build the Markdown → block-tree ourselves, delivering the whole
document in a single ``batch-actions`` request (one HTTP round-trip).

Install the SDK (git-only, not on PyPI; needs Python ≥ 3.11):

    pip install "roam-client @ git+https://github.com/Roam-Research/backend-sdks.git#subdirectory=python"

Config: ``ROAM_API_TOKEN`` (graph edit token), ``ROAM_GRAPH_NAME``.
"""

from __future__ import annotations

import itertools
import re

from .base import ParsedDoc, Sink, SinkError, SinkResult, register

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_INSTALL_HINT = (
    'Roam sink needs the official SDK — pip install '
    '"roam-client @ git+https://github.com/Roam-Research/backend-sdks.git#subdirectory=python"'
)


def md_to_roam_tree(markdown: str) -> list:
    """Convert Markdown into a nested Roam block tree.

    Headings become parent blocks (``heading`` 1–3); the lines under a heading
    nest beneath it. Returns ``[{"string", "heading"?, "children": [...]}, ...]``.
    """
    roots: list = []
    stack: list = []  # [(heading_level, node)]
    for raw in markdown.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        match = _HEADING.match(line)
        if match:
            level = len(match.group(1))
            node = {"string": match.group(2), "heading": min(level, 3), "children": []}
            while stack and stack[-1][0] >= level:
                stack.pop()
            (stack[-1][1]["children"] if stack else roots).append(node)
            stack.append((level, node))
        else:
            node = {"string": line, "children": []}
            (stack[-1][1]["children"] if stack else roots).append(node)
    return roots


def tree_to_actions(children: list, parent_uid: str, uidgen) -> list:
    """Flatten a block tree into ``create-block`` actions for one batch request."""
    actions: list = []
    for order, node in enumerate(children):
        uid = uidgen()
        block = {"string": node["string"], "uid": uid}
        if node.get("heading"):
            block["heading"] = node["heading"]
        actions.append({
            "action": "create-block",
            "location": {"parent-uid": parent_uid, "order": order},
            "block": block,
        })
        actions.extend(tree_to_actions(node.get("children", []), uid, uidgen))
    return actions


@register
class RoamSink(Sink):
    name = "roam"
    aliases = ("roamresearch",)
    requires = ("ROAM_API_TOKEN", "ROAM_GRAPH_NAME")
    label = "Roam Research (batch-actions, optional dep)"

    def deliver(self, doc: ParsedDoc) -> SinkResult:
        try:
            from roam_client.client import create_page, initialize_graph
        except ImportError as exc:  # pragma: no cover - exercised via SinkError path
            raise SinkError(_INSTALL_HINT) from exc

        token = self.env("ROAM_API_TOKEN")
        graph = self.env("ROAM_GRAPH_NAME")
        client = initialize_graph({"token": token, "graph": graph})

        create_page(client, {"page": {"title": doc.title}})

        counter = itertools.count(1)
        actions = tree_to_actions(
            md_to_roam_tree(doc.markdown), doc.title, lambda: f"mu{next(counter):07d}"
        )
        if actions:
            client.call(
                f"/api/graph/{graph}/write", "POST",
                {"action": "batch-actions", "actions": actions},
            )
        return SinkResult(
            sink=self.name, ok=True,
            url=f"https://roamresearch.com/#/app/{graph}",
            detail=f"{len(actions)} block(s) via batch-actions (images need public URLs)",
        )
