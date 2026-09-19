# -*- coding: utf-8 -*-
"""抓回来的东西 → 能用的东西。

    # 搜来的笔记 → 统一字段（jsonl + csv）
    python 03_加工/run.py search 02_储存/01_lingzao/search-notes/

    # 博主全量笔记 → Excel
    python 03_加工/run.py table 02_储存/01_lingzao/analyze-user-profile/

    # 想全都要
    python 03_加工/run.py search <路径> --format all

输入可以是文件，也可以是目录（目录会递归找 .json）。
认命令靠 JSON 里的 `data.type`，不靠文件名。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from adapters import ad_lingzao  # noqa: E402
from adapters.base import (  # noqa: E402
    FIELD_LABELS,
    NoteRecord,
    expand_paths,
    flatten,
    write_csv,
    write_jsonl,
)

ROOT = HERE.parent
DEFAULT_OUT = ROOT / "04_产出" / "表格"

# 列宽（按 FIELD_LABELS 的顺序给，不够的用默认）
COL_WIDTHS = {
    "序号": 5, "数据来源": 9, "采集命令": 17, "账号名称": 16, "账号ID": 24,
    "标题": 38, "笔记ID": 22, "发布时间(UTC+8)": 19, "类型": 8, "xhs_note_type": 13,
    "时长(秒)": 9, "点赞": 9, "收藏": 9, "评论": 8, "分享": 8, "互动总量": 10,
    "收藏/点赞": 10, "协作标记": 9, "商品笔记": 9, "置顶": 6, "原始标签/描述": 44,
    "标签": 24, "字幕状态": 10, "字幕是否截断": 11, "笔记链接": 40, "封面URL": 44,
    "原始文件": 30,
}


# --------------------------------------------------------------------------
# 采集 → 统一记录
# --------------------------------------------------------------------------

def collect(inputs: list[str], only: str | None = None, quiet: bool = False):
    """按 data.type 认领文件，返回 (records, meta 列表)。认不出的文件单独报出来。"""
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
# Excel
# --------------------------------------------------------------------------

def build_excel(records: list[NoteRecord], out_path: Path, title: str = ""):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        sys.exit("缺 openpyxl。装一下：pip install openpyxl")

    wb = Workbook()
    ws = wb.active
    ws.title = "统一数据"
    labels = FIELD_LABELS
    ncol = len(labels)

    title_font = Font(name="微软雅黑", size=14, bold=True)
    header_font = Font(name="微软雅黑", size=11, bold=True)
    data_font = Font(name="微软雅黑", size=10)
    border = Border(left=Side(style="thin"), right=Side(style="thin"),
                    top=Side(style="thin"), bottom=Side(style="thin"))
    header_fill = PatternFill("solid", start_color="D9E1F2", end_color="D9E1F2")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)

    # 第 1 行标题
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
    ws.cell(1, 1, title or f"统一数据表｜{len(records)} 条").font = title_font
    ws.cell(1, 1).alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 34
    ws.row_dimensions[2].height = 6

    # 第 3 行表头
    for c, name in enumerate(labels, 1):
        cell = ws.cell(3, c, name)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = border
        cell.alignment = center
    ws.row_dimensions[3].height = 26

    # 数据
    for i, rec in enumerate(records, 1):
        row = i + 3
        values = rec.to_row(i)
        for c, name in enumerate(labels, 1):
            cell = ws.cell(row, c, values[name])
            cell.font = data_font
            cell.border = border
            cell.alignment = left if name in ("标题", "原始标签/描述", "标签",
                                              "笔记链接", "封面URL", "原始文件") else center
            if name == "收藏/点赞" and isinstance(values[name], (int, float)):
                cell.number_format = "0.0000"
        ws.row_dimensions[row].height = 22

    for c, name in enumerate(labels, 1):
        ws.column_dimensions[get_column_letter(c)].width = COL_WIDTHS.get(name, 14)

    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:{get_column_letter(ncol)}{3 + len(records)}"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path


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
        records.sort(key=lambda r: r.interactions_total, reverse=True)

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


# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="把 02_储存 里的原始数据，变成 04_产出 里能用的东西。",
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

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
