# -*- coding: utf-8 -*-
"""得到大脑 · 补封面。

    python 03_加工/02_getnote/run.py cover "02_储存/02_getnote/blogger/"

**和灵造那边完全分开，两边规则不一样：**

| | 灵造 | 得到大脑 |
|---|---|---|
| 封面字段 | `media.cover_large_url` | `post_cover` |
| 链接带签名？ | **带**（`t=` 时间戳） | **不带** |
| 有效期 | 约 3 小时，过了全 498 | **永久**，什么时候补都行 |
| 怎么办 | **必须抓完立刻抢**，晚了就废 | 不急，图池缺了随时补 |

所以灵造那份要「抢救」，这份只要「补缺」。**别把一边的紧张感套到另一边。**

数据从哪来：**单条详情的 JSON**（`*_blogger-content_*.json`）—— 那张是走 HTTP
`/blogger/content/detail` 拉的，里面就带 `post_cover`。
（2026-09-20 起得到大脑采集全走 HTTP，详情一次给齐逐字稿 + 封面 + 原链接。）

落 `04_产出/图片/<昵称>_<follow_id>/<笔记ID>.<ext>`。
图池是**缓存**：先拉下来再说，归位到各条内容目录由 `bundle` 做。
"""

from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from adapter import _author_from_dir  # noqa: E402
from util import expand_paths, load_json  # noqa: E402

ROOT = HERE.parent.parent
POOL = ROOT / "04_产出" / "图片"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
_EXT = {"image/webp": ".webp", "image/jpeg": ".jpg", "image/jpg": ".jpg",
        "image/png": ".png", "image/gif": ".gif"}

# 详情文件的落盘名：<日期>_blogger-content_<post_id_alias>.json
_RE_DETAIL = re.compile(r"(?:^|_)blogger-content_(?P<alias>[^.]+)\.json$")


def _slug(s, limit: int = 40) -> str:
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", str(s or "")).strip("_")
    return s[:limit] or "unknown"


def target_from_detail(path: Path, dirname: str) -> tuple[str, str, str] | None:
    """单条详情 JSON → (图池目录名, 笔记ID, 封面URL)。不是详情、或没封面就返回 None。"""
    try:
        data = load_json(path).get("data") or {}
    except Exception:
        return None
    if not isinstance(data, dict) or "post_cover" not in data:
        return None                      # 不是详情文件（可能是 bloggers / 列表）

    # 身份：详情里的 post_id_alias 是**空串**，只能从文件名取
    m = _RE_DETAIL.search(path.name)
    nid = m.group("alias") if m else str(data.get("post_id_alias") or "")
    url = str(data.get("post_cover") or "").strip()
    if not nid or not url:
        return None
    return (dirname, nid, url)


def download_one(url: str, dest_dir: Path, note_id: str) -> tuple[bool, str]:
    """下一条。返回 (下来了?, 说明)。已经有的不重下。"""
    if any((dest_dir / (note_id + ext)).is_file() for ext in _EXT.values()):
        return False, "已有"

    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, type(e).__name__

    if not body:
        return False, "下回来是空的"
    (dest_dir / (note_id + _EXT.get(ctype, ".jpg"))).write_bytes(body)
    return True, ""


def cmd_cover(args) -> int:
    files = expand_paths(args.input, (".json",))
    if not files:
        print("没找到 .json 文件。")
        return 1

    by_dir: dict[str, list[tuple[str, str]]] = {}
    author_cache: dict[str, str] = {}

    for f in files:
        parent = str(f.parent)
        if parent not in author_cache:
            a = _author_from_dir(f.parent)
            author_cache[parent] = f"{_slug(a['name'] or 'unknown', 30)}_{a['follow_id'] or 'noid'}"
        t = target_from_detail(f, author_cache[parent])
        if t:
            dirname, nid, url = t
            by_dir.setdefault(dirname, []).append((nid, url))

    if not by_dir:
        print("这些文件里没有带封面的**详情**（`*_blogger-content_*.json`）。")
        print("  封面在详情里 —— 先抓详情：")
        print("    python 01_采集/02_getnote/collect.py details --topic <topic_id> --follow <follow_id>")
        return 1

    total = sum(len(v) for v in by_dir.values())
    print(f"补封面　{len(by_dir)} 个博主｜共 {total} 条")
    print("-" * 56)

    ok = skipped = failed = 0
    reasons: dict[str, int] = {}
    for dirname, items in by_dir.items():
        out_dir = POOL / dirname
        for nid, url in items:
            good, why = download_one(url, out_dir, nid)
            if good:
                ok += 1
            elif why == "已有":
                skipped += 1
            else:
                failed += 1
                reasons[why] = reasons.get(why, 0) + 1
        print(f"  {dirname}   共 {len(items)} 条")

    print("-" * 56)
    print(f"成功 {ok}｜已有跳过 {skipped}｜失败 {failed}")
    if reasons:
        print("失败原因：")
        for why, n in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  {n} 条   {why}")
        print("（得到大脑的封面链接**不过期**，失败了重跑一次基本就能好）")
    print(f"图池  {POOL.relative_to(ROOT)}")
    print("（图池是缓存，先拉下来再说；归位到各条内容目录由 bundle 做）")
    return 0


def build_parser(sub) -> None:
    p = sub.add_parser("cover", help="补封面 → 04_产出/图片/（得到大脑用，永久链接）")
    p.add_argument("input", nargs="+", help="详情 JSON（*_blogger-content_*.json）或它的目录")
    p.set_defaults(func=cmd_cover)
