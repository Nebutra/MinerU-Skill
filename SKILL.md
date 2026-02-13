# MinerU Skill

AI-powered PDF to Markdown conversion using MinerU's VLM engine.

## What This Skill Does

When you ask the AI to:
- "Parse this PDF into Markdown"
- "Extract text from these PDFs"
- "Convert PDF to Markdown for Obsidian"

This skill automatically:
1. Uploads PDFs to MinerU API
2. Waits for VLM-powered parsing
3. Downloads structured Markdown with LaTeX formulas preserved
4. Extracts images and tables
5. Organizes output for your knowledge base

## Quick Start

```bash
# Install skill
git clone https://github.com/Nebutra/MinerU-Skill.git ~/openclaw-skills/mineru/

# Set API token
export MINERU_TOKEN="your-token-here"  # Get from https://mineru.net/user-center/api-token
```

## Usage Examples

### Single File
```
请把这个 PDF 解析成 Markdown: ./document.pdf
```

### Batch Directory
```
把这 100 个 PDF 都解析了，输出到 Obsidian: ./papers/ → ~/Obsidian/MyVault/
```

### Direct to Obsidian
```
解析这些试卷，直接保存到我的考研 Vault 里
```

## Scripts

| Script | Use Case |
|--------|----------|
| `mineru_v2.py` | Default - async parallel (recommended) |
| `mineru_async.py` | High concurrency (15+ workers) |
| `mineru_stable.py` | Robust sequential processing |

## CLI Reference

```bash
python scripts/mineru_v2.py \
  --dir <pdf-directory> \
  --output <output-path> \
  --workers <concurrency> \
  --resume  # Skip processed files
```

## Output Structure

```
output/
├── document-name/
│   ├── document-name.md    # Main Markdown
│   ├── images/             # Extracted images
│   └── content.json        # Metadata
```

## Features

- 🔢 LaTeX formula preservation
- 📊 Table extraction
- 🖼️ Image extraction
- ⚡ Parallel processing (up to 15x)
- 🔄 Auto resume
- 📁 Direct to Obsidian output

## Requirements

- Python 3.8+
- `requests`, `aiohttp`
- MinerU API token (free: 2000 pages/day)

## Get API Token

1. Visit https://mineru.net/user-center/api-token
2. Create free token
3. Set: `export MINERU_TOKEN="your-token"`
