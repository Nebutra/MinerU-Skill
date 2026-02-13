---
name: mineru
description: Parse PDF into Markdown/JSON/DOCX using MinerU API. Extract text, tables, formulas with OCR support. Use when converting PDF documents, extracting content from scanned papers, or batch processing PDF files.
metadata:
  author: Nebutra
  version: "2.0.0"
  argument-hint: <pdf-file-or-url>
---

# MinerU PDF Parser

Parse PDF documents into structured Markdown using the MinerU API.

## Quick Start

```bash
# Set API token
export MINERU_TOKEN="your-jwt-token"

# Parse single PDF
python mineru_api.py --file ./document.pdf --output ./output/
```

## Features

- **Multi-format Output**: Markdown, JSON, DOCX
- **Formula Recognition**: LaTeX formula extraction
- **Table Extraction**: Structured table parsing
- **OCR Support**: Scanned PDF processing
- **Batch Processing**: Parallel processing with async

## Authentication

Get your free token at: https://open.walab.ai/

```bash
export MINERU_TOKEN="your-token-here"
```
