# -*- coding: utf-8 -*-
"""得到大脑这条链自己的小工具。

**不引用本项目其他源的任何文件** —— 删掉 `03_加工/02_getnote/` 整个目录，
得到大脑的加工能力就干净地消失，不会留下断掉的引用。

（和灵造那边有一份内容重复的工具代码。这是拍过板的：**允许冗余**，
换「删目录即卸载」和「改一边碰不到另一边」。别提议合并。）
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

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


_TIME_CODE_RE = re.compile(r"^\d{1,2}[:：]\d{2}")


def extract_tags(text: str | None) -> list[str]:
    """从文本里抠出 `#话题`。

    两个坑（灵造那边踩过的，得到大脑这边同样适用）：

    1. 小红书的标签尾巴带 `[话题]`，要先摘掉，否则整串被吃。
    2. **正文里的 `#00:34 确定问题` 是时间码，不是话题** —— 不滤掉的话
       一列「标签」全是时间戳。

    （得到大脑的抖音内容用的是 `标题 #标签1 #标签2`，也是这个函数处理。）
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
    """读 JSON。文件里其实是 Markdown 时，给一句能救命的报错。"""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        head = text.lstrip()[:60].replace("\n", " ")
        raise ValueError(
            f"{p.name} 不是合法 JSON（文件头：{head}…）。"
            "得到大脑一般不会出现这种情况；若它是 Markdown，说明工具擅自改了落盘格式。"
        ) from e


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


def mtime_cst(p: Path) -> str:
    """抓取时刻 = 原始文件的 mtime（本机在 +8 区，直接格式化）。"""
    try:
        return datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return ""


def now_stamp(fmt: str = "%Y%m%d") -> str:
    return datetime.now().strftime(fmt)
