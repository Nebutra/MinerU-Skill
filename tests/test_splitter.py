"""Tests for oversized-PDF splitting + merge (optional pypdf, faked here)."""

import json
import sys
import types

import pytest

import mineru
import splitter


# --------------------------------------------------------------------------- #
# Fake pypdf: a "PDF" is a file whose bytes are b"PAGES=<n>"
# --------------------------------------------------------------------------- #
class _FakeReader:
    def __init__(self, path):
        n = int(open(path, "rb").read().split(b"=")[1])
        self.pages = list(range(n))


class _FakeWriter:
    def __init__(self):
        self._pages = []

    def add_page(self, page):
        self._pages.append(page)

    def write(self, handle):
        handle.write(b"PAGES=%d" % len(self._pages))


@pytest.fixture
def fake_pypdf(monkeypatch):
    mod = types.ModuleType("pypdf")
    mod.PdfReader = _FakeReader
    mod.PdfWriter = _FakeWriter
    monkeypatch.setitem(sys.modules, "pypdf", mod)
    return mod


def _ok(data):
    return json.dumps({"code": 0, "data": data, "msg": "ok"}).encode()


# --------------------------------------------------------------------------- #
# splitter unit
# --------------------------------------------------------------------------- #
def test_page_count(fake_pypdf, tmp_path):
    pdf = tmp_path / "d.pdf"
    pdf.write_bytes(b"PAGES=50")
    assert splitter.pdf_page_count(str(pdf)) == 50


def test_split_pdf_slices_into_parts(fake_pypdf, tmp_path):
    pdf = tmp_path / "d.pdf"
    pdf.write_bytes(b"PAGES=50")
    parts = splitter.split_pdf(str(pdf), 20, tmp_path / "parts")
    assert len(parts) == 3  # 20 + 20 + 10
    assert all(p.name.startswith("d__part") for p in parts)


def test_split_pdf_passthrough_when_small(fake_pypdf, tmp_path):
    pdf = tmp_path / "d.pdf"
    pdf.write_bytes(b"PAGES=5")
    parts = splitter.split_pdf(str(pdf), 20, tmp_path / "parts")
    assert parts == [pdf]


def test_split_pdf_missing_pypdf_raises(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "pypdf", None)  # force ImportError
    pdf = tmp_path / "d.pdf"
    pdf.write_bytes(b"x")
    with pytest.raises(splitter.SplitError) as exc:
        splitter.pdf_page_count(str(pdf))
    assert "pip install" in str(exc.value)


# --------------------------------------------------------------------------- #
# mineru.split_cap
# --------------------------------------------------------------------------- #
def test_split_cap():
    assert mineru.split_cap(None, "auto") == mineru.AGENT_MAX_PAGES
    assert mineru.split_cap("tok", "auto") == mineru.STANDARD_MAX_PAGES
    assert mineru.split_cap(None, "standard") == mineru.STANDARD_MAX_PAGES
    assert mineru.split_cap("tok", "auto", override=42) == 42


# --------------------------------------------------------------------------- #
# process_split orchestration
# --------------------------------------------------------------------------- #
def test_process_split_none_for_url_or_nonpdf():
    opts = mineru.ParseOptions()
    assert mineru.process_split("https://x.com/a.pdf", opts, token=None, output_dir=None,
                                api="auto", resume=False, timeout=1, cap=20) is None
    assert mineru.process_split("a.docx", opts, token=None, output_dir=None,
                                api="auto", resume=False, timeout=1, cap=20) is None


def test_process_split_none_when_fits(fake_pypdf, tmp_path):
    pdf = tmp_path / "small.pdf"
    pdf.write_bytes(b"PAGES=10")
    res = mineru.process_split(str(pdf), mineru.ParseOptions(), token=None,
                               output_dir=tmp_path / "out", api="auto", resume=False, timeout=1, cap=20)
    assert res is None  # fits -> caller uses normal process_one


def test_process_split_merges_parts(fake_pypdf, tmp_path, monkeypatch):
    pdf = tmp_path / "big.pdf"
    pdf.write_bytes(b"PAGES=45")  # -> 3 parts at cap 20

    def fake_http(method, url, *, headers=None, data=None, timeout=60):
        if "/agent/parse/file" in url:
            return 200, _ok({"task_id": "T", "file_url": "https://oss/u"})
        if "oss/u" in url:
            return 200, b""
        if "/agent/parse/T" in url:
            return 200, _ok({"state": "done", "markdown_url": "https://cdn/m.md"})
        if "cdn/m.md" in url:
            return 200, b"# Part\n\nbody\n"
        raise AssertionError(url)

    monkeypatch.setattr(mineru, "_http", fake_http)
    out = tmp_path / "out"
    res = mineru.process_split(
        str(pdf), mineru.ParseOptions(), token=None, output_dir=out, api="auto",
        resume=False, timeout=1, cap=20,
    )
    assert res.state == "done"
    assert res.markdown.count("# Part") == 3
    assert res.markdown.count("---") == 2  # 3 parts joined by 2 separators
    assert (out / "big" / "big.md").read_text(encoding="utf-8") == res.markdown
    assert res.task_id == "split:3parts"


def test_process_split_missing_pypdf_fails_with_hint(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "pypdf", None)
    pdf = tmp_path / "big.pdf"
    pdf.write_bytes(b"x")
    res = mineru.process_split(str(pdf), mineru.ParseOptions(), token=None,
                               output_dir=tmp_path / "out", api="auto", resume=False, timeout=1, cap=20)
    assert res.state == "failed" and "pip install" in res.error
