#!/usr/bin/env python3
"""从 analyze-user-profile --format json 中逐个拆解笔记为独立 .md 文件

CLI 用法（无需修改脚本，直接传参）:
  python extract_profile_notes.py \
    --profile "布布糕.json" --subtitle "布布糕_字幕合集.md" \
    --profile "陈好.json" --subtitle "陈好_字幕合集.md"

或从 stdin 读 JSON 配置（适合 agent 编程调用）:
  echo '[["布布糕.json","布布糕_字幕.md"],["陈好.json","陈好_字幕.md"]]' \
    | python extract_profile_notes.py --stdin

v3: 纯 CLI 驱动，消除 Read+Edit 开销
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# 默认路径，可用 --base-dir 覆盖
DEFAULT_BASE = Path(r"C:\Users\PC\WorkBuddy\edge浏览器查询\内容资产库")
PYTHON = Path(r"C:\Users\PC\.workbuddy\binaries\python\envs\default\Scripts\python.exe")


def sanitize_filename(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:80] if len(s) > 80 else s


def iso_to_date(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return iso_str[:10] if len(iso_str) >= 10 else "unknown"


def extract_tags(desc: str) -> list:
    tags = re.findall(r'#([^#\[]+?)(?:\[话题\])?#', desc)
    return [t.strip() for t in tags if t.strip()]


def parse_subtitle_collection(md_path: str) -> dict:
    """解析完整字幕合集 .md → {note_id: full_text}"""
    if not os.path.exists(md_path):
        print(f"  ⚠ 完整字幕合集不存在: {md_path}", file=sys.stderr)
        return {}

    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()

    sections = re.split(r'\n(?=## \d+\. )', text)
    result = {}
    for sec in sections[1:]:
        note_id_m = re.search(r'- 笔记 ID:\s*(\S+)', sec)
        if not note_id_m:
            continue
        note_id = note_id_m.group(1)
        subtitle_m = re.search(r'### 字幕纯文本\n\n(.+?)\n\n### 原始 SRT', sec, re.DOTALL)
        if subtitle_m:
            result[note_id] = subtitle_m.group(1).strip()
    return result


def build_frontmatter(item: dict, nickname: str, published_date: str,
                      note_type: str, complete_subtitle: str | None) -> str:
    note_id = item.get("id", "")
    url = item.get("url", "")
    title = item.get("title", "")
    text = item.get("text", {})
    desc = text.get("desc", "")
    subtitle_data = text.get("subtitle", {})
    media = item.get("media", {})
    metrics = item.get("metrics", {})
    monetization = item.get("monetization", {})
    collaboration = monetization.get("collaboration", {})
    commerce = monetization.get("commerce_note", {})
    sticky = item.get("sticky", False)

    content_form = "视频笔记" if note_type == "video" else "图文笔记"
    liked = metrics.get("liked", 0) or 0
    collected = metrics.get("collected", 0) or 0
    commented = metrics.get("commented", 0) or 0
    shared = metrics.get("shared", 0) or 0
    total = liked + collected + commented + shared
    save_ratio = round(collected / liked * 100, 1) if liked > 0 else 0

    tags = extract_tags(desc)
    cover_url = media.get("cover_large_url", "")
    subtitle_status = "available" if subtitle_data.get("status") == "ready" else "not_applicable"

    if complete_subtitle is not None:
        plain_text = complete_subtitle
        subtitle_source = "灵造API artifact 完整字幕"
    else:
        plain_text = subtitle_data.get("plain_text", "")
        subtitle_source = "灵造API profile-json 截断预览 ⚠"
        if content_form == "视频笔记" and subtitle_status == "available":
            print(f"  ⚠ 未在完整字幕合集中找到 {note_id[:12]}... {title[:30]}", file=sys.stderr)

    lines = [
        "---",
        '文档类型: 小红书笔记原始档案',
        '档案版本: "1.0"',
        "数据层: 原始数据",
        "平台: 小红书",
        f'账号: "{nickname}"',
        f'笔记ID: "{note_id}"',
        f"内容形式: {content_form}",
        f'发布时间: "{published_date}"',
        f'原始标题: "{title}"',
        f'原始笔记链接: "{url}"',
        f'封面原始链接: "{cover_url}"',
        '封面本地备份: ""',
        "封面OCR状态: 未识别",
        '封面OCR文本: ""',
        f"字幕状态: {subtitle_status}",
        f'字幕来源: "{subtitle_source}"',
        '原始字幕文件: ""',
        '原始时间轴字幕文件: ""',
        f"点赞: {liked}",
        f"收藏: {collected}",
        f"评论: {commented}",
        f"分享: {shared}",
        f"互动总量: {total}",
        f"收藏点赞比: {save_ratio}",
        f"是否合作: {'是' if collaboration.get('likely_collaboration') else '否'}",
        f"是否商品笔记: {'是' if commerce.get('likely_goods_note') else '否'}",
        f"是否置顶: {'是' if sticky else '否'}",
        f'视频时长秒: {media.get("video_duration_seconds", 0)}',
        f'抓取时间: "2026-08-04"',
        "数据来源: 灵造API analyze-user-profile",
        "tags:",
        "  - 内容资产库",
        "  - 原始数据",
    ]
    for tag in tags:
        lines.append(f"  - {tag}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    lines.append("## 原始正文/描述")
    lines.append("")
    lines.append(f"> {desc}")
    lines.append("")

    if content_form == "视频笔记" and plain_text:
        lines.append("## 原始字幕（纯文本）")
        lines.append("")
        for paragraph in plain_text.split("\n"):
            paragraph = paragraph.strip()
            if paragraph:
                lines.append(f"> {paragraph}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*本文件由机械程序从灵造 API 抓取数据自动生成，未经 AI 改写。*")
    lines.append("")
    return "\n".join(lines)


def process_profile(json_path: str, subtitle_md_path: str, notes_dir: str, json_dir: str):
    """处理单个 profile JSON + 完整字幕合集"""
    json_abs = json_path if os.path.isabs(json_path) else os.path.join(json_dir, json_path)
    subtitle_abs = subtitle_md_path if os.path.isabs(subtitle_md_path) else os.path.join(json_dir, subtitle_md_path)

    subtitle_map = parse_subtitle_collection(subtitle_abs)
    print(f"\n  完整字幕合集: {len(subtitle_map)} 条")

    with open(json_abs, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("data", {}).get("items", [])
    nickname = data.get("data", {}).get("user", {}).get("nickname", "unknown")

    print(f"=== {nickname} — {len(items)} 条笔记 ===")

    created = 0
    truncated_count = 0
    for item in items:
        note_id = item.get("id", "")
        note_type = item.get("xhs_note_type", item.get("type", "normal"))
        published_at = item.get("published_at", "")
        published_date = iso_to_date(published_at)
        title = item.get("title", "无标题")

        complete_subtitle = subtitle_map.get(note_id)
        if complete_subtitle is None and note_type == "video":
            truncated_count += 1

        subdir = "视频笔记" if note_type == "video" else "图文笔记"
        target_dir = os.path.join(notes_dir, subdir)
        os.makedirs(target_dir, exist_ok=True)

        safe_title = sanitize_filename(title)
        safe_nickname = sanitize_filename(nickname)
        filename = f"{published_date}__{safe_nickname}_{safe_title}.md"
        filepath_out = os.path.join(target_dir, filename)

        md_content = build_frontmatter(item, nickname, published_date, note_type, complete_subtitle)

        with open(filepath_out, "w", encoding="utf-8") as f:
            f.write(md_content)

        created += 1
        status = "✓完整" if complete_subtitle else "⚠截断"
        print(f"  [{note_type:6s}] {status} {filename}")

    print(f"  写入 {created} 个文件")
    if truncated_count > 0:
        print(f"  ⚠ {truncated_count} 条视频笔记仍使用截断预览", file=sys.stderr)
    else:
        print(f"  ✅ 0 条截断，全部使用完整字幕")


def main():
    parser = argparse.ArgumentParser(description="拆解 profile JSON → 逐条笔记 .md")
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE),
                        help=f"内容资产库根目录（默认: {DEFAULT_BASE}）")
    parser.add_argument("--json-dir", default=None,
                        help="灵造原始 JSON 目录（默认: BASE/90_数据源/灵造原始JSON）")
    parser.add_argument("--notes-dir", default=None,
                        help="笔记输出目录（默认: BASE/01_原始笔记/小红书）")

    # 方式 A: 命令行传多组 --profile / --subtitle 对
    parser.add_argument("--profile", default=[], action="append",
                        help="profile JSON 文件名（可多次指定，与 --subtitle 一一对应）")
    parser.add_argument("--subtitle", default=[], action="append",
                        help="完整字幕合集文件名（与 --profile 一一对应）")

    # 方式 B: stdin 读取 JSON 配置 [[json, md], ...]
    parser.add_argument("--stdin", action="store_true",
                        help="从 stdin 读取 JSON 数组配置")

    args = parser.parse_args()

    base = Path(args.base_dir)
    json_dir = args.json_dir or str(base / "90_数据源" / "灵造原始JSON")
    notes_dir = args.notes_dir or str(base / "01_原始笔记" / "小红书")

    if args.stdin:
        config = json.loads(sys.stdin.read())
        profiles = config
    elif args.profile and args.subtitle:
        if len(args.profile) != len(args.subtitle):
            print("❌ --profile 和 --subtitle 数量不匹配", file=sys.stderr)
            sys.exit(1)
        profiles = list(zip(args.profile, args.subtitle))
    else:
        print("❌ 请提供 --profile/--subtitle 对，或 --stdin 读取配置", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    for json_fn, subtitle_fn in profiles:
        process_profile(json_fn, subtitle_fn, notes_dir, json_dir)

    print(f"\n✅ 全部完成。共处理 {len(profiles)} 个 profile。")


if __name__ == "__main__":
    main()
