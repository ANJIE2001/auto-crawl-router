# -*- coding: utf-8 -*-
"""灵造这条链自己的小工具。

**不引用本项目其他源的任何文件** —— 删掉 `03_加工/01_lingzao/` 整个目录，
灵造的加工能力就干净消失，不留断引用。

（和 `02_getnote/util.py` 内容重复。这是拍过板的：**允许冗余**，
换「删目录即卸载」+「改一边碰不到另一边」。别提议合并。）
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

# 小红书时间一律按东八区落库
CST = timezone(timedelta(hours=8))


def safe_int(val: Any) -> int:
    """字符串数字、None、'1.2万' 都能忍。"""
    if val is None or isinstance(val, bool):
        return 0
    if isinstance(val, int):
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
    """从正文/描述里抠出 `#话题#`。

    两个坑：

    1. 小红书的标签尾巴带 `[话题]`，得先摘掉，否则整串被吃掉。
    2. **正文里的 `#00:34 确定问题` 是章节时间码，不是话题。**
       灵造的 search-notes 会把这类时间轴塞在 content 里，不滤掉的话
       一列「标签」全是时间戳。
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


def now_stamp(fmt: str = "%Y%m%d") -> str:
    return datetime.now().strftime(fmt)
