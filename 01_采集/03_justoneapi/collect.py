#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
JustOneAPI 采集器 —— 规格驱动，一个执行器跑 371 个接口。

    python 01_采集/03_justoneapi/collect.py doctor
    python 01_采集/03_justoneapi/collect.py list xhs
    python 01_采集/03_justoneapi/collect.py balance
    python 01_采集/03_justoneapi/collect.py call xhs.search_user keyword=养生
    python 01_采集/03_justoneapi/collect.py call xhs.search_user keyword=养生 --go
    python 01_采集/03_justoneapi/collect.py accounts --platform xhs --keyword 养生 --go

★ 三条规矩（跟另外两个源一致）
  1. 付费动作默认只预演，加 --go 才真跑
  2. 凭证存你自己电脑（环境变量 / 注册表），项目里一个 key 都不留
  3. 每次调用的完整响应原样落盘，一个字节都不删

★ 这个源跟灵造/得到大脑不一样的地方
  接口有 371 个，不可能一个接口写一个函数。所以：
      spec/public-api.json   接口字典（参数、必填、类型、说明）
      config.json            动作表（只记「调哪个接口」，加动作不改代码）
      collect.py             一个通用执行器
  加接口 = 在 config.json 的 endpoints 里加一行。

★ 两个容易踩的坑（都实测过）
  - GET 的 token 放 URL 参数，POST 的 token 放 form body，不是 header
  - 业务码 code=0 才算成功；失败的请求不计费
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SPEC_PATH = HERE / "spec" / "public-api.json"
CONFIG_PATH = HERE / "config.json"

REG_ROOT = r"Software\AutoCrawlRouter"
REG_SECTION = "justoneapi"

STORE_DIR = ROOT / "02_储存" / "03_justoneapi"

# 业务码 → 人话
CODES = {
    0: "成功（计费）",
    100: "Token 无效或已失效（不计费）",
    301: "采集失败，请重试（不计费）",
    302: "超出速率限制（不计费）",
    303: "超出每日配额（不计费）",
    400: "参数错误（不计费）",
    500: "内部服务器错误（不计费）",
    600: "权限不足（不计费）",
    601: "账户余额不足（不计费）",
    602: "TOKEN 累计消费超限（不计费）",
}

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ---------------------------------------------------------------- 凭证
def _reg_env(name):
    """直接读注册表里的用户环境变量（HKCU\\Environment）。

    绕这一下是为了「刚设完还没重启」—— Windows 的环境变量不会自动进
    已经开着的进程，读注册表就能立刻用上。
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
    """读独立注册表项 HKCU\\Software\\AutoCrawlRouter\\justoneapi\\<field>。"""
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


def _read_env_file(path):
    if not path.is_file():
        return {}
    out = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        v = v.strip().strip('"').strip("'")
        if v:
            out[k.strip()] = v
    return out


def resolve_cred(env_name, reg_field):
    """按优先级找凭证，返回 (值, 来源说明)。

        ① 进程环境变量
        ② 注册表里的用户环境变量（刚设完没刷新的情况）
        ③ 独立注册表项 HKCU\\Software\\AutoCrawlRouter\\justoneapi
        ④ 项目根 .env（兜底兼容）

    ★ 前三项都在你自己的电脑里，打包带走不了。
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
    v = (_read_env_file(ROOT / ".env").get(env_name) or "").strip()
    if v:
        return v, "项目根 .env（建议搬进环境变量，见 05_技能/set_key.py）"
    return "", ""


def mask_token(s):
    """token 一律打码 —— 它出现在 URL 里，日志一泄就废了。"""
    if not s:
        return ""
    s = str(s)
    if len(s) <= 6:
        return "*" * len(s)
    return s[:3] + "*" * (len(s) - 5) + s[-2:]


def load_config():
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    token, src = resolve_cred(cfg.get("auth", {}).get("env", "JUSTONEAPI_TOKEN"), "api_key")
    cfg["_token"] = token
    cfg["_token_source"] = src
    return cfg


# ---------------------------------------------------------------- spec
def load_spec():
    if not SPEC_PATH.is_file():
        raise SystemExit(
            f"缺接口字典：{SPEC_PATH}\n"
            "  从官方仓库拉一份：python 01_采集/03_justoneapi/collect.py sync-spec"
        )
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def op_of(spec, path):
    """返回 (method, op_dict)。"""
    item = (spec.get("paths") or {}).get(path)
    if not item:
        return None, None
    for m, op in item.items():
        if isinstance(op, dict):
            return m.upper(), op
    return None, None


def params_of(op):
    """拆成 (query 参数, form 参数)，每项 (名字, 是否必填, 说明)。token 已经剔掉。"""
    q = []
    for p in op.get("parameters") or []:
        if p.get("name") == "token":
            continue
        q.append((p["name"], bool(p.get("required")), (p.get("description") or "").strip()))
    f = []
    rb = op.get("requestBody") or {}
    form = (rb.get("content") or {}).get("application/x-www-form-urlencoded")
    if form:
        sch = form.get("schema") or {}
        req = set(sch.get("required") or [])
        for name, sub in (sch.get("properties") or {}).items():
            if name == "token":
                continue
            f.append((name, name in req, (sub.get("description") or "").strip()))
    return q, f


def iter_endpoints(spec, tag=None, include_hidden=False):
    """遍历 spec 里的接口，可按平台标签过滤。默认跳过 x-docs-hidden（废弃版本）。"""
    for path, item in (spec.get("paths") or {}).items():
        for m, op in item.items():
            if not isinstance(op, dict):
                continue
            if not include_hidden and op.get("x-docs-hidden"):
                continue
            tags = op.get("tags") or []
            if tag and tag not in tags:
                continue
            yield path, m.upper(), op, tags


# ---------------------------------------------------------------- 余额（走 MCP，免费）
def mcp_call(cfg, tool, args=None, timeout=20, retries=1):
    """调 MCP 的 tools/call。MCP 支持无状态直调，不用先 initialize。

    返回解析后的 dict；失败返回 None（查余额失败不该影响主流程）。
    ★ 超时给短（20 秒）—— 实测这个域名偶尔卡住，卡 45 秒×3 次会把整个命令拖死。
    """
    url = cfg.get("mcp_url") or "https://mcp.justoneapi.com/mcp"
    token = cfg.get("_token") or ""
    if not token:
        return None
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": tool, "arguments": args or {}}}
    data = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {token}",
        "User-Agent": cfg.get("user_agent") or "Mozilla/5.0",
    }
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
            # 响应是 SSE：取最后一条 data: 行
            for line in reversed(raw.splitlines()):
                if line.startswith("data:"):
                    obj = json.loads(line[5:].strip())
                    txt = obj["result"]["content"][0]["text"]
                    return json.loads(txt)
            return json.loads(raw)
        except Exception as e:  # 网络抖动就重试，查余额失败不该阻断采集
            last_err = e
            if attempt < retries:
                time.sleep(2)
    print(f"  （余额查询失败：{type(last_err).__name__}，不影响采集）")
    return None


def get_balance(cfg):
    """返回 {"balance": 1.95, "currency": "CNY"} 或 None。免费。"""
    r = mcp_call(cfg, "get_account_balance")
    if not r or not r.get("success"):
        return None
    d = r.get("data") or {}
    try:
        return {"balance": round(float(d.get("availableBalance", d.get("balance", 0))), 4),
                "currency": d.get("currency") or "CNY"}
    except (TypeError, ValueError):
        return None


def get_usage(cfg):
    r = mcp_call(cfg, "get_usage_summary")
    if not r or not r.get("success"):
        return None
    d = r.get("data") or {}
    tok = d.get("token") or {}
    return {
        "used": tok.get("usedAmount"),
        "budget": tok.get("budgetAmount"),
        "total": d.get("totalAmount"),
        "currency": d.get("currency"),
    }


# ---------------------------------------------------------------- HTTP
def do_request(cfg, token, method, path, query, form, token_in_form):
    """发一次请求。返回 (http_status, payload, elapsed_ms, url_for_log)。

    ★ 参数放哪儿不是看 GET/POST，是看 spec 里怎么写：
        - 公众号 search-account/v1：POST，但参数全在 query
        - 视频号 search-account/v1：POST，参数全在 form body
      token 跟着走 —— 有 form 就进 form，否则进 query。
    """
    base = (cfg.get("base_url") or "https://api.justoneapi.com").rstrip("/")
    ua = cfg.get("user_agent") or "Mozilla/5.0"
    timeout = int(cfg.get("timeout") or 120)

    q = {k: v for k, v in (query or {}).items() if v not in (None, "")}
    f = {k: v for k, v in (form or {}).items() if v not in (None, "")}
    if token_in_form:
        f["token"] = token
    else:
        q["token"] = token

    url = f"{base}{path}"
    if q:
        url = f"{url}?{urllib.parse.urlencode(q)}"

    data = urllib.parse.urlencode(f).encode() if f else None
    headers = {"User-Agent": ua, "Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)

    # ★ 打日志时 token 必须打码 —— 它既在 URL 里也在 form body 里，
    #   任何一处漏掉，一次报错就把 token 写进了日志和截图。
    shown = {k: (mask_token(token) if k == "token" else v) for k, v in {**q, **f}.items()}
    body_note = ""
    if f:
        f_shown = {k: (mask_token(token) if k == "token" else v) for k, v in f.items()}
        body_note = "  [form: " + "&".join(f"{k}={v}" for k, v in f_shown.items()) + "]"
    q_shown = {k: v for k, v in shown.items() if k not in f}
    log_url = f"{base}{path}"
    if q_shown:
        log_url += "?" + "&".join(f"{k}={v}" for k, v in q_shown.items())
    log_url += body_note

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
    except Exception as e:
        return None, {"_transport_error": f"{type(e).__name__}: {e}"}, int((time.time() - t0) * 1000), log_url
    elapsed = int((time.time() - t0) * 1000)

    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        payload = {"_raw_text": raw.decode("utf-8", "replace")[:20000]}
    return status, payload, elapsed, log_url


# ---------------------------------------------------------------- 落盘
_ILLEGAL = re.compile(r'[\\/:*?"<>|\s]+')


def slug(s, limit=40):
    s = _ILLEGAL.sub("_", str(s or "")).strip("_")
    return (s[:limit] or "na")


def _param_digest(params):
    """把参数拼成一个可读的文件名片段：keyword=养生&page=1 → 养生_p1"""
    if not params:
        return "noargs"
    parts = []
    for k in sorted(params):
        v = params[k]
        if v in (None, ""):
            continue
        s = str(v)
        parts.append(s if len(s) <= 20 else s[:20])
    return slug("_".join(parts)) if parts else "noargs"


def save_run(cfg, endpoint_key, ep, params, payload, meta):
    """原样存完整响应 + 一份 meta。返回 (json_path, meta_path)。"""
    out_dir = STORE_DIR / endpoint_key
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"{ts}_{_param_digest(params)}"
    jp = out_dir / f"{stem}.json"
    mp = out_dir / f"{stem}.meta.json"

    text = json.dumps(payload, ensure_ascii=False, indent=1)
    jp.write_text(text, encoding="utf-8")

    meta = dict(meta)
    meta["file"] = jp.name
    meta["bytes"] = len(text.encode("utf-8"))
    meta["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    mp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return jp, mp, meta


LEDGER = STORE_DIR / "_ledger.jsonl"


def append_ledger(entry):
    """一行一条调用记录。余额会因充值跳动，这份台账才是「到底花了多少」的底账。"""
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 动作
def cmd_doctor(args):
    cfg = load_config()
    spec = load_spec()
    print("JustOneAPI · 自检")
    print("=" * 66)
    print(f"配置文件      {CONFIG_PATH.relative_to(ROOT)}")
    print(f"接口字典      {SPEC_PATH.relative_to(ROOT)}　"
          f"{len(spec.get('paths') or {})} 个接口")

    tok = cfg.get("_token")
    if tok:
        print(f"Token        {mask_token(tok)}　← {cfg.get('_token_source')}")
    else:
        print("Token        没找到 ✗")
        print(f"             设置：python 05_技能/set_key.py justoneapi --api-key <token>")

    eps = cfg.get("endpoints") or {}
    print(f"可用动作      {len(eps)} 个　（{'、'.join(sorted({k.split('.')[0] for k in eps}))}）")
    print(f"落盘目录      {STORE_DIR.relative_to(ROOT)}")

    if not tok:
        print("-" * 66)
        print("先解决 Token，再跑别的。")
        return 1

    print("-" * 66)
    print("查余额（免费）…", end="", flush=True)
    b = get_balance(cfg)
    if b:
        print(f" 余额 {b['currency']} {b['balance']}")
        u = get_usage(cfg)
        if u and u.get("used") is not None:
            print(f"             累计已花 {u['used']}　"
                  f"消费上限 {u['budget'] if u['budget'] else '未设 ⚠'}")
        if b["balance"] < 1:
            print("             ⚠ 余额不足 1 元，跑不了几次")
    else:
        print(" 查不到（网络或 MCP 的问题，不影响采集）")

    print("-" * 66)
    print("就绪。")
    print("  看有哪些接口：  python 01_采集/03_justoneapi/collect.py list xhs")
    print("  预演（不花钱）：python 01_采集/03_justoneapi/collect.py call xhs.search_user keyword=养生")
    return 0


def cmd_balance(args):
    cfg = load_config()
    if not cfg.get("_token"):
        raise SystemExit("缺 Token：python 05_技能/set_key.py justoneapi --api-key <token>")
    b = get_balance(cfg)
    if not b:
        print("查不到余额（网络或 MCP 的问题）")
        return 1
    u = get_usage(cfg) or {}
    print(f"余额        {b['currency']} {b['balance']}")
    if u.get("used") is not None:
        print(f"累计已花    {u['used']}")
        print(f"消费上限    {u['budget'] if u['budget'] else '未设（建议去 dashboard 设一个，防意外烧光）'}")
    return 0


def cmd_spent(args):
    """看本地台账：到底花了多少（余额会因充值跳动，这份账不受影响）。"""
    if not LEDGER.is_file():
        print("还没有调用记录。")
        return 0
    rows = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    if not rows:
        print("台账是空的。")
        return 0

    by_day = {}
    for r in rows:
        day = (r.get("at") or "")[:10] or "未知"
        d = by_day.setdefault(day, {"n": 0, "ok": 0, "cost": 0.0})
        d["n"] += 1
        if r.get("ok"):
            d["ok"] += 1
        d["cost"] += float(r.get("cost") or 0)

    print("调用台账（按价目表记账，失败不计费）")
    print("=" * 58)
    tn = tok_ = 0
    tcost = 0.0
    for day in sorted(by_day):
        d = by_day[day]
        print(f"  {day}   {d['n']:3} 次（成功 {d['ok']:3}）   ¥{round(d['cost'], 4)}")
        tn += d["n"]
        tok_ += d["ok"]
        tcost += d["cost"]
    print("-" * 58)
    print(f"  合计      {tn:3} 次（成功 {tok_:3}）   ¥{round(tcost, 4)}")

    cfg = load_config()
    if cfg.get("_token"):
        print()
        b = get_balance(cfg)
        if b:
            print(f"  当前余额  {b['currency']} {b['balance']}")
    print()
    print("  明细文件  " + str(LEDGER.relative_to(ROOT)))
    return 0


TAG_OF = {
    "xhs": "Xiaohongshu (RedNote)",
    "dy": "Douyin (TikTok China)",
    "sph": "WeChat Channels",
    "gzh": "WeChat Official Accounts",
}


def cmd_list(args):
    cfg = load_config()
    spec = load_spec()
    plat = (args.platform or "").strip().lower()
    tag = TAG_OF.get(plat, plat or None)
    if plat and not tag:
        print(f"不认识的平台：{plat}　可用：{'、'.join(TAG_OF)}")
        return 1

    pricing = cfg.get("pricing") or {}
    eps = cfg.get("endpoints") or {}
    by_path = {v["path"]: (k, v) for k, v in eps.items()}

    rows = list(iter_endpoints(spec, tag=tag, include_hidden=args.all))
    rows.sort(key=lambda x: x[0])
    print(f"{plat or '全部平台'}　{len(rows)} 个可用接口"
          f"{'（含已隐藏的废弃版本）' if args.all else ''}")
    print("=" * 96)
    for path, m, op, tags in rows:
        mark = "★" if path in by_path else " "
        price = pricing.get(path)
        ps = f"¥{price:<5}" if price is not None else "  ?   "
        q, f = params_of(op)
        req = [n for n, r, _ in q + f if r]
        print(f" {mark} {m:5} {path:56} {ps} {op.get('summary','')[:26]:26} 必填:{','.join(req) or '-'}")
    print("-" * 96)
    print("★ = 已经在 config.json 里配好动作，可以直接 call")
    if not args.all:
        print("（想连废弃版本一起看：加 --all）")
    return 0


def _parse_pairs(pairs):
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"参数要写成 k=v 的样子，这个是：{p}")
        k, _, v = p.partition("=")
        out[k.strip()] = v
    return out


def _run_one(cfg, spec, key, params, go):
    """预演或真跑一个动作。返回 0/1。"""
    eps = cfg.get("endpoints") or {}
    if key not in eps:
        # 允许直接传 path
        hit = [k for k, v in eps.items() if v["path"] == key]
        if not hit:
            print(f"不认识的动作：{key}")
            print(f"  可用：{'、'.join(sorted(eps))}")
            print(f"  或者先 list 看看：python 01_采集/03_justoneapi/collect.py list xhs")
            return 1
        key = hit[0]
    ep = eps[key]
    path, method = ep["path"], ep["method"]
    cost = ep.get("cost")

    _, op = op_of(spec, path)
    if op is None:
        print(f"spec 里找不到这个接口：{path}")
        return 1
    q, f = params_of(op)
    declared = {n: (r, d) for n, r, d in q + f}

    unknown = [k for k in params if k not in declared]
    if unknown:
        print(f"⚠ 这些参数接口不认识，会被一起发出去：{', '.join(unknown)}")
    missing = [n for n, (r, d) in declared.items() if r and n not in params]
    if missing:
        print(f"✗ 缺必填参数：{', '.join(missing)}")
        for n, (r, d) in declared.items():
            flag = "必填" if r else "可选"
            print(f"    {n:16} {flag}  {d[:60]}")
        return 1

    print(f"{ep['label']}")
    print(f"  {method} {path}")
    print(f"  参数：{json.dumps(params, ensure_ascii=False) or '（无）'}")
    print(f"  单价：¥{cost if cost is not None else '未知'}")

    if not go:
        print("  ★ 预演模式 —— 没有调用，也没有花钱。加 --go 才真跑。")
        return 0

    token = cfg.get("_token")
    if not token:
        print("✗ 缺 Token：python 05_技能/set_key.py justoneapi --api-key <token>")
        return 1

    before = get_balance(cfg)
    if before:
        print(f"  跑前余额：{before['currency']} {before['balance']}")
        if before["balance"] < (cost or 0):
            print(f"✗ 余额不够这次调用（需要 ¥{cost}）")
            return 1

    # ★ 按 spec 的 in 拆参数：query 的进 URL，form 的进 body。
    #   接口有没有 form 定义，也决定 token 放哪。
    q_names = {n for n, _r, _d in q}
    f_names = {n for n, _r, _d in f}
    q_vals, f_vals = {}, {}
    for k, v in params.items():
        if k in q_names:
            q_vals[k] = v
        elif k in f_names:
            f_vals[k] = v
        else:
            # spec 没声明的参数：有 form 就放 form，否则放 query
            (f_vals if f_names else q_vals)[k] = v
    token_in_form = bool(f_names)

    # ★ 301 = 上游采集失败，官方原话就是「SEND REQUEST AGAIN」，而且不计费。
    #   实测抖音第一次 301、第二次就成功，所以自动重试，别让用户自己再来一遍。
    max_retry = int(cfg.get("retry_on_301") or 2)
    attempts = 0
    total_ms = 0
    print("  调用中…", end="", flush=True)
    while True:
        attempts += 1
        status, payload, elapsed, log_url = do_request(
            cfg, token, method, path, q_vals, f_vals, token_in_form)
        total_ms += elapsed
        code_now = payload.get("code") if isinstance(payload, dict) else None
        print(f" {elapsed}ms", end="", flush=True)
        if code_now == 301 and attempts <= max_retry:
            print(f"  ← 301 上游采集失败（不计费），2 秒后重试 {attempts}/{max_retry}")
            time.sleep(2)
            print("  重试中…", end="", flush=True)
            continue
        break
    print()
    print(f"  {log_url}")
    elapsed = total_ms

    # 余额与对账
    after = get_balance(cfg)
    code = payload.get("code") if isinstance(payload, dict) else None
    ok = (code == 0)

    # ★ 对账以「价目表」为准，不用余额相减 —— 实测两个坑：
    #   ① 充了钱余额会往上跳，差额变成负数
    #   ② 扣费是延迟入账的，跑完立刻查可能还没扣
    #   所以：应花多少 = 单价 × 成功次数（失败不计费）；余额只作参考快照。
    cost_est = round(cost, 4) if (ok and cost is not None) else 0.0
    delta = None
    billing_note = ""
    if before and after:
        delta = round(before["balance"] - after["balance"], 4)
        if abs(delta - cost_est) < 0.005:
            billing_note = "已入账"
        elif delta < 0:
            billing_note = f"期间有充值（+{abs(delta)}），余额差不能当花费"
        elif abs(delta) < 0.0001:
            billing_note = "余额未变，扣费可能延迟入账"
        else:
            billing_note = f"余额差 {delta}，与价目 {cost_est} 不一致，待核对"

    if isinstance(payload, dict) and payload.get("_transport_error"):
        print(f"✗ 请求没发出去：{payload['_transport_error']}")
        return 1

    meta = {
        "endpoint": key,
        "label": ep["label"],
        "method": method,
        "path": path,
        "params": params,
        "called_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "http_status": status,
        "code": code,
        "message": (payload.get("message") if isinstance(payload, dict) else None),
        "elapsed_ms": elapsed,
        "ok": ok,
        "cost_listed": cost,
        "cost_estimated": cost_est,
        "balance_before": before["balance"] if before else None,
        "balance_after": after["balance"] if after else None,
        "balance_delta": delta,
        "billing_note": billing_note,
        "request_id": (payload.get("requestId") if isinstance(payload, dict) else None),
    }
    jp, mp, meta = save_run(cfg, key, ep, params, payload, meta)
    append_ledger({
        "at": meta["called_at"], "endpoint": key, "ok": ok,
        "cost": cost_est, "balance_after": meta["balance_after"],
        "code": code,
    })

    print("-" * 66)
    if ok:
        print(f"✓ code=0　成功")
    else:
        print(f"✗ code={code}　{CODES.get(code, '未知业务码')}")
        if isinstance(payload, dict) and payload.get("reason"):
            print(f"  reason: {payload.get('reason')}")
    print(f"  原始响应  {jp.relative_to(ROOT)}　{meta['bytes']} 字节")
    print(f"  调用记录  {mp.relative_to(ROOT)}")
    print(f"  本次花费  ¥{cost_est}（按价目表；失败不计费）")
    if before and after:
        print(f"  余额      {before['balance']} → {after['balance']}"
              + (f"　（{billing_note}）" if billing_note else ""))
    elif before:
        print(f"  余额      {before['balance']}（跑完没查到，不影响）")
    return 0 if ok else 1


def cmd_call(args):
    cfg = load_config()
    spec = load_spec()
    params = _parse_pairs(args.pairs)
    return _run_one(cfg, spec, args.endpoint, params, args.go)


PLAT_TO_ACTION = {
    "xhs": "xhs.search_user",
    "dy": "dy.search_user",
    "sph": "sph.search_account",
    "gzh": "gzh.search_account",
}


def cmd_accounts(args):
    """四平台统一的账号搜索。"""
    plat = (args.platform or "").strip().lower()
    if plat not in PLAT_TO_ACTION:
        print(f"平台要是 {'、'.join(PLAT_TO_ACTION)} 之一")
        return 1
    params = {"keyword": args.keyword}
    if args.page:
        params["page"] = str(args.page)
    cfg = load_config()
    spec = load_spec()
    print(f"【账号搜索 · {plat}】")
    return _run_one(cfg, spec, PLAT_TO_ACTION[plat], params, args.go)


def cmd_sync_spec(args):
    """从官方仓库拉最新 spec。只有这一步需要联网拉文件（免费）。"""
    url = ("https://raw.githubusercontent.com/justoneapi-official/"
           "justoneapi-python/main/openapi/public-api.json")
    print(f"拉取：{url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
    except Exception as e:
        print(f"✗ 拉不下来：{type(e).__name__}: {e}")
        return 1
    old = len(json.loads(SPEC_PATH.read_text(encoding="utf-8")).get("paths") or {}) if SPEC_PATH.is_file() else 0
    obj = json.loads(raw.decode("utf-8"))
    new = len(obj.get("paths") or {})
    SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_bytes(raw)
    print(f"✓ 已更新 {SPEC_PATH.relative_to(ROOT)}")
    print(f"  接口数 {old} → {new}")
    print("  提醒：加了新接口要自己在 config.json 的 endpoints 里补一行才会出现在动作表里")
    return 0


# ---------------------------------------------------------------- 入口
def main():
    ap = argparse.ArgumentParser(
        prog="collect.py",
        description="JustOneAPI 采集器 —— 一个执行器跑 371 个接口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("doctor", help="自检：token / 接口字典 / 余额 / 动作数")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("balance", help="查余额和累计消费（免费）")
    p.set_defaults(func=cmd_balance)

    p = sub.add_parser("spent", help="看本地台账：一共花了多少（免费）")
    p.set_defaults(func=cmd_spent)

    p = sub.add_parser("list", help="列出某个平台可用的接口（从 spec 读，免费）")
    p.add_argument("platform", nargs="?", help="xhs / dy / sph / gzh，不填=全部")
    p.add_argument("--all", action="store_true", help="连废弃版本一起列")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("call", help="调一个接口；默认只预演，加 --go 才真跑")
    p.add_argument("endpoint", help="动作名（如 xhs.search_user）或接口路径")
    p.add_argument("pairs", nargs="*", help="参数，写成 k=v；不带 = 的会被拒")
    p.add_argument("--go", action="store_true", help="真跑（会花钱）")
    p.set_defaults(func=cmd_call)

    p = sub.add_parser("accounts", help="四平台统一的账号搜索")
    p.add_argument("--platform", required=True, help="xhs / dy / sph / gzh")
    p.add_argument("--keyword", required=True, help="搜什么")
    p.add_argument("--page", type=int, default=0, help="第几页（默认只拿第一页）")
    p.add_argument("--go", action="store_true", help="真跑（会花钱）")
    p.set_defaults(func=cmd_accounts)

    p = sub.add_parser("sync-spec", help="从官方仓库拉最新接口字典")
    p.set_defaults(func=cmd_sync_spec)

    args = ap.parse_args()
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
