# -*- coding: utf-8 -*-
"""从飞书「笔记」表读链接 → 走得到大脑抓口播 → 回填同一行。

    python 03_加工/回填/pull_getnote.py              # 预演：看清楚要处理哪些，不抓不写
    python 03_加工/回填/pull_getnote.py --go         # 真跑（每条约 15-20 秒）
    python 03_加工/回填/pull_getnote.py --go --limit 3   # 先跑 3 条看质量

★ 要哪个字段（用错一次才分清，别再搞错）

    一条链接在得到大脑里有**两个正文**：

        web_page.content   = 链接原文  ← ★ 用户要的「逐字稿」就是它
        content            = AI 解读版（重写、带表格）← 不要这个

    原文的结构（视频笔记）长这样：

        博主写的文案（书面语）
        #话题标签
        ![](图片)
        口播转写  ← "消掉""销掉""风钱"这种同音错字

    得到大脑已经把视频口播拼进原文里了，所以**整段都要**，
    只去掉 `![](图片)` 这种 markdown 标记（渲染用的，回填没意义）。

    ⛔ 别自作聪明只取「看起来像口播」的那一段 —— 那样会把博主写的文案扔掉。

★ 三条铁律

1. **标题必须传**。不传 title，得到大脑会用 AI 重写标题（原帖「恐惧很深的人…」
   → 「深度认知：恐惧深厚个体的人生成长路径解析」），回来就对不上了。
2. **状态列就是进度文件**。已写「有稿」的下次直接跳过，中断了重跑不会重抓。
3. **每抓完一条立刻写回**，不攒到最后。一条 20 秒，攒着中断就全丢。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TMP = ROOT / "_fill_tmp"
STORE = ROOT / "02_储存" / "02_getnote" / "link"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AutoCrawlRouter/1.0"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ---------------------------------------------------------------- 凭证

def _reg_get(name):
    """从 HKCU\\Environment 读用户环境变量 —— 刚设完没重启也能用。"""
    try:
        import winreg
    except ImportError:
        return ""
    for root in (winreg.HKEY_CURRENT_USER,):
        try:
            with winreg.OpenKey(root, "Environment") as k:
                v, _ = winreg.QueryValueEx(k, name)
                return str(v)
        except OSError:
            pass
    return ""


def resolve(name, field):
    v = (os.environ.get(name) or "").strip()
    if v:
        return v
    # config.local.json 兜底（那个文件不进 git）
    local = HERE.parent / "01_采集" / "02_getnote" / "config.local.json"
    if local.is_file():
        try:
            o = (json.loads(local.read_text(encoding="utf-8")).get("openapi") or {})
            v = str(o.get(field) or "").strip()
            if v:
                return v
        except Exception:
            pass
    return _reg_get(name)


def load_cfg():
    p = HERE / "config.json"
    cfg = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    cfg.setdefault("fields", {})
    for k, d in (("note_id", "笔记ID"), ("transcript", "逐字稿"),
                 ("source", "逐字稿来源"), ("status", "逐字稿状态"),
                 ("link", "笔记链接"), ("title", "笔记标题"),
                 ("note_type", "笔记类型")):
        cfg["fields"].setdefault(k, d)
    cfg.setdefault("status", {"has": "有稿", "none": "无稿", "fail": "失败"})
    return cfg


# ---------------------------------------------------------------- 得到大脑

class Getnote:
    def __init__(self):
        self.base = (resolve("GETNOTE_BASE_URL", "base_url")
                     or "https://openapi.biji.com/open/api/v1").rstrip("/")
        self.cid = resolve("GETNOTE_CLIENT_ID", "client_id")
        self.key = resolve("GETNOTE_API_KEY", "api_key")
        if not self.cid or not self.key:
            raise SystemExit("缺得到大脑凭证。跑 `python 05_技能/set_key.py` 看看现在从哪读的。")

    def call(self, method, path, body=None, timeout=90):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "Authorization": self.key,          # ⚠️ 不带 Bearer
            "X-Client-ID": self.cid,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": UA,
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            return {"_http": e.code, "_body": e.read().decode("utf-8", "replace")[:400]}
        except Exception as e:
            return {"_error": str(e)}

    def save_link(self, url, title):
        body = {"note_type": "link", "link_url": url}
        if title:
            body["title"] = title          # ★ 不传就会被 AI 改写
        return self.call("POST", "/resource/note/save", body)

    def wait_task(self, task_id, budget=180, gap=3.0):
        """普通链接是异步的，返回 task_id，要轮询到 success。"""
        t0 = time.time()
        while time.time() - t0 < budget:
            time.sleep(gap)
            r = self.call("POST", "/resource/note/task/progress", {"task_id": task_id})
            d = r.get("data") or {}
            if d.get("status") in ("success", "failed", "error"):
                return d
        return {"status": "timeout"}

    def detail(self, note_id):
        r = self.call("GET", f"/resource/note/detail?id={note_id}")
        return (r.get("data") or {}).get("note") or {}


def extract_original(text):
    """链接原文 = `web_page.content` 去掉图片 markdown 后的全文。

    ★ 这就是用户要的「逐字稿」—— 不是 AI 解读那版（`content`），是原帖原文。
      得到大脑已经把视频口播拼进这段里了（口语段满是"消掉""销掉"这种同音错字），
      所以**整段都留着，不要只取某一部分**。
    """
    import re
    t = text or ""
    t = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", t)     # 图片 markdown 对回填没用
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


# ---------------------------------------------------------------- 飞书

def lark_exe():
    for name in ("lark-cli.cmd", "lark-cli.exe", "lark-cli"):
        p = shutil.which(name)
        if p:
            return p
    return None


def lark(exe, args, timeout=600):
    p = subprocess.run([exe] + args, capture_output=True, timeout=timeout, cwd=str(ROOT))
    return (p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"))


def fetch_rows(exe, cfg):
    TMP.mkdir(parents=True, exist_ok=True)
    rel = "_fill_tmp/pull_rows.ndjson"
    for p in (ROOT / rel, ROOT / "_fill_tmp/pull_rows.manifest.json"):
        if p.exists():
            p.unlink()

    args = ["base", "+record-list",
            "--base-token", cfg["base_token"], "--table-id", cfg["table_id"],
            "--limit", "2000", "--format", "ndjson", "--output", rel,
            "--overwrite", "--as", "user"]
    for k in ("note_id", "link", "title", "note_type", "transcript", "status"):
        args += ["--field-id", cfg["fields"][k]]

    rc, out, err = lark(exe, args)
    if rc != 0:
        raise SystemExit(f"拉飞书记录失败\n{(err or out)[:600]}")

    rows = []
    f = ROOT / rel
    if f.is_file():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


def write_back(exe, cfg, record_id, transcript, status_key):
    f = cfg["fields"]
    cols = {
        f["transcript"]: transcript,
        f["source"]: ["得到大脑"],
        f["status"]: [cfg["status"][status_key]],
    }
    rel = "_fill_tmp/writeback.json"
    (ROOT / rel).write_text(
        json.dumps({"update_records": {record_id: cols}}, ensure_ascii=False),
        encoding="utf-8")
    rc, out, err = lark(exe, ["base", "+record-batch-update",
                              "--base-token", cfg["base_token"],
                              "--table-id", cfg["table_id"],
                              "--json", "@" + rel, "--as", "user"])
    return rc == 0, (err or out)[:300]


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(
        description="飞书表读链接 → 得到大脑抓口播 → 回填（默认只预演）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例子：\n  python 03_加工/回填/pull_getnote.py --limit 3 --go\n",
    )
    ap.add_argument("--go", action="store_true", help="真跑（默认只预演）")
    ap.add_argument("--limit", type=int, default=0, help="最多处理几条，默认全部")
    ap.add_argument("--redo", action="store_true",
                    help="连已标「有稿」的也重抓（默认跳过）")
    args = ap.parse_args()

    exe = lark_exe()
    if not exe:
        return print("✗ 没找到 lark-cli") or 1

    cfg = load_cfg()
    f = cfg["fields"]

    print("拉飞书表 ……", end=" ", flush=True)
    rows = fetch_rows(exe, cfg)
    print(f"{len(rows)} 行")

    todo = []
    for r in rows:
        nid = str(r.get(f["note_id"]) or "").strip()
        url = str(r.get(f["link"]) or "").strip()
        status = r.get(f["status"]) or []
        status = status[0] if isinstance(status, list) and status else ""
        if not nid or not url:
            continue
        if status == cfg["status"]["has"] and not args.redo:
            continue
        todo.append({
            "record_id": r.get("record_id"),
            "note_id": nid,
            "url": url,
            "title": str(r.get(f["title"]) or "").strip(),
            "type": (r.get(f["note_type"]) or [""])[0] if isinstance(r.get(f["note_type"]), list) else "",
        })

    if args.limit:
        todo = todo[:args.limit]

    print("-" * 56)
    print(f"  待处理   {len(todo)} 条（已标「有稿」的自动跳过）")
    print(f"  花费     0 元（得到大脑会员制，只占次数）")
    print(f"  预计     {len(todo) * 18 // 60} 分钟（约 18 秒/条）")
    print("-" * 56)
    for t in todo[:8]:
        print(f"  {t['type'] or '?'}  {t['title'][:32] or '(无标题)'}")
    if len(todo) > 8:
        print(f"  …… 还有 {len(todo) - 8} 条")

    if not todo:
        print("没有要处理的。")
        return 0
    if not args.go:
        print("\n这是预演，一条都没抓、没写。确认无误加 --go 再跑。")
        return 0

    gn = Getnote()
    if not STORE.is_dir():
        STORE.mkdir(parents=True, exist_ok=True)

    done = no_speech = failed = 0
    t_start = time.time()

    for i, t in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}] {t['title'][:36] or t['note_id']}")
        t0 = time.time()

        res = gn.save_link(t["url"], t["title"])
        d = res.get("data") or {}
        note_id = d.get("note_id")
        task_id = d.get("task_id") or ((d.get("tasks") or [{}])[0].get("task_id"))

        if not note_id and task_id:
            pd = gn.wait_task(task_id)
            note_id = pd.get("note_id")
            if not note_id:
                print(f"  抓取失败（{pd.get('status')}）")
                failed += 1
                write_back(exe, cfg, t["record_id"], None, "fail")
                continue

        note = gn.detail(note_id) if note_id else {}
        if not note:
            print("  详情为空")
            failed += 1
            write_back(exe, cfg, t["record_id"], None, "fail")
            continue

        # 原始 JSON 留底（回溯用，不占地方）
        (STORE / f"{time.strftime('%Y-%m-%d')}_note_{note_id}.json").write_text(
            json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")

        body = (note.get("web_page") or {}).get("content") or ""
        original = extract_original(body)

        if len(original) >= 20:
            ok, err = write_back(exe, cfg, t["record_id"], original, "has")
            print(f"  原文 {len(original)} 字  回填 {'ok' if ok else '失败 ' + err}  ({int(time.time()-t0)}s)")
            done += 1
        else:
            ok, err = write_back(exe, cfg, t["record_id"], None, "none")
            why = "整篇只有图片，原帖没有文字正文" if len(body) > 200 else "页面没抓到内容"
            print(f"  {why}  标记 无稿 {'ok' if ok else '失败'}  ({int(time.time()-t0)}s)")
            no_speech += 1

    print("\n" + "=" * 56)
    print(f"有原文 {done} 条 ｜ 无原文 {no_speech} 条 ｜ 失败 {failed} 条")
    print(f"总耗时 {int(time.time() - t_start)} 秒")
    print("中断了直接重跑 —— 已标「有稿」的会跳过，不会重复抓。")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
