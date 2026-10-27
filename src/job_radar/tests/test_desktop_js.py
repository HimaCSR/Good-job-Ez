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


class TestNoUndefinedIdentifiers(unittest.TestCase):
    """**不许引用未定义的标识符** —— 渲染时直接 ReferenceError 崩掉。

    SDK 文档里点名的坑：
    > A `jsx` element renders nothing / throws `ReferenceError`.
    > An identifier used in a `jsx()` call isn't imported.

    本机踩过：`ResumeView` 里用了 `uploadTplRef` / `converting` /
    `onPickTemplate`，**三个都没定义**（代码从 demo 转过来时抄漏了）。
    切到「用户简历」标签就崩 —— 整个页面被错误边界接管，
    日志里只有一行 `ReferenceError: converting is not defined`。

    ## 检查方式（**文件级**）

    收集整个文件里**所有被定义过的名字**：
    - `const/let/var X` / `function X`
    - 解构出来的名字（`const { a, b } = ...`）
    - 函数参数
    - import 进来的名字

    然后收集所有**被引用**的名字，减去上面那批。
    剩下的，如果又不是 JS 内置/SDK 导出 → 就是未定义。

    **为什么用文件级而不是函数级**：函数级需要精确的作用域分析，
    而这个文件是 JSX 编译产物（`jsx(...)` 调用而非 JSX 语法），
    函数级的边界很容易切错（切错就会误报或漏报）。
    文件级会漏掉「跨函数误用」，但那种情况极罕见。

    **字符串字面量要先剥掉** —— 否则 'AI' / 'PDF' 这种内容
    会被当成变量引用。
    """

    # SDK 导出的 + JS 内置 + 本文件里定义的全局 helper
    GLOBALS = {
        # SDK
        "Button", "Input", "Textarea", "Badge", "GlyphSpinner",
        "EmptyState", "ErrorState", "cn", "host", "useQuery", "useMutation",
        "useQueryClient", "SIDEBAR_NAV_AREA", "ROUTES_AREA", "PANES_AREA",
        "TITLEBAR_AREAS", "STATUSBAR_AREAS",
        # 本文件的 helper（在别的函数里定义）
        "Segmented", "Panel", "Field", "ChipEditor", "TemplateCard",
        "ResumeRow", "JobCard", "ApplyResumeDialog", "ResumeOptimizeDialog",
        "ExperienceEditor", "ExperienceForm", "PhotoUpload", "LoginPanel",
        "ApplySwitchPanel", "PushSettingsPanel", "ResumeImportPanel",
        "ProfileView", "RecommendView", "ResumeView", "PlatformView",
        "ReportView", "SettingsView", "FilterFields", "SettingsPage",
        "SubPage", "ViewBody", "useConfig", "useJobs", "useRuns", "useLogin",
        "useMock", "useLogs", "useApplySwitches", "SITE_META",
        "APPLY_SITE_META", "BROWSER_LOGIN_SITES", "VIEWS",
        # JS 内置
        "React", "Fragment", "jsx", "jsxs", "console", "JSON", "Object",
        "Array", "String", "Number", "Boolean", "Math", "Date", "Error",
        "Promise", "setTimeout", "clearTimeout", "setInterval",
        "clearInterval", "fetch", "FileReader", "btoa", "atob",
        "encodeURIComponent", "decodeURIComponent", "Intl", "Map", "Set",
        "WeakMap", "Symbol", "parseInt", "parseFloat", "isNaN", "undefined",
        "null", "true", "false", "window", "document", "Blob", "URL",
        "FormData", "performance", "navigator", "location", "structuredClone",
        "crypto", "TextEncoder", "TextDecoder", "Uint8Array", "alert",
        # JS 关键字（不是变量，但正则会把它们扫出来）
        "var", "let", "const", "function", "return", "if", "else", "for",
        "while", "do", "switch", "case", "break", "continue", "new",
        "typeof", "instanceof", "in", "of", "this", "class", "extends",
        "super", "try", "catch", "finally", "throw", "delete", "void",
        "yield", "await", "async", "static", "get", "set", "default",
        "export", "import", "from", "as", "with", "debugger",
        # 其它内置全局
        "globalThis", "Infinity", "NaN", "WeakSet", "Reflect", "Proxy",
        "queueMicrotask", "requestAnimationFrame", "cancelAnimationFrame",
        # 对象方法名（不是变量引用）
        "register", "registerSettingsPage", "unregister",
    }

    def _strip_strings(self, src):
        """剥掉字符串字面量**和注释**（保留长度，方便按位置取上下文）。

        注释里出现的英文单词（register / switch / try …）如果不清掉，
        会被当成变量引用 —— 全是噪音。
        """
        blank = lambda mm: " " * len(mm.group(0))
        # 先剥注释（避免注释里的引号打乱字符串配对）
        out = re.sub(r"//[^\n]*", blank, src)
        out = re.sub(r"/\*[\s\S]*?\*/", blank, out)
        # 再剥字符串
        out = re.sub(r"'(?:[^'\\\n]|\\.)*'", blank, out)
        out = re.sub(r'"(?:[^"\\\n]|\\.)*"', blank, out)
        out = re.sub(r"`(?:[^`\\]|\\.)*`", blank, out)
        return out

    def _defined_names(self, src):
        names = set()
        # const / let / var / function 声明
        for m in re.finditer(
                r"\b(?:const|let|var|function)\s+([A-Za-z_$][\w$]*)", src):
            names.add(m.group(1))
        # 解构：const { a, b } = ...  /  const [a, b] = ...
        for m in re.finditer(r"\{([^}]*)\}\s*=", src):
            for part in m.group(1).split(","):
                part = part.strip().split(":")[0].split("=")[0].strip()
                if re.match(r"^[A-Za-z_$][\w$]*$", part):
                    names.add(part)
        for m in re.finditer(r"\[([^\]]*)\]\s*=", src):
            for part in m.group(1).split(","):
                part = part.strip().split("=")[0].strip()
                if re.match(r"^[A-Za-z_$][\w$]*$", part):
                    names.add(part)
        # 函数参数：function f(a, { b, c }) / const f = (a) =>
        for m in re.finditer(r"\(([^()]*)\)", src):
            raw = m.group(1)
            # 整体去掉一层 {} / []，再按逗号拆 —— 否则第一个 part 会带着
            # '{'、最后一个带着 '}'，两边都匹配不上名字的正则。
            raw = raw.strip()
            if raw.startswith("{") and raw.endswith("}"):
                raw = raw[1:-1]
            elif raw.startswith("[") and raw.endswith("]"):
                raw = raw[1:-1]
            for part in raw.split(","):
                part = part.strip()
                if not part:
                    continue
                # 去掉默认值和类型标注
                part = part.split("=")[0].split(":")[0].strip()
                if not part:
                    continue
                if re.match(r"^[A-Za-z_$][\w$]*$", part):
                    names.add(part)
                else:
                    # 嵌套解构 { a: { b } }
                    for sub in re.findall(r"[A-Za-z_$][\w$]*", part):
                        names.add(sub)
        # import 进来的
        for m in re.finditer(r"import\s*\{([^}]*)\}", src):
            for part in m.group(1).split(","):
                part = part.strip().split(" as ")[-1].strip()
                if re.match(r"^[A-Za-z_$][\w$]*$", part):
                    names.add(part)
        return names

    def test_no_undefined_identifiers(self):
        src = _read()
        code = self._strip_strings(src)
        defined = self._defined_names(src)
        bad = []
        for m in re.finditer(r"(?<![.\w$])([A-Za-z_$][\w$]*)", code):
            ident = m.group(1)
            if ident in defined or ident in self.GLOBALS:
                continue
            # 对象键：`{ ref: x }` —— 键后面紧跟 ':'
            tail = code[m.end():m.end()+3]
            if re.match(r"^\s*:(?!:)", tail):
                continue
            # 赋值目标：`x = ...`
            if re.match(r"^\s*=(?!=)", tail):
                continue
            # 函数调用/属性前的大写词（组件名）—— GLOBALS 已覆盖大部分
            bad.append((ident, m.start()))
        if bad:
            seen = {}
            for ident, pos in bad:
                seen.setdefault(ident, pos)
            msg = "\n".join(
                "  %s  ——  上下文: %s" % (
                    ident,
                    re.sub(r"\s+", " ", code[max(0, pos - 50):pos + 30]))
                for ident, pos in sorted(seen.items()))
            self.fail(
                "这些标识符在整个文件里从没被定义过"
                "（渲染时会 ReferenceError 崩掉）：\n" + msg)


class TestNoNestedScroll(unittest.TestCase):
    """插件根容器**不许**自己滚动 —— 滚动是 app 的事。

    ## 为什么要查

    app 的容器链路：

        OverlayMain       flex min-h-0 flex-1 flex-col overflow-hidden   (高度确定)
        └─ section        min-h-0 overflow-hidden
           └─ div        h-full min-h-0 overflow-y-auto                 ← 真正的滚动容器

    插件根容器如果再写 `h-full overflow-y-auto`，就变成**嵌套滚动**：
    内层高度被压成外层的高度（flex + h-full），
    内容超出被内层裁掉，而内层因为内容被 flex 压缩过
    **scrollHeight == clientHeight → 不出现滚动条** →
    面板内容彻底消失，用户完全看不到，也没法滚过去。

    实测（用 app 的真实 CSS 复现）：
      修复前  滚动容器 scrollHeight=752 == clientHeight=752（不能滚）
              插件 root 只有 672px（内容被裁，无滚动条）
      修复后  滚动容器 scrollHeight=844 > 752（能滚）
              插件 root 764px（内容完整）

    ## 规则

    插件的**根容器**（SettingsPage / SubPage 这类页面根）
    不能同时带 `h-full` 和 `overflow-y-auto`。
    """

    def test_page_roots_do_not_scroll(self):
        src = _read()
        # 找出所有「页面根容器」的 className —— 带 max-w-3xl 的那种
        bad = []
        for m in re.finditer(r"className:\s*'([^']*max-w-3xl[^']*)'", src):
            cls = m.group(1)
            has_h_full = 'h-full' in cls.split()
            has_scroll = 'overflow-y-auto' in cls.split() or 'overflow-auto' in cls.split()
            if has_h_full and has_scroll:
                line = src[:m.start()].count('\n') + 1
                bad.append((line, cls))
        if bad:
            msg = "\n".join("  第 %d 行: %s" % (ln, c) for ln, c in bad)
            self.fail(
                "页面根容器不要同时设 h-full 和 overflow-y-auto ——\n"
                "app 的 SettingsContent 已经是滚动容器，"
                "再套一层会变成嵌套滚动，内容被裁且没有滚动条。\n"
                + msg)


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
