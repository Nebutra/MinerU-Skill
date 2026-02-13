#!/usr/bin/env python3
"""
MinerU PDF Parser - 高性能异步并发版本

Optimizations:
- asyncio + aiohttp: 单线程异步，无 GIL 开销
- 连接池复用: 减少 TCP 握手
- 信号量控制: 精确并发数
- 自动重试: 失败自动重试 3 次
"""

import argparse
import asyncio
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Optional, Tuple

import aiohttp

API_BASE = "https://mineru.net/api/v4"

# 并发控制
MAX_CONCURRENT = 10
MAX_RETRIES = 3


class MinerUClient:
    """MinerU API 异步客户端"""
    
    def __init__(self, token: str, session: aiohttp.ClientSession):
        self.token = token
        self.session = session
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    
    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
    
    async def create_batch_upload(self, filename: str, data_id: str) -> Tuple[str, str]:
        """获取上传链接"""
        async with self.session.post(
            f"{API_BASE}/file-urls/batch",
            headers=self._headers(),
            json={
                "files": [{"name": filename, "data_id": data_id}],
                "model_version": "vlm",
                "enable_formula": True,
                "enable_table": True,
            },
        ) as resp:
            result = await resp.json()
            if result.get("code") != 0:
                raise Exception(f"API error: {result.get('msg')}")
            data = result["data"]
            return data["batch_id"], data["file_urls"][0]
    
    async def upload_file(self, upload_url: str, file_path: Path) -> bool:
        """上传文件"""
        async with self.session.put(
            upload_url,
            data=file_path.read_bytes(),
        ) as resp:
            return resp.status == 200
    
    async def wait_for_result(self, batch_id: str, timeout: int = 600) -> Optional[str]:
        """等待解析完成，返回下载链接"""
        start = time.time()
        
        while time.time() - start < timeout:
            async with self.session.get(
                f"{API_BASE}/extract-results/batch/{batch_id}",
                headers=self._headers(),
            ) as resp:
                result = await resp.json()
                results = result["data"]["extract_result"]
                
                if not results:
                    await asyncio.sleep(5)
                    continue
                
                state = results[0].get("state")
                
                if state == "done":
                    return results[0].get("full_zip_url")
                elif state == "failed":
                    raise Exception(results[0].get("err_msg", "解析失败"))
                
                await asyncio.sleep(5)
        
        raise TimeoutError("等待超时")
    
    async def download_and_extract(self, zip_url: str, output_dir: Path, filename: str) -> Path:
        """下载并解压"""
        zip_path = output_dir / f"{filename}.zip"
        
        async with self.session.get(zip_url) as resp:
            zip_path.write_bytes(await resp.read())
        
        extract_dir = output_dir / filename
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
        
        zip_path.unlink()
        
        # 重命名
        md_file = extract_dir / "full.md"
        if md_file.exists():
            md_file.rename(extract_dir / f"{filename}.md")
        
        return extract_dir
    
    async def process_file(
        self,
        file_path: Path,
        output_dir: Path,
        index: int,
        total: int,
    ) -> Tuple[bool, str]:
        """处理单个文件（带重试）"""
        filename = file_path.name
        stem = file_path.stem
        
        # 检查是否已存在
        if (output_dir / stem).exists():
            print(f"  [{index+1}/{total}] ⏭️  {stem}")
            return True, stem
        
        async with self.semaphore:  # 控制并发
            for attempt in range(MAX_RETRIES):
                try:
                    print(f"  [{index+1}/{total}] {'🔄' if attempt > 0 else '📤'} {stem}")
                    
                    # 1. 获取上传链接
                    batch_id, upload_url = await self.create_batch_upload(filename, stem)
                    
                    # 2. 上传
                    if not await self.upload_file(upload_url, file_path):
                        raise Exception("上传失败")
                    
                    # 3. 等待解析
                    zip_url = await self.wait_for_result(batch_id)
                    
                    # 4. 下载解压
                    await self.download_and_extract(zip_url, output_dir, stem)
                    
                    print(f"  [{index+1}/{total}] ✅ {stem}")
                    return True, stem
                    
                except Exception as e:
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(2 ** attempt)  # 指数退避
                        continue
                    print(f"  [{index+1}/{total}] ❌ {stem}: {e}")
                    return False, stem
        
        return False, stem


async def main_async(args):
    """异步主函数"""
    token = args.token or os.environ.get("MINERU_TOKEN")
    if not token:
        print("❌ 请设置 MINERU_TOKEN")
        sys.exit(1)
    
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 收集文件
    input_dir = Path(args.dir)
    pdf_files = sorted(list(input_dir.glob("*.pdf")) + list(input_dir.glob("*.PDF")))
    
    if not pdf_files:
        print("❌ 未找到 PDF 文件")
        sys.exit(1)
    
    # 过滤已处理的
    if args.resume:
        original = len(pdf_files)
        pdf_files = [f for f in pdf_files if not (output_dir / f.stem).exists()]
        if skipped := original - len(pdf_files):
            print(f"⏭️  跳过已处理: {skipped} 个")
    
    if not pdf_files:
        print("✅ 所有文件已处理完成!")
        return
    
    total = len(pdf_files)
    print(f"\n📚 开始处理 {total} 个文件 (异步并发: {MAX_CONCURRENT})")
    print(f"📁 输出到: {output_dir}\n")
    
    start_time = time.time()
    
    # 创建 aiohttp session（连接池复用）
    connector = aiohttp.TCPConnector(limit=MAX_CONCURRENT * 2, force_close=False)
    timeout = aiohttp.ClientTimeout(total=3600)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        client = MinerUClient(token, session)
        
        # 并发处理所有文件
        tasks = [
            client.process_file(f, output_dir, i, total)
            for i, f in enumerate(pdf_files)
        ]
        results = await asyncio.gather(*tasks)
    
    # 统计
    success = sum(1 for ok, _ in results if ok)
    failed = sum(1 for ok, _ in results if not ok)
    failed_files = [name for ok, name in results if not ok]
    
    elapsed = time.time() - start_time
    print(f"\n{'='*50}")
    print(f"✅ 成功: {success}")
    print(f"❌ 失败: {failed}")
    print(f"⏱️  耗时: {elapsed/60:.1f} 分钟")
    print(f"🚀 速度: {total/elapsed*60:.1f} 文件/分钟")
    
    if failed_files:
        print(f"\n失败文件:")
        for f in failed_files:
            print(f"  - {f}")
    
    print(f"\n📁 结果: {output_dir}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--token")
    parser.add_argument("--workers", "-w", type=int, default=10, help="并发数")
    parser.add_argument("--resume", action="store_true")
    
    args = parser.parse_args()
    
    global MAX_CONCURRENT
    MAX_CONCURRENT = args.workers
    
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
