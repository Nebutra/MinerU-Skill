"""Tests for heading-aware RAG chunking."""

import json

import chunking
import mineru


def test_splits_by_heading_with_breadcrumb():
    md = "# Title\n\nIntro paragraph.\n\n## Section A\n\nBody of A.\n\n## Section B\n\nBody of B.\n"
    chunks = chunking.chunk_markdown(md, source="paper.pdf")
    headings = [c["heading"] for c in chunks]
    assert "Title" in headings[0]
    assert any(h == "Title > Section A" for h in headings)
    assert any(h == "Title > Section B" for h in headings)
    # ids are stable + sequential
    assert [c["index"] for c in chunks] == list(range(len(chunks)))
    assert all(c["id"].startswith("paper-") for c in chunks)
    assert all(c["source"] == "paper.pdf" for c in chunks)


def test_size_split_keeps_chunks_under_max():
    big = "# H\n\n" + ("word " * 1000)
    chunks = chunking.chunk_markdown(big, max_chars=500)
    assert len(chunks) > 1
    assert all(c["chars"] <= 500 for c in chunks)


def test_nested_heading_breadcrumb():
    md = "# A\n\n## B\n\n### C\n\ndeep text\n"
    chunks = chunking.chunk_markdown(md)
    assert any(c["heading"] == "A > B > C" for c in chunks)


def test_heading_pop_on_same_or_shallower_level():
    md = "# A\n\n## B\n\ntext b\n\n## C\n\ntext c\n"
    chunks = chunking.chunk_markdown(md)
    # C must be a sibling of B (A > C), not nested under B
    assert any(c["heading"] == "A > C" for c in chunks)
    assert not any(c["heading"] == "A > B > C" for c in chunks)


def test_empty_and_no_heading():
    assert chunking.chunk_markdown("") == []
    chunks = chunking.chunk_markdown("just plain text, no headings")
    assert len(chunks) == 1 and chunks[0]["heading"] == ""


def _ok(data):
    return json.dumps({"code": 0, "data": data, "msg": "ok"}).encode()


def test_cli_chunk_emits_sidecar_and_json(tmp_path, monkeypatch, capsys):
    def fake_http(method, url, *, headers=None, data=None, timeout=60):
        if "/agent/parse/url" in url:
            return 200, _ok({"task_id": "K1"})
        if "/agent/parse/K1" in url:
            return 200, _ok({"state": "done", "markdown_url": "https://cdn/k.md"})
        if "cdn/k.md" in url:
            return 200, b"# Title\n\nIntro paragraph.\n\n## Section\n\nBody text.\n"
        raise AssertionError(url)

    monkeypatch.setattr(mineru, "_http", fake_http)
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    out = tmp_path / "out"

    code = mineru.main(["https://x.com/a.pdf", "--output", str(out), "--chunk", "--json", "--quiet"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    chunks = payload["results"][0]["chunks"]
    assert len(chunks) >= 2
    assert any("Section" in c["heading"] for c in chunks)
    sidecar = out / "a" / "a.chunks.json"
    assert sidecar.exists()
    assert json.loads(sidecar.read_text(encoding="utf-8"))[0]["id"].startswith("https")
