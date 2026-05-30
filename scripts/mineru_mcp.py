#!/usr/bin/env python3
"""Zero-dependency MCP server (stdio) for MinerU Skill.

Speaks newline-delimited JSON-RPC 2.0 over stdin/stdout using only the standard
library, so an MCP host (Claude, Cursor, Windsurf, ...) can call MinerU. Register:

    {"command": "python3", "args": ["scripts/mineru_mcp.py"]}

Tools: ``mineru_parse``, ``mineru_parse_to``, ``mineru_list_sinks``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mineru  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "mineru", "version": mineru.__version__}

TOOLS = [
    {
        "name": "mineru_parse",
        "description": "Parse a PDF / Office / image file or URL into clean Markdown via MinerU.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "Local file path or http(s) URL"},
                "output_dir": {"type": "string", "description": "Where to write output (default ./output)"},
                "api": {"type": "string", "enum": ["auto", "agent", "standard"]},
                "engine": {"type": "string", "enum": ["cloud", "local", "auto"]},
                "ocr": {"type": "boolean"},
                "lang": {"type": "string"},
            },
            "required": ["input"],
        },
    },
    {
        "name": "mineru_parse_to",
        "description": "Parse a document and deliver the Markdown into content tools (Obsidian, Notion, Feishu, ...).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "input": {"type": "string"},
                "sinks": {"type": "array", "items": {"type": "string"}, "description": "Sink names, e.g. ['obsidian','notion']"},
                "output_dir": {"type": "string"},
            },
            "required": ["input", "sinks"],
        },
    },
    {
        "name": "mineru_list_sinks",
        "description": "List available delivery targets and their required environment variables.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class MethodNotFound(Exception):
    pass


def _text_result(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _tool_parse(args: dict) -> dict:
    opts = mineru.ParseOptions(is_ocr=bool(args.get("ocr")), language=args.get("lang", "ch"))
    token = os.environ.get("MINERU_TOKEN")
    output_dir = Path(args.get("output_dir") or "./output")
    res = mineru.process_one(
        args["input"], opts, token=token, output_dir=output_dir,
        api=args.get("api", "auto"), engine=args.get("engine", "cloud"),
    )
    if res.state == "done":
        return _text_result(res.markdown or "")
    return _text_result(f"Parse failed: {res.error}", is_error=True)


def _tool_parse_to(args: dict) -> dict:
    opts = mineru.ParseOptions()
    token = os.environ.get("MINERU_TOKEN")
    output_dir = Path(args.get("output_dir") or "./output")
    res = mineru.process_one(args["input"], opts, token=token, output_dir=output_dir)
    if res.state != "done":
        return _text_result(f"Parse failed: {res.error}", is_error=True)
    sinks = mineru._load_sinks()
    if sinks is None:
        return _text_result("Sinks package unavailable.", is_error=True)
    doc = sinks.ParsedDoc(title=res.name, markdown=res.markdown, source=res.source,
                          modality=res.modality, markdown_path=res.markdown_path)
    outcomes = [o.to_status() for o in sinks.deliver_all(doc, args["sinks"])]
    any_fail = any(not o["ok"] for o in outcomes)
    return _text_result(json.dumps({"name": res.name, "deliveries": outcomes}, ensure_ascii=False, indent=2),
                        is_error=any_fail)


def _tool_list_sinks(_args: dict) -> dict:
    sinks = mineru._load_sinks()
    if sinks is None:
        return _text_result("Sinks package unavailable.", is_error=True)
    listing = [{"name": n, "label": sinks.get_sink(n).label, "requires": list(sinks.get_sink(n).requires)}
               for n in sinks.sink_names()]
    return _text_result(json.dumps(listing, ensure_ascii=False, indent=2))


_TOOL_HANDLERS = {
    "mineru_parse": _tool_parse,
    "mineru_parse_to": _tool_parse_to,
    "mineru_list_sinks": _tool_list_sinks,
}


def _route(method: str, params: dict):
    if method == "initialize":
        return {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return _text_result(f"Unknown tool: {name}", is_error=True)
        try:
            return handler(params.get("arguments") or {})
        except Exception as exc:  # noqa: BLE001 - report as a tool error, never crash the server
            return _text_result(f"{type(exc).__name__}: {exc}", is_error=True)
    raise MethodNotFound(method)


def dispatch(request: dict):
    """Handle one JSON-RPC request dict; return a response dict, or None for notifications."""
    is_notification = "id" not in request
    req_id = request.get("id")
    try:
        result = _route(request.get("method"), request.get("params") or {})
    except MethodNotFound as exc:
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {exc}"}}
    except Exception as exc:  # noqa: BLE001
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(exc)}}
    if is_notification:
        return None
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def serve(stdin=None, stdout=None) -> None:
    """Read newline-delimited JSON-RPC from stdin, write responses to stdout."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue
        response = dispatch(request)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()


def main() -> int:
    serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
