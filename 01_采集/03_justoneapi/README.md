# 03_justoneapi · 第三个源

> Just One API（`api.justoneapi.com`）：一个 token 打通十几个平台的结构化数据接口。
> 这个源**只做四件事**：小红书、抖音、视频号、公众号的**账号搜索 + 内容元数据**。
> 逐字稿这四家都不给（只有 B站/YouTube 有字幕接口），要稿得另外下载视频再转写。

---

## 这个源跟另外两个源不一样

| | 灵造 / 得到大脑 | 这个源 |
|---|---|---|
| 接口数量 | 2~5 个动作写死 | **371 个接口**，用一份 OpenAPI 字典驱动 |
| 加接口 | 改代码 | **改 `config.json` 一行** |
| 给的东西 | 正文 / 逐字稿 | 结构化数据（账号、内容、指标） |
| 产出形态 | 一条内容一个文件夹 | **主要是表** |

所以骨架是「**字典 + 一个执行器 + 一张动作表**」：

```
spec/public-api.json   接口字典（371 个接口的参数、必填、类型、说明）
        ↓ 读
collect.py             一个通用执行器（call 任意接口）
        ↑ 查
config.json            动作表：只记「调哪个接口」，加动作不改代码
```

---

## 先配凭证

```bash
python 05_技能/set_key.py justoneapi --api-key <你的token>
python 05_技能/set_key.py            # 不加参数 = 看现在从哪读到的
```

token **存你本机注册表**（`HKCU\Environment` 的 `JUSTONEAPI_TOKEN`），项目里一个字都不留。

---

## 怎么用

```bash
# 自检（免费）：token / 字典 / 余额 / 动作数
python 01_采集/03_justoneapi/collect.py doctor

# 查余额和累计消费（免费）
python 01_采集/03_justoneapi/collect.py balance

# 看本地台账：一共花了多少（免费）
python 01_采集/03_justoneapi/collect.py spent

# 列出某个平台可用的接口（免费，从字典读）
python 01_采集/03_justoneapi/collect.py list xhs

# 预演（不花钱）
python 01_采集/03_justoneapi/collect.py call xhs.search_user keyword=养生

# 真跑（花钱）
python 01_采集/03_justoneapi/collect.py call xhs.search_user keyword=养生 --go

# 四平台统一的账号搜索
python 01_采集/03_justoneapi/collect.py accounts --platform xhs --keyword 养生 --go

# 拉最新接口字典（免费，官方仓库更新了就同步一次）
python 01_采集/03_justoneapi/collect.py sync-spec
```

平台代号：`xhs` 小红书 · `dy` 抖音 · `sph` 视频号 · `gzh` 公众号

---

## 花费

单价来自 dashboard 导出（2026-10-29），**只收 `code=0` 的成功请求**。
失败（301/302/303/400/601/602 等）**一分不收**。

| 平台 | 账号搜索一次 | 一次给几条 | 单条成本 | 备注 |
|---|---|---|---|---|
| 抖音 | **¥0.10** | 20 | ¥0.005 | 最便宜 |
| 小红书 | ¥0.15 | 20 | ¥0.008 | 最干净 |
| 公众号 | ¥0.40 | **1** | ¥0.40 | **性价比最差** |
| 视频号 | ¥1.50 | 20 | ¥0.075 | 最贵，且 v3 不通 |

**全量拉一个博主（按 100 条内容估）**：

| 平台 | 算法 | 合计 |
|---|---|---|
| 公众号 | 历史文章列表 ¥0.20 × 20 次 + 正文抓网页（免费） | **¥4.00** |
| 抖音 | 列表 5 次 + 详情 100 次，每次 ¥0.10 | **¥10.50** |
| 小红书 | 列表 5 次 + 详情 100 次，每次 ¥0.15 | **¥15.75** |
| 视频号 | 账号视频 ¥0.50 + 基本信息 ¥0.30×100 + 下载地址 ¥0.30×100 | **¥60+** |

---

## 四平台实测记录（2026-10-29，都是真调用）

### 小红书 · 账号搜索 `xhs.search_user`（GET，param 在 query）
20 条，13 个字段：`id` / `name` / `red_id` / `desc` / `image` / `link` / `sub_title`
- **粉丝数藏在 `sub_title` 文本里**，形如 `"粉丝 30.4万"` —— 要正则抠，没有独立数字字段
- `desc` 是「小红书号：xxx」，不是简介
- 账号 ID 用 `id`（24 位），小红书号是 `red_id`

### 抖音 · 账号搜索 `dy.search_user`（GET，param 在 query）
20 条，但结构是**卡片套 JSON 字符串**：
```
data.business_data[].data.raw_data   ← 这是个 2900 字的 JSON 字符串，要二次 json.loads
    → .user_info  ← 解析后 72 个字段
```
- 有用的：`nickname` / `unique_id`（抖音号）/ `uid` / `sec_uid` / `follower_count`（**是数字**）
- `sec_uid` 是调「博主视频列表」的必填参数
- **一定要两层解析**，第一层拿不到任何账号信息

### 公众号 · 账号搜索 `gzh.search_account`（POST，但 param 在 query）
- 只回 **1 条**（关键词匹配最准的那个），字段很实在：
  `name` / `biz` / `ghid` / `wxid` / **`fans`（粉丝数）** / **`avg_top_read`（平均阅读）** / `week_articles` / `lastest_publish`
- `ghid`（`gh_` 开头）是调「历史文章列表」的必填参数

### 视频号 · 账号搜索 `sph.search_account`（POST，param 在 **form body**）
20 条，卡片嵌套：
```
data.data[].items[]   ← 真实条目在这层
```
- `title` / `desc` / `thumbUrl` / `docID` / `authInfo` / `jumpInfo.userName`（视频号 ID）
- ⚠️ **标题里带 HTML 标签**：`糖姐爱<em class="highlight">养生</em>` —— 必须洗掉
- `totalCount` 是总结果数（实测 400）
- 分页靠 `offset` + `cookies`（854 字符的不透明串）+ `continueFlag`

---

## 踩过的坑（都是实测踩出来的，别重犯）

1. **token 的位置不是固定的**：GET 放 URL 参数，POST 看有没有 form body —— 有就放 form，没有就放 query。
   **它不是 header**，跟得到大脑（`Authorization`）、红狐（`X-API-KEY`）都不一样。

2. **同一个 POST，参数位置可能完全不同**：
   - 公众号 `search-account/v1`：POST，但 `keyword` 在 **query**
   - 视频号 `search-account/v1`：POST，`keyword` 在 **form body**
   → 判据只有一个：`spec` 里 `parameters[].in` 和 `requestBody`，别看 GET/POST。

3. **`code=301` 是常态，要自动重试**：原文 `COLLECT FAILED, SEND REQUEST AGAIN`。
   实测抖音第一次 301、第二次成功。**301 不计费**，所以重试零成本。
   采集器已内置重试 2 次（`config.json` 的 `retry_on_301`）。

4. **视频号 `search-account/v3` 持续 301**（连续 3 次都失败），但 `v1` 正常。
   v3 便宜 3 倍（¥0.50 vs ¥1.50）却不能用，**默认动作已指向 v1**。
   以后可以隔段时间再试 v3，通了就把 `sph.search_account` 的 path 改回去。

5. **扣费是延迟入账的**，跑完立刻查余额经常还是旧值。所以：
   - 「花了多少」**按价目表算**（成功次数 × 单价），准
   - 「剩多少」查余额，实时
   - 两者不一致时不要慌，也不是 bug

6. **充值会让余额往上跳**，用「余额前后相减」算花费会得出负数。已被本地台账 `_ledger.jsonl` 取代。

7. **日志里 token 必须打码**：token 既在 URL 又在 form body 里，任一处漏了，
   一次报错就把 token 写进日志和截图。`mask_token()` 已覆盖两处。

8. **这个源没有逐字稿**。371 个接口里带字幕能力的只有 B站 `get-video-caption/v2`
   和 YouTube `get-video-captions/v1`，四平台都没有。
   抖音和视频号能拿**视频直链**，真要稿得「下载视频 → 转写」，那是另一条链路。

---

## 落盘长什么样

```
02_储存/03_justoneapi/
├── _ledger.jsonl                       每次调用的台账（一行一条）
├── xhs.search_user/
│   ├── 20261029_190348_养生.json        完整原始响应，一字不删
│   └── 20261029_190348_养生.meta.json   参数、耗时、code、花费、余额、sha256
├── dy.search_user/
├── gzh.search_account/
└── sph.search_account/
```

`02_储存` **不进 git**（体积大），换机器要手动拷。

---

## 加工的边界（还没写）

这个源**不套 30 列**。四平台字段完全不同：小红书的粉丝在文本里、抖音的藏在 JSON 字符串里、
公众号只有 1 条、视频号标题带 HTML —— 硬塞进同一张 30 列的表会拧巴。

计划：**每个平台一个 adapter，出各自的宽表**，列名跟着接口的实际字段走。
加工层等采集侧稳定了再写。

---

## 目录里各文件干什么

| 文件 | 干什么 | 进 git |
|---|---|---|
| `collect.py` | 唯一入口：doctor / balance / spent / list / call / accounts / sync-spec | 是 |
| `config.json` | 动作表 + 价目表。**真值不在这里** | 是 |
| `spec/public-api.json` | 接口字典，1.2 MB，371 个接口 | 是 |
| `README.md` | 就是这份 | 是 |
