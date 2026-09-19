#!/usr/bin/env python3
"""将浏览器 CDP 抓取的博主主页 JSON → 逐条独立 .md 笔记文件

浏览器标准化 JSON 格式（agent 用 web-access skill 从 __INITIAL_STATE__ 提取后生成）:
{
  "source": "browser-cdp",
  "captured_at": "2026-08-04T22:00:00",
  "blogger_name": "布布糕",
  "blogger_id": "5f...",
  "notes": [
    {
      "noteId": "xxx",
      "title": "xxx",
      "noteType": "video",
      "videoDuration": 123,
      "publishTime": 1700000000000,
      "likedCount": "1234",
      "collectedCount": "567",
      "commentCount": "89",
      "shareCount": "12",
      "coverUrl": "https://...",
      "tags": ["标签1"],
      "noteUrl": "https://...",
      "isTop": false,
      "desc": "正文描述...",
      "subtitleText": ""
    }
  ]
}

CLI 用法:
  python process_browser_notes.py \
    --input "浏览器原始数据/2026-08-04_profile_布布糕.json" \
    --input "浏览器原始数据/2026-08-04_profile_陈好.json" \
    --output-dir "内容资产库/01_原始笔记/小红书/"

v1: 浏览器优先管线，0 credits
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

DEFAULT_BASE = Path(r"C:\Users\PC\WorkBuddy\edge浏览器查询")


def sanitize_filename(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:80] if len(s) > 80 else s


def ms_to_date(ms: int) -> str:
    """毫秒时间戳 → YYYY-MM-DD"""
    try:
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone(timedelta(hours=8)))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return "unknown"


def ms_to_datetime_str(ms: int) -> str:
    """毫秒时间戳 → YYYY-MM-DD HH:MM:SS (UTC+8)"""
    try:
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone(timedelta(hours=8)))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "unknown"


def safe_int(val) -> int:
    """兼容字符串数字和整数"""
    if val is None:
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def build_frontmatter(note: dict, blogger_name: str, blogger_id: str,
                      captured_at: str) -> str:
    """为单条浏览器笔记生成 .md frontmatter + 正文"""
    note_id = note.get("noteId", "")
    title = note.get("title", "无标题")
    note_type = note.get("noteType", "normal")
    publish_ts = note.get("publishTime", 0)
    published_date = ms_to_date(publish_ts)
    published_full = ms_to_datetime_str(publish_ts)
    cover_url = note.get("coverUrl", "")
    desc = note.get("desc", "")
    tags = note.get("tags", [])
    note_url = note.get("noteUrl", f"https://www.xiaohongshu.com/explore/{note_id}")
    is_top = note.get("isTop", False)
    duration = note.get("videoDuration", 0)
    subtitle_text = note.get("subtitleText", "")

    liked = safe_int(note.get("likedCount", 0))
    collected = safe_int(note.get("collectedCount", 0))
    commented = safe_int(note.get("commentCount", 0))
    shared = safe_int(note.get("shareCount", 0))
    total = liked + collected + commented + shared
    save_ratio = round(collected / liked * 100, 1) if liked > 0 else 0

    content_form = "视频笔记" if note_type == "video" else "图文笔记"

    # 字幕状态
    if subtitle_text:
        subtitle_status = "browser_extracted"
        subtitle_source = "浏览器CDP页面提取"
    elif note_type == "video":
        subtitle_status = "browser_no_subtitle"
        subtitle_source = "浏览器数据（需灵造提取）"
    else:
        subtitle_status = "not_applicable"
        subtitle_source = "图文笔记无字幕"

    lines = [
        "---",
        '文档类型: 小红书笔记原始档案',
        '档案版本: "1.0"',
        "数据层: 原始数据",
        "平台: 小红书",
        f'账号: "{blogger_name}"',
        f'博主ID: "{blogger_id}"',
        f'笔记ID: "{note_id}"',
        f"内容形式: {content_form}",
        f'发布时间: "{published_full}"',
        f'原始标题: "{title}"',
        f'原始笔记链接: "{note_url}"',
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
        "是否合作: 未知",
        "是否商品笔记: 未知",
        f"是否置顶: {'是' if is_top else '否'}",
        f'视频时长秒: {duration}',
        f'抓取时间: "{captured_at[:10]}"',
        "数据来源: 浏览器CDP",
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

    if desc:
        lines.append("## 原始正文/描述")
        lines.append("")
        lines.append(f"> {desc}")
        lines.append("")

    if subtitle_text:
        lines.append("## 原始字幕（纯文本）")
        lines.append("")
        for paragraph in subtitle_text.split("\n"):
            paragraph = paragraph.strip()
            if paragraph:
                lines.append(f"> {paragraph}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*本文件由浏览器 CDP 抓取数据自动生成，未经 AI 改写。*")
    lines.append("*字幕需通过灵造 get-note-detail 提取（20 credits/条）。*")
    lines.append("")
    return "\n".join(lines)


def process_input(input_path: str, output_dir: str):
    """处理单个浏览器 profile JSON → 拆解为 .md 文件"""
    if not os.path.exists(input_path):
        print(f"  ❌ 文件不存在: {input_path}", file=sys.stderr)
        return 0, 0, 0

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    blogger_name = data.get("blogger_name", "unknown")
    blogger_id = data.get("blogger_id", "")
    captured_at = data.get("captured_at", "")
    notes = data.get("notes", [])

    print(f"\n=== {blogger_name} (ID: {blogger_id}) — {len(notes)} 条笔记 ===")

    video_count = 0
    image_count = 0
    created = 0

    for note in notes:
        note_type = note.get("noteType", "normal")
        publish_ts = note.get("publishTime", 0)
        published_date = ms_to_date(publish_ts)
        title = note.get("title", "无标题")

        if note_type == "video":
            video_count += 1
            subdir = "视频笔记"
        else:
            image_count += 1
            subdir = "图文笔记"

        target_dir = os.path.join(output_dir, subdir)
        os.makedirs(target_dir, exist_ok=True)

        safe_title = sanitize_filename(title)
        safe_name = sanitize_filename(blogger_name)
        filename = f"{published_date}__{safe_name}_{safe_title}.md"
        filepath_out = os.path.join(target_dir, filename)

        md_content = build_frontmatter(note, blogger_name, blogger_id, captured_at)

        with open(filepath_out, "w", encoding="utf-8") as f:
            f.write(md_content)
        created += 1
        print(f"  [{note_type:6s}] {filename}")

    print(f"  写入 {created} 个文件 | 视频: {video_count} | 图文: {image_count}")
    return created, video_count, image_count


def main():
    parser = argparse.ArgumentParser(
        description="浏览器 profile JSON → 逐条笔记 .md")
    parser.add_argument("--input", action="append", default=[],
                        help="浏览器标准化 JSON 文件路径（可多次指定）")
    parser.add_argument("--output-dir", required=True,
                        help="笔记输出目录（如 内容资产库/01_原始笔记/小红书/）")
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE),
                        help=f"项目根目录（默认: {DEFAULT_BASE}）")

    args = parser.parse_args()

    if not args.input:
        print("❌ 请至少提供一个 --input 文件路径", file=sys.stderr)
        sys.exit(1)

    base = Path(args.base_dir)
    output_dir = args.output_dir
    if not os.path.isabs(output_dir):
        output_dir = str(base / output_dir)

    total_created = 0
    total_video = 0
    total_image = 0
    total_inputs = len(args.input)

    for input_path in args.input:
        if not os.path.isabs(input_path):
            input_path = str(base / input_path)
        c, v, i = process_input(input_path, output_dir)
        total_created += c
        total_video += v
        total_image += i

    print(f"\n✅ 全部完成。{total_inputs} 个博主，{total_created} 条笔记 "
          f"（视频 {total_video}，图文 {total_image}）")
    print(f"📁 输出目录: {output_dir}")
    print(f"💡 下一步: python scripts/download_covers.py  # 立即下载封面")
    print(f"💡 下一步: python scripts/build_notes_excel.py --browser-data ...")


if __name__ == "__main__":
    main()
