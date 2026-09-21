#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
设置凭证 —— key 只存在你自己的电脑里，不进项目、不进 git、不进打包。

    python 05_技能/set_key.py                    # 看当前 key 从哪读到（推荐先跑这个）
    python 05_技能/set_key.py getnote --client-id cli_xxx --api-key gk_live_xxx
    python 05_技能/set_key.py lingzao --api-key lgz_xxx
    python 05_技能/set_key.py getnote --clear    # 清掉

**为什么不像以前那样写在项目文件里**：项目是要打包发人的，key 跟着走就泄露了。
放自己电脑的环境变量里，包发出去里面一个 key 都没有。

两种存法，`--scope` 选（默认 user）：

    --scope user      存成用户环境变量（底层写在注册表 HKCU\\Environment）
                      ← 本机一贯做法，飞书凭证 FEISHU_APP_ID / FEISHU_APP_SECRET 就是这么存的
    --scope registry  存进独立注册表项 HKCU\\Software\\AutoCrawlRouter\\<源名>
                      ← 不出现在环境变量列表里（set 看不到），比较隐蔽

代码读的时候**两个地方都认**，顺序是：

    ① 进程环境变量  →  ② 注册表里的用户环境变量  →  ③ 独立注册表项  →  ④ 项目根 .env

② 存在是为了「刚设完还没重启」——Windows 的环境变量不会自动进已经开着的进程，
所以设完立刻用也不用重开。

⚠️ key 是明文存注册表的（跟飞书那套一样），**能读到这台电脑的人就能读到它**。
  这是本地单机工具的常规做法；要更强的隔离得靠独立的只读权限应用 key。
"""
from __future__ import annotations

import argparse
import ctypes
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

if os.name != "nt":
    sys.exit("这个脚本只在 Windows 上有效（要用注册表）。")

import winreg  # noqa: E402

REG_ROOT = r"Software\AutoCrawlRouter"
ENV_KEY = r"Environment"

SOURCES = {
    "getnote": {
        "label": "得到大脑",
        "fields": [
            ("client_id", "GETNOTE_CLIENT_ID", "client_id"),
            ("api_key", "GETNOTE_API_KEY", "api_key"),
            ("base_url", "GETNOTE_BASE_URL", "base_url"),
        ],
    },
    "lingzao": {
        "label": "灵造",
        "fields": [
            ("api_key", "LINGZAO_API_KEY", "api_key"),
            ("base_url", "LINGZAO_BASE_URL", "base_url"),
        ],
    },
}


def mask(v: str) -> str:
    if not v:
        return ""
    v = re.sub(r"(gk_live_)[A-Za-z0-9.]+", r"\1<hidden>", v)
    v = re.sub(r"(lgz_)[A-Za-z0-9]{6,}", r"\1<hidden>", v)
    v = re.sub(r"(cli_)[a-f0-9]{8,}", r"\1<hidden>", v)
    return v


# ---------------------------------------------------------------------------
# 注册表读写
# ---------------------------------------------------------------------------

def _broadcast_env_change() -> None:
    """告诉系统「环境变量变了」—— 不然资源管理器和其他程序要等重启才认。"""
    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x001A
    SMTO_ABORTIFHUNG = 0x0002
    try:
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
            SMTO_ABORTIFHUNG, 5000, ctypes.byref(ctypes.c_ulong()))
    except Exception:
        pass


def env_write(name: str, value: str) -> None:
    """写用户环境变量（注册表 HKCU\\Environment）。value 为空 = 删掉。"""
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, ENV_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if value:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        else:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass
    _broadcast_env_change()


def env_read(name: str) -> str:
    """只读注册表里的用户环境变量（不看当前进程的缓存）。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ENV_KEY, 0, winreg.KEY_READ) as k:
            v, _ = winreg.QueryValueEx(k, name)
            return str(v).strip()
    except FileNotFoundError:
        return ""


def app_write(section: str, field: str, value: str) -> None:
    path = rf"{REG_ROOT}\{section}"
    if value:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, field, 0, winreg.REG_SZ, value)
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, field)
        except FileNotFoundError:
            pass


def app_read(section: str, field: str) -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{REG_ROOT}\{section}", 0, winreg.KEY_READ) as k:
            v, _ = winreg.QueryValueEx(k, field)
            return str(v).strip()
    except FileNotFoundError:
        return ""


def app_clear(section: str) -> None:
    """清掉整个源段落。"""
    try:
        winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, rf"{REG_ROOT}\{section}", 0, 0)
    except FileNotFoundError:
        pass
    except OSError:
        pass


# ---------------------------------------------------------------------------
# .env（只读，用来报告「别处还有没有」）
# ---------------------------------------------------------------------------

def read_env_file():
    f = ROOT / ".env"
    if not f.is_file():
        return {}
    out = {}
    for raw in f.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        v = v.strip().strip('"').strip("'")
        if v:
            out[k.strip()] = v
    return out


def locate(src: str, env_name: str, field: str):
    """按优先级找值，返回 (值, 来源)。"""
    v = (os.environ.get(env_name) or "").strip()
    if v:
        return v, "进程环境变量"
    v = env_read(env_name)
    if v:
        return v, "用户环境变量（注册表 HKCU\\Environment）"
    v = app_read(src, field)
    if v:
        return v, f"独立注册表项 HKCU\\{REG_ROOT}\\{src}"
    v = read_env_file().get(env_name, "")
    if v:
        return v, "项目根 .env  ← 建议搬走，见下"
    return "", ""


# ---------------------------------------------------------------------------
# 动作
# ---------------------------------------------------------------------------

def cmd_show() -> int:
    print("凭证当前在哪")
    print("=" * 62)
    envf = read_env_file()
    for src, meta in SOURCES.items():
        print(f"\n{meta['label']}  ({src})")
        for field, env_name, reg_field in meta["fields"]:
            val, where = locate(src, env_name, reg_field)
            if val:
                print(f"  {field:<11} 有  {mask(val)}　← {where}")
            else:
                print(f"  {field:<11} ——  没找到")
    # 只挑真正敏感的字段 —— base_url 这种默认地址不算「真值」，别误报
    sensitive = re.compile(r"(API_KEY|CLIENT_ID|SECRET|TOKEN)")
    leaked = [k for k in envf
              if k.startswith(("GETNOTE_", "LINGZAO_")) and sensitive.search(k)]
    print()
    print("-" * 62)
    if leaked:
        print(f"⚠️ 项目根 .env 里还有 {len(leaked)} 个真值：{'、'.join(leaked)}")
        print("   打包发人前必须排掉（或干脆搬进环境变量）：")
        print("     python 05_技能/set_key.py getnote --client-id cli_xxx --api-key gk_live_xxx")
    else:
        print("项目根 .env 里没有密钥 ✓  打包时不会泄露")
    return 0


def cmd_set(args) -> int:
    meta = SOURCES[args.source]
    given = {f[0]: getattr(args, f[0].replace("-", "_"), None) for f in meta["fields"]}
    given = {k: v for k, v in given.items() if v}
    if not given:
        names = " / ".join(f"--{f[0].replace('_', '-')}" for f in meta["fields"])
        print(f"至少给一个值：{names}")
        return 1

    print(f"写入 {meta['label']}")
    print("=" * 62)
    for field, env_name, reg_field in meta["fields"]:
        if field not in given:
            continue
        val = given[field]
        if args.scope == "registry":
            app_write(args.source, reg_field, val)
            print(f"  {field:<11} {mask(val)}   →  HKCU\\{REG_ROOT}\\{args.source}\\{reg_field}")
        else:
            env_write(env_name, val)
            print(f"  {field:<11} {mask(val)}   →  用户环境变量 {env_name}")

    print()
    if args.scope == "user":
        print("已广播刷新，**不用重启**就能用（代码会直接读注册表兜底）。")
    print("验证一下：python 05_技能/prereq_check.py")
    return 0


def cmd_clear(args) -> int:
    meta = SOURCES[args.source]
    print(f"清除 {meta['label']}")
    print("=" * 62)
    for field, env_name, reg_field in meta["fields"]:
        if env_read(env_name):
            env_write(env_name, "")
            print(f"  已删用户环境变量 {env_name}")
        if app_read(args.source, reg_field):
            app_write(args.source, reg_field, "")
            print(f"  已删注册表项 {REG_ROOT}\\{args.source}\\{reg_field}")
    app_clear(args.source)
    print("\n清完了。项目根 .env 里的值不受影响 —— 那个文件要自己处理。")
    return 0


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        prog="set_key.py",
        description="把凭证存进本机（环境变量 / 注册表），项目里不留 key",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = ap.add_subparsers(dest="cmd")

    for src, meta in SOURCES.items():
        label = meta["label"]
        sp = sub.add_parser(src, help=f"设置 {label}")
        sp.add_argument("--scope", choices=("user", "registry"), default="user",
                        help="user=用户环境变量（默认）；registry=独立注册表项")
        sp.add_argument("--clear", action="store_true", help="清掉这个源已存的凭证")
        for field, env_name, reg_field in meta["fields"]:
            sp.add_argument(f"--{field.replace('_', '-')}", dest=field, default=None,
                            help=f"{field}（环境变量 {env_name}）")
        sp.set_defaults(func=lambda a, s=src: cmd_clear(a) if a.clear else cmd_set(a), source=src)

    args = ap.parse_args()
    if not getattr(args, "cmd", None):
        return cmd_show()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
