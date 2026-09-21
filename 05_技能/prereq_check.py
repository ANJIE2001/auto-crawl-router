#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
环境前置检查 —— 第一次用这套流程的人，先跑这个。

    python 05_技能/prereq_check.py

它只查「跑不跑得起来」，**不抓数据、不花钱、不改任何文件**。查三样：

    1. Python 和依赖（出表格要 openpyxl）
    2. 灵造      —— 抓小红书，**花钱**，靠一个本地 CLI
    3. 得到大脑  —— 抓抖音 / 任意网页，不花钱，靠开放平台 API Key

**缺什么就告诉你装什么、怎么装、装完落在哪个路径。** 三样齐了才谈得上抓数据。

★ **凭证只存在你自己的电脑里**（环境变量 / 注册表），项目文件夹里一个 key 都不留 ——
这样把项目打包发人，包里也没有钥匙。设凭证用：

    python 05_技能/set_key.py getnote --client-id cli_xxx --api-key gk_live_xxx

和 selfcheck.py 的分工：
    selfcheck.py  —— 项目「体检」：数据对不对、命名乱没乱、有没有密钥泄露
    prereq_check  —— 环境「上岗检查」：软件装了没、凭证配了没、配在哪
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HOME = Path.home()

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# 本机（Windows）上项目该用的解释器 —— 有 openpyxl 的那个
VENV_PY = HOME / ".workbuddy" / "binaries" / "python" / "envs" / "default" / "Scripts" / "python.exe"

LINGZAO_INSTALL = ("npx --yes skills add https://assets-tian.midao.site/skills/lingzao "
                   "--skill lingzao -g --copy --agent \"*\" -y")
LINGZAO_SITE = "https://lingzao.atian.vip"
GETNOTE_SITE = "https://openapi.biji.com"

OK, NO, HINT = "就绪", "缺失", "注意"


def head(n, title, note=""):
    print()
    print(f"[{n}] {title}" + (f"   —— {note}" if note else ""))
    print("-" * 60)


def line(label, state, detail=""):
    print(f"    {label:<14} {state:<6} {detail}".rstrip())


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def read_env(path):
    """读 KEY=VALUE 形式的 .env。文件不在就返回空 dict。"""
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


REG_ROOT = r"Software\AutoCrawlRouter"


def _reg_env(name):
    """直接读注册表里的用户环境变量（HKCU\\Environment）—— 绕开进程缓存。"""
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ) as k:
            v, _ = winreg.QueryValueEx(k, name)
            return str(v).strip()
    except Exception:
        return ""


def _reg_app(section, field):
    """读独立注册表项 HKCU\\Software\\AutoCrawlRouter\\<section>\\<field>。"""
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{REG_ROOT}\{section}",
                            0, winreg.KEY_READ) as k:
            v, _ = winreg.QueryValueEx(k, field)
            return str(v).strip()
    except Exception:
        return ""


def resolve_cred(env_name, section, field):
    """
    按优先级找凭证，和两个 collect.py 用的是同一套顺序：

        ① 进程环境变量 → ② 注册表里的用户环境变量 → ③ 独立注册表项 → ④ 项目根 .env

    ①②③ 都在**你自己的电脑里**，打包带不走；.env 排最后只作兼容。
    """
    v = (os.environ.get(env_name) or "").strip()
    if v:
        return v, f"环境变量 {env_name}"
    v = _reg_env(env_name)
    if v:
        return v, f"用户环境变量 {env_name}（注册表）"
    v = _reg_app(section, field)
    if v:
        return v, f"注册表 HKCU\\{REG_ROOT}\\{section}"
    v = (read_env(ROOT / ".env").get(env_name) or "").strip()
    if v:
        return v, "项目根 .env ⚠️ 建议搬进环境变量"
    return "", ""


def run(cmd, timeout=90, cwd=None):
    """跑个外部命令，拿 (returncode, stdout, stderr)。失败不抛异常。"""
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           cwd=str(cwd or ROOT))
        return (p.returncode,
                p.stdout.decode("utf-8", "replace"),
                p.stderr.decode("utf-8", "replace"))
    except FileNotFoundError:
        return 127, "", "找不到这个命令"
    except subprocess.TimeoutExpired:
        return 124, "", f"超时（{timeout}s）"
    except Exception as e:  # noqa: BLE001
        return 1, "", repr(e)


# ---------------------------------------------------------------------------
# 1. Python 和依赖
# ---------------------------------------------------------------------------

def check_python():
    head("1/3", "Python 和依赖")
    v = sys.version_info
    line("Python", OK if v >= (3, 8) else HINT, f"{sys.version.split()[0]}  {sys.executable}")
    if v < (3, 8):
        print("                  太旧了，装 3.8 以上。")

    missing = []
    for mod, ver_attr, why in (("openpyxl", "__version__", "出 xlsx 表格要它"),):
        try:
            m = __import__(mod)
            line(mod, OK, f"{getattr(m, ver_attr, '?')}  （{why}）")
        except ImportError:
            line(mod, NO, f"{why}")
            missing.append(mod)

    if missing:
        print()
        print("    装它的办法（三选一，看你怎么跑的）：")
        if VENV_PY.is_file():
            print(f"      · 本机推荐用这个解释器（它已经装好了）：")
            print(f"          {VENV_PY}")
            print(f"        用它跑任何脚本，例：")
            print(f'          "{VENV_PY}" 05_技能/prereq_check.py')
        print(f"      · 或者给当前解释器装上：\"{sys.executable}\" -m pip install {' '.join(missing)}")
        print(f"      · 装了还不行，多半是跑错解释器了 —— 你看到的是 {sys.executable}")
    return not missing


# ---------------------------------------------------------------------------
# 2. 灵造
# ---------------------------------------------------------------------------

def find_lingzao_skill():
    """找灵造 Skill 本体的目录（里面得有 scripts/lingzao_client.py）。"""
    cands = []
    sk = HOME / ".workbuddy" / "skills"
    if sk.is_dir():
        cands += sorted(sk.glob("@user_*/lingzao"))
        cands.append(sk / "lingzao")
    cands += [HOME / ".agents" / "skills" / "lingzao",
              HOME / ".claude" / "skills" / "lingzao"]
    for c in cands:
        if (c / "scripts" / "lingzao_client.py").is_file():
            return c
    return None


def find_lingzao_cli():
    """
    找能直接运行的 CLI 入口。

    ⚠️ 官方 setup.sh 只生成一个**没有扩展名**的 bash 脚本 `bin/lingzao`。
    Windows 上双击不了、也当不了命令 —— 必须有个 .cmd / .exe 才作数。
    所以这里只认 .cmd / .exe / .bat，不把那个 bash 文件当成果。
    """
    b = HOME / ".lingzao" / "bin"
    if not b.is_dir():
        return None
    for name in ("lingzao.cmd", "lingzao.exe", "lingzao.bat"):
        p = b / name
        if p.is_file():
            return p
    return None


def check_lingzao():
    head("2/3", "灵造", "抓小红书，按次扣积分 —— 花钱的那个")
    ready = False

    skill = find_lingzao_skill()
    if skill:
        ver = ""
        vf = skill / "VERSION"
        if vf.is_file():
            ver = vf.read_text(encoding="utf-8", errors="ignore").strip()
        if not ver:
            meta = skill / "_meta.json"
            if meta.is_file():
                try:
                    ver = json.loads(meta.read_text(encoding="utf-8")).get("version", "")
                except Exception:
                    pass
        line("Skill 本体", OK, f"{skill}  版本 {ver or '未知'}")
    else:
        line("Skill 本体", NO, "没装")

    cli = find_lingzao_cli()
    if cli:
        line("CLI 入口", OK, str(cli))
    else:
        line("CLI 入口", NO, "没有可运行的入口")

    # 凭证
    cred_file = HOME / ".lingzao" / "config.json"
    key = ""
    if cred_file.is_file():
        try:
            key = str(json.loads(cred_file.read_text(encoding="utf-8")).get("api_key") or "")
        except Exception:
            key = ""
    if key:
        line("API Key", OK, f"{cred_file}（{key[:4]}…，共 {len(key)} 位）")
    else:
        line("API Key", NO, f"{cred_file} 里没有 api_key")

    # 连通（doctor 不花钱）
    if skill and key:
        client = skill / "scripts" / "lingzao_client.py"
        py = str(VENV_PY) if VENV_PY.is_file() else sys.executable
        rc, sout, serr = run([py, str(client), "doctor"], timeout=120)
        blob = sout + serr
        if rc == 0 and "正常" in blob:
            user = re.search(r"用户:\s*(\S+)", blob)
            line("连通性", OK, f"登录账号 {user.group(1) if user else '（doctor 没回报账号）'}")
            ready = True
        else:
            line("连通性", NO, (blob.strip().splitlines() or ["doctor 没跑通"])[-1][:70])

    if not ready:
        print()
        print("    灵造怎么装 —— 照着做：")
        print()
        print("      第 1 步 · 装 Skill 本体（免费）")
        print(f"        {LINGZAO_INSTALL}")
        print()
        print("      ⚠️ 它认不出 WorkBuddy 的 skills/@user_xxx 结构，会装到")
        print(f"        {HOME / '.agents' / 'skills' / 'lingzao'}")
        print("        装完把它整个复制到 WorkBuddy 的位置：")
        print(f"        {HOME / '.workbuddy' / 'skills' / '@user_71a0bff3' / 'lingzao'}")
        print("        （旧版独有的 _meta.json / index.md / skill-card.md 留着，别删）")
        print()
        print("      第 2 步 · 补 Windows 启动器")
        print(f"        官方只生成 bash 版的 {HOME / '.lingzao' / 'bin' / 'lingzao'}，Windows 用不了。")
        print(f"        在同一目录新建 lingzao.cmd，写一行：")
        print(f'          "{VENV_PY}" "{HOME / ".workbuddy" / "skills" / "@user_71a0bff3" / "lingzao" / "scripts" / "lingzao_client.py"}" %*')
        print()
        print("      第 3 步 · 拿 API Key（做选题/标题/封面可以先不配，查公开内容才要）")
        print(f"        打开 {LINGZAO_SITE} → 按教程开通积分 → 复制 API Key")
        print()
        print("      第 4 步 · 存凭证（二选一）")
        print(f'        · 给 CLI 自己用：bash "<skill目录>/scripts/setup.sh" --api-key "lgz_xxx" '
              f'--base-url "{LINGZAO_SITE}"')
        print("        · 或者只给本项目用（存你自己电脑，不影响 CLI）：")
        print('          python 05_技能/set_key.py lingzao --api-key "lgz_xxx"')
        print()
        print(f"      装完认这两个地方：")
        print(f"        CLI   {HOME / '.lingzao' / 'bin' / 'lingzao.cmd'}")
        print(f"        凭证  {HOME / '.lingzao' / 'config.json'}")

    return ready


# ---------------------------------------------------------------------------
# 3. 得到大脑
# ---------------------------------------------------------------------------

def check_getnote():
    head("3/3", "得到大脑", "抓抖音 / 任意网页，会员制 —— 不花额外钱的那个")

    cid, src_cid = resolve_cred("GETNOTE_CLIENT_ID", "getnote", "client_id")
    key, src_key = resolve_cred("GETNOTE_API_KEY", "getnote", "api_key")
    base, _ = resolve_cred("GETNOTE_BASE_URL", "getnote", "base_url")
    base = (base or "https://openapi.biji.com/open/api/v1").rstrip("/")

    line("Client ID", OK if cid else NO, f"{cid[:8]}…　← {src_cid}" if cid else "没找到")
    line("API Key", OK if key else NO,
         f"{key[:12]}…（{len(key)} 位）　← {src_key}" if key else "没找到")
    line("接口地址", OK, base)

    if not (cid and key):
        print()
        print("    得到大脑怎么配 —— 两步：")
        print()
        print("      第 1 步 · 拿凭证")
        print(f"        打开 {GETNOTE_SITE} → 创建应用 → 生成 API Key")
        print("        会同时给你 Client ID（cli_ 开头）和 API Key（gk_live_ 开头）")
        print("        权限只勾 topic.read + topic.blogger.read —— 带 note. 前缀的一律别勾")
        print("        （那是私人笔记，项目不碰）")
        print()
        print("      第 2 步 · 存进你自己的电脑（项目里不留 key，打包才带不走）")
        print("        python 05_技能/set_key.py getnote \\")
        print("            --client-id cli_xxxx --api-key gk_live_xxxx.xxxx")
        print()
        print("        默认存成用户环境变量（底层写在注册表 HKCU\\Environment）。")
        print("        想藏得更深？加 --scope registry，存进")
        print(f"        HKCU\\{REG_ROOT}\\getnote —— 不出现在环境变量列表里。")
        return False

    # 连通（list 接口不花钱）
    url = f"{base}/resource/knowledge/list"
    req = urllib.request.Request(url, headers={
        "Authorization": key,
        "X-Client-ID": cid,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        d = data.get("data") or {}
        kbs = d.get("topics") or d.get("list") or d.get("knowledge") or []
        line("连通性", OK, f"看到 {len(kbs)} 个知识库")
        for k in kbs[:8]:
            if isinstance(k, dict):
                tid = k.get("topic_id") or k.get("id") or ""
                print(f"                   {str(k.get('name') or k.get('title') or '?'):<24} topic_id = {tid}")
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:150]
        line("连通性", NO, f"HTTP {e.code}  {body}")
        if e.code in (401, 403):
            print("                  多半是 key 不对或权限没勾 —— 回开放平台核对")
        return False
    except Exception as e:  # noqa: BLE001
        line("连通性", NO, f"连不上（{type(e).__name__}: {e}）")
        print("                  网络问题，或 base_url 写错了")
        return False


# ---------------------------------------------------------------------------

def main() -> int:
    print("环境前置检查")
    print("=" * 60)
    print("第一次用这套流程，先跑这个。它只查环境，不抓数据、不花钱。")

    py_ok = check_python()
    lz_ok = check_lingzao()
    gn_ok = check_getnote()

    print()
    print("=" * 60)
    print("结论")
    print("-" * 60)
    for label, ok, todo in (
        ("Python 依赖", py_ok, "装 openpyxl（见上面 [1/3]）"),
        ("灵造", lz_ok, "装 Skill 本体 + 补 lingzao.cmd（见上面 [2/3]）"),
        ("得到大脑", gn_ok, "建 .env + 填两个凭证（见上面 [3/3]）"),
    ):
        print(f"    {label:<12} {'可以用' if ok else '还不能用 —— ' + todo}")

    print()
    if py_ok and lz_ok and gn_ok:
        print("三样齐了，可以开始抓数据。")
        print()
        print("  凭证都在你自己电脑里（环境变量 / 注册表），项目文件夹里没有 key")
        print("  —— 打包发人不会泄露。要看存在哪：python 05_技能/set_key.py")
        print()
        print("  抓小红书（花钱，先不加 --go 只预演）：")
        print('    python 01_采集/01_lingzao/collect.py search --keyword "AI写作"')
        print()
        print("  抓抖音 / 网页（不花钱，直接跑）：")
        print("    python 01_采集/02_getnote/collect.py bloggers --topic <知识库ID>")
        return 0

    print("有缺的，按上面每一节的步骤装。装完再跑一次这个脚本复查。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
