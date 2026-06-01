# Delivery Integrations (`--to`)

After parsing, MinerU Skill can deliver the Markdown straight into your content
tools using each tool's **official ingestion path** — no fragile generic block
converters. Targets are pluggable sinks; select one or more with `--to NAME`
(repeatable). List them live with `python3 scripts/mineru.py --list-sinks`.

```bash
# Parse and fan out to several destinations at once
python3 scripts/mineru.py paper.pdf --to obsidian --to notion --to slack
```

Each sink reads its configuration from **environment variables** so an AI agent
can run it non-interactively. Delivery results appear in `--json` output under
each result's `sinks` array.

## Support matrix

| Target | `--to` | Native path | Auth / config (env) | Markdown fidelity | Images |
|--------|--------|-------------|---------------------|-------------------|--------|
| **Obsidian** | `obsidian` (`ob`) | filesystem write + YAML frontmatter | `OBSIDIAN_VAULT`, `OBSIDIAN_SUBDIR?` | full | ✅ copied to `<note>.assets/` |
| **Logseq** | `logseq` | filesystem write, outline + `key:: value` | `LOGSEQ_GRAPH` | full (outline transform) | ✅ copied to `assets/` |
| **SiYuan** | `siyuan` | kernel `createDocWithMd` | `SIYUAN_TOKEN`, `SIYUAN_API_URL?`, `SIYUAN_NOTEBOOK?` | full (GFM) | ✅ `asset/upload` |
| **Notion** | `notion` | `POST /v1/pages` (blocks) | `NOTION_API_KEY`, `NOTION_PARENT_PAGE_ID`, `NOTION_VERSION?` | structure (headings/lists/code/quote) | ⚠️ text only¹ |
| **Linear** | `linear` | GraphQL `issueCreate` | `LINEAR_API_KEY`, `LINEAR_TEAM_ID` | full (Markdown-native) | ✅ base64-inlined |
| **Yuque 语雀** | `yuque` (`语雀`) | open API create doc | `YUQUE_TOKEN`, `YUQUE_NAMESPACE` | full (Markdown-native) | ⚠️ host publicly² |
| **Coda** | `coda` | page canvas `format:markdown` | `CODA_API_TOKEN`, `CODA_DOC_ID?` | full (Markdown-native) | ⚠️ public URL² |
| **Slack** | `slack` | external-upload `.md` file | `SLACK_BOT_TOKEN`, `SLACK_CHANNEL` | full (raw file) | ⚠️ not embedded |
| **Lark 飞书** | `feishu` (`lark`, `飞书`) | Drive `import_tasks` → Docx | `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_FOLDER_TOKEN?` | full (server-converted) | ⚠️ public URL² |
| **Confluence** | `confluence` | `POST /wiki/api/v2/pages` (storage) | `CONFLUENCE_BASE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`, `CONFLUENCE_SPACE_ID` | MD→HTML | ⚠️ not attached |
| **OneNote** | `onenote` | Graph `sections/{id}/pages` | `ONENOTE_TOKEN`³, `ONENOTE_SECTION_ID` | MD→HTML | ⚠️ remote only |
| **TickTick 滴答** | `ticktick` (`dida`, `滴答清单`) | `POST /open/v1/task` | `TICKTICK_TOKEN`, `TICKTICK_PROJECT_ID?` | task note | ❌ unsupported |
| **DingTalk 钉钉** | `dingtalk` (`钉钉`) | robot markdown webhook | `DINGTALK_WEBHOOK`, `DINGTALK_SECRET?` | markdown message | ⚠️ public URL only |
| **Airtable** | `airtable` | `POST /v0/{base}/{table}` record | `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`, `AIRTABLE_TABLE`, `AIRTABLE_TITLE_FIELD?`, `AIRTABLE_BODY_FIELD?` | record field⁴ | ❌ not uploaded |
| **WeCom 企业微信** | `wecom` (`企业微信`) | app `message/send` markdown | `WECOM_CORPID`, `WECOM_CORPSECRET`, `WECOM_AGENTID`, `WECOM_TOUSER?` | message (subset, ≤2 KB)⁵ | ❌ unsupported |
| **Roam Research** ⁶ | `roam` | `batch-actions` block tree | `ROAM_API_TOKEN`, `ROAM_GRAPH_NAME` | full (Markdown→outline) | ⚠️ public URL |
| **WPS 金山文档** ⁶ | `wps` (`kdocs`, `金山`) | Markdown→DOCX → kdocs upload | `WPS_APP_ID`, `WPS_APP_SECRET`, `WPS_PARENT_PATH?` | DOCX (via html-for-docx) | embedded in DOCX |

Notes:
1. **Notion** images need a separate `file_uploads` upload-then-reference dance; v1 delivers text + structure and notes the count of un-embedded local images. (Roadmap: image upload.)
2. Hosted services that ingest Markdown by value but have no first-class CLI asset upload — local images must be hosted at a public URL to render. The Markdown is delivered intact; image links that are already URLs work.
3. **OneNote** `ONENOTE_TOKEN` is a Microsoft Graph access token (delegated, scope `Notes.Create`). Obtain it via the device-code OAuth flow; the sink itself stays non-interactive.
4. **Airtable** is a database, not a document store — the doc is stored as one record (title + body fields). A good "save this doc as a row" target, not a document publisher.
5. **WeCom** markdown messages are a limited subset (≤2048 bytes, no images/tables, not rendered in the workbench). Best as a notification/summary; for a full document deliver via Lark/Notion and send the link.
6. **Optional-dependency sinks** — these two rely on a third-party library that the sink lazy-imports only when used, so the core and the other 15 sinks stay zero-dependency. If the library is absent, the sink returns a clear `pip install …` hint. They are implemented to the official specs but, being credential/desktop-gated, are best-effort until validated against live accounts.

## Optional-dependency sinks (`[roam]`, `[wps]`)

```bash
pip install "mineru-skill[wps]"    # html-for-docx  (Markdown → DOCX)
pip install "mineru-skill[roam]"   # official roam-client SDK (git, needs Python ≥3.11)
# roam-client is git-only; equivalently:
pip install "roam-client @ git+https://github.com/Roam-Research/backend-sdks.git#subdirectory=python"
```

- **Roam** — no library ingests Markdown into Roam, but the official `roam-client` SDK handles the genuinely error-prone transport (307/308 peer-host redirect, dual `Authorization`/`x-authorization` Bearer headers, `/write`). We depend on it for transport and build only the Markdown→outline tree, delivering the whole document in one `batch-actions` request. Images must be public URLs.
- **WPS / 金山文档** — Markdown→DOCX uses the maintained pure-pip `html-for-docx` (reusing this project's Markdown→HTML); the kdocs upload signs requests with the documented WPS-2 scheme (plain SHA-1) using only the standard library. Requires an approved kdocs developer app + provisioned appspace.

Adding more targets is a single small module — see `scripts/sinks/base.py`. PRs welcome.
