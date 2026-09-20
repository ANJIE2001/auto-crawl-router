# -*- coding: utf-8 -*-
"""灵造这条链的统一字段。

规矩只有一条：**统一字段之外，原始条目整条挂在 `raw` 上。**
为什么要 raw：上游改字段、清洗写错、想回溯原始值，都靠它。

设计取舍（用户 2026-09-19 拍板）：

- **代码分开**：这个文件只服务灵造，不引用得到大脑那边任何东西。
  删掉 `03_加工/01_lingzao/` = 灵造加工能力干净消失。
- **列名对齐**：中文列名和得到大脑**同一套词**（约定写在 `03_加工/columns.md`），
  因为「输出层是给人读的」，列名一致才能在 Excel 里对齐。
- **允许冗余**：这份 dataclass 和得到大脑那份内容高度相似 —— 这是**故意的**。
  别提议抽公共父类。
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
    """一条笔记的统一形态。所有灵造命令都吐这个。"""

    # --- 溯源：这一条是从哪来的 ---
    source: str = "lingzao"      # lingzao / getnote / browser / api_x
    command: str = ""            # search-notes / analyze-user-profile / ...
    raw_file: str = ""
    collected_at: str = ""       # 这批数据抓取到的时刻
                                 # 博主的点赞收藏每天在涨，不记时间就说不清是哪天的数

    # --- 身份 ---
    note_id: str = ""
    title: str = ""                  # 只放笔记标题，绝不把博主名拼进来
    author_id: str = ""
    author_name: str = ""            # 通用名
    author_platform_name: str = ""   # 平台原生账号名（小红书昵称）
    url: str = ""

    # --- 形态 ---
    note_type: str = ""          # video / normal / ads
    xhs_note_type: str = ""      # video / image
    published_at: str = ""       # 'YYYY-MM-DD HH:MM:SS' 东八区
    duration_seconds: int | None = None

    # --- 指标 ---
    # 三态：给了数字就是真值；None = 该来源没有这项数据（导出成「未知」）。
    # ⚠️ 别把 None 当 0 —— 0 是「确实没互动」，None 是「压根没这个字段」。
    liked: int | None = None
    collected: int | None = None
    commented: int | None = None
    shared: int | None = None
    interactions_total: int | None = None      # finalize() 算
    collect_like_ratio: float | None = None    # finalize() 算

    # --- 标记（三态）---
    is_sticky: bool = False
    is_collaboration: bool | None = None
    is_commerce_note: bool | None = None

    # --- 内容 ---
    desc: str = ""
    tags: list[str] = field(default_factory=list)
    cover_url: str = ""
    ip_location: str = ""

    # --- 字幕 ---
    subtitle_status: str = ""        # ready / failed / missing / ''
    subtitle_truncated: bool = False
    subtitle_text: str = ""          # 纯文本（截断预览也算，看 subtitle_truncated）

    # --- 原样保留 ---
    raw: dict = field(default_factory=dict)

    def finalize(self) -> "NoteRecord":
        """算派生字段。适配器最后一步必须调它。

        三态规则：四项互动**全是 None** → 合计和比值也是 None；
        只要有一项有值，就按有值的求和，缺的那项当 0 参与。
        """
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
    """一个原始文件 → 一批统一记录，外加这个文件的元信息。"""

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
            s["图文"] = sum(1 for r in self.records if r.note_type in ("normal", "image"))
            s["广告"] = sum(1 for r in self.records if r.note_type == "ads")
            s["字幕ready"] = sum(1 for r in self.records if r.subtitle_status == "ready")
            s["字幕截断"] = sum(1 for r in self.records if r.subtitle_truncated)
        return s


class BaseAdapter:
    source: str = "lingzao"
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
    # excel 打开 utf-8 csv 会乱码，加 BOM
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELD_LABELS)
        w.writeheader()
        w.writerows(rows)
    return p
