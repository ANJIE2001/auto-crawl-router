# -*- coding: utf-8 -*-
"""灵造适配器。

灵造把三种命令的结果都塞在 `{"ok":…, "data":{"type":"<命令名>", "items":[…]}}`
这同一个壳里，所以按 `data.type` 分派就够。

三种命令的实际形状（2026-09-19 实测）：

    search-notes          item: id/title/summary/content/type/xhs_note_type/url/
                               coverUrl/author{id,name}/metrics/tags/
                               media{images,video{durationMs}}/publishedAt/ipLocation
                          注意 type 可能是 "ads"，xhs_note_type 会是 null

    analyze-user-profile  item: id/url/title/type/xhs_note_type/published_at/sticky/
                               metrics/media/text{desc,subtitle}/monetization
                          外层还有 user / page / artifacts{subtitle_markdown}

    search-users          目前只落成 Markdown，不解析（见 search_users_not_supported）

两个坑记在这：

1. **扩展名叫 .json 不代表内容是 JSON。** 灵造有时直接存 Markdown，
   `load_json()` 会认出来并给你一句人话报错。
2. **profile 的字幕是截断的。** `text.subtitle.truncated == true`，
   完整字幕在 `data.artifacts.subtitle_markdown.url`。别拿截断的去当全文用。
"""

from __future__ import annotations

from pathlib import Path

from record import AdapterResult, BaseAdapter, NoteRecord
from util import extract_tags, iso_to_cst, load_json, ms_to_cst, safe_int

SOURCE = "lingzao"


def _clean(s) -> str:
    return "" if s is None else str(s)


# --------------------------------------------------------------------------

class LingzaoSearchNotes(BaseAdapter):
    """批量搜笔记。有作者、有指标、没字幕。"""

    source = SOURCE
    command = "search-notes"

    def parse(self, path: str | Path) -> AdapterResult:
        p = Path(path)
        d = load_json(p)
        data = d.get("data") or {}
        items = data.get("items") or []

        records = []
        for it in items:
            author = it.get("author") or {}
            metrics = it.get("metrics") or {}
            media = it.get("media") or {}
            video = media.get("video") or {}
            content = _clean(it.get("content") or it.get("summary"))

            tags = list(it.get("tags") or [])
            if not tags:
                tags = extract_tags(content)

            duration = 0
            if video.get("durationMs"):
                duration = safe_int(video["durationMs"]) // 1000

            images = media.get("images") or []
            cover = _clean(it.get("coverUrl"))
            if not cover and images:
                cover = _clean(images[0].get("url"))

            rec = NoteRecord(
                source=SOURCE,
                command=self.command,
                raw_file=str(p),
                note_id=_clean(it.get("id")),
                title=_clean(it.get("title")),
                author_id=_clean(author.get("id")),
                author_name=_clean(author.get("name")),
                url=_clean(it.get("url")),
                note_type=_clean(it.get("type")),
                xhs_note_type=_clean(it.get("xhs_note_type")),
                published_at=iso_to_cst(it.get("publishedAt")),
                duration_seconds=duration,
                liked=safe_int(metrics.get("liked")),
                collected=safe_int(metrics.get("collected")),
                commented=safe_int(metrics.get("commented")),
                shared=safe_int(metrics.get("shared")),
                desc=content,
                tags=tags,
                cover_url=cover,
                ip_location=_clean(it.get("ipLocation")),
                subtitle_status="",          # 搜索接口不给字幕
                subtitle_truncated=False,
                subtitle_text="",
                raw=it,
            ).finalize()
            records.append(rec)

        meta = {
            "query": data.get("query"),
            "sort": data.get("sort"),
            "note_type_filter": data.get("note_type"),
            "time_filter": data.get("time_filter"),
            "cost_credits": d.get("cost_credits"),
            "remaining_credits": d.get("remaining_credits"),
            "request_id": d.get("request_id"),
        }
        return AdapterResult(SOURCE, self.command, str(p), records, meta)


# --------------------------------------------------------------------------

class LingzaoProfile(BaseAdapter):
    """深挖单博主。有字幕（截断）、有商单标记、有分页信息。"""

    source = SOURCE
    command = "analyze-user-profile"

    def parse(self, path: str | Path) -> AdapterResult:
        p = Path(path)
        d = load_json(p)
        data = d.get("data") or {}
        items = data.get("items") or []
        user = data.get("user") or {}
        page = data.get("page") or {}
        artifacts = data.get("artifacts") or {}

        nickname = _clean(user.get("nickname"))
        user_id = _clean(user.get("id"))

        records = []
        for it in items:
            metrics = it.get("metrics") or {}
            media = it.get("media") or {}
            text = it.get("text") or {}
            subtitle = text.get("subtitle") or {}
            monet = it.get("monetization") or {}
            collab = monet.get("collaboration") or {}
            commerce = monet.get("commerce_note") or {}
            desc = _clean(text.get("desc"))

            # 商单 / 带货：两个键名灵造都用过，都认
            is_collab = collab.get("likely_collaboration")
            is_commerce = commerce.get("is_goods_note")
            if is_commerce is None:
                is_commerce = commerce.get("likely_goods_note")

            sub_status = _clean(subtitle.get("status"))
            sub_truncated = bool(subtitle.get("truncated"))

            rec = NoteRecord(
                source=SOURCE,
                command=self.command,
                raw_file=str(p),
                note_id=_clean(it.get("id")),
                title=_clean(it.get("title")),
                author_id=user_id,
                author_name=nickname,
                url=_clean(it.get("url")),
                note_type=_clean(it.get("type")),
                xhs_note_type=_clean(it.get("xhs_note_type")),
                published_at=iso_to_cst(it.get("published_at")),
                duration_seconds=safe_int(media.get("video_duration_seconds")),
                liked=safe_int(metrics.get("liked")),
                collected=safe_int(metrics.get("collected")),
                commented=safe_int(metrics.get("commented")),
                shared=safe_int(metrics.get("shared")),
                is_sticky=bool(it.get("sticky")),
                is_collaboration=is_collab if isinstance(is_collab, bool) else None,
                is_commerce_note=is_commerce if isinstance(is_commerce, bool) else None,
                desc=desc,
                tags=extract_tags(desc),
                cover_url=_clean(media.get("cover_large_url")),
                subtitle_status=sub_status,
                subtitle_truncated=sub_truncated,
                subtitle_text=_clean(subtitle.get("plain_text")),
                raw=it,
            ).finalize()
            records.append(rec)

        sub_artifact = artifacts.get("subtitle_markdown") or {}
        meta = {
            "author_name": nickname,
            "author_id": user_id,
            "page": page,
            "has_more": page.get("has_more"),
            "next_cursor": page.get("next_cursor"),
            "subtitle_artifact_status": sub_artifact.get("status"),
            "subtitle_artifact_url": sub_artifact.get("url"),
            "subtitle_artifact_bytes": sub_artifact.get("size_bytes"),
            "cost_credits": d.get("cost_credits"),
            "remaining_credits": d.get("remaining_credits"),
            "request_id": d.get("request_id"),
        }
        return AdapterResult(SOURCE, self.command, str(p), records, meta)


# --------------------------------------------------------------------------

class LingzaoSearchUsers(BaseAdapter):
    """搜创作者。

    灵造这一路目前只输出 Markdown（标题「小红书创作者搜索」），
    拿不到结构化字段，所以直接拒绝，而不是假装解析成功。
    """

    source = SOURCE
    command = "search-users"

    def parse(self, path: str | Path) -> AdapterResult:
        p = Path(path)
        d = load_json(p)  # 内容是 md 时这里就会带人话报错
        raise NotImplementedError(
            f"{p.name} 的 data.type 是 search-users：灵造这一路目前只落 Markdown，"
            "没有结构化字段可解析。要么等灵造的 JSON 输出，要么改走浏览器兜底。"
            f"（文件里的实际 type: {(d.get('data') or {}).get('type')}）"
        )


# --------------------------------------------------------------------------
# 分派
# --------------------------------------------------------------------------

_BY_TYPE = {
    "search-notes": LingzaoSearchNotes,
    "analyze-user-profile": LingzaoProfile,
    "search-users": LingzaoSearchUsers,
}


def detect_command(path: str | Path) -> str:
    """读一眼 data.type，别猜。"""
    d = load_json(path)
    data = d.get("data") or {}
    cmd = _clean(data.get("type"))
    if not cmd:
        raise ValueError(f"{Path(path).name} 里没有 data.type，认不出是哪种灵造输出。")
    return cmd


def parse_auto(path: str | Path) -> AdapterResult:
    """丢个文件进来，自己认命令再解析。run.py 走这条路。"""
    cmd = detect_command(path)
    cls = _BY_TYPE.get(cmd)
    if cls is None:
        raise ValueError(
            f"灵造命令 '{cmd}' 还没有适配器。"
            f"现有：{', '.join(_BY_TYPE)}。加一个就照 LingzaoSearchNotes 的样子抄。"
        )
    return cls().parse(path)


# 给 run.py 用的默认适配器：一个文件混着多种命令也能各自认领
class LingzaoAuto(BaseAdapter):
    source = SOURCE
    command = "auto"

    def parse(self, path: str | Path) -> AdapterResult:
        return parse_auto(path)
