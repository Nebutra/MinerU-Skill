"""DingTalk (钉钉) sink — push parsed Markdown as a robot markdown message.

A DingTalk custom robot accepts a ``markdown`` message type. The official native
ingestion path is therefore a webhook POST carrying the document title and body.
When a signing secret is configured the request is HMAC-SHA256 signed per
DingTalk's spec. DingTalk's markdown renderer only fetches images over public
URLs, so local images won't render.

Docs: https://open.dingtalk.com/document/robots/custom-robot-access.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse

from . import _http
from .base import ParsedDoc, Sink, SinkError, SinkResult, register


@register
class DingTalkSink(Sink):
    name = "dingtalk"
    aliases = ("钉钉",)
    requires = ("DINGTALK_WEBHOOK",)
    label = "DingTalk robot markdown (钉钉)"

    def _build_url(self) -> str:
        webhook = self.env("DINGTALK_WEBHOOK")
        if webhook.startswith("http"):
            url = webhook
        else:
            url = f"https://oapi.dingtalk.com/robot/send?access_token={webhook}"

        secret = self.env("DINGTALK_SECRET")
        if secret:
            timestamp = str(round(time.time() * 1000))
            string_to_sign = f"{timestamp}\n{secret}"
            hmac_code = hmac.new(
                secret.encode(), string_to_sign.encode(), hashlib.sha256
            ).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            url += f"&timestamp={timestamp}&sign={sign}"
        return url

    def deliver(self, doc: ParsedDoc) -> SinkResult:
        url = self._build_url()
        payload = {
            "msgtype": "markdown",
            "markdown": {"title": doc.title, "text": doc.markdown},
        }
        status, parsed = _http.request_json("POST", url, payload=payload)

        if parsed.get("errcode") not in (0, None):
            raise SinkError(parsed.get("errmsg") or f"DingTalk HTTP {status}: {parsed}")

        return SinkResult(
            sink=self.name,
            ok=True,
            url=None,
            detail="robot markdown message (local images won't render; host publicly)",
        )
