"""Tests for the stdio MCP server (JSON-RPC dispatch + tool calls)."""

import io
import json

import mineru
import mineru_mcp


def _result(req):
    return mineru_mcp.dispatch(req)


def test_initialize():
    resp = _result({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "mineru"
    assert "protocolVersion" in resp["result"]


def test_tools_list():
    resp = _result({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {"mineru_parse", "mineru_parse_to", "mineru_list_sinks"}


def test_notification_returns_no_response():
    assert _result({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unknown_method_errors():
    resp = _result({"jsonrpc": "2.0", "id": 3, "method": "bogus"})
    assert resp["error"]["code"] == -32601


def _fake_done(markdown="# Hi\n"):
    res = mineru.ParseResult(name="doc", source="x")
    res.state = "done"
    res.markdown = markdown
    res.markdown_path = "/tmp/doc.md"
    res.modality = "pdf"
    return res


def test_tool_parse_returns_markdown(monkeypatch):
    monkeypatch.setattr(mineru, "process_one", lambda *a, **k: _fake_done("# Parsed\n"))
    resp = _result({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {"name": "mineru_parse", "arguments": {"input": "a.pdf"}}})
    result = resp["result"]
    assert result["isError"] is False
    assert result["content"][0]["text"] == "# Parsed\n"


def test_tool_parse_failure_is_error(monkeypatch):
    failed = mineru.ParseResult(name="doc", source="x")
    failed.state = "failed"
    failed.error = "boom"
    monkeypatch.setattr(mineru, "process_one", lambda *a, **k: failed)
    resp = _result({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                    "params": {"name": "mineru_parse", "arguments": {"input": "a.pdf"}}})
    assert resp["result"]["isError"] is True
    assert "boom" in resp["result"]["content"][0]["text"]


def test_tool_list_sinks():
    resp = _result({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                    "params": {"name": "mineru_list_sinks", "arguments": {}}})
    listing = json.loads(resp["result"]["content"][0]["text"])
    names = {item["name"] for item in listing}
    assert "obsidian" in names and "notion" in names


def test_unknown_tool_is_error():
    resp = _result({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                    "params": {"name": "nope", "arguments": {}}})
    assert resp["result"]["isError"] is True


def test_serve_loop(monkeypatch):
    monkeypatch.setattr(mineru, "process_one", lambda *a, **k: _fake_done("# X\n"))
    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "mineru_parse", "arguments": {"input": "a.pdf"}}}) + "\n"
    )
    stdout = io.StringIO()
    mineru_mcp.serve(stdin=stdin, stdout=stdout)
    lines = [json.loads(ln) for ln in stdout.getvalue().splitlines() if ln.strip()]
    assert len(lines) == 2  # initialize + tools/call (notification produced nothing)
    assert lines[0]["id"] == 1
    assert lines[1]["result"]["content"][0]["text"] == "# X\n"
