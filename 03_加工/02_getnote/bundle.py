# -*- coding: utf-8 -*-
"""得到大脑博主内容 → 一条内容一个文件夹。

    python 03_加工/02_getnote/run.py blogger "02_储存/02_getnote/blogger"

产出结构和灵造那套**完全一致**（用户要求「结构是一样的」）：

    04_产出/博主/<昵称>_<账号ID>/
        _索引.xlsx                     总表（和灵造同一套列名）
        <发布日期>_<标题>/
            逐字稿.md                 信息头 + 正文 + 逐字稿（一个文件看全貌）
            封面.<ext>                 （图池里有才放）

**和灵造版的差异**（因为得到大脑压根没有这些数据，不是偷懒）：

1. **没有 `_逐字稿合集.md`** —— 得到大脑的逐字稿就在每条详情里，
   没有「一份合集文件」这个概念。
2. **封面先看图池，没有就现下** —— 图池是**缓存**
   (`04_产出/图片/<昵称>_<账号ID>/<笔记ID>.<ext>`)，由 `run.py cover` 填；
   图池里没有时，用详情 JSON 里的 `post_cover` **当场下**。
   得到大脑的封面链接**不带签名、不过期**（和灵造相反），现下是安全的，
   所以这里是「补缺」不是「抢救」。**别把灵造那边的紧张感套过来。**
3. **单条文件更短** —— 没有指标 / 时长 / 商单标记，这几项它给不了。

三条命名规矩和灵造一致（用户 2026-09-19 拍板，别擅自改）：

1. **博主目录 = 昵称_账号ID** —— 改昵称了也能对回账号。
2. **单条目录 = 发布日期_标题，不用 001 序号** —— 增量抓时序号会错位。
3. **单条目录里的文件名固定**（逐字稿.md / 封面.*）——
   文件名固定了，以后一个脚本就能跑全部博主。

重跑是幂等的：先扫博主目录，按 `逐字稿.md` 信息头里的笔记 ID 认领已有文件夹，
所以同一批数据重复导出不会变成 `xxx_2`。
"""

from __future__ import annotations

import re
import shutil
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from record import NoteRecord

ROOT = Path(__file__).resolve().parent.parent.parent
PRODUCE = ROOT / "04_产出"
PACK_ROOT = PRODUCE / "博主"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
_EXT = {"image/webp": ".webp", "image/jpeg": ".jpg", "image/jpg": ".jpg",
        "image/png": ".png", "image/gif": ".gif"}

# 只有半角这几个字符是 Windows 文件名不认的。
# 全角的 ？！：、（） 都是合法字符 —— 别手痒把它们也换掉，标题会变丑。
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
TITLE_MAX = 40


# --------------------------------------------------------------------------
# 命名
# --------------------------------------------------------------------------

def clean_name(s, limit: int = TITLE_MAX) -> str:
    """清洗成能当文件夹名的字符串。"""
    s = _ILLEGAL.sub("_", str(s or ""))
    s = re.sub(r"\s+", " ", s).strip(" .")
    if len(s) > limit:
        s = s[:limit].rstrip()
    return s or "untitled"


def folder_stem(rec: NoteRecord) -> str:
    """单条目录名：发布日期_标题。日期空着也不能崩。"""
    date = (rec.published_at or "")[:10] or "0000-00-00"
    return f"{date}_{clean_name(rec.title)}"


def _unique_dir(parent: Path, stem: str) -> Path:
    d = parent / stem
    n = 2
    while d.exists():
        d = parent / f"{stem}_{n}"
        n += 1
    return d


def _read_note_id(folder: Path) -> str:
    """从已有的产出文件里抠出笔记 ID，用来认领旧文件夹。

    优先看 `逐字稿.md`（合并后的新格式，信息头在最上面），
    退回 `笔记信息.md`（旧格式）—— 迁移期两者都要认。
    """
    for name in ("逐字稿.md", "笔记信息.md"):
        f = folder / name
        if not f.is_file():
            continue
        m = re.search(r"^-\s*笔记 ID[：:]\s*(\S+)", f.read_text(encoding="utf-8"), re.M)
        if m:
            return m.group(1)
    return ""


# --------------------------------------------------------------------------
# 封面（先看图池这个缓存，没有就用详情里的 post_cover 现下）
# --------------------------------------------------------------------------

def find_pool_cover(author_id: str, note_id: str) -> Path | None:
    """从封面池里取图。

    池子在 `04_产出/图片/<昵称>_<账号ID>/<笔记ID>.<ext>`。
    目录名用「后缀匹配账号 ID」，免得两边的昵称清洗规则哪天对不上。

    ⚠️ 图池是**缓存**、不是必经之路 —— 取不到就由 `download_cover()` 现下。
    """
    base = PRODUCE / "图片"
    if not base.is_dir() or not author_id or not note_id:
        return None
    for d in base.iterdir():
        if d.is_dir() and d.name.endswith("_" + author_id):
            for f in sorted(d.glob(note_id + ".*")):
                if f.is_file():
                    return f
    return None


def download_cover(url: str, folder: Path) -> tuple[Path | None, str]:
    """下封面到单条内容目录。返回 (路径, 错误说明)；成功时错误说明为空。

    和灵造那份**同名同签名，但规则完全不同**：

    | | 灵造 | 得到大脑 |
    |---|---|---|
    | 链接带签名 | 带（`t=` 时间戳） | **不带** |
    | 有效期 | 约 3 小时，过期全 498 | **永久** |
    | 语义 | **抢救**（晚了就废） | **补缺**（什么时候都行） |

    所以灵造那份是「必须抓完立刻抢」，这份只是「图池缺了就补一下」。
    """
    if not url:
        return None, "没有封面 URL"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, f"{type(e).__name__}"

    if not body:
        return None, "下回来是空的"
    path = folder / ("封面" + _EXT.get(ctype, ".jpg"))
    path.write_bytes(body)
    return path, ""


# --------------------------------------------------------------------------
# 单条内容
# --------------------------------------------------------------------------

def build_note_md(rec: NoteRecord, author: str, author_id: str) -> str:
    """一条内容 = **一个文件**：信息头 + 原始标题串 + 逐字稿。

    用户 2026-09-19 定：「笔记信息可以融到逐字稿里面，没必要硬分两个文件。」
    得到大脑**没有**互动数据 / 时长 / 商单标记 —— 那几行**不写**，
    只在末尾留一句占位说明。**没有就是没有，不硬编、不占空位。**
    """
    tags = " / ".join(rec.tags) if rec.tags else "（无）"
    return "\n".join([
        f"# {rec.title or '(无标题)'}",
        "",
        f"- 笔记 ID：{rec.note_id}",
        f"- 链接：{rec.url or '（无）'}",
        f"- 博主：{author}（{author_id}）",
        f"- 发布时间：{rec.published_at}",
        f"- 数据抓取：{rec.collected_at or '（未记录）'}",
        f"- 类型：{rec.note_type}",
        f"- 逐字稿：{rec.subtitle_status or '（无）'}",
        f"- 标签：{tags}",
        "",
        "> 本来源（得到大脑）不提供点赞 / 收藏 / 评论 / 分享与视频时长。",
        "",
        "## 原始标题串",
        "",
        rec.desc or "（无）",
        "",
        "---",
        "",
        "## 逐字稿",
        "",
        rec.subtitle_text.rstrip() if rec.subtitle_text else "（这条没有逐字稿）",
        "",
    ])


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def export_bundle(source) -> dict:
    """把一个得到大脑博主的数据拆成目录树。返回统计信息（含 records 供出表）。

    `source` 可以是：

    - 一个**目录** —— 递归找 `*_blogger-content_*.json`（常态：一批 20 条详情）
    - 单个详情 JSON 文件的路径

    列表文件（`*_blogger-contents_*.json`）**不参与** —— 字段不全、没有逐字稿。
    """
    from adapter import parse_auto
    from util import expand_paths

    p = Path(source)
    if p.is_dir():
        files = [f for f in expand_paths([p], (".json",)) if "_blogger-content_" in f.name]
        if not files:
            raise ValueError(
                f"{p} 里没有 `*_blogger-content_*.json`。"
                "列表文件（`*_blogger-contents_*`）字段不全、没有逐字稿，不参与归档。")
    else:
        files = [p]

    records = []
    for f in files:
        records.extend(parse_auto(f).records)
    records.sort(key=lambda r: r.published_at, reverse=True)
    if not records:
        raise ValueError(f"{p.name} 里一条内容都没有。")

    author = records[0].author_name or "unknown"
    author_id = records[0].author_id or ""

    # 博主的数据每天都在变，所以每条都标上是哪一次抓的。
    # 原始文件落盘后没人动过，拿它的修改时间就是抓取时刻（多个文件取最晚的）。
    collected = max(datetime.fromtimestamp(f.stat().st_mtime) for f in files) \
        .strftime("%Y-%m-%d %H:%M:%S")
    for rec in records:
        rec.collected_at = collected

    pack_dir = PACK_ROOT / f"{clean_name(author, 30)}_{author_id or 'noid'}"
    pack_dir.mkdir(parents=True, exist_ok=True)

    # 已有文件夹按笔记 ID 认领 —— 保证重跑幂等，不会堆出 xxx_2
    claimed: dict[str, Path] = {}
    for d in pack_dir.iterdir():
        if d.is_dir():
            nid = _read_note_id(d)
            if nid:
                claimed[nid] = d

    stat = {"条数": len(records), "有逐字稿": 0, "无逐字稿": 0,
            "封面成功": 0, "封面来自图池": 0, "封面现下": 0, "封面缺失": 0,
            "复用旧目录": 0, "新建目录": 0}
    cover_errs: list[str] = []

    for rec in records:
        folder = claimed.get(rec.note_id)
        if folder:
            stat["复用旧目录"] += 1
        else:
            folder = _unique_dir(pack_dir, folder_stem(rec))
            stat["新建目录"] += 1
        folder.mkdir(parents=True, exist_ok=True)

        if rec.subtitle_text:
            stat["有逐字稿"] += 1
        else:
            stat["无逐字稿"] += 1

        # 一条内容 = 一个文件：信息头 + 原始标题串 + 逐字稿（没稿也写，信息头独立）
        (folder / "逐字稿.md").write_text(
            build_note_md(rec, author, author_id), encoding="utf-8")
        # 迁移：旧格式留下的 笔记信息.md 删掉，别两套并存
        stale_info = folder / "笔记信息.md"
        if stale_info.is_file():
            stale_info.unlink()

        # 封面：先看图池（缓存），没有就用详情里的 post_cover 现下。
        # 得到大脑的链接不带签名、不过期 → 现下是安全的。
        # （灵造那边正相反：带签名、约 3 小时过期，只能当场抢。）
        pooled = find_pool_cover(author_id, rec.note_id)
        if pooled:
            shutil.copy2(pooled, folder / ("封面" + pooled.suffix))
            stat["封面成功"] += 1
            stat["封面来自图池"] += 1
        else:
            got, err = download_cover(rec.cover_url, folder)
            if got:
                stat["封面成功"] += 1
                stat["封面现下"] += 1
            else:
                stat["封面缺失"] += 1
                if err:
                    cover_errs.append(err)

    return {"pack_dir": pack_dir, "author": author, "author_id": author_id,
            "records": records, "stats": stat, "cover_errs": cover_errs}
