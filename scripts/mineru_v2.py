#!/usr/bin/env python3
"""
MinerU PDF Parser - 修复版

使用正确的 OSS 上传方式
"""

import argparse
import os
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

API_BASE = "https://mineru.net/api/v4"


def get_token(args):
    return args.token or os.environ.get("MINERU_TOKEN")


def headers(token):
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


def process_file(token, file_path, output_dir, index, total):
    """处理单个文件"""
    filename = Path(file_path).name
    stem = Path(file_path).stem
    
    # 检查是否已存在
    if (output_dir / stem).exists():
        print(f"  [{index+1}/{total}] ⏭️  {stem}")
        return True, stem
    
    print(f"  [{index+1}/{total}] 📤 {stem}", end="", flush=True)
    
    for attempt in range(5):
        try:
            # 1. 获取上传链接
            resp = requests.post(
                f"{API_BASE}/file-urls/batch",
                headers=headers(token),
                json={
                    "files": [{"name": filename, "data_id": stem}],
                    "model_version": "vlm",
                    "enable_formula": True,
                    "enable_table": True,
                },
                timeout=60,
            )
            result = resp.json()
            
            if result.get("code") != 0:
                raise Exception(f"API错误: {result.get('msg')}")
            
            batch_id = result["data"]["batch_id"]
            upload_url = result["data"]["file_urls"][0]
            
            # 2. 上传文件 - 使用正确的方式
            print(" ⏳", end="", flush=True)
            
            # 关键：不设置 Content-Type，让 requests 自动处理
            with open(file_path, "rb") as f:
                file_data = f.read()
            
            upload_resp = requests.put(
                upload_url,
                data=file_data,  # 使用 data 而不是 files
                timeout=300,
            )
            
            if upload_resp.status_code not in [200, 203]:
                raise Exception(f"上传失败: {upload_resp.status_code}")
            
            # 3. 等待解析
            print(" 🔄", end="", flush=True)
            
            for _ in range(120):
                status_resp = requests.get(
                    f"{API_BASE}/extract-results/batch/{batch_id}",
                    headers=headers(token),
                    timeout=30,
                )
                results = status_resp.json()["data"]["extract_result"]
                
                if results:
                    state = results[0].get("state")
                    
                    if state == "done":
                        # 4. 下载
                        print(" 📥", end="", flush=True)
                        zip_url = results[0]["full_zip_url"]
                        zip_path = output_dir / f"{stem}.zip"
                        
                        dl_resp = requests.get(zip_url, timeout=300)
                        zip_path.write_bytes(dl_resp.content)
                        
                        extract_dir = output_dir / stem
                        with zipfile.ZipFile(zip_path) as zf:
                            zf.extractall(extract_dir)
                        
                        zip_path.unlink()
                        
                        # 重命名
                        md = extract_dir / "full.md"
                        if md.exists():
                            md.rename(extract_dir / f"{stem}.md")
                        
                        print(" ✅")
                        return True, stem
                    
                    elif state == "failed":
                        raise Exception(results[0].get("err_msg", "解析失败"))
                
                time.sleep(5)
            
            raise Exception("等待超时")
            
        except Exception as e:
            if attempt < 4:
                print(f" 🔄r{attempt+1}", end="", flush=True)
                time.sleep(2 ** attempt)
            else:
                print(f" ❌ {e}")
                return False, stem
    
    return False, stem


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--token")
    parser.add_argument("--workers", "-w", type=int, default=5)
    parser.add_argument("--resume", action="store_true")
    
    args = parser.parse_args()
    
    token = get_token(args)
    if not token:
        print("❌ 请设置 MINERU_TOKEN")
        sys.exit(1)
    
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 收集文件
    input_dir = Path(args.dir)
    pdf_files = sorted(list(input_dir.glob("*.pdf")) + list(input_dir.glob("*.PDF")))
    
    if args.resume:
        original = len(pdf_files)
        pdf_files = [f for f in pdf_files if not (output_dir / f.stem).exists()]
        if skipped := original - len(pdf_files):
            print(f"⏭️  跳过已处理: {skipped} 个\n")
    
    if not pdf_files:
        print("✅ 所有文件已完成!")
        return
    
    total = len(pdf_files)
    print(f"📚 开始处理 {total} 个文件 (并发: {args.workers})\n")
    
    success = 0
    failed = 0
    failed_files = []
    start = time.time()
    
    # 并行处理
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_file, token, f, output_dir, i, total): f
            for i, f in enumerate(pdf_files)
        }
        
        for future in as_completed(futures):
            ok, name = future.result()
            if ok:
                success += 1
            else:
                failed += 1
                failed_files.append(name)
    
    elapsed = time.time() - start
    print(f"\n{'='*50}")
    print(f"✅ 成功: {success}")
    print(f"❌ 失败: {failed}")
    print(f"⏱️  耗时: {elapsed/60:.1f} 分钟")
    
    if failed_files:
        print(f"\n失败: {failed_files}")
    
    print(f"\n📁 输出: {output_dir}")


if __name__ == "__main__":
    main()
