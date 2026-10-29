# -*- coding: utf-8 -*-
"""把本地逐字稿回填到飞书「笔记」表。

    python 03_加工/回填/fill_feishu.py                      # 预演：只报告，一条都不写
    python 03_加工/回填/fill_feishu.py --go                 # 真写
    python 03_加工/回填/fill_feishu.py <jsonl或目录> --go    # 指定数据源

数据从哪来：默认扫 `04_产出/表格/*.jsonl`（统一 30 列，含 note_id 和 subtitle_text）。

★ 三条铁律：

1. **只按笔记ID匹配**，绝不按标题 —— 同一个博主会有同名笔记，按标题匹配必然串行。
2. **只更新、不新建**。表里没有的笔记ID，只报告，不追加记录（否则你的表会被塞进
   一堆本地有、你不想展示的东西）。
3. **本地没稿时默认不碰单元格**。你手填过的内容不会被一个空值冲掉；
   真要清空得显式 `--clear-empty`。

⚠️ 这是**写操作**。默认预演，加 `--go` 才真写。写之前会先把要写的内容快照到
   `_fill_tmp/` 留底。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TMP = ROOT / "_fill_tmp"
DEFAULT_SOURCE = ROOT / "04_产出" / "博主"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def die(msg):
    print(f"✗ {msg}")
    return 1


def find_cli():
    for name in ("lark-cli.cmd", "lark-cli.exe", "lark-cli"):
        p = shutil.which(name)
        if p:
            return p
    return None


def load_config():
    path = HERE / "config.json"
    if not path.is_file():
        raise SystemExit(f"缺配置文件：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 本地侧

def iter_inputs(paths):
    """把文件 / 目录展开成待读文件列表。目录里认 `_索引.xlsx` 和 `*.jsonl`。"""
    out = []
    for raw in paths:
        p = Path(raw)
        if not p.is_absolute():
            p = (ROOT / p).resolve()
        if p.is_dir():
            out += sorted(list(p.rglob("_索引.xlsx")) + list(p.rglob("*.jsonl")))
        elif p.is_file():
            out.append(p)
        else:
            print(f"  ! 跳过不存在的路径：{raw}")
    return out


def read_xlsx(path):
    """读 `_索引.xlsx`。表头不固定在某一行的（前面有标题行、空行），
    所以**找第一个含「笔记ID」的行**当表头，别硬编码行号。"""
    try:
        from openpyxl import load_workbook
    except ImportError:
        print("  ! 没装 openpyxl，跳过 xlsx。用 05_技能 里那个 python 跑。")
        return None

    ws = load_workbook(path, read_only=True, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))

    hdr_i = None
    for i, r in enumerate(rows[:10]):
        cells = [str(c).strip() if c is not None else "" for c in r]
        if "笔记ID" in cells:
            hdr_i = i
            break
    if hdr_i is None:
        return None

    h = [str(c).strip() if c is not None else "" for c in rows[hdr_i]]
    if "逐字稿" not in h:
        return None
    i_id, i_t = h.index("笔记ID"), h.index("逐字稿")
    i_s = h.index("数据来源") if "数据来源" in h else -1

    out = []
    for r in rows[hdr_i + 1:]:
        nid = str(r[i_id] or "").strip() if i_id < len(r) else ""
        if not nid:
            continue
        out.append({
            "note_id": nid,
            "subtitle_text": str(r[i_t] or "").strip() if i_t < len(r) else "",
            "source": str(r[i_s] or "").strip() if 0 <= i_s < len(r) else "",
        })
    return out


def read_jsonl(path):
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        out.append({
            "note_id": str(row.get("note_id") or "").strip(),
            "subtitle_text": (row.get("subtitle_text") or "").strip(),
            "source": (row.get("source") or "").strip(),
        })
    return out


def load_local(files):
    """笔记ID → {text, source}。同一 ID 出现多次时，留最长的稿（空的让位给有字的）。"""
    seen, conflicts, skipped = {}, 0, []
    for f in files:
        rows = read_xlsx(f) if f.suffix.lower() == ".xlsx" else read_jsonl(f)
        if rows is None:
            skipped.append(f.name)
            continue
        for row in rows:
            nid = row["note_id"]
            if not nid:
                continue
            text = row["subtitle_text"]
            old = seen.get(nid)
            if old is None:
                seen[nid] = {"text": text, "source": row["source"], "file": f.name}
            else:
                conflicts += 1
                if len(text) > len(old["text"]):
                    seen[nid] = {"text": text, "source": row["source"], "file": f.name}
    return seen, conflicts, skipped


# ---------------------------------------------------------------- 飞书侧

def lark(exe, args, timeout=600):
    proc = subprocess.run([exe] + args, capture_output=True,
                          timeout=timeout, cwd=str(ROOT))
    return (proc.returncode,
            proc.stdout.decode("utf-8", "replace"),
            proc.stderr.decode("utf-8", "replace"))


def fetch_records(exe, cfg):
    """拉飞书表：笔记ID → record_id。只取两列，别拉整表。"""
    TMP.mkdir(parents=True, exist_ok=True)
    out_rel = "_fill_tmp/feishu_rows.ndjson"
    out_abs = ROOT / out_rel
    # lark-cli 会把 ndjson 和同名 manifest 一起写；上一次的残留会让它直接报错
    for p in (out_abs, ROOT / "_fill_tmp/feishu_rows.manifest.json"):
        if p.exists():
            p.unlink()

    rc, stdout, stderr = lark(exe, [
        "base", "+record-list",
        "--base-token", cfg["base_token"],
        "--table-id", cfg["table_id"],
        "--field-id", cfg["fields"]["note_id"],
        "--limit", "2000",
        "--format", "ndjson",
        "--output", out_rel,
        "--overwrite",
        "--as", "user",
    ])
    if rc != 0:
        print(stderr.strip()[:800])
        raise SystemExit("拉飞书记录失败")

    rows = []
    if out_abs.is_file():
        for line in out_abs.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass

    mapping, dup = {}, 0
    key = cfg["fields"]["note_id"]
    for r in rows:
        nid = str(r.get(key) or "").strip()
        rid = r.get("record_id") or ""
        if not nid or not rid:
            continue
        if nid in mapping:
            dup += 1
            continue
        mapping[nid] = rid
    return mapping, len(rows), dup


# ---------------------------------------------------------------- 计划与写入

def build_plan(local, remote, cfg, clear_empty=False):
    f = cfg["fields"]
    st = cfg["status"]
    smap = cfg.get("source_map") or {}

    plan, missing, empty_skipped = [], [], 0

    for nid, item in local.items():
        rid = remote.get(nid)
        if not rid:
            missing.append(nid)
            continue

        text = item["text"]
        if text:
            plan.append((rid, nid, {
                f["transcript"]: text,
                f["source"]: [smap.get(item["source"], item["source"] or "未知")],
                f["status"]: [st["has"]],
            }))
        elif clear_empty:
            plan.append((rid, nid, {
                f["transcript"]: None,
                f["status"]: [st["none"]],
            }))
        else:
            empty_skipped += 1

    return plan, missing, empty_skipped


def write_batches(exe, cfg, plan):
    size = int(cfg.get("batch_size") or 200)
    total = 0
    for i in range(0, len(plan), size):
        chunk = plan[i:i + size]
        payload = {"update_records": {rid: cols for rid, _nid, cols in chunk}}

        rel = f"_fill_tmp/payload_{i // size + 1}.json"
        (ROOT / rel).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        print(f"  第 {i // size + 1} 批：{len(chunk)} 条 …… ", end="", flush=True)
        rc, stdout, stderr = lark(exe, [
            "base", "+record-batch-update",
            "--base-token", cfg["base_token"],
            "--table-id", cfg["table_id"],
            "--json", "@" + rel,
            "--as", "user",
        ])
        if rc != 0:
            print("失败")
            print((stderr or stdout).strip()[:600])
            return total
        print("ok")
        total += len(chunk)
    return total


# ---------------------------------------------------------------- 入口

def main():
    ap = argparse.ArgumentParser(
        description="把本地逐字稿回填到飞书「笔记」表（默认只预演）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例子：\n"
            "  python 03_加工/回填/fill_feishu.py            # 预演\n"
            "  python 03_加工/回填/fill_feishu.py --go       # 真写\n"
        ),
    )
    ap.add_argument("inputs", nargs="*",
                    help=f"_索引.xlsx / jsonl / 目录，默认扫 {DEFAULT_SOURCE.relative_to(ROOT)}")
    ap.add_argument("--go", action="store_true", help="真的写入飞书（默认只预演）")
    ap.add_argument("--clear-empty", action="store_true",
                    help="本地没稿时也把单元格清空（默认不碰，免得冲掉你手填的）")
    args = ap.parse_args()

    exe = find_cli()
    if not exe:
        return die("没找到 lark-cli。装了飞书连接器才有；没有它就只能走 RPA，不稳。")

    cfg = load_config()

    # 1. 本地
    files = iter_inputs(args.inputs or [str(DEFAULT_SOURCE)])
    if not files:
        return die("没找到 _索引.xlsx 或 *.jsonl。先跑一次加工，或者显式指定路径。")
    print(f"本地数据  {len(files)} 个文件")
    local, conflicts, skipped = load_local(files)
    if skipped:
        print(f"           ⚠ {len(skipped)} 个文件没有「笔记ID / 逐字稿」列，跳过："
              + "、".join(skipped[:3]))
    has_text = sum(1 for v in local.values() if v["text"])
    print(f"           {len(local)} 条唯一笔记，其中 {has_text} 条有逐字稿")
    if conflicts:
        print(f"           （{conflicts} 条重复出现，已按「留最长的稿」合并）")

    # 2. 飞书
    print("拉飞书表 ……", end=" ", flush=True)
    remote, nrows, dup = fetch_records(exe, cfg)
    print(f"{nrows} 行，{len(remote)} 个笔记ID")
    if dup:
        print(f"           ⚠ 表里有 {dup} 个重复笔记ID，只认第一条")

    # 3. 计划
    plan, missing, empty_skipped = build_plan(local, remote, cfg, args.clear_empty)

    print("-" * 56)
    print(f"  能匹配上     {len(plan)} 条")
    print(f"  本地有、表里没有  {len(missing)} 条（不会新建记录）")
    if missing:
        for nid in missing[:5]:
            print(f"      - {nid}")
        if len(missing) > 5:
            print(f"      …… 还有 {len(missing) - 5} 条")
    if empty_skipped:
        print(f"  本地无稿跳过 {empty_skipped} 条（要清空加 --clear-empty）")
    print("-" * 56)

    if not plan:
        print("没有可写的。")
        return 0

    if not args.go:
        print("这是预演，飞书表一个字都没动。确认没问题，加 --go 再跑一次。")
        return 0

    # 4. 快照留底 —— 写坏了能照着还原
    TMP.mkdir(parents=True, exist_ok=True)
    snap = TMP / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    snap.write_text(json.dumps(
        [{"record_id": rid, "note_id": nid, "fields": cols} for rid, nid, cols in plan],
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"快照留底  {snap.relative_to(ROOT)}")

    # 5. 写
    print("写入飞书 ……")
    n = write_batches(exe, cfg, plan)
    print(f"\n完成 {n} / {len(plan)} 条")
    if n < len(plan):
        print("没写完。已经写进去的不受影响，修完问题直接重跑就会跳过已写的（幂等）。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
