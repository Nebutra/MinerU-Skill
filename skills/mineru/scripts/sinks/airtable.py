"""Airtable sink — store parsed Markdown as a record in a base/table.

Airtable is a database, not a document tool: the native ingestion path is a
record whose fields hold the title and the Markdown body. Field names are
configurable to match an existing table schema.

Docs: https://airtable.com/developers/web/api/create-records
(POST /v0/{baseId}/{tableIdOrName}).
"""

from __future__ import annotations

import urllib.parse

from . import _http
from .base import ParsedDoc, Sink, SinkError, SinkResult, register

API_BASE = "https://api.airtable.com/v0"


@register
class AirtableSink(Sink):
    name = "airtable"
    requires = ("AIRTABLE_API_KEY", "AIRTABLE_BASE_ID", "AIRTABLE_TABLE")
    label = "Airtable record (database)"

    def deliver(self, doc: ParsedDoc) -> SinkResult:
        api_key = self.env("AIRTABLE_API_KEY")
        base = self.env("AIRTABLE_BASE_ID")
        table = self.env("AIRTABLE_TABLE")
        title_field = self.env("AIRTABLE_TITLE_FIELD", "Title")
        body_field = self.env("AIRTABLE_BODY_FIELD", "Notes")

        url = f"{API_BASE}/{base}/{urllib.parse.quote(table)}"
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {"fields": {title_field: doc.title, body_field: doc.markdown}}

        status, parsed = _http.request_json("POST", url, headers=headers, payload=payload)

        if parsed.get("error") or status >= 400:
            raise SinkError(str(parsed.get("error") or f"HTTP {status}"))
        if not parsed.get("id"):
            raise SinkError(f"Airtable returned no record id: {parsed}")

        return SinkResult(
            sink=self.name,
            ok=True,
            url=None,
            detail="stored as a database record (Airtable is a DB, not a doc)",
        )
