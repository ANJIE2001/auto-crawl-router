# 01_lingzao · 灵造

**花钱的源。** 主动去外面搜：按关键词搜笔记、深挖单个博主。

- `search`（搜笔记）→ **20 积分/次**
- `profile`（博主深度解析）→ 按条数分档：1–20 条 **50**，21–40 条 **100**

---

## 第一次使用

> **已经在别的项目里配过灵造？** 跑一下 `lingzao doctor`，如果显示「正常」，
> 这一整节都跳过，直接跑最下面的自检就行。**Key 不用再填一遍。**

### 1. 装 CLI

```bash
npx skills add https://assets-tian.midao.site/skills/lingzao --skill lingzao -g --copy
```

装完 CLI 在 `~/.lingzao/bin/lingzao.cmd`。

### 2. 配 API Key

打开 <https://lingzao.atian.vip>，按教程开通在线服务、拿到 Key，然后：

```bash
bash "<灵造 Skill 目录>/scripts/setup.sh" --base-url "https://lingzao.atian.vip"
```

> **`<灵造 Skill 目录>` 就是那个含 `SKILL.md` 的文件夹** —— 本机在
> `~/.workbuddy/skills/@user_71a0bff3/lingzao/`，`setup.sh` 在它的 `scripts/` 下面。
> ⚠️ **不在 `~/.lingzao/` 里** —— 那是 CLI 的安装位置，两回事。

Key 存在 `~/.lingzao/config.json`，**不会进这个项目**。

### 3. 自检

```bash
python 01_采集/01_lingzao/collect.py doctor
```

看到「就绪」就能用了。它会告诉你 CLI 找到没、连得通没、账号是谁。

---

## 要填的只有两处

打开同目录的 `config.json`：

| 字段 | 什么时候填 |
|---|---|
| `cli.path` | 只在自动找不到 CLI 时才填，填完整路径 |
| `auth.api_key` | 只在想覆盖 CLI 已存的 Key 时才填。**这个文件会进 git，别把 Key 写这儿**——要填请写到同目录的 `config.local.json`，那个不进 git |

其余字段保持默认即可。

---

## 怎么跑

```bash
# 预演：打印要调的命令、落盘路径、花费，然后停下。不花钱
python 01_采集/01_lingzao/collect.py search --keyword "AI写作"

# 确认了再加 --go
python 01_采集/01_lingzao/collect.py search --keyword "AI写作" --sort most_liked --go

# 深挖单个博主
python 01_采集/01_lingzao/collect.py profile --url "https://www.xiaohongshu.com/user/profile/xxx" --go
```

可选筛选参数（不给就用默认）：

| 参数 | 可选值 |
|---|---|
| `--sort` | `general` / `most_liked` / `popularity_descending` / `comment_descending` / `collect_descending` |
| `--note-type` | `不限` / `视频笔记` / `图文笔记` / `直播笔记` |
| `--time-filter` | `不限` / `一天内` / `一周内` / `半年内` |

**真抓成功之后会自动往下走**，不用你记得第二步：

```
抓取 → 落盘 JSON（02_储存/01_lingzao/）
     → 抢封面       （URL 只有 3 小时寿命，见下）
     → 下完整字幕合集（免费，见下）
     → 接清洗 → 04_产出/博主/<昵称>_<账号ID>/ 里立刻有东西
```

`--no-clean` 关掉最后一步，只采集不出表。加工层万一被删了，采集照常工作、只提示一句。

想手动重跑加工：

```bash
python 03_加工/01_lingzao/run.py search "02_储存/01_lingzao/search-notes/xxx.json"
python 03_加工/01_lingzao/run.py bundle "02_储存/01_lingzao/analyze-user-profile/xxx.json"
```

---

## 两个坑

**封面 URL 带过期签名，只有约 3 小时寿命。** 采集时已经自动抢一遍（落盘后立刻跑），
超了就全返回 HTTP 498，**而且救不回来** —— 原始 JSON 里存的是已经签好名的 URL，
过期就是废纸，想拿新的只能重新抓一次（**花钱**）。

所以漏了、失败了要**趁窗口内**补：

```bash
python 03_加工/01_lingzao/run.py cover "02_储存/01_lingzao/analyze-user-profile/"
```

**profile 里的字幕是截断的 —— 但全文采集时已经一起下好了。**

JSON 里 `items[].text.subtitle.plain_text` 那份**卡在 1203 字上限**（实测 16 条有字幕的
里 14 条正好撞顶）。**全文不在 items 里**，而是**顶层字段**：

```
data.artifacts.subtitle_markdown.status      ready
data.artifacts.subtitle_markdown.url         静态文件地址（公开签名，expires_at: null，不过期）
data.artifacts.subtitle_markdown.size_bytes  服务端报的大小
```

那是个公开签名的静态文件，下载**不调灵造 API、不扣积分**。采集落盘后顺手就下 ——
**落两个文件**，都跟源 JSON 同前缀：

| 文件 | 内容 |
|---|---|
| `<JSON名>_完整字幕合集.md` | 正文，**原样落盘不解析**（加工层按同前缀精确配对） |
| `<JSON名>_artifacts.json` | **来源记录**：URL / status / size / `sha256` / 下载结果 |

那份 `_artifacts.json` 就是**以后想重下全文时的入口** —— 不用拿几百 KB 的原始 JSON 去 grep。
下完会拿服务端给的 `sha256` 校验一遍：**只比 size 不够**，内容坏掉不一定改大小。
（`status=missing` 这类没下成的也会写一份，记下原因，而不是静默略过。）

所以加工出来的 `逐字稿.md` 是**全文**。怎么判断：**各条长度不一样 = 全文；
一堆一样的数字 = 还在用截断版**（那说明合集没下到）。

⚠️ 别在 `items[].artifacts` 里找 —— 那个是空的，第一次就查错了地方。

---

## 想加动作

改同目录 `collect.py` 末尾的 `ACTIONS`，照 `search` 抄一份，换命令和参数。`config.json` 不用动。

---

## 这个文件夹是自包含的

`collect.py` 里带着全部执行逻辑，**不引用 `01_采集` 里的任何其他文件**。

所以它拷到哪儿都能跑，只要同目录有 `config.json`。唯一要注意的：如果新位置往上两级
不是项目根，打开 `config.json` 填一下 `project_root`，告诉它 `02_储存` 在哪。
