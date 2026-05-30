"""Mocked-integration tests for the document/knowledge-base sinks.

Each sink's only network seam is ``sinks._http.http_request``; we replace it per
test with a small URL-routing fake that records calls and returns canned
``(status, body_bytes)`` pairs. Tests assert that each sink hits the correct
endpoints with the right headers/payloads and returns ``ok=True``, plus one
failure path per sink that surfaces a :class:`SinkError`.
"""

import base64
import json

import pytest

import sinks
from sinks import get_sink
from sinks.base import ParsedDoc


# --------------------------------------------------------------------------- #
# Fake HTTP transport
# --------------------------------------------------------------------------- #
def _json_bytes(obj):
    return json.dumps(obj).encode("utf-8")


class Router:
    """Route fake HTTP calls by URL substring; capture every call."""

    def __init__(self):
        self._routes = []  # [method_or_None, substring, [(status, bytes)], idx]
        self.calls = []    # [(method, url, headers, data)]

    def add(self, substring, responses, method=None):
        self._routes.append([method, substring, list(responses), 0])
        return self

    def __call__(self, method, url, *, headers=None, data=None, timeout=60):
        self.calls.append((method, url, headers or {}, data))
        for route in self._routes:
            want_method, substring, responses, idx = route
            if want_method and want_method != method:
                continue
            if substring in url:
                pick = min(idx, len(responses) - 1)
                route[3] = idx + 1
                return responses[pick]
        raise AssertionError(f"No fake route for {method} {url}")

    def request(self, substring, method=None):
        for m, url, headers, data in self.calls:
            if substring in url and (method is None or m == method):
                return m, url, headers, data
        raise AssertionError(f"No recorded call matching {method} {substring}")

    def payload(self, substring, method=None):
        _m, _u, _h, data = self.request(substring, method)
        return json.loads(data.decode("utf-8")) if data else {}


@pytest.fixture
def router(monkeypatch):
    r = Router()
    monkeypatch.setattr(sinks._http, "http_request", r)
    return r


def _doc(markdown="# Title\n\nbody\n", title="My Doc", **kw):
    return ParsedDoc(title=title, markdown=markdown, source="s.pdf",
                     modality="pdf", **kw)


def _img_doc(tmp_path):
    """A doc with one real local image referenced relatively."""
    md_dir = tmp_path / "out"
    md_dir.mkdir()
    (md_dir / "fig.png").write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    md_path = md_dir / "doc.md"
    md_path.write_text("# T\n\n![cap](fig.png)\n")
    return ParsedDoc(title="My Doc", markdown="# T\n\n![cap](fig.png)\n",
                     source="s.pdf", modality="pdf", markdown_path=str(md_path))


# --------------------------------------------------------------------------- #
# SiYuan
# --------------------------------------------------------------------------- #
def test_siyuan_success_uploads_image_and_creates_doc(router, tmp_path, monkeypatch):
    monkeypatch.setenv("SIYUAN_TOKEN", "tok")
    monkeypatch.delenv("SIYUAN_NOTEBOOK", raising=False)
    monkeypatch.delenv("SIYUAN_API_URL", raising=False)
    router.add("/api/notebook/lsNotebooks",
               [(200, _json_bytes({"code": 0, "data": {"notebooks": [{"id": "NB1"}]}}))])
    router.add("/api/asset/upload",
               [(200, _json_bytes({"code": 0, "data": {"succMap": {"fig.png": "assets/fig-x.png"}}}))])
    router.add("/api/filetree/createDocWithMd",
               [(200, _json_bytes({"code": 0, "data": "DOC123"}))])

    res = get_sink("siyuan").deliver(_img_doc(tmp_path))
    assert res.ok is True
    assert res.url == "siyuan://blocks/DOC123"
    assert res.detail == "1 image(s)"

    # Default base URL + Token auth header.
    _m, url, headers, _d = router.request("/api/notebook/lsNotebooks")
    assert url.startswith("http://127.0.0.1:6806")
    assert headers["Authorization"] == "Token tok"
    # createDocWithMd uses chosen notebook + safe path, and the rewritten image ref.
    payload = router.payload("/api/filetree/createDocWithMd")
    assert payload["notebook"] == "NB1"
    assert payload["path"] == "/My Doc"
    assert "assets/fig-x.png" in payload["markdown"]


def test_siyuan_uses_env_notebook_and_base(router, tmp_path, monkeypatch):
    monkeypatch.setenv("SIYUAN_TOKEN", "tok")
    monkeypatch.setenv("SIYUAN_NOTEBOOK", "MYNB")
    monkeypatch.setenv("SIYUAN_API_URL", "http://siyuan.local:6806/")
    router.add("/api/filetree/createDocWithMd",
               [(200, _json_bytes({"code": 0, "data": "D2"}))])

    res = get_sink("siyuan").deliver(_doc())
    assert res.ok and res.url == "siyuan://blocks/D2"
    # No notebook listing should have been requested.
    assert all("lsNotebooks" not in u for _m, u, _h, _d in router.calls)
    _m, url, _h, _d = router.request("/api/filetree/createDocWithMd")
    assert url.startswith("http://siyuan.local:6806/api/")
    assert router.payload("/api/filetree/createDocWithMd")["notebook"] == "MYNB"


def test_siyuan_error_code_raises(router, monkeypatch):
    monkeypatch.setenv("SIYUAN_TOKEN", "tok")
    monkeypatch.setenv("SIYUAN_NOTEBOOK", "NB")
    router.add("/api/filetree/createDocWithMd",
               [(200, _json_bytes({"code": -1, "msg": "Auth failed"}))])
    with pytest.raises(sinks.SinkError) as exc:
        get_sink("siyuan").deliver(_doc())
    assert "Auth failed" in str(exc.value)


def test_siyuan_unreachable_raises(router, monkeypatch):
    monkeypatch.setenv("SIYUAN_TOKEN", "tok")
    monkeypatch.setenv("SIYUAN_NOTEBOOK", "NB")
    router.add("/api/filetree/createDocWithMd", [(0, b"")])
    with pytest.raises(sinks.SinkError) as exc:
        get_sink("siyuan").deliver(_doc())
    assert "not reachable" in str(exc.value)


# --------------------------------------------------------------------------- #
# Notion
# --------------------------------------------------------------------------- #
def test_notion_success_creates_page(router, monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "secret")
    monkeypatch.setenv("NOTION_PARENT_PAGE_ID", "PARENT")
    monkeypatch.delenv("NOTION_VERSION", raising=False)
    router.add("/v1/pages",
               [(200, _json_bytes({"object": "page", "id": "PG1",
                                   "url": "https://notion.so/PG1"}))])

    md = "# H1\n## H2\n### H3\n> quote\n- bullet\n1. first\n\npara\n```\ncode\n```\n"
    res = get_sink("notion").deliver(_doc(markdown=md))
    assert res.ok and res.url == "https://notion.so/PG1"
    assert res.detail == "text+structure"

    _m, _u, headers, _d = router.request("/v1/pages")
    assert headers["Authorization"] == "Bearer secret"
    assert headers["Notion-Version"] == "2022-06-28"
    payload = router.payload("/v1/pages")
    assert payload["parent"]["page_id"] == "PARENT"
    types = [b["type"] for b in payload["children"]]
    assert types == ["heading_1", "heading_2", "heading_3", "quote",
                     "bulleted_list_item", "numbered_list_item", "paragraph", "code"]
    code_block = payload["children"][-1]
    assert code_block["code"]["language"] == "plain text"
    assert code_block["code"]["rich_text"][0]["text"]["content"] == "code"


def test_notion_chunks_over_100_blocks(router, monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "secret")
    monkeypatch.setenv("NOTION_PARENT_PAGE_ID", "PARENT")
    router.add("/v1/pages", [(200, _json_bytes({"object": "page", "id": "PG2",
                                                "url": "https://notion.so/PG2"}))])
    router.add("/blocks/PG2/children", [(200, _json_bytes({"object": "list"}))])

    md = "\n".join(f"para {i}" for i in range(250))
    res = get_sink("notion").deliver(_doc(markdown=md))
    assert res.ok
    # Create with 100 + two PATCH chunks (100 + 50).
    create = router.payload("/v1/pages")
    assert len(create["children"]) == 100
    patches = [json.loads(d.decode()) for m, u, h, d in router.calls
               if "/blocks/PG2/children" in u]
    assert [len(p["children"]) for p in patches] == [100, 50]


def test_notion_image_note_in_detail(router, tmp_path, monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "secret")
    monkeypatch.setenv("NOTION_PARENT_PAGE_ID", "PARENT")
    router.add("/v1/pages", [(200, _json_bytes({"object": "page", "id": "PG3",
                                                "url": "https://notion.so/PG3"}))])
    res = get_sink("notion").deliver(_img_doc(tmp_path))
    assert res.ok
    assert "1 local images not embedded" in res.detail


def test_notion_error_raises(router, monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "secret")
    monkeypatch.setenv("NOTION_PARENT_PAGE_ID", "PARENT")
    router.add("/v1/pages",
               [(401, _json_bytes({"object": "error", "status": 401,
                                   "message": "API token is invalid."}))])
    with pytest.raises(sinks.SinkError) as exc:
        get_sink("notion").deliver(_doc())
    assert "API token is invalid." in str(exc.value)


# --------------------------------------------------------------------------- #
# Linear
# --------------------------------------------------------------------------- #
def test_linear_success_inlines_image(router, tmp_path, monkeypatch):
    monkeypatch.setenv("LINEAR_API_KEY", "lin_key")
    monkeypatch.setenv("LINEAR_TEAM_ID", "TEAM")
    router.add("/graphql", [(200, _json_bytes({"data": {"issueCreate": {
        "success": True,
        "issue": {"id": "I1", "url": "https://linear.app/x/issue/ABC-1", "identifier": "ABC-1"},
    }}}))])

    res = get_sink("linear").deliver(_img_doc(tmp_path))
    assert res.ok and res.url == "https://linear.app/x/issue/ABC-1"
    assert res.detail == "1 image(s) inlined"

    _m, url, headers, _d = router.request("/graphql")
    assert url == "https://api.linear.app/graphql"
    # Raw key, NO Bearer prefix.
    assert headers["Authorization"] == "lin_key"
    assert not headers["Authorization"].startswith("Bearer")
    payload = router.payload("/graphql")
    assert payload["variables"]["input"]["teamId"] == "TEAM"
    desc = payload["variables"]["input"]["description"]
    expected_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\nFAKE").decode("ascii")
    assert f"data:image/png;base64,{expected_b64}" in desc


def test_linear_graphql_errors_raise(router, monkeypatch):
    monkeypatch.setenv("LINEAR_API_KEY", "lin_key")
    monkeypatch.setenv("LINEAR_TEAM_ID", "TEAM")
    router.add("/graphql",
               [(200, _json_bytes({"errors": [{"message": "Authentication required"}]}))])
    with pytest.raises(sinks.SinkError) as exc:
        get_sink("linear").deliver(_doc())
    assert "Authentication required" in str(exc.value)


def test_linear_unsuccessful_raises(router, monkeypatch):
    monkeypatch.setenv("LINEAR_API_KEY", "lin_key")
    monkeypatch.setenv("LINEAR_TEAM_ID", "TEAM")
    router.add("/graphql",
               [(200, _json_bytes({"data": {"issueCreate": {"success": False}}}))])
    with pytest.raises(sinks.SinkError):
        get_sink("linear").deliver(_doc())


# --------------------------------------------------------------------------- #
# Yuque
# --------------------------------------------------------------------------- #
def test_yuque_success(router, monkeypatch):
    monkeypatch.setenv("YUQUE_TOKEN", "ytok")
    monkeypatch.setenv("YUQUE_NAMESPACE", "me/notes")
    router.add("/repos/me/notes/docs",
               [(200, _json_bytes({"data": {"id": 9, "slug": "my-doc"}}))])

    res = get_sink("yuque").deliver(_doc())
    assert res.ok and res.url == "https://www.yuque.com/me/notes/my-doc"

    _m, _u, headers, _d = router.request("/repos/me/notes/docs")
    assert headers["X-Auth-Token"] == "ytok"
    assert headers["User-Agent"] == "MinerU-Skill/3.0"
    payload = router.payload("/repos/me/notes/docs")
    assert payload == {"title": "My Doc", "slug": "my-doc", "public": 0,
                       "format": "markdown", "body": "# Title\n\nbody\n"}


def test_yuque_alias_resolves():
    assert get_sink("语雀") is get_sink("yuque")


def test_yuque_error_raises(router, monkeypatch):
    monkeypatch.setenv("YUQUE_TOKEN", "ytok")
    monkeypatch.setenv("YUQUE_NAMESPACE", "me/notes")
    router.add("/repos/me/notes/docs",
               [(401, _json_bytes({"message": "Unauthorized"}))])
    with pytest.raises(sinks.SinkError) as exc:
        get_sink("yuque").deliver(_doc())
    assert "Unauthorized" in str(exc.value)


# --------------------------------------------------------------------------- #
# Coda
# --------------------------------------------------------------------------- #
def test_coda_creates_new_doc(router, monkeypatch):
    monkeypatch.setenv("CODA_API_TOKEN", "ctok")
    monkeypatch.delenv("CODA_DOC_ID", raising=False)
    router.add("/apis/v1/docs",
               [(201, _json_bytes({"id": "D1", "browserLink": "https://coda.io/d/D1"}))])

    res = get_sink("coda").deliver(_doc())
    assert res.ok and res.url == "https://coda.io/d/D1"

    _m, url, headers, _d = router.request("/apis/v1/docs")
    assert url == "https://coda.io/apis/v1/docs"
    assert headers["Authorization"] == "Bearer ctok"
    payload = router.payload("/apis/v1/docs")
    assert payload["title"] == "My Doc"
    assert payload["initialPage"]["pageContent"]["canvasContent"]["format"] == "markdown"


def test_coda_adds_page_to_existing_doc(router, monkeypatch):
    monkeypatch.setenv("CODA_API_TOKEN", "ctok")
    monkeypatch.setenv("CODA_DOC_ID", "EXIST")
    router.add("/apis/v1/docs/EXIST/pages",
               [(202, _json_bytes({"id": "P1", "browserLink": "https://coda.io/d/EXIST/P1"}))])

    res = get_sink("coda").deliver(_doc())
    assert res.ok and res.url == "https://coda.io/d/EXIST/P1"
    _m, url, _h, _d = router.request("/apis/v1/docs/EXIST/pages")
    assert url == "https://coda.io/apis/v1/docs/EXIST/pages"
    payload = router.payload("/apis/v1/docs/EXIST/pages")
    assert payload["name"] == "My Doc"
    assert payload["pageContent"]["canvasContent"]["content"] == "# Title\n\nbody\n"


def test_coda_error_raises(router, monkeypatch):
    monkeypatch.setenv("CODA_API_TOKEN", "ctok")
    monkeypatch.delenv("CODA_DOC_ID", raising=False)
    router.add("/apis/v1/docs",
               [(403, _json_bytes({"message": "Forbidden"}))])
    with pytest.raises(sinks.SinkError) as exc:
        get_sink("coda").deliver(_doc())
    assert "Forbidden" in str(exc.value)


# --------------------------------------------------------------------------- #
# deliver_all integration (failure surfaces as ok=False)
# --------------------------------------------------------------------------- #
def test_deliver_all_failure_path(router, monkeypatch):
    monkeypatch.setenv("CODA_API_TOKEN", "ctok")
    monkeypatch.delenv("CODA_DOC_ID", raising=False)
    router.add("/apis/v1/docs", [(500, _json_bytes({"message": "boom"}))])
    results = sinks.deliver_all(_doc(), ["coda"])
    assert len(results) == 1
    assert results[0].ok is False
    assert "boom" in results[0].error
