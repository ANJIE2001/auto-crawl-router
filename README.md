# 自动抓取内容路由

把散在小红书博主、灵造、得到大脑里的内容抓回来，落成统一字段，再产出表格。

一件事：**内容进来 → 存下来 → 洗干净 → 出成品。**

---

## 四层骨架

| 层 | 干什么 | 谁往里写 |
|---|---|---|
| `00_路由` | 决定这次任务走哪个来源 | `routes.json` |
| `01_采集` | 抓取脚本、调度 | 各来源适配器 |
| `02_储存` | 原始数据，只进不改 | 采集层 |
| `03_加工` | 统一字段、清洗、转表格 | `adapters/`、`run.py` |
| `04_产出` | 给人看的东西 | 加工层 |

数据流向单线：`采集 → 储存（原始） → 加工 → 产出`。不回头改写原始数据。

---

## 储存按来源分

```
02_储存/
├── 01_lingzao/
│   ├── search-notes/          # 批量搜笔记，20 credits/次
│   ├── analyze-user-profile/  # 深挖单博主，100 credits/博主
│   └── search-users/          # 搜用户
├── 02_getnote/                # 得到大脑（订阅追踪、收藏归档）
├── 03_browser/                # CDP 浏览器兜底，0 成本
└── 04_api_x/                  # 预留：第三方裸 API
```

产出分四类：`表格 / 文件 / 图片 / 视频`。

---

## 路由规则

看 `00_路由/routes.json`。一句话版本：

- 批量搜笔记、深挖博主 → **灵造**（花钱，字段全）
- 订阅更新、收藏归档 → **得到大脑**（要 Pro 会员）
- 前两个都不通 → **浏览器兜底**（慢，但不要钱）

---

## 快速开始

```bash
# 1. 装依赖
pip install openpyxl

# 2. 搜来的笔记 → 统一字段（jsonl + csv）
python 03_加工/run.py search 02_储存/01_lingzao/search-notes/xxx.json

# 3. 博主全量笔记 → Excel
python 03_加工/run.py table 02_储存/01_lingzao/analyze-user-profile/xxx.json
```

`03_加工/scripts/` 里是迁移过来的旧脚本，跑法见各自文件头的注释。新流程一律走 `run.py` + `adapters/`。

---

## 坑（别踩）

- **`02_储存` 和 `04_产出` 不入 git**。原始数据和成品体积大，`.gitignore` 已排除；换机器要手动拷。
- **灵造 credits 花得快**。search-notes 一次 20，analyze-user-profile 一个博主 100。抓之前先想清楚要什么。
- **灵造 profile JSON 里的字幕是截断的**。`text.subtitle.truncated = true`，完整字幕得走 `artifacts.subtitle_markdown` 那个 URL。
- **封面 URL 带过期签名**。抓完 profile 一小时内必须下载封面，否则 HTTP 498。
- **`.env` 不入库**。密钥只写本地，`.env.example` 是模板。

---

## 统一字段

加工层所有来源都吐同一套字段，见 `03_加工/adapters/base.py`。

要点：**统一字段之外，原始条目整条挂在 `raw` 上**。清洗出错时能对回原样。
