# -*- coding: utf-8 -*-
"""
JustOneAPI 的统一行结构 + 导出。

★ 这个源不套 30 列。
  灵造/得到大脑是「一条内容一条记录」，字段能对齐；这个源是「一个账号一条记录」，
  四个平台的原始结构差得太远（小红书的粉丝数在文本里、抖音的藏在 JSON 字符串里、
  公众号只回 1 条、视频号标题带 HTML）。硬套 30 列会有一半是「未知」。

  所以单独定一套 **账号表 13 列**，只留四个平台都说得通的字段，
  平台特有的字段整条挂在 `raw` 上，需要时能回溯。

★ 三态铁律照旧：没有就是 None → 导出成「未知」，绝不填 0。
  0 是「确实是 0 粉」，未知是「这个平台压根没给这个字段」。混了会误判。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

# 列名与顺序 —— 改动要同步 04_产出/README.md
COLUMNS = [
    "序号",
    "平台",
    "账号名称",
    "平台账号名",
    "账号ID",
    "粉丝数",
    "简介",
    "认证",
    "头像URL",
    "主页链接",
    "关键词",
    "抓取时间",
    "原始文件",
]

UNKNOWN = "未知"


def _cell(v):
    """None / 空串 一律变「未知」，不要 0、不要空。"""
    if v is None:
        return UNKNOWN
    if isinstance(v, str) and not v.strip():
        return UNKNOWN
    return v


def to_row(rec: dict, seq: int) -> list:
    """一条记录 → 一行（按 COLUMNS 顺序）。"""
    return [
        seq,
        _cell(rec.get("platform")),
        _cell(rec.get("name")),
        _cell(rec.get("account_name")),
        _cell(rec.get("account_id")),
        _cell(rec.get("fans")),
        _cell(rec.get("desc")),
        _cell(rec.get("verify")),
        _cell(rec.get("avatar")),
        _cell(rec.get("home_url")),
        _cell(rec.get("keyword")),
        _cell(rec.get("fetched_at")),
        _cell(rec.get("raw_file")),
    ]


def finalize(recs: list) -> list:
    """按粉丝数降序（未知的排最后），然后编号。"""
    def key(r):
        f = r.get("fans")
        return (0, -f) if isinstance(f, (int, float)) else (1, 0)
    ordered = sorted(recs, key=key)
    return [to_row(r, i) for i, r in enumerate(ordered, 1)]


def export_csv(rows: list, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        w.writerows(rows)
    return path


def export_jsonl(recs: list, path: Path) -> Path:
    """整条记录（含 raw）另存一份，方便回溯。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path
