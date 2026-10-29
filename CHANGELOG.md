# 更新日志

本文件记录「好岗好找 · Good-job-Ez」的重要变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [未发布]

### 新增

- **BOSS 直聘接入**（2026-10-29）
  - **本地 adapter**（`~/.bb-browser/sites/boss/search.js`）——
    私有 adapter 优先于社区库
  - **`bbclient.ensure_boss_context()`** —— BOSS 的 `joblist.json` API
    **必须在 zhipin 页面上下文里**发（要 anti-content token），
    没有就 `open` 一个 BOSS 搜索页（社区版 adapter 直接跑会**超时**）
  - **`boss_city_codes.py`** —— BOSS 城市码表（63 个，**官方接口核对**）：
    `wapi/zpgeek/common/data/city/site.json` → 400 个城市码
  - **`scan` 按站点分码表** —— 智联 3~4 位 `jl`、BOSS 9 位 `city`，
    **混用会静默抓到别的城市**
  - **FIELD_MAP 两套字段名都认** —— 社区 adapter 返 `title`/`company`，
    原表只认 `name`/`brandName` → **抓回来的岗位标题和公司全是空**。
    统一词表名放后面（`_normalize` 按插入顺序取，后者覆盖前者）
  - **`cityName` 映射到新增的 `city` 字段** —— 它只给「城市」，
    映射成 `area` 会**把区县信息冲掉**
  - **`scripts/verify-boss-city-codes.sh`** —— 官方接口交叉核对
    + 逐个实测抓取（可只验几个城市）
  - **`scripts/fetch_boss_cities.mjs`** —— 用 CDP 直连抓城市全表
    （`bb-browser eval` 走命令行，**有 8191 字符上限**会截断长代码）
- **模板上传真机修复**（2026-10-29）
  - **`.doc` 里装 docx 能传** —— 按文件头（magic number）判真实格式，
    不只认扩展名。用户的「后端开发.doc」内容其实是 docx
  - **真·旧版 .doc 明确提示** —— 「请在 Word 里另存为 .docx 再上传」，
    不再只说「不支持」
  - **支持选文件夹** —— 新增带 `webkitdirectory` 的独立 input
    （普通 file input 选目录浏览器直接报错）；**那个 input 不带 `accept`**
    （带了会把目录里的文件全过滤掉）
  - **`accept` 加 `.doc`** —— 否则文件选择框里根本选不到
  - **`onPickTemplate` 支持多文件** —— 逐个转换，汇总成功/失败
  - **图片尺寸用标准库读文件头** —— 不再用 PIL
    （CI 没装 PIL → 读不到尺寸 → 走 A4 兜底 → `297 != 315`）
- **`tests/test_ci_parity.py`（6 个）** —— 「本机 3.14 ≠ CI 3.11~3.13」的回归测试
  - 核心模块顶层不许 import PIL
  - 单测不许 import Hermes 的包（自己造假模块塞 `sys.modules`）
- **`dev.sh check` 第 8 步** —— **多 Python 版本验证**（用 `py` 启动器逐个跑
  3.12/3.13/3.11，没装的跳过）—— 提交前 10 秒知道 CI 会不会红
- **`tests/test_boss.py`（15 个）**、**`tests/test_template_upload.py`（12 个）**

- **招聘站浏览器与登录**（`browser_session.py`）
  - 登录态只在浏览器里 → 插件不碰密码、不碰验证码，给用户一个
    「打开招聘网站登录」的地方
  - **用 bb-browser 自己起的浏览器**（有可见窗口、profile 持久化，
    浏览器完全重启后 cookie 一个不少）—— 不接管用户的日常 Chrome
  - 抓取前自动确保浏览器在跑（`bbclient.run_site` 里调
    `ensure_browser()`）
  - 设置页「平台接入」新增「招聘站登录」面板：每站一个登录按钮
  - API：`GET /browser/status`、`POST /browser/login`
  - **不硬编码任何本机路径** —— 别人设备上也能用
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
- **`src/job_radar/scripts/verify_browser_session.py`** —— 浏览器会话端到端验证
  （真的关掉浏览器再拉起来，验证 cookie 持久化）

- **主攻方向 / 也投方向（两级）**
  - `title_keywords_primary` —— 主攻，命中给**满 30 分**
  - `title_keywords` —— 也投，命中给**固定 15 分**
  - 用户同时投多个方向时混在一张列表里会**平分 30 分** → 两个方向混排，
    主攻被次要挤下去
  - **没填主攻时按老规则**（每个 +10，最多 30）—— 老用户分数不变
  - 个人信息页拆成「主攻方向」和「也投的方向」两个输入
- **多城市抓取**
  - 站点 → 城市 → 关键词 三层循环
  - **智联的 `--city` 只认一个码**，逗号分隔会**静默退化成全国**
  - 新增 `settings.cities`（存**城市名**，抓取时翻译成码）
  - 设置页新增「抓取城市」选择器 —— **给城市名，不给「南宁 = 3150」**
- **智联城市码表**（`city_codes.py`）
  - 36 个**实测通过**的城市 —— 按记忆填的 60 个里有 **28 个是错的**
  - `scripts/verify-city-codes.sh` 逐个码跑真实抓取对比城市名
  - `scripts/find_city_code.sh <城市名>` 扫出新城市的码
  - 详见 [`docs/智联城市码表.md`](docs/智联城市码表.md)
- **按当前画像重排岗位**（`storage.rescore_all`）
  - 改了方向/技能/城市后，**没被抓到的老岗位**分数还是旧的 → 老岗位挤在前面
  - 扫描开始时自动重算；设置页有「按当前画像重排岗位」按钮
- **结构化经历落 SQLite**（`experiences` 表）
  - 之前只在 mock 的**进程内存**里 —— 重启全丢
  - 空 id 一律生成新的（uuid，不用序号 —— 删过会撞）
- **结构化经历进简历**
  - 「工作经历」章节有**公司 / 职位 / 起止** —— 自由文本给不了这些
  - bullets 只留命中 JD 的；没命中任何要求的经历**仍保留标题**
  - 只填结构化经历（不填自由文本）也能生成简历
- **用户技能当 JD 要求**
  - 内置别名表只覆盖常见技术词 → JD 写「熟悉 CAD、Revit」但要求里**一个都没有**
    → 用户的 CAD 经历**一条都匹配不上** → 简历写成空的
  - 规则：**用户会的技能 + 出现在 JD 里** = 一条 JD 要求
- **新用户开箱可用**
  - 个人信息页检测到「方向和技能都空」→ 引导条 + **「填一份示例」**按钮
  - 设置页检测到「没关键词」→ 提示（`scan` 会直接中止）
- **岗位推荐折叠** —— 默认只显示分数最高的 **5 条**，其余折叠到「更多岗位」
- **Word / PDF / 图片模板转换真实现**（`template_convert.py`）
- **新对话接手指南大幅更新** —— 当前画像方向、进度、**本轮踩的 14 个坑**

- **「主攻方向」存不进去**（严重）
  - 后端 `ProfileIn` 模型里没有 `title_keywords_primary` → Pydantic **直接丢掉**
  - → 界面填了 → 保存 → 接口返回 `{"ok": true}` → **刷新就没了**，且不报错
- **新增结构化经历把旧的挤掉**
  - 前端新增时传 `id: ''`（空字符串），后端 `dict.setdefault` 在
    **key 存在时不会覆盖** → 空串被当成真 id → upsert 把同 id 的旧记录顶掉
- **`cities` 的配置描述和实现对不上**
  - `plugin.yaml` 说填城市**码**，代码只认**城市名**
  - 照着填码 → 解析成空 → **静默退回默认城市（杭州）**
- **脱离包就 `attempted relative import`**
  - `from . import report` 脱离包直接 ImportError；`tools.daily()` 把它吞成
    「生成日报失败」
- **`load_config()` 依赖 ctx** —— 没有 ctx 时 `keywords` 为空 → 抓取直接中止。
  现在兜底读 Hermes 的 `config.yaml`
- **改了画像，老岗位的分数不重算**
- **React `key` 警告** —— `jsx(type, props, key)` 第三参数才是 key
- **const 暂时性死区会让整页白屏** —— `Cannot access 'showAllJobs' before initialization`
- **`Button variant: 'primary'` / `Badge variant: 'soft'` 不存在**
  → cva 不生成样式类 → 组件渲染成裸文字
- **个人信息页缺保存按钮** —— 原来只在「真实经历」面板，从「身份信息」填完找不到
- **个人信息输入框打不进字** —— `setIdentity` 把更新函数当键名传给了 `set(k, v)`
- **「＋ 添加技能」点了没反应** —— Electron 禁用 `window.prompt()`
- **测试会污染用户真实数据 / 真去抓网站**
  - `plugin_data_dir` 在 `storage.py` 是**顶层 import**、在 `config.py` 是**函数内
    import** —— 两个都得 patch，否则测试写进用户真实经历库
  - `args.get("sites") or cfg["sites"]` 会吃掉空列表 → 测试真发了 80 个请求
  - 已有断言守着（`tests/test_new_user_journey.py`）

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
- **单测只隔离了配置读路径** —— 写路径会真调 `hermes config set`：
  本机污染用户 config.yaml，CI 上没 CLI 直接抛错
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
