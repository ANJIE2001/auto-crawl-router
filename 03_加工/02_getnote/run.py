# -*- coding: utf-8 -*-
"""得到大脑的加工入口。**只服务得到大脑** —— 不引用灵造那边任何一个文件。

    # 博主内容 → 04_产出/博主/<昵称>_<账号ID>/ 目录树（含索引表）
    python 03_加工/02_getnote/run.py blogger "02_储存/02_getnote/blogger"

    # 只想出一张表，不拆目录树
    python 03_加工/02_getnote/run.py table "02_储存/02_getnote/blogger"

    # 补封面 → 04_产出/图片/（链接不过期，图池缺了随时补）
    python 03_加工/02_getnote/run.py cover "02_储存/02_getnote/blogger"

    # 视频下载（占位：拿不到直链，跑它只会告诉你现状）
    python 03_加工/02_getnote/run.py video "02_储存/02_getnote/blogger"

输入可以是文件，也可以是目录（目录会递归找 .json）。
⚠️ **认命令靠落盘文件名**（得到大脑的 JSON 里没有 `data.type` 那种字段）。

⚠️ **不调得到大脑 CLI、不花额度。** `cover` 会联网下载图片（URL 来自本地快照），
   图片 CDN 不计费 —— 所以照样不占额度。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import adapter as ad_getnote  # noqa: E402
from cover import build_parser as _build_cover_parser  # noqa: E402
from export import build_excel  # noqa: E402
from record import NoteRecord, flatten, write_csv, write_jsonl  # noqa: E402
from util import expand_paths  # noqa: E402
from video import build_parser as _build_video_parser  # noqa: E402

ROOT = HERE.parent.parent
DEFAULT_OUT = ROOT / "04_产出" / "表格"


# --------------------------------------------------------------------------

def collect(inputs: list[str], only: str | None = None, quiet: bool = False):
    """按得到大脑的落盘名认领文件。认不出的单独报出来 —— 别硬猜。"""
    seen: set[str] = set()
    results = []
    skipped: list[tuple[str, str]] = []

    for p in expand_paths(inputs, (".json",)):
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            cmd = ad_getnote.detect_command(p)
        except Exception as e:
            skipped.append((p.name, str(e)))
            continue
        if only and cmd != only:
            skipped.append((p.name, f"{cmd}，本轮只要 {only}"))
            continue
        try:
            results.append(ad_getnote.parse_auto(p))
        except Exception as e:
            skipped.append((p.name, str(e)))

    records = flatten(results)
    if not quiet:
        for r in results:
            st = r.stats()
            label = r.meta.get("author_name") or ""
            extra = " | ".join(f"{k} {v}" for k, v in st.items() if k != "条数" and v)
            print(f"  [{r.command}] {Path(r.raw_file).name}"
                  f"{'  ' + str(label) if label else ''}")
            print(f"      条数 {st['条数']}" + (f" | {extra}" if extra else ""))
        for name, why in skipped:
            print(f"  [跳过] {name} — {why}")

    return records, results, skipped


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------

def cmd_blogger(args):
    """博主内容 → `04_产出/博主/<昵称>_<账号ID>/` 目录树。

    结构和灵造那套**完全一致**（用户 2026-09-19 要求：「走的是得到大脑，
    但它也是批量抓的那种类型，产出按博主那套来，结构是一样的」）。
    """
    from bundle import export_bundle

    if len(args.input) != 1:
        print("一次只处理一个博主：传一个目录（里面是这批详情 JSON），或单个详情文件。")
        return 1

    try:
        r = export_bundle(args.input[0])
    except Exception as e:
        print(f"归档失败：{e}")
        return 1

    pack = r["pack_dir"]
    st = r["stats"]
    build_excel(r["records"], pack / "_索引.xlsx",
                f"得到大脑｜{r['author']}｜{len(r['records'])} 条")

    print(f"\n博主    {r['author']}（{r['author_id'] or '无ID'}）")
    print(f"目录    {pack}")
    print(f"  条数          {st['条数']}")
    print(f"  逐字稿        有 {st['有逐字稿']} ｜ 无 {st['无逐字稿']}")
    print(f"  封面          有 {st['封面成功']}"
          f"（图池 {st['封面来自图池']} ｜ 现下 {st['封面现下']}）｜ 缺 {st['封面缺失']}")
    print(f"  文件夹        新建 {st['新建目录']} ｜ 复用旧的 {st['复用旧目录']}")
    if st["封面缺失"]:
        print("  ⚠ 这些条既不在图池里、现下也没成 —— 先跑 `run.py cover` 补图池，再重跑本命令。")
        errs = sorted(set(r.get("cover_errs") or []))
        if errs:
            print("    下载失败原因：" + "；".join(errs[:5]))
    print(f"索引表  {pack / '_索引.xlsx'}")
    return 0


def cmd_table(args):
    """只出一张表（不拆目录树）。"""
    records, _results, _skipped = collect(args.input, only="blogger/content/detail")
    if not records:
        print("没有可导出的得到大脑博主内容。")
        print("  只认 `*_blogger-content_*.json` —— 那是逐条详情，逐字稿在里面。")
        return 1

    records.sort(key=lambda r: r.published_at, reverse=True)
    stamp = datetime.now().strftime("%Y%m%d")
    author = records[0].author_name or "unknown"
    out = Path(args.out) if args.out else DEFAULT_OUT / f"得到大脑_{stamp}_{author}.xlsx"
    build_excel(records, out, f"得到大脑｜{author}｜{len(records)} 条")

    ready = sum(1 for r in records if r.subtitle_status == "ready")
    print(f"\n共 {len(records)} 条（有逐字稿 {ready} / 无 {len(records) - ready}），已写出：\n  {out}")
    print("注：得到大脑不给互动数据（点赞/收藏/评论/分享）和时长，那几列显示「未知」——")
    print("    那是「该来源没有这项数据」，不是 0。别相加。")
    return 0


# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="得到大脑：把 02_储存/02_getnote 里的原始数据，变成 04_产出 里能用的东西。",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("blogger", help="博主内容 → 04_产出/博主/ 目录树")
    pb.add_argument("input", nargs="+", help="落盘目录（或单个详情 JSON）")
    pb.set_defaults(func=cmd_blogger)

    pt = sub.add_parser("table", help="博主内容 → 只出一张 xlsx")
    pt.add_argument("input", nargs="+", help="落盘目录（或单个详情 JSON）")
    pt.add_argument("--out", help="输出 xlsx 路径")
    pt.set_defaults(func=cmd_table)

    # 下载类动作：封面、视频**各自一个文件** —— 两边规则不一样（一个临时链接、
    # 一个永久链接），所以按源分开写，这儿只是把它们的命令行接进来。
    _build_cover_parser(sub)
    _build_video_parser(sub)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
