# 01_采集

把内容抓回来，原样落进 `02_储存`。**只干这一件事**——清洗、转表是 `03_加工` 的活。

---

## 一个源一个文件夹，各自独立

```
01_采集/
├── README.md
├── 01_lingzao/         # 灵造（花钱）
│   ├── config.json     # ★ 要填的在这
│   ├── collect.py      # 执行逻辑 + 动作定义，自包含
│   └── README.md       # 怎么装、怎么跑
└── 02_getnote/         # 得到大脑（不花钱）
    ├── config.json     # ★ 要填的在这
    ├── collect.py
    └── README.md
```

**每个文件夹都是完整的。** 里面这三个文件就够跑，不引用外面的任何东西。

所以：

- **拷走就能用** —— 把 `01_lingzao/` 整个拷到别的项目去，只要有 Python，照样跑
- **删掉就是卸载** —— 不要灵造了，删掉 `01_lingzao/`，得到大脑毫发无伤

**代价**：两个 `collect.py` 里的工具代码是重复的。改一个 bug 要改两遍——
这是换独立性的价钱。**改的时候记得两个都改。**

| 源 | 干什么 | 花钱吗 |
|---|---|---|
| `01_lingzao` | 主动去搜：按关键词搜笔记、深挖单个博主 | 花。搜一次 **20**；博主深度解析按条数 **50 / 100** 分档 |
| `02_getnote` | 读**外部内容**：订阅博主的逐字稿 + 封面 | 不花（会员制，只占次数） |

---

## 不装依赖，也不用配环境

两份 `collect.py` **只用 Python 标准库**，一个 pip 包都没用。

所以没有 `pip install`，没有虚拟环境，没有要配的环境变量。打命令就行。

CLI 的路径也不写死，每次自己去 `config.json` 列的位置找：先看显式路径，再看环境变量，
再试候选位置，最后翻 `PATH`。

---

## 各跑各的

```bash
# 灵造
python 01_采集/01_lingzao/collect.py doctor
python 01_采集/01_lingzao/collect.py search --keyword "AI写作"          # 预演，不花钱
python 01_采集/01_lingzao/collect.py search --keyword "AI写作" --go     # 真抓

# 得到大脑（全走开放平台 HTTP API，不用 CLI）
python 01_采集/02_getnote/collect.py doctor
python 01_采集/02_getnote/collect.py bloggers --topic <topic_id>            # 拿 follow_id
python 01_采集/02_getnote/collect.py details  --topic <topic_id> --follow <follow_id>
```

抓完接着出表：

```bash
python 03_加工/01_lingzao/run.py  search "02_储存/01_lingzao/search-notes/xxx.json"
python 03_加工/02_getnote/run.py table  "02_储存/02_getnote/blogger"
```

---

## 花钱的源默认不跑

`01_lingzao` 的 `config.json` 里标了 `"paid": true`，所以不加 `--go` **只预演**：
打印要调的命令、落盘路径、花费，然后停下。确认无误再加 `--go`。

得到大脑标的是 `paid: false`，直接跑。

> 别用 `cost` 的文案来判断花不花钱——「0（会员制，读接口不额外扣费）」里也带「扣费」两个字。

---

## 原始输出原样存

不做任何清洗。能当 JSON 解析就存 `.json`，否则存 `.txt`，绝不丢内容。重名自动加序号，
不覆盖。想清洗、想对字段，交给 `03_加工`——那里出错还能回头对原始数据。

---

## 搬走 / 加第三个源

**搬走**：把文件夹整个拷过去就行。只有一种情况要额外处理——如果新位置往上两级不是
项目根，打开 `config.json` 填一下 `project_root`，告诉它 `02_储存` 在哪。

**加第三个源**：复制 `01_lingzao` 或 `02_getnote` 整个文件夹，改名字，然后动三处：

| 改哪 | 改什么 |
|---|---|
| `config.json` | `name`、`store_dir`、`cli`、`probe` |
| `collect.py` | 文件头的说明、末尾的 `ACTIONS` |
| `README.md` | 说明文字 |
