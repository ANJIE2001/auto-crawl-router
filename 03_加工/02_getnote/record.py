# -*- coding: utf-8 -*-
"""得到大脑这条链的统一字段。

设计取舍（用户 2026-09-19 拍板）：

- **代码分开**：这个文件只服务得到大脑，不引用灵造那边任何东西。
  删掉 `03_加工/02_getnote/` = 得到大脑加工能力干净消失。
- **列名对齐**：中文列名**和灵造用同一套词**。因为「输出层是给人读的」，
  两张表列名一致才能在 Excel 里对齐合并。列名约定写在 `03_加工/columns.md`。
- **允许冗余**：这份 dataclass 和灵造那份内容高度相似 —— 这是**故意的**。
  别提议抽公共父类。

⚠️ 得到大脑**没有**互动数据（点赞/收藏/评论/分享），也**没有时长**。
互动那几列照样存在，但值恒为 `None`（导出成「未知」）。
**「未知」不等于 0** —— 0 是「确实没互动」，未知是「这个来源根本没这个字段」。

⚠️ **封面**：详情接口（`/blogger/content/detail`）里带 `post_cover`，所以 `cover_url`
   这一列**填得上**（2026-09-20 起）。
   封面**图**由 `bundle.py` 归位：先取图池 `04_产出/图片/<昵称>_<账号ID>/<笔记ID>.<ext>`
   （缓存，用 `03_加工/02_getnote/run.py cover` 补），图池里没有就用手上的 `cover_url` **现下**。
   得到大脑的封面链接**不带签名、不过期**，现下是安全的（灵造那边正相反）。
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

UNKNOWN_LABEL = "未知"


# --------------------------------------------------------------------------
# 统一字段
# --------------------------------------------------------------------------

@dataclass
class NoteRecord:
    """一条得到大脑内容的统一形态。"""

    # --- 溯源 ---
    source: str = "getnote"
    command: str = ""            # blogger/content/detail / blogger/contents / bloggers（HTTP 路径）
    raw_file: str = ""           # 原始落盘文件路径
    collected_at: str = ""       # 抓取时刻（取原始文件的 mtime）

    # --- 身份 ---
    note_id: str = ""
    title: str = ""              # 只放原帖标题，绝不把博主名拼进来
    author_id: str = ""
    author_name: str = ""            # 通用名
    author_platform_name: str = ""   # 平台原生账号名（抖音名 / 小红书名）
    url: str = ""

    # --- 形态 ---
    note_type: str = ""          # video（得到大脑的 post_type）
    xhs_note_type: str = ""      # 得到大脑不给，恒空
    published_at: str = ""       # 'YYYY-MM-DD HH:MM:SS'
    duration_seconds: int | None = None

    # --- 指标（得到大脑全线为 None，导出成「未知」）---
    liked: int | None = None
    collected: int | None = None
    commented: int | None = None
    shared: int | None = None
    interactions_total: int | None = None
    collect_like_ratio: float | None = None

    # --- 标记（得到大脑不给，None = 未知）---
    is_sticky: bool = False
    is_collaboration: bool | None = None
    is_commerce_note: bool | None = None

    # --- 内容 ---
    desc: str = ""               # 原始标题串（含话题）
    tags: list[str] = field(default_factory=list)
    cover_url: str = ""          # CLI 拿不到封面；要封面得走 HTTP API
    ip_location: str = ""

    # --- 逐字稿（得到大脑的核心产出）---
    subtitle_status: str = ""        # ready（有稿）/ missing（无稿）/ ''（列表接口没有正文）
    subtitle_truncated: bool = False # 得到大脑给全文，恒 False
    subtitle_text: str = ""

    # --- 原样保留 ---
    raw: dict = field(default_factory=dict)

    def finalize(self) -> "NoteRecord":
        """算派生字段。适配器最后一步必须调它。"""
        nums = [self.liked, self.collected, self.commented, self.shared]
        if all(v is None for v in nums):
            self.interactions_total = None
            self.collect_like_ratio = None
        else:
            self.interactions_total = sum(v for v in nums if v is not None)
            self.collect_like_ratio = (
                round((self.collected or 0) / self.liked, 4) if self.liked else None
            )
        return self

    @staticmethod
    def _tri(v: bool | None) -> str:
        if v is None:
            return UNKNOWN_LABEL
        return "是" if v else "否"

    @staticmethod
    def _num(v: int | float | None) -> int | float | str:
        return UNKNOWN_LABEL if v is None else v

    def to_row(self, seq: int | None = None) -> dict:
        """导出用的中文表头行。列序与 FIELD_LABELS 一致。"""
        return {
            "序号": seq,
            "数据来源": self.source,
            "采集命令": self.command,
            "抓取时间": self.collected_at,
            "账号名称": self.author_name,
            "平台账号名": self.author_platform_name,
            "账号ID": self.author_id,
            "标题": self.title,
            "笔记ID": self.note_id,
            "发布时间(UTC+8)": self.published_at,
            "类型": self.note_type,
            "xhs_note_type": self.xhs_note_type,
            "时长(秒)": self._num(self.duration_seconds),
            "点赞": self._num(self.liked),
            "收藏": self._num(self.collected),
            "评论": self._num(self.commented),
            "分享": self._num(self.shared),
            "互动总量": self._num(self.interactions_total),
            "收藏/点赞": self._num(self.collect_like_ratio),
            "协作标记": self._tri(self.is_collaboration),
            "商品笔记": self._tri(self.is_commerce_note),
            "置顶": "是" if self.is_sticky else "否",
            "原始标签/描述": self.desc,
            "标签": " ".join(self.tags),
            "字幕状态": self.subtitle_status,
            "字幕是否截断": "是" if self.subtitle_truncated else "否",
            "逐字稿": self.subtitle_text,
            "笔记链接": self.url,
            "封面URL": self.cover_url,
            "原始文件": self.raw_file,
        }

    def to_dict(self) -> dict:
        return asdict(self)


FIELD_LABELS: list[str] = list(NoteRecord().to_row().keys())


# --------------------------------------------------------------------------
# 适配器基类
# --------------------------------------------------------------------------

@dataclass
class AdapterResult:
    source: str = ""
    command: str = ""
    raw_file: str = ""
    records: list[NoteRecord] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def stats(self) -> dict:
        n = len(self.records)
        s: dict[str, Any] = {"条数": n}
        if n:
            s["视频"] = sum(1 for r in self.records if r.note_type == "video")
            s["有逐字稿"] = sum(1 for r in self.records if r.subtitle_status == "ready")
            s["无逐字稿"] = sum(1 for r in self.records if r.subtitle_status == "missing")
        return s


class BaseAdapter:
    source: str = "getnote"
    command: str = ""
    suffixes: tuple[str, ...] = (".json",)

    def parse(self, path: str | Path) -> AdapterResult:
        raise NotImplementedError


# --------------------------------------------------------------------------
# 导出
# --------------------------------------------------------------------------

def flatten(results: Iterable[AdapterResult]) -> list[NoteRecord]:
    out: list[NoteRecord] = []
    for r in results:
        out.extend(r.records)
    return out


def records_to_rows(records: Iterable[NoteRecord]) -> list[dict]:
    return [rec.to_row(i) for i, rec in enumerate(records, 1)]


def write_jsonl(records: Iterable[NoteRecord], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as f:
        for rec in records:
            f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
    return p


def write_csv(records: Iterable[NoteRecord], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = records_to_rows(records)
    # Excel 打开 utf-8 csv 会乱码，加 BOM
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELD_LABELS)
        w.writeheader()
        w.writerows(rows)
    return p
