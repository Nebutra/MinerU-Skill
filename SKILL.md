---
name: mineru
description: "Parse PDFs into clean Markdown using MinerU's VLM engine. Use when: (1) Converting PDF to Markdown, (2) Extracting text/tables/formulas from PDFs, (3) Batch processing multiple PDFs, (4) Saving parsed content to Obsidian or knowledge bases. Supports LaTeX formulas, tables, images, and async parallel processing."
homepage: https://mineru.net
metadata:
  openclaw:
    emoji: "📄"
    requires:
      bins: ["python3"]
      env: ["MINERU_TOKEN"]
    install:
      - id: pip
        kind: pip
        packages: ["requests", "aiohttp"]
        label: "Install Python dependencies (pip)"
---

# MinerU PDF Parser

Parse PDF documents into Markdown with LaTeX formula preservation, table extraction, and image handling.

## Setup

Get API token from https://mineru.net/user-center/api-token (free: 2000 pages/day, 200MB max):

```bash
export MINERU_TOKEN="your-token-here"
```

## Commands

### Single File

```bash
python3 scripts/mineru_v2.py --file ./document.pdf --output ./output/
```

### Batch Directory with Resume

```bash
python3 scripts/mineru_v2.py \
  --dir ./pdfs/ \
  --output ./output/ \
  --workers 10 \
  --resume
```

### Direct to Obsidian

```bash
python3 scripts/mineru_v2.py \
  --dir ./pdfs/ \
  --output "~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian/VaultName/" \
  --resume
```

## CLI Options

```
--dir PATH        Input directory of PDFs
--file PATH       Single PDF file  
--output PATH     Output directory (default: ./output/)
--workers N       Concurrent workers (default: 5, max: 15)
--resume          Skip already processed files
--timeout SEC     Per-file timeout (default: 600)
```

## Script Selection

| Script | Use When |
|--------|----------|
| `mineru_v2.py` | Default - async parallel |
| `mineru_async.py` | Fast network, need 15+ workers |
| `mineru_stable.py` | Unstable network, sequential |

## Output

```
output/
├── document-name/
│   ├── document-name.md    # Main Markdown
│   ├── images/             # Extracted images
│   └── content.json        # Metadata
```

## Supported Documents

- Academic papers (LaTeX formulas)
- Exam papers (考研, 高考)
- Financial reports (tables)
- Textbooks (formulas + diagrams)
- Scanned PDFs (enable OCR)

## Performance

| Workers | Speed |
|---------|-------|
| 1 (sequential) | 1.2 files/min |
| 5 | 3.1 files/min |
| 15 | 5.6 files/min |

## Error Handling

- 3x auto-retry with exponential backoff
- Use `--resume` to skip completed files
- Check logs for failed files

## API Reference

For detailed API documentation, see [references/api_reference.md](references/api_reference.md).
