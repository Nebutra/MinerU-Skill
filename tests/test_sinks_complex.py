"""Mocked-integration tests for the complex multi-step sinks.

Covers Slack, Feishu/Lark, Confluence and OneNote. Every one of these sinks
drives a multi-step HTTP sequence (Slack: reserve -> upload -> complete; Feishu:
token -> media upload -> import task -> poll), so the fake router below mirrors
``sinks._http.http_request`` exactly, routes by URL substring, supports sequenced
responses, and records every call for assertions.

Run offline:
    python3 -m pytest tests/test_sinks_complex.py -o addopts="" -q
"""

import json
import urllib.parse

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

    Replaces ``sinks._http.http_request`` so it mirrors that signature and
    returns ``(status, body_bytes)``. ``request_json`` decodes the body itself,
    so JSON steps and raw byte steps (Slack octet upload, OneNote, Feishu media
    multipart) all funnel through the same seam.
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

    def body_form(self, method, substring):
        for m, url, _headers, data in self.calls:
            if m == method and substring in url and data:
                return dict(urllib.parse.parse_qsl(data.decode("utf-8")))
        raise AssertionError(f"No form body captured for {method} {substring}")

    def header_for(self, method, substring):
        for m, url, headers, _data in self.calls:
            if m == method and substring in url:
                return headers or {}
        raise AssertionError(f"No call captured for {method} {substring}")

    def order(self):
        return [(m, u) for m, u, _h, _d in self.calls]


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
    ("slack", "slack"),
    ("feishu", "feishu"),
    ("lark", "feishu"),
    ("飞书", "feishu"),
    ("confluence", "confluence"),
    ("onenote", "onenote"),
    ("msonenote", "onenote"),
])
def test_sinks_registered_with_aliases(name, canonical):
    sink = get_sink(name)
    assert sink is not None, f"{name} did not register"
    assert sink.name == canonical


# --------------------------------------------------------------------------- #
# Slack — files.getUploadURLExternal -> upload -> files.completeUploadExternal
# --------------------------------------------------------------------------- #
def _slack_env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-123")
    monkeypatch.setenv("SLACK_CHANNEL", "C0001")


def test_slack_external_upload_three_step_success(router, monkeypatch):
    _slack_env(monkeypatch)
    router.add("files.getUploadURLExternal", [(200, _json_bytes({
        "ok": True, "upload_url": "https://files.slack.com/upload/u1", "file_id": "F1",
    }))], method="POST")
    router.add("files.slack.com/upload/u1", [(200, b"OK")], method="POST")
    router.add("files.completeUploadExternal", [(200, _json_bytes({
        "ok": True, "files": [{"id": "F1", "permalink": "https://slack.com/files/F1"}],
    }))], method="POST")

    res = get_sink("slack").deliver(_doc())
    assert res.ok is True
    assert res.url == "https://slack.com/files/F1"
    assert "images not embedded" in res.detail

    # Step order: reserve -> octet upload -> complete.
    order = router.order()
    reserve = next(i for i, (m, u) in enumerate(order) if "getUploadURLExternal" in u)
    upload = next(i for i, (m, u) in enumerate(order) if "upload/u1" in u)
    complete = next(i for i, (m, u) in enumerate(order) if "completeUploadExternal" in u)
    assert reserve < upload < complete

    # Step 1: form-encoded filename + byte length, bearer auth.
    form = router.body_form("POST", "getUploadURLExternal")
    content = _doc().markdown.encode("utf-8")
    assert form["filename"] == "my-parsed-doc.md"
    assert form["length"] == str(len(content))
    h1 = router.header_for("POST", "getUploadURLExternal")
    assert h1["Authorization"] == "Bearer xoxb-123"
    assert h1["Content-Type"] == "application/x-www-form-urlencoded"

    # Step 2: raw bytes posted to the reserved URL as octet-stream.
    [(_m, _u, h2, body2)] = router.find("POST", "upload/u1")
    assert h2["Content-Type"] == "application/octet-stream"
    assert body2 == content

    # Step 3: completeUploadExternal carries file id, channel, comment.
    payload = router.body_json("POST", "completeUploadExternal")
    assert payload["files"] == [{"id": "F1", "title": "My Parsed Doc"}]
    assert payload["channel_id"] == "C0001"
    assert payload["initial_comment"] == "Parsed: My Parsed Doc"
    assert router.header_for("POST", "completeUploadExternal")["Authorization"] == "Bearer xoxb-123"


def test_slack_reserve_error_surfaces_via_deliver_all(router, monkeypatch):
    _slack_env(monkeypatch)
    router.add("files.getUploadURLExternal", [(200, _json_bytes({
        "ok": False, "error": "invalid_auth",
    }))])

    [res] = deliver_all(_doc(), ["slack"])
    assert res.ok is False
    assert res.error == "invalid_auth"


# --------------------------------------------------------------------------- #
# Feishu — token -> media upload -> import task -> poll
# --------------------------------------------------------------------------- #
def _feishu_env(monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "cli_app")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.delenv("FEISHU_FOLDER_TOKEN", raising=False)


def test_feishu_import_pipeline_success(router, monkeypatch):
    _feishu_env(monkeypatch)
    monkeypatch.setenv("FEISHU_FOLDER_TOKEN", "fldXYZ")
    router.add("tenant_access_token/internal", [(200, _json_bytes({
        "code": 0, "tenant_access_token": "t-tenant", "expire": 7200,
    }))], method="POST")
    router.add("drive/v1/medias/upload_all", [(200, _json_bytes({
        "code": 0, "data": {"file_token": "med-1"},
    }))], method="POST")
    router.add("drive/v1/import_tasks", [(200, _json_bytes({
        "code": 0, "data": {"ticket": "tick-1"},
    }))], method="POST")
    # Poll: first in-progress (2), then done (0) with a URL.
    router.add("drive/v1/import_tasks/tick-1", [
        (200, _json_bytes({"code": 0, "data": {"result": {"job_status": 2}}})),
        (200, _json_bytes({"code": 0, "data": {"result": {
            "job_status": 0, "url": "https://feishu.cn/docx/D1", "token": "D1",
        }}})),
    ], method="GET")

    # Avoid the 1s sleep on the in-progress poll.
    monkeypatch.setattr(sinks.feishu.time, "sleep", lambda *_a, **_k: None)

    res = get_sink("feishu").deliver(_doc())
    assert res.ok is True
    assert res.url == "https://feishu.cn/docx/D1"
    assert "Feishu Docx" in res.detail

    # Step order across the four phases.
    order = router.order()
    tok = next(i for i, (m, u) in enumerate(order) if "tenant_access_token" in u)
    media = next(i for i, (m, u) in enumerate(order) if "medias/upload_all" in u)
    imp = next(i for i, (m, u) in enumerate(order) if u.endswith("import_tasks"))
    poll = next(i for i, (m, u) in enumerate(order) if "import_tasks/tick-1" in u)
    assert tok < media < imp < poll

    # Step 1: token request carries app id/secret.
    body_tok = router.body_json("POST", "tenant_access_token")
    assert body_tok == {"app_id": "cli_app", "app_secret": "secret"}

    # Step 2: media upload is multipart with bearer auth and the .md filename.
    h_media = router.header_for("POST", "medias/upload_all")
    assert h_media["Authorization"] == "Bearer t-tenant"
    assert h_media["Content-Type"].startswith("multipart/form-data; boundary=")
    [(_m, _u, _h, media_body)] = router.find("POST", "medias/upload_all")
    assert b'name="parent_type"' in media_body
    assert b"ccm_import_open" in media_body
    assert b'filename="My Parsed Doc.md"' in media_body
    assert _doc().markdown.encode("utf-8") in media_body

    # Step 3: import task references the file token and folder mount key.
    body_imp = router.body_json("POST", "drive/v1/import_tasks")
    assert body_imp["file_extension"] == "md"
    assert body_imp["file_token"] == "med-1"
    assert body_imp["type"] == "docx"
    assert body_imp["file_name"] == "My Parsed Doc"
    assert body_imp["point"] == {"mount_type": 1, "mount_key": "fldXYZ"}

    # Step 4: poll happened twice (in-progress then done).
    assert len(router.find("GET", "import_tasks/tick-1")) == 2


def test_feishu_token_failure_surfaces_via_deliver_all(router, monkeypatch):
    _feishu_env(monkeypatch)
    router.add("tenant_access_token/internal", [(200, _json_bytes({
        "code": 10003, "msg": "app not found",
    }))])

    [res] = deliver_all(_doc(), ["feishu"])
    assert res.ok is False
    assert res.error == "app not found"


def test_feishu_import_job_error_surfaces(router, monkeypatch):
    _feishu_env(monkeypatch)
    router.add("tenant_access_token/internal", [(200, _json_bytes({
        "code": 0, "tenant_access_token": "t-tenant",
    }))], method="POST")
    router.add("drive/v1/medias/upload_all", [(200, _json_bytes({
        "code": 0, "data": {"file_token": "med-1"},
    }))], method="POST")
    router.add("drive/v1/import_tasks", [(200, _json_bytes({
        "code": 0, "data": {"ticket": "tick-2"},
    }))], method="POST")
    # job_status 3 (unknown/error) with a message; GET disambiguates from the POST.
    router.add("drive/v1/import_tasks/tick-2", [(200, _json_bytes({
        "code": 0, "data": {"result": {"job_status": 3, "job_error_msg": "conversion failed"}},
    }))], method="GET")

    with pytest.raises(sinks.SinkError) as exc:
        get_sink("feishu").deliver(_doc())
    assert "conversion failed" in str(exc.value)


# --------------------------------------------------------------------------- #
# Confluence — POST /wiki/api/v2/pages with storage HTML + Basic auth
# --------------------------------------------------------------------------- #
def _confluence_env(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://acme.atlassian.net/")
    monkeypatch.setenv("CONFLUENCE_EMAIL", "me@acme.com")
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "tok-99")
    monkeypatch.setenv("CONFLUENCE_SPACE_ID", "12345")


def test_confluence_create_page_success(router, monkeypatch):
    import base64

    _confluence_env(monkeypatch)
    router.add("/wiki/api/v2/pages", [(200, _json_bytes({
        "id": "page-1",
        "_links": {"webui": "/spaces/DOC/pages/page-1"},
    }))], method="POST")

    res = get_sink("confluence").deliver(_doc())
    assert res.ok is True
    # base (with trailing slash stripped) + webui path.
    assert res.url == "https://acme.atlassian.net/spaces/DOC/pages/page-1"
    assert "storage HTML" in res.detail

    # Endpoint resolved against the rstripped base.
    [(_m, url, _h, _d)] = router.find("POST", "/wiki/api/v2/pages")
    assert url == "https://acme.atlassian.net/wiki/api/v2/pages"

    # Basic auth header is base64(email:token).
    expected = base64.b64encode(b"me@acme.com:tok-99").decode("ascii")
    headers = router.header_for("POST", "/wiki/api/v2/pages")
    assert headers["Authorization"] == f"Basic {expected}"
    assert headers["Content-Type"] == "application/json"

    # Storage-format body with converted HTML.
    body = router.body_json("POST", "/wiki/api/v2/pages")
    assert body["spaceId"] == "12345"
    assert body["status"] == "current"
    assert body["title"] == "My Parsed Doc"
    assert body["body"]["representation"] == "storage"
    assert "<h1>My Parsed Doc</h1>" in body["body"]["value"]


def test_confluence_no_webui_link_yields_none_url(router, monkeypatch):
    _confluence_env(monkeypatch)
    router.add("/wiki/api/v2/pages", [(200, _json_bytes({"id": "page-2"}))])

    res = get_sink("confluence").deliver(_doc())
    assert res.ok is True
    assert res.url is None


def test_confluence_error_surfaces_via_deliver_all(router, monkeypatch):
    _confluence_env(monkeypatch)
    router.add("/wiki/api/v2/pages", [(400, _json_bytes({
        "title": "title already exists",
    }))])

    [res] = deliver_all(_doc(), ["confluence"])
    assert res.ok is False
    assert res.error == "title already exists"


# --------------------------------------------------------------------------- #
# OneNote — POST HTML to a section's pages endpoint (Microsoft Graph)
# --------------------------------------------------------------------------- #
def _onenote_env(monkeypatch):
    monkeypatch.setenv("ONENOTE_TOKEN", "graph-tok")
    monkeypatch.setenv("ONENOTE_SECTION_ID", "sec-99")


def test_onenote_create_page_success(router, monkeypatch):
    _onenote_env(monkeypatch)
    router.add("onenote/sections/sec-99/pages", [(201, _json_bytes({
        "id": "page-1",
        "links": {"oneNoteWebUrl": {"href": "https://onenote.com/p/1"}},
    }))], method="POST")

    res = get_sink("onenote").deliver(_doc())
    assert res.ok is True
    assert res.url == "https://onenote.com/p/1"
    assert "remote images only" in res.detail

    # Endpoint embeds the section id.
    [(_m, url, _h, _d)] = router.find("POST", "sections/sec-99/pages")
    assert url == "https://graph.microsoft.com/v1.0/me/onenote/sections/sec-99/pages"

    # Bearer auth + text/html content type.
    headers = router.header_for("POST", "sections/sec-99/pages")
    assert headers["Authorization"] == "Bearer graph-tok"
    assert headers["Content-Type"] == "text/html"

    # Body is a full HTML document with an escaped <title> and converted body.
    [(_m, _u, _h, data)] = router.find("POST", "sections/sec-99/pages")
    html_doc = data.decode("utf-8")
    assert html_doc.startswith("<!DOCTYPE html><html><head>")
    assert "<title>My Parsed Doc</title>" in html_doc
    assert "<h1>My Parsed Doc</h1>" in html_doc


def test_onenote_escapes_title_in_html(router, monkeypatch):
    _onenote_env(monkeypatch)
    router.add("onenote/sections/sec-99/pages", [(201, _json_bytes({"id": "p"}))])

    doc = ParsedDoc(title="A & B <x>", markdown="# heading\n")
    res = get_sink("onenote").deliver(doc)
    assert res.ok is True
    assert res.url is None  # no oneNoteWebUrl link present

    [(_m, _u, _h, data)] = router.find("POST", "sections/sec-99/pages")
    html_doc = data.decode("utf-8")
    assert "<title>A &amp; B &lt;x&gt;</title>" in html_doc


def test_onenote_http_error_surfaces_via_deliver_all(router, monkeypatch):
    _onenote_env(monkeypatch)
    router.add("onenote/sections/sec-99/pages", [(401, b'{"error":"InvalidAuthenticationToken"}')])

    [res] = deliver_all(_doc(), ["onenote"])
    assert res.ok is False
    assert res.error.startswith("OneNote HTTP 401:")
    assert "InvalidAuthenticationToken" in res.error
