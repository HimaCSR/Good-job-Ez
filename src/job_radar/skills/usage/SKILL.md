---
name: usage
description: "Use when the user asks about job hunting, new positions, or the daily job digest."
---

# job-radar 使用说明

## 这个插件做什么

定时抓招聘网站岗位 → 按用户的个人画像算匹配度 → 生成日报 → 推送到聊天窗口。

**只读**：不投简历、不联系招聘方、不改账号设置。

## 五个工具

| 工具 | 用途 |
| --- | --- |
| `job_radar_scan` | 抓取 + 打分 + 入库，返回高分岗位 |
| `job_radar_push` | 从岗位池生成待推送的消息序列（≤50 字/条），返回 `messages` 数组 |
| `job_radar_daily` | 生成 Markdown 日报，返回文件路径 |
| `job_radar_list` | 列出本地岗位池（按匹配度倒序） |
| `job_radar_mark` | 标记岗位：interested / applied / ignored |

## 推送规则（重要）

用户的硬性约定：**任何聊天窗单条消息不超过 50 字符**，超出必须按句子拆成多条依次发。

推岗位时：

1. **不要粘贴日报全文或岗位描述全文** —— 只给摘要 + 日报文件路径。
2. 每条岗位摘要控制在 50 字内，例如：

```
🔔 前端开发工程师 · 三维方向
某公司 · 上海徐汇 · 匹配度 88
职位名命中：前端；技能覆盖 5/7
```

3. 一条消息装不下就拆成多条，依次发送。
4. 岗位链接单独放一条，不要挤在摘要里。

## 配置在哪

- **关键词 / 城市 / 分数线 / 启用哪些站**：`plugins.entries.job-radar.settings`
  （用 `hermes config set plugins.entries.job-radar.settings.keywords '["前端"]'`）
- **个人画像（技能、城市、期望薪资）**：插件目录下的 `profile.yaml`
  只有用户自己改，AI 不要写它。

## 站点现状

- `zhaopin`（智联招聘）：**可用**，DOM 抓取，JD 全文能拿到；未登录时薪资被遮罩。
- `boss`（BOSS直聘）：**可能被风控** —— 接口返回 `code 37「您的环境存在异常」`，
  且页面自己发的请求也一样，属于账号/IP 被标记，不是脚本问题。
  遇到这个错误就告诉用户「BOSS 触发了风控，需要你在浏览器里手动搜一次」，
  不要尝试绕过。

## 失败时怎么办

- 报 `code 37` → BOSS 风控，请用户在浏览器里手动操作一次
- 报 401/403/请先登录 → 请用户去对应网站登录
- 报超时 → daemon 可能没连上，跑 `bb-browser daemon status` 检查
- 抓到 0 条 → 关键词太窄或城市代码不对，智联城市代码 538=杭州、489=全国

## 排障：网关加载的是旧版插件代码（重要）

网关在**启动时**把插件代码导入进程内。改了插件源码后，磁盘上是新的、进程里仍是旧的，
于是出现「源码明明有 `job_radar_push`，工具列表里却没有」这类症状。判据：看网关日志

```
grep -n "job-radar 已注册" $LOCALAPPDATA/hermes/logs/gateway.log
```

- `已注册：4 个工具` → 进程里是旧代码（当前版本是 **5 个**）
- `已注册：5 个工具` → 已是新代码

热重载（不用重启网关，cron 回合里也能做）：

```bash
W="$LOCALAPPDATA/hermes/installs/<env>/environments/<env>/workspace"
PYTHONPATH="$W/workspace" "$W/venv/Scripts/python.exe" -c "
from pathlib import Path
from gateway.control_socket import reload_gateway_plugins
print(reload_gateway_plugins(Path(r'$LOCALAPPDATA/hermes')))
"
```

返回 `{'reloaded': True, ...}` 即成功。注意：重载只让**新会话**拿到新工具；
当前 cron 回合的工具表是启动时冻结的，本回合用不了，得等下一回合。

## 排障：WinError 193（%1 不是有效的 Win32 应用程序）

Windows 不能直接 `CreateProcess` 执行 `.sh`。旧版 `bbclient.py` 直接跑 `bb.sh` 就会报这个。
新版 `bbclient.py` 改成走 Git for Windows 的 bash：

```
C:\Program Files\Git\bin\bash.exe  bb.sh site zhaopin/search <关键词> --city 653 --json
```

如果又看到 193，先确认 `bbclient.py` 里 `_cmd()` 是否还在用 bash 包裹。
手动验证抓取通路（绕过插件，直接调适配器）：

```bash
"C:/Program Files/Git/bin/bash.exe" \
  "$LOCALAPPDATA/hermes/tools/bb-browser/bb.sh" site zhaopin/search 前端 --city 653 --json
```

## 排障：cron 里发多条消息

- cron 的**最终回复**会自动投递到 `deliver` 目标，QQ/Telegram 适配器**不会**按换行把一条回复拆成多条。
  所以「每条消息一条独立消息」，靠在最终回复里换行达不到 —— 那仍是 1 条长消息。
- `hermes send` 在 cron 回合里会被去重拦截：
  `{"success": true, "skipped": true, "reason": "cron_auto_delivery_duplicate_target"}`。
  Hermes 的原话是「把要给用户看的内容放进最终回复」。
- 想真正逐条投递，只能用**另一个** target（例如同时发到飞书），或把 job 的 `deliver` 换成别的平台。
- 因此：默认把 `job_radar_push` 的 `messages` 原样按行放进最终回复，一行一条；
  并**如实告知**用户这是 N 行的一条消息，而不是 N 条独立消息。

## 排障：push 把英文单词切坏

`split_for_qq` 硬切时可能落进 ASCII 单词中间（`javascript` → `javas` + `cript`）。
断点顺序应为：句末标点 → 词内分隔符 → 回退到 ASCII 单词起点 → 硬切。
改完跑 `python -m unittest test_push -v`（插件 `tests/` 目录）确认 11 个用例仍全过。
