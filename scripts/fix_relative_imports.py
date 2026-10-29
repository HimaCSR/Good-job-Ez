"""给**函数体内**的相对 import 加 fallback。

## 为什么需要

插件的模块之间用 `from . import report` 这种相对 import。
**在包里跑没问题**，但**脱离包**（单测、独立脚本、某些定时任务路径）
就会炸：

    ImportError: attempted relative import with no known parent package

本机踩过：`tools.daily()` 里 `from . import report` ——
单测调它直接返回「生成日报失败: attempted relative import…」。

## 规则（很重要，别改错）

- **只改函数体内的**（有缩进的）——
  顶层 import 保持原样，`__init__.py` 更是必须用相对 import（那是包入口）
- **已经有 try/except 包裹的跳过** —— 不重复套
- 不动 `from .xxx import yyy` 的顶层版本

## 用法

    python scripts/fix_relative_imports.py
"""

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(REPO, "src", "job_radar")

# 函数体内的 `from . import x` / `from .x import y`
RE_FROM_DOT = re.compile(r"^([ \t]+)from \. import ([A-Za-z_][\w, ]*)$", re.M)
RE_FROM_MOD = re.compile(r"^([ \t]+)from \.(\w+) import ([A-Za-z_][\w, ]*)$", re.M)


def _already_wrapped(lines, idx):
    """这一行是不是已经在 try 里？"""
    for j in range(idx - 1, max(-1, idx - 4), -1):
        line = lines[j].strip()
        if line.startswith("except ImportError"):
            return True
        if line.startswith("try:"):
            return True
        if line and not line.startswith(("except", "try", "from", "import")):
            return False
    return False


def fix(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    lines = src.split("\n")
    out = []
    changed = 0

    for i, line in enumerate(lines):
        m = RE_FROM_DOT.match(line) or RE_FROM_MOD.match(line)
        if not m:
            out.append(line)
            continue
        if _already_wrapped(lines, i):
            out.append(line)
            continue

        indent = m.group(1)
        if m.re is RE_FROM_DOT:
            names = m.group(2)
            rel = "from . import %s" % names
            plain = "import %s" % names
        else:
            mod, names = m.group(2), m.group(3)
            rel = "from .%s import %s" % (mod, names)
            plain = "from %s import %s" % (mod, names)

        out.append("%stry:" % indent)
        out.append("%s    %s" % (indent, rel))
        out.append("%sexcept ImportError:          # 脱离包单独导入时（单测）" % indent)
        out.append("%s    %s" % (indent, plain))
        changed += 1

    new = "\n".join(out)
    if new != src:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new)
    return changed


def main():
    total = 0
    for name in sorted(os.listdir(PKG)):
        if not name.endswith(".py") or name == "__init__.py":
            continue
        path = os.path.join(PKG, name)
        try:
            n = fix(path)
            if n:
                print("  %-22s %d 处" % (name, n))
                total += n
        except Exception as exc:
            print("  ! %s: %s" % (name, exc))
    print("共改 %d 处" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
