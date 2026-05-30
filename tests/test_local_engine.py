"""Tests for the optional offline engine (--engine local/auto), libs faked."""

import json
import sys
import types

import pytest

import local_engine
import mineru
from local_engine import LocalEngineError


@pytest.fixture
def fake_pymupdf4llm(monkeypatch):
    mod = types.ModuleType("pymupdf4llm")
    mod.to_markdown = lambda path, **kw: f"# Local\n\nparsed offline: {path}\n"
    monkeypatch.setitem(sys.modules, "pymupdf4llm", mod)
    return mod


def _fake_pymupdf(monkeypatch, text):
    class _Page:
        def get_text(self):
            return text

    class _Doc:
        def __iter__(self):
            return iter([_Page()])

    mod = types.ModuleType("pymupdf")
    mod.open = lambda path: _Doc()
    monkeypatch.setitem(sys.modules, "pymupdf", mod)


# --------------------------------------------------------------------------- #
# Module unit
# --------------------------------------------------------------------------- #
def test_available_and_parse(fake_pymupdf4llm, tmp_path):
    assert local_engine.available() is True
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    assert "# Local" in local_engine.parse_local(str(pdf))


def test_parse_local_missing_lib(monkeypatch):
    monkeypatch.setitem(sys.modules, "pymupdf4llm", None)
    with pytest.raises(LocalEngineError) as exc:
        local_engine.parse_local("x.pdf")
    assert "pip install" in str(exc.value)


def test_is_born_digital(monkeypatch):
    _fake_pymupdf(monkeypatch, "real extractable text " * 50)
    assert local_engine.is_born_digital("x.pdf") is True
    _fake_pymupdf(monkeypatch, "")
    assert local_engine.is_born_digital("x.pdf") is False


# --------------------------------------------------------------------------- #
# process_one wiring
# --------------------------------------------------------------------------- #
def test_engine_local_parses_offline_without_cloud(fake_pymupdf4llm, tmp_path, monkeypatch):
    monkeypatch.setattr(mineru, "_http", lambda *a, **k: (_ for _ in ()).throw(AssertionError("cloud called")))
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF")
    res = mineru.process_one(str(pdf), mineru.ParseOptions(), token=None,
                             output_dir=tmp_path / "out", engine="local", poll_interval=0)
    assert res.state == "done" and res.api == "local"
    assert "# Local" in res.markdown
    assert (tmp_path / "out" / "doc" / "doc.md").exists()


def test_engine_local_missing_lib_fails_with_hint(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "pymupdf4llm", None)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF")
    res = mineru.process_one(str(pdf), mineru.ParseOptions(), token=None,
                             output_dir=tmp_path / "out", engine="local", poll_interval=0)
    assert res.state == "failed" and "pip install" in res.error


def test_engine_auto_falls_back_to_cloud_for_scanned(fake_pymupdf4llm, tmp_path, monkeypatch):
    _fake_pymupdf(monkeypatch, "")  # no text -> not born-digital -> cloud

    def fake_http(method, url, *, headers=None, data=None, timeout=60):
        if "/agent/parse/file" in url:
            return 200, json.dumps({"code": 0, "data": {"task_id": "T", "file_url": "https://oss/u"}}).encode()
        if "oss/u" in url:
            return 200, b""
        if "/agent/parse/T" in url:
            return 200, json.dumps({"code": 0, "data": {"state": "done", "markdown_url": "https://cdn/m.md"}}).encode()
        if "cdn/m.md" in url:
            return 200, b"# Cloud\n"
        raise AssertionError(url)

    monkeypatch.setattr(mineru, "_http", fake_http)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF")
    res = mineru.process_one(str(pdf), mineru.ParseOptions(), token=None,
                             output_dir=tmp_path / "out", engine="auto", poll_interval=0)
    assert res.state == "done" and res.api == "agent"  # cloud was used
    assert "# Cloud" in res.markdown
