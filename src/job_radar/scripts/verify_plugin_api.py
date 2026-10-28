"""插件 API 后端的真实验证 —— 加载、模块注册、热重载。

## 测什么

1. `plugin_api.py` 能正常加载（不炸）
2. 每个 `_sibling("X")` 用到的模块**都真的能取到**（不是 None）
3. `.md` 简历能解析（**用插件实际加载的那个模块**，不是直接 import）
4. **热重载真的生效** —— 改源码后，同一个进程里拿到新代码

## 为什么第 4 条重要

**Python 模块一旦 import 就固定了。** 本机踩过：
加了 `.md` 支持，源文件改对了，但插件 API 进程是 16:11 起的，
它 import 的是 16:11 的版本 —— 用户看到「不支持的格式：.md」，
而我看代码完全正确。

光看源码永远看不出来 —— 得在**同一个进程里**验证。

用法：
    python scripts/verify_plugin_api.py
"""

import importlib.util
import os
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(HERE)
sys.path.insert(0, PLUGIN_DIR)

OK = "  ✔"
BAD = "  ✘"
fails = []


def check(label, cond, detail=""):
    global fails
    if cond:
        print(OK, label, detail)
    else:
        print(BAD, label, detail)
        fails.append(label)


def _load_api():
    """按 Hermes 的方式加载插件 API。"""
    if "job_radar" not in sys.modules:
        pkg = types.ModuleType("job_radar")
        pkg.__path__ = [PLUGIN_DIR]
        pkg.__package__ = "job_radar"
        sys.modules["job_radar"] = pkg
    path = os.path.join(PLUGIN_DIR, "dashboard", "plugin_api.py")
    spec = importlib.util.spec_from_file_location("plugin_api_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    print("=" * 62)
    print("插件 API 后端 —— 真实加载验证")
    print("=" * 62)

    # **显式开热重载** ——
    # 生产环境靠「插件目录是软链/junction」自动开，
    # 但这个脚本跑在仓库目录（真实目录）里，判据是 False。
    os.environ["JOB_RADAR_HOT_RELOAD"] = "1"

    api = _load_api()
    check("plugin_api.py 加载成功", True)
    check("热重载开关生效", api._dev_hot_reload())

    # ① 每个用到的模块都取得到
    import re
    src = open(os.path.join(PLUGIN_DIR, "dashboard", "plugin_api.py"),
               encoding="utf-8").read()
    used = sorted(set(re.findall(r'_sibling\(\s*"(\w+)"\s*\)', src)))
    missing = []
    for name in used:
        try:
            mod = api._sibling(name)
            if mod is None:
                missing.append(name)
        except Exception as exc:      # noqa: BLE001
            missing.append("%s(%s)" % (name, exc))
    check("所有 _sibling 模块都取得到", not missing,
          "用了 %d 个，缺: %s" % (len(used), missing))

    # ② 模板上传的模块在（这个之前漏注册过）
    for name in ("template_convert", "template_store"):
        try:
            api._sibling(name)
            check("模块 %s 可用" % name, True)
        except Exception as exc:      # noqa: BLE001
            check("模块 %s 可用" % name, False, str(exc))

    # ③ .md 简历能解析（用插件实际加载的模块）
    ri = api._sibling("resume_import")
    md = """# 张三的简历

**姓名**：张三
**电话**：138****0000
**邮箱**：zhangsan@example.com
**最高学历**：本科
**毕业院校**：某某大学
**专业**：软件工程

## 专业技能

- Python
- Go
- Kubernetes

## 工作经历

### 某某科技有限公司 | 高级后端工程师 | 2023.04 - 至今

- 负责核心服务架构设计
- 主导数据库分库分表改造

## 期望城市

- 杭州
- 上海
"""
    result = ri.parse_resume("r.md", md.encode("utf-8"))
    check(".md 解析返回 ok", result.get("ok"), result.get("note", ""))
    d = result.get("draft") or {}
    check(".md 解析出姓名", d.get("identity", {}).get("name") == "张三",
          repr(d.get("identity", {}).get("name")))
    check(".md 解析出城市", "杭州" in (d.get("cities") or []),
          str(d.get("cities")))
    check(".md 解析出经历", len(d.get("experiences") or []) == 1,
          "%d 段" % len(d.get("experiences") or []))
    check(".md 解析出技能", "Python" in (d.get("skills") or []),
          str(d.get("skills")))

    # ④ 热重载真的生效吗
    #
    # 改一个兄弟模块的源码，再取一次 —— 同一个进程里应该拿到新代码。
    probe_name = "hot_reload_probe"
    probe_path = os.path.join(PLUGIN_DIR, probe_name + ".py")
    created = not os.path.exists(probe_path)
    try:
        with open(probe_path, "w", encoding="utf-8") as fh:
            fh.write("VALUE = 1\n")
        api._SIBLING_MODULES[probe_name] = None
        api._SIBLING_MTIMES[probe_name] = 0.0

        first = api._sibling(probe_name)
        check("热重载：首次能取到模块", first is not None
              and getattr(first, "VALUE", None) == 1,
              "VALUE=%s" % getattr(first, "VALUE", None))

        time.sleep(0.02)
        with open(probe_path, "w", encoding="utf-8") as fh:
            fh.write("VALUE = 2\n")
        os.utime(probe_path, (time.time() + 2, time.time() + 2))

        second = api._sibling(probe_name)
        check("热重载：源码改了能拿到新值",
              getattr(second, "VALUE", None) == 2,
              "VALUE=%s" % getattr(second, "VALUE", None))
    finally:
        api._SIBLING_MODULES.pop(probe_name, None)
        api._SIBLING_MTIMES.pop(probe_name, None)
        sys.modules.pop("job_radar." + probe_name, None)
        if created and os.path.exists(probe_path):
            os.remove(probe_path)

    # ⑤ 加载摘要（打日志的那个函数）能跑
    try:
        api._log_load_summary()
        check("加载摘要能跑", True)
    except Exception as exc:      # noqa: BLE001
        check("加载摘要能跑", False, str(exc))

    print("=" * 62)
    if fails:
        print("失败 %d 项：%s" % (len(fails), "、".join(fails)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
