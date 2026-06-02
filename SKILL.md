---
name: mineru
description: "An AI-Native skill for parsing PDF / Office / image files into clean Markdown with MinerU — a fast, zero-config document parser for AI agents. Works with NO token via the lightweight Agent API and auto-upgrades to the Standard API (token) for large files, batches, and DOCX/HTML/LaTeX export. Use when: (1) Converting PDF/Word/PPT/Excel/image to Markdown, (2) Extracting text, tables, formulas, or running OCR on scanned docs, (3) Batch-parsing a folder in parallel, (4) Piping parsed Markdown straight back to an agent or into Obsidian."
homepage: https://mineru.net
metadata:
  author: Nebutra
  version: "3.3.1"
  argument-hint: <pdf-file-or-url>
  openclaw:
    emoji: "📄"
    requires:
      bins: ["python3"]
---

# MinerU PDF Parser

Parse PDF, Office (Word/PPT/Excel), and image files into clean Markdown — with
LaTeX formulas, tables, images, and OCR. One zero-dependency script, two backends,
automatic routing.

## Zero-config quick start (no token, no install)

```bash
# Parse a local file or URL — the Agent API needs no login
python3 scripts/mineru.py paper.pdf

# Pipe the Markdown straight back to an agent
python3 scripts/mineru.py paper.pdf --stdout

# Machine-readable status for tool pipelines
python3 scripts/mineru.py paper.pdf --json
```

No `pip install`, no API key. The free **Agent API** handles files ≤ 10 MB / ≤ 20 pages.

### Run with uv (zero-install, managed Python)

`scripts/mineru.py` carries [PEP 723](https://peps.python.org/pep-0723/) inline
metadata, so [uv](https://docs.astral.sh/uv/) runs it directly — no venv, no
`pip install`, with a uv-managed interpreter:

```bash
uv run scripts/mineru.py paper.pdf --stdout       # zero-install run
uv run --no-project --with pytest pytest -q       # dev suite via uv
```

## Power mode (token) — large files, batches, extra formats

```bash
export MINERU_TOKEN="..."          # https://mineru.net/apiManage/token

# Parallel batch a directory, resume on re-run
python3 scripts/mineru.py ./pdfs/ --output ./out/ --workers 8 --resume

# Export DOCX/HTML/LaTeX alongside Markdown (auto-routes to the Standard API)
python3 scripts/mineru.py report.pdf --format docx --format latex
```

When a token is set, the tool **auto-routes**: small single files still use the
free Agent API; anything large (> 10 MB / > 20 pages), batched, or needing extra
export formats uses the **Standard API** (≤ 200 MB / ≤ 200 pages). If the Agent
API hits a size/page limit, it auto-escalates to the Standard API.

## Supported modalities

| Modality | Extensions | OCR |
|----------|-----------|-----|
| PDF | `.pdf` | `--ocr` |
| Image | `.png .jpg .jpeg .jp2 .webp .gif .bmp` | built-in |
| Word | `.doc .docx` | — |
| Slides | `.ppt .pptx` | — |
| Sheet | `.xls .xlsx` | — |
| HTML | `.html` (Standard API, `MinerU-HTML` model) | — |

## Common options

```
INPUT...          One or more files, a directory, or a URL
--output, -o      Output directory (default: ./output)
--api             auto | agent | standard   (default: auto)
--model           pipeline | vlm | MinerU-HTML  (default: vlm)
--format          docx | html | latex  (repeatable; forces Standard API)
--lang            OCR/document language (default: ch)
--ocr             Enable OCR for scanned documents
--pages           Page range, e.g. "1-10" or "2,4-6"
--workers, -w     Concurrent submit/upload/download slots (default: 8)
--resume          Skip inputs already parsed
--stdout          Print Markdown to stdout
--json            Print machine-readable status to stdout
--to SINK         Deliver into a content tool (repeatable); --list-sinks to enumerate
--obsidian PATH   Shortcut for --to obsidian with this vault
--engine          cloud | local | auto  (local/auto parse born-digital PDFs offline)
--split           Split oversized PDFs past the page caps, parse parts, merge (needs pypdf)
--chunk           Emit heading-aware RAG chunks (.chunks.json + --json)
--doctor          Environment self-check and exit
```

## MCP server

Expose MinerU over MCP (zero-dependency stdio JSON-RPC) so an MCP host can call it:

```bash
python3 scripts/mineru_mcp.py
```

Tools: `mineru_parse`, `mineru_parse_to` (parse + deliver to sinks), `mineru_list_sinks`.

## Deliver into your tools (`--to`)

Parse once and push the Markdown into content tools via each one's official path:

```bash
python3 scripts/mineru.py paper.pdf --to obsidian --to notion --to feishu
```

Targets: `obsidian` `logseq` `siyuan` `notion` `linear` `yuque` `coda` `slack`
`feishu` `confluence` `onenote` `ticktick` `dingtalk` `airtable` `wecom` (all
zero-dependency), plus `roam` and `wps` via optional extras. Each reads its config
from env vars (run `--list-sinks`). Per-target auth, fidelity, and image notes:
[references/integrations.md](references/integrations.md).

## Output

```
output/
└── document-name/
    ├── document-name.md    # clean Markdown
    └── images/             # extracted figures (Standard API)
```

## Performance (real, measured)

End-to-end latency for the official demo PDF via the free Agent API:
**cold ≈ 14 s · warm ≈ 13 s** (submit → poll → download). Batches scale with
`--workers`. Numbers come from the no-mock live benchmark in `tests/test_live.py`.

## Testing

```bash
python3 -m pytest                      # fast unit suite (offline)
MINERU_LIVE=1 python3 -m pytest -m live -s   # real API + benchmark (no mocks)
```

## API Reference

See [references/api_reference.md](references/api_reference.md). Official docs:
https://mineru.net/apiManage/docs · Token: https://mineru.net/apiManage/token
