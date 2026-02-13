# MinerU Skill

 ![GitHub Release](https://img.shields.io/github/v/release/Nebutra/MinerU-Skill?include_prereleases) ![Python](https://img.shields.io/badge/Python-3.8+-blue.svg) ![License](https://img.shields.io/badge/License-MIT-green.svg) ![API](https://img.shields.io/badge/API-MinerU-orange.svg)

![GitHub stars](https://img.shields.io/github/stars/Nebutra/MinerU-Skill?style=social) ![GitHub forks](https://img.shields.io/github/forks/Nebutra/MinerU-Skill?style=social)

**An AI Skill that transforms PDF documents into clean Markdown using MinerU's VLM engine.**

Perfect for knowledge workers, researchers, and anyone who needs to extract structured content from PDFs with support for mathematical formulas, tables, and images.

---

## ⚡ What's New in v2.0

### 🚀 High-Performance Async Engine

| Feature | Before | After |
|---------|--------|-------|
| Concurrency Model | ThreadPoolExecutor | **asyncio + aiohttp** |
| HTTP Library | requests (blocking) | **aiohttp (async)** |
| Connection Management | New per request | **Connection Pool** |
| Max Concurrency | 5-10 workers | **15+ workers** |
| Auto-Retry | Manual | **3x with exponential backoff** |

### 📊 Performance Comparison

```
┌──────────────────────────────────────────────────────────────┐
│  THROUGHPUT: 10 PDF files (~15 pages each)                   │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  v1.0 (Sequential):    ████████████████████  8.5 minutes    │
│                                                              │
│  v2.0 (Async 5):       ████████              3.2 minutes    │
│                                                              │
│  v2.0 (Async 15):      ████                  1.8 minutes    │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## ✨ Features

| Category | Details |
|----------|---------|
| 📄 **PDF Input** | Local files, URLs, batch directories |
| 📝 **Output Format** | Clean Markdown + JSON metadata + Extracted images |
| 🔢 **Math Support** | LaTeX formulas preserved |
| 📊 **Table Extraction** | Markdown tables with structure |
| 🖼️ **Image Extraction** | Auto-saved to `images/` folder |
| ⚡ **Async Processing** | Up to 15x parallel uploads |
| 🔄 **Auto Resume** | Skip already processed files |
| 🛡️ **Error Handling** | 3x retry with exponential backoff |
| 📁 **Direct to Obsidian** | Output to your vault automatically |

---

## 🚀 Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/Nebutra/MinerU-Skill.git
cd MinerU-Skill

# Install dependencies
pip install requests aiohttp
```

### Get Your API Token

1. Visit [MinerU](https://mineru.net/user-center/api-token)
2. Create a free API token
3. Set environment variable:

```bash
export MINERU_TOKEN="your-token-here"
```

**Free Tier:** 2000 pages/day, 200MB max file size

---

## 📖 Usage

### Single File

```bash
python scripts/mineru_v2.py \
  --file ./document.pdf \
  --output ./output/
```

### Batch Directory

```bash
python scripts/mineru_v2.py \
  --dir ./pdfs/ \
  --output ./output/ \
  --workers 10 \
  --resume
```

### Direct to Obsidian

```bash
python scripts/mineru_v2.py \
  --dir ./pdfs/ \
  --output "~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian/MyVault/Notes/" \
  --workers 5 \
  --resume
```

---

## 🎯 Available Scripts

| Script | Description | Best For |
|--------|-------------|----------|
| `mineru_v2.py` | **Recommended** - Async parallel processing | Most use cases |
| `mineru_async.py` | Ultra-high concurrency (15+ workers) | Fast networks |
| `mineru_stable.py` | Sequential with robust retry | Unstable networks |
| `mineru_api.py` | Full-featured with all options | Advanced users |

---

## 📁 Output Structure

```
output/
├── 2024年数学一真题/
│   ├── 2024年数学一真题.md    # Main Markdown file
│   ├── images/                # Extracted images
│   │   ├── image_0_0.png
│   │   └── ...
│   └── content.json           # Metadata
├── 2025年数学一真题/
│   └── ...
└── ...
```

---

## 🔧 CLI Options

```
--dir PATH        Input directory of PDF files
--file PATH       Single PDF file
--output PATH     Output directory (default: ./output/)
--token TOKEN     MinerU API token (or set MINERU_TOKEN env)
--workers N       Concurrent workers (default: 5)
--resume          Skip already processed files
--timeout SEC     Timeout per file (default: 600)
```

---

## 💡 Examples

### 考研数学真题解析

```bash
# Parse 40 exam papers with 10 workers
python scripts/mineru_v2.py \
  --dir ./历年真题/ \
  --output ./解析结果/ \
  --workers 10 \
  --resume

# Result: 40 PDFs → 40 Markdown files with formulas preserved
```

### Research Paper Extraction

```bash
# Parse academic papers
python scripts/mineru_v2.py \
  --dir ./papers/ \
  --output ./extracted/ \
  --workers 5

# Result: LaTeX formulas + tables + figures all preserved
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     USER REQUEST                            │
│         "Parse 100 PDFs from ./docs/"                       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  MINERU SKILL ENGINE                        │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Scanner   │→ │  Scheduler  │→ │   Worker    │         │
│  │ (PDF files) │  │ (asyncio)   │  │ Pool (N)    │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│                            │                                │
│                            ▼                                │
│  ┌─────────────────────────────────────────────────┐       │
│  │           MINERU API CLIENT                      │       │
│  │  • Get upload URL                                │       │
│  │  • Upload to OSS                                 │       │
│  │  • Poll for completion                           │       │
│  │  • Download result                               │       │
│  └─────────────────────────────────────────────────┘       │
│                            │                                │
│                            ▼                                │
│  ┌─────────────────────────────────────────────────┐       │
│  │           OUTPUT PROCESSOR                       │       │
│  │  • Extract ZIP                                   │       │
│  │  • Rename files                                  │       │
│  │  • Organize images                               │       │
│  └─────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     OUTPUT                                  │
│     Markdown + JSON + Images → Obsidian/Notion/etc.        │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎨 Supported Document Types

| Type | Quality | Notes |
|------|---------|-------|
| 📚 Academic Papers | ⭐⭐⭐⭐⭐ | LaTeX formulas preserved |
| 📝 Exam Papers | ⭐⭐⭐⭐⭐ | Perfect for 考研, 高考, etc. |
| 📊 Financial Reports | ⭐⭐⭐⭐ | Tables extracted accurately |
| 📰 News Articles | ⭐⭐⭐⭐⭐ | Clean text extraction |
| 📖 Textbooks | ⭐⭐⭐⭐ | Formulas + diagrams |
| 🗎 Scanned PDFs | ⭐⭐⭐ | Works with OCR enabled |

---

## 🔗 Integration with AI Tools

### Obsidian

Output directly to your vault:

```bash
python scripts/mineru_v2.py \
  --dir ./pdfs/ \
  --output "~/Obsidian/MyVault/" \
  --resume
```

### ClawHub

Install as an OpenClaw skill:

```bash
# Clone to your skills directory
git clone https://github.com/Nebutra/MinerU-Skill.git \
  ~/openclaw-skills/mineru/
```

### MCP (Model Context Protocol)

Use with any MCP-compatible AI:

```json
{
  "mcpServers": {
    "mineru": {
      "command": "python",
      "args": ["/path/to/MinerU-Skill/scripts/mineru_v2.py"]
    }
  }
}
```

---

## 📊 Benchmarks

### Test Environment
- **Hardware:** MacBook Air M1, 16GB RAM
- **Network:** 100Mbps home connection
- **Files:** 10 PDFs, ~15 pages each

### Results

| Configuration | Time | Speed |
|--------------|------|-------|
| Sequential (1 worker) | 8.5 min | 1.2 files/min |
| Parallel (5 workers) | 3.2 min | 3.1 files/min |
| Async (10 workers) | 2.1 min | 4.8 files/min |
| Async (15 workers) | 1.8 min | 5.6 files/min |

---

## 🤝 Contributing

Contributions are welcome! Here's how to help:

1. Fork the repository
2. Create your feature branch (`git checkout -b feat/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: add amazing feature'`)
4. Push to the branch (`git push origin feat/amazing-feature`)
5. Open a Pull Request

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- [MinerU](https://mineru.net/) - Powerful PDF parsing API
- [OpenClaw](https://openclaw.ai/) - AI assistant framework

---

## 📮 Support

- **Issues:** [GitHub Issues](https://github.com/Nebutra/MinerU-Skill/issues)
- **Discussions:** [GitHub Discussions](https://github.com/Nebutra/MinerU-Skill/discussions)

---

<div align="center">

**If you find this useful, consider giving it a ⭐!**

Made with ❤️ by [Nebutra](https://github.com/Nebutra)

</div>
