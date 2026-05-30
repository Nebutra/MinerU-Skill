<p align="center">
  <img src="assets/mineru-skill.jpg" alt="MinerU Skill — AI-Native document parsing for the AI-agent era: PDF, Office, images, formulas & tables in; clean Markdown out to your agents, terminal, and the knowledge & content tools you already use" width="100%">
</p>

# MinerU Skill

[![GitHub Release](https://img.shields.io/github/v/release/Nebutra/MinerU-Skill?include_prereleases)](https://github.com/Nebutra/MinerU-Skill/releases) [![Python](https://img.shields.io/badge/Python-3.8+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/) [![Zero Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](requirements.txt) [![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE) [![ClawHub](https://img.shields.io/badge/ClawHub-Available-purple.svg)](https://clawhub.com)

[![GitHub Stars](https://img.shields.io/github/stars/Nebutra/MinerU-Skill?style=social)](https://github.com/Nebutra/MinerU-Skill/stargazers) [![GitHub Forks](https://img.shields.io/github/forks/Nebutra/MinerU-Skill?style=social)](https://github.com/Nebutra/MinerU-Skill/network/members)

**An AI-Native document parser built for AI agents** — turn PDF, Office & image files into clean Markdown with _zero_ API key, _zero_ install, and fast parallel batches.

**[中文文档](README_CN.md)** | **English**

---

## ⚡ Try it in 5 seconds (no signup, no token, no pip install)

```bash
python3 scripts/mineru.py https://cdn-mineru.openxlab.org.cn/demo/example.pdf --stdout
```

Prefer [uv](https://docs.astral.sh/uv/)? The script ships [PEP 723](https://peps.python.org/pep-0723/)
inline metadata, so uv runs it with a managed Python and zero install:

```bash
uv run scripts/mineru.py https://cdn-mineru.openxlab.org.cn/demo/example.pdf --stdout
```

That's it. No account. No API key. No dependencies. The free **Agent API** parses
the PDF and streams clean Markdown straight to your terminal — or to your AI agent.

> Need more power? `export MINERU_TOKEN=...` and the same command auto-upgrades to
> the **Standard API** for 200 MB / 200-page files, parallel batches, and DOCX/HTML/LaTeX export.

---

## 🤔 Why not just call MinerU directly?

| | Raw MinerU API / scripts | **MinerU Skill** |
|---|---|---|
| **Start with no token** | ❌ token required | ✅ free Agent API, zero-config |
| **Backend selection** | 🤷 you pick & wire it | ✅ **auto-routes** Agent ⇄ Standard |
| **Install footprint** | `requests` + `aiohttp` | ✅ **zero deps** (stdlib only) |
| **Agent-friendly output** | files only | ✅ `--stdout` Markdown · `--json` status |
| **Modalities** | DIY per format | ✅ PDF · image · Word · PPT · Excel · HTML |
| **Batch + resume** | hand-rolled | ✅ `--workers` + `--resume` built in |
| **Bad-token errors** | cryptic `code None` | ✅ clear "token expired → refresh here" |
| **Obsidian export** | — | ✅ `--obsidian /path/to/vault` |

Built for the **AI-Agent era**: an agent can run it instantly, get Markdown on stdout,
and never touch a config file.

---

## 🚀 Install as a Skill (Claude Code, Codex, Cursor & 35+ agents)

### Vercel Skills (recommended)

```bash
npx skills add Nebutra/MinerU-Skill
```
Supported: Claude Code, Antigravity, Codex, Cursor, OpenClaw, Hermes Agent — and 35+ more.

### OpenClaw

```bash
git clone https://github.com/Nebutra/MinerU-Skill.git ~/openclaw-skills/mineru/
# No token needed to start. Optional: export MINERU_TOKEN=...  (https://mineru.net/apiManage/token)
```

### ClawHub

```bash
clawhub install mineru
```

### Claude Code / Cursor / Windsurf

```bash
git clone https://github.com/Nebutra/MinerU-Skill.git ~/.claude/skills/mineru/
```

---

## 💬 Talk to your AI

```
You: 解析这些考研数学真题 PDF 到我的 Obsidian

AI: 📚 1 input(s) · workers=8 · token set
    ✅ [agent/pdf] 1993年考研数学（一）真题 (13.9s)
    ✅ [standard/pdf] 2024年考研数学（一）真题 (28.4s)   ← auto-upgraded (large file)
    ...
    📁 saved to Obsidian/考研/数学一/
```

```
把 ./papers/ 目录下所有 PDF 并行解析，跳过已处理的，直接存到 Obsidian
```

---

## 🧩 Supported formats — PDF, Word, PPT, Excel, image & HTML

| Modality | Extensions | OCR |
|----------|-----------|-----|
| 📄 PDF | `.pdf` | `--ocr` |
| 🖼️ Image | `.png .jpg .jpeg .jp2 .webp .gif .bmp` | built-in |
| 📝 Word | `.doc .docx` | — |
| 📊 Slides | `.ppt .pptx` | — |
| 📈 Sheet | `.xls .xlsx` | — |
| 🌐 HTML | `.html` (Standard, `MinerU-HTML`) | — |

LaTeX formulas, structured tables, and extracted images are preserved.

---

## 🛠️ CLI reference

```bash
# Zero-config single file or URL
python3 scripts/mineru.py paper.pdf

# Pipe Markdown back to an agent / capture machine status
python3 scripts/mineru.py paper.pdf --stdout
python3 scripts/mineru.py paper.pdf --json

# Parallel batch a directory, resume on re-run, copy into Obsidian
export MINERU_TOKEN=...
python3 scripts/mineru.py ./pdfs/ --output ./out/ --workers 8 --resume \
  --obsidian "~/Obsidian/MyVault/"

# Scanned docs with OCR; export extra formats (auto-routes to Standard API)
python3 scripts/mineru.py scan.pdf --ocr --lang en --format docx --format latex
```

| Option | Description |
|--------|-------------|
| `INPUT...` | File(s), a directory, or a URL |
| `--output, -o` | Output directory (default `./output`) |
| `--api` | `auto` · `agent` · `standard` (default `auto`) |
| `--model` | `pipeline` · `vlm` · `MinerU-HTML` (default `vlm`) |
| `--format` | `docx` · `html` · `latex` (repeatable; forces Standard API) |
| `--ocr` / `--lang` | Enable OCR / set language (default `ch`) |
| `--pages` | Page range, e.g. `1-10` or `2,4-6` |
| `--workers, -w` | Concurrent inputs (default 4) |
| `--resume` | Skip inputs already parsed |
| `--stdout` / `--json` | Markdown to stdout / machine status to stdout |
| `--to SINK` | Deliver into a content tool (repeatable) — see below |
| `--obsidian PATH` | Shortcut for `--to obsidian` with this vault |
| `--list-sinks` | List delivery targets and their required env vars |

---

## 🔌 Deliver anywhere (`--to`)

Parse once, push straight into your tools using each one's **official** ingestion
path (no hacky converters). Fan out to several at once:

```bash
python3 scripts/mineru.py paper.pdf --to obsidian --to notion --to slack
```

| | Tools | `--to` |
|---|---|---|
| 📓 Notes (local) | Obsidian · Logseq · SiYuan | `obsidian` `logseq` `siyuan` |
| 🌐 Docs / Wiki | Notion · Confluence · OneNote · Coda · Yuque 语雀 · Feishu 飞书 | `notion` `confluence` `onenote` `coda` `yuque` `feishu` |
| 💬 Chat / Tasks | Slack · DingTalk 钉钉 · WeCom 企业微信 · TickTick 滴答 · Linear · Airtable | `slack` `dingtalk` `wecom` `ticktick` `linear` `airtable` |
| 🧩 Optional (extras) | Roam · WPS 金山文档 | `roam` `wps` |

Each target uses its native Markdown path where one exists (Obsidian, Logseq,
SiYuan, Linear, Yuque, Coda, Feishu, TickTick) or a faithful conversion where the
tool requires it (Notion blocks; Confluence/OneNote HTML; Roam outline; WPS DOCX).
**15 targets are zero-dependency**; Roam & WPS lazy-load a library only when used
(`pip install "mineru-skill[roam]" "mineru-skill[wps]"`). Full per-target auth,
fidelity, and image notes are in
**[references/integrations.md](references/integrations.md)**. Run
`python3 scripts/mineru.py --list-sinks` to see the required env vars.

---

## 📁 Output structure

```
output/
└── document-name/
    ├── document-name.md    # clean Markdown
    └── images/             # extracted figures (Standard API)
```

---

## 📊 Performance (real, no-mock benchmark)

End-to-end latency for the official demo PDF via the **free Agent API**
(submit → poll → download), measured by `tests/test_live.py`:

| Run | Latency |
|-----|---------|
| Cold | ~14 s |
| Warm | ~13 s |
| p50 | ~14 s |

Batches scale with `--workers`. Reproduce it yourself:

```bash
MINERU_LIVE=1 python3 -m pytest -m live -s
```

---

## 🔑 API token (optional)

The Agent API needs **no token**. Set one to unlock the Standard API (large files,
batch, DOCX/HTML/LaTeX):

1. Visit **[MinerU Token Management](https://mineru.net/apiManage/token)**
2. Create a free token
3. `export MINERU_TOKEN="your-token-here"`

**Free Standard quota:** 1000 pages/day at highest priority · 200 MB / 200 pages max.

> 📖 Official API docs: https://mineru.net/apiManage/docs

---

## 🧪 Develop & test

```bash
python3 -m pytest                            # fast unit suite (offline, no network)
MINERU_LIVE=1 python3 -m pytest -m live -s   # real API + benchmark (no mocks)

uv run --no-project --with pytest pytest -q  # same suite via uv (managed Python)
```

Zero runtime dependencies — `scripts/mineru.py` is pure standard library, and runs
under either `python3` or `uv run` (PEP 723 inline metadata).

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

## 🏗️ How it works

```
your file / URL
      │
      ▼
┌──────────────────────────────────────────────┐
│  mineru.py  (zero-dep, AI-Native)            │
│  detect modality → choose API (auto)         │
│     • no token / small  → Agent API          │
│     • token + big/batch → Standard API       │
│     • Agent size/page limit → auto-escalate  │
│  submit → poll → download → write Markdown   │
└──────────────────────────────────────────────┘
      │
      ▼
Markdown (+ images)  →  stdout · files · Obsidian · JSON status
```

---

## 🤝 Contributing

Fork → Branch → Commit → Push → PR. Issues and ideas welcome — we actively maintain
this skill and ship around the MinerU ecosystem for AI agents.

## 📝 License

MIT — see [LICENSE](LICENSE).

## 🙏 Acknowledgments

- [MinerU](https://mineru.net/) — PDF parsing engine ([token](https://mineru.net/apiManage/token) · [docs](https://mineru.net/apiManage/docs))
- [OpenClaw](https://openclaw.ai/) — AI skill framework
- [ClawHub](https://clawhub.com) — skill marketplace

---

<div align="center">

**If this skill saves you time, give it a ⭐ — it helps other agents find it.**

Made with ❤️ by [Nebutra](https://github.com/Nebutra)

</div>
