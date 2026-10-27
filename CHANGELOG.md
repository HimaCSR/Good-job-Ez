# 更新日志

本文件记录「好岗好找 · Good-job-Ez」的重要变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [未发布]

### 新增

- **投递三道门真实现**（`apply_gate.py`）
  - 站点开关（默认全关）+ 一次性令牌（5 分钟，绑定 job_id + site）+ 每日上限
  - **令牌落 SQLite**（`apply_tokens` 表）—— 内存版重启就丢，跨进程也不共享
  - 投递记录落 `apply_records` 表
  - 配置用**扁平键**（`apply_zhaopin` / `apply_limit_zhaopin`）——
    嵌套字典会被配置读取器打散成顶层键
  - 设置页「平台接入」新增「投递开关」面板：每站一个开关 + 每日上限
  - 动作层（真正投出去）还没接 —— 招聘站投递接口需要站点私有 adapter
- **定时任务改为脚本模式（不经过 LLM）**
  - `examples/job_radar_cron.py` → 装到 `~/.hermes/scripts/`
  - `hermes cron edit <id> --script job_radar_cron.py --no-agent`
  - **完全不烧 token**，脚本 stdout 直接投递到 QQ；空输出 = 静默
- **岗位推送去重**：`jobs` 表新增 `pushed_at` 列，只推没推过的岗位
- **`src/job_radar/requirements.txt`** —— 显式声明 jinja2 / fastapi / pydantic
- **`scripts/check-desktop-js.mjs`** —— 桌面端 plugin.js 语法自检（只解析不执行）
- **`src/job_radar/scripts/verify_apply_gate.py`** —— 三道门端到端验证
  （打真实配置 + 真实库，跑完自动恢复原值并清理）

### 修复

- **Python 3.11 / 3.12 / 3.13 上插件直接导入失败**
  - `storage.py` 用了 `List[dict]` 但没 `from typing import List`
  - 本机是 3.14（注解惰性求值）所以看不出来，**CI 矩阵必炸**
- **CI 从来没装依赖** —— `jinja2` / `fastapi` / `pydantic` 缺失，
  main 分支的 CI 一直是红的。现在补上 requirements 并安装
- **懒加载日志 handler 第一次写日志就崩**（Python 3.11 / 3.12 / 3.13）
  - `logging.Handler.handle()` 在进入 emit **之前**就 acquire 了 handler 的 lock，
    而父类 `__init__` 在首次 emit 里才跑，会新建一个 lock 替换掉原来的
    → `RuntimeError: cannot release un-acquired lock`
  - Python 3.14 上 `Handler.handle` 实现不同，看不出来
- **SQLite 连接泄漏** —— `with conn:` 只提交事务、**不关连接**，
  24 个调用点每个漏一个句柄。改用 `_Conn` 子类，`__exit__` 里关
- **推送格式还是旧版**：一直带着分数和命中理由，用户早就定了「只发岗位名 · 城市 + 链接」
- **同一个岗位被反复推送**：`only_new=true` 只看「最近一天首次出现」，
  而 `INSERT OR REPLACE` 每次抓取都重置 `first_seen` 和 `pushed_at`，
  导致判据失效。改成 `ON CONFLICT DO UPDATE` —— 只更新变化字段，
  保留首次出现时间和推送标记

### 计划中

- **投递动作层**：调招聘站真实投递接口（需要站点私有 adapter）
- **经历结构化**：落库并接进简历生成（现在只有自由文本，缺公司名和时间）
- **Word / 图片模板转换**：抽版式参数 → HTML 模板
- **汇博招聘 adapter**
- **Release tag**

---

## [0.2.0] — 2026-10-26

### 新增

- **插件运行日志**（`logging_setup.py`）
  - 两层输出：插件自己的 `job-radar.log`（RotatingFileHandler 5 MB × 3）
    + 标准 logging（`hermes_plugins.job_radar` 命名空间，进 Hermes 的
    `agent.log` / `errors.log`）
  - 凭证自动打码：已知凭证键（`zp_at` / `cookie` / `token` …）的值换成
    `[REDACTED]`，40 位以上随机串也打码；状态描述、URL、公司名不受影响
  - 埋点覆盖 adapter 调用、扫描主流程、日报、推送、登录态体检；
    未捕获异常走 `log.exception` 带完整堆栈
- **后端 API**（`dashboard/plugin_api.py`，11 个端点）
  - `GET /config /jobs /runs /login /report /resumes /templates /logs`
  - `POST /settings /profile /templates /logs/purge`
- **桌面端设置页**（`src/job_radar/desktop/plugin.js`）
  - 主入口 `ctx.registerSettingsPage`，五个子页：个人信息 / 岗位推荐 /
    用户简历 / 平台接入 / 日报
  - 左侧栏入口 + `/job-radar` 路由
  - 「平台接入」新增「运行日志」面板（默认收起）
- **简历与模板数据表**：`resumes` / `resume_templates`（`storage.py`）
- **用户简历模块**：模板库（多选、帮助浮层、上传入口）+ 简历档案列表

### 修复

- **后端路由从未挂载**：缺少 `dashboard/manifest.json`，Hermes 找不到
  `api` 字段，所有端点一直 404
- **dashboard 层相对导入必然失败**：Hermes 把 `dashboard/plugin_api.py` 当独立
  模块加载（`hermes_dashboard_plugin_<name>`），没有父包，
  `from . import storage` 抛 ImportError。改为把插件根目录注册成真包 `job_radar`，
  兄弟模块按依赖顺序加载
- **薪资解析崩溃**（`matcher._salary_score`）：`8000-12000` 这种不带单位的
  写法没给 `unit` 赋值 → `UnboundLocalError`，扫描直接崩。
  此前未暴露是因为所有岗位薪资都是打码的 `**-**元`；登录后拿到真实薪资才触发
- **QQ 分条切断 URL**：`split_for_qq` 在 `limit` 处硬切会把链接切成
  `https:` + `//example.com` 两半，点了打不开。新增 `_url_boundary()`：
  URL 起点在 limit 内时把切点推到 URL 之前，URL 独占一段时整条不切
- **配置读取用 ctx 而非磁盘**：`load_config()` 在没有 ctx 时返回默认值
  （`keywords` 为空），定时任务会抓不到东西。设置页改为直接读磁盘，
  读写都走 `hermes config get/set`，不手写 YAML
- **UI 三个视图被挤出主内容区**：多余闭合 `</div>` 导致浏览器重组 DOM

### 变更

- **个人画像移出插件目录**：`profile.yaml` 从插件目录移到
  `<plugin-data>/job-radar/profile.yaml` —— 插件目录在开发时指向 git 仓库，
  画像是私有数据不能进版本库
- 评分公式去掉经验项：**职位名 30 + 技能 30 + 城市 20 + 薪资 20**
- 推送格式精简：每条消息只含 `岗位名 · 城市` + 链接，不带分数与理由
- 日报模块顺序：今日日报在前，推送内容在后；定时与推送细项并进「高级」
- 岗位卡三个按钮同行横排：简历匹配优化 / 投递简历 / 打开岗位
- 筛选条件收进「今日候选」面板右上角「高级」，默认折叠

---

## [0.1.0] — 2026-10-26

### 新增

- **抓取层**：智联招聘、BOSS 直聘两个只读 adapter（私有，不进仓库）
- **匹配评分**（`matcher.py`）：本地确定性打分，0~100 分，输出命中理由与技能缺口
- **岗位池存储**（`storage.py`）：SQLite，`job_id` 主键，重复岗位不新增行
- **日报生成**（`report.py`）：每日 Markdown，含分数、理由、缺口、链接
- **QQ 推送拆分**（`push.py`）：每条 ≤50 字符（URL 除外），按句拆分不劈开单词
- **登录态体检**（`login_check.py` / `browser_cookies.py`）：
  走 CDP `Storage.getCookies` 读状态，**不落盘凭证值**
- **6 个 agent 工具**：`job_radar_scan` / `daily` / `list` / `mark` / `push` / `login`

### 说明

- 登录态复用用户本机 Chrome（CDP 9222），插件不登录、不存密码、不偷 cookie
- 关掉 Chrome 再打开登录态仍在（实测）
- 城市代码：智联杭州 `653`，BOSS 杭州 `101210100`

---

[未发布]: https://github.com/HimaCSR/Good-job-Ez/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/HimaCSR/Good-job-Ez/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/HimaCSR/Good-job-Ez/releases/tag/v0.1.0
