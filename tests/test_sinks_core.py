"""Tests for the sinks framework, Markdown utilities, local sinks, and CLI wiring."""

import json
from pathlib import Path

import pytest

import mineru
import sinks
from sinks import _http, _md, deliver_all, get_sink, sink_names
from sinks.base import ParsedDoc


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def test_all_sink_modules_load_cleanly():
    assert sinks.IMPORT_ERRORS == {}, f"sink import failures: {sinks.IMPORT_ERRORS}"


def test_expected_sinks_registered():
    names = set(sink_names())
    expected = {
        "obsidian", "logseq", "siyuan", "notion", "linear", "yuque", "coda",
        "slack", "feishu", "confluence", "onenote", "ticktick", "dingtalk",
        "airtable", "wecom",
    }
    assert expected <= names, f"missing sinks: {expected - names}"


def test_alias_resolves():
    assert get_sink("ob") is get_sink("obsidian")


# --------------------------------------------------------------------------- #
# Markdown utilities
# --------------------------------------------------------------------------- #
def test_slugify_and_safe_filename():
    assert _md.slugify("Hello World!") == "hello-world"
    assert _md.safe_filename('a/b:c*d?') == "a b c d"
    assert _md.safe_filename("") == "document"


def test_find_and_rewrite_images(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "fig.png").write_bytes(b"PNG")
    md = "# T\n\n![cap](images/fig.png)\n\n![remote](https://x.com/y.png)\n"
    found = _md.find_local_images(md, tmp_path)
    assert len(found) == 1 and found[0][1] == "images/fig.png"
    out = _md.rewrite_images(md, {"images/fig.png": "assets/fig.png"})
    assert "assets/fig.png" in out and "https://x.com/y.png" in out


def test_yaml_frontmatter():
    fm = _md.yaml_frontmatter({"title": "T", "tags": ["a", "b"], "empty": ""})
    assert "title: T" in fm and "- a" in fm and "- b" in fm
    assert "empty" not in fm
    assert fm.startswith("---") and fm.rstrip().endswith("---")


def test_md_to_html_constructs():
    html = _md.md_to_html(
        "# Head\n\nSome **bold** and `code`.\n\n- one\n- two\n\n"
        "```\ncode block\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
    )
    assert "<h1>Head</h1>" in html
    assert "<strong>bold</strong>" in html
    assert "<code>code</code>" in html
    assert "<ul>" in html and "<li>one</li>" in html
    assert "<pre><code>" in html
    assert "<table>" in html and "<th>A</th>" in html and "<td>1</td>" in html


def test_md_to_html_escapes():
    assert "&lt;script&gt;" in _md.md_to_html("<script>alert(1)</script>")


def test_md_to_logseq_outline():
    out = _md.md_to_logseq("# Heading\n\nbody line\n", properties={"title": "T", "tags": "x, y"})
    lines = out.splitlines()
    assert lines[0] == "- title:: T"
    assert "- # Heading" in out
    assert "\t- body line" in out


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #
def test_encode_multipart():
    ctype, body = _http.encode_multipart(fields={"a": "1"}, files=[("file", "x.png", b"BYTES")])
    assert ctype.startswith("multipart/form-data; boundary=")
    assert b'name="a"' in body and b'filename="x.png"' in body and b"BYTES" in body


def test_request_json_parses(monkeypatch):
    monkeypatch.setattr(_http, "http_request", lambda *a, **k: (200, b'{"ok": true}'))
    status, parsed = _http.request_json("GET", "https://x")
    assert status == 200 and parsed == {"ok": True}


def test_request_json_non_json(monkeypatch):
    monkeypatch.setattr(_http, "http_request", lambda *a, **k: (500, b"<html>"))
    status, parsed = _http.request_json("GET", "https://x")
    assert status == 500 and parsed == {}


# --------------------------------------------------------------------------- #
# Local sinks
# --------------------------------------------------------------------------- #
def _doc_with_image(tmp_path, title="My Doc"):
    src = tmp_path / "src"
    (src / "images").mkdir(parents=True)
    (src / "images" / "fig.png").write_bytes(b"PNG")
    md = f"# {title}\n\nIntro paragraph.\n\n![cap](images/fig.png)\n"
    md_path = src / "doc.md"
    md_path.write_text(md)
    return ParsedDoc(title=title, markdown=md, source="doc.pdf", modality="pdf",
                     markdown_path=str(md_path))


def test_obsidian_sink_writes_note_and_assets(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT", str(vault))
    res = get_sink("obsidian").deliver(_doc_with_image(tmp_path))
    assert res.ok
    note = vault / "My Doc.md"
    text = note.read_text(encoding="utf-8")
    assert "title: My Doc" in text
    assert (vault / "My Doc.assets" / "fig.png").read_bytes() == b"PNG"
    assert "My Doc.assets/fig.png" in text


def test_logseq_sink_writes_outline_and_assets(tmp_path, monkeypatch):
    graph = tmp_path / "graph"
    (graph / "pages").mkdir(parents=True)
    monkeypatch.setenv("LOGSEQ_GRAPH", str(graph))
    res = get_sink("logseq").deliver(_doc_with_image(tmp_path, title="Note"))
    assert res.ok
    page = (graph / "pages" / "Note.md").read_text(encoding="utf-8")
    assert "title:: Note" in page
    assert (graph / "assets" / "note-fig.png").read_bytes() == b"PNG"
    assert "../assets/note-fig.png" in page


def test_obsidian_missing_vault_dir_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path / "nope"))
    from sinks.base import SinkError
    with pytest.raises(SinkError):
        get_sink("obsidian").deliver(ParsedDoc(title="x", markdown="hi"))


# --------------------------------------------------------------------------- #
# deliver_all orchestration
# --------------------------------------------------------------------------- #
def test_deliver_all_unknown_sink():
    out = deliver_all(ParsedDoc(title="x", markdown="hi"), ["nope"])
    assert out[0].ok is False and "unknown" in out[0].error


def test_deliver_all_missing_config(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT", raising=False)
    out = deliver_all(ParsedDoc(title="x", markdown="hi"), ["obsidian"])
    assert out[0].ok is False and "missing config" in out[0].error


# --------------------------------------------------------------------------- #
# CLI --to integration (core parse mocked, real local sink)
# --------------------------------------------------------------------------- #
def _ok(data):
    return json.dumps({"code": 0, "data": data, "msg": "ok"}).encode()


def test_cli_delivers_to_obsidian(tmp_path, monkeypatch, capsys):
    calls = []

    def fake_http(method, url, *, headers=None, data=None, timeout=60):
        calls.append(url)
        if "/agent/parse/url" in url:
            return 200, _ok({"task_id": "C1"})
        if "/agent/parse/C1" in url:
            return 200, _ok({"state": "done", "markdown_url": "https://cdn/c.md"})
        if "cdn/c.md" in url:
            return 200, b"# Parsed Doc\n\nHello.\n"
        raise AssertionError(url)

    monkeypatch.setattr(mineru, "_http", fake_http)
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT", str(vault))
    monkeypatch.delenv("MINERU_TOKEN", raising=False)

    code = mineru.main([
        "https://x.com/a.pdf", "--output", str(tmp_path / "out"),
        "--to", "obsidian", "--json", "--quiet",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    sink_status = payload["results"][0]["sinks"][0]
    assert sink_status["sink"] == "obsidian" and sink_status["ok"] is True
    assert (vault / "a.md").exists()


def test_cli_list_sinks(capsys):
    code = mineru.main(["--list-sinks"])
    assert code == 0
    out = capsys.readouterr().out
    assert "obsidian" in out and "notion" in out and "feishu" in out
