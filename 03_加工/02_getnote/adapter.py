# -*- coding: utf-8 -*-
"""得到大脑适配器。

**只处理「外抓」链路** —— 博主订阅（抖音）那一条。
不碰用户私人笔记（`notes` / `note` / `search` / `tag` 那一组命令本项目禁用），
详见项目 MEMORY 的「CLI 的能力边界」。

⚠️ **认命令靠文件名，不靠 JSON 里的 type** ——
这一点和灵造**相反**（灵造有 `data.type`，得到大脑没有）。所以文件名是唯一身份来源。

本适配器认的落盘文件：

    2026-09-19_bloggers_谢胜子_1397022.json          博主列表
    2026-09-19_blogger-contents_谢胜子_p1.json       内容列表
    2026-09-19_blogger-content_<post_id_alias>.json  单条详情 ← 逐字稿在这

字段现实（2026-09-19 实测，每条都是踩出来的）：

1. **详情的 `post_id_alias` 是空串** → 身份只能从**文件名**取（落盘名里带着 alias）。
2. **详情里没有任何作者字段** → 博主名去**同目录的 bloggers 文件**里找。
3. **没有互动数据、没有时长** → 那几列一律 `None`，导出成「未知」。
   封面**不属于**这种情况 —— 详情接口给 `post_cover`，直接填进 `cover_url` 列。
4. `post_name` 带完整话题串（`标题 #标签1 #标签2 …`）→ 标题和标签要拆开。
5. `post_url` 是**483 字的超长抖音分享链接**（带 share_sign / ts / u_code），
   还可能过期 → 落表前洗干净。**但小红书的 xsec_token 是必需的，不能洗。**
6. 逐字稿**不保证每条都有**（实测 20 条里 1 条没有）→ 按 ready / missing 两态处理。

删掉的字段都在 `raw` 里，随时能回溯。
"""

from __future__ import annotations

import re
from pathlib import Path

from record import AdapterResult, BaseAdapter, NoteRecord
from util import extract_tags, load_json, mtime_cst

SOURCE = "getnote"

# 文件名模式（落盘命名见 01_采集/02_getnote/ 的约定）
_RE_BLOGGERS = re.compile(r"(?:^|_)bloggers_(?P<name>.+?)_(?P<fid>\d+)\.json$")
_RE_CONTENTS = re.compile(r"(?:^|_)blogger-contents_(?P<name>.+?)_p\d+\.json$")
_RE_CONTENT = re.compile(r"(?:^|_)blogger-content_(?P<alias>[^.]+)\.json$")


def _clean(s) -> str:
    return "" if s is None else str(s).strip()


def _split_title_tags(title: str) -> tuple[str, list[str]]:
    """`标题 #标签1 #标签2` → (`标题`, [标签1, 标签2])。

    得到大脑把话题直接拼在标题尾巴上，不拆的话「标题」列会拖一串话题。
    标签全在标题后半段，所以砍在**第一个 `#`** 处即可。
    """
    s = _clean(title)
    tags = extract_tags(s)
    if not tags:
        return s, []
    cut = s.find("#")
    return (s[:cut].strip() if cut > 0 else s), tags


def _short_url(u: str) -> str:
    """洗掉抖音分享链接的跟踪参数。

    `https://www.iesdouyin.com/share/video/7686503495624707369/?region=CN&mid=…`
    → `https://www.iesdouyin.com/share/video/7686503495624707369/`

    ⚠️ **小红书不洗** —— 它的 `xsec_token` 去掉就打不开了。
    """
    s = _clean(u)
    if not s:
        return ""
    if "iesdouyin.com" in s or "douyin.com" in s:
        return s.split("?", 1)[0]
    return s


def _author_from_dir(raw_dir: Path) -> dict:
    """从同目录的 bloggers / blogger-contents 文件里推断博主。

    得到大脑的详情接口**不给博主**，所以只能这样旁敲侧击。
    一个知识库一个博主是常态。
    """
    out = {"name": "", "platform": "", "follow_id": ""}
    if not raw_dir.is_dir():
        return out

    # bloggers 文件最权威（有 account_name / platform / follow_id_str）
    for f in sorted(raw_dir.glob("*_bloggers_*.json")):
        m = _RE_BLOGGERS.search(f.name)
        try:
            d = load_json(f)
        except Exception:
            continue
        bloggers = ((d.get("data") or {}).get("bloggers") or [])
        if not bloggers:
            continue
        want_name = m.group("name") if m else ""
        want_fid = m.group("fid") if m else ""
        pick = next((b for b in bloggers if _clean(b.get("follow_id_str")) == want_fid), None) \
            or next((b for b in bloggers if _clean(b.get("account_name")) == want_name), None) \
            or bloggers[0]
        out["name"] = _clean(pick.get("account_name"))
        out["platform"] = _clean(pick.get("platform"))
        out["follow_id"] = _clean(pick.get("follow_id_str"))
        return out

    # 退一步：contents 的文件名里有博主名（落盘时写的）
    for f in sorted(raw_dir.glob("*_blogger-contents_*.json")):
        m = _RE_CONTENTS.search(f.name)
        if m:
            out["name"] = m.group("name")
            return out
    return out


def _blank_metrics() -> dict:
    """得到大脑不给互动数据 —— 显式声明，别用默认值糊过去。"""
    return {"liked": None, "collected": None, "commented": None, "shared": None,
            "duration_seconds": None}


# --------------------------------------------------------------------------

class GetnoteBloggerContent(BaseAdapter):
    """博主单条内容（含逐字稿 + 封面）。

    输入是 HTTP `GET /resource/knowledge/blogger/content/detail?topic_id=&post_id=`
    的落盘 JSON（**2026-09-20 起采集全走 HTTP**，之前是 CLI）：

        {"success": true, "data": {"post_media_text": "…", "post_cover": "…",
         "post_url": "…", "post_publish_time": "…"}}

    注意 `data` 是**平铺**的（不像 `note` 接口是 `data.note`）。
    """

    command = "blogger/content/detail"

    def parse(self, path: str | Path) -> AdapterResult:
        p = Path(path)
        d = load_json(p)
        data = d.get("data") or {}

        # ① 身份：详情里 post_id_alias 是空串，只能从文件名取
        m = _RE_CONTENT.search(p.name)
        alias = m.group("alias") if m else _clean(data.get("post_id_alias"))

        # ② 博主：详情里没有作者字段，去同目录捞
        author = _author_from_dir(p.parent)

        raw_title = _clean(data.get("post_name") or data.get("post_title"))
        title, tags = _split_title_tags(raw_title)
        text = _clean(data.get("post_media_text"))

        rec = NoteRecord(
            source=SOURCE,
            command=self.command,
            raw_file=str(p),
            collected_at=mtime_cst(p),

            note_id=alias,
            title=title,
            author_id=author["follow_id"],
            author_name=author["name"],
            author_platform_name=author["name"] if author["platform"] == "douyin" else "",
            url=_short_url(data.get("post_url")),
            cover_url=_clean(data.get("post_cover")),   # 走 HTTP 详情才有；不过期

            note_type=_clean(data.get("post_type")),
            published_at=_clean(data.get("post_publish_time")),

            desc=raw_title,
            tags=tags,

            subtitle_status="ready" if text else "missing",
            subtitle_text=text,

            raw=data,
            **_blank_metrics(),
        ).finalize()

        return AdapterResult(SOURCE, self.command, str(p), [rec], {
            "author_name": author["name"],
            "author_platform": author["platform"],
            "follow_id": author["follow_id"],
            "has_text": bool(text),
        })


class GetnoteBloggerContents(BaseAdapter):
    """博主内容列表。

    ⚠️ **列表接口没有逐字稿** —— 逐字稿只在详情里有。
    所以它单独出的表是**残缺**的，价值在于**清单**：
    告诉你有哪些内容、各自 id 是什么，好去逐条拉详情。
    （要出完整表就抓详情。列表文件不会被出表命令认领 —— 见 run.py 的 only 过滤。）
    """

    command = "blogger/contents"

    def parse(self, path: str | Path) -> AdapterResult:
        p = Path(path)
        d = load_json(p)
        data = d.get("data") or {}
        items = data.get("contents") or data.get("list") or []

        author = _author_from_dir(p.parent)
        m = _RE_CONTENTS.search(p.name)
        if m:
            author = dict(author, name=m.group("name"))

        records = []
        for it in items:
            raw_title = _clean(it.get("post_title") or it.get("post_name"))
            title, tags = _split_title_tags(raw_title)
            rec = NoteRecord(
                source=SOURCE,
                command=self.command,
                raw_file=str(p),
                collected_at=mtime_cst(p),

                note_id=_clean(it.get("post_id_alias")),
                title=title,
                author_id=author["follow_id"],
                author_name=author["name"],
                author_platform_name=author["name"] if author["platform"] == "douyin" else "",
                url="",                       # 列表不给链接

                note_type=_clean(it.get("post_type")),
                published_at=_clean(it.get("post_publish_time")),

                desc=raw_title,
                tags=tags,

                # 列表没有正文 —— 状态留空，别谎报 missing
                subtitle_status="",
                subtitle_text="",

                raw=it,
                **_blank_metrics(),
            ).finalize()
            records.append(rec)

        return AdapterResult(SOURCE, self.command, str(p), records, {
            "author_name": author["name"],
            "total": data.get("total"),
            "has_more": data.get("has_more"),
        })


# --------------------------------------------------------------------------
# 分派
# --------------------------------------------------------------------------

def detect_command(path: str | Path) -> str:
    """认文件名。得到大脑的 JSON 里没有 type 字段，**只能靠文件名**。

    认不出来就报人话 —— 别猜，猜错了会把私人笔记的落盘文件也吞进来。
    """
    name = Path(path).name
    if _RE_CONTENT.search(name):
        return "blogger/content/detail"
    if _RE_CONTENTS.search(name):
        return "blogger/contents"
    if _RE_BLOGGERS.search(name):
        return "bloggers"
    raise ValueError(
        f"认不出 {name} 是得到大脑的哪种输出。"
        "本项目只认外抓链路的落盘名（`*_bloggers_*.json` / `*_blogger-contents_*.json` / "
        "`*_blogger-content_*.json`），其他一律不碰。"
    )


_BY_CMD = {
    "blogger/content/detail": GetnoteBloggerContent,
    "blogger/contents": GetnoteBloggerContents,
}


def parse_auto(path: str | Path) -> AdapterResult:
    cmd = detect_command(path)
    cls = _BY_CMD.get(cmd)
    if cls is None:
        raise ValueError(f"得到大脑命令 '{cmd}' 还没有适配器。现有：{', '.join(_BY_CMD)}")
    return cls().parse(path)
