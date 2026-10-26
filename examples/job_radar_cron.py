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
             "push", "login_check", "browser_cookies", "logging_setup", "tools"]
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
                out.setdefault(last, []).append(line.lstrip()[2:].strip())
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
                out[key] = raw
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

    # 1) 抓取
    try:
        scan_raw = tools.scan({})
        scan = __import__("json").loads(scan_raw)
    except Exception as exc:
        print("招聘雷达：抓取失败 %s" % exc)
        return

    if scan.get("error"):
        print("招聘雷达：抓取失败 %s" % scan["error"])
        return

    # 2) 生成推送消息（只推没推过的）
    try:
        push_raw = tools.push({"max_jobs": 3, "only_new": True})
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
    for m in msgs:
        print(m)


if __name__ == "__main__":
    main()
