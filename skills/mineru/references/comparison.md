<!-- Web-researched competitive comparison (45 tools, 6 categories, adversarially fact-checked). Last researched 2026-05-31. Star counts / versions are point-in-time. -->

# MinerU Skill — Competitive Comparison Reference

This document gives an honest, sourced, per-tool breakdown of how **MinerU Skill** compares to the document-parsing landscape. Read the framing first: it determines how to interpret every "we win / they win" below.

## What MinerU Skill actually is (and is not)

MinerU Skill is a **zero-config, zero-dependency, agent-native convenience layer over [MinerU](https://github.com/opendatalab/MinerU)'s cloud API**, plus 17 turnkey delivery integrations to note/knowledge/content tools. Concretely (verified in this repo):

- Core script `scripts/mineru.py` is **~54KB / ~1,350 lines of pure Python standard library** — no `requests`/`aiohttp`, no model weights.
- A **genuinely token-free** default: the free **Agent API** path (`agent_parse` → `_agent_poll`) sends **no `Authorization` header** (the Bearer header is set only when a token is present). Files ≤10MB / ≤20 pages.
- **Auto-routing**: with a token, large/batched/extra-format jobs use the **Standard API** (≤200MB / ≤200 pages); the Agent path **auto-escalates** to Standard on size/page limits.
- **17 delivery sinks** (16 sink modules + `local.py` registering both `obsidian` and `logseq`): obsidian, logseq, siyuan, notion, confluence, onenote, coda, yuque, feishu, slack, dingtalk, wecom, ticktick, linear, airtable — all zero-dependency — plus **roam** (needs `roam-client`) and **wps** (needs `html-for-docx`) which lazy-load one library only when used.
- `--resume` dedup, parallel `--workers` (ThreadPoolExecutor), `--stdout`/`--json` agent output.

**Critical dependency:** our accuracy is **entirely downstream of, and capped by, what MinerU's cloud serves.** We own no models. Therefore:

- We have **no quality edge** over any other cloud wrapper that hits the same MinerU API — OCR/table/formula output is **identical**.
- Self-hosting the MinerU engine gives the **same or better** accuracy (version-controllable, no upload caps).

**Hard limits we cannot exceed:** 10MB/20-page free Agent tier, 200MB/200-page Standard tier, plus IP rate limits. Self-hosted tools have no such caps (only hardware).

**Our benchmark is latency-only.** `tests/test_live.py` measures end-to-end cloud round-trip latency (~13–14s for the official demo PDF). It is **not** an accuracy benchmark; we have no OmniDocBench/olmOCR-Bench numbers of our own.

### A note on the speed claim

Our ~13–14s/doc cloud round-trip is **not** a clean win over self-hosted GPU engines. A normal self-host with a GPU runs at ~0.18s/page (Marker) or ~2.12 pages/sec (MinerU on A100) — far faster at any real scale. We only out-run **slow Apple-Silicon-CPU local runs of small docs** (e.g., M4 VLM at 32–148s/page). Do not frame "faster wall-clock" as a general win.

### A note on benchmarks

No single benchmark is authoritative. Different benchmarks favor different tools:
- **OmniDocBench** (v1.5/v1.6): MinerU2.5 **90.67** (v1.5), MinerU2.5-Pro **95.69** (v1.6) — leads, beating Gemini 2.5 Pro / GPT-4o / Qwen2.5-VL-72B on text/table/formula. Source: arXiv 2509.22186.
- **olmOCR-Bench** (Ai2, Oct 2025): olmOCR-2 **82.4** > Marker **76.1** > **MinerU 75.8**. Here MinerU **trails** — this is a real olmOCR win and must stay visible.
- **RD-TableBench**: Reducto 90.2% on complex tables — but Reducto authored this benchmark (vendor-biased).
- Mathpix is the de-facto formula-OCR standard (BLEU/edit-distance studies), though a PaddleOCR-VL-based tool claims to beat it on OmniDocBench v1.0 formula recognition, so the very top is contested.

> Star counts / versions below (e.g. MinerU "65.7k / v3.2.1") are point-in-time and not independently re-verified.

---

## Category 1 — Self-hosted / open-source parsing engines

These are the tools that close our single biggest gap: **fully offline / air-gapped / no cloud / no upload caps.**

### MinerU engine (opendatalab) — the engine we wrap
- **Source:** https://github.com/opendatalab/MinerU · arXiv 2509.22186 · https://huggingface.co/opendatalab/MinerU2.5-Pro-2604-1.2B
- **Strengths:** Owns the SOTA models (OmniDocBench 90.67 / 95.69-Pro v1.6). 109-language OCR, handwriting, cross-page table merge, formula→LaTeX (the source of *our* LaTeX). Fully self-hostable → offline, air-gappable, zero per-page cost, no caps. Pipeline backend runs pure CPU; VLM needs 8GB+ VRAM. Native MCP, Python/Go/TS SDKs, LangChain/LlamaIndex/Dify/FastGPT.
- **Weaknesses vs us:** Heavy install (multi-GB torch/vLLM + weights, 16GB RAM / 20GB disk floor); slow on Apple Silicon; no note/PKM delivery sinks; library/CLI rather than zero-config.
- **Verdict:** **Beats us** on offline, privacy, caps, accuracy ceiling, ecosystem. **We beat it** only on zero-install/zero-config and built-in delivery.

### Marker (datalab-to / VikParuchuri)
- **Source:** https://github.com/datalab-to/marker · https://allenai.org/blog/olmocr-2
- **Strengths:** Fully offline; very high batch throughput (~122 pages/sec/H100, 0.18s/page GPU); broad formats incl. EPUB; optional local-LLM (Ollama) quality boost with no data leaving the machine; ~35k+ stars, active.
- **Weaknesses:** **GPL-3.0** code + model weights under a modified RAIL-M (free only under ~$2M funding+revenue; commercial above that needs a Datalab license). olmOCR-Bench **76.1** — below olmOCR-2 and MinerU's OmniDocBench standing.
- **Verdict:** Beats us on offline/throughput; we beat it on zero-install and 17 delivery sinks. License gate is a real friction it has and we don't.

### Docling (IBM / DS4SD)
- **Source:** https://github.com/docling-project/docling · https://huggingface.co/ibm-granite/granite-docling-258M · arXiv 2408.09869
- **Strengths:** **Widest input modality set** (PDF/DOCX/PPTX/XLSX/HTML/AsciiDoc/LaTeX/CSV/images + **audio via ASR** + USPTO/JATS/XBRL). Tiny 258M Granite-Docling VLM runs on CPU/modest GPU. **MIT code + Apache-2.0 weights.** Deep framework ecosystem (LangChain/LlamaIndex/Haystack + official MCP), IBM-backed, 60k+ stars. Air-gapped by design.
- **Weaknesses:** Absolute accuracy lags MinerU on OmniDocBench/olmOCR-Bench; library-first (not a zero-config CLI); targets framework ingestion, not file delivery to note tools.
- **Verdict:** Beats us on offline, modality breadth, permissive license, ecosystem; we beat it on zero-install and note/PKM delivery. **Do not over-rank its MIT as uniquely best** — olmOCR's Apache-2.0 on *both* code and 7B weights is at least as commercially valuable.

### olmOCR (allenai)
- **Source:** https://github.com/allenai/olmocr · https://allenai.org/blog/olmocr-2 · https://huggingface.co/datasets/allenai/olmOCR-bench
- **Strengths:** **Leads Ai2's olmOCR-Bench (82.4 vs MinerU 75.8)** — a benchmark where MinerU trails. **Apache-2.0 on code AND the olmOCR-2-7B weights** (most commercial-friendly model reuse here). Built for million-page LLM-training linearization. Offline.
- **Weaknesses:** **PDF/image only** (no Office/HTML); **English-primary**, filters non-English (MinerU does 109-lang); **requires a 12GB+ NVIDIA GPU, no CPU mode at all**.
- **Verdict:** Beats us on offline, that-benchmark accuracy, license, scale. We beat it on modality breadth, multilingual, no-GPU, delivery, zero-install. **Keep the olmOCR-Bench lead visible — do not cherry-pick only OmniDocBench.**

### Nougat (facebookresearch / Meta AI)
- **Source:** https://github.com/facebookresearch/nougat · arXiv 2308.13418
- **Strengths:** Strong LaTeX/math on arXiv-style scientific PDFs (its trained niche). Offline.
- **Weaknesses:** **PDF + English/Latin-script only** (no CJK); **CC-BY-NC weights (non-commercial)**; effectively **unmaintained** (last release Aug 2023); known repetition/hallucination/[MISSING_PAGE] failures off-distribution.
- **Verdict:** Offline + niche math is its only edge; we beat it on general-purpose, multilingual, maintenance, commercial license, delivery.

### PyMuPDF4LLM (pymupdf / Artifex)
- **Source:** https://github.com/pymupdf/pymupdf4llm · https://pymupdf.io/blog/pymupdf-layout-10-faster-pdf-parsing-without-gpus
- **Strengths:** **Far faster and lighter than any ML tool on born-digital PDFs** (~hundreds of pages/sec on plain CPU; a C-optimized variant claims ~520 pages/sec). Lowest dependency/hardware footprint. Offline, no cloud, no caps. Ideal for huge clean-PDF corpora where speed > fidelity.
- **Weaknesses:** No ML → no real formula/LaTeX, weak complex tables, poor scanned/handwritten; slow external OCR; **AGPL-3.0 OR Artifex commercial**; Office formats need paid **PyMuPDF Pro**.
- **Verdict:** A genuine win for the speed-over-fidelity, clean-PDF use case. We beat it on hard-doc quality (MinerU's VLM), multilingual OCR, and delivery — but acknowledge its speed/footprint advantage honestly.

### Zerox (getomni-ai)
- **Source:** https://github.com/getomni-ai/zerox
- **Strengths:** Trivial provider-flexibility (OpenAI/Azure/Bedrock-Claude/Gemini/Vertex); JSON-Schema structured extraction (Node SDK); MIT code.
- **Weaknesses:** **NOT offline and NOT token-free** — mandates a paid cloud vision-LLM key; needs graphicsmagick+ghostscript; **no published benchmarks**; per-page LLM cost can exceed MinerU on large jobs.
- **Verdict:** We beat it on token-free start, benchmarked accuracy, dedicated formula/table models, system-dep footprint, and delivery. It beats us on provider-swap flexibility and typed JSON extraction.

---

## Category 2 — Commercial cloud document-parsing APIs

Mostly **stronger than us** on enterprise accuracy, SLAs, structured extraction, and RAG/MCP ecosystems. Our honest edges are narrow: token-free + zero-install hosted default, clean Markdown/LaTeX of academic PDFs, and 17 delivery sinks none of them offer.

### LlamaParse (LlamaIndex / LlamaCloud)
- **Source:** https://www.llamaindex.ai/pricing · LlamaCloud MCP docs
- **Beats us:** Official hosted **MCP server**; deep native RAG stack (parse→index→LlamaExtract/LlamaAgents); steerable NL parsing with frontier LLMs (GPT-4.1/Gemini 2.5 Pro); richer outputs (per-page JSON, XLSX, HTML tables, annotated PDF); enterprise SLAs; mature Python+TS SDKs.
- **We beat:** Token-free start (it needs a LlamaCloud key from page one); zero runtime deps; 17 note/PKM sinks (it delivers to RAG indexes, not note tools); built-in `--resume`/parallel batch CLI.

### Mathpix (Convert API)
- **Source:** https://mathpix.com/pricing/api · https://mathpix.com/image-to-latex
- **Beats us:** **Best-in-class formula/equation OCR (printed AND handwritten) → clean LaTeX — clearly better than MinerU for pure math fidelity; concede this, do not imply parity.** Mature Snip ecosystem + Overleaf workflows; very low per-image cost at scale.
- **We beat:** Token-free start (Mathpix API requires a paid PAYG account, **$19.99 setup fee**, card on file; **no recurring free monthly allowance** — only a one-time $29 test credit; the consumer Snip app's free quota does **not** apply to the API); general-purpose multi-modal Office parsing; 17 delivery sinks; built-in batch CLI.

### Unstructured.io
- **Source:** https://unstructured.io/pricing · https://github.com/Unstructured-IO/unstructured
- **Beats us:** **Apache-2.0 core library is fully self-hostable → 100% offline** (we cannot); official MCP + huge connector ecosystem (S3/SharePoint/vector DBs); built-in chunking+embedding (RAG-ready); 25+ file types; permissive license for product embedding.
- **We beat:** Token-free hosted default with zero install (its hosted API needs a key; self-host means running infra); cleaner human-readable Markdown out of the box (its primary output is JSON "elements"); 17 note/PKM sinks (it targets vector DBs/storage). *On parsing quality:* VLM parsing is generally stronger for complex layout/formula, but this is **not a benchmarked head-to-head** — state it as a tendency, not a measured win.

### Reducto
- **Source:** https://reducto.ai/pricing
- **Beats us:** **Best complex/financial table extraction (90.2% RD-TableBench — vendor-authored but the strongest public evidence)**; agentic multi-pass OCR; SOC2/HIPAA, on-prem/VPC/air-gapped, enterprise SLAs; schema-based extraction with bounding boxes/citations.
- **We beat:** Token-free start (it needs a key + credits); zero-install plain CLI; 17 delivery sinks; auto-routing/--resume/parallel batch.

### Chunkr (and similar RAG-native APIs)
- **Beats us:** Self-hostable (offline option we lack); RAG-native chunking + broad export (DOCX/HTML/LaTeX).
- **We beat:** Token-free start; zero-install; 17 note/PKM sinks.
- **Caveat (fact-check):** Do **not** claim "stronger VLM Markdown for formulas" — Chunkr cloud uses its own proprietary models and we have **no head-to-head benchmark**. Drop the quality claim; keep only the export-breadth and offline framing.

---

## Category 3 — Other MinerU wrappers, skills & MCP servers (our direct peers)

**Every cloud-backed wrapper here hits the same MinerU API we do, so its OCR/table/formula output is IDENTICAL to ours.** We have **no quality edge** over them — only DX differences. Claims of "better OCR/formula/Markdown" vs these are **invalid** and must not appear.

### Official MinerU MCP server (mineru-open-mcp / MinerU-Ecosystem)
- **Source:** https://github.com/opendatalab/MinerU-Ecosystem · https://pypi.org/project/mineru-open-mcp/
- **Beats us:** **Official, first-party** — tracks API/format changes day-one; native **MCP server** (stdio + streamable-http) in Claude Desktop/Cursor/Windsurf with zero glue; full ecosystem (Python/Go/TS SDKs, LangChain/LlamaIndex/Dify/FastGPT). **Same free no-token Flash tier as us** — our "free zero-token" edge is fully matched by the first party.
- **We beat:** Zero runtime deps (vs pip/uvx install); auto-routing Agent⇄Standard with auto-escalation; 17 delivery sinks; `--resume`/parallel batch; usable as a plain CLI outside any MCP host.

### MinerU-Document-Explorer (official, opendatalab)
- **Source:** https://github.com/opendatalab/MinerU-Document-Explorer
- **Beats us:** Different, **larger** value prop — a local agent-native **knowledge engine** (BM25/vector/hybrid retrieval + deep-reading + LLM-wiki) with 15 MCP tools; runs 100% locally for its core; MIT, 568 stars.
- **We beat:** We're a focused zero-dep converter; broader conversion modalities; 17 delivery sinks (it keeps content in its own index/wiki); no Node/local-model download.

### linxule/mineru-mcp (Node, cloud)
- **Source:** https://github.com/linxule/mineru-mcp
- **Beats us:** Native MCP server with 6 granular tools (explicit status-polling + batch-status pagination); first-class for Node/JS MCP stacks; batch up to 200 URLs/request.
- **We beat:** **Free no-token path** (it **requires** a token always); zero runtime deps (vs Node 18+); broader modalities (Excel/HTML); 17 delivery sinks; usable as plain CLI outside MCP.

### mineru-converter-mcp-server (AvatarGanymede/MinerU-MCP)
- **Source:** https://pypi.org/project/mineru-converter-mcp-server/
- **Beats us:** **Auto-splits PDFs >200MB and segments >600-page docs by page range — gracefully exceeding the 200MB/200-page cap we are bound by.** Turnkey Smithery + Render deploy (per-user key); explicit HTML input.
- **We beat:** Free no-token default (it requires a key); zero runtime deps; plain CLI (no MCP host/Render/Smithery needed); 17 sinks; auto-routing.

### grimoire-skill (LeoLin990405)
- **Source:** https://github.com/LeoLin990405/grimoire-skill
- **Beats us:** Higher-level knowledge-capture ("parse once, share twice" → Obsidian notes + reusable skill packs); ingests **video** (YouTube/Bilibili) + subtitles (modalities we don't touch); cross-agent skill management; content-aware Obsidian auto-filing.
- **We beat:** Free no-token default (it needs a token + `--cloud-ok` for local files); zero runtime deps (vs bash+jq+awk + optional yt-dlp/ffmpeg); 17 sinks vs primarily Obsidian; broader Office/HTML; cross-platform single-file portability.

### kesslerio/mineru-pdf-parser (openclaw/ClawHub skill, local CPU)
- **Source:** openclaw/skills · SKILL.md
- **Beats us:** **Fully local/offline (pure CPU, cross-platform)** — no cloud/token/caps; handles privacy-sensitive docs; native Markdown + JSON.
- **We beat:** Zero install (it needs a full local MinerU install + weights + shell wrapper); no GPU/heavy runtime; faster wall-clock **only vs slow local CPU**; broader modalities; 17 sinks; `--stdout`/`--json`; better docs.

### nilecui/mineru-parser-skills (Claude Agent SDK, cloud)
- **Source:** https://github.com/nilecui/mineru-parser-skills
- **Beats us:** Built directly on the Claude Agent SDK (slots into Agent-SDK apps). Honestly little else — it's a thinner cloud wrapper.
- **We beat:** Accepts local files/dirs **and** URLs (it is **URL-only** — cannot parse a local PDF); free no-token default; zero runtime deps; batch/`--resume`/parallel; 17 sinks; broader modalities; mature/documented vs a 4-commit, no-license repo. *Caveat:* our "benchmarked" claim means **latency-measured**, not accuracy-benchmarked.

### TINKPA/mcp-mineru (local MLX, Apple Silicon)
- **Source:** https://github.com/TINKPA/mcp-mineru
- **Beats us:** **Fully offline/local** via MinerU running on-device (MLX accel); no cloud/token/caps; data never leaves the Mac.
- **We beat:** Zero install/no weights/no GPU; **faster wall-clock only for typical multi-page docs vs its slow local inference (32–148s/page on M4)** — not a general speed win; broader modalities; batch/`--resume`/17 sinks; more active/documented; usable as plain CLI.

---

## Summary of mandatory concessions (do not bury these)

1. **Offline / air-gapped is our single biggest gap.** MinerU engine, Marker, Docling, olmOCR, Nougat, PyMuPDF4LLM, TINKPA, kesslerio, MinerU-Document-Explorer, and self-hostable Unstructured/Chunkr all run with **zero cloud dependency**. We are cloud-only and **cannot handle confidential/regulated/air-gapped content at all.**
2. **Data privacy:** every self-hosted competitor keeps documents on the machine; we **upload every file** to MinerU's cloud — a hard disqualifier for many regulated users.
3. **Accuracy is downstream of, and capped by, MinerU's cloud.** Self-hosting MinerU2.5-Pro gives the same-or-better accuracy with no caps. Same-backend wrappers yield **identical** quality to us.
4. **Hard caps:** 10MB/20-page (Agent), 200MB/200-page (Standard), IP rate limits. mineru-converter exceeds them via auto-split/segmentation.
5. **Mathpix beats us on formula/LaTeX OCR (incl. handwriting).**
6. **Reducto leads complex/financial tables; olmOCR leads olmOCR-Bench (82.4 vs MinerU 75.8).** Different benchmarks favor different tools — never cherry-pick only OmniDocBench.
7. **Official first-party advantage:** the official MinerU MCP/Document-Explorer + ecosystem track changes day-one and match our free tier; we are third-party, can lag, and ship **no MCP server**.
8. **Permissive-license wins we lack:** olmOCR (Apache-2.0 code + 7B weights), Docling (MIT + Apache-2.0 weights), Unstructured (Apache-2.0 core).
9. **PyMuPDF4LLM is far faster/lighter on born-digital PDFs** (clean-text corpora, speed > fidelity).

## Sources

- MinerU engine: https://github.com/opendatalab/MinerU · arXiv 2509.22186 · https://huggingface.co/opendatalab/MinerU2.5-Pro-2604-1.2B · https://neurohive.io/en/state-of-the-art/mineru2-5-open-source-1-2b-model-for-pdf-parsing-outperforms-gemini-2-5-pro-on-benchmarks/
- Official MCP / ecosystem: https://github.com/opendatalab/MinerU-Ecosystem · https://pypi.org/project/mineru-open-mcp/ · https://github.com/opendatalab/MinerU-Document-Explorer
- Marker: https://github.com/datalab-to/marker · https://allenai.org/blog/olmocr-2
- Docling: https://github.com/docling-project/docling · arXiv 2408.09869 · https://huggingface.co/ibm-granite/granite-docling-258M
- olmOCR: https://github.com/allenai/olmocr · https://allenai.org/blog/olmocr-2 · https://huggingface.co/datasets/allenai/olmOCR-bench
- Nougat: https://github.com/facebookresearch/nougat · arXiv 2308.13418
- PyMuPDF4LLM: https://github.com/pymupdf/pymupdf4llm · https://pymupdf.io/blog/pymupdf-layout-10-faster-pdf-parsing-without-gpus
- Zerox: https://github.com/getomni-ai/zerox
- LlamaParse: https://www.llamaindex.ai/pricing
- Mathpix: https://mathpix.com/pricing/api · https://mathpix.com/image-to-latex
- Unstructured: https://unstructured.io/pricing · https://github.com/Unstructured-IO/unstructured
- Reducto: https://reducto.ai/pricing
- Other wrappers: https://github.com/linxule/mineru-mcp · https://pypi.org/project/mineru-converter-mcp-server/ · https://github.com/LeoLin990405/grimoire-skill · https://github.com/nilecui/mineru-parser-skills · https://github.com/TINKPA/mcp-mineru
