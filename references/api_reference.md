# MinerU API Reference

## Base URL

```
https://mineru.net/api/v4
```

## Authentication

All requests require Bearer token in Authorization header:

```
Authorization: Bearer YOUR_API_TOKEN
```

Get token from: https://mineru.net/user-center/api-token

## Endpoints

### Single File Parsing (URL)

**POST** `/extract/task`

Parse PDF from URL.

Request body:
```json
{
  "url": "https://example.com/doc.pdf",
  "model_version": "vlm",
  "is_ocr": false,
  "enable_formula": true,
  "enable_table": true,
  "language": "ch",
  "page_ranges": "1-10",
  "extra_formats": ["docx", "html"],
  "data_id": "my-document",
  "no_cache": false,
  "cache_tolerance": 900
}
```

Response:
```json
{
  "code": 0,
  "data": {"task_id": "xxx-xxx-xxx"},
  "msg": "ok",
  "trace_id": "xxx"
}
```

### Get Task Result

**GET** `/extract/task/{task_id}`

Response:
```json
{
  "code": 0,
  "data": {
    "task_id": "xxx",
    "state": "done",
    "full_zip_url": "https://...",
    "err_msg": ""
  },
  "msg": "ok"
}
```

States:
- `pending` - Queued
- `running` - Processing
- `done` - Complete
- `failed` - Error
- `converting` - Format conversion

### Batch URL Parsing

**POST** `/extract/task/batch`

Request body:
```json
{
  "files": [
    {"url": "https://example.com/doc1.pdf", "data_id": "doc1"},
    {"url": "https://example.com/doc2.pdf", "data_id": "doc2"}
  ],
  "model_version": "vlm"
}
```

Response:
```json
{
  "code": 0,
  "data": {"batch_id": "xxx-xxx-xxx"},
  "msg": "ok"
}
```

### Batch File Upload

**POST** `/file-urls/batch`

Get upload URLs for local files.

Request body:
```json
{
  "files": [
    {"name": "doc1.pdf", "data_id": "doc1"}
  ],
  "model_version": "vlm"
}
```

Response:
```json
{
  "code": 0,
  "data": {
    "batch_id": "xxx",
    "file_urls": ["https://upload-url-1"]
  },
  "msg": "ok"
}
```

Then upload files with PUT request to each URL.

### Get Batch Results

**GET** `/extract-results/batch/{batch_id}`

Response:
```json
{
  "code": 0,
  "data": {
    "batch_id": "xxx",
    "extract_result": [
      {
        "file_name": "doc.pdf",
        "state": "done",
        "full_zip_url": "https://..."
      }
    ]
  },
  "msg": "ok"
}
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | string | required | PDF URL |
| `model_version` | string | `pipeline` | `pipeline`, `vlm`, or `MinerU-HTML` |
| `is_ocr` | bool | `false` | Enable OCR for scanned docs |
| `enable_formula` | bool | `true` | Formula recognition |
| `enable_table` | bool | `true` | Table recognition |
| `language` | string | `ch` | Language code |
| `page_ranges` | string | all | "1-10,15,20-30" |
| `extra_formats` | array | [] | `["docx","html","latex"]` |
| `data_id` | string | - | Custom identifier |
| `no_cache` | bool | `false` | Bypass cache |
| `cache_tolerance` | int | 900 | Cache TTL in seconds |

## Rate Limits

- **Free tier**: 2000 pages/day at high priority
- **Max file size**: 200MB
- **Max pages**: 600 per file
- **Batch limit**: 200 files per request

## Error Codes

| Code | Description |
|------|-------------|
| A0202 | Invalid token |
| A0211 | Token expired |
| -500 | Parameter error |
| -60005 | File too large (>200MB) |
| -60006 | Too many pages (>600) |
| -60008 | File read timeout |
| -60010 | Parse failed |
| -60018 | Daily limit reached |
