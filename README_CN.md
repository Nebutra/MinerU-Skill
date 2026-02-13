# MinerU Skill

[![GitHub Release](https://img.shields.io/github/v/release/Nebutra/MinerU-Skill?include_prereleases)](https://github.com/Nebutra/MinerU-Skill/releases) [![Python](https://img.shields.io/badge/Python-3.8+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/) [![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE) [![Smithery](https://img.shields.io/badge/Smithery-Available-blue.svg)](https://smithery.ai/skills/nebutra/mineru-skill)

[![GitHub Stars](https://img.shields.io/github/stars/Nebutra/MinerU-Skill?style=social)](https://github.com/Nebutra/MinerU-Skill/stargazers) [![GitHub Forks](https://img.shields.io/github/forks/Nebutra/MinerU-Skill?style=social)](https://github.com/Nebutra/MinerU-Skill/network/members)

**一款将 PDF 文档转换为简洁 Markdown 的 AI Skill，基于 MinerU VLM 引擎。**

**中文文档** | **[English](README.md)**

---

## 🤖 什么是 Skill？

**Skill** 是扩展 AI 助手能力的功能包。当你向 AI 提出需求时，它会自动：

1. **识别** 你的自然语言请求
2. **激活** 对应的 Skill
3. **执行** Skill 提供的工具
4. **返回** 结果给你

### 示例对话

```
你: 解析这些考研数学真题 PDF 到我的 Obsidian

AI: 📚 发现 40 个 PDF 文件
    ⏳ 开始并行解析 (5 workers)...
    ✅ 1993年考研数学（一）真题 → Markdown
    ✅ 1994年考研数学（一）真题 → Markdown
    ...
    ✅ 完成！已保存到 Obsidian/考研/数学一/
```

---

## 🚀 安装为 Skill

### Smithery

[![安装到 Smithery](https://img.shields.io/badge/安装到-Smithery-blue)](https://smithery.ai/skills/nebutra/mineru-skill)

### OpenClaw

```bash
# 克隆到 skills 目录
git clone https://github.com/Nebutra/MinerU-Skill.git ~/openclaw-skills/mineru/

# 设置 API Token
export MINERU_TOKEN="你的-token"  # 获取: https://mineru.net/user-center/api-token
```

### ClawHub

```bash
# 通过 clawhub CLI 安装
clawhub install mineru
```

### Claude Code / Cursor / Windsurf

```bash
# 克隆到 AI 的 skills 文件夹
git clone https://github.com/Nebutra/MinerU-Skill.git ~/.claude/skills/mineru/
```

---

## 💬 使用示例

### 单文件

```
把 ./document.pdf 解析成 Markdown
```

### 批量目录

```
解析 ./papers/ 目录下的所有 PDF，输出到 ./output/
```

### 直接到 Obsidian

```
把这些 PDF 解析后直接保存到我的 Obsidian Vault
```

### 考研真题示例

```
解析 1987-2025 年考研数学真题，保存到 Obsidian/考研/数学一/
用 10 个并发，跳过已处理的文件
```

---

## ⚡ 功能特性

| 特性 | 说明 |
|------|------|
| 📄 **PDF 输入** | 本地文件、URL、批量目录 |
| 📝 **输出格式** | Markdown + JSON 元数据 + 图片 |
| 🔢 **LaTeX 公式** | 完整保留数学公式 |
| 📊 **表格提取** | 结构化提取 |
| 🖼️ **图片提取** | 自动保存到 `images/` |
| ⚡ **异步处理** | 15 个并行上传 |
| 🔄 **断点续传** | 跳过已处理文件 |
| 📁 **直通 Obsidian** | 直接输出到 Vault |

---

## 🛠️ 命令行使用

也可以直接通过 CLI 使用：

```bash
# 单文件
python scripts/mineru_v2.py --file ./doc.pdf --output ./output/

# 批量 + 断点续传
python scripts/mineru_v2.py \
  --dir ./pdfs/ \
  --output ~/Obsidian/MyVault/ \
  --workers 10 \
  --resume
```

| 参数 | 说明 |
|------|------|
| `--dir PATH` | 输入目录 |
| `--file PATH` | 单文件 |
| `--output PATH` | 输出目录 |
| `--workers N` | 并发数 (默认: 5) |
| `--resume` | 跳过已处理文件 |
| `--token TOKEN` | API Token |

---

## 📁 输出结构

```
output/
├── 文档名称/
│   ├── 文档名称.md      # 主 Markdown 文件
│   ├── images/          # 提取的图片
│   │   ├── image_0_0.png
│   │   └── ...
│   └── content.json     # 元数据
└── ...
```

---

## 📊 性能对比

**测试：** 10 个 PDF，每个约 15 页 (MacBook Air M1)

| 配置 | 耗时 | 速度 |
|------|------|------|
| 串行 | 8.5 分钟 | 1.2 文件/分钟 |
| 异步 (5 workers) | 3.2 分钟 | 3.1 文件/分钟 |
| 异步 (15 workers) | 1.8 分钟 | 5.6 文件/分钟 |

---

## 🔑 获取 API Token

1. 访问 [MinerU](https://mineru.net/user-center/api-token)
2. 创建免费 API Token
3. 设置环境变量：

```bash
export MINERU_TOKEN="你的-token"
```

**免费额度：** 每天 2000 页，单文件最大 200MB

---

## ⭐ Star 趋势

<a href="https://www.star-history.com/#Nebutra/MinerU-Skill&type=timeline&legend=bottom-right">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=Nebutra/MinerU-Skill&type=timeline&theme=dark&legend=bottom-right" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=Nebutra/MinerU-Skill&type=timeline&legend=bottom-right" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=Nebutra/MinerU-Skill&type=timeline&legend=bottom-right" />
 </picture>
</a>

---

## 🏗️ Skill 架构

```
┌─────────────────────────────────────────────────────────────┐
│                      用户请求                                │
│      "把这些 PDF 解析成 Markdown"                           │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                      AI 助手                                │
│  • 识别 PDF 解析任务                                        │
│  • 激活 MinerU skill                                        │
│  • 读取 SKILL.md 获取指令                                   │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  MINERU SKILL 引擎                          │
│  扫描器 ──► 调度器 ──► 工作池 (N 个协程)                    │
│                           │                                 │
│                           ▼                                 │
│  API: 获取链接 ──► 上传 ──► 轮询 ──► 下载                   │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                        输出                                 │
│     Markdown + JSON + 图片 ──► Obsidian/文件               │
└─────────────────────────────────────────────────────────────┘
```

---

## 🤝 贡献指南

1. Fork → Branch → Commit → Push → PR

---

## 📝 许可证

MIT License - 详见 [LICENSE](LICENSE)

---

## 🙏 致谢

- [MinerU](https://mineru.net/) - PDF 解析 API
- [OpenClaw](https://openclaw.ai/) - AI Skill 框架
- [ClawHub](https://clawhub.com) - Skill 市场

---

<div align="center">

**觉得有用？给个 ⭐ 支持一下！**

Made with ❤️ by [Nebutra](https://github.com/Nebutra)

</div>
