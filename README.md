# MinerU Skill

[![GitHub Release](https://img.shields.io/github/v/release/Nebutra/MinerU-Skill?include_prereleases)](https://github.com/Nebutra/MinerU-Skill/releases) [![Python](https://img.shields.io/badge/Python-3.8+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/) [![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE) [![ClawHub](https://img.shields.io/badge/ClawHub-Available-purple.svg)](https://clawhub.com)

[![GitHub Stars](https://img.shields.io/github/stars/Nebutra/MinerU-Skill?style=social)](https://github.com/Nebutra/MinerU-Skill/stargazers) [![GitHub Forks](https://img.shields.io/github/forks/Nebutra/MinerU-Skill?style=social)](https://github.com/Nebutra/MinerU-Skill/network/members)

**An AI Skill that transforms PDF documents into clean Markdown using MinerU's VLM engine.**

Tell your AI assistant: *"Parse these PDFs into Markdown"* and it handles everything.

**[中文文档](README_CN.md)** | **English**

---

## 🤖 What is a Skill?

A **Skill** is an AI capability package that extends your AI assistant's abilities. When you ask the AI to do something, it automatically:

1. **Recognizes** the task from your natural language
2. **Activates** the appropriate skill
3. **Executes** the task using the skill's tools
4. **Delivers** results back to you

### Example Conversation

```
You: 解析这些考研数学真题 PDF 到我的 Obsidian

AI: 📚 发现 40 个 PDF 文件
    ⏳ 开始并行解析 (5 workers)...
    ✅ 1993年考研数学（一）真题 → Markdown
    ✅ 1994年考研数学（一）真题 → Markdown
    ...
    ✅ 完成！已保存到 Obsidian/考研/数学一/
```

---

## 🚀 Install as Skill

### OpenClaw

```bash
# Clone to your skills directory
git clone https://github.com/Nebutra/MinerU-Skill.git ~/openclaw-skills/mineru/

# Set API token
export MINERU_TOKEN="your-token-here"  # Get from https://mineru.net/user-center/api-token
```

### ClawHub

```bash
# Install via clawhub CLI
clawhub install mineru
```

### Claude Code / Cursor / Windsurf

```bash
# Clone to AI skills folder
git clone https://github.com/Nebutra/MinerU-Skill.git ~/.claude/skills/mineru/
```

---

## 💬 Usage Examples

### Single File

```
把 ./document.pdf 解析成 Markdown
```

### Batch Directory

```
解析 ./papers/ 目录下的所有 PDF，输出到 ./output/
```

### Direct to Obsidian

```
把这些 PDF 解析后直接保存到我的 Obsidian Vault
```

### Chinese Example

```
解析 1987-2025 年考研数学真题，保存到 Obsidian/考研/数学一/
用 10 个并发，跳过已处理的文件
```

---

## ⚡ Features

| Feature | Description |
|---------|-------------|
| 📄 **PDF Input** | Local files, URLs, batch directories |
| 📝 **Output** | Markdown + JSON metadata + Images |
| 🔢 **LaTeX** | Math formulas preserved |
| 📊 **Tables** | Structure extraction |
| 🖼️ **Images** | Auto-extracted to `images/` |
| ⚡ **Async** | 15x parallel uploads |
| 🔄 **Resume** | Skip processed files |
| 📁 **Obsidian** | Direct vault output |

---

## 🛠️ CLI Reference

You can also use directly via CLI:

```bash
# Single file
python scripts/mineru_v2.py --file ./doc.pdf --output ./output/

# Batch with resume
python scripts/mineru_v2.py \
  --dir ./pdfs/ \
  --output ~/Obsidian/MyVault/ \
  --workers 10 \
  --resume
```

| Option | Description |
|--------|-------------|
| `--dir PATH` | Input directory |
| `--file PATH` | Single file |
| `--output PATH` | Output directory |
| `--workers N` | Concurrency (default: 5) |
| `--resume` | Skip processed files |
| `--token TOKEN` | API token |

---

## 📁 Output Structure

```
output/
├── document-name/
│   ├── document-name.md    # Main Markdown
│   ├── images/             # Extracted images
│   │   ├── image_0_0.png
│   │   └── ...
│   └── content.json        # Metadata
└── ...
```

---

## 📊 Performance

**Test:** 10 PDFs, ~15 pages each (MacBook Air M1)

| Configuration | Time | Speed |
|--------------|------|-------|
| Sequential | 8.5 min | 1.2 files/min |
| Async (5 workers) | 3.2 min | 3.1 files/min |
| Async (15 workers) | 1.8 min | 5.6 files/min |

---

## 🔑 Get API Token

1. Visit [MinerU](https://mineru.net/user-center/api-token)
2. Create free API token
3. Set environment:

```bash
export MINERU_TOKEN="your-token-here"
```

**Free Tier:** 2000 pages/day, 200MB max file

---

## ⭐ Star History

<a href="https://www.star-history.com/#Nebutra/MinerU-Skill&type=timeline&legend=bottom-right">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=Nebutra/MinerU-Skill&type=timeline&theme=dark&legend=bottom-right" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=Nebutra/MinerU-Skill&type=timeline&legend=bottom-right" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=Nebutra/MinerU-Skill&type=timeline&legend=bottom-right" />
 </picture>
</a>

---

## 🏗️ Skill Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    USER REQUEST                             │
│      "Parse these PDFs to Markdown"                         │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    AI ASSISTANT                             │
│  • Recognizes PDF parsing task                             │
│  • Activates MinerU skill                                  │
│  • Reads SKILL.md for instructions                         │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  MINERU SKILL ENGINE                        │
│  Scanner ──► Scheduler ──► Worker Pool (N workers)         │
│                           │                                 │
│                           ▼                                 │
│  API: Get URL ──► Upload ──► Poll ──► Download             │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                      OUTPUT                                 │
│     Markdown + JSON + Images ──► Obsidian/Files            │
└─────────────────────────────────────────────────────────────┘
```

---

## 🤝 Contributing

1. Fork → Branch → Commit → Push → PR

---

## 📝 License

MIT License - see [LICENSE](LICENSE)

---

## 🙏 Acknowledgments

- [MinerU](https://mineru.net/) - PDF parsing API
- [OpenClaw](https://openclaw.ai/) - AI skill framework
- [ClawHub](https://clawhub.com) - Skill marketplace

---

<div align="center">

**If this skill helps you, give it a ⭐!**

Made with ❤️ by [Nebutra](https://github.com/Nebutra)

</div>
