# -*- coding: utf-8 -*-
"""统一字段 + 通用工具。

规矩只有一条：**统一字段之外，原始条目整条挂在 `raw` 上。**

为什么要 raw：上游改字段、清洗写错、想回溯原始值，都靠它。任何来源的
适配器都不许只留洗过的字段，否则三天后你没法回答"这条笔记原来长什么样"。
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

# 小红书时间一律按东八区落库
CST = timezone(timedelta(hours=8))

# 三态：True / False / None（未知）。导出时转成 是 / 否 / 未知
UNKNOWN_LABEL = "未知"


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def safe_int(val: Any) -> int:
    """字符串数字、None、'1.2万' 都能忍。"""
    if val is None or isinstance(val, bool):
        return 0
    if isinstance(val, (int,)):
        return val
    if isinstance(val, float):
        return int(val)
    s = str(val).strip().replace(",", "")
    if not s:
        return 0
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def iso_to_cst(iso_str: str | None) -> str:
    """ISO8601（含 Z）→ 'YYYY-MM-DD HH:MM:SS'（东八区）。失败返回空串。"""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return str(iso_str)[:19]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CST).strftime("%Y-%m-%d %H:%M:%S")


def ms_to_cst(ms: Any) -> str:
    """毫秒时间戳 → 'YYYY-MM-DD HH:MM:SS'（东八区）。"""
    n = safe_int(ms)
    if n <= 0:
        return ""
    try:
        return datetime.fromtimestamp(n / 1000, tz=CST).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return ""


_TIME_CODE_RE = re.compile(r"^\d{1,2}[:：]\d{2}")


def extract_tags(text: str | None) -> list[str]:
    """从正文/描述里抠出 #话题#。

    比看上去麻烦，两个坑：

    1. 小红书的标签尾巴带个 `[话题]`，得先摘掉，否则整串都会被吃掉。
    2. **正文里的 `#00:34 确定问题` 是章节时间码，不是话题。**
       灵造的 search-notes 会把这类时间轴塞在 content 里，不滤掉的话
       一列"标签"全是时间戳。
    """
    if not text:
        return []
    s = str(text).replace("[话题]", "")
    out: list[str] = []
    for t in re.findall(r"#([^#\s\[\]]+)", s):
        t = t.strip()
        if not t or t in out:
            continue
        if _TIME_CODE_RE.match(t):
            continue
        out.append(t)
    return out


def load_json(path: str | Path) -> dict:
    """读 JSON。**文件里其实是 Markdown 时给出能救命的报错。**"""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        head = text.lstrip()[:60].replace("\n", " ")
        if head.startswith("#"):
            raise ValueError(
                f"{p.name} 其实是 Markdown，不是 JSON（文件头：{head}…）。"
                "灵造有时会把结果直接存成 md。这种情况要么手工处理，"
                "要么让采集层加 --format json 重新拉一份。"
            ) from e
        raise ValueError(f"{p.name} 不是合法 JSON：{e}") from e


def expand_paths(paths: Iterable[str | Path], suffixes: tuple[str, ...] = (".json",)) -> list[Path]:
    """文件直接收；目录就递归找指定后缀，忽略 __pycache__。"""
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            for child in sorted(p.rglob("*")):
                if child.is_file() and child.suffix.lower() in suffixes:
                    out.append(child)
        else:
            raise FileNotFoundError(f"路径不存在：{p}")
    return out


# --------------------------------------------------------------------------
# 统一字段
# --------------------------------------------------------------------------

@dataclass
class NoteRecord:
    """一条笔记的统一形态。所有来源都吐这个。"""

    # --- 溯源：这一条是从哪来的 ---
    source: str = ""            # lingzao / getnote / browser / api_x
    command: str = ""           # search-notes / analyze-user-profile / ...
    raw_file: str = ""          # 原始文件路径（相对项目根最好）

    # --- 身份 ---
    note_id: str = ""
    title: str = ""
    author_id: str = ""
    author_name: str = ""
    url: str = ""

    # --- 形态 ---
    note_type: str = ""          # video / normal / ads
    xhs_note_type: str = ""      # video / image
    published_at: str = ""       # 'YYYY-MM-DD HH:MM:SS' 东八区
    duration_seconds: int = 0

    # --- 指标 ---
    liked: int = 0
    collected: int = 0
    commented: int = 0
    shared: int = 0
    interactions_total: int = 0      # finalize() 算
    collect_like_ratio: float = 0.0  # finalize() 算

    # --- 标记（三态） ---
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
        """算派生字段。适配器最后一步必须调它。"""
        self.interactions_total = self.liked + self.collected + self.commented + self.shared
        self.collect_like_ratio = (
            round(self.collected / self.liked, 4) if self.liked > 0 else 0.0
        )
        return self

    # 三态 → 中文
    @staticmethod
    def _tri(v: bool | None) -> str:
        if v is None:
            return UNKNOWN_LABEL
        return "是" if v else "否"

    def to_row(self, seq: int | None = None) -> dict:
        """导出用的中文表头行。列序与 FIELD_LABELS 一致。"""
        return {
            "序号": seq,
            "数据来源": self.source,
            "采集命令": self.command,
            "账号名称": self.author_name,
            "账号ID": self.author_id,
            "标题": self.title,
            "笔记ID": self.note_id,
            "发布时间(UTC+8)": self.published_at,
            "类型": self.note_type,
            "xhs_note_type": self.xhs_note_type,
            "时长(秒)": self.duration_seconds,
            "点赞": self.liked,
            "收藏": self.collected,
            "评论": self.commented,
            "分享": self.shared,
            "互动总量": self.interactions_total,
            "收藏/点赞": self.collect_like_ratio,
            "协作标记": self._tri(self.is_collaboration),
            "商品笔记": self._tri(self.is_commerce_note),
            "置顶": "是" if self.is_sticky else "否",
            "原始标签/描述": self.desc,
            "标签": " ".join(self.tags),
            "字幕状态": self.subtitle_status,
            "字幕是否截断": "是" if self.subtitle_truncated else "否",
            "笔记链接": self.url,
            "封面URL": self.cover_url,
            "原始文件": self.raw_file,
        }

    def to_dict(self) -> dict:
        """完整字典，含 raw。写 jsonl 用这个。"""
        return asdict(self)


# 统一字段的列名与顺序（导出唯一真源，别在别处再抄一遍）
FIELD_LABELS: list[str] = list(NoteRecord().to_row().keys())


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
        s: dict[str, int] = {"条数": n}
        if n:
            s["视频"] = sum(1 for r in self.records if r.note_type == "video")
            s["图文"] = sum(1 for r in self.records if r.note_type in ("normal", "image"))
            s["广告"] = sum(1 for r in self.records if r.note_type == "ads")
            s["字幕ready"] = sum(1 for r in self.records if r.subtitle_status == "ready")
            s["字幕截断"] = sum(1 for r in self.records if r.subtitle_truncated)
        return s


class BaseAdapter:
    """所有来源适配器的爹。子类只需实现 parse()。"""

    source: str = ""
    command: str = ""
    suffixes: tuple[str, ...] = (".json",)

    def parse(self, path: str | Path) -> AdapterResult:
        raise NotImplementedError

    def parse_paths(self, paths: Iterable[str | Path]) -> list[AdapterResult]:
        results = []
        for p in expand_paths(paths, self.suffixes):
            results.append(self.parse(p))
        return results


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
        writer = csv.DictWriter(f, fieldnames=FIELD_LABELS)
        writer.writeheader()
        writer.writerows(rows)
    return p
