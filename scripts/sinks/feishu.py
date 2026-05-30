"""Feishu / Lark sink: import the parsed Markdown as a Docx document.

Feishu (飞书) / Lark ingests Markdown through its Drive import pipeline. Delivery
follows that official path:

1. ``tenant_access_token/internal`` — exchange the app id/secret for a tenant
   access token.
2. ``drive/v1/medias/upload_all`` — upload the ``.md`` bytes as an import medium
   and obtain a ``file_token``.
3. ``drive/v1/import_tasks`` — kick off an import task converting the medium to a
   Docx, returning a ``ticket``.
4. Poll ``drive/v1/import_tasks/{ticket}`` until the job finishes, surfacing the
   resulting document URL.

Local images are not uploaded — they would need public URLs to render in Docx.
"""

from __future__ import annotations

import json
import time

from . import _http, _md
from .base import ParsedDoc, Sink, SinkError, SinkResult, register


@register
class FeishuSink(Sink):
    name = "feishu"
    aliases = ("lark", "飞书")
    requires = ("FEISHU_APP_ID", "FEISHU_APP_SECRET")
    label = "Feishu / Lark Docx (Drive import)"

    def deliver(self, doc: ParsedDoc) -> SinkResult:
        app_id = self.env("FEISHU_APP_ID")
        app_secret = self.env("FEISHU_APP_SECRET")
        folder_token = self.env("FEISHU_FOLDER_TOKEN")

        # Step 1: tenant access token.
        status, parsed = _http.request_json(
            "POST",
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            payload={"app_id": app_id, "app_secret": app_secret},
        )
        token = parsed.get("tenant_access_token")
        if parsed.get("code") not in (0, None) or not token:
            raise SinkError(parsed.get("msg") or f"Feishu auth failed (HTTP {status})")
        headers = {"Authorization": f"Bearer {token}"}

        # Step 2: upload the Markdown bytes as an import medium.
        content = doc.markdown.encode("utf-8")
        fname = _md.safe_filename(doc.title) + ".md"
        ctype, body = _http.encode_multipart(
            fields={
                "file_name": fname,
                "parent_type": "ccm_import_open",
                "size": str(len(content)),
                "extra": json.dumps({"obj_type": "docx", "file_extension": "md"}),
            },
            files=[("file", fname, content)],
        )
        up_status, raw = _http.http_request(
            "POST",
            "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all",
            headers={**headers, "Content-Type": ctype},
            data=body,
        )
        parsed = _parse_json(raw)
        if parsed.get("code") not in (0, None):
            raise SinkError(parsed.get("msg") or f"Feishu media upload failed (HTTP {up_status})")
        file_token = (parsed.get("data") or {}).get("file_token")
        if not file_token:
            raise SinkError("Feishu did not return a file_token")

        # Step 3: create the import task.
        status, parsed = _http.request_json(
            "POST",
            "https://open.feishu.cn/open-apis/drive/v1/import_tasks",
            headers=headers,
            payload={
                "file_extension": "md",
                "file_token": file_token,
                "type": "docx",
                "file_name": doc.title,
                "point": {"mount_type": 1, "mount_key": folder_token or ""},
            },
        )
        if parsed.get("code") not in (0, None):
            raise SinkError(parsed.get("msg") or f"Feishu import task failed (HTTP {status})")
        ticket = (parsed.get("data") or {}).get("ticket")
        if not ticket:
            raise SinkError("Feishu did not return an import ticket")

        # Step 4: poll until the import job completes.
        url = None
        for _attempt in range(20):
            status, parsed = _http.request_json(
                "GET",
                f"https://open.feishu.cn/open-apis/drive/v1/import_tasks/{ticket}",
                headers=headers,
            )
            res = (parsed.get("data") or {}).get("result") or {}
            job_status = res.get("job_status")
            if job_status == 0:
                url = res.get("url")
                break
            if job_status in (1, 2):
                time.sleep(1)
                continue
            raise SinkError(res.get("job_error_msg") or "Feishu import failed")

        return SinkResult(
            sink=self.name, ok=True, url=url,
            detail="imported to Feishu Docx (local images need public URLs)",
        )


def _parse_json(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
