#!/usr/bin/env python3
"""
MinerU PDF Parser - Parse PDFs into Markdown using MinerU API

Usage:
    python mineru_api.py --url "https://example.com/doc.pdf" --output ./parsed/
    python mineru_api.py --file ./document.pdf --output ./parsed/
    python mineru_api.py --dir ./pdfs/ --output ./parsed/ --concurrency 5
"""

import argparse
import asyncio
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import aiohttp
import requests

API_BASE = "https://mineru.net/api/v4"
DEFAULT_TIMEOUT = 600
DEFAULT_POLL_INTERVAL = 5
DEFAULT_CONCURRENCY = 5


def get_token(args: argparse.Namespace) -> str:
    """Get API token from args or environment."""
    token = args.token or os.environ.get("MINERU_TOKEN")
    if not token:
        raise ValueError(
            "No API token provided. Set MINERU_TOKEN environment variable "
            "or use --token argument. Get token from: https://mineru.net/user-center/api-token"
        )
    return token


def headers(token: str) -> dict:
    """Return authorization headers."""
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "Accept": "*/*",
    }


# ============ Async Functions ============


async def async_post(session: aiohttp.ClientSession, url: str, token: str, data: dict, timeout: int = 30) -> dict:
    """Async POST request."""
    async with session.post(
        url,
        headers=headers(token),
        json=data,
        timeout=aiohttp.ClientTimeout(total=timeout),
    ) as response:
        result = await response.json()
        if result.get("code") != 0:
            raise Exception(f"API error: {result.get('msg', result)}")
        return result


async def async_get(session: aiohttp.ClientSession, url: str, token: str, timeout: int = 30) -> dict:
    """Async GET request."""
    async with session.get(
        url,
        headers=headers(token),
        timeout=aiohttp.ClientTimeout(total=timeout),
    ) as response:
        result = await response.json()
        if result.get("code") != 0:
            raise Exception(f"API error: {result.get('msg', result)}")
        return result


async def async_create_task_from_url(
    session: aiohttp.ClientSession,
    token: str,
    url: str,
    data_id: str,
    model_version: str = "vlm",
    enable_formula: bool = True,
    enable_table: bool = True,
    is_ocr: bool = False,
) -> str:
    """Create a parsing task from URL. Returns task_id."""
    data = {
        "url": url,
        "model_version": model_version,
        "enable_formula": enable_formula,
        "enable_table": enable_table,
        "is_ocr": is_ocr,
        "data_id": data_id,
    }
    result = await async_post(session, f"{API_BASE}/extract/task", token, data)
    return result["data"]["task_id"]


async def async_get_task_status(session: aiohttp.ClientSession, token: str, task_id: str) -> dict:
    """Get task status and result."""
    result = await async_get(session, f"{API_BASE}/extract/task/{task_id}", token)
    return result["data"]


async def async_wait_for_task(
    session: aiohttp.ClientSession,
    token: str,
    task_id: str,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Wait for task to complete. Returns result data."""
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout:
            raise TimeoutError(f"Task timed out after {timeout} seconds")

        status = await async_get_task_status(session, token, task_id)
        state = status.get("state")

        if state == "done":
            return status
        elif state == "failed":
            raise Exception(f"Task failed: {status.get('err_msg', 'Unknown error')}")

        await asyncio.sleep(poll_interval)


async def async_download_and_extract(session: aiohttp.ClientSession, url: str, output_dir: Path, filename: str) -> Path:
    """Download and extract result ZIP asynchronously."""
    zip_path = output_dir / f"{filename}.zip"

    async with session.get(url, timeout=aiohttp.ClientTimeout(total=300)) as response:
        with open(zip_path, "wb") as f:
            async for chunk in response.content.iter_chunked(8192):
                f.write(chunk)

    # Extract ZIP (sync, fast enough)
    extract_dir = output_dir / filename
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    zip_path.unlink()
    return extract_dir


async def async_parse_single_url(
    session: aiohttp.ClientSession,
    token: str,
    url: str,
    output_dir: Path,
    index: int,
    total: int,
    model_version: str = "vlm",
    enable_formula: bool = True,
    enable_table: bool = True,
    is_ocr: bool = False,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
    verbose: bool = True,
) -> tuple:
    """Parse a single PDF URL asynchronously. Returns (index, filename, extract_dir or error)."""
    parsed = urlparse(url)
    filename = Path(parsed.path).stem or f"document_{index}"

    if verbose:
        print(f"  [{index+1}/{total}] 开始: {filename}")

    try:
        # Create task
        task_id = await async_create_task_from_url(
            session, token, url, filename, model_version, enable_formula, enable_table, is_ocr
        )

        # Wait for completion
        result = await async_wait_for_task(session, token, task_id, poll_interval, timeout)

        # Download result
        zip_url = result.get("full_zip_url")
        if not zip_url:
            raise Exception("No result URL in response")

        extract_dir = await async_download_and_extract(session, zip_url, output_dir, filename)

        if verbose:
            print(f"  [{index+1}/{total}] ✅ 完成: {filename}")

        return (index, filename, extract_dir)

    except Exception as e:
        if verbose:
            print(f"  [{index+1}/{total}] ❌ 失败: {filename} - {e}")
        return (index, filename, str(e))


async def async_parse_batch_urls(
    token: str,
    urls: list,
    output_dir: Path,
    model_version: str = "vlm",
    enable_formula: bool = True,
    enable_table: bool = True,
    is_ocr: bool = False,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
    concurrency: int = DEFAULT_CONCURRENCY,
    verbose: bool = True,
) -> list:
    """Parse multiple PDF URLs concurrently."""
    if verbose:
        print(f"\n📚 并发解析 {len(urls)} 个文件 (并发数: {concurrency})...")

    output_dir.mkdir(parents=True, exist_ok=True)

    connector = aiohttp.TCPConnector(limit=concurrency)
    timeout_config = aiohttp.ClientTimeout(total=timeout * 2)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout_config) as session:
        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(concurrency)

        async def bounded_parse(url, index):
            async with semaphore:
                return await async_parse_single_url(
                    session, token, url, output_dir, index, len(urls),
                    model_version, enable_formula, enable_table, is_ocr,
                    poll_interval, timeout, verbose
                )

        # Run all tasks concurrently
        tasks = [bounded_parse(url, i) for i, url in enumerate(urls)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        output_dirs = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                if verbose:
                    print(f"  [{i+1}/{len(urls)}] ❌ 异常: {result}")
            else:
                index, filename, data = result
                if isinstance(data, Path):
                    output_dirs.append(data)
                    # Rename full.md to {filename}.md
                    md_file = data / "full.md"
                    if md_file.exists():
                        md_file.rename(data / f"{filename}.md")

        return output_dirs


# ============ Batch File Upload Functions ============


def create_batch_from_files(
    token: str,
    file_paths: list,
    model_version: str = "vlm",
    enable_formula: bool = True,
    enable_table: bool = True,
    is_ocr: bool = False,
) -> tuple:
    """Create batch parsing task by uploading files. Returns (batch_id, upload_urls)."""
    files = [{"name": Path(f).name, "data_id": Path(f).stem} for f in file_paths]
    data = {
        "files": files,
        "model_version": model_version,
        "enable_formula": enable_formula,
        "enable_table": enable_table,
        "is_ocr": is_ocr,
    }

    response = requests.post(
        f"{API_BASE}/file-urls/batch",
        headers=headers(token),
        json=data,
        timeout=60,
    )
    result = response.json()

    if result.get("code") != 0:
        raise Exception(f"Failed to get upload URLs: {result.get('msg', result)}")

    return result["data"]["batch_id"], result["data"]["file_urls"]


def upload_file(upload_url: str, file_path: str) -> bool:
    """Upload a single file to the given URL."""
    with open(file_path, "rb") as f:
        response = requests.put(upload_url, data=f, timeout=300)
    return response.status_code == 200


def get_batch_status(token: str, batch_id: str) -> list:
    """Get batch task status and results."""
    response = requests.get(
        f"{API_BASE}/extract-results/batch/{batch_id}",
        headers=headers(token),
        timeout=30,
    )
    result = response.json()

    if result.get("code") != 0:
        raise Exception(f"Failed to get batch status: {result.get('msg', result)}")

    return result["data"]["extract_result"]


def wait_for_batch(
    token: str,
    batch_id: str,
    total_files: int,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
    verbose: bool = True,
) -> list:
    """Wait for batch to complete. Returns list of results."""
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout:
            raise TimeoutError(f"Batch timed out after {timeout} seconds")

        results = get_batch_status(token, batch_id)

        completed = sum(1 for r in results if r.get("state") == "done")
        failed = sum(1 for r in results if r.get("state") == "failed")
        running = sum(1 for r in results if r.get("state") == "running")
        pending = total_files - completed - failed - running

        if verbose:
            print(f"  状态: {completed} 完成, {running} 处理中, {pending} 等待, {failed} 失败")

        if completed + failed == total_files:
            return results

        time.sleep(poll_interval)


def download_result(url: str, output_dir: Path, filename: str) -> Path:
    """Download and extract result ZIP."""
    zip_path = output_dir / f"{filename}.zip"

    response = requests.get(url, stream=True, timeout=300)
    response.raise_for_status()

    with open(zip_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    extract_dir = output_dir / filename
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    zip_path.unlink()

    return extract_dir


def parse_local_files(
    token: str,
    file_paths: list,
    output_dir: Path,
    model_version: str = "vlm",
    enable_formula: bool = True,
    enable_table: bool = True,
    is_ocr: bool = False,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
    verbose: bool = True,
) -> list:
    """Parse local PDF files by uploading them (sync, for smaller batches)."""
    if verbose:
        print(f"\n📚 上传并解析 {len(file_paths)} 个文件...")

    output_dir.mkdir(parents=True, exist_ok=True)

    # Create batch and upload
    batch_id, upload_urls = create_batch_from_files(
        token, file_paths, model_version, enable_formula, enable_table, is_ocr
    )

    if verbose:
        print(f"  Batch ID: {batch_id}")

    # Upload files
    for i, (file_path, upload_url) in enumerate(zip(file_paths, upload_urls)):
        if verbose:
            print(f"  上传 {Path(file_path).name}... ({i+1}/{len(file_paths)})")
        if not upload_file(upload_url, file_path):
            print(f"  ❌ 上传失败: {file_path}")

    # Wait for completion
    results = wait_for_batch(token, batch_id, len(file_paths), poll_interval, timeout, verbose)

    # Download results
    output_dirs = []
    for result in results:
        if result.get("state") == "done":
            zip_url = result.get("full_zip_url")
            filename = result.get("data_id") or result.get("file_name", "document")
            filename = Path(filename).stem

            extract_dir = download_result(zip_url, output_dir, filename)
            output_dirs.append(extract_dir)

            # Rename full.md
            md_file = extract_dir / "full.md"
            if md_file.exists():
                md_file.rename(extract_dir / f"{filename}.md")

            if verbose:
                print(f"  ✓ {filename}")
        else:
            if verbose:
                print(f"  ✗ {result.get('file_name', 'unknown')}: {result.get('err_msg', 'failed')}")

    return output_dirs


# ============ Main ============


def main():
    parser = argparse.ArgumentParser(
        description="Parse PDFs using MinerU API with concurrent processing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --url "https://example.com/doc.pdf" --output ./parsed/
  %(prog)s --file ./document.pdf --output ./parsed/
  %(prog)s --dir ./pdfs/ --output ./parsed/ --concurrency 10
  %(prog)s --urls-file ./urls.txt --output ./parsed/ --concurrency 5
        """,
    )

    # Input options
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--url", help="Single PDF URL to parse")
    input_group.add_argument("--file", help="Single local PDF file to parse")
    input_group.add_argument("--dir", help="Directory of PDF files to parse")
    input_group.add_argument("--urls-file", help="File containing URLs (one per line)")

    # Output options
    parser.add_argument("--output", default="./output/", help="Output directory")

    # Authentication
    parser.add_argument("--token", help="MinerU API token (or set MINERU_TOKEN env)")

    # Parsing options
    parser.add_argument("--model", default="vlm", choices=["pipeline", "vlm", "MinerU-HTML"])
    parser.add_argument("--ocr", action="store_true", help="Enable OCR for scanned PDFs")
    parser.add_argument("--formula", action="store_true", default=True)
    parser.add_argument("--no-formula", action="store_false", dest="formula")
    parser.add_argument("--table", action="store_true", default=True)
    parser.add_argument("--no-table", action="store_false", dest="table")

    # Concurrency options
    parser.add_argument("--concurrency", "-c", type=int, default=DEFAULT_CONCURRENCY,
                        help=f"Number of concurrent tasks (default: {DEFAULT_CONCURRENCY})")
    parser.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--batch-size", type=int, default=50,
                        help="Batch size for large directories (default: 50)")

    args = parser.parse_args()

    # Get token
    try:
        token = get_token(args)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Create output directory
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.url:
            # Single URL - use async for consistency
            asyncio.run(async_parse_batch_urls(
                token, [args.url], output_dir,
                args.model, args.formula, args.table, args.ocr,
                args.poll_interval, args.timeout, 1
            ))

        elif args.urls_file:
            # URLs from file
            with open(args.urls_file) as f:
                urls = [line.strip() for line in f if line.strip()]

            print(f"📋 从文件读取 {len(urls)} 个 URL")

            asyncio.run(async_parse_batch_urls(
                token, urls, output_dir,
                args.model, args.formula, args.table, args.ocr,
                args.poll_interval, args.timeout, args.concurrency
            ))

        elif args.file:
            # Single local file
            parse_local_files(
                token, [args.file], output_dir,
                args.model, args.formula, args.table, args.ocr,
                args.poll_interval, args.timeout
            )

        elif args.dir:
            # Directory of files - batch process
            input_dir = Path(args.dir)
            pdf_files = list(input_dir.glob("*.pdf")) + list(input_dir.glob("*.PDF"))

            if not pdf_files:
                print(f"No PDF files found in {args.dir}", file=sys.stderr)
                sys.exit(1)

            print(f"📚 发现 {len(pdf_files)} 个 PDF 文件")

            # Process in batches
            batch_size = args.batch_size
            total_batches = (len(pdf_files) + batch_size - 1) // batch_size

            for batch_num in range(total_batches):
                start_idx = batch_num * batch_size
                end_idx = min((batch_num + 1) * batch_size, len(pdf_files))
                batch_files = pdf_files[start_idx:end_idx]

                print(f"\n📦 批次 {batch_num + 1}/{total_batches} ({len(batch_files)} 个文件)")

                parse_local_files(
                    token, [str(f) for f in batch_files], output_dir,
                    args.model, args.formula, args.table, args.ocr,
                    args.poll_interval, args.timeout
                )

        print(f"\n✅ 完成! 结果保存在: {output_dir}")

    except Exception as e:
        print(f"\n❌ 错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
