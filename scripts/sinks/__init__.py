"""Pluggable delivery sinks for parsed Markdown.

Each submodule registers one or more :class:`Sink` implementations that deliver a
:class:`ParsedDoc` into a content tool using that tool's official ingestion path.
Importing this package populates the registry; a sink module that fails to import
is recorded in :data:`IMPORT_ERRORS` rather than breaking the others.
"""

from __future__ import annotations

import importlib
import sys

from .base import (  # noqa: F401
    ParsedDoc,
    Sink,
    SinkError,
    SinkResult,
    get_sink,
    sink_names,
    REGISTRY,
)

# Sink modules to load. Order is cosmetic.
_MODULES = [
    "local",       # obsidian, logseq (filesystem)
    "siyuan",
    "notion",
    "linear",
    "yuque",
    "coda",
    "ticktick",
    "dingtalk",
    "airtable",
    "wecom",
    "slack",
    "feishu",
    "confluence",
    "onenote",
    "roam",        # optional dependency (roam-client)
    "wps",         # optional dependency (html-for-docx)
]

IMPORT_ERRORS: dict = {}

for _name in _MODULES:
    try:
        importlib.import_module(f"{__name__}.{_name}")
    except Exception as exc:  # noqa: BLE001 - a bad sink shouldn't break the rest
        IMPORT_ERRORS[_name] = f"{type(exc).__name__}: {exc}"
        print(f"[sinks] failed to load {_name}: {exc}", file=sys.stderr)


def deliver_all(doc: ParsedDoc, names) -> list:
    """Deliver ``doc`` to each named sink, returning a list of :class:`SinkResult`."""
    results = []
    for name in names:
        sink = get_sink(name)
        if sink is None:
            results.append(SinkResult(sink=name, ok=False, error=f"unknown sink '{name}'"))
            continue
        missing = sink.missing_config()
        if missing:
            results.append(SinkResult(
                sink=sink.name, ok=False,
                error=f"missing config: {', '.join(missing)}",
            ))
            continue
        try:
            results.append(sink.deliver(doc))
        except SinkError as exc:
            results.append(SinkResult(sink=sink.name, ok=False, error=str(exc)))
        except Exception as exc:  # noqa: BLE001 - surface but never crash the run
            results.append(SinkResult(sink=sink.name, ok=False, error=f"{type(exc).__name__}: {exc}"))
    return results
