"""Slack sink: upload the parsed Markdown as a file via the external-upload flow.

Slack deprecated ``files.upload`` (retired) in favour of a three-step external
upload. Delivery follows that official path:

1. ``files.getUploadURLExternal`` — reserve an upload URL + file id for the
   given filename and byte length.
2. ``POST`` the raw bytes to the returned upload URL.
3. ``files.completeUploadExternal`` — finalize the upload, attach it to the
   target channel, and post an initial comment.

Images are *not* embedded: Markdown is uploaded as a single ``.md`` file.
"""

from __future__ import annotations

import urllib.parse

from . import _http, _md
from .base import ParsedDoc, Sink, SinkError, SinkResult, register


@register
class SlackSink(Sink):
    name = "slack"
    requires = ("SLACK_BOT_TOKEN", "SLACK_CHANNEL")
    label = "Slack channel (file upload)"

    def deliver(self, doc: ParsedDoc) -> SinkResult:
        token = self.env("SLACK_BOT_TOKEN")
        channel = self.env("SLACK_CHANNEL")
        auth = {"Authorization": f"Bearer {token}"}

        content = doc.markdown.encode("utf-8")
        filename = _md.slugify(doc.title) + ".md"

        # Step 1: reserve an external upload URL + file id. This endpoint wants
        # form-encoded data, so use http_request and parse the JSON response.
        form = urllib.parse.urlencode({
            "filename": filename,
            "length": len(content),
        }).encode("utf-8")
        status, raw = _http.http_request(
            "POST",
            "https://slack.com/api/files.getUploadURLExternal",
            headers={**auth, "Content-Type": "application/x-www-form-urlencoded"},
            data=form,
        )
        parsed = _parse_json(raw)
        if not parsed.get("ok"):
            raise SinkError(parsed.get("error") or f"Slack getUploadURLExternal failed (HTTP {status})")
        upload_url = parsed.get("upload_url")
        file_id = parsed.get("file_id")
        if not upload_url or not file_id:
            raise SinkError("Slack did not return an upload URL / file id")

        # Step 2: upload the raw bytes to the reserved URL.
        up_status, _up_body = _http.http_request(
            "POST", upload_url,
            headers={"Content-Type": "application/octet-stream"},
            data=content,
        )
        if up_status != 200:
            raise SinkError(f"Slack file upload failed (HTTP {up_status})")

        # Step 3: finalize the upload into the channel.
        status, parsed = _http.request_json(
            "POST",
            "https://slack.com/api/files.completeUploadExternal",
            headers=auth,
            payload={
                "files": [{"id": file_id, "title": doc.title}],
                "channel_id": channel,
                "initial_comment": f"Parsed: {doc.title}",
            },
        )
        if not parsed.get("ok"):
            raise SinkError(parsed.get("error") or f"Slack completeUploadExternal failed (HTTP {status})")

        files = parsed.get("files") or [{}]
        url = files[0].get("permalink")
        return SinkResult(
            sink=self.name, ok=True, url=url,
            detail="uploaded .md file (images not embedded)",
        )


def _parse_json(raw):
    import json
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
