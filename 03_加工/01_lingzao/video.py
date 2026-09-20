# -*- coding: utf-8 -*-
"""灵造 · 视频下载（**占位接口，当前不下载任何东西**）。

    python 03_加工/01_lingzao/run.py video "02_储存/01_lingzao/analyze-user-profile/"

**为什么现在是空的**：这条链拿不到视频直链。
灵造只给**时长**、不给地址（`analyze-user-profile` 用 `media.video_duration_seconds`，
`search-notes` 用 `media.video.durationMs` —— 两种命令字段名不一样）；另外能给的
只有一个笔记页链接，那不是视频文件地址。

所以这个文件先把「接口 + 询问流程」摆好，等接上视频源再填实现。
将来接上之后，流程按用户定的走：

    1. **抓取完成后先问一句**，不自己决定：
         · 这次有几条带视频？
         · 要不要下？
         · 下要多少钱、占多大地方？
    2. 默认**下**（无非占点地方），也可以改成默认不下 —— 见下面 `DEFAULT_DOWNLOAD`
    3. **不管默认是什么，都会先问一次** —— 因为要报成本，不能闷头下

和得到大脑那边完全分开：那份在 `03_加工/02_getnote/video.py`，
两边的规则不一样（一个抓临时链接、一个抓永久链接），别混。
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from util import expand_paths, load_json  # noqa: E402

# 真接上视频源之后，问你「要不要下」时的默认选中项。
# 改成 False 就是默认不下。**但无论这里写什么，都会先问一次。**
DEFAULT_DOWNLOAD = True


def scan(paths) -> list[tuple[str, str, float]]:
    """扫本地 profile JSON，列出带视频的条目：(文件, 笔记ID, 时长秒)。

    灵造没给视频 URL，但给了时长 —— 有时长就说明这条是视频。
    ⚠️ 两种命令的字段名**不一样**（踩过）：
       · `analyze-user-profile` → `media.video_duration_seconds`（秒）
       · `search-notes`        → `media.video.durationMs`（毫秒）
    """
    found: list[tuple[str, str, float]] = []
    for f in expand_paths(paths, (".json",)):
        try:
            data = load_json(f).get("data") or {}
        except Exception:
            continue
        if data.get("type") != "analyze-user-profile":
            continue
        for it in (data.get("items") or []):
            media = it.get("media") or {}
            secs = 0.0
            if media.get("video_duration_seconds"):
                secs = float(media["video_duration_seconds"])
            elif (media.get("video") or {}).get("durationMs"):
                secs = float(media["video"]["durationMs"]) / 1000
            if secs:
                found.append((f.name, str(it.get("id") or ""), round(secs, 1)))
    return found


def cmd_video(args) -> int:
    items = scan(args.input)

    print("视频下载（占位接口）")
    print("-" * 56)
    print(f"  本地带视频   {len(items)} 条")
    if items:
        total = sum(x[2] for x in items)
        print(f"  总时长       {total / 60:.1f} 分钟")
    print("  视频直链     ✗ 拿不到")
    print("-" * 56)
    print("为什么拿不到：")
    print("  灵造只给时长、不给地址（profile 用 media.video_duration_seconds，")
    print("  search 用 media.video.durationMs）。能给的只有笔记页链接，不是视频文件。")
    print()
    print("所以这次不会下任何东西。等接上视频源之后，流程是这样：")
    print("  1. 抓取完成后先问你 —— 这次有几条视频、要不要下、下要多少钱、占多大")
    print("  2. 默认是「下」（无非占点地方），也可以改成默认不下")
    print("  3. 不管默认是什么，都会先问一次 —— 要报成本，不能闷头下")
    print()
    print(f"  当前默认：{'下' if DEFAULT_DOWNLOAD else '不下'}")
    print(f"  改默认：   {Path(__file__).name} 顶部的 DEFAULT_DOWNLOAD")
    return 0


def build_parser(sub) -> None:
    p = sub.add_parser("video", help="视频下载（占位：灵造拿不到直链，不下载）")
    p.add_argument("input", nargs="+", help="profile JSON 或目录")
    p.set_defaults(func=cmd_video)
