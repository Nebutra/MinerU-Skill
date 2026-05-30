"""WeCom (企业微信 / WeChat Work) sink — send parsed Markdown as an app message.

WeCom apps deliver content via the message-send API. The native ingestion path
is a ``markdown`` message from a self-built app: first an access token is fetched
with the corp id + secret, then the message is posted. WeCom's markdown is a
limited subset with a 2048-byte content cap and no inline images, so the body is
truncated to fit.

Docs: https://developer.work.weixin.qq.com/document/path/90236 (message/send),
https://developer.work.weixin.qq.com/document/path/91039 (gettoken).
"""

from __future__ import annotations

from . import _http
from .base import ParsedDoc, Sink, SinkError, SinkResult, register

TOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
SEND_URL = "https://qyapi.weixin.qq.com/cgi-bin/message/send"


@register
class WeComSink(Sink):
    name = "wecom"
    aliases = ("企业微信", "wechatwork")
    requires = ("WECOM_CORPID", "WECOM_CORPSECRET", "WECOM_AGENTID")
    label = "WeCom app markdown (企业微信)"

    def deliver(self, doc: ParsedDoc) -> SinkResult:
        corpid = self.env("WECOM_CORPID")
        secret = self.env("WECOM_CORPSECRET")
        agentid = self.env("WECOM_AGENTID")
        touser = self.env("WECOM_TOUSER", "@all")

        # Step 1: fetch an access token.
        token_url = f"{TOKEN_URL}?corpid={corpid}&corpsecret={secret}"
        status, parsed = _http.request_json("GET", token_url)
        if parsed.get("errcode") not in (0, None) or not parsed.get("access_token"):
            raise SinkError(parsed.get("errmsg") or f"WeCom token fetch failed: {parsed}")
        token = parsed["access_token"]

        # Step 2: send the markdown message.
        send_url = f"{SEND_URL}?access_token={token}"
        payload = {
            "touser": touser,
            "msgtype": "markdown",
            "agentid": int(agentid),
            "markdown": {"content": doc.markdown[:2048]},
        }
        status, parsed = _http.request_json("POST", send_url, payload=payload)
        if parsed.get("errcode") not in (0, None):
            raise SinkError(parsed.get("errmsg") or f"WeCom send failed: {parsed}")

        return SinkResult(
            sink=self.name,
            ok=True,
            url=None,
            detail="markdown notification (WeCom markdown is a limited subset, "
                   "2048-byte cap, no inline images)",
        )
