"""Mocked-integration tests for the enterprise/task sinks.

Covers TickTick, DingTalk, Airtable and WeCom. All HTTP is exercised through the
single ``sinks._http.http_request`` seam, replaced per test by a tiny in-memory
URL router so no network access is required. Both ``request_json`` and any raw
``http_request`` callers funnel through it.

Run offline:
    python3 -m pytest tests/test_sinks_enterprise.py -o addopts="" -q
"""

import json

import pytest

import sinks
from sinks import deliver_all, get_sink
from sinks.base import ParsedDoc


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
def _json_bytes(obj):
    return json.dumps(obj).encode("utf-8")


class Router:
    """Route fake HTTP calls by URL substring; record every call for assertions.

    Replaces ``sinks._http.http_request`` so it must mirror that signature and
    return ``(status, body_bytes)``. ``request_json`` decodes the body itself.
    """

    def __init__(self):
        self._routes = []  # [method_or_None, substring, [(status, bytes)], idx]
        self.calls = []

    def add(self, substring, responses, method=None):
        self._routes.append([method, substring, list(responses), 0])
        return self

    def __call__(self, method, url, *, headers=None, data=None, timeout=60):
        self.calls.append((method, url, headers, data))
        for route in self._routes:
            want_method, substring, responses, idx = route
            if want_method and want_method != method:
                continue
            if substring in url:
                pick = min(idx, len(responses) - 1)
                route[3] = idx + 1
                return responses[pick]
        raise AssertionError(f"No fake route for {method} {url}")

    # Convenience accessors -------------------------------------------------- #
    def find(self, method, substring):
        return [c for c in self.calls if c[0] == method and substring in c[1]]

    def body_json(self, method, substring):
        for m, url, _headers, data in self.calls:
            if m == method and substring in url and data:
                return json.loads(data.decode("utf-8"))
        raise AssertionError(f"No body captured for {method} {substring}")

    def header_for(self, method, substring):
        for m, url, headers, _data in self.calls:
            if m == method and substring in url:
                return headers or {}
        raise AssertionError(f"No call captured for {method} {substring}")


@pytest.fixture
def router(monkeypatch):
    r = Router()
    monkeypatch.setattr(sinks._http, "http_request", r)
    return r


def _doc():
    return ParsedDoc(
        title="My Parsed Doc",
        markdown="# My Parsed Doc\n\nBody text with ![fig](img.png).\n",
        images=(),
        source="/tmp/my.pdf",
        modality="pdf",
        markdown_path="/tmp/out/my.md",
    )


# --------------------------------------------------------------------------- #
# Registration sanity
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name,canonical", [
    ("ticktick", "ticktick"),
    ("dida", "ticktick"),
    ("滴答清单", "ticktick"),
    ("dingtalk", "dingtalk"),
    ("钉钉", "dingtalk"),
    ("airtable", "airtable"),
    ("wecom", "wecom"),
    ("企业微信", "wecom"),
    ("wechatwork", "wecom"),
])
def test_sinks_registered_with_aliases(name, canonical):
    sink = get_sink(name)
    assert sink is not None, f"{name} did not register"
    assert sink.name == canonical


# --------------------------------------------------------------------------- #
# TickTick
# --------------------------------------------------------------------------- #
def test_ticktick_success_posts_task(router, monkeypatch):
    monkeypatch.setenv("TICKTICK_TOKEN", "tok-123")
    monkeypatch.setenv("TICKTICK_PROJECT_ID", "proj-9")
    router.add("api.ticktick.com/open/v1/task", [(200, _json_bytes({"id": "task-1"}))], method="POST")

    res = get_sink("ticktick").deliver(_doc())
    assert res.ok is True
    assert res.url is None
    assert "no inline images" in res.detail

    body = router.body_json("POST", "/open/v1/task")
    assert body["title"] == "My Parsed Doc"
    assert body["content"].startswith("# My Parsed Doc")
    assert body["projectId"] == "proj-9"
    assert router.header_for("POST", "/open/v1/task")["Authorization"] == "Bearer tok-123"


def test_ticktick_omits_project_id_when_unset(router, monkeypatch):
    monkeypatch.setenv("TICKTICK_TOKEN", "tok-123")
    monkeypatch.delenv("TICKTICK_PROJECT_ID", raising=False)
    router.add("/open/v1/task", [(200, _json_bytes({"id": "task-2"}))])

    get_sink("ticktick").deliver(_doc())
    assert "projectId" not in router.body_json("POST", "/open/v1/task")


def test_ticktick_http_error_surfaces_via_deliver_all(router, monkeypatch):
    monkeypatch.setenv("TICKTICK_TOKEN", "tok-123")
    router.add("/open/v1/task", [(401, _json_bytes({"errorMessage": "unauthorized"}))])

    [res] = deliver_all(_doc(), ["ticktick"])
    assert res.ok is False
    assert "TickTick HTTP 401" in res.error


# --------------------------------------------------------------------------- #
# DingTalk
# --------------------------------------------------------------------------- #
def test_dingtalk_success_full_webhook_url(router, monkeypatch):
    monkeypatch.setenv("DINGTALK_WEBHOOK", "https://oapi.dingtalk.com/robot/send?access_token=abc")
    monkeypatch.delenv("DINGTALK_SECRET", raising=False)
    router.add("oapi.dingtalk.com/robot/send", [(200, _json_bytes({"errcode": 0, "errmsg": "ok"}))])

    res = get_sink("dingtalk").deliver(_doc())
    assert res.ok is True
    assert res.url is None

    body = router.body_json("POST", "/robot/send")
    assert body["msgtype"] == "markdown"
    assert body["markdown"]["title"] == "My Parsed Doc"
    assert body["markdown"]["text"].startswith("# My Parsed Doc")

    # No secret -> no signature appended.
    [(_m, url, _h, _d)] = router.find("POST", "/robot/send")
    assert "&sign=" not in url and "&timestamp=" not in url


def test_dingtalk_bare_token_builds_url(router, monkeypatch):
    monkeypatch.setenv("DINGTALK_WEBHOOK", "rawtoken123")
    monkeypatch.delenv("DINGTALK_SECRET", raising=False)
    router.add("oapi.dingtalk.com/robot/send", [(200, _json_bytes({"errcode": 0, "errmsg": "ok"}))])

    get_sink("dingtalk").deliver(_doc())
    [(_m, url, _h, _d)] = router.find("POST", "/robot/send")
    assert url == "https://oapi.dingtalk.com/robot/send?access_token=rawtoken123"


def test_dingtalk_secret_appends_timestamp_and_sign(router, monkeypatch):
    monkeypatch.setenv("DINGTALK_WEBHOOK", "https://oapi.dingtalk.com/robot/send?access_token=abc")
    monkeypatch.setenv("DINGTALK_SECRET", "SEC123")
    router.add("oapi.dingtalk.com/robot/send", [(200, _json_bytes({"errcode": 0, "errmsg": "ok"}))])

    get_sink("dingtalk").deliver(_doc())
    [(_m, url, _h, _d)] = router.find("POST", "/robot/send")
    assert "&timestamp=" in url
    assert "&sign=" in url


def test_dingtalk_errcode_failure_surfaces(router, monkeypatch):
    monkeypatch.setenv("DINGTALK_WEBHOOK", "https://oapi.dingtalk.com/robot/send?access_token=abc")
    monkeypatch.delenv("DINGTALK_SECRET", raising=False)
    router.add("/robot/send", [(200, _json_bytes({"errcode": 310000, "errmsg": "keywords not in content"}))])

    [res] = deliver_all(_doc(), ["dingtalk"])
    assert res.ok is False
    assert res.error == "keywords not in content"


# --------------------------------------------------------------------------- #
# Airtable
# --------------------------------------------------------------------------- #
def test_airtable_success_creates_record(router, monkeypatch):
    monkeypatch.setenv("AIRTABLE_API_KEY", "key-abc")
    monkeypatch.setenv("AIRTABLE_BASE_ID", "appBASE")
    monkeypatch.setenv("AIRTABLE_TABLE", "My Table")
    monkeypatch.delenv("AIRTABLE_TITLE_FIELD", raising=False)
    monkeypatch.delenv("AIRTABLE_BODY_FIELD", raising=False)
    router.add("api.airtable.com/v0/appBASE", [(200, _json_bytes({"id": "rec-1"}))], method="POST")

    res = get_sink("airtable").deliver(_doc())
    assert res.ok is True
    assert res.url is None
    assert "database record" in res.detail

    # Table name URL-encoded into the endpoint.
    [(_m, url, _h, _d)] = router.find("POST", "/v0/appBASE")
    assert url == "https://api.airtable.com/v0/appBASE/My%20Table"

    body = router.body_json("POST", "/v0/appBASE")
    assert body["fields"]["Title"] == "My Parsed Doc"
    assert body["fields"]["Notes"].startswith("# My Parsed Doc")
    assert router.header_for("POST", "/v0/appBASE")["Authorization"] == "Bearer key-abc"


def test_airtable_custom_field_names(router, monkeypatch):
    monkeypatch.setenv("AIRTABLE_API_KEY", "key-abc")
    monkeypatch.setenv("AIRTABLE_BASE_ID", "appBASE")
    monkeypatch.setenv("AIRTABLE_TABLE", "Docs")
    monkeypatch.setenv("AIRTABLE_TITLE_FIELD", "Name")
    monkeypatch.setenv("AIRTABLE_BODY_FIELD", "Body")
    router.add("/v0/appBASE", [(200, _json_bytes({"id": "rec-2"}))])

    get_sink("airtable").deliver(_doc())
    fields = router.body_json("POST", "/v0/appBASE")["fields"]
    assert "Name" in fields and "Body" in fields


def test_airtable_error_surfaces(router, monkeypatch):
    monkeypatch.setenv("AIRTABLE_API_KEY", "key-abc")
    monkeypatch.setenv("AIRTABLE_BASE_ID", "appBASE")
    monkeypatch.setenv("AIRTABLE_TABLE", "Docs")
    router.add("/v0/appBASE", [(422, _json_bytes({"error": {"type": "UNKNOWN_FIELD_NAME"}}))])

    [res] = deliver_all(_doc(), ["airtable"])
    assert res.ok is False
    assert "UNKNOWN_FIELD_NAME" in res.error


# --------------------------------------------------------------------------- #
# WeCom
# --------------------------------------------------------------------------- #
def test_wecom_success_token_then_send(router, monkeypatch):
    monkeypatch.setenv("WECOM_CORPID", "corp1")
    monkeypatch.setenv("WECOM_CORPSECRET", "sec1")
    monkeypatch.setenv("WECOM_AGENTID", "1000002")
    monkeypatch.delenv("WECOM_TOUSER", raising=False)
    router.add("/cgi-bin/gettoken", [(200, _json_bytes({"errcode": 0, "access_token": "AT-xyz"}))], method="GET")
    router.add("/cgi-bin/message/send", [(200, _json_bytes({"errcode": 0, "errmsg": "ok"}))], method="POST")

    res = get_sink("wecom").deliver(_doc())
    assert res.ok is True
    assert res.url is None
    assert "2048-byte cap" in res.detail

    # Token GET happens before the message POST.
    methods_urls = [(m, u) for m, u, _h, _d in router.calls]
    get_idx = next(i for i, (m, u) in enumerate(methods_urls) if m == "GET" and "gettoken" in u)
    post_idx = next(i for i, (m, u) in enumerate(methods_urls) if m == "POST" and "message/send" in u)
    assert get_idx < post_idx

    # gettoken carries corpid + corpsecret.
    [(_m, token_url, _h, _d)] = router.find("GET", "gettoken")
    assert "corpid=corp1" in token_url and "corpsecret=sec1" in token_url

    # send uses the returned token and a well-formed payload.
    [(_m, send_url, _h, _d)] = router.find("POST", "message/send")
    assert "access_token=AT-xyz" in send_url
    body = router.body_json("POST", "message/send")
    assert body["touser"] == "@all"
    assert body["msgtype"] == "markdown"
    assert body["agentid"] == 1000002  # coerced to int
    assert body["markdown"]["content"].startswith("# My Parsed Doc")


def test_wecom_caps_content_at_2048_bytes(router, monkeypatch):
    monkeypatch.setenv("WECOM_CORPID", "corp1")
    monkeypatch.setenv("WECOM_CORPSECRET", "sec1")
    monkeypatch.setenv("WECOM_AGENTID", "7")
    router.add("/cgi-bin/gettoken", [(200, _json_bytes({"errcode": 0, "access_token": "AT"}))])
    router.add("/cgi-bin/message/send", [(200, _json_bytes({"errcode": 0}))])

    big = ParsedDoc(title="Big", markdown="x" * 5000)
    get_sink("wecom").deliver(big)
    assert len(router.body_json("POST", "message/send")["markdown"]["content"]) == 2048


def test_wecom_token_failure_surfaces(router, monkeypatch):
    monkeypatch.setenv("WECOM_CORPID", "corp1")
    monkeypatch.setenv("WECOM_CORPSECRET", "bad")
    monkeypatch.setenv("WECOM_AGENTID", "7")
    router.add("/cgi-bin/gettoken", [(200, _json_bytes({"errcode": 40001, "errmsg": "invalid credential"}))])

    [res] = deliver_all(_doc(), ["wecom"])
    assert res.ok is False
    assert res.error == "invalid credential"


def test_wecom_send_failure_surfaces(router, monkeypatch):
    monkeypatch.setenv("WECOM_CORPID", "corp1")
    monkeypatch.setenv("WECOM_CORPSECRET", "sec1")
    monkeypatch.setenv("WECOM_AGENTID", "7")
    router.add("/cgi-bin/gettoken", [(200, _json_bytes({"errcode": 0, "access_token": "AT"}))])
    router.add("/cgi-bin/message/send", [(200, _json_bytes({"errcode": 81013, "errmsg": "user not found"}))])

    with pytest.raises(sinks.SinkError) as exc:
        get_sink("wecom").deliver(_doc())
    assert "user not found" in str(exc.value)
