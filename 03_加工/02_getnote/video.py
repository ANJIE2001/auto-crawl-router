# -*- coding: utf-8 -*-
"""得到大脑 · 视频下载（**占位接口，当前不下载任何东西**）。

    python 03_加工/02_getnote/run.py video "02_储存/02_getnote/blogger/"

**为什么现在是空的**：这条链拿不到视频文件地址。
`post_url` 给的是抖音的**分享页**（`iesdouyin.com/share/video/<id>/`），
不是 `.mp4` 那样的直链。要变成能下的地址，得再加一层解析（比如 yt-dlp 之类），
那是新增依赖，不是改几行的事 —— 所以先把接口和询问流程摆好。

将来接上之后，流程按用户定的走：

    1. **抓取完成后先问一句**，不自己决定：
         · 这次有几条带视频？
         · 要不要下？
         · 下要多少钱、占多大地方？
    2. 默认**下**（无非占点地方），也可以改成默认不下 —— 见下面 `DEFAULT_DOWNLOAD`
    3. **不管默认是什么，都会先问一次** —— 因为要报成本，不能闷头下

和灵造那边完全分开：那份在 `03_加工/01_lingzao/video.py`。
两边规则不一样（一个抓临时链接、一个抓永久链接），别混。
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


def _iter_dicts(obj):
    """把嵌套结构里所有 dict 拉平 —— 响应层级不固定，省得写死路径。"""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _iter_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_dicts(v)


def scan(paths) -> dict:
    """扫本地 JSON，数一数有多少条视频、一共见过多少条内容。

    得到大脑的 `post_type` 会是 `video` / `img_text` 这种值，按它分。
    按 `post_id_alias` 去重（同一条内容在列表和详情里会出现两次）。
    """
    files = expand_paths(paths, (".json",))
    seen_all: set[str] = set()
    seen_video: set[str] = set()

    for f in files:
        try:
            j = load_json(f)
        except Exception:
            continue
        for d in _iter_dicts(j):
            alias = d.get("post_id_alias")
            ptype = d.get("post_type")
            if not alias or not ptype:
                continue
            a = str(alias)
            seen_all.add(a)
            if str(ptype).lower() == "video":
                seen_video.add(a)

    return {"files": len(files), "全部": len(seen_all), "视频": len(seen_video)}


def cmd_video(args) -> int:
    st = scan(args.input)

    print("视频下载（占位接口）")
    print("-" * 56)
    print(f"  扫了文件     {st['files']} 个")
    print(f"  内容条目     {st['全部']} 条")
    print(f"  其中视频     {st['视频']} 条")
    print("  视频直链     ✗ 拿不到")
    print("-" * 56)
    print("为什么拿不到：")
    print("  post_url 给的是抖音**分享页**（iesdouyin.com/share/video/…），")
    print("  不是视频文件地址。要变成能下的直链，得再加一层解析（如 yt-dlp）。")
    print()
    print("所以这次不会下任何东西。等接上之后，流程是这样：")
    print("  1. 抓取完成后先问你 —— 这次有几条视频、要不要下、下要多少钱、占多大")
    print("  2. 默认是「下」（无非占点地方），也可以改成默认不下")
    print("  3. 不管默认是什么，都会先问一次 —— 要报成本，不能闷头下")
    print()
    print(f"  当前默认：{'下' if DEFAULT_DOWNLOAD else '不下'}")
    print(f"  改默认：   {Path(__file__).name} 顶部的 DEFAULT_DOWNLOAD")
    return 0


def build_parser(sub) -> None:
    p = sub.add_parser("video", help="视频下载（占位：拿不到直链，不下载）")
    p.add_argument("input", nargs="+", help="落盘目录或 JSON 文件")
    p.set_defaults(func=cmd_video)
