# MinerU Skill

![GitHub Release](https://img.shields.io/github/v/release/Nebutra/MinerU-Skill)
![License](https://img.shields.io/github/license/Nebutra/MinerU-Skill)

Parse PDF documents into Markdown/JSON/DOCX using MinerU API. Extract text, tables, formulas with OCR support.

## Features

- **Multi-format Output**: Markdown, JSON, DOCX
- **Formula Recognition**: LaTeX formula extraction
- **Table Extraction**: Structured table parsing
- **OCR Support**: Scanned PDF processing
- **Batch Processing**: Parallel processing with async

## Installation

### Vercel Skills (Recommended)

```bash
npx skills add Nebutra/MinerU-Skill
```

### Python

```bash
pip install -r requirements.txt
```

## Quick Start

```bash
# Set API token
export MINERU_TOKEN="your-jwt-token"

# Parse single PDF
python scripts/mineru_api.py --file ./document.pdf --output ./output/

# Parse from URL
python scripts/mineru_api.py --url "https://example.com/doc.pdf" --output ./output/

# Batch process directory
python scripts/mineru_api.py --dir ./pdfs/ --output ./output/
```

## Authentication

Get your free token at: https://open.walab.ai/

```bash
export MINERU_TOKEN="your-token-here"
```

## Limits

- Free tier: 2000 pages/day
- Max file: 200MB
- Max pages: 600/page

## Supported Agents

- OpenCode
- Claude Code
- Codex
- Cursor
- And 35+ more via Vercel Skills

## License

MIT
