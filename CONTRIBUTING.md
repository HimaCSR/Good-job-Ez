# 参与开发

本文给要改这个插件的人看。只想用的话看 [README](README.md) 就够了。

---

## 30 秒了解架构

```
定时器 / agent 工具
      ↓
  tools.py            ← 工具层：scan / daily / push / login_status
      ↓
  bbclient.py         ← 抓取层：调 bb-browser 跑 adapter（只读）
      ↓
  bb-browser daemon
      ↓
  你的 Chrome (9222)  ← 复用登录态
      ↓
  matcher.py          ← 打分层：本地确定性规则，0~100 分
      ↓
  storage.py          ← 存储层：SQLite 岗位池
      ↓
  report.py / push.py ← 输出层：Markdown 日报 / QQ 短消息
```

**三条铁律**（改代码时别破坏）：

1. **只读** —— 抓取永远不写操作，投递必须用户明确确认
2. **不烧 LLM** —— 打分是本地确定性规则，别改成调模型
3. **凭证不落盘** —— cookie 值不进配置、不进 SQLite、不进日志、不进 git

---

## 开发环境

### 依赖

| 组件 | 位置 | 说明 |
| --- | --- | --- |
| Python | Hermes 自带 | `python -m unittest` 就能跑，无需装包 |
| Node | Hermes 自带 | bb-browser 需要，**PATH 里的 node 可能是 14（没有 fetch）** |
| bb-browser | `$HERMES_HOME/tools/bb-browser/` | 0.14.2 |
| Chrome | 你自己的 | 开着调试端口 9222 |

第三方依赖（jinja2 / fastapi / pydantic）装在
`src/job_radar/requirements.txt`：

```bash
pip install -r src/job_radar/requirements.txt
```

### ⚠️ 本机 Python ≠ CI Python

| | 版本 | 注解求值 |
| --- | --- | --- |
| 本机开发 | 3.14 | 惰性（`-> List[dict]` 少 import **不报错**） |
| CI 矩阵 | 3.11 / 3.12 / 3.13 | 立即求值（少 import → **NameError，导入即失败**） |

**改完在 3.12 上也跑一遍**：

```bash
/c/Users/19863/AppData/Local/Programs/Python/Python312/python.exe -m unittest discover -s tests
```

这条已经踩过：`storage.py` 用了 `List[dict]` 但没 `from typing import List`，
本机 3.14 全绿，CI 三个版本全红。

### 目录布局（开发时）

```
$HERMES_HOME/plugins/job-radar   ←── junction ──→  <repo>/src/job_radar
```

插件目录是仓库的**目录联接（junction）**，改代码即生效，不用手动同步。

> 如果不是 junction，说明有人在用「运行目录 + 仓库」两份副本。
> 见下面的「切换到 junction 开发模式」。

### 私有数据不在仓库里

| 数据 | 位置 |
| --- | --- |
| 个人画像 | `<plugin-data>/job-radar/profile.yaml` |
| 岗位库 | `<plugin-data>/job-radar/jobs.db` |
| 日报 | `<plugin-data>/job-radar/reports/` |
| 日志 | `<plugin-data>/job-radar/logs/` |
| 私有 adapter | `~/.bb-browser/sites/<site>/` |

`.gitignore` 已经挡住这些，但**别依赖它** —— 新增私有文件时同时更新
`docs/发布前脱敏清单`。

---

## 跑测试

```bash
cd src/job_radar
python -m unittest discover -s tests
```

或者用脚本（会顺带做脱敏扫描）：

```bash
scripts/dev.sh test
```

**测试基线：157 个用例全过。** 提交前必须全绿。

测试分三类，都不需要网络和浏览器：

| 文件 | 测什么 |
| --- | --- |
| `test_matcher.py` | 打分规则（关键词命中、技能覆盖率、城市、薪资解析） |
| `test_push.py` | 50 字拆分、URL 不被切断 |
| `test_login_check.py` | 登录态判定（用构造的 cookie，不碰浏览器） |
| `test_logging_setup.py` | **凭证打码**（最重要的一条防线）+ 懒加载 handler |
| `test_plugin_api.py` | 配置读写、画像读写、路径解析 |
| `test_apply_gate.py` | **三道门真的能挡住**（真实现，不是 mock） |
| `test_mock_provider.py` | mock 层的闸门判定（形状跟真实现一致） |

---

## 加一个新招聘站

这是最常见的扩展。分四步：

### 1. 写 adapter（私有，不进仓库）

adapter 是 bb-browser 的站点脚本，放在 `~/.bb-browser/sites/<site>/`：

```
~/.bb-browser/sites/boss/search.js    ← 列表
~/.bb-browser/sites/boss/detail.js    ← 详情
```

输出**统一词表**，这样上层不用改：

```js
{
  jobs: [{
    job_id: "...",      // 唯一 ID，跨天要稳定
    title: "...",
    company: "...",
    salary: "15-25K",   // 打码也行，但登录后要能看到
    city: "杭州 拱墅",
    experience: "3-5年",
    degree: "本科",
    skills: ["vue", "typescript"],
    url: "https://...",
    description: "完整 JD 文本",
  }]
}
```

### 2. 在 `bbclient.py` 里接上

```python
def run_site(site, *args, timeout=120): ...
```

已经有 `zhaopin/search` 和 `boss/search` 的调用范例。
新站照抄一个分支即可 —— **不需要改这里**，只需要在 `tools.py` 的
`_fetch_site()` 里加一个 `if site == "your-site":` 分支。

### 3. 在 `tools.py` 的 `FIELD_MAP` 里加字段映射

各站字段名不一样（智联叫 `area`、BOSS 叫 `city`），在这里统一。

### 4. 在 `plugin.yaml` 的 `config_schema` 里加站点名

并在 `login_check.py` 的 `SITE_AUTH` 里登记登录凭证名（没有强制登录的站
就写空列表，会显示「需实际抓取验证」）。

### 5. 测

```bash
# 真跑一次
hermes tools call job_radar_scan '{"sites": ["your-site"], "max_jobs": 5}'

# 看日志
tail -f "$LOCALAPPDATA/hermes/plugin-data/job-radar/logs/job-radar.log"
```

---

## 改设置页

设置页有两份，**都是真源码**，要一起改：

| 文件 | 用途 |
| --- | --- |
| `src/job_radar/desktop/plugin.js` | **真正运行的**桌面端 React 设置页 |
| `docs/设置页-demo.html` | 独立预览版（单文件 HTML，可直接双击打开） |

`plugin.js` 是**纯 ESM，未编译**，UI 用 `jsx()` 调用，**不能写 JSX 语法**。
只允许 import `@hermes/plugin-sdk` 和 `react`。

改完后要同步到桌面端副本：

```bash
scripts/dev.sh sync-desktop
```

或者在 Hermes 桌面端 **Settings ▸ Plugins** 点 Rescan。

### 主题配色

**不要硬编码颜色。** 全部用 `--ui-*` 变量，宿主换皮肤插件跟着变。

---

## 加后端接口

后端在 `dashboard/plugin_api.py`，挂在 `/api/plugins/job-radar/`。

规矩：

1. **不用相对导入** —— Hermes 把这个文件当独立模块加载，没有父包。
   用 `_sibling("模块名")` 取兄弟模块（见文件顶部的加载器）
2. **配置读写走 Hermes CLI**，不手写 YAML：
   `hermes config set plugins.entries.job-radar.settings.<key> <value>`
3. 新端点记得在 `tests/test_plugin_api.py` 里加用例

前端调法：`ctx.rest('/路径', { method: 'POST', body: {...} })`

---

## 提交规范

[Conventional Commits](https://www.conventionalcommits.org/)：

```
feat(logging): 新增运行日志
fix(push): 保护 URL 不被切断
docs: 补 ROADMAP
refactor: 抽出站点适配层
chore: 升级依赖
```

### 提交前检查清单

```bash
scripts/dev.sh check
```

会跑：

- [ ] 单元测试全过
- [ ] 脱敏扫描（真实姓名 / 手机号 / 邮箱 / 本机路径 / 真实公司名）
- [ ] `git status` 里没有 `profile.yaml` / `jobs.db` / `*.docx`
- [ ] `hermes plugins doctor <插件目录> --ci` 通过

---

## 切换到 junction 开发模式

需要**先停掉网关**（它锁着插件目录），再执行：

```bash
scripts/dev.sh link
```

脚本会：

1. 把 `$HERMES_HOME/plugins/job-radar` 备份成 `.bak-before-junction`
2. 删掉原目录
3. 建 junction 指向 `<repo>/src/job_radar`

回退：

```bash
scripts/dev.sh unlink
```

> 为什么不默认就是 junction？
> 因为 junction 要求网关重启才能生效（网关 import 插件时锁着目录）。
> 开发时重启网关很烦，所以留了个开关。

---

## 常见坑

| 现象 | 原因 | 怎么办 |
| --- | --- | --- |
| `Cannot find a Chromium-based browser` | PATH 里的 node 是 14，没有 `fetch` | 用 Hermes 自带的 node 绝对路径 |
| BOSS 突然报 code 37 | **连错了浏览器**，不是被封 | `bb.sh status` 确认连的是哪个 Chrome |
| 配置改了没生效 | 手写 YAML 缩进错，整个节点变空 | 用 `hermes config set` |
| 桌面端看不到插件 | 有 marker 的插件默认禁用（安全设计） | Settings ▸ Plugins 里手动启用 |
| 后端端点一直 404 | 缺 `dashboard/manifest.json` | 补上，`api` 字段指向 `plugin_api.py` |
| `ImportError: relative import` | dashboard 层用了相对导入 | 用 `_sibling()` |
| 薪资打码 `**-**元` | 该站没登录 | 先在浏览器登录一次 |
| 本机测试全绿，CI 全红 | 本机 3.14 注解惰性求值，CI 3.11~3.13 立即求值 | 在 3.12 上也跑一遍 |
| `cannot release un-acquired lock` | 懒加载 handler 首次 emit 时父类换了 lock | 见 `logging_setup._ensure_open` 里的修法 |
| 配置读出来是空的 | 存了嵌套字典，被打散成顶层键 | 用扁平键 `apply_zhaopin` |
| 桌面端改完没反应 | 桌面半边是**副本** | `bash scripts/dev.sh sync-desktop`，再 Reload plugins |

---

## 联系方式

问题、想法、PR 都欢迎：
<https://github.com/HimaCSR/Good-job-Ez/issues>

## 开发模式（mock）

三个功能里，**投递三道门已有真实现**（`apply_gate.py`），
另外两个还在用 mock 数据：

| 功能 | 状态 | mock 提供什么 | 真实现要做的事 |
| --- | --- | --- | --- |
| 投递三道门 | ✅ 已实现 | （不再需要） | 动作层：调招聘站真实投递接口 |
| 经历结构化 | ⬜ mock 中 | 两条虚构经历，支持增删改 | 落库 + 接进简历生成 |
| 模板转换 | ⬜ mock 中 | 假的版式参数 | 读 .docx/.pdf/图片并抽版式 |

**mock 开关的三个来源**（优先级从高到低）：

```bash
# 1. 环境变量（临时）
JOB_RADAR_MOCK=1 hermes gateway restart

# 2. 插件配置（推荐，设置页可改，不用重启）
hermes config set plugins.entries.job-radar.settings.mock true

# 3. 代码里显式指定
mock_provider.enabled(force=True)
```

**接口形状跟真实现一致** —— 接真实现时只要把 `mock` 参数关掉，
前端一行都不用改。

**平台接入页**会显示「开发模式」横幅，一眼看到现在跑的是真数据还是假数据，
横幅上还有个「重置」按钮（清掉 mock 的投递计数和令牌）。

**测试**：`tests/test_mock_provider.py` 验 mock 层的闸门判定；
`tests/test_apply_gate.py` 验**真实现**的闸门 ——
两边都要「三道门真的能挡住」，如果闸门做漏了，后面接动作层就来不及了。

### 端到端验证三道门

单测用假 settings 和临时库。要验证「接线对不对」（真配置 + 真库）：

```bash
cd src/job_radar && python scripts/verify_apply_gate.py
```

它会写 config.yaml（开关和上限），**跑完自动恢复原值并清理记录**。
