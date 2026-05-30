"""Tests for the optional WPS / 金山文档 sink (Markdown→DOCX + WPS-2 signed upload).

The Markdown→DOCX dependency (``html-for-docx``) is faked, and HTTP is mocked, so
these run offline without the optional package installed.
"""

import hashlib
import json
import sys
import types

import pytest

import sinks
from sinks import wps as wps_mod
from sinks.base import ParsedDoc, SinkError


class _FakeDocxDoc:
    def save(self, buf):
        buf.write(b"PK\x03\x04fake-docx-bytes")


class _FakeHtmlToDocx:
    def parse_html_string(self, html):
        assert "<h1>" in html  # confirms md_to_html ran
        return _FakeDocxDoc()


@pytest.fixture
def fake_html4docx(monkeypatch):
    mod = types.ModuleType("html4docx")
    mod.HtmlToDocx = _FakeHtmlToDocx
    monkeypatch.setitem(sys.modules, "html4docx", mod)
    return mod


def test_wps_registered():
    assert sinks.get_sink("wps") is sinks.get_sink("kdocs")
    assert sinks.get_sink("金山文档") is not None


def test_wps_uploads_with_valid_wps2_signature(fake_html4docx, monkeypatch):
    calls = []

    def fake_http(method, url, *, headers=None, data=None, timeout=60):
        calls.append((method, url, headers, data))
        return 200, json.dumps({"code": 0, "data": {"file_token": "box-xyz"}}).encode()

    monkeypatch.setattr(sinks._http, "http_request", fake_http)
    monkeypatch.setenv("WPS_APP_ID", "app123")
    monkeypatch.setenv("WPS_APP_SECRET", "secret456")

    doc = ParsedDoc(title="My Report", markdown="# Hi\n\nsome text\n")
    res = sinks.get_sink("wps").deliver(doc)

    assert res.ok and res.url == "box-xyz"
    method, url, headers, body = calls[-1]
    assert method == "POST" and url == wps_mod.KDOCS_UPLOAD
    assert b'filename="My Report.docx"' in body and b"fake-docx-bytes" in body

    # WPS-2 signature is plain SHA-1(secret + content_md5 + content_type + date).
    assert headers["Authorization"].startswith("WPS-2:app123:")
    sig = headers["Authorization"].split(":", 2)[2]
    assert len(sig) == 40
    assert headers["Content-Md5"] == hashlib.md5(body).hexdigest()
    expected = hashlib.sha1(
        ("secret456" + headers["Content-Md5"] + headers["Content-Type"] + headers["Date"]).encode()
    ).hexdigest()
    assert sig == expected


def test_wps_surfaces_api_error(fake_html4docx, monkeypatch):
    monkeypatch.setattr(
        sinks._http, "http_request",
        lambda *a, **k: (200, json.dumps({"code": 40001, "message": "bad app"}).encode()),
    )
    monkeypatch.setenv("WPS_APP_ID", "x")
    monkeypatch.setenv("WPS_APP_SECRET", "y")
    out = sinks.deliver_all(ParsedDoc(title="t", markdown="# h\n"), ["wps"])
    assert out[0].ok is False and "bad app" in out[0].error


def test_wps_missing_converter_gives_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "html4docx", None)  # force ImportError
    monkeypatch.setenv("WPS_APP_ID", "x")
    monkeypatch.setenv("WPS_APP_SECRET", "y")
    with pytest.raises(SinkError) as exc:
        sinks.get_sink("wps").deliver(ParsedDoc(title="t", markdown="# h\n"))
    assert "pip install" in str(exc.value)
