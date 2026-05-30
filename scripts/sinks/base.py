"""Core types and the sink registry for delivering parsed Markdown to content tools.

A *sink* takes a :class:`ParsedDoc` (Markdown + local images + metadata) and
delivers it into one destination (Obsidian, Notion, Slack, Feishu, ...) using
that tool's OFFICIAL native ingestion path. Sinks read their configuration from
environment variables so an AI agent can run them without interactive prompts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedDoc:
    """A parsed document ready for delivery."""

    title: str
    markdown: str
    images: tuple = ()            # absolute paths to local image files
    source: str = ""
    modality: str = "unknown"
    markdown_path: Optional[str] = None


@dataclass
class SinkResult:
    """Outcome of delivering a :class:`ParsedDoc` to one sink."""

    sink: str
    ok: bool
    url: Optional[str] = None
    detail: Optional[str] = None
    error: Optional[str] = None

    def to_status(self) -> dict:
        return {
            "sink": self.sink,
            "ok": self.ok,
            "url": self.url,
            "detail": self.detail,
            "error": self.error,
        }


class SinkError(Exception):
    """Raised by a sink when delivery fails for a known reason."""


class Sink:
    """Base class for a delivery target.

    Subclasses set ``name``/``aliases``/``requires`` and implement
    :meth:`deliver`. ``requires`` lists the environment variables that must be
    present for the sink to be usable.
    """

    name: str = "base"
    aliases: tuple = ()
    requires: tuple = ()          # required env vars
    label: str = ""               # human description
    local: bool = False           # filesystem-only, no network/auth

    def env(self, key: str, default: Optional[str] = None) -> Optional[str]:
        value = os.environ.get(key, default)
        return value.strip() if isinstance(value, str) else value

    def missing_config(self) -> list:
        return [k for k in self.requires if not self.env(k)]

    def is_configured(self) -> bool:
        return not self.missing_config()

    def deliver(self, doc: ParsedDoc) -> SinkResult:  # pragma: no cover - abstract
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
REGISTRY: dict = {}


def register(cls):
    """Class decorator that instantiates a sink and registers it by name+aliases."""
    inst = cls()
    REGISTRY[inst.name] = inst
    for alias in inst.aliases:
        REGISTRY[alias] = inst
    return cls


def get_sink(name: str) -> Optional[Sink]:
    return REGISTRY.get(name.lower())


def sink_names() -> list:
    """Canonical sink names (no aliases), sorted."""
    return sorted({s.name for s in REGISTRY.values()})
