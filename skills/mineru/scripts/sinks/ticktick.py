"""TickTick (滴答清单) sink — create a task from parsed Markdown.

TickTick's Open API exposes a task object whose ``content`` field holds the body
text. The official native ingestion path for arbitrary Markdown is therefore a
task: the document title becomes the task title and the Markdown becomes the
task content. Tasks have no attachment/inline-image surface, so local images are
not delivered.

Docs: https://developer.ticktick.com/docs (POST /open/v1/task).
"""

from __future__ import annotations

from . import _http
from .base import ParsedDoc, Sink, SinkError, SinkResult, register

API_URL = "https://api.ticktick.com/open/v1/task"


@register
class TickTickSink(Sink):
    name = "ticktick"
    aliases = ("dida", "滴答清单")
    requires = ("TICKTICK_TOKEN",)
    label = "TickTick task (滴答清单)"

    def deliver(self, doc: ParsedDoc) -> SinkResult:
        token = self.env("TICKTICK_TOKEN")
        project_id = self.env("TICKTICK_PROJECT_ID")

        payload = {"title": doc.title, "content": doc.markdown}
        if project_id:
            payload["projectId"] = project_id

        headers = {"Authorization": f"Bearer {token}"}
        status, parsed = _http.request_json("POST", API_URL, headers=headers, payload=payload)

        if status >= 400:
            raise SinkError(f"TickTick HTTP {status}: {parsed}")
        if not parsed.get("id"):
            raise SinkError(f"TickTick returned no task id: {parsed}")

        return SinkResult(
            sink=self.name,
            ok=True,
            url=None,
            detail="task content (no inline images supported by TickTick)",
        )
