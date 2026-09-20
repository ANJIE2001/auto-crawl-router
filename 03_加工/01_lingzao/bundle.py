# -*- coding: utf-8 -*-
"""博主全量抓取 → 一条内容一个文件夹。

    python 03_加工/01_lingzao/run.py bundle 02_储存/01_lingzao/analyze-user-profile/xxx.json

产出：

    04_产出/博主/<昵称>_<账号ID>/
        _索引.xlsx                      40 行总表（含逐字稿列）
        _逐字稿合集.md                  整份合集，通读用
        2026-09-19_一个真正帮你赚米的skill/
            逐字稿.md                   信息头 + 正文 + 逐字稿（一个文件看全貌）
            封面.webp                   （链接过期就下不到，会记进报告）

三条规矩（2026-09-19 用户拍板，别擅自改）：

1. **博主目录 = 昵称_账号ID** —— 以后改昵称了也能对回账号。
2. **单条目录 = 发布日期_标题，不用 001 序号** —— 增量抓时序号会错位，
   把"身份"和"顺序"搅在一起。顺序靠日期，身份永远认笔记 ID。
3. **单条目录里的文件名固定**（逐字稿.md / 封面.*），
   哪个博主、哪次抓取都一样 —— 文件名固定了，以后一个脚本就能跑全部博主。

重跑是幂等的：先扫一遍博主目录，按里面的笔记 ID 认领已有文件夹，
所以同一批数据重复导出不会变成 `xxx_2`。
"""

from __future__ import annotations

import re
import shutil
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import adapter as ad_lingzao
from record import NoteRecord

ROOT = Path(__file__).resolve().parent.parent.parent
PRODUCE = ROOT / "04_产出"
PACK_ROOT = PRODUCE / "博主"

# 只有半角这几个字符是 Windows 文件名不认的。
# 全角的 ？！：、（） 都是合法字符 —— 别手痒把它们也换掉，标题会变丑。
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
TITLE_MAX = 40
_UA = {"User-Agent": "Mozilla/5.0"}
_EXT = {"image/webp": ".webp", "image/jpeg": ".jpg", "image/jpg": ".jpg",
        "image/png": ".png", "image/gif": ".gif"}


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
# 逐字稿合集解析
# --------------------------------------------------------------------------

def parse_collection(md_path: str | Path) -> dict[str, dict[str, str]]:
    """读灵造的「完整字幕合集.md」→ {笔记ID: {"plain":…, "srt":…}}。

    合集结构（2026-09-19 实测）：

        ## 3. 标题
        - 笔记 ID: xxx
        ...
        ### 字幕纯文本
        一行一句
        ### 原始 SRT
        ~~~srt
        1
        00:00:00,000 --> 00:00:01,843
        这句话
        ~~~
    """
    p = Path(md_path)
    if not p.is_file():
        return {}
    text = p.read_text(encoding="utf-8")
    out: dict[str, dict[str, str]] = {}
    for block in re.split(r"^## \d+\. ", text, flags=re.M)[1:]:
        m = re.search(r"^-\s*笔记 ID:\s*(\S+)", block, re.M)
        if not m:
            continue
        out[m.group(1)] = {
            "plain": _section(block, "字幕纯文本"),
            "srt": _section(block, "原始 SRT"),
        }
    return out


def _section(block: str, name: str) -> str:
    """抠出某个 ### 小节的内容，顺带剥掉 SRT 的 ~~~ 围栏。"""
    m = re.search(rf"^###\s*{re.escape(name)}\s*\n(.*?)(?=^###\s|\Z)", block, re.S | re.M)
    if not m:
        return ""
    body = m.group(1).strip()
    fenced = re.match(r"^~~~+[a-zA-Z]*\s*\n(.*?)\n~~~+\s*$", body, re.S)
    return (fenced.group(1) if fenced else body).strip()


def find_collection(author: str, source_path: str | Path | None = None) -> Path | None:
    """找那份「完整字幕合集.md」。三档，从准到宽：

    1. **跟源 JSON 同目录、同前缀** —— 采集层下载时就是这么命名的
       （`<JSON 名字>_完整字幕合集.md`，落在 `02_储存`）。
       同一博主重抓多次会有多份，只有同前缀才能确定是哪一次的。
    2. **在 04_产出 里按博主名找** —— 历史遗留的那份，以及吃老成品表
       （xlsx，没有源 JSON 路径）的情形。
       两种文件都认：博主目录里的 `_逐字稿合集.md`（当前格式），
       以及早期的 `*完整字幕合集.md`。
       ⚠️ 这里必须拿**整个路径**做匹配，不能只看文件名 ——
       `_逐字稿合集.md` 这名字里不带博主，只有父目录带。
    3. 都没有就返回 None —— **不报错**，逐字稿退回 JSON 里那份截断版。
    """
    if source_path:
        cand = Path(source_path).parent / f"{Path(source_path).stem}_完整字幕合集.md"
        if cand.is_file():
            return cand

    if not PRODUCE.is_dir():
        return None
    for pat in ("*完整字幕合集.md", "_逐字稿合集.md"):
        for p in PRODUCE.rglob(pat):
            if author and author in str(p):
                return p
    return None


# --------------------------------------------------------------------------
# 封面
# --------------------------------------------------------------------------

def find_pool_cover(author_id: str, note_id: str) -> Path | None:
    """从采集层抢下来的封面池里取图。

    采集时封面 URL 没过期，`collect.py` 会当场把 40 张全下到
    `04_产出/图片/<昵称>_<账号ID>/<笔记ID>.webp`。加工时优先用这个池子 ——
    等轮到出表，那些 URL 早就 498 了，现下是下不到的。

    目录名用「后缀匹配账号 ID」，免得两边的昵称清洗规则哪天对不上。
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
    """下封面。返回 (路径, 错误说明)；成功时错误说明为空。

    封面 URL 带**过期签名**（查询串里的 t= 就是抓取那一刻的十六进制时间戳），
    实测过期约 3 小时就会 498，所以必须在抓完的当次就下。
    """
    if not url:
        return None, "没有封面 URL"
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except urllib.error.HTTPError as e:
        hint = "（签名已过期，要重新抓一次才拿得到）" if e.code == 498 else ""
        return None, f"HTTP {e.code}{hint}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

    if not body:
        return None, "下回来是空的"
    path = folder / ("封面" + _EXT.get(ctype, ".jpg"))
    path.write_bytes(body)
    return path, ""


# --------------------------------------------------------------------------
# 单条内容
# --------------------------------------------------------------------------

def _tri(v) -> str:
    return "未知" if v is None else ("是" if v else "否")


def build_note_md(rec: NoteRecord, author: str, author_id: str) -> str:
    """一条内容 = **一个文件**：信息头 + 正文 + 逐字稿。

    用户 2026-09-19 定的：「笔记信息其实可以融到逐字稿里面，没必要硬分两个文件。
    先前的灵造的那个笔记信息也可以融到逐字稿里面这样去写。」
    → 所以不再单独产 `笔记信息.md`，全并进 `逐字稿.md`，一个文件看到全貌。
    """
    tags = " / ".join(rec.tags) if rec.tags else "（无）"
    dur = "未知" if rec.duration_seconds is None else f"{rec.duration_seconds} 秒"
    n = rec._num
    return "\n".join([
        f"# {rec.title or '(无标题)'}",
        "",
        f"- 笔记 ID：{rec.note_id}",
        f"- 链接：{rec.url}",
        f"- 博主：{author}（{author_id}）",
        f"- 发布时间：{rec.published_at}",
        f"- 数据抓取：{rec.collected_at or '（未记录）'}",
        f"- 类型：{rec.note_type} / {rec.xhs_note_type}",
        f"- 时长：{dur}",
        f"- 点赞：{n(rec.liked)} ｜ 收藏：{n(rec.collected)} ｜ 评论：{n(rec.commented)} "
        f"｜ 分享：{n(rec.shared)} ｜ 互动总量：{n(rec.interactions_total)}",
        f"- 收藏/点赞：{n(rec.collect_like_ratio)}",
        f"- 置顶：{'是' if rec.is_sticky else '否'}",
        f"- 疑似商单：{_tri(rec.is_collaboration)} ｜ 商品笔记：{_tri(rec.is_commerce_note)}",
        f"- 字幕状态：{rec.subtitle_status or '无'}"
        f"（截断：{'是' if rec.subtitle_truncated else '否'}）",
        f"- 标签：{tags}",
        "",
        "## 正文",
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

def load_records(path: Path):
    """按后缀认入口。

    活的原始数据是灵造的 profile JSON（`analyze-user-profile`）；
    历史数据可能只剩一张当时导出的成品表，那就走 `ad_table`。
    两边吐的都是同一套 NoteRecord，后面的流程完全一样。
    """
    if path.suffix.lower() in (".xlsx", ".xls"):
        import table as ad_table
        return ad_table.parse_table(path)
    return ad_lingzao.parse_auto(path)


def export_bundle(source_path: str | Path,
                  subtitle_md: str | Path | None = None,
                  covers: bool = True) -> dict:
    """把一个博主的数据拆成目录树。返回统计信息（含 records 供出表）。"""
    result = load_records(Path(source_path))
    records = sorted(result.records, key=lambda r: r.published_at, reverse=True)
    if not records:
        raise ValueError(f"{Path(source_path).name} 里一条笔记都没有。")

    author = records[0].author_name or "unknown"
    author_id = records[0].author_id or ""

    # 博主的数据每天都在变（点赞收藏会涨），所以每条都标上是哪一次抓的。
    # 原始文件落盘后没人动过，拿它的修改时间就是抓取时刻。
    src = Path(source_path)
    collected = datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    for rec in records:
        rec.collected_at = collected

    pack_dir = PACK_ROOT / f"{clean_name(author, 30)}_{author_id or 'noid'}"
    pack_dir.mkdir(parents=True, exist_ok=True)

    # 逐字稿：优先用调用方给的合集，否则自己找（先认源文件同前缀，再按博主名）
    md = Path(subtitle_md) if subtitle_md else find_collection(author, source_path)
    subs = parse_collection(md) if md else {}

    # 已有文件夹按笔记 ID 认领 —— 保证重跑幂等，不会堆出 xxx_2
    claimed: dict[str, Path] = {}
    for d in pack_dir.iterdir():
        if d.is_dir():
            nid = _read_note_id(d)
            if nid:
                claimed[nid] = d

    stat = {"条数": len(records), "逐字稿全文": 0, "逐字稿截断": 0,
            "封面成功": 0, "封面来自图池": 0, "封面失败": 0,
            "复用旧目录": 0, "新建目录": 0}
    cover_errors: list[str] = []

    for rec in records:
        folder = claimed.get(rec.note_id)
        if folder:
            stat["复用旧目录"] += 1
        else:
            folder = _unique_dir(pack_dir, folder_stem(rec))
            stat["新建目录"] += 1
        folder.mkdir(parents=True, exist_ok=True)

        # 完整稿优先；只有截断预览时就标出来，别让人以为这就是全文
        full = (subs.get(rec.note_id) or {}).get("plain", "")
        if len(full) > 30:
            rec.subtitle_text = full
            stat["逐字稿全文"] += 1
        elif rec.subtitle_text:
            rec.subtitle_text = rec.subtitle_text.rstrip() + "\n\n（以上是截断预览，完整稿没拿到）"
            stat["逐字稿截断"] += 1

        # 一条内容 = 一个文件：信息头 + 正文 + 逐字稿（没稿也写，信息头独立于逐字稿）
        (folder / "逐字稿.md").write_text(
            build_note_md(rec, author, author_id), encoding="utf-8")
        # 迁移：旧格式留下的 笔记信息.md 删掉，别两套并存
        stale_info = folder / "笔记信息.md"
        if stale_info.is_file():
            stale_info.unlink()

        # 封面先看图池（采集时抢下来的），没有再拿 URL 现下
        pooled = find_pool_cover(author_id, rec.note_id)
        if pooled:
            shutil.copy2(pooled, folder / ("封面" + pooled.suffix))
            stat["封面成功"] += 1
            stat["封面来自图池"] += 1
        elif covers:
            _p, err = download_cover(rec.cover_url, folder)
            if err:
                stat["封面失败"] += 1
                if err not in cover_errors:
                    cover_errors.append(err)
            else:
                stat["封面成功"] += 1

    # 合集也留一份在博主目录，方便通读
    # ⚠️ 用 shutil.copy2，**不要** read_text + write_text ——
    # 后者在 Windows 上会把 LF 悄悄转成 CRLF，结果两份「内容一样」的文件字节数不同，
    # 排查这种差异纯属白费功夫（2026-09-20 实测踩到）。
    if md and md.is_file():
        target = pack_dir / "_逐字稿合集.md"
        if md.resolve() != target.resolve():
            shutil.copy2(md, target)

    return {"pack_dir": pack_dir, "author": author, "author_id": author_id,
            "records": records, "stats": stat, "cover_errors": cover_errors,
            "collection": str(md) if md else ""}
