#!/usr/bin/env python3
"""招聘岗位雷达 —— 定时抓取并输出待推送的消息。

由 Hermes cron 以 `--no-agent --script` 方式调用：
**完全不经过 LLM**，脚本 stdout 直接投递到 QQ。
省 token、行为确定、不会因为模型胡说而推错内容。

用法（手动跑）：
    python job_radar_cron.py

输出：
    每条消息一行（岗位名 · 城市 / 链接）。空输出 = 静默（不推送）。

设计约束：
- **只读** —— 只抓岗位，绝不投递简历
- **每条 ≤50 字符**（URL 除外）—— 用户硬性约定
- 同一个岗位不重复推 —— 用 jobs.pushed_at 标记
- 出错时输出可读的提示，不要抛栈（栈没人看）
"""

import os
import sys

PLUGIN_DIR = os.environ.get(
    "JOB_RADAR_PLUGIN_DIR",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", "plugins", "job-radar"))

if PLUGIN_DIR and PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)


def _load():
    """按真包方式加载插件模块（跟 dashboard 层一致）。"""
    import importlib.util
    import types

    pkg = types.ModuleType("job_radar")
    pkg.__path__ = [PLUGIN_DIR]
    pkg.__package__ = "job_radar"
    sys.modules["job_radar"] = pkg

    names = ["config", "schemas", "matcher", "storage", "bbclient", "report",
             "push", "login_check", "browser_cookies", "logging_setup", "tools",
             # **调度 + 方向分类** —— 自定义抓取/推送时间、按方向分组
             "schedule", "direction_catalog", "direction_evaluate"]
    for name in names:
        path = os.path.join(PLUGIN_DIR, name + ".py")
        if not os.path.exists(path):
            continue
        key = "job_radar." + name
        if key in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(key, path)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:
            pass
    return sys.modules


def _unquote(text):
    """**剥掉 YAML 的引号** —— 值本身是对的，但表示层可能带引号。

    ## 为什么必须剥

    `hermes config set` 写列表时，YAML 会给某些元素加引号
    （`06:20` 在 YAML 里像时间戳 → 加引号；`11:20` 不加）：

    ```
    scan_times:
      - 06:20
      - '11:20'
    ```

    **不剥的话** cron 脚本读到 `"'11:20'"` → `parse_hhmm()` 失败
    → **那个时间点永远不会触发**（静默失效，用户完全看不出来）。

    → 标量值和列表项**都要剥**。
    """
    s = str(text or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1].strip()
    return s


def _read_settings():
    """从 Hermes 配置读设置（走 CLI，不手写 YAML）。"""
    import subprocess

    home = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", "hermes-agent")
    cli = os.path.join(home, ".hermes", "bin", "hermes.exe")
    if not os.path.exists(cli):
        cli = os.path.join(home, ".hermes", "bin", "hermes")
    if not os.path.exists(cli):
        return {}
    try:
        proc = subprocess.run(
            [cli, "config", "get", "plugins.entries.job-radar.settings"],
            capture_output=True, text=True, timeout=60, cwd=home)
    except Exception:
        return {}
    if proc.returncode != 0:
        return {}

    out, last = {}, None
    for line in (proc.stdout or "").splitlines():
        if not line.strip():
            continue
        if line.lstrip().startswith("- "):
            if last:
                # **列表项也要剥引号** —— 见 `_unquote` 的说明
                out.setdefault(last, []).append(
                    _unquote(line.lstrip()[2:]))
            continue
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        key, raw = key.strip(), raw.strip()
        last = key
        if raw == "":
            out[key] = []
        elif raw in ("true", "false"):
            out[key] = raw == "true"
        else:
            try:
                out[key] = int(raw)
            except ValueError:
                out[key] = _unquote(raw)
    return out


def main():
    mods = _load()
    tools = mods.get("job_radar.tools")
    config = mods.get("job_radar.config")
    if tools is None or config is None:
        print("招聘雷达：插件模块没加载上，跳过")
        return

    # 注入配置（独立进程里没有 ctx）
    settings = _read_settings()

    class _Ctx:
        def __init__(self, d):
            self._d = d

        def get_config(self, key, default=None):
            return self._d.get(key, default)

    try:
        config.set_context(_Ctx(settings))
    except Exception:
        pass

    # ── **用户自定义抓取/推送时间** ──
    #
    # cron 每 10 分钟醒一次 → 每次问「现在该抓吗？该推吗？」
    #
    # - `scan_times` —— 该抓的时间点（默认 09:00 / 13:00 / 17:00 / 21:00）
    # - `push_times` —— 该推的时间点（默认 09:30 / 17:30）
    #
    # **都不命中 → 静默退出**（stdout 为空 = 不推送）。
    #
    # **同一时间点只干一次** —— 09:00 那档，cron 会在 09:00/09:10/09:20
    # 各醒一次 → 不去重的话抓取跑 3 遍 → 浪费请求、可能撞风控。
    #
    # 用法：抓取和推送**分开两个 cron 任务**，各自带 `--mode scan|push`。
    # 不带 `--mode` → 两个都按时间判断（老行为兼容）。
    import sys as _sys
    import datetime as _dt

    mode = "both"
    if "--mode" in _sys.argv:
        try:
            mode = _sys.argv[_sys.argv.index("--mode") + 1].strip().lower()
        except (IndexError, ValueError):
            mode = "both"

    # **从已加载的模块里取** —— 比 import 稳
    # （独立进程里 `job_radar` 是手工造的 module 对象，
    #   `from job_radar import schedule` 有时拿不到）
    _sched = mods.get("job_radar.schedule")

    def _should(kind, times, key):
        """该干吗？_sched 不可用 → 总是干（老行为）。"""
        if not times or _sched is None:
            return True
        try:
            return _sched.should_run(times=times, state_key=key)
        except Exception:
            return True

    want_scan = mode in ("scan", "both")
    want_push = mode in ("push", "both")

    def _as_list(v):
        """配置里的时间点 —— 列表或逗号分隔字符串都认。"""
        if not v:
            return []
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        if isinstance(v, (list, tuple)):
            return [str(x).strip() for x in v if str(x).strip()]
        return []

    # ── **时间点** ──
    #
    # ## 「没配过」vs「显式清空」
    #
    # `hermes config get` **不输出空列表的键** ——
    # 所以「键不在」有两种可能：
    #
    # | 情况 | 含义 | 怎么办 |
    # | --- | --- | --- |
    # | 键不在 + 没有 `*_disabled` 标记 | **用户没配过** | 用默认档 |
    # | 键不在 + 有 `*_disabled` 标记 | 用户**显式清空** | 尊重用户，不跑 |
    #
    # 不加标记 → 用户清空后又被默认档填回去 → **清空没用**。
    #
    # `scan_times_disabled` / `push_times_disabled` 就是那个标记
    # （前端保存时如果用户把列表清空，就把它设成 true）。
    DEFAULT_SCAN = ["09:00", "13:00", "17:00", "21:00"]
    DEFAULT_PUSH = ["09:30", "17:30"]

    def _slots(key, disabled_key, default):
        if settings.get(disabled_key):
            return []                       # **用户显式关了** → 不跑
        v = _as_list(settings.get(key))
        return v if v else list(default)  # **没配过** → 用默认档

    scan_times = _slots("scan_times", "scan_times_disabled", DEFAULT_SCAN)
    push_times = _slots("push_times", "push_times_disabled", DEFAULT_PUSH)

    do_scan = want_scan and _should("scan", scan_times, "cron_scan_slot")
    do_push = want_push and _should("push", push_times, "cron_push_slot")

    if not do_scan and not do_push:
        # 静默 —— 不打扰用户
        return

    # 1) 抓取
    if do_scan:
        try:
            scan_raw = tools.scan({})
            scan = __import__("json").loads(scan_raw)
        except Exception as exc:
            print("招聘雷达：抓取失败 %s" % exc)
            return

        if scan.get("error"):
            print("招聘雷达：抓取失败 %s" % scan["error"])
            return

    # 2) 生成推送消息（**单个方向**里评分最高的 N 条）
    if not do_push:
        return

    try:
        push_raw = tools.push({"max_jobs": int(settings.get("push_max") or 5),
                               "only_new": True})
        push = __import__("json").loads(push_raw)
    except Exception as exc:
        print("招聘雷达：生成推送失败 %s" % exc)
        return

    if push.get("error"):
        print("招聘雷达：生成推送失败 %s" % push["error"])
        return

    msgs = push.get("messages") or []
    if not msgs:
        # 空输出 = 静默，不打扰用户
        return

    # 3) 输出 —— cron 会原样投递
    #
    # **先报方向** —— 用户知道今天推的是哪一类
    direction = push.get("direction") or ""
    if direction:
        print("【%s】" % direction)
    for m in msgs:
        print(m)


if __name__ == "__main__":
    main()
