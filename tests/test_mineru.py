"""Unit + mocked-integration tests for the unified MinerU CLI.

HTTP is exercised through the single ``mineru._http`` seam, replaced per test by
a tiny in-memory router so no network access is required.
"""

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

import mineru


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
def _json_bytes(obj):
    return json.dumps(obj).encode("utf-8")


def _ok(data):
    return _json_bytes({"code": 0, "data": data, "msg": "ok"})


class Router:
    """Route fake HTTP calls by URL substring; supports sequenced responses."""

    def __init__(self):
        self._routes = []  # (method_or_None, substring, response_or_iterator)
        self.calls = []

    def add(self, substring, responses, method=None):
        # ``responses`` is a list of (status, bytes); repeated calls advance it.
        self._routes.append([method, substring, list(responses), 0])
        return self

    def __call__(self, method, url, *, headers=None, data=None, timeout=60):
        self.calls.append((method, url, data))
        for route in self._routes:
            want_method, substring, responses, idx = route
            if want_method and want_method != method:
                continue
            if substring in url:
                pick = min(idx, len(responses) - 1)
                route[3] = idx + 1
                return responses[pick]
        raise AssertionError(f"No fake route for {method} {url}")


@pytest.fixture
def router(monkeypatch):
    r = Router()
    monkeypatch.setattr(mineru, "_http", r)
    return r


def _make_zip(md_body="# Hello\n"):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("full.md", md_body)
        zf.writestr("images/.keep", "")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_is_url():
    assert mineru.is_url("https://x.com/a.pdf")
    assert mineru.is_url("http://x.com/a.pdf")
    assert not mineru.is_url("/tmp/a.pdf")


@pytest.mark.parametrize("source,expected", [
    ("/tmp/My Paper.pdf", "My Paper"),
    ("https://x.com/docs/report.pdf?token=abc", "report"),
    ("https://x.com/a/b/", "b"),
    ("./relative/file.PDF", "file"),
])
def test_safe_stem(source, expected):
    assert mineru.safe_stem(source) == expected


def test_safe_data_id_sanitizes_and_truncates():
    assert mineru.safe_data_id("a b/c*d") == "a-b-c-d"
    assert len(mineru.safe_data_id("x" * 300)) == 128


@pytest.mark.parametrize("name,supported", [
    ("a.pdf", True), ("a.PNG", True), ("a.docx", True),
    ("a.html", True), ("a.txt", False), ("a", False),
])
def test_is_supported(name, supported):
    assert mineru.is_supported(name) is supported


def test_is_html():
    assert mineru.is_html("a.HTML")
    assert not mineru.is_html("a.pdf")


@pytest.mark.parametrize("source,modality", [
    ("/tmp/a.pdf", "pdf"),
    ("scan.JPG", "image"),
    ("notes.docx", "word"),
    ("deck.pptx", "slides"),
    ("data.xlsx", "sheet"),
    ("page.html", "html"),
    ("https://x.com/download", "url"),
    ("mystery.bin", "unknown"),
])
def test_detect_modality(source, modality):
    assert mineru.detect_modality(source) == modality


@pytest.mark.parametrize("ranges,expected", [
    (None, None), ("", None), ("1-10", "1-10"), ("2,4-6", "2"),
])
def test_to_agent_page_range(ranges, expected):
    assert mineru.to_agent_page_range(ranges) == expected


def test_error_hint_known_and_unknown():
    assert "Standard API" in mineru.error_hint(-30001)
    assert "expired" in mineru.error_hint("A0211")
    assert "code 999" in mineru.error_hint(999)


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #
def test_choose_api_no_token_uses_agent():
    assert mineru.choose_api(token=None, source="a.pdf", size_bytes=10,
                             batch=False, extra_formats=(), explicit="auto") == "agent"


def test_choose_api_html_forces_standard():
    assert mineru.choose_api(token=None, source="a.html", size_bytes=10,
                             batch=False, extra_formats=(), explicit="auto") == "standard"


def test_choose_api_token_small_stays_agent():
    assert mineru.choose_api(token="t", source="a.pdf", size_bytes=1024,
                             batch=False, extra_formats=(), explicit="auto") == "agent"


@pytest.mark.parametrize("kwargs", [
    dict(batch=True, extra_formats=(), size_bytes=1),
    dict(batch=False, extra_formats=("docx",), size_bytes=1),
    dict(batch=False, extra_formats=(), size_bytes=mineru.AGENT_MAX_BYTES + 1),
])
def test_choose_api_token_escalates_to_standard(kwargs):
    assert mineru.choose_api(token="t", source="a.pdf", explicit="auto", **kwargs) == "standard"


@pytest.mark.parametrize("explicit", ["agent", "standard"])
def test_choose_api_explicit_wins(explicit):
    assert mineru.choose_api(token=None, source="a.html", size_bytes=10**9,
                             batch=True, extra_formats=("docx",), explicit=explicit) == explicit


# --------------------------------------------------------------------------- #
# _api_json
# --------------------------------------------------------------------------- #
def test_api_json_returns_data(router):
    router.add("/extract/task", [(200, _ok({"task_id": "T1"}))])
    data = mineru._api_json("POST", f"{mineru.STANDARD_API}/extract/task", token="t", payload={})
    assert data["task_id"] == "T1"


def test_api_json_raises_on_error_code(router):
    router.add("/extract/task", [(200, _json_bytes({"code": "A0202", "msg": "bad"}))])
    with pytest.raises(mineru.MinerUError) as exc:
        mineru._api_json("POST", f"{mineru.STANDARD_API}/extract/task", payload={})
    assert exc.value.code == "A0202"


def test_api_json_handles_auth_gateway_envelope(router):
    # Real v4 auth failures use {success:false, msgCode:...} instead of {code:...}.
    router.add("/extract/task", [(200, _json_bytes({
        "traceId": "x", "msgCode": "A0202", "msg": "user authenticate failed",
        "data": None, "success": False, "total": 0,
    }))])
    with pytest.raises(mineru.MinerUError) as exc:
        mineru._api_json("POST", f"{mineru.STANDARD_API}/extract/task", token="bad", payload={})
    assert exc.value.code == "A0202"
    assert "token" in str(exc.value).lower()


# --------------------------------------------------------------------------- #
# Agent flow
# --------------------------------------------------------------------------- #
def test_agent_parse_url_success(router):
    router.add("/agent/parse/url", [(200, _ok({"task_id": "A1"}))])
    router.add("/agent/parse/A1", [
        (200, _ok({"state": "running"})),
        (200, _ok({"state": "done", "markdown_url": "https://cdn/full.md"})),
    ])
    router.add("cdn/full.md", [(200, b"# Parsed\n")])

    markdown, task_id = mineru.agent_parse("https://x.com/a.pdf", mineru.ParseOptions(), poll_interval=0)
    assert task_id == "A1"
    assert markdown == "# Parsed\n"


def test_agent_parse_file_uploads_then_polls(router, tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    router.add("/agent/parse/file", [(200, _ok({"task_id": "A2", "file_url": "https://oss/put"}))])
    router.add("oss/put", [(200, b"")], method="PUT")
    router.add("/agent/parse/A2", [(200, _ok({"state": "done", "markdown_url": "https://cdn/m.md"}))])
    router.add("cdn/m.md", [(200, b"# File\n")])

    markdown, task_id = mineru.agent_parse(str(pdf), mineru.ParseOptions(), poll_interval=0)
    assert markdown == "# File\n"
    # Ensure a PUT upload actually happened.
    assert any(method == "PUT" for method, _url, _data in router.calls)


def test_agent_parse_failed_raises_with_code(router):
    router.add("/agent/parse/url", [(200, _ok({"task_id": "A3"}))])
    router.add("/agent/parse/A3", [(200, _ok({"state": "failed", "err_code": -30003, "err_msg": "too many pages"}))])
    with pytest.raises(mineru.MinerUError) as exc:
        mineru.agent_parse("https://x.com/a.pdf", mineru.ParseOptions(), poll_interval=0)
    assert exc.value.code == -30003


# --------------------------------------------------------------------------- #
# Standard flow
# --------------------------------------------------------------------------- #
def test_standard_parse_file_returns_zip(router, tmp_path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF fake")
    zip_bytes = _make_zip("# Report\n")
    router.add("/file-urls/batch", [(200, _ok({"batch_id": "B1", "file_urls": ["https://oss/put1"]}))])
    router.add("oss/put1", [(200, b"")], method="PUT")
    router.add("/extract-results/batch/B1", [
        (200, _ok({"extract_result": [{"file_name": "report.pdf", "state": "done", "full_zip_url": "https://cdn/r.zip"}]})),
    ])
    router.add("cdn/r.zip", [(200, zip_bytes)])

    blob, batch_id = mineru.standard_parse(str(pdf), mineru.ParseOptions(), token="t", poll_interval=0)
    assert batch_id == "B1"
    assert blob == zip_bytes


def test_standard_parse_url_uses_extract_task(router):
    zip_bytes = _make_zip()
    router.add("/extract/task", [(200, _ok({"task_id": "T9"}))], method="POST")
    router.add("/extract/task/T9", [(200, _ok({"state": "done", "full_zip_url": "https://cdn/u.zip"}))], method="GET")
    router.add("cdn/u.zip", [(200, zip_bytes)])

    blob, task_id = mineru.standard_parse("https://x.com/a.pdf", mineru.ParseOptions(), token="t", poll_interval=0)
    assert task_id == "T9"
    assert blob == zip_bytes


def test_standard_html_uses_minerhtml_model(router):
    router.add("/extract/task", [(200, _ok({"task_id": "H1"}))], method="POST")
    router.add("/extract/task/H1", [(200, _ok({"state": "done", "full_zip_url": "https://cdn/h.zip"}))], method="GET")
    router.add("cdn/h.zip", [(200, _make_zip())])

    mineru.standard_parse("https://x.com/page.html", mineru.ParseOptions(), token="t", poll_interval=0)

    post = next(d for m, u, d in router.calls if m == "POST" and u.endswith("/extract/task"))
    assert json.loads(post.decode())["model_version"] == "MinerU-HTML"


# --------------------------------------------------------------------------- #
# Output writers
# --------------------------------------------------------------------------- #
def test_write_markdown(tmp_path):
    md_path = mineru.write_markdown("doc", "# Hi\n", tmp_path)
    assert md_path == tmp_path / "doc" / "doc.md"
    assert md_path.read_text() == "# Hi\n"


def test_write_zip_renames_full_md(tmp_path):
    md_path = mineru.write_zip("doc", _make_zip("# Z\n"), tmp_path)
    assert md_path == tmp_path / "doc" / "doc.md"
    assert md_path.read_text() == "# Z\n"
    assert not (tmp_path / "doc" / "full.md").exists()


def test_copy_to_obsidian_copies_md_and_images(tmp_path):
    src_dir = tmp_path / "out" / "doc"
    (src_dir / "images").mkdir(parents=True)
    md = src_dir / "doc.md"
    md.write_text("# Vault\n")
    (src_dir / "images" / "fig1.png").write_bytes(b"img")
    vault = tmp_path / "vault"
    dest = mineru.copy_to_obsidian(md, "doc", vault)
    assert dest.read_text() == "# Vault\n"
    assert (vault / "images" / "fig1.png").read_bytes() == b"img"


# --------------------------------------------------------------------------- #
# expand_inputs
# --------------------------------------------------------------------------- #
def test_expand_inputs_directory_filters_supported(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"x")
    (tmp_path / "b.docx").write_bytes(b"x")
    (tmp_path / "c.txt").write_bytes(b"x")
    out = mineru.expand_inputs([str(tmp_path), "https://x.com/d.pdf"])
    assert sorted(Path(p).name for p in out if not mineru.is_url(p)) == ["a.pdf", "b.docx"]
    assert "https://x.com/d.pdf" in out


# --------------------------------------------------------------------------- #
# process_one orchestration
# --------------------------------------------------------------------------- #
def test_process_one_agent_writes_markdown(router, tmp_path):
    router.add("/agent/parse/url", [(200, _ok({"task_id": "P1"}))])
    router.add("/agent/parse/P1", [(200, _ok({"state": "done", "markdown_url": "https://cdn/p.md"}))])
    router.add("cdn/p.md", [(200, b"# Agent\n")])

    res = mineru.process_one(
        "https://x.com/a.pdf", mineru.ParseOptions(), token=None,
        output_dir=tmp_path, poll_interval=0,
    )
    assert res.state == "done"
    assert res.api == "agent"
    assert Path(res.markdown_path).read_text() == "# Agent\n"


def test_process_one_resume_skips_existing(tmp_path):
    target = tmp_path / "a"
    target.mkdir(parents=True)
    (target / "a.md").write_text("done")
    res = mineru.process_one(
        "https://x.com/a.pdf", mineru.ParseOptions(), token=None,
        output_dir=tmp_path, resume=True, poll_interval=0,
    )
    assert res.state == "skipped"


def test_process_one_auto_escalates_to_standard(router, tmp_path, monkeypatch):
    pdf = tmp_path / "big.pdf"
    pdf.write_bytes(b"%PDF small-but-many-pages")
    # Agent path fails with a page-limit error.
    router.add("/agent/parse/file", [(200, _ok({"task_id": "E1", "file_url": "https://oss/e"}))])
    router.add("oss/e", [(200, b"")], method="PUT")
    router.add("/agent/parse/E1", [(200, _ok({"state": "failed", "err_code": -30003, "err_msg": "pages"}))])
    # Standard path succeeds; the result zip is now streamed to disk, not buffered.
    router.add("/file-urls/batch", [(200, _ok({"batch_id": "E2", "file_urls": ["https://oss/e2"]}))])
    router.add("oss/e2", [(200, b"")], method="PUT")
    router.add("/extract-results/batch/E2", [
        (200, _ok({"extract_result": [{"file_name": "big.pdf", "state": "done", "full_zip_url": "https://cdn/e.zip"}]})),
    ])

    def fake_download(url, dest, *, timeout=300):
        Path(dest).write_bytes(_make_zip("# Escalated\n"))
        return dest

    monkeypatch.setattr(mineru, "_download_to_path", fake_download)

    res = mineru.process_one(
        str(pdf), mineru.ParseOptions(), token="t",
        output_dir=tmp_path, poll_interval=0,
    )
    assert res.state == "done"
    assert res.api == "standard"
    assert Path(res.markdown_path).read_text() == "# Escalated\n"


def test_process_one_standard_without_token_fails(tmp_path):
    res = mineru.process_one(
        "https://x.com/page.html", mineru.ParseOptions(), token=None,
        output_dir=tmp_path, poll_interval=0,
    )
    assert res.state == "failed"
    assert "token" in res.error.lower()


# --------------------------------------------------------------------------- #
# CLI plumbing
# --------------------------------------------------------------------------- #
def test_options_from_args_maps_flags():
    args = mineru.build_parser().parse_args(
        ["a.pdf", "--ocr", "--no-table", "--format", "docx", "--pages", "1-3", "--lang", "en"]
    )
    opts = mineru.options_from_args(args)
    assert opts.is_ocr is True
    assert opts.enable_table is False
    assert opts.extra_formats == ("docx",)
    assert opts.page_ranges == "1-3"
    assert opts.language == "en"


def test_to_status_omits_markdown_body():
    res = mineru.ParseResult(name="d", source="s", modality="pdf", markdown="# big body")
    status = res.to_status()
    assert "markdown" not in status
    assert status["name"] == "d"
    assert status["modality"] == "pdf"


def test_process_one_records_modality_and_timing(router, tmp_path):
    router.add("/agent/parse/url", [(200, _ok({"task_id": "T1"}))])
    router.add("/agent/parse/T1", [(200, _ok({"state": "done", "markdown_url": "https://cdn/t.md"}))])
    router.add("cdn/t.md", [(200, b"# M\n")])
    res = mineru.process_one(
        "https://x.com/a.pdf", mineru.ParseOptions(), token=None,
        output_dir=tmp_path, poll_interval=0,
    )
    assert res.modality == "pdf"
    assert res.elapsed is not None and res.elapsed >= 0


def test_main_json_output(router, tmp_path, capsys, monkeypatch):
    pdf = tmp_path / "m.pdf"
    pdf.write_bytes(b"%PDF")
    router.add("/agent/parse/file", [(200, _ok({"task_id": "M1", "file_url": "https://oss/m"}))])
    router.add("oss/m", [(200, b"")], method="PUT")
    router.add("/agent/parse/M1", [(200, _ok({"state": "done", "markdown_url": "https://cdn/mm.md"}))])
    router.add("cdn/mm.md", [(200, b"# Main\n")])
    monkeypatch.delenv("MINERU_TOKEN", raising=False)

    code = mineru.main([str(pdf), "--output", str(tmp_path / "out"), "--json", "--quiet"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["done"] == 1
    assert payload["results"][0]["api"] == "agent"


# --------------------------------------------------------------------------- #
# Retry / backoff layer (patches the lower _send_once seam; _http wraps it)
# --------------------------------------------------------------------------- #
def test_http_retries_5xx_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_send(method, url, *, headers=None, data=None, timeout=60):
        calls["n"] += 1
        return (503, b"busy", None) if calls["n"] == 1 else (200, b"ok", None)

    monkeypatch.setattr(mineru, "_send_once", fake_send)
    monkeypatch.setattr(mineru, "_backoff_delay", lambda *a, **k: 0)
    status, body = mineru._http("GET", "https://x/y")
    assert status == 200 and body == b"ok" and calls["n"] == 2


def test_http_does_not_retry_4xx(monkeypatch):
    calls = {"n": 0}

    def fake_send(*a, **k):
        calls["n"] += 1
        return 404, b"nope", None

    monkeypatch.setattr(mineru, "_send_once", fake_send)
    status, body = mineru._http("GET", "https://x/y")
    assert status == 404 and calls["n"] == 1  # client/business errors are not retried


def test_http_429_retries_then_raises(monkeypatch):
    monkeypatch.setattr(mineru, "_send_once", lambda *a, **k: (429, b"", "1"))
    monkeypatch.setattr(mineru, "_backoff_delay", lambda *a, **k: 0)
    with pytest.raises(mineru.MinerUError) as exc:
        mineru._http("GET", "https://x/y")
    assert exc.value.code == 429


def test_api_json_retries_retryable_business_code(router, monkeypatch):
    monkeypatch.setattr(mineru, "_backoff_delay", lambda *a, **k: 0)
    router.add(
        "/file-urls/batch",
        [
            (200, _json_bytes({"code": -60009, "msg": "queue full"})),
            (200, _ok({"batch_id": "B", "file_urls": []})),
        ],
        method="POST",
    )

    data = mineru._api_json("POST", f"{mineru.STANDARD_API}/file-urls/batch", token="t", payload={})

    assert data["batch_id"] == "B"
    posts = [c for c in router.calls if c[0] == "POST" and c[1].endswith("/file-urls/batch")]
    assert len(posts) == 2


def test_api_json_rejects_non_2xx_even_with_success_envelope(router):
    router.add("/extract/task", [(403, _ok({"task_id": "SHOULD_NOT_PASS"}))], method="POST")

    with pytest.raises(mineru.MinerUError) as exc:
        mineru._api_json("POST", f"{mineru.STANDARD_API}/extract/task", token="t", payload={})

    assert "HTTP 403" in str(exc.value)


def test_api_json_does_not_retry_fatal_business_code(router, monkeypatch):
    monkeypatch.setattr(mineru, "_backoff_delay", lambda *a, **k: 0)
    router.add(
        "/extract/task",
        [(200, _json_bytes({"code": "A0202", "msg": "bad token"}))],
        method="POST",
    )

    with pytest.raises(mineru.MinerUError) as exc:
        mineru._api_json("POST", f"{mineru.STANDARD_API}/extract/task", token="bad", payload={})

    assert exc.value.code == "A0202"
    calls = [c for c in router.calls if c[0] == "POST" and c[1].endswith("/extract/task")]
    assert len(calls) == 1


def test_api_json_retryable_business_code_exhaustion_keeps_code(router, monkeypatch):
    monkeypatch.setattr(mineru, "_backoff_delay", lambda *a, **k: 0)
    router.add(
        "/file-urls/batch",
        [(200, _json_bytes({"code": -60009, "msg": "queue full"}))],
        method="POST",
    )

    with pytest.raises(mineru.MinerUError) as exc:
        mineru._api_json("POST", f"{mineru.STANDARD_API}/file-urls/batch", token="t", payload={})

    assert exc.value.code == -60009
    assert "queue is full" in str(exc.value)
    calls = [c for c in router.calls if c[0] == "POST" and c[1].endswith("/file-urls/batch")]
    assert len(calls) == mineru.RETRY_MAX_ATTEMPTS


def test_http_network_error_retries_then_raises(monkeypatch):
    import urllib.error

    def fake_send(*a, **k):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(mineru, "_send_once", fake_send)
    monkeypatch.setattr(mineru, "_backoff_delay", lambda *a, **k: 0)
    with pytest.raises(mineru.MinerUError):
        mineru._http("GET", "https://x/y")


def test_backoff_delay_grows_caps_and_honors_retry_after():
    assert 0 < mineru._backoff_delay(0) <= mineru.RETRY_BASE_DELAY
    assert mineru._backoff_delay(8) <= mineru.RETRY_MAX_DELAY
    assert mineru._backoff_delay(0, "2") == 2.0  # explicit Retry-After wins


# --------------------------------------------------------------------------- #
# Streaming + atomic writers
# --------------------------------------------------------------------------- #
def test_extract_zip_path_renames_full_md(tmp_path):
    zip_file = tmp_path / "r.zip"
    zip_file.write_bytes(_make_zip("# Streamed\n"))
    md = mineru.extract_zip_path("doc", zip_file, tmp_path / "out")
    assert md == tmp_path / "out" / "doc" / "doc.md"
    assert md.read_text() == "# Streamed\n"


def test_write_markdown_is_atomic(tmp_path):
    md = mineru.write_markdown("d", "# A\n", tmp_path)
    assert md.read_text() == "# A\n"
    assert not list((tmp_path / "d").glob(".*partial"))  # no leftover temp file


def test_write_zip_rejects_path_traversal(tmp_path):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../pwn.md", "owned")

    with pytest.raises(mineru.MinerUError):
        mineru.write_zip("doc", buf.getvalue(), tmp_path / "out")

    assert not (tmp_path / "pwn.md").exists()


def test_put_file_streams_with_content_length(monkeypatch, tmp_path):
    src = tmp_path / "upload.pdf"
    src.write_bytes(b"x" * 1024)
    seen = {}

    def fake_http(method, url, *, headers=None, data=None, timeout=60):
        seen["method"] = method
        seen["headers"] = headers
        seen["data"] = data
        return 200, b""

    monkeypatch.setattr(mineru, "_http", fake_http)

    mineru._put_file("https://oss/upload", str(src))

    assert seen["method"] == "PUT"
    assert seen["headers"]["Content-Length"] == "1024"
    assert "Content-Type" not in seen["headers"]
    assert hasattr(seen["data"], "read")


def test_send_once_redirect_rewinds_stream_body(monkeypatch):
    reads = []

    class FakeResponse:
        version = 11

        def __init__(self, status, location=None):
            self.status = status
            self._location = location

        def read(self):
            return b""

        def getheader(self, name, default=None):
            if name == "Location":
                return self._location
            return default

    class FakeConn:
        def __init__(self, response):
            self.response = response
            self.timeout = None

        def request(self, method, path, body=None, headers=None):
            reads.append(body.read() if hasattr(body, "read") else body)

        def getresponse(self):
            return self.response

    conns = [
        FakeConn(FakeResponse(307, "https://oss.example/upload2")),
        FakeConn(FakeResponse(200)),
    ]

    def fake_get_conn(scheme, host, port, timeout):
        return conns.pop(0), (scheme, host, port)

    monkeypatch.setattr(mineru, "_get_conn", fake_get_conn)
    body = BytesIO(b"payload")

    status, _raw, _retry_after = mineru._send_once("PUT", "https://oss.example/upload", data=body)

    assert status == 200
    assert reads == [b"payload", b"payload"]


def test_process_one_prechecks_standard_file_size(tmp_path):
    huge = tmp_path / "huge.pdf"
    with open(huge, "wb") as handle:
        handle.truncate(mineru.STANDARD_MAX_BYTES + 1)

    res = mineru.process_one(
        str(huge), mineru.ParseOptions(), token="t",
        output_dir=tmp_path / "out", api="standard",
    )

    assert res.state == "failed"
    assert "200 MB" in res.error


def test_precheck_empty_file_fails_before_submit(router, tmp_path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")

    res = mineru.process_one(
        str(empty),
        mineru.ParseOptions(),
        token=None,
        output_dir=tmp_path / "out",
        api="agent",
    )

    assert res.state == "failed"
    assert "Empty file" in res.error
    assert router.calls == []


# --------------------------------------------------------------------------- #
# Decoupled pipeline: true batch submit, batch poll, failure isolation.
# These pin the `active`-filter regression: without the fix the poll phase is
# skipped and every batched file is wrongly reported failed.
# --------------------------------------------------------------------------- #
def test_chunk_standard_files_splits_by_model_and_size():
    opts = mineru.ParseOptions()
    pdfs = [
        mineru._Job(
            source=f"f{i}.pdf",
            stem=f"f{i}",
            api="standard",
            is_url=False,
            result=mineru.ParseResult(name=f"f{i}", source=f"f{i}.pdf"),
        )
        for i in range(3)
    ]
    html = mineru._Job(
        source="p.html",
        stem="p",
        api="standard",
        is_url=False,
        result=mineru.ParseResult(name="p", source="p.html"),
    )
    chunks = mineru._chunk_standard_files(pdfs + [html], opts, batch_size=2)
    assert sorted(len(c) for c in chunks) == [1, 1, 2]  # pdfs -> 2+1, html isolated
    assert any(all(mineru.is_html(j.source) for j in c) for c in chunks)


def test_run_pipeline_true_batch_submit(router, tmp_path, monkeypatch):
    a = tmp_path / "a.pdf"
    a.write_bytes(b"%PDF a")
    b = tmp_path / "b.pdf"
    b.write_bytes(b"%PDF b")
    router.add(
        "/file-urls/batch",
        [(200, _ok({"batch_id": "B", "file_urls": ["https://oss/a", "https://oss/b"]}))],
        method="POST",
    )
    router.add("oss/a", [(200, b"")], method="PUT")
    router.add("oss/b", [(200, b"")], method="PUT")
    router.add(
        "/extract-results/batch/B",
        [
            (
                200,
                _ok(
                    {
                        "extract_result": [
                            {
                                "file_name": "a.pdf",
                                "state": "done",
                                "full_zip_url": "https://cdn/a.zip",
                            },
                            {
                                "file_name": "b.pdf",
                                "state": "done",
                                "full_zip_url": "https://cdn/b.zip",
                            },
                        ]
                    }
                ),
            )
        ],
    )

    def fake_download(url, dest, *, timeout=300):
        Path(dest).write_bytes(_make_zip(f"# {url[-5:]}\n"))
        return dest

    monkeypatch.setattr(mineru, "_download_to_path", fake_download)

    results = mineru.run_pipeline(
        [str(a), str(b)],
        mineru.ParseOptions(),
        token="t",
        output_dir=tmp_path / "out",
        api="standard",
        resume=False,
        poll_interval=0,
        timeout=300,
        batch_size=50,
        workers=1,
        want_markdown=True,
    )
    assert sorted(r.state for r in results) == ["done", "done"]
    # The whole batch was submitted in ONE /file-urls/batch call with both files.
    posts = [d for m, u, d in router.calls if m == "POST" and u.endswith("/file-urls/batch")]
    assert len(posts) == 1
    assert len(json.loads(posts[0].decode())["files"]) == 2
    assert (tmp_path / "out" / "a" / "a.md").exists()
    assert (tmp_path / "out" / "b" / "b.md").exists()


def test_reserve_batch_rejects_file_url_count_mismatch(monkeypatch, tmp_path):
    a = tmp_path / "a.pdf"
    a.write_bytes(b"a")
    b = tmp_path / "b.pdf"
    b.write_bytes(b"b")
    jobs = [
        mineru._Job(str(a), "a", "standard", False, mineru.ParseResult("a", str(a)), data_id="a-0"),
        mineru._Job(str(b), "b", "standard", False, mineru.ParseResult("b", str(b)), data_id="b-1"),
    ]

    def fake_api(method, url, *, token=None, payload=None, timeout=60):
        assert len(payload["files"]) == 2
        return {"batch_id": "B", "file_urls": ["https://oss/a"]}

    monkeypatch.setattr(mineru, "_api_json", fake_api)

    with pytest.raises(mineru.MinerUError) as exc:
        mineru._reserve_batch(jobs, mineru.ParseOptions(), "t", timeout=11)

    assert "upload URL" in str(exc.value)
    assert all(not job.poll_id for job in jobs)


def test_run_pipeline_passes_timeout_to_submit_upload_poll_and_download(monkeypatch, tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    seen = {"api": [], "upload": [], "download": []}

    def fake_api(method, url, *, token=None, payload=None, timeout=60):
        seen["api"].append((method, url, timeout))
        if url.endswith("/file-urls/batch"):
            return {"batch_id": "B", "file_urls": ["https://oss/a"]}
        if url.endswith("/extract-results/batch/B"):
            return {
                "extract_result": [
                    {
                        "data_id": "a-0",
                        "file_name": "a.pdf",
                        "state": "done",
                        "full_zip_url": "https://cdn/a.zip",
                    }
                ]
            }
        raise AssertionError(url)

    def fake_put(upload_url, path, timeout=300):
        seen["upload"].append(timeout)

    def fake_download(url, dest, *, timeout=300):
        seen["download"].append(timeout)
        Path(dest).write_bytes(_make_zip("# A\n"))
        return dest

    monkeypatch.setattr(mineru, "_api_json", fake_api)
    monkeypatch.setattr(mineru, "_put_file", fake_put)
    monkeypatch.setattr(mineru, "_download_to_path", fake_download)

    results = mineru.run_pipeline(
        [str(pdf)],
        mineru.ParseOptions(),
        token="t",
        output_dir=tmp_path / "out",
        api="standard",
        resume=False,
        poll_interval=0,
        timeout=7,
        batch_size=50,
        workers=1,
    )

    assert results[0].state == "done"
    assert {timeout for _method, _url, timeout in seen["api"]} == {7}
    assert seen["upload"] == [7]
    assert seen["download"] == [7]


def test_run_pipeline_batches_standard_urls(router, tmp_path, monkeypatch):
    router.add(
        "/extract/task/batch",
        [(200, _ok({"batch_id": "UB"}))],
        method="POST",
    )
    router.add(
        "/extract-results/batch/UB",
        [
            (
                200,
                _ok(
                    {
                        "extract_result": [
                            {
                                "data_id": "u1-0",
                                "file_name": "u1.pdf",
                                "state": "done",
                                "full_zip_url": "https://cdn/u1.zip",
                            },
                            {
                                "data_id": "u2-1",
                                "file_name": "u2.pdf",
                                "state": "done",
                                "full_zip_url": "https://cdn/u2.zip",
                            },
                        ]
                    }
                ),
            )
        ],
    )

    def fake_download(url, dest, *, timeout=300):
        Path(dest).write_bytes(_make_zip(f"# {url[-6:]}\n"))
        return dest

    monkeypatch.setattr(mineru, "_download_to_path", fake_download)

    results = mineru.run_pipeline(
        ["https://x.com/u1.pdf", "https://x.com/u2.pdf"],
        mineru.ParseOptions(),
        token="t",
        output_dir=tmp_path / "out",
        api="standard",
        resume=False,
        poll_interval=0,
        timeout=300,
        batch_size=50,
        workers=1,
        want_markdown=True,
    )

    assert sorted(r.state for r in results) == ["done", "done"]
    posts = [d for m, u, d in router.calls if m == "POST" and u.endswith("/extract/task/batch")]
    assert len(posts) == 1
    assert len(json.loads(posts[0].decode())["files"]) == 2


def test_run_pipeline_isolates_per_file_failure(router, tmp_path):
    router.add(
        "/agent/parse/url",
        [(200, _ok({"task_id": "A1"})), (200, _ok({"task_id": "A2"}))],
        method="POST",
    )
    router.add(
        "/agent/parse/A1",
        [(200, _ok({"state": "done", "markdown_url": "https://cdn/a1.md"}))],
    )
    router.add(
        "/agent/parse/A2",
        [(200, _ok({"state": "failed", "err_code": -60010, "err_msg": "parse failed"}))],
    )
    router.add("cdn/a1.md", [(200, b"# A1\n")])

    results = mineru.run_pipeline(
        ["https://x.com/a.pdf", "https://x.com/b.pdf"],
        mineru.ParseOptions(),
        token=None,
        output_dir=tmp_path,
        api="auto",
        resume=False,
        poll_interval=0,
        timeout=300,
        batch_size=50,
        workers=1,
        want_markdown=True,
    )
    # one bad file does not abort the batch
    assert sorted(r.state for r in results) == ["done", "failed"]


def test_standard_failed_state_preserves_err_code_hint():
    job = mineru._Job(
        source="https://x.com/a.pdf",
        stem="a",
        api="standard",
        is_url=True,
        result=mineru.ParseResult(name="a", source="https://x.com/a.pdf"),
    )

    def fake_api(method, url, *, token=None, payload=None, timeout=60):
        return {"state": "failed", "err_code": -60018, "err_msg": ""}

    original = mineru._api_json
    mineru._api_json = fake_api
    try:
        completed, failed = mineru._poll_group("task", "T", [job], "t")
    finally:
        mineru._api_json = original

    assert completed == []
    assert failed == [job]
    assert "Daily parse quota" in job.result.error


def test_duplicate_batch_file_names_do_not_share_name_fallback():
    job1 = mineru._Job(
        source="/a/dup.pdf",
        stem="dup",
        api="standard",
        is_url=False,
        result=mineru.ParseResult(name="dup", source="/a/dup.pdf"),
        data_id="first",
        file_name="dup.pdf",
    )
    job2 = mineru._Job(
        source="/b/dup.pdf",
        stem="dup",
        api="standard",
        is_url=False,
        result=mineru.ParseResult(name="dup", source="/b/dup.pdf"),
        data_id="second",
        file_name="dup.pdf",
    )

    def fake_api(method, url, *, token=None, payload=None, timeout=60):
        return {
            "extract_result": [
                {"file_name": "dup.pdf", "state": "done", "full_zip_url": "https://cdn/one.zip"}
            ]
        }

    original = mineru._api_json
    mineru._api_json = fake_api
    try:
        completed, failed = mineru._poll_group("batch", "B", [job1, job2], "t")
    finally:
        mineru._api_json = original

    assert completed == []
    assert failed == []


def test_main_batch_routes_through_pipeline(router, tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    f1 = tmp_path / "x.pdf"
    f1.write_bytes(b"%PDF")
    f2 = tmp_path / "y.pdf"
    f2.write_bytes(b"%PDF")
    router.add(
        "/agent/parse/file",
        [
            (200, _ok({"task_id": "M1", "file_url": "https://oss/1"})),
            (200, _ok({"task_id": "M2", "file_url": "https://oss/2"})),
        ],
        method="POST",
    )
    router.add("oss/", [(200, b"")], method="PUT")
    router.add("/agent/parse/M1", [(200, _ok({"state": "done", "markdown_url": "https://cdn/1.md"}))])
    router.add("/agent/parse/M2", [(200, _ok({"state": "done", "markdown_url": "https://cdn/2.md"}))])
    router.add("cdn/1.md", [(200, b"# One\n")])
    router.add("cdn/2.md", [(200, b"# Two\n")])

    code = mineru.main(
        [
            str(f1),
            str(f2),
            "--output",
            str(tmp_path / "out"),
            "--workers",
            "1",
            "--poll-interval",
            "0",
            "--json",
            "--quiet",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["done"] == 2 and payload["failed"] == 0


def test_main_with_token_uses_standard_file_batch(router, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("MINERU_TOKEN", "t")
    a = tmp_path / "a.pdf"
    a.write_bytes(b"%PDF a")
    b = tmp_path / "b.pdf"
    b.write_bytes(b"%PDF b")
    router.add(
        "/file-urls/batch",
        [(200, _ok({"batch_id": "B", "file_urls": ["https://oss/a", "https://oss/b"]}))],
        method="POST",
    )
    router.add("oss/a", [(200, b"")], method="PUT")
    router.add("oss/b", [(200, b"")], method="PUT")
    router.add(
        "/extract-results/batch/B",
        [
            (
                200,
                _ok(
                    {
                        "extract_result": [
                            {"data_id": "a-0", "file_name": "a.pdf", "state": "done", "full_zip_url": "https://cdn/a.zip"},
                            {"data_id": "b-1", "file_name": "b.pdf", "state": "done", "full_zip_url": "https://cdn/b.zip"},
                        ]
                    }
                ),
            )
        ],
    )

    def fake_download(url, dest, *, timeout=300):
        Path(dest).write_bytes(_make_zip(f"# {url[-5:]}\n"))
        return dest

    monkeypatch.setattr(mineru, "_download_to_path", fake_download)

    code = mineru.main(
        [
            str(a),
            str(b),
            "--output",
            str(tmp_path / "out"),
            "--workers",
            "1",
            "--poll-interval",
            "0",
            "--json",
            "--quiet",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["done"] == 2
    assert {item["api"] for item in payload["results"]} == {"standard"}
    posts = [d for m, u, d in router.calls if m == "POST" and u.endswith("/file-urls/batch")]
    assert len(posts) == 1
    assert len(json.loads(posts[0].decode())["files"]) == 2


def test_main_returns_nonzero_when_pipeline_has_any_failed_input(router, tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    a = tmp_path / "ok.pdf"
    a.write_bytes(b"%PDF ok")
    b = tmp_path / "bad.pdf"
    b.write_bytes(b"%PDF bad")
    router.add(
        "/agent/parse/file",
        [
            (200, _ok({"task_id": "OK", "file_url": "https://oss/ok"})),
            (200, _ok({"task_id": "BAD", "file_url": "https://oss/bad"})),
        ],
        method="POST",
    )
    router.add("oss/", [(200, b"")], method="PUT")
    router.add("/agent/parse/OK", [(200, _ok({"state": "done", "markdown_url": "https://cdn/ok.md"}))])
    router.add("/agent/parse/BAD", [(200, _ok({"state": "failed", "err_code": -60010, "err_msg": "parse failed"}))])
    router.add("cdn/ok.md", [(200, b"# OK\n")])

    code = mineru.main(
        [
            str(a),
            str(b),
            "--output",
            str(tmp_path / "out"),
            "--workers",
            "1",
            "--poll-interval",
            "0",
            "--json",
            "--quiet",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["done"] == 1
    assert payload["failed"] == 1
    assert code == 1


def test_main_pipeline_stdout_prints_all_markdown(router, tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    f1 = tmp_path / "one.pdf"
    f1.write_bytes(b"%PDF one")
    f2 = tmp_path / "two.pdf"
    f2.write_bytes(b"%PDF two")
    router.add(
        "/agent/parse/file",
        [
            (200, _ok({"task_id": "S1", "file_url": "https://oss/s1"})),
            (200, _ok({"task_id": "S2", "file_url": "https://oss/s2"})),
        ],
        method="POST",
    )
    router.add("oss/", [(200, b"")], method="PUT")
    router.add("/agent/parse/S1", [(200, _ok({"state": "done", "markdown_url": "https://cdn/s1.md"}))])
    router.add("/agent/parse/S2", [(200, _ok({"state": "done", "markdown_url": "https://cdn/s2.md"}))])
    router.add("cdn/s1.md", [(200, b"# One\n")])
    router.add("cdn/s2.md", [(200, b"# Two\n")])

    code = mineru.main(
        [
            str(f1),
            str(f2),
            "--output",
            str(tmp_path / "out"),
            "--workers",
            "1",
            "--poll-interval",
            "0",
            "--stdout",
            "--quiet",
        ]
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "# One\n" in out
    assert "# Two\n" in out
