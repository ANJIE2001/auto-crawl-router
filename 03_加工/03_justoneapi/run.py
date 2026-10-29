#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
JustOneAPI 加工层入口：把 02_储存 里的原始 JSON 变成 04_产出 里的表。

    python 03_加工/03_justoneapi/run.py accounts
    python 03_加工/03_justoneapi/run.py accounts --keyword 养生
    python 03_加工/03_justoneapi/run.py accounts --out "随便什么路径.xlsx"

★ 只做「账号搜索」这一类动作。笔记详情、视频列表的结构完全不同，
  等各自的 adapter 写好了再往这里加，别混在一起解析。
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
STORE = ROOT / "02_储存" / "03_justoneapi"
OUT_DIR = ROOT / "04_产出" / "表格"

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import adapter          # noqa: E402  同目录扁平导入（目录名以数字开头，不是包）
import record           # noqa: E402
import export           # noqa: E402


def cmd_accounts(args) -> int:
    if not STORE.is_dir():
        print(f"还没有原始数据：{STORE}")
        print("  先抓一次：python 01_采集/03_justoneapi/collect.py accounts --platform xhs --keyword 养生 --go")
        return 1

    recs, scanned, skipped = adapter.load_all(STORE, keyword=args.keyword)
    print("账号搜索 · 加工")
    print("=" * 60)
    print(f"原始目录    {STORE.relative_to(ROOT)}")
    if args.keyword:
        print(f"关键词      {args.keyword}")
    print(f"扫过的文件  {scanned} 个")
    print(f"解析出      {len(recs)} 条账号")

    if skipped:
        print(f"\n跳过 {len(skipped)} 个文件：")
        for name, why in skipped[:8]:
            print(f"  - {name}：{why}")
        if len(skipped) > 8:
            print(f"  …还有 {len(skipped) - 8} 个")

    if not recs:
        print("\n没有可解析的记录。")
        return 1

    print("\n平台分布：")
    for plat in ("小红书", "抖音", "视频号", "公众号"):
        n = sum(1 for r in recs if r.get("platform") == plat)
        if n:
            fans = [r["fans"] for r in recs if r.get("platform") == plat and isinstance(r.get("fans"), int)]
            top = f"　粉丝最高 {max(fans):,}" if fans else "　粉丝数：未知"
            print(f"  {plat:5} {n:3} 条{top}")

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    tag = re.sub(r'[\\/:*?"<>|\s]+', "_", args.keyword or "全部")[:20] or "全部"
    stem = f"账号搜索_{tag}_{ts}"

    if args.out:
        xlsx_path = Path(args.out)
    else:
        xlsx_path = OUT_DIR / f"{stem}.xlsx"

    rows = record.finalize(recs)
    export.export_xlsx(recs, xlsx_path)
    csv_path = xlsx_path.with_suffix(".csv")
    record.export_csv(rows, csv_path)
    jsonl_path = xlsx_path.with_suffix(".jsonl")
    record.export_jsonl(recs, jsonl_path)

    print("\n产出：")
    for p in (xlsx_path, csv_path, jsonl_path):
        print(f"  {p.relative_to(ROOT) if str(p).startswith(str(ROOT)) else p}")
    print(f"\n★ 一共 {len(rows)} 行，打开 xlsx 就能看。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="run.py",
        description="JustOneAPI 加工层：原始 JSON → 表格",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("accounts", help="账号搜索结果 → 表格（总表 + 每平台分表）")
    p.add_argument("--keyword", help="只处理这个关键词的结果")
    p.add_argument("--out", help="指定输出 xlsx 路径")
    p.set_defaults(func=cmd_accounts)

    args = ap.parse_args()
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
