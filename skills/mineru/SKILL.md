---
name: mineru
description: An AI-Native skill for parsing PDF / Office / image files into Markdown with MinerU — a fast, zero-config document parser for AI agents. Works with NO token via the Agent API and auto-upgrades to the Standard API (token) for large files, batches, and DOCX/HTML/LaTeX export. Use when converting PDF/Word/PPT/Excel/image documents, extracting text/tables/formulas, running OCR, or batch processing.
metadata:
  author: Nebutra
  version: "3.3.1"
  argument-hint: <pdf-file-or-url>
---

# MinerU PDF Parser

Parse PDF, Office, and image documents into structured Markdown via the MinerU API.

## Quick Start

```bash
# Zero-config: no token, no install (free Agent API)
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mineru.py" ./document.pdf --output ./output/

# Pipe Markdown back to an agent
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mineru.py" ./document.pdf --stdout

# Power mode: token unlocks large files / batch / extra formats
export MINERU_TOKEN="..."   # https://mineru.net/apiManage/token
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mineru.py" ./pdfs/ --output ./output/ --workers 8 --resume
```

## Features

- **Auto-routing**: free Agent API by default, auto-upgrades to the Standard API (token) for large/batch/extra-format jobs
- **Multi-modal**: PDF, images, Word, PPT, Excel, HTML
- **High-performance OCR**: `--ocr` with language selection (`--lang`)
- **Formula & table recognition**: LaTeX formulas, structured tables
- **Multi-format export**: Markdown (default), plus DOCX / HTML / LaTeX
- **AI-Native output**: `--stdout` (Markdown) and `--json` (machine status)
- **Batch + resume**: parallel workers with `--resume`
- **Zero dependencies**: standard library only

## Authentication

A token is **optional** — the Agent API works without one. Set a token to unlock
the Standard API (≤ 200 MB / ≤ 200 pages, batch, DOCX/HTML/LaTeX):

```bash
export MINERU_TOKEN="your-token-here"   # https://mineru.net/apiManage/token
```

Official API docs: https://mineru.net/apiManage/docs
