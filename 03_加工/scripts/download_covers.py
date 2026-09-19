#!/usr/bin/env python3
"""批量下载笔记封面到本地备份，并更新 .md 的 封面本地备份 字段。

v3 修复: 用 Python 原生 os.replace() 替换文件，不再依赖 bash subprocess。
         封面下载 + 字段更新在同一 Python 进程中完成，无需 Read+Edit。
         CDN token 过期（HTTP 498）会自动跳过并提示重新抓取。

用法:
  python download_covers.py [--base-dir PATH] [--dry-run]
"""

import argparse
import hashlib
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE = Path(r"C:\Users\PC\WorkBuddy\edge浏览器查询\内容资产库")


def download_cover(url: str, save_path: str) -> bool:
    if os.path.exists(save_path):
        return True
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.xiaohongshu.com/",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
            if len(data) < 500:
                return False
            with open(save_path, "wb") as f:
                f.write(data)
            return True
    except urllib.error.HTTPError as e:
        if e.code == 498:
            print(f"    ❌ HTTP 498 — CDN sign token 已过期，需重新抓取 profile 后立即下载")
        else:
            print(f"    ❌ HTTP {e.code}")
        return False
    except Exception as e:
        print(f"    ❌ {e}")
        return False


def update_md_inplace(md_path: str, rel_path: str) -> bool:
    """直接在原文件上替换封面备份字段（Python 原生 os.replace）"""
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    new_content = re.sub(
        r'封面本地备份: ".*?"',
        f'封面本地备份: "{rel_path}"',
        content,
    )
    if new_content == content:
        return False

    # 先写临时文件，再原子替换（处理 Windows 文件锁）
    tmp_path = md_path + ".tmp"
    for attempt in range(3):
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            os.replace(tmp_path, md_path)  # 原子操作
            return True
        except (PermissionError, OSError):
            if attempt < 2:
                time.sleep(0.3)
            else:
                print(f"    ⚠ 写入失败（文件被占用）: {os.path.basename(md_path)}", file=sys.stderr)
                # 清理临时文件
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                return False
    return False


def main():
    parser = argparse.ArgumentParser(description="批量下载小红书笔记封面")
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE),
                        help=f"内容资产库根目录（默认: {DEFAULT_BASE}）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只扫描不下载")
    args = parser.parse_args()

    base = Path(args.base_dir)
    notes_dir = base / "01_原始笔记" / "小红书"
    cover_dir = base / "90_数据源" / "封面本地备份"
    cover_dir.mkdir(parents=True, exist_ok=True)

    # 收集任务
    tasks = []
    for root, dirs, files in os.walk(notes_dir):
        for fname in files:
            if not fname.endswith(".md"):
                continue
            md_path = os.path.join(root, fname)
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
            url_m = re.search(r'封面原始链接: "(.+?)"', content)
            backup_m = re.search(r'封面本地备份: "(.+?)"', content)
            cover_url = url_m.group(1) if url_m else ""
            existing_backup = backup_m.group(1) if backup_m else ""
            if cover_url:
                tasks.append((md_path, content, cover_url, existing_backup))

    total = len(tasks)
    if total == 0:
        print("未发现任何带封面 URL 的笔记。")
        return

    print(f"共发现 {total} 条封面的笔记\n")

    if args.dry_run:
        print("=== DRY RUN — 不执行下载 ===")
        for idx, (md_path, _, cover_url, existing) in enumerate(tasks, 1):
            status = "✓已有" if existing else "⬇待下载"
            print(f"  [{idx}/{total}] {status} {os.path.basename(md_path)[:50]}")
        return

    downloaded = 0
    failed = 0
    skipped = 0
    updated = 0

    for idx, (md_path, content, cover_url, existing_backup) in enumerate(tasks, 1):
        note_id_m = re.search(r'笔记ID: "(.+?)"', content)
        title_m = re.search(r'原始标题: "(.+?)"', content)
        note_id = note_id_m.group(1) if note_id_m else "unknown"
        title = title_m.group(1) if title_m else os.path.basename(md_path)

        # 已有本地备份 → 跳过下载，直接更新字段（如果字段为空）
        if existing_backup:
            abs_backup = base / existing_backup
            if abs_backup.exists():
                skipped += 1
                continue

        ext = ".webp"
        url_hash = hashlib.md5(cover_url.encode()).hexdigest()[:8]
        save_fname = f"{note_id}_{url_hash}{ext}"
        save_path = str(cover_dir / save_fname)
        rel_path = f"90_数据源/封面本地备份/{save_fname}"

        print(f"[{idx}/{total}] 📥 {title[:50]}...")

        if download_cover(cover_url, save_path):
            downloaded += 1
            size_kb = os.path.getsize(save_path) // 1024
            print(f"    ✅ {save_fname} ({size_kb}KB)")
            # 同一进程内立即更新字段
            if update_md_inplace(md_path, rel_path):
                updated += 1
            else:
                print(f"    ⚠ 封面下载成功但字段更新失败", file=sys.stderr)
        else:
            failed += 1

    print(f"\n{'='*50}")
    print(f"总计: {total} | ✅ 下载: {downloaded} | ⏭ 跳过: {skipped} | ❌ 失败: {failed} | ✏ 字段更新: {updated}")
    if failed > 0:
        print("\n⚠ 失败的原因通常是 CDN sign token 过期（HTTP 498）。")
        print("  解决: 重新抓取 profile → 立即运行本脚本（不要间隔超过 1 小时）")
    print(f"\n封面目录: {cover_dir}")


if __name__ == "__main__":
    main()
