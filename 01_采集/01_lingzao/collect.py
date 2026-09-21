#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
灵造 · 采集入口

**这个文件夹是自包含的**：拷到任何地方都能跑，不依赖 01_采集 里的其他文件。
只要保证同目录有 config.json 就行。

要改的东西只有两处：
    调什么命令、带什么参数   →  文件末尾的 ACTIONS
    CLI 在哪、API Key       →  同目录的 config.json

灵造是付费源：不加 --go 只预演，确认了才真跑。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
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
TIMEOUT = 900  # 单次 CLI 调用上限（秒）
REG_ROOT = r"Software\AutoCrawlRouter"      # 独立注册表项的根
REG_SECTION = "lingzao"


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


def _reg_env(name):
    """
    直接读注册表里的**用户环境变量**（HKCU\\Environment）。

    为什么绕这一下：Windows 设完环境变量不会自动进已经开着的进程，
    直接读注册表就能「设完立刻用」，不用重开窗口。
    """
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ) as k:
            v, _ = winreg.QueryValueEx(k, name)
            return str(v).strip()
    except Exception:
        return ""


def _reg_app(field):
    """读独立注册表项 HKCU\\Software\\AutoCrawlRouter\\lingzao\\<field>。"""
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{REG_ROOT}\{REG_SECTION}",
                            0, winreg.KEY_READ) as k:
            v, _ = winreg.QueryValueEx(k, field)
            return str(v).strip()
    except Exception:
        return ""


def resolve_cred(env_name, reg_field):
    """
    按优先级找一个凭证值，返回 (值, 来源说明)。顺序：

        ① 进程环境变量
        ② 注册表里的用户环境变量（刚设完、还没刷新的情况）
        ③ 独立注册表项 HKCU\\Software\\AutoCrawlRouter\\lingzao
        ④ 项目根 .env

    ★ **前三项都在你自己的电脑里，打包带走不了** —— 这就是这个顺序存在的理由。
      .env 排最后只作兼容。要设凭证：`python 05_技能/set_key.py`
    """
    v = (os.environ.get(env_name) or "").strip()
    if v:
        return v, f"环境变量 {env_name}"
    v = _reg_env(env_name)
    if v:
        return v, f"用户环境变量 {env_name}"
    v = _reg_app(reg_field)
    if v:
        return v, f"注册表 HKCU\\{REG_ROOT}\\{REG_SECTION}"
    v = (read_env_file(HERE.parent.parent / ".env").get(env_name) or "").strip()
    if v:
        return v, "项目根 .env（建议搬进环境变量，见 05_技能/set_key.py）"
    return "", ""


def load_config():
    """
    配置来源，越靠前越优先：

        ① 进程环境变量           ┐
        ② 注册表里的用户环境变量  ├ ★ 凭证的家 —— 只在你电脑里，打包带不走
        ③ 独立注册表项           ┘
        ④ 项目根 .env            ← 兼容保留；真值不该放这儿
        ⑤ 同目录 config.json / config.local.json（结构 + 说明，进 git）

    ★ 灵造的 key 平时由 CLI 自己管（`~/.lingzao/config.json`），**这里通常留空就行**。
      只有「想给本项目单独用一个 key」时才需要设 LINGZAO_API_KEY。
      设凭证：`python 05_技能/set_key.py lingzao --api-key lgz_xxx`
    """
    cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    local = HERE / "config.local.json"
    if local.is_file():
        _overlay(cfg, json.loads(local.read_text(encoding="utf-8")))

    auth = cfg.setdefault("auth", {})
    val, _src = resolve_cred("LINGZAO_API_KEY", "api_key")
    if val:
        auth["api_key"] = val
    val, _src = resolve_cred("LINGZAO_BASE_URL", "base_url")
    if val:
        auth["base_url"] = val
    return cfg


def project_root(cfg):
    """02_储存 在哪。默认按「本文件往上两级」推断，搬走了才需要在 config 里写死。"""
    r = cfg.get("project_root")
    return Path(r).expanduser().resolve() if r else HERE.parent.parent


def resolve_cli(cfg):
    """按 显式路径 → 环境变量 → 候选位置 → PATH 的顺序找 CLI。找不到回 None。"""
    c = cfg.get("cli", {})
    cands = [c.get("path")]
    if c.get("env"):
        cands.append(os.environ.get(c["env"]))
    cands += [Path(x).expanduser() for x in c.get("candidates", [])]
    cands += [shutil.which(x) for x in c.get("which", [])]

    for cand in cands:
        if not cand:
            continue
        try:
            p = Path(cand)
            if p.is_file():
                return p
        except (OSError, ValueError):
            continue
    return None


def env_for_cli(cfg):
    """只在本文件夹填了 key 时才设环境变量 —— 不填就完全交给 CLI 自己。"""
    auth = cfg.get("auth", {})
    env = dict(auth.get("extra_env") or {})
    if auth.get("api_key"):
        env[auth["env"]] = auth["api_key"]
    return env


# ---------------------------------------------------------------- 工具

_CMD_META = re.compile(r"[&|<>^()\s]")


def _quote_for_cmd(arg):
    """
    给参数补引号，让 cmd.exe 别把里面的 & | < > 当成命令分隔符。

    必须在参数里有这些字符时才加 —— 加了引号后 cmd 会把整段当字面量，
    这也是为什么不能反过来"给所有参数都加引号"：那会改动原本正常的调用。
    """
    arg = str(arg)
    if _CMD_META.search(arg):
        return '"' + arg.replace('"', '""') + '"'
    return arg


def run_cli(cli, argv, extra_env=None, timeout=TIMEOUT):
    args = [str(cli)] + [str(a) for a in argv]
    env = os.environ.copy()
    env.update({k: v for k, v in (extra_env or {}).items() if v})

    # .cmd / .bat 是批处理，最终由 cmd.exe 解释。Python 传参数组时只在含空格或
    # Tab 的情况下才加引号，于是 URL 里的 & 会被 cmd 当成命令分隔符 ——
    # 小红书博主主页的分享链接（?xsec_token=...&xsec_source=pc_feed）必踩。
    # 所以这种情况自己拼命令行、走 shell，并给含元字符的参数补上引号。
    need_shell = (
        os.name == "nt"
        and str(cli).lower().endswith((".cmd", ".bat"))
        and any(_CMD_META.search(a) for a in args)
    )
    if need_shell:
        line = " ".join(_quote_for_cmd(a) for a in args)
        if line.startswith('"'):  # cmd /c 会剥掉首尾引号，整体再包一层挡住
            line = '"' + line + '"'
        proc = subprocess.run(line, shell=True, capture_output=True,
                              timeout=timeout, env=env)
    else:
        proc = subprocess.run(args, capture_output=True, timeout=timeout, env=env)

    return (
        proc.returncode,
        proc.stdout.decode("utf-8", "replace"),
        proc.stderr.decode("utf-8", "replace"),
    )


def slug(s, limit=40):
    s = re.sub(r"^https?://", "", str(s or ""))
    s = re.sub(r"[\\/:*?\"<>|\s#]+", "_", s).strip("_")
    return s[:limit] or "untitled"


def fill(template, values):
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1)) or ""), template)


def build_argv(spec, values):
    """
    填 argv 模板。遇到「--开关 + {占位符}」这一对，占位符没值就把整对丢掉 ——
    否则会把 --sort {sort} 原样甩给 CLI，报一堆莫名其妙的参数错。
    """
    raw = list(spec["argv"])
    out, i = [], 0
    while i < len(raw):
        tok = raw[i]
        nxt = raw[i + 1] if i + 1 < len(raw) else None
        if tok.startswith("--") and nxt and nxt.startswith("{") and nxt.endswith("}"):
            val = values.get(nxt[1:-1])
            if val in (None, ""):
                i += 2
                continue
            out += [tok, str(val)]
            i += 2
            continue
        out.append(tok)
        i += 1
    return out


def save_raw(text, out_dir, filename):
    """原始输出原样落盘。能当 JSON 解析就 .json，否则 .txt —— 绝不丢内容，重名加序号。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        json.loads(text)
        ext = ".json"
    except Exception:
        ext = ".txt"

    path = out_dir / (filename + ext)
    n = 2
    while path.exists():
        path = out_dir / f"{filename}_{n}{ext}"
        n += 1
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------- 封面

_COVER_EXT = {"image/webp": ".webp", "image/jpeg": ".jpg", "image/jpg": ".jpg",
              "image/png": ".png", "image/gif": ".gif"}


def download_covers(payload, root):
    """
    把 profile 里每条笔记的封面当场下下来。

    **为什么必须当场下**：封面 URL 带着过期签名（查询串里的 `t=` 就是生成那一刻的
    十六进制时间戳），实测过三个小时再下就全返回 HTTP 498，神仙难救。
    所以这步紧跟在落盘后面，不另开一次操作。

    落 `04_产出/图片/<昵称>_<账号ID>/<笔记ID>.<ext>`：
    文件名用**笔记 ID**（永远不变），加工层的 bundle 再从这里取图归位到各条内容文件夹。
    """
    data = payload.get("data") or {}
    if data.get("type") != "analyze-user-profile":
        return
    items = data.get("items") or []
    if not items:
        return

    user = data.get("user") or {}
    dir_name = f"{slug(user.get('nickname') or 'unknown', 30)}_{user.get('id') or 'noid'}"
    out_dir = root / "04_产出" / "图片" / dir_name
    out_dir.mkdir(parents=True, exist_ok=True)

    ok = skipped = failed = 0
    err = ""
    for it in items:
        nid = it.get("id") or ""
        url = (it.get("media") or {}).get("cover_large_url") or ""
        if not nid or not url:
            skipped += 1
            continue
        if any((out_dir / (nid + ext)).is_file() for ext in _COVER_EXT.values()):
            skipped += 1          # 已经有了就不重复下
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
                ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        except urllib.error.HTTPError as e:
            failed += 1
            err = f"HTTP {e.code}" + ("（签名过期）" if e.code == 498 else "")
            continue
        except Exception as e:
            failed += 1
            err = type(e).__name__
            continue
        if body:
            (out_dir / (nid + _COVER_EXT.get(ctype, ".jpg"))).write_bytes(body)
            ok += 1

    print(f"封面    {out_dir.relative_to(root)}")
    print(f"        成功 {ok}｜已有跳过 {skipped}｜失败 {failed}"
          + (f"  最后一次错误：{err}" if err else ""))


# ---------------------------------------------------------------- 字幕合集

def download_subtitle_collection(payload, out_dir, stem, root):
    """
    把灵造的「完整字幕合集」下下来。

    **为什么必须单独下这一步**：JSON 里 `items[].text.subtitle` 那份字幕是
    **截断版** —— 实测 16 条有字幕的里，14 条长度正好卡在 1203 字。全文不在
    items 里，而是**顶层响应字段**：

        data.artifacts.subtitle_markdown.status   ready / 其它
        data.artifacts.subtitle_markdown.url      静态文件地址
        data.artifacts.subtitle_markdown.size_bytes

    ⚠️ 别在 `items[].artifacts` 里找 —— 那个是空的，第一次就查错了地方。

    这个 URL 是公开签名的静态文件（`visibility: public`、`expires_at: null`），
    下载**不调灵造 API、不扣积分、不花钱**。但它只在本次响应里给出，
    所以趁落盘这一次一起拿，别等以后再想补。

    落**两个**文件（都跟源 JSON 同前缀）：

        <stem>_完整字幕合集.md     正文（原样，不解析）
        <stem>_artifacts.json      来源 URL + 校验值 + 下载结果
                                   —— 见 write_artifact_sidecar()

    `bundle.find_collection()` 按**同前缀**精确配对（同一博主重抓多次会有多份，
    只有同前缀才能确定是哪一次的）。
    """
    data = payload.get("data") or {}
    if data.get("type") != "analyze-user-profile":
        return ""

    sm = (data.get("artifacts") or {}).get("subtitle_markdown") or {}
    status = (sm.get("status") or "").strip()
    url = sm.get("url") or ""

    saved: Path | None = None
    body = b""
    nbytes = 0
    got_sha = ""
    note = ""            # 没下成的原因（空 = 下成了）

    if not url:
        note = f"本次没给 URL（status={status or '无'}）"
    elif status and status != "ready":
        # 转写还没跑完。不重试 —— 下次重抓时会带上（重抓会重新走一遍 API）
        note = f"还没生成好（status={status}）"
    else:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            note = f"下载失败：HTTP {e.code}"
        except Exception as e:
            note = f"下载失败：{type(e).__name__}"
        else:
            if not body:
                note = "下下来是空的"

    if body and not note:
        saved = out_dir / f"{stem}_完整字幕合集.md"
        saved.write_bytes(body)          # 原样落盘，不解析
        nbytes = len(body)
        got_sha = hashlib.sha256(body).hexdigest()

        # 校验：服务端给了 size 和 sha256，两个都比。
        # ⚠️ 只比 size 不够 —— 内容坏掉不一定改大小。sha256 才是硬证据。
        problems = []
        if sm.get("size_bytes") and int(sm["size_bytes"]) != nbytes:
            problems.append(f"大小不符（服务端 {sm['size_bytes']}）")
        want_sha = str(sm.get("sha256") or "").lower()
        if want_sha and want_sha != got_sha:
            problems.append(f"sha256 不符（服务端 {want_sha[:12]}…）")

        print(f"字幕合集  {saved.relative_to(root)}")
        print(f"          {nbytes} 字节"
              + (f"   ⚠ {'；'.join(problems)}" if problems else "   ✓ 大小与 sha256 都对得上"))
    else:
        print(f"字幕合集  {note} —— 逐字稿只能取 JSON 里的截断版")

    # ★ 不管下成没下成，都把「URL + 结果」记进原始数据层
    write_artifact_sidecar(out_dir, stem, payload, saved, nbytes, got_sha, note)

    return str(saved) if saved else ""


def write_artifact_sidecar(out_dir, stem, payload, saved, nbytes, sha256, note):
    """把「这批数据的 artifact 从哪来、下到哪去」记成一份小文件。

    落 `<同 JSON 前缀>_artifacts.json` —— 跟主文件同前缀，一眼能配对。

    **为什么原始 JSON 里有 `data.artifacts` 还要单独记**：

    1. 它是**整个响应级别**的（一份合集覆盖整批笔记），埋在几百 KB 的 JSON 深处；
    2. 「下载成没成、校验过没有、落地叫什么名」这些**结果**压根不在响应里；
    3. 以后想重下全文，直接读这份小文件就知道 URL，不用拿 JSON 去 grep。

    用户 2026-09-20 的要求：「原始数据层也要把逐字稿的 URL 跟着抓下来」。
    """
    a = ((payload.get("data") or {}).get("artifacts") or {}).get("subtitle_markdown") or {}
    if not a and not note:
        return ""

    record = {
        "source": "lingzao",
        "raw_file": f"{stem}.json",
        "request_id": payload.get("request_id", ""),
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "subtitle_markdown": {
            # --- 服务端给的（URL 就在这儿，重下靠它）---
            "status": a.get("status", ""),
            "url": a.get("url", ""),
            "format": a.get("format", ""),
            "size_bytes": a.get("size_bytes"),
            "sha256": a.get("sha256", ""),
            "r2_key": a.get("r2_key", ""),
            "expires_at": a.get("expires_at"),
            "visibility": a.get("visibility", ""),
            # --- 本地下载结果 ---
            "saved_as": saved.name if saved else "",
            "saved_bytes": nbytes,
            "saved_sha256": sha256,
            "verified": bool(saved) and not note,
            "note": note,
        },
    }
    p = out_dir / f"{stem}_artifacts.json"
    p.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------- doctor

def cmd_doctor(cfg, actions):
    name = cfg.get("name", HERE.name)
    print(f"{name} · 自检")
    print("=" * 56)
    problems = []

    has_local = (HERE / "config.local.json").is_file()
    print(f"配置文件      {HERE.name}/config.json" + ("（外挂 config.local.json）" if has_local else ""))

    root = project_root(cfg)
    store = root / cfg["store_dir"]
    print(f"落盘目录      {cfg['store_dir']}" + ("" if store.is_dir() else "（还没建，采集时会自动建）"))

    auth = cfg.get("auth", {})
    if auth.get("api_key"):
        print("API Key       用本文件夹里填的那个")
    else:
        print(f"API Key       没填 → 用 CLI 自己存的（{auth.get('where', '位置见 README')}）")
        if auth.get("get_key_at"):
            print(f"              要换成自己的？去 {auth['get_key_at']} 拿")

    cli = resolve_cli(cfg)
    if not cli:
        problems.append(cfg.get("cli", {}).get("hint") or f"没找到 {name} 的 CLI")
        print("CLI           未找到")
    else:
        probe = cfg.get("probe", {})
        try:
            rc, out, err = run_cli(cli, probe.get("argv", ["--version"]), env_for_cli(cfg), timeout=120)
        except Exception as e:
            problems.append(f"CLI 调用异常：{e}")
            print("CLI           调用异常")
        else:
            expect = probe.get("expect", "")
            if rc == 0 and (expect in out if expect else True):
                detail = ""
                m = re.search(r"(?:用户|account|user)[:：]\s*(\S+)", out)
                if m:
                    detail = f"  {m.group(1)}"
                print(f"CLI           OK  {cli}{detail}")
            else:
                problems.append(auth.get("hint")
                                or f"{probe.get('label', '连通性')} 没通过（rc={rc}）。")
                print("CLI           未就绪")

    print("可用动作      " + "、".join(actions))
    print("-" * 56)

    if problems:
        print("照下面做就行：")
        for p in problems:
            lines = str(p).splitlines()
            print("  · " + lines[0])
            for ln in lines[1:]:
                print("    " + ln)
        return 1

    print("就绪。")
    return 0


# ---------------------------------------------------------------- 采集

def cmd_do(spec, cfg, values, go, clean=True):
    name = cfg.get("name", "")
    cli = resolve_cli(cfg)
    if not cli:
        print(f"没找到 {name} 的 CLI。先跑 `doctor` 看看，或在这个文件夹的 config.json 里填 cli.path。")
        return 1

    root = project_root(cfg)
    argv = build_argv(spec, values)
    filename = slug(fill(spec["filename"], values), limit=80)
    out_dir = root / cfg["store_dir"] / spec["sub_dir"] if spec.get("sub_dir") else root / cfg["store_dir"]
    rel = out_dir.relative_to(root)
    paid = bool(cfg.get("paid", False))

    print(f"{spec.get('label', '采集')}")
    print("-" * 56)
    print(f"  CLI     {cli}")
    print(f"  命令    {' '.join(str(x) for x in argv)}")
    print(f"  落盘    {rel}\\{filename}.json")
    print(f"  花费    {spec.get('cost', '未知')}")
    print("-" * 56)

    if paid and not go:
        print("这一步会花钱，所以只预演，不真跑。")
        print("确认上面都对，末尾加 --go 再来一次。")
        return 0

    print("执行中……")
    try:
        rc, out, err = run_cli(cli, argv, env_for_cli(cfg))
    except subprocess.TimeoutExpired:
        print(f"超时（>{TIMEOUT}s），没落盘。稍后重试，或缩小范围。")
        return 1

    if rc != 0:
        print(f"CLI 返回非 0（rc={rc}），没有落盘。")
        if err.strip():
            print(err.strip()[:1200])
        return rc

    # 有的 CLI 即使 rc=0 也会在正文里报失败
    try:
        payload = json.loads(out)
        if isinstance(payload, dict) and payload.get("success") is False:
            print("CLI 报告 success=false，没有落盘。")
            print(json.dumps(payload.get("error", {}), ensure_ascii=False, indent=2)[:800])
            return 1
    except Exception:
        pass

    if not out.strip():
        print("CLI 成功了但一个字都没返回，没有落盘。")
        return 1

    path = save_raw(out, out_dir, filename)
    print(f"已落盘  {path.relative_to(root)}")
    print(f"        {len(out)} 字符")

    # 解析一次 —— 封面和字幕合集都要用它，别 load 两遍
    try:
        payload = json.loads(out)
    except Exception:
        payload = None

    if payload:
        # 封面签名会过期，晚一步就废了 —— 落盘后立刻抓
        try:
            download_covers(payload, root)
        except Exception as e:
            print(f"封面    跳过（{e}）")

        # 字幕全文是顶层 artifact，不在 items 里 —— 一起下（不花钱）
        # ⚠️ 用 path.stem 而不是 filename：save_raw 遇重名会加 `_2`
        #    （同一天重抓同一个博主就会），合集必须跟实际 JSON 同名才配得上
        try:
            download_subtitle_collection(payload, out_dir, path.stem, root)
        except Exception as e:
            print(f"字幕合集  跳过（{e}）")

    # 抓完顺手接清洗 —— 别让用户记得第二步（详见 clean_after 的注释）
    clean_after(cfg, root, path, spec.get("clean"), enabled=clean)
    return 0


# ---------------------------------------------------------------- 抓完接清洗

def clean_after(cfg, root, path, action, enabled=True):
    """采集落了盘，顺手把**同源**的加工跑掉。

    用户原话：「你抓到数据之后**不会主动调用文件做清洗**」
    「只会抓到这些文件里，但是没有到产出成的话，我是看不清也看不见的」

    所以每次真抓成功，这里就把对应的加工动作跑一遍，让 `04_产出/` 里立刻有东西 ——
    不用用户记得第二步。

    **这是可选依赖**：加工层不在（被删了 / 搬走了）就跳过，采集照常工作，
    「删目录即卸载」依然成立。
    """
    if not enabled:
        print("\n（--no-clean：跳过出表）")
        return 0
    if not action:
        return 0

    runner = root / "03_加工" / "01_lingzao" / "run.py"
    if not runner.is_file():
        print(f"\n（加工层不在，跳过出表 —— {runner.relative_to(root)} 不存在）")
        return 0

    print(f"\n接清洗 → 03_加工/01_lingzao/run.py {action}")
    print("-" * 56)
    try:
        proc = subprocess.run(
            [sys.executable, str(runner), action, str(path)],
            capture_output=True, timeout=900, cwd=str(root),
        )
    except subprocess.TimeoutExpired:
        print("清洗超时（>900s）。原始数据已经落盘了，稍后可以单独重跑。")
        return 0

    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    print(out.strip() or "（没有输出）")
    if proc.returncode != 0:
        print(f"⚠ 清洗返回非 0（rc={proc.returncode}）—— 原始数据没丢，问题出在加工那一步。")
        if err.strip():
            print(err.strip()[:800])
    return proc.returncode


# ---------------------------------------------------------------- 动作定义

ACTIONS = {
    "search": {
        "label": "按关键词搜笔记",
        "cost": "20 积分/次",
        "sub_dir": "search-notes",
        "clean": "search",
        "filename": "{date}_search-notes_{keyword_slug}",
        "argv": [
            "search-notes", "--platform", "xhs",
            "--keyword", "{keyword}",
            "--sort", "{sort}",
            "--note-type", "{note_type}",
            "--time-filter", "{time_filter}",
            "--format", "json",
        ],
        "args": {
            "keyword": {"required": True, "help": "搜索词"},
            "sort": {"help": "general / most_liked / popularity_descending / comment_descending / collect_descending"},
            "note-type": {"help": "不限 / 视频笔记 / 图文笔记 / 直播笔记"},
            "time-filter": {"help": "不限 / 一天内 / 一周内 / 半年内"},
        },
    },

    "profile": {
        "label": "深挖单个博主",
        "cost": "50–100 积分（按条数：1–20 条 50，21–40 条 100）",
        "sub_dir": "analyze-user-profile",
        "filename": "{date}_profile_{url_slug}",
        "clean": "bundle",
        "argv": [
            "analyze-user-profile",
            "--url", "{url}",
            "--limit", "{limit}",
            "--format", "json",
        ],
        "args": {
            "url": {"required": True, "help": "博主主页 URL"},
            "limit": {"help": "抓多少条笔记，默认 20"},
        },
    },
}


# ---------------------------------------------------------------- 入口

def main():
    cfg = load_config()
    name = cfg.get("name", HERE.name)

    p = argparse.ArgumentParser(
        prog="collect.py",
        description=f"{name} · 采集入口。原始输出落进 02_储存，不做清洗。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=cfg.get("examples", ""),
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="自检：CLI 在不在、连不连得通、配置填对没有")

    for aname, spec in ACTIONS.items():
        sp = sub.add_parser(aname, help=spec.get("label", aname))
        for arg, meta in (spec.get("args") or {}).items():
            kw = {"help": meta.get("help", "")}
            if meta.get("required"):
                kw["required"] = True
            else:
                kw["default"] = ""
            sp.add_argument("--" + arg, **kw)
        sp.add_argument("--go", action="store_true", help="真的跑（付费源才需要）")
        sp.add_argument("--no-clean", action="store_true", help="抓完不自动出表")

    args = p.parse_args()

    if args.cmd == "doctor":
        return cmd_doctor(cfg, ACTIONS)

    spec = ACTIONS[args.cmd]
    values = {"date": datetime.now().strftime("%Y-%m-%d")}
    values.update({k: v for k, v in vars(args).items() if k != "go"})
    for key in ("keyword", "query", "url"):
        values[key + "_slug"] = slug(values.get(key, ""))

    return cmd_do(spec, cfg, values, go=args.go, clean=not args.no_clean)


if __name__ == "__main__":
    sys.exit(main())
