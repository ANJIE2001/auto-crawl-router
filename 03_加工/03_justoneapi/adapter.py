# -*- coding: utf-8 -*-
"""
四个平台的原始 JSON → 统一账号记录。

★ 四个平台的「同一个概念」长在不同地方，这里就是把这些差异吃掉的地方：

    平台      账号名              平台账号名            内部 ID      粉丝数
    小红书    users[].name       users[].red_id       users[].id   sub_title 里的文本
    抖音      user_info.nickname user_info.unique_id  user_info.uid  follower_count（数字）
    视频号    items[].title      jumpInfo.userName    item.docID   ✗ 没有
    公众号    data[].name        data[].wxid          data[].ghid  data[].fans

★ 认平台靠落盘目录名（`xhs.search_user` 的第一段），不靠 JSON 内容 ——
  抖音和小红书的返回都是「一个巨大 dict」，光看结构分不出来。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PLATFORM_LABEL = {
    "xhs": "小红书",
    "dy": "抖音",
    "sph": "视频号",
    "gzh": "公众号",
}

_FANS_RE = re.compile(r"粉丝\s*([\d.]+)\s*(万|w|W)?")
_TAG_RE = re.compile(r"<[^>]+>")


def _clean_html(s):
    return _TAG_RE.sub("", s or "").strip()


def _fans_from_text(s):
    """小红书把粉丝数塞在 sub_title 文本里，形如「粉丝 30.4万」。"""
    if not s:
        return None
    m = _FANS_RE.search(str(s))
    if not m:
        return None
    try:
        n = float(m.group(1))
    except ValueError:
        return None
    if m.group(2):
        n *= 10000
    return int(n)


def _first_url(obj):
    """抖音的头像字段是 {url_list: [...]}，取第一个。"""
    if isinstance(obj, dict):
        lst = obj.get("url_list") or []
        return lst[0] if lst else None
    if isinstance(obj, str):
        return obj
    return None


# ---------------------------------------------------------------- 各平台
def parse_xhs(payload, ctx):
    """小红书 · 账号搜索。data.users[]"""
    out = []
    users = ((payload.get("data") or {}).get("users")) or []
    for u in users:
        if not isinstance(u, dict):
            continue
        uid = u.get("id")
        fans = _fans_from_text(u.get("sub_title"))
        out.append({
            "platform": "小红书",
            "name": u.get("name"),
            "account_name": u.get("red_id"),
            "account_id": uid,
            "fans": fans,
            "desc": u.get("desc"),
            "verify": "官方认证" if u.get("red_official_verified") else None,
            "avatar": u.get("image"),
            # 接口给的是 xhsdiscover:// 客户端跳转，网页版按 id 拼得出来
            "home_url": f"https://www.xiaohongshu.com/user/profile/{uid}" if uid else None,
            **ctx,
            "raw": u,
        })
    return out


def parse_dy(payload, ctx):
    """抖音 · 账号搜索。

    ★ 真正的数据藏在 data.business_data[].data.raw_data ——
      那是一段 **JSON 字符串**（实测 2900 字），要二次 json.loads 才拿得到 user_info。
      第一层 business_data 里只有卡片样式，没有任何账号信息。
    """
    out = []
    cards = ((payload.get("data") or {}).get("business_data")) or []
    for c in cards:
        if not isinstance(c, dict):
            continue
        d = c.get("data") if isinstance(c.get("data"), dict) else c
        raw = d.get("raw_data")
        if not isinstance(raw, str):
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        ui = obj.get("user_info")
        if not isinstance(ui, dict):
            continue
        sec = ui.get("sec_uid")
        verify = ui.get("custom_verify") or ui.get("enterprise_verify_reason") or None
        out.append({
            "platform": "抖音",
            "name": ui.get("nickname"),
            "account_name": ui.get("unique_id"),
            "account_id": ui.get("uid"),
            "fans": ui.get("follower_count"),
            "desc": ui.get("signature"),
            "verify": verify or None,
            "avatar": _first_url(ui.get("avatar_thumb")),
            "home_url": f"https://www.douyin.com/user/{sec}" if sec else None,
            **ctx,
            "raw": ui,
        })
    return out


def parse_sph(payload, ctx):
    """视频号 · 账号搜索。data.data[].items[]

    ★ 标题里带高亮标签：`糖姐爱<em class="highlight">养生</em>` —— 必须洗掉。
    ★ 没有粉丝数字段，只能给「未知」。
    """
    out = []
    cards = ((payload.get("data") or {}).get("data")) or []
    for box in cards:
        if not isinstance(box, dict):
            continue
        for it in box.get("items") or []:
            if not isinstance(it, dict):
                continue
            jump = it.get("jumpInfo") or {}
            out.append({
                "platform": "视频号",
                "name": _clean_html(it.get("title")),
                "account_name": jump.get("userName") or (it.get("noticeParam") or {}).get("finderUsername"),
                "account_id": it.get("docID"),
                "fans": None,  # 接口不给
                "desc": _clean_html(it.get("desc")),
                "verify": it.get("authInfo") or None,
                "avatar": it.get("thumbUrl"),
                "home_url": None,  # 视频号没有公开主页地址
                **ctx,
                "raw": it,
            })
    return out


def parse_gzh(payload, ctx):
    """公众号 · 账号搜索。data.data[]

    实测这个接口只回 1 条（最匹配的那个），但字段最实在：
    粉丝数、平均阅读、周更篇数都有。
    """
    out = []
    items = ((payload.get("data") or {}).get("data")) or []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append({
            "platform": "公众号",
            "name": it.get("name"),
            "account_name": it.get("wxid"),
            "account_id": it.get("ghid"),
            "fans": it.get("fans"),
            "desc": None,
            "verify": it.get("customer_type") or None,
            "avatar": it.get("avatar"),
            "home_url": it.get("qrcode"),
            **ctx,
            "raw": it,
        })
    return out


PARSERS = {
    "xhs": parse_xhs,
    "dy": parse_dy,
    "sph": parse_sph,
    "gzh": parse_gzh,
}


# ---------------------------------------------------------------- 扫盘
def _meta_of(json_path: Path):
    """读同名的 .meta.json —— 抓取时间、关键词、花费都在里面。"""
    mp = json_path.parent / (json_path.stem + ".meta.json")
    if not mp.is_file():
        return {}
    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_all(store_dir: Path, keyword=None):
    """扫 02_储存/03_justoneapi/<平台.动作>/ 下所有响应，解析成记录。

    只收「账号搜索」类动作（*search_user / *search_account）；
    别的动作（笔记详情、视频列表）结构不同，等各自的 adapter 写好了再收。
    """
    recs = []
    scanned = 0
    skipped = []
    if not store_dir.is_dir():
        return recs, scanned, skipped

    for d in sorted(store_dir.iterdir()):
        if not d.is_dir():
            continue
        name = d.name
        if "." not in name:
            continue
        plat, action = name.split(".", 1)
        if plat not in PARSERS:
            continue
        if not (action.startswith("search_user") or action.startswith("search_account")):
            continue
        parser = PARSERS[plat]

        for jp in sorted(d.glob("*.json")):
            if jp.name.endswith(".meta.json"):
                continue
            meta = _meta_of(jp)
            kw = (meta.get("params") or {}).get("keyword")
            if keyword and kw != keyword:
                continue
            try:
                payload = json.loads(jp.read_text(encoding="utf-8"))
            except Exception as e:
                skipped.append((jp.name, f"读不了: {e}"))
                continue
            if payload.get("code") != 0:
                skipped.append((jp.name, f"code={payload.get('code')}（失败的调用，跳过）"))
                continue
            ctx = {
                "keyword": kw,
                "fetched_at": meta.get("called_at"),
                "raw_file": str(jp.relative_to(store_dir)),
            }
            try:
                got = parser(payload, ctx)
            except Exception as e:
                skipped.append((jp.name, f"解析出错: {type(e).__name__}: {e}"))
                continue
            if not got:
                skipped.append((jp.name, "解析出 0 条（结构可能变了）"))
            recs.extend(got)
            scanned += 1
    return recs, scanned, skipped
