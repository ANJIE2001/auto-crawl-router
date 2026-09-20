# 02_getnote · 得到大脑

**不花钱的源。全走开放平台 HTTP API，不用 CLI**（2026-09-20 定）。

读接口会员制、不额外扣费，所以**不用加 `--go`**，直接跑。

**跑完自动出表** —— 采集成功后会自动接上同源的加工，`04_产出/` 里立刻有东西。

---

## 第一次使用

### 1. 配凭证（唯一的准备）

去**得到大脑开放平台** → 创建应用 → 生成 API Key，会同时给你两个值：

| 值 | 形如 | 对应请求头 |
|---|---|---|
| Client ID | `cli_xxx` | `X-Client-ID` |
| API Key | `gk_live_xxx` | `Authorization`（**不带 Bearer 前缀**） |

填进同目录的 **`config.local.json`**：

```json
{
  "openapi": {
    "client_id": "cli_xxxxxxxx",
    "api_key": "gk_live_xxxxxxxx"
  }
}
```

> **为什么不填 `config.json`？** 那个文件会进 git。`config.local.json` 在 `.gitignore` 里
> （`01_采集/*/config.local.json`），填那儿不会外泄。

**开权限的时候**只抓外部内容的话，勾这几个就够：

| Scope | 作用 |
|---|---|
| `topic.read` | 读知识库信息 |
| `topic.blogger.read` | **读博主内容**（逐字稿靠它） |
| `topic.write` | 只在想让程序自动订阅新博主时才勾 |
| `topic.live.read` | 只在要抓直播时才勾 |

**带 `note.` 前缀的一个都别勾** —— 那是私人笔记的读写权限，勾了隔离就白做了。

⚠️ **不需要装 `getnote` CLI，也不需要 `auth login`。** 这条链一个 CLI 都不调。

### 2. 自检

```bash
python 01_采集/02_getnote/collect.py doctor
```

会列出手上有哪些知识库、各自的 `topic_id`。看到「就绪」就能用了。

---

## 怎么跑

三步，但一般只用第三步（前两步是给你查 id 用的）：

```bash
# ① 博主列表 → 拿 follow_id
python 01_采集/02_getnote/collect.py bloggers --topic YpDxK1MY

# ② 内容列表 → 拿 post_id_alias 清单（只想看有哪些内容时跑）
python 01_采集/02_getnote/collect.py contents --topic YpDxK1MY --follow 1397022

# ③ 逐条详情 → 逐字稿 + 封面，★ 跑完自动出表
python 01_采集/02_getnote/collect.py details --topic YpDxK1MY --follow 1397022 --limit 20
```

**`details` 是关键命令**：它内部先拉一次内容列表拿到 id，再逐条拉详情。
跑完它会自动调 `03_加工/02_getnote/run.py blogger`，
把 `04_产出/博主/<昵称>_<账号ID>/` 里该有的全铺好 —— **不用你记得第二步**。
不想让它自动出表就加 `--no-clean`。

| 参数 | 说明 |
|---|---|
| `--limit` | 拉多少条（`details` 默认 20；`0` = 全部） |
| `--pages` | 最多翻多少页，每页固定 20 条（`page_size` 参数无效） |
| `--gap` | 每条之间的间隔秒数，默认 3.5。**被限流了就调大** |

### 已知速度

**桶级限流**，连着调两个接口就会撞 `429`，等 4 秒恢复。所以每条之间停 3.5 秒：

```
20 条  ≈ 2 分钟
665 条 ≈ 40 分钟
```

额度（read）日 20000 / 月 200000 —— 撞的一定是 QPS 桶，不是配额。

---

## 三条接口（都在 `/open/api/v1/resource/knowledge` 下）

| 用途 | 路径 | 关键返回 |
|---|---|---|
| 博主列表 | `GET /bloggers?topic_id=` | 账号名 / `follow_id_str` / 内容数 / 头像 / 抖音主页 |
| 内容列表 | `GET /blogger/contents?topic_id=&follow_id=&page=` | 12 字段，含封面、原链接 |
| **内容详情** | `GET /blogger/content/detail?topic_id=&post_id=` | **`post_media_text` = 逐字稿** |

**为什么全走 HTTP、不用 CLI**：详情接口一次返回 12 个字段 ——
逐字稿和**封面**都在里面；CLI 的详情只有 10 个、而且**没有封面**。
走一条通道，就少一处「两边不一致」。

⚠️ **官方文档不全**：详情接口文档只写了 6 个字段，实测返回 12 个
（多出 `post_cover` / `post_url` / `post_type` / `post_create_time` / `post_update_time` /
`post_subtitle`）。**别拿文档的字段表当白名单校验**，会漏数据。

---

## 字段现实（都是踩出来的）

- **封面（`post_cover`）链接不过期** —— 不带签名，和灵造那种 3 小时就废的完全两回事。
  封面**图**由加工层归位（`03_加工/02_getnote/`）：先取图池，图池里没有就用这个 URL
  **现下** —— 所以不用担心缺封面。想把图池一次性补满：`run.py cover`。
  哪天缺了随时补，不用抢。
- **逐字稿不保证每条都有** —— 实测 20 条里 1 条没有。适配器按「有稿 / 无稿」两态处理。
- **详情里的 `post_id_alias` 是空串** → 身份只能从**落盘文件名**取。
- **详情里没有任何作者字段** → 博主名去**同目录的 `_bloggers_*.json`** 里找。
- **`post_name` 带完整话题串**（`标题 #标签1 #标签2`）→ 标题和标签要拆开。
- **`post_url` 是 483 字的超长抖音链接**（带 `share_sign` / `ts` / `u_code`），落表前洗净。
- 没有互动数据、没有时长 —— 表里那几列是**「未知」**，不是 `0`。

### 落盘命名（改之前想清楚）

```
02_储存/02_getnote/blogger/
    _bloggers_<昵称>_<follow_id>.json          博主列表
    _blogger-contents_<昵称>_p1.json           内容列表
    _blogger-content_<post_id_alias>.json      单条详情 ← 逐字稿 + 封面
```

两个坑：

1. **不能带日期前缀** —— 带上就跨天并存，同一条内容变两个文件，加工层读到双份
   （实测踩过：20 条被当成 40 条）。哪次抓的看文件 mtime。
2. **必须保住前导 `_`** —— 加工层用 `*_blogger-content_*` 这种 glob 认文件，少了它对不上。

---

## 功能边界：只抓外部，不碰私人笔记

本项目**只抓外部内容**，不读这个账号里的私人笔记。

**可以调**：就上面那三条 HTTP 接口（`bloggers` / `contents` / `details`）。

CLI 那套（`kb bloggers` / `kb blogger-contents` / `kb blogger-content` / `kbs`）**本项目不用** ——
HTTP 给的字段更多（详情 **12 个 vs 10 个**，而且**带封面**）。只有两件 HTTP 还没包的事才可能要 CLI：
**订阅新博主**（`kb blogger-follow`）、**直播**（`kb lives`）。**用到再说，别默认走 CLI。**

**不要调**：

```
notes / note / note original / note transcript / note attachments /
note timeline / note quick-note / note todos    私人笔记
search                                           语义搜的就是私人笔记
tag * / kb（知识库笔记列表）
save / note update / note delete / note share    写
```

⚠️ **这是「约定隔离」，不是「权限隔离」。** 现在这条链用的是**全权限** key
（用户知情接受），靠代码自觉不碰那些接口。想硬隔离只有一条路：
去开放平台建一个只勾 `topic.read` + `topic.blogger.read` 的应用，把
`config.local.json` 里那两个值换掉，**代码不用动**。

---

## 这个文件夹是自包含的

`collect.py` 里带着全部执行逻辑，**不引用 `01_采集` 里的任何其他文件**。
只用 Python 标准库，一个 pip 包都不用装。

拷到哪儿都能跑，只要同目录有 `config.json` 和 `config.local.json`。
唯一要注意的：如果新位置往上两级不是项目根，打开 `config.json` 填一下 `project_root`。

> **抓完自动接清洗**那一步会去找 `03_加工/02_getnote/run.py`。
> 找不到就跳过（只提示一句），采集照常工作 —— 所以**删掉加工层目录，
> 这个文件夹依然是完整可用的**。
