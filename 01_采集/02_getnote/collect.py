#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
得到大脑 · 采集入口

**这个文件夹是自包含的**：拷到任何地方都能跑，不依赖 01_采集 里的其他文件。
只要保证同目录有 config.json 和 config.local.json 就行。

★ **一律走开放平台 HTTP API，不用 CLI**（2026-09-20 用户定）。

  理由：HTTP 的**详情**接口一次返回 12 个字段 —— 逐字稿 `post_media_text`
  和**封面** `post_cover` 都在里面；CLI 的详情只有 10 个、**而且没有封面**。
  走一条通道，就少一处「两边不一致」，也不用再管 CLI 装在哪、Git Bash 那个坑。

  三条接口（前缀 `https://openapi.biji.com/open/api/v1/resource/knowledge`）：

      博主列表   GET /bloggers?topic_id=
      内容列表   GET /blogger/contents?topic_id=&follow_id=&page=
      内容详情   GET /blogger/content/detail?topic_id=&post_id=   ← 逐字稿 + 封面

要改的东西只有两处：
    调什么接口、带什么参数   →  文件末尾的动作定义
    两个凭证值               →  同目录 config.local.json 的 openapi 段

读接口，会员制不额外扣费，直接跑，不用加 --go。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

HERE = Path(__file__).resolve().parent
DEFAULT_BASE = "https://openapi.biji.com/open/api/v1"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


# ---------------------------------------------------------------- 配置

def _overlay(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _overlay(base[k], v)
        else:
            base[k] = v


def read_env_file(path):
    """
    读项目根 .env（一行一个 KEY=VALUE，# 开头是注释）。

    为什么不引第三方 dotenv：采集层「不用装任何东西」是它的卖点，
    为了几行配置去装个包不划算。
    """
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip().strip('"').strip("'")
        if v:
            out[k.strip()] = v
    return out


def env_file_path():
    """项目根 .env —— 本文件在 01_采集/<源>/ 下，往上两级就是根。"""
    return HERE.parent.parent / ".env"


def load_config():
    """
    配置三层，后者压前者：

        ① 同目录 config.json        —— 结构 + 说明，进 git，真值留空
        ② 同目录 config.local.json  —— 老位置，现在只剩空壳（仍兼容，不报错）
        ③ 项目根 .env               —— ★ 真凭证的家，不进 git、不进安装包

    凭证只该写在第 ③ 层。前两层填了也不报错，但 .env 说了算。
    """
    cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    local = HERE / "config.local.json"
    if local.is_file():
        _overlay(cfg, json.loads(local.read_text(encoding="utf-8")))

    env = read_env_file(env_file_path())
    if env:
        o = cfg.setdefault("openapi", {})
        for env_key, cfg_key in (("GETNOTE_CLIENT_ID", "client_id"),
                                 ("GETNOTE_API_KEY", "api_key"),
                                 ("GETNOTE_BASE_URL", "base_url")):
            if env.get(env_key):
                o[cfg_key] = env[env_key]
    return cfg


def project_root(cfg):
    """02_储存 在哪。默认按「本文件往上两级」推断，搬走了才需要在 config 里写死。"""
    r = cfg.get("project_root")
    return Path(r).expanduser().resolve() if r else HERE.parent.parent


def openapi_creds(cfg):
    """取开放平台凭证。缺了就报清怎么填，别跑到一半才炸。"""
    o = cfg.get("openapi") or {}
    cid = str(o.get("client_id") or "").strip()
    key = str(o.get("api_key") or "").strip()
    if not cid or not key:
        raise SystemExit(
            "缺开放平台凭证 —— 这个源全走 HTTP API，两个值必须配好。\n"
            f"  打开  {env_file_path()}\n"
            "  填这两行（真值只放这里，别写进 config.json）：\n"
            "      GETNOTE_CLIENT_ID=cli_ 开头\n"
            "      GETNOTE_API_KEY=gk_live_ 开头\n"
            f"  怎么拿：{o.get('get_key_at') or '得到大脑开放平台 → 创建应用 → 生成 API Key'}\n"
            "  没有 .env？照 .env.example 复制一份再填。"
        )
    base = str(o.get("base_url") or DEFAULT_BASE).rstrip("/")
    return base, cid, key


# ---------------------------------------------------------------- HTTP

def http_json(url, cid, key, timeout=60, retries=3, gap=4.0):
    """GET 一个 JSON。撞 429 就等 gap 秒重试 —— 得到大脑是**桶级限流**，连调两个接口就会撞。"""
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={
            "Authorization": key,        # ⚠️ 不带 Bearer 前缀，加了会 401
            "X-Client-ID": cid,
            "Accept": "application/json",
            "User-Agent": UA,
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            last = f"HTTP {e.code}  {body[:300]}"
            if e.code == 429 and attempt < retries - 1:
                time.sleep(gap * (attempt + 1))
                continue
            raise SystemExit(f"请求失败：{url}\n  {last}")
        except Exception as e:
            last = str(e)
            if attempt < retries - 1:
                time.sleep(gap)
                continue
            raise SystemExit(f"请求失败：{url}\n  {last}")
    raise SystemExit(f"请求失败：{url}\n  {last}")


# ---------------------------------------------------------------- 工具

def slug(s, limit=40):
    s = re.sub(r"[\\/:*?\"<>|\s#]+", "_", str(s or "")).strip("_")
    return s[:limit] or "untitled"


def save_raw(text, out_dir, filename, overwrite=True):
    """落盘。

    ⚠️ **这里默认覆盖，和灵造那边不一样。**
    灵造重抓要花积分，所以重名加序号、留着历史；得到大脑不花钱、随时能重拉，
    覆盖更干净 —— 而且**必须覆盖**：详情文件名里带着笔记 ID，
    加序号会变成 `xxx_2`，加工层会把它当成另一个笔记 ID。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        json.loads(text)
        ext = ".json"
    except Exception:
        ext = ".txt"

    path = out_dir / (filename + ext)
    if path.exists() and not overwrite:
        n = 2
        while path.exists():
            path = out_dir / f"{filename}_{n}{ext}"
            n += 1
    path.write_text(text, encoding="utf-8")
    return path


def _store_dir(cfg, root):
    return root / cfg["store_dir"] / "blogger"


# ---------------------------------------------------------------- doctor

def cmd_doctor(cfg, actions):
    name = cfg.get("name", HERE.name)
    print(f"{name} · 自检")
    print("=" * 56)

    envp = env_file_path()
    has_env = bool(read_env_file(envp))
    has_local = (HERE / "config.local.json").is_file()
    src = f"{HERE.name}/config.json"
    if has_env:
        src += " + 项目根 .env  ← 凭证读这里"
    elif has_local:
        src += "（外挂 config.local.json）"
    print(f"配置文件      {src}")

    root = project_root(cfg)
    store = _store_dir(cfg, root)
    print(f"落盘目录      {cfg['store_dir']}/blogger"
          + ("" if store.is_dir() else "（还没建，采集时会自动建）"))

    o = cfg.get("openapi") or {}
    if not (o.get("client_id") and o.get("api_key")):
        print("开放平台凭证  没填 ← 这条链全走 HTTP，不填什么都干不了")
        print(f"              打开项目根 .env，填这两行：")
        print("                  GETNOTE_CLIENT_ID=cli_ 开头")
        print("                  GETNOTE_API_KEY=gk_live_ 开头")
        print("              没有 .env？照 .env.example 复制一份再填。")
        return 1

    base = str(o.get("base_url") or DEFAULT_BASE).rstrip("/")
    print(f"开放平台凭证  已填（来源：{'项目根 .env' if has_env else 'config.local.json'}）")
    print(f"接口地址      {base}")

    try:
        resp = http_json(f"{base}/resource/knowledge/list", o["client_id"], o["api_key"],
                         timeout=30, retries=1)
        d = resp.get("data") or {}
        kbs = d.get("topics") or d.get("list") or d.get("knowledge") or []
        print(f"连通性        OK  看到 {len(kbs)} 个知识库")
        for k in kbs[:8]:
            if not isinstance(k, dict):
                print(f"                {k}")
                continue
            tid = k.get("topic_id") or k.get("id") or ""
            n = k.get("note_count")
            if n is None:
                n = (k.get("stats") or {}).get("note_count")
            line = f"                {str(k.get('name') or '?')[:24]:<26}topic_id = {tid}"
            if n is not None:
                line += f"   （笔记 {n}）"
            print(line)
    except SystemExit as e:
        print("连通性        失败")
        print("  · " + str(e).splitlines()[0])
        return 1

    print("可用动作      " + "、".join(actions))
    print("-" * 56)
    print("就绪。")
    return 0


# ---------------------------------------------------------------- 抓完接清洗

def clean_after(cfg, root, paths, enabled=True):
    """采集落了盘，顺手把**同源**的加工跑掉。

    用户原话：「你抓到数据之后**不会主动调用文件做清洗**」
    「只会抓到这些文件里，但是没有到产出成的话，我是看不清也看不见的」

    所以每次真抓成功，这里就把 `03_加工/02_getnote/run.py blogger` 跑一遍，
    让 `04_产出/` 里立刻有东西 —— 不用用户记得第二步。

    **这是可选依赖**：加工层不在（被删了 / 搬走了）就跳过，采集照常工作，
    「删目录即卸载」依然成立。
    """
    if not enabled:
        print("\n（--no-clean：跳过出表）")
        return 0

    runner = root / "03_加工" / "02_getnote" / "run.py"
    if not runner.is_file():
        print(f"\n（加工层不在，跳过出表 —— {runner.relative_to(root)} 不存在）")
        return 0

    print("\n接清洗 → 03_加工/02_getnote/run.py blogger")
    print("-" * 56)
    try:
        proc = subprocess.run(
            [sys.executable, str(runner), "blogger", str(paths)],
            capture_output=True, timeout=600, cwd=str(root),
        )
    except subprocess.TimeoutExpired:
        print("清洗超时（>600s）。原始数据已经落盘了，稍后可以单独重跑。")
        return 0

    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    print(out.strip() or "（没有输出）")
    if proc.returncode != 0:
        print(f"⚠ 清洗返回非 0（rc={proc.returncode}）—— 原始数据没丢，问题出在加工那一步。")
        if err.strip():
            print(err.strip()[:800])
    return proc.returncode


# ---------------------------------------------------------------- 动作：博主列表

def cmd_bloggers(cfg, args):
    base, cid, key = openapi_creds(cfg)
    root = project_root(cfg)
    out_dir = _store_dir(cfg, root)

    print("博主列表")
    print("-" * 56)
    print("  接口    GET /resource/knowledge/bloggers")
    print(f"  知识库  {args.topic}")
    print("  花费    0（会员制，读接口不额外扣费）")
    print("-" * 56)

    url = f"{base}/resource/knowledge/bloggers?topic_id={urllib.parse.quote(args.topic)}"
    resp = http_json(url, cid, key)
    bloggers = ((resp.get("data") or {}).get("bloggers") or [])
    if not bloggers:
        print("这个知识库里没有订阅的博主。")
        return 1

    for b in bloggers:
        print(f"  {b.get('account_name')}   平台={b.get('platform')}"
              f"   内容数={b.get('notes_count')}   状态={b.get('hook_state')}")
        print(f"      follow_id = {b.get('follow_id_str')}（拿这个去拉内容列表）")
        if b.get("follow_link"):
            print(f"      主页       {b.get('follow_link')}")

    # 文件名沿用「昵称_follow_id」—— 加工层靠它认博主
    first = bloggers[0]
    name = slug(first.get("account_name") or "unknown", 30)
    fid = first.get("follow_id_str") or "noid"
    path = save_raw(json.dumps(resp, ensure_ascii=False, indent=2), out_dir,
                    f"_bloggers_{name}_{fid}")
    print(f"\n已落盘  {path.relative_to(root)}")
    print(f"        {len(bloggers)} 个博主")
    return 0


# ---------------------------------------------------------------- 博主名

def find_blogger_name(base, cid, key, topic, follow, out_dir):
    """按 follow_id 找博主昵称。

    `contents` / `details` 只拿到**内容**，列表里不带博主名 ——
    所以以前那两处直接打印的是 `follow_id` 那串数字，看着像丢了名字。

    两档，从省到费：
      ① 翻本地 `_bloggers_*.json`（零请求）
      ② 本地没有才问一次 `/bloggers`（读接口，不花额度）
    都拿不到就返回空串 —— 调用方退回显示 follow_id，**不瞎猜**。
    """
    # ① 本地
    try:
        for f in sorted(out_dir.glob("*_bloggers_*.json"), reverse=True):
            data = json.loads(f.read_text(encoding="utf-8")).get("data") or {}
            for b in data.get("bloggers") or []:
                if str(b.get("follow_id_str") or "") == str(follow):
                    n = (b.get("account_name") or "").strip()
                    if n:
                        return n
    except Exception:
        pass

    # ② 问一次接口
    try:
        resp = http_json(f"{base}/resource/knowledge/bloggers"
                         f"?topic_id={urllib.parse.quote(topic)}", cid, key)
        for b in ((resp.get("data") or {}).get("bloggers") or []):
            if str(b.get("follow_id_str") or "") == str(follow):
                return (b.get("account_name") or "").strip()
    except SystemExit:
        pass
    except Exception:
        pass
    return ""


def label_blogger(name: str, follow) -> str:
    """有名字就 `谢胜子（1397022）`，没有就只显示 follow_id。"""
    return f"{name}（{follow}）" if name else str(follow)


# ---------------------------------------------------------------- 内容列表（内部共用）

def fetch_contents(base, cid, key, topic, follow, pages, gap, limit=0, quiet=False):
    """翻页拉内容列表，返回 (contents, total)。

    `page_size` 参数**无效**，固定 20 条/页（实测）。靠 `has_more` 决定要不要继续。
    """
    items, page, total = [], 1, 0
    while page <= max(1, pages):
        url = (f"{base}/resource/knowledge/blogger/contents"
               f"?topic_id={urllib.parse.quote(topic)}"
               f"&follow_id={urllib.parse.quote(str(follow))}&page={page}")
        resp = http_json(url, cid, key)
        data = resp.get("data") or {}
        got = data.get("contents") or []
        if not got:
            break
        total = data.get("total") or total
        items.extend(got)
        if not quiet:
            print(f"    第 {page} 页  {len(got)} 条  （这个博主共 {total} 条）")
        if limit and len(items) >= limit:
            items = items[:limit]
            break
        if not data.get("has_more"):
            break
        page += 1
        time.sleep(max(0.0, gap))       # 桶级限流，翻页得歇
    return items, total


def cmd_contents(cfg, args):
    base, cid, key = openapi_creds(cfg)
    root = project_root(cfg)
    out_dir = _store_dir(cfg, root)

    who = find_blogger_name(base, cid, key, args.topic, args.follow, out_dir)

    print("内容列表")
    print("-" * 56)
    print("  接口    GET /resource/knowledge/blogger/contents")
    print(f"  博主    {label_blogger(who, args.follow)}")
    print("  花费    0（会员制）")
    print("-" * 56)

    items, total = fetch_contents(base, cid, key, args.topic, args.follow,
                                  args.pages, args.gap, limit=args.limit)
    if not items:
        print("一条都没拿到。检查 topic_id / follow_id 对不对。")
        return 1

    # 文件名叫**昵称**（和 `_bloggers_` 那套一致，看着像人话），拿不到才退回 follow_id
    name = args.name or who or args.follow
    # ⚠️ 文件名**不带日期，但必须保住前导下划线**：
    #    · 不带日期 —— 带上就会和昨天那批并存，覆盖失效、加工层读到双份
    #      （2026-09-20 实测踩过：20 条被当成 40 条）。哪次抓的看文件 mtime。
    #    · 前导 `_` —— 加工层用 `*_blogger-content_*` 这种 glob 认文件，少了它对不上。
    #    `_p1` 是命名占位（多页已合并成一个文件），加工层的正则要求这个后缀。
    path = save_raw(json.dumps({
        "topic_id": args.topic, "follow_id": str(args.follow),
        "total_available": total, "fetched": len(items), "contents": items,
    }, ensure_ascii=False, indent=2), out_dir,
        f"_blogger-contents_{slug(name, 30)}_p1")

    print(f"\n已落盘  {path.relative_to(root)}")
    print(f"        {len(items)} 条（博主共 {total} 条）")
    print("\n下一步：拉详情（逐字稿 + 封面都在详情里，一条命令出全套）")
    print(f"  python 01_采集/02_getnote/collect.py details "
          f"--topic {args.topic} --follow {args.follow} --limit {len(items)}")
    return 0


# ---------------------------------------------------------------- 动作：逐条详情

def cmd_details(cfg, args):
    base, cid, key = openapi_creds(cfg)
    root = project_root(cfg)
    out_dir = _store_dir(cfg, root)

    who = find_blogger_name(base, cid, key, args.topic, args.follow, out_dir)

    print("内容详情（逐字稿 + 封面）")
    print("-" * 56)
    print("  接口    GET /resource/knowledge/blogger/content/detail")
    print(f"  博主    {label_blogger(who, args.follow)}")
    print(f"  条数    {args.limit or '全部（按 --pages 翻页）'}")
    print("  花费    0（会员制）")
    print("-" * 56)

    # 先要一份清单才知道有哪些 post_id —— 内部拉，不落盘（要清单就单独跑 contents）
    print("  先拉内容列表（拿 post_id_alias）……")
    items, total = fetch_contents(base, cid, key, args.topic, args.follow,
                                  args.pages, args.gap, limit=args.limit, quiet=True)
    if not items:
        print("内容列表是空的，没法拉详情。")
        return 1
    print(f"  共 {len(items)} 条要拉（博主共 {total} 条）")

    ok = failed = got_text = got_cover = 0
    reasons: dict[str, int] = {}

    for i, it in enumerate(items, 1):
        alias = str(it.get("post_id_alias") or "")
        if not alias:
            failed += 1
            reasons["列表里没给 post_id_alias"] = reasons.get("列表里没给 post_id_alias", 0) + 1
            continue

        url = (f"{base}/resource/knowledge/blogger/content/detail"
               f"?topic_id={urllib.parse.quote(args.topic)}"
               f"&post_id={urllib.parse.quote(alias)}")
        try:
            resp = http_json(url, cid, key)
        except SystemExit as e:
            failed += 1
            reasons["请求失败"] = reasons.get("请求失败", 0) + 1
            print(f"    ! {alias}  {str(e).splitlines()[0]}")
            continue

        d = resp.get("data") or {}
        has_text = bool(str(d.get("post_media_text") or "").strip())
        has_cover = bool(str(d.get("post_cover") or "").strip())
        if has_text:
            got_text += 1
        if has_cover:
            got_cover += 1

        try:
            # ⚠️ 文件名**不带日期，但必须保住前导下划线**（和上面 contents 同理）：
            #    带日期 → 跨天并存、同一条内容变两个文件、加工层读双份；
            #    少了下划线 → 加工层 `*_blogger-content_*` 那个 glob 认不出。
            save_raw(json.dumps(resp, ensure_ascii=False, indent=2), out_dir,
                     f"_blogger-content_{alias}")
            ok += 1
        except Exception as e:
            failed += 1
            reasons[type(e).__name__] = reasons.get(type(e).__name__, 0) + 1
            continue

        flag = ("稿" if has_text else "**无稿**") + ("+封面" if has_cover else "")
        print(f"    + {i:>3}/{len(items)}  {alias}  {flag}")

        if i < len(items):
            time.sleep(max(0.0, args.gap))   # 桶级限流

    print("-" * 56)
    print(f"落盘 {ok}｜失败 {failed}")
    print(f"  有逐字稿  {got_text}/{ok}" + ("   ← 缺的那几条是源头就没有" if got_text < ok else ""))
    print(f"  有封面    {got_cover}/{ok}" + ("   ← 封面链接不过期，缺了可以重跑" if got_cover < ok else ""))
    if failed:
        print("失败原因：")
        for why, n in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  {n} 条   {why}")
    print(f"落盘目录  {out_dir.relative_to(root)}")

    if ok:
        clean_after(cfg, root, out_dir, enabled=not args.no_clean)
    return 0


# ---------------------------------------------------------------- 入口

def main():
    cfg = load_config()
    name = cfg.get("name", HERE.name)

    p = argparse.ArgumentParser(
        prog="collect.py",
        description=f"{name} · 采集入口（全走开放平台 HTTP API）。原始输出落进 02_储存，不做清洗。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=cfg.get("examples", ""),
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="自检：凭证填没填、接口通不通、有哪些知识库")

    pb = sub.add_parser("bloggers", help="博主列表 → 拿 follow_id")
    pb.add_argument("--topic", required=True, help="知识库 ID")

    pc = sub.add_parser("contents", help="内容列表 → 拿 post_id_alias")
    pc.add_argument("--topic", required=True, help="知识库 ID")
    pc.add_argument("--follow", required=True, help="博主的 follow_id")
    pc.add_argument("--name", default="", help="博主昵称，用来命名文件；不填就用 follow_id")
    pc.add_argument("--limit", type=int, default=0, help="最多拉多少条（0 = 不限）")
    pc.add_argument("--pages", type=int, default=40, help="最多翻多少页，每页固定 20 条")
    pc.add_argument("--gap", type=float, default=3.5, help="翻页间隔秒数，被限流就调大")

    pd = sub.add_parser("details", help="逐条详情 → 逐字稿 + 封面（★ 主命令，跑完自动出表）")
    pd.add_argument("--topic", required=True, help="知识库 ID")
    pd.add_argument("--follow", required=True, help="博主的 follow_id")
    pd.add_argument("--limit", type=int, default=20, help="拉多少条（默认 20；0 = 全部）")
    pd.add_argument("--pages", type=int, default=40, help="最多翻多少页")
    pd.add_argument("--gap", type=float, default=3.5, help="每条之间的间隔秒数，被限流就调大")
    pd.add_argument("--no-clean", action="store_true", help="抓完不自动出表")

    args = p.parse_args()

    if args.cmd == "doctor":
        return cmd_doctor(cfg, ["bloggers", "contents", "details"])
    if args.cmd == "bloggers":
        return cmd_bloggers(cfg, args)
    if args.cmd == "contents":
        return cmd_contents(cfg, args)
    if args.cmd == "details":
        return cmd_details(cfg, args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
