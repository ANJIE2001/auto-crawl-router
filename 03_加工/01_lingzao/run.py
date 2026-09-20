# -*- coding: utf-8 -*-
"""灵造的加工入口。**只服务灵造** —— 不引用得到大脑那边任何一个文件。

    # 搜来的笔记 → 统一字段（jsonl + csv + xlsx）
    python 03_加工/01_lingzao/run.py search "02_储存/01_lingzao/search-notes/"

    # 博主全量笔记 → Excel
    python 03_加工/01_lingzao/run.py table "02_储存/01_lingzao/analyze-user-profile/"

    # 博主全量 → 一条内容一个文件夹
    python 03_加工/01_lingzao/run.py bundle "02_储存/01_lingzao/analyze-user-profile/xxx.json"

    # 补封面 → 04_产出/图片/（灵造的封面 URL 带签名，约 3 小时过期，越早跑越好）
    python 03_加工/01_lingzao/run.py cover "02_储存/01_lingzao/analyze-user-profile/"

    # 视频下载（占位：灵造拿不到视频直链，跑它只会告诉你现状）
    python 03_加工/01_lingzao/run.py video "02_储存/01_lingzao/analyze-user-profile/"

输入可以是文件，也可以是目录（目录会递归找 .json）。
认命令靠 JSON 里的 `data.type`，不靠文件名。

⚠️ **不调灵造 CLI、不花 credits。** `cover` 会联网下载图片（读的是本地 JSON 里
   已经存好的 URL），但图片 CDN 不计费 —— 所以照样一分钱不花。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import adapter as ad_lingzao  # noqa: E402
from cover import build_parser as _build_cover_parser  # noqa: E402
from export import build_excel  # noqa: E402
from record import (  # noqa: E402
    FIELD_LABELS,
    NoteRecord,
    flatten,
    write_csv,
    write_jsonl,
)
from util import expand_paths  # noqa: E402
from video import build_parser as _build_video_parser  # noqa: E402

ROOT = HERE.parent.parent
DEFAULT_OUT = ROOT / "04_产出" / "表格"


# --------------------------------------------------------------------------
# 采集 → 统一记录
# --------------------------------------------------------------------------

def collect(inputs: list[str], only: str | None = None, quiet: bool = False):
    """按 data.type 认领文件，返回 (records, results, skipped)。认不出的单独报出来。"""
    seen: set[str] = set()
    results = []
    skipped: list[tuple[str, str]] = []

    for p in expand_paths(inputs, (".json",)):
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            cmd = ad_lingzao.detect_command(p)
        except Exception as e:  # md 冒充 json、空壳文件等
            skipped.append((p.name, str(e)))
            continue
        if only and cmd != only:
            skipped.append((p.name, f"data.type={cmd}，本轮只要 {only}"))
            continue
        try:
            results.append(ad_lingzao.parse_auto(p))
        except Exception as e:
            skipped.append((p.name, str(e)))

    records = flatten(results)
    if not quiet:
        for r in results:
            st = r.stats()
            label = r.meta.get("query") or r.meta.get("author_name") or ""
            extra = " | ".join(f"{k} {v}" for k, v in st.items() if k != "条数" and v)
            print(f"  [{r.command}] {Path(r.raw_file).name}"
                  f"{'  ' + str(label) if label else ''}")
            print(f"      条数 {st['条数']}" + (f" | {extra}" if extra else ""))
            if r.meta.get("cost_credits") is not None:
                print(f"      credits {r.meta['cost_credits']}"
                      f"（剩余 {r.meta.get('remaining_credits')}）")
            if r.meta.get("subtitle_artifact_url"):
                print(f"      完整字幕 artifact：{r.meta['subtitle_artifact_url']}")
            elif r.meta.get("subtitle_artifact_status") == "missing":
                print("      完整字幕 artifact：无（这条博主没有 ready 字幕）")
        for name, why in skipped:
            print(f"  [跳过] {name} — {why}")

    return records, results, skipped


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------

def cmd_search(args):
    records, _results, _skipped = collect(args.input, only="search-notes")
    if not records:
        print("没有可导出的 search-notes 记录。")
        return 1

    # 按互动总量排序，爆款先看
    if not args.no_sort:
        records.sort(key=lambda r: (r.interactions_total or 0), reverse=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    query = next((r for r in [x.meta.get("query") for x in _results] if r), "")
    base = f"搜索笔记_{query or 'unknown'}_{stamp}"
    out_dir = Path(args.out) if args.out else DEFAULT_OUT
    out_dir.mkdir(parents=True, exist_ok=True)

    made = []
    if args.format in ("jsonl", "all"):
        made.append(write_jsonl(records, out_dir / f"{base}.jsonl"))
    if args.format in ("csv", "all"):
        made.append(write_csv(records, out_dir / f"{base}.csv"))
    if args.format in ("xlsx", "all"):
        title = f"搜索笔记｜{query or ''}｜{len(records)} 条".replace("｜｜", "｜")
        made.append(build_excel(records, out_dir / f"{base}.xlsx", title))

    print(f"\n共 {len(records)} 条，已写出：")
    for m in made:
        print(f"  {m}")
    if _skipped:
        print(f"（跳过 {len(_skipped)} 个文件）")
    return 0


def cmd_table(args):
    records, _results, _skipped = collect(args.input, only="analyze-user-profile")
    if not records:
        print("没有可导出的 analyze-user-profile 记录。")
        return 1

    if not args.no_sort:
        records.sort(key=lambda r: r.published_at, reverse=True)

    stamp = datetime.now().strftime("%Y%m%d")
    author = records[0].author_name or "unknown"
    out = Path(args.out) if args.out else DEFAULT_OUT / f"笔记原始数据表_{stamp}_{author}.xlsx"
    build_excel(records, out, f"笔记原始数据表｜{author}｜{len(records)} 条")

    print(f"\n共 {len(records)} 条，已写出：\n  {out}")
    if _skipped:
        print(f"（跳过 {len(_skipped)} 个文件）")
    return 0


def cmd_bundle(args):
    """博主全量 → 一条内容一个文件夹，外加一份索引表。"""
    from bundle import export_bundle

    files = expand_paths(args.input, (".json", ".xlsx", ".xls"))
    if len(files) != 1:
        print(f"bundle 一次只处理一个博主，这次数到 {len(files)} 个文件。"
              "指定具体文件，或者换一个只含单个博主的目录。")
        return 1

    try:
        r = export_bundle(files[0], args.subtitles, covers=not args.no_cover)
    except Exception as e:
        print(f"导出失败：{e}")
        return 1

    pack = r["pack_dir"]
    st = r["stats"]
    build_excel(r["records"], pack / "_索引.xlsx",
                f"笔记原始数据表｜{r['author']}｜{len(r['records'])} 条")

    print(f"\n博主    {r['author']}（{r['author_id']}）")
    print(f"目录    {pack}")
    print(f"  条数          {st['条数']}")
    print(f"  逐字稿        全文 {st['逐字稿全文']} ｜ 只有截断预览 {st['逐字稿截断']}")
    print(f"  封面          成功 {st['封面成功']}"
          f"（其中图池 {st['封面来自图池']}）｜ 失败 {st['封面失败']}")
    print(f"  文件夹        新建 {st['新建目录']} ｜ 复用旧的 {st['复用旧目录']}")
    if r["collection"]:
        print(f"  合集          {r['collection']}")
    for err in r["cover_errors"]:
        print(f"  ⚠ 封面：{err}")
    print(f"索引表  {pack / '_索引.xlsx'}")
    return 0


# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="灵造：把 02_储存/01_lingzao 里的原始数据，变成 04_产出 里能用的东西。",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("search", help="search-notes → 统一字段表")
    ps.add_argument("input", nargs="+", help="JSON 文件或目录")
    ps.add_argument("--out", help=f"输出目录（默认 {DEFAULT_OUT}）")
    ps.add_argument("--format", choices=["jsonl", "csv", "xlsx", "all"], default="all",
                    help="默认 all")
    ps.add_argument("--no-sort", action="store_true", help="不按互动总量排序")
    ps.set_defaults(func=cmd_search)

    pt = sub.add_parser("table", help="analyze-user-profile → Excel")
    pt.add_argument("input", nargs="+", help="profile JSON 文件或目录")
    pt.add_argument("--out", help="输出 xlsx 路径")
    pt.add_argument("--no-sort", action="store_true", help="不按发布时间排序")
    pt.set_defaults(func=cmd_table)

    pb = sub.add_parser("bundle", help="analyze-user-profile → 一条内容一个文件夹")
    pb.add_argument("input", nargs="+", help="profile JSON，或已导出的成品表 xlsx")
    pb.add_argument("--subtitles", help="逐字稿合集 md（不给就按博主名自动找）")
    pb.add_argument("--no-cover", action="store_true", help="不下载封面")
    pb.set_defaults(func=cmd_bundle)

    # 下载类动作：封面、视频**各自一个文件** —— 两边规则不一样（一个临时链接、
    # 一个永久链接），所以按源分开写，这儿只是把它们的命令行接进来。
    _build_cover_parser(sub)
    _build_video_parser(sub)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
