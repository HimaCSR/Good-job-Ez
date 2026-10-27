# AGENTS.md

给在这个仓库里干活的 AI（Claude Code、Cursor、Hermes 等）。

**先读 [`docs/新对话接手指南.md`](docs/新对话接手指南.md)** —— 里面有：
用户的硬性要求、当前进度、下一步、动手前必须知道的坑、常用命令。

在 Hermes 里还有本项目的 skill `job-radar`（`skill_view(name='job-radar')`），
踩坑记录更细。

---

## 本机环境变量

需要本机路径时用这些变量，别把绝对路径写进仓库：

| 变量 | 是什么 |
| --- | --- |
| `HERMES_HOME` | Hermes 主目录（插件、配置、日志、数据都在这下面） |
| `LOCALAPPDATA` | Windows 本机数据目录 |

## 30 秒上手

```bash
# 测试（运行版和仓库版都要跑 —— 仓库是真相源，运行版是 junction）
cd "$LOCALAPPDATA/hermes/plugins/job-radar" && python -m unittest discover -s tests
cd "<repo>/src/job_radar" && python -m unittest discover -s tests

# 提交前检查（测试 + 脱敏 + 仓库卫生，一条命令）
bash scripts/dev.sh check
```

## 结构

```
src/job_radar/            agent 半边（Python，跑在 Hermes 网关里）
  ├── plugin.yaml         元数据 + 配置 schema
  ├── tools.py            8 个工具的实现
  ├── matcher.py          本地打分（职位名30+技能30+城市20+薪资20）
  ├── storage.py          SQLite：jobs / runs / resumes / resume_templates
  ├── resume_*.py         模板库 / 匹配优化 / PDF 导出与档案
  ├── mock_provider.py    三个缺口的假数据（接口形状与真实现一致）
  ├── dashboard/          设置页后端 API（FastAPI）
  ├── desktop/plugin.js   桌面半边（React 设置页）
  └── tests/              123 个单元测试
```

## 三条铁律

1. **不编造经历** —— 简历生成的每条 bullet 必须能追溯到用户写过的原文
2. **投递要用户点头** —— 不可逆动作，必须过三道门（开关 → 令牌 → 上限）
3. **仓库里不能有隐私** —— 真实姓名/手机/邮箱/本机路径/真实公司名/cookie 值

其余细则见接手指南。

## 改完要做的

```bash
bash scripts/dev.sh check        # 测试 + 脱敏 + 卫生
bash scripts/dev.sh sync-desktop # 改了 desktop/plugin.js 才需要
git commit && git push
```

**agent 半边是 junction**，改完即生效。
**桌面半边是副本**，改完要 `sync-desktop`，
而且桌面 app 还要重载（⌘K → Reload desktop plugins）才生效。
