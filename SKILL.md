# MinerU Skill

MinerU PDF Parser - Parse PDFs into clean Markdown using MinerU's VLM engine.

## Quick Start

```bash
# Set API token
export MINERU_TOKEN="your-token-here"

# Parse single file
python scripts/mineru_v2.py --file ./document.pdf --output ./output/

# Parse directory
python scripts/mineru_v2.py --dir ./pdfs/ --output ./output/ --workers 10 --resume
```

## Get API Token

1. Visit https://mineru.net/user-center/api-token
2. Create a free API token
3. Set as environment variable: `export MINERU_TOKEN="..."`

## Options

- `--dir PATH` - Input directory of PDFs
- `--file PATH` - Single PDF file
- `--output PATH` - Output directory (default: ./output/)
- `--workers N` - Concurrent workers (default: 5)
- `--resume` - Skip already processed files
- `--timeout SEC` - Timeout per file (default: 600)

## Scripts

| Script | Description |
|--------|-------------|
| `mineru_v2.py` | Recommended - Async parallel |
| `mineru_async.py` | Ultra-high concurrency |
| `mineru_stable.py` | Sequential, robust |
| `mineru_api.py` | Full-featured |
