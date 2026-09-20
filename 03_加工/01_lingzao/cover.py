# -*- coding: utf-8 -*-
"""灵造 · 补封面。

    # 从原始 profile JSON 补
    python 03_加工/01_lingzao/run.py cover "02_储存/01_lingzao/analyze-user-profile/"

    # 从历史成品表补（只剩一张 xlsx 的老数据也能试）
    python 03_加工/01_lingzao/run.py cover "04_产出/表格/笔记原始数据表_2026-08-28_本自聚足.xlsx"

**为什么灵造要单独一个「补封面」**：
灵造的封面 URL **带过期签名**（查询串里的 `t=` 就是生成那一刻的十六进制时间戳），
实测约 3 小时后就全返回 HTTP 498。所以采集层 `collect.py` 会在落盘后立刻抢一遍 ——
但那一遍可能失败（网络抖动、刚好卡在过期边缘），事后再想补就没有入口了。
这个文件补的就是那个缺口。

⚠️ **窗口一过就救不回来。** 原始 JSON 里存的是**已经签好名**的 URL，过期就是一张废纸，
本动作也下不到。想拿新 URL 只能重新调灵造抓一次（**花钱**）。
所以：抓完尽快跑，别隔天。

**和得到大脑那边完全分开**：那份在 `03_加工/02_getnote/cover.py`，
它读的是**永久链接**（不过期），两边的处理逻辑不一样，别混。

**不调灵造 API、不花 credits** —— 只读本地文件里的 URL，去下载图片。
落 `04_产出/图片/<昵称>_<账号ID>/<笔记ID>.<ext>`。
图池是**缓存**：先拉下来再说，分类归位是 `bundle` 的事。
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from util import expand_paths, load_json  # noqa: E402

ROOT = HERE.parent.parent
POOL = ROOT / "04_产出" / "图片"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
_EXT = {"image/webp": ".webp", "image/jpeg": ".jpg", "image/jpg": ".jpg",
        "image/png": ".png", "image/gif": ".gif"}


def _slug(s, limit: int = 30) -> str:
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", str(s or "")).strip("_")
    return s[:limit] or "unknown"


# --------------------------------------------------------------------------
# 从本地文件里把「要下哪些图」列出来
# --------------------------------------------------------------------------

def targets_from_profile(path: Path) -> list[tuple[str, str, str]]:
    """profile JSON → [(图池目录名, 笔记ID, 封面URL)]"""
    data = load_json(path).get("data") or {}
    if data.get("type") != "analyze-user-profile":
        return []
    user = data.get("user") or {}
    dirname = f"{_slug(user.get('nickname') or 'unknown')}_{user.get('id') or 'noid'}"

    out: list[tuple[str, str, str]] = []
    for it in (data.get("items") or []):
        media = it.get("media") or {}
        nid = str(it.get("id") or "")
        url = media.get("cover_large_url") or media.get("cover_url") or ""
        if nid and url:
            out.append((dirname, nid, str(url)))
    return out


def targets_from_table(path: Path) -> list[tuple[str, str, str]]:
    """成品表 xlsx → [(图池目录名, 笔记ID, 封面URL)]

    老数据可能只剩这张表，但表里留着「封面原始URL」。那条链接若是抓取当时写下的，
    多半已经过期；要是有没过期的，就能顺手救回来。
    """
    from table import load_rows
    rows, _info = load_rows(path)

    out: list[tuple[str, str, str]] = []
    for row in rows:
        cells = {k: ("" if v is None else str(v).strip()) for k, v in row.items()}
        nid = cells.get("笔记ID") or cells.get("笔记Id") or ""
        url = cells.get("封面原始URL") or cells.get("封面URL") or ""
        name = cells.get("账号名称") or cells.get("博主") or "unknown"
        aid = cells.get("账号ID") or "noid"
        if nid and url:
            out.append((f"{_slug(name)}_{aid}", nid, url))
    return out


# --------------------------------------------------------------------------
# 下载
# --------------------------------------------------------------------------

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
        hint = "（签名已过期）" if e.code == 498 else ""
        return False, f"HTTP {e.code}{hint}"
    except Exception as e:
        return False, type(e).__name__

    if not body:
        return False, "下回来是空的"
    (dest_dir / (note_id + _EXT.get(ctype, ".jpg"))).write_bytes(body)
    return True, ""


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def cmd_cover(args) -> int:
    files = expand_paths(args.input, (".json", ".xlsx"))
    if not files:
        print("没找到 .json / .xlsx 文件。")
        return 1

    targets: list[tuple[str, str, str]] = []
    for f in files:
        try:
            if f.suffix.lower() == ".xlsx":
                targets += targets_from_table(f)
            else:
                targets += targets_from_profile(f)
        except Exception as e:
            print(f"跳过 {f.name}：{e}")

    if not targets:
        print("这些文件里没有带封面 URL 的笔记。")
        print("  · profile JSON 要有 data.type = analyze-user-profile")
        print("  · 成品表要有「封面原始URL」列")
        return 1

    by_dir: dict[str, list[tuple[str, str]]] = {}
    for dirname, nid, url in targets:
        by_dir.setdefault(dirname, []).append((nid, url))

    print(f"补封面　{len(by_dir)} 个博主｜共 {len(targets)} 条")
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
        if any("498" in w for w in reasons):
            print("⚠ 出现 498 = 签名已过期，**补不回来了**。")
            print("  想拿新链接只能重新调灵造抓一次 —— 那要花 credits，先跟用户报账。")
    print(f"图池  {POOL.relative_to(ROOT)}")
    print("（图池是缓存，先拉下来再说；归位到各条内容目录由 bundle 做）")
    return 0


def build_parser(sub) -> None:
    p = sub.add_parser("cover", help="补封面 → 04_产出/图片/（灵造用，带签名的链接）")
    p.add_argument("input", nargs="+", help="profile JSON / 成品表 xlsx，或它们的目录")
    p.set_defaults(func=cmd_cover)
