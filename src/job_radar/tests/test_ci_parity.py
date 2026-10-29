"""「本机能过、CI 挂掉」这类问题的回归测试。

## 背景

CI 的 Python 矩阵是 **3.11 / 3.12 / 3.13**，本机是 **3.14**（Hermes 自带一堆库）。
本机全绿 ≠ CI 全绿 —— 本项目在这上面栽过两次。

## 本轮抓到的两个

### ① 图片尺寸靠 PIL → CI 上没装

`template_convert._image_to_css` 用 `from PIL import Image` 拿图片尺寸。
**PIL 在本机 3.14 有、CI 的 3.11~3.13 没有** →

    test_image_keeps_aspect_ratio
    AssertionError: 297 != 315.0 within 2.0 delta

297 是 **A4 默认页高** —— 说明**读尺寸失败走了兜底**。

修法：**标准库读图片头**（PNG 的 IHDR / JPEG 的 SOF / GIF / WebP），
不引入 PIL（项目铁律：零额外依赖）。

### ② 测试 import Hermes 的 `plugins` 包 → CI 上不存在

`from plugins import plugin_storage` —— 本机有（Hermes 自带），
CI 上没有 → `ModuleNotFoundError`。

修法：**测试自己造一个假模块**塞进 `sys.modules`，不依赖 Hermes 环境。

## 铁律

**任何单测都不能依赖「本机恰好有、CI 没有」的东西。**
本机 3.14 是**最宽松**的环境 —— 恰恰最容易掩盖问题。
"""

import os
import struct
import sys
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _png(w, h):
    """现造一个 PNG（标准库 zip/zlib 够用，不依赖 PIL）。"""

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"")) + chunk(b"IEND", b""))


class TestImageSizeWithoutPIL(unittest.TestCase):
    """图片尺寸**不靠 PIL** —— 标准库读文件头。"""

    def test_png_size(self):
        from template_convert import _image_size
        self.assertEqual(_image_size(_png(200, 300)), (200, 300))
        self.assertEqual(_image_size(_png(1, 1)), (1, 1))
        self.assertEqual(_image_size(_png(1920, 1080)), (1920, 1080))

    def test_garbage_returns_none(self):
        """读不出来就返回 None —— **不要瞎猜一个尺寸**。"""
        from template_convert import _image_size
        self.assertEqual(_image_size(b""), (None, None))
        self.assertEqual(_image_size(b"notanimage"), (None, None))

    def test_module_does_not_import_pil_at_top(self):
        """**顶层不 import PIL** —— 只在需要时才 import。

        顶层 import 会让「没装 PIL 的环境」**整个模块导入失败**，
        比「某个功能降级」严重得多。

        **只看 import 行** —— 文档字符串里提到 PIL 不算。
        """
        import template_convert
        src = open(template_convert.__file__, encoding="utf-8").read()
        # 顶层 import 区（第一个 def/class 之前），但只看 import 语句
        head = src.split("\ndef ")[0]
        for line in head.split("\n"):
            st = line.strip()
            if st.startswith(("import ", "from ")) and "PIL" in st:
                self.fail("template_convert 顶层 import 了 PIL：%s" % st)

    def test_convert_uses_stdlib_size(self):
        """**转换时真的用上了标准库读的尺寸**（不是 A4 兜底）。"""
        from template_convert import convert
        out = convert("a.png", _png(200, 300))
        # convert 返回 dict（参数 + css）
        css = out.get("css", "") if isinstance(out, dict) else str(out)
        params = out.get("params", {}) if isinstance(out, dict) else {}
        # 200x300 的图 → 页面宽 210mm 时，高 = 210 × 300/200 = **315mm**
        # （不是 A4 的 297mm）
        self.assertIn("315mm", css,
                      "页高不是按图比例算的 —— 说明尺寸没读到")
        self.assertNotIn("297mm", css,
                         "还是走的 A4 默认页高 —— 说明尺寸没读到")
        if params:
            self.assertNotEqual(params.get("page_height_mm"), 297,
                                "还是走的 A4 默认页高 —— 说明尺寸没读到")


class TestNoHermesDependency(unittest.TestCase):
    """**单测不能依赖 Hermes 环境** —— CI 上没有 Hermes。"""

    def test_new_user_journey_makes_fake_plugins(self):
        """新用户那条测试自己造 `plugins.plugin_storage`。"""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "test_new_user_journey.py")
        src = open(path, encoding="utf-8").read()
        self.assertIn("types.ModuleType(\"plugins\")", src,
                      "测试没有造假的 plugins 模块 —— CI 上会 ModuleNotFoundError")

    def test_tests_do_not_import_hermes_packages(self):
        """**扫所有测试文件** —— 不许直接 import Hermes 的包。"""
        here = os.path.dirname(os.path.abspath(__file__))
        bad = []
        for name in sorted(os.listdir(here)):
            if not name.startswith("test_") or not name.endswith(".py"):
                continue
            src = open(os.path.join(here, name), encoding="utf-8").read()
            # 只看 import 行（注释里的不算）
            for line in src.split("\n"):
                st = line.strip()
                if not st.startswith(("import ", "from ")):
                    continue
                if "plugins" in st and "plugin_storage" in st:
                    # 造模块的方式（types.ModuleType）不算依赖
                    if "ModuleType" in st:
                        continue
                    bad.append("%s: %s" % (name, st))
        self.assertEqual(bad, [],
                         "这些测试直接 import 了 Hermes 的包（CI 上不存在）：%s"
                         % bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
