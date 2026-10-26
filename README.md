# 好岗好找 · Good-job-Ez

> 一个跑在 [Hermes](https://hermes-agent.nousresearch.com) 上的招聘岗位雷达插件。
> 定时从 BOSS 直聘、智联招聘抓岗位，按你的画像本地打分，把高分的推到你手机上。

**核心原则：只读抓取 + 本地打分 + 推送前必须你点头。**

---

## 它做什么

| 能力 | 说明 |
| --- | --- |
| **定时抓取** | 按关键词轮询各招聘站，只读，不碰你的日常窗口 |
| **本地打分** | 职位名 30 + 技能 30 + 城市 20 + 薪资 20 → 0~100 分。**不烧 LLM** |
| **精简推送** | 每条消息 = `岗位名 · 城市` + 链接，不带分数不带理由 |
| **日报存档** | 每天一份 Markdown，完整明细（分数/命中/缺口）留档 |
| **登录态体检** | 告诉你各站登录态还剩几天，掉了会提醒 |
| **简历匹配优化** | 读 JD → 对照你的经历 → 按模板生成定向简历，**不编造经历** |
| **用户简历档案** | 投递成功的简历自动存 PDF + 打标签，作为后续推荐依据 |

---

## 亮点：复用你浏览器的登录态

大多数爬虫方案让你重新登录一遍。这个插件**不登录、不存密码、不偷 cookie**。

它做的是：让 [bb-browser](https://github.com/epiral/bb-browser) 通过 CDP
挂到你**已经在跑的那个 Chrome** 上，借用你现有的登录态发请求。

```
你的 Chrome (9222)  ←── bb-browser daemon ──→ job-radar
  └─ profile/
       └─ Network/Cookies  ← 登录态在这，插件碰都不碰
```

好处：

- 关掉 Chrome 再打开，**登录态还在**，不用重新登录
- 你的账号行为轨迹是真实的，比新开的自动化浏览器更像人
- 插件崩了、卸载了，你的账号不受影响

代价（说在前面）：出口 IP 还是你本机的 IP，
**独立 profile 不会改变这一点**，也无法隐藏。

---

## 安装

### 1. 克隆

```bash
git clone https://github.com/<你的账号>/Good-job-Ez.git
cd Good-job-Ez
```

### 2. 装到 Hermes 插件目录

```bash
# Windows
cp -r src/job_radar "$LOCALAPPDATA/hermes/plugins/job-radar"

# macOS / Linux
cp -r src/job_radar ~/.hermes/plugins/job-radar
```

### 3. 准备 bb-browser

```bash
npm install -g bb-browser
```

### 4. 用带调试端口的 Chrome 启动

```bash
chrome --remote-debugging-port=9222 --user-data-dir="/path/to/your/profile"
```

> 用**你平时那个 profile**，这样才有你已登录的 cookie。
> 换 profile = 换身份。

### 5. 填个人画像

编辑 `~/.hermes/plugins/job-radar/profile.yaml`：

```yaml
{
  "title_keywords": ["前端", "web", "three.js"],
  "skills": ["three.js", "vue", "typescript", "node"],
  "city": "杭州",
  "min_experience_years": 3,
  "min_salary": 15,
  "exclude_companies": ["外包", "劳务派遣"]
}
```

### 6. 起插件

```bash
hermes plugins doctor ~/.hermes/plugins/job-radar --ci
```

---

## 配置

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `keywords` | `[]` | 搜索关键词列表 |
| `city` | `653` | 智联城市代码。653=杭州 538=上海 530=北京 489=全国 |
| `boss_city` | `101210100` | BOSS 城市代码。101210100=杭州 |
| `min_score` | `60` | 日报/推送的入选分数线 0-100 |
| `max_jobs_per_run` | `40` | 单次运行最多抓多少条 |
| `sites` | `["zhaopin"]` | 启用哪些站：`zhaopin` / `boss` |
| `request_gap_seconds` | `12` | 两次请求的基准间隔（秒），实际会加 0~20 秒随机 |

### 城市代码

智联和 BOSS 各有一套，别混：

| 城市 | 智联 | BOSS |
| --- | --- | --- |
| 全国 | 489 | 100010000 |
| 北京 | 530 | 101010100 |
| 上海 | 538 | 101020100 |
| 杭州 | 653 | 101210100 |
| 深圳 | 765 | 101280600 |

---

## 工具

| 工具 | 作用 |
| --- | --- |
| `job_radar_scan` | 跑一次抓取 + 打分 + 入库 |
| `job_radar_daily` | 生成今日日报 Markdown |
| `job_radar_push` | 把高分岗位推送到 QQ |
| `job_radar_list` | 列出岗位池（按匹配度倒序） |
| `job_radar_mark` | 给岗位打标签（interested / applied / ignored） |
| `job_radar_login` | 体检各站登录态，算出还能用几天 |

---

## 风控与安全

插件的第一原则是**不出事**：

- **默认只读。** 投递功能默认关闭，开了也要你单独点头。
- **三道门。** 站点开关（默认关）→ 一次性确认令牌（5 分钟）→ 该站每日上限。
- **PAUSE 总闸。** 建一个 `PAUSE` 文件，立刻停掉一切抓取。
- **随机停顿。** 每次请求后停 12~32 秒，单次运行条数封顶。
  被限流时第一件事是**加大间隔**，不是加并发。
- **简历文件不走大模型。** 上传的 .docx/.pdf 只在本机做规则解析，
  不发给任何模型。（例外：「AI 根据经历推荐」传的是提取出的方向词，可以调模型。）

详见 `docs/开发文档与流程图.html` 的「四、风险控制清单」。

---

## 开发

```bash
# 跑测试
cd src/job_radar && python -m unittest discover -s tests

# 看当前抓取层状态
python src/job_radar/../job_radar/tests/../  # 详见 docs/抓取层现状.md
```

### 目录结构

```
Good-job-Ez/
├── src/job_radar/          插件本体
│   ├── plugin.yaml         插件元数据 + 配置 schema
│   ├── __init__.py         工具注册
│   ├── tools.py            六个工具的实现
│   ├── matcher.py          本地打分（五项权重）
│   ├── bbclient.py         调用 bb-browser adapter
│   ├── storage.py          SQLite 岗位池
│   ├── report.py           Markdown 日报生成
│   ├── push.py             QQ 消息拆分（50 字上限）
│   ├── login_check.py      登录态体检（纯函数，可单测）
│   ├── browser_cookies.py  CDP 读 cookie（不落盘）
│   └── tests/              单元测试
├── docs/
│   ├── 开发文档与流程图.html   架构 + 流程图 + 风险清单
│   ├── 开发文档与流程图.pdf
│   ├── 设置页-demo.html        设置页 UI demo（未接后端）
│   └── 抓取层现状.md           实测记录
└── examples/
```

### 加一个新招聘站

每个站一个 adapter，输出统一的岗位 JSON。
**新增站点不需要改打分和推送逻辑。**

```
~/.bb-browser/sites/<站名>/search.js
~/.bb-browser/sites/<站名>/detail.js
```

详细写法见 bb-browser 的 site-system 文档。

---

## 状态

| 站点 | 状态 |
| --- | --- |
| 智联招聘 | ✅ 抓通（列表 + 详情 JD） |
| BOSS直聘 | ✅ 抓通（列表 + 详情） |
| 汇博招聘网 | 🚧 adapter 未开发 |
| 广西人才网 | ⏸ 暂缓（多子域名，各自独立身份） |
| 重庆人社 | ⏸ 暂缓（公告流，不参与打分） |

---

## 许可

MIT。见 [LICENSE](LICENSE)。

---

## 免责声明

本项目用于**个人求职辅助**。

- 抓取行为发生在你自己的浏览器、你的账号、你的 IP 上，风险自负。
- 请遵守目标站点的服务条款与 robots 协议，抓取频率已内置限速。
- 投递出去的内容由你自己负责，插件只帮你整理和准备材料。
