"""桌面端 plugin.js 的静态检查 —— 抓那些**运行时才炸**的问题。

## 为什么需要这个

桌面端 plugin.js 是**纯 ESM 未编译**的，加载进 Electron 渲染进程。
这类文件有两类问题在代码层完全看不出来：

1. **Hook 顺序错误**（React error #310）
   组件里 `React.useState` 写在条件 `return` 之后 →
   首次渲染 loading 时提前 return，Hook 没执行 →
   数据到了再渲染，Hook 数量变了 → **React 崩溃**。
   整个路由挂掉，页面停在崩溃前的残留 DOM 上。
   本机就踩过：设置页只剩「个人信息」，标签栏不出现。

2. **用了 app CSS 里不存在的 Tailwind 类**
   app 的 CSS 是 JIT 生成的，只含 app 自己用过的类。
   插件写 app 没用过的类 → 样式静默失效。
   （这个由 `scripts/check-desktop-css.mjs` 检查，不在 Python 这边。）

**代价**：第 1 类问题会让整个插件页面不可用，而且日志里只有
一行 minified 的 `React error #310`，很难定位到哪个组件。

## 怎么查 Hook 顺序

React 的规则：**每次渲染，Hook 的调用顺序和数量必须一致**。

静态检查的做法：
- 找出每个组件函数体里的所有 Hook 调用行
- 找出所有提前 `return` 的行
- **如果某个 Hook 在提前 return 之后** → 危险

但只看「return 之后」不够 —— 还要看**分支覆盖**：
比如 `if (a) return X; useState(); if (b) return Y; useEffect();`
两条路径的 Hook 数不同 → 也炸。

所以这里做的是**保守检查**：任何 Hook 出现在任何提前 return 之后，
都报出来（宁可多报也不要漏）。

## 用法

    cd src/job_radar && python -m unittest tests.test_desktop_js.py
"""

import os
import re
import sys
import unittest

PLUGIN_JS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "desktop", "plugin.js")

# Hook 名字（SDK 的 + React 的）
HOOK_RE = re.compile(
    r"\b(useState|useEffect|useMemo|useCallback|useRef|useContext|"
    r"useReducer|useLayoutEffect|useQuery|useMutation|useQueryClient)\s*\(")

# 提前 return：`return xxx`（排除 return 后面接表达式的写法）
RETURN_RE = re.compile(r"^\s*return\s+\S")


def _read():
    with open(PLUGIN_JS, encoding="utf-8") as fh:
        return fh.read()


def _functions(src):
    """切出每个顶层函数：(名字, 函数体)。"""
    out = []
    for m in re.finditer(r"^function (\w+)\(([^)]*)\)\s*\{", src, re.M):
        name = m.group(1)
        start = m.end()
        nxt = src.find("\nfunction ", start)
        out.append((name, src[start:nxt if nxt > 0 else start + 20000]))
    return out


class TestDesktopJsExists(unittest.TestCase):

    def test_plugin_js_present(self):
        self.assertTrue(os.path.exists(PLUGIN_JS),
                        "找不到 %s" % PLUGIN_JS)

    def test_not_empty(self):
        self.assertGreater(len(_read()), 10000)


class TestHookOrder(unittest.TestCase):
    """Hook 顺序 —— React error #310 的静态检查。"""

    def setUp(self):
        self.src = _read()
        self.funcs = _functions(self.src)

    def test_found_functions(self):
        self.assertGreater(len(self.funcs), 10,
                           "没解析到函数，检查脚本本身是不是坏了")

    def test_no_hook_after_early_return(self):
        """**任何 Hook 都不能出现在提前 return 之后。**

        否则首次渲染（loading）和后续渲染的 Hook 数量不同 →
        React error #310 → 整个页面崩。
        """
        bad = []
        for name, body in self.funcs:
            lines = body.split("\n")
            ret_at = None
            for i, line in enumerate(lines):
                stripped = line.strip()
                # 注释行不算
                if stripped.startswith("//") or stripped.startswith("*"):
                    continue
                if ret_at is None and RETURN_RE.match(line):
                    # 「Hook 包装函数」的开头 `return useQuery({...})`
                    # 是这个函数本身就是 Hook，不是组件里的提前 return。
                    # 判据：函数体里第一个非空行就是它。
                    if HOOK_RE.search(line) and not any(
                            l.strip() for l in lines[:i]):
                        continue
                    ret_at = i
                if ret_at is not None:
                    m = HOOK_RE.search(line)
                    if m:
                        # 注释里的不算
                        stripped = line.strip()
                        if stripped.startswith("//") or stripped.startswith("*"):
                            continue
                        bad.append((name, i + 1, m.group(1), stripped[:60]))
        if bad:
            msg = "\n".join(
                "  %s 第 %d 行: %s（%s）" % (n, ln, txt, hook)
                for n, ln, hook, txt in bad)
            self.fail(
                "这些 Hook 排在提前 return 之后 —— 会触发 React error #310：\n"
                + msg)

    def test_use_state_before_conditional_return(self):
        """重点盯 SettingsPage —— 之前就是这里出的问题。"""
        src = self.src
        m = re.search(r"function SettingsPage\([^)]*\)\s*\{(.*?)\n\}\n",
                      src, re.S)
        self.assertIsNotNone(m, "找不到 SettingsPage")
        body = m.group(1)
        lines = body.split("\n")
        hook_idx = None
        ret_idx = None
        for i, line in enumerate(lines):
            if hook_idx is None and "React.useState" in line:
                hook_idx = i
            if ret_idx is None and RETURN_RE.match(line):
                ret_idx = i
        self.assertIsNotNone(hook_idx, "SettingsPage 里没有 useState")
        self.assertIsNotNone(ret_idx, "SettingsPage 里没有提前 return")
        self.assertLess(
            hook_idx, ret_idx,
            "SettingsPage 的 useState 排在提前 return 之后 —— "
            "这正是「标签栏不出现」的根因")


class TestNoHardcodedColors(unittest.TestCase):
    """不许硬编码颜色 —— 主题变量约定。"""

    def test_no_hex_colors(self):
        """不许硬编码颜色（除了 SITE_META 里的招聘站品牌色）。

        品牌色是「这个站是红色的」这种标识信息，不是主题色 ——
        放在 SITE_META 里做数据，不进 className。
        """
        src = _read()
        code = "\n".join(l for l in src.split("\n")
                         if not l.strip().startswith("//"))
        # 去掉 SITE_META 那一段（品牌色登记表）
        code = re.sub(r"const SITE_META = \{[\s\S]*?\n\}", "", code)
        hits = re.findall(r"#[0-9a-fA-F]{3,8}\b", code)
        self.assertEqual(hits, [], "有硬编码颜色: %s" % hits[:5])

    def test_uses_theme_variables(self):
        src = _read()
        self.assertIn("--ui-", src, "应该用 --ui-* 主题变量")


class TestNoRelativeImports(unittest.TestCase):
    """只允许三个 specifier —— app 的加载器只认这三个。"""

    ALLOWED = {"@hermes/plugin-sdk", "react", "react/jsx-runtime"}

    def test_imports_allowed(self):
        src = _read()
        bad = []
        for m in re.finditer(r"from\s+['\"]([^'\"]+)['\"]", src):
            spec = m.group(1)
            if spec not in self.ALLOWED:
                bad.append(spec)
        self.assertEqual(bad, [], "有不允许的 import: %s" % bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
