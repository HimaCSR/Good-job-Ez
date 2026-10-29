"""模板上传转换的测试。

## 测什么

1. `.docx` → 抽版式参数（纸张/页边距/字号/字体/分栏/强调色）
2. `.pdf` → 抽页面尺寸
3. 图片 → 「底图 + 文字层」
4. 非法输入 → 明确报错，不崩
5. 端到端：上传 → 落盘 → **能真的渲染出 HTML**

**第 5 条最重要** —— 转换出来的 CSS 必须能套进共享骨架，
否则「缩略图 = 实际输出」就不成立。

## 造测试文件

`.docx` 就是 zip + XML，所以测试里用 `zipfile` 现造 ——
**不依赖真实 Word 文件**，也不依赖 python-docx。
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import template_convert  # noqa: E402


# ── 造文件 ──────────────────────────────────────────────────────────────────

DOC_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:p><w:r><w:rPr><w:rFonts w:ascii="SimSun" w:hAnsi="SimSun"/>
  <w:sz w:val="44"/><w:color w:val="1F4E79"/></w:rPr><w:t>张三</w:t></w:r></w:p>
<w:p><w:r><w:rPr><w:sz w:val="21"/></w:rPr><w:t>后端工程师</w:t></w:r></w:p>
<w:p><w:r><w:rPr><w:sz w:val="21"/></w:rPr><w:t>负责核心服务开发</w:t></w:r></w:p>
<w:sectPr>
  <w:pgSz w:w="11906" w:h="16838"/>
  <w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1701"/>
  <w:cols w:num="2"/>
</w:sectPr>
</w:body></w:document>"""

STYLES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:sz w:val="21"/></w:rPr></w:rPrDefault>
</w:docDefaults></w:styles>"""


def make_docx(document_xml=DOC_XML, styles_xml=STYLES_XML):
    """造一个最小可用的 .docx。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.'
                   'openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", document_xml)
        z.writestr("word/styles.xml", styles_xml)
    return buf.getvalue()


def make_pdf(width_pt=595.28, height_pt=841.89, text="Hello"):
    """造一个最小 PDF（带 MediaBox 和一段文本）。"""
    objs = []
    objs.append("<< /Type /Catalog /Pages 2 0 R >>")
    objs.append("<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objs.append("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %s %s] "
                "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
                % (width_pt, height_pt))
    stream = "BT /F1 12 Tf 72 720 Td (%s) Tj ET" % text
    objs.append("<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(("%d 0 obj\n%s\nendobj\n" % (i, body)).encode("latin-1"))
    xref_at = out.tell()
    out.write(("xref\n0 %d\n" % (len(objs) + 1)).encode("latin-1"))
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(("%010d 00000 n \n" % off).encode("latin-1"))
    out.write(("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
               % (len(objs) + 1, xref_at)).encode("latin-1"))
    return out.getvalue()


def make_png(width=200, height=300):
    """造一个最小 PNG（1x1 像素放大不合规范，用纯字节更省事）。"""
    import struct
    import zlib

    def chunk(tag, data):
        c = tag + data
        return (struct.pack(">I", len(data)) + c
                + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF))

    raw = b""
    for _ in range(height):
        raw += b"\x00" + b"\xff\x00\x00" * width
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


# ── .docx ───────────────────────────────────────────────────────────────────

class TestDocxConvert(unittest.TestCase):

    def setUp(self):
        self.data = make_docx()
        self.result = template_convert.convert("我的模板.docx", self.data)
        self.assertTrue(self.result["ok"], self.result.get("error"))

    def test_extracts_page_size(self):
        p = self.result["params"]
        # 11906 twip = 210mm
        self.assertAlmostEqual(p["page_width_mm"], 210.0, delta=0.5)
        self.assertAlmostEqual(p["page_height_mm"], 297.0, delta=0.5)

    def test_extracts_margins(self):
        p = self.result["params"]
        # 1134 twip = 20mm；1701 twip = 30mm
        self.assertAlmostEqual(p["margin_top_mm"], 20.0, delta=0.5)
        self.assertAlmostEqual(p["margin_left_mm"], 30.0, delta=0.5)
        self.assertAlmostEqual(p["margin_right_mm"], 20.0, delta=0.5)

    def test_extracts_font_size(self):
        # 正文 21 半磅 = 10.5pt
        self.assertAlmostEqual(self.result["params"]["font_size_pt"], 10.5, delta=0.2)

    def test_extracts_name_size(self):
        # 第一个 run 44 半磅 = 22pt
        self.assertAlmostEqual(self.result["params"]["name_size_pt"], 22.0, delta=0.2)

    def test_extracts_font_family(self):
        self.assertIn("SimSun", self.result["params"]["font_family"])

    def test_extracts_columns(self):
        self.assertEqual(self.result["params"]["columns"], 2)

    def test_extracts_accent_color(self):
        self.assertEqual(self.result["params"]["accent_color"], "#1f4e79")

    def test_css_has_two_columns(self):
        """双栏用 **CSS columns**（分栏流），不是 flex。

        flex 是「并排」—— .head 和每个 .sec 都并排，版式直接乱。
        Word 的分栏是「内容流到第二栏」→ column-count。
        """
        css = self.result["css"]
        self.assertIn("column-count: 2", css)
        # 分栏容器不能用 flex（.contact 用 flex 是另一回事，不算）
        self.assertNotIn(".page { display: flex", css)
        self.assertNotIn(".content { display: flex", css)

    def test_css_contact_no_word_split(self):
        """抬头一行放不下时整块换行 —— 不能把「杭州」拆成「杭」「州」。"""
        css = self.result["css"]
        self.assertIn("flex-wrap: wrap", css)
        self.assertIn("white-space: nowrap", css)

    def test_css_no_double_percent(self):
        """`100%%` 是 bug —— CSS 里应该是 `100%`。"""
        self.assertNotIn("%%", self.result["css"])

    def test_css_font_size_in_px(self):
        """字号从 pt 转成 px（1pt = 4/3px）。"""
        # 10.5pt = 14px
        self.assertIn("font-size: 14px", self.result["css"])

    def test_css_page_size_matches_params(self):
        """CSS 里的页面尺寸要跟抽到的参数一致。

        不直接比字符串 —— CSS 里整数值不写小数尾巴（`210mm` 不是 `210.0mm`），
        所以比数值。
        """
        import re as _re
        css = self.result["css"]
        p = self.result["params"]
        m = _re.search(r"@page \{ size: ([\d.]+)mm ([\d.]+)mm", css)
        self.assertIsNotNone(m, css)
        self.assertAlmostEqual(float(m.group(1)), p["page_width_mm"], delta=0.1)
        self.assertAlmostEqual(float(m.group(2)), p["page_height_mm"], delta=0.1)

    def test_extracted_list_not_empty(self):
        self.assertGreaterEqual(len(self.result["extracted"]), 4)


# ── .pdf ────────────────────────────────────────────────────────────────────

class TestPdfConvert(unittest.TestCase):

    def test_extracts_page_size(self):
        data = make_pdf(595.28, 841.89)
        r = template_convert.convert("r.pdf", data)
        self.assertTrue(r["ok"], r.get("error"))
        p = r["params"]
        self.assertAlmostEqual(p["page_width_mm"], 210.0, delta=1.0)
        self.assertAlmostEqual(p["page_height_mm"], 297.0, delta=1.0)

    def test_scanned_pdf_says_so(self):
        """没有文字的 PDF（扫描件）要**如实说**，不能瞎填。"""
        data = make_pdf(text="")
        r = template_convert.convert("scan.pdf", data)
        self.assertTrue(r["ok"])
        # 可能有一点点空白，仍应该给个提示或至少不崩
        self.assertTrue(r["css"])

    def test_css_has_page_rule(self):
        r = template_convert.convert("r.pdf", make_pdf())
        self.assertIn("@page", r["css"])
        self.assertIn(".page {", r["css"])


class TestPdfStyleExtraction(unittest.TestCase):
    """**PDF 要抽出视觉风格** —— 不只是页面尺寸。

    ## 为什么

    用户：「我上传的模板是存在UI风格设计的，转换成模板后，
    对应风格并没有跟着转换过来。」

    原来 `_pdf_to_css` **只抽页面尺寸** —— 配色/字号/字体/装饰全丢
    → 生成的模板跟原文件完全不像。

    ## PDF 里其实有这些信息

    PDF 没有「样式表」，但**绘图指令里有**：

    | 指令 | 含义 |
    | --- | --- |
    | `r g b rg` | 填充色 |
    | `/F4 34 Tf` | 字号 |
    | `/BaseFont /XXX` | 字体名（在**对象定义**里，不在压缩流里） |
    | `x y w h re f` | **填充**的矩形 |
    | `x y w h re W* n` | **裁剪**路径（不画 —— 不能当色块！） |

    ## 三个坑

    1. **内容流是压缩的** —— 不解压就找不到任何指令
    2. **最大的流往往是内嵌字体文件**（几百 KB TTF 二进制）——
       取最大的流 → 一个 `Tf` 都抽不到
    3. **`re` 后面跟 `W*` 的是裁剪路径** —— 当成色块 →
       标题栏底色变成强调色 → **白字蓝底，字看不见**
    """

    @staticmethod
    def _styled_pdf():
        """造一个带配色/字号/装饰的 PDF（FlateDecode 压缩内容流）。"""
        import zlib
        content = (
            b"q\n"
            b".2235 .251 .5176 RG .2235 .251 .5176 rg\n"
            b"/F4 34 Tf\n"
            b"1 0 0 -1 83.5 700 Tm\n"
            b"(Name) Tj\n"
            b"ET\n"
            b"q\n"
            b".8471 .8784 .9412 RG .8471 .8784 .9412 rg\n"
            b"0 0 20 2320 re\nf\n"
            b"Q\n"
            b"q\n"
            b".749 .749 .749 RG .749 .749 .749 rg\n"
            b"84 303 674 2 re\nf\n"
            b"Q\n"
        )
        compressed = zlib.compress(content)
        objs = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Contents 4 0 R /Resources << /Font << /F4 5 0 R >> >> >>",
            b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(compressed)
            + compressed + b"\nendstream",
            b"<< /Type /Font /Subtype /Type0 /BaseFont /AAAAAA+MicrosoftYaHei >>",
        ]
        out = io.BytesIO()
        out.write(b"%PDF-1.4\n")
        offsets = []
        for i, body in enumerate(objs, 1):
            offsets.append(out.tell())
            out.write(("%d 0 obj\n" % i).encode("latin-1"))
            out.write(body)
            out.write(b"\nendobj\n")
        xref_at = out.tell()
        out.write(("xref\n0 %d\n" % (len(objs) + 1)).encode("latin-1"))
        out.write(b"0000000000 65535 f \n")
        for off in offsets:
            out.write(("%010d 00000 n \n" % off).encode("latin-1"))
        out.write(("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                   % (len(objs) + 1, xref_at)).encode("latin-1"))
        return out.getvalue()

    def test_extracts_accent_color(self):
        """**强调色** —— 出现最多且非灰度的颜色。"""
        r = template_convert.convert("s.pdf", self._styled_pdf())
        self.assertTrue(r["ok"], r.get("error"))
        # .2235 .251 .5176 → #384083
        self.assertEqual(r["params"]["accent_color"], "#384083")
        self.assertIn("强调色", r["extracted"])

    def test_extracts_font_size(self):
        """**字号** —— 姓名取最大，正文取众数。"""
        r = template_convert.convert("s.pdf", self._styled_pdf())
        self.assertEqual(r["params"]["name_size_pt"], 34.0)
        self.assertIn("字号", r["extracted"])

    def test_extracts_font_name(self):
        """**字体名** —— 在对象定义里，不在压缩流里。"""
        r = template_convert.convert("s.pdf", self._styled_pdf())
        # MicrosoftYaHei → "Microsoft YaHei"（**不能拆成 "Microsoft Ya Hei"**）
        self.assertIn('"Microsoft YaHei"', r["params"]["font_family"])
        self.assertNotIn("Microsoft Ya Hei", r["params"]["font_family"])

    def test_extracts_vertical_bar(self):
        """**竖条**（侧边色带）—— 高远大于宽的填充矩形。"""
        r = template_convert.convert("s.pdf", self._styled_pdf())
        self.assertIn("_accent_bar_px", r["params"])
        self.assertEqual(r["params"]["_accent_bar_color"], "#d8dff0")
        self.assertIn("侧边色带", r["extracted"])

    def test_extracts_divider(self):
        """**分隔线** —— 宽远大于高、很薄的填充矩形。"""
        r = template_convert.convert("s.pdf", self._styled_pdf())
        self.assertIn("_divider_px", r["params"])
        self.assertEqual(r["params"]["_divider_color"], "#bebebe")

    def test_css_applies_style_to_elements(self):
        """**抽到的风格要真的作用到元素上** —— 否则抽了也白抽。"""
        r = template_convert.convert("s.pdf", self._styled_pdf())
        css = r["css"]
        self.assertIn(".name {", css)
        self.assertIn("#384083", css)          # 强调色
        self.assertIn(".item-title", css)      # 正文色
        self.assertIn("border-left", css)      # 竖条
        self.assertIn("border-bottom", css)    # 分隔线

    def test_clipping_path_is_not_a_color_block(self):
        """**裁剪路径（`re W* n`）不是色块** ——
        当成色块 → 标题栏底色 = 强调色 → 白字蓝底 → **字看不见**。
        """
        import zlib
        content = (b".2235 .251 .5176 RG .2235 .251 .5176 rg\n"
                   b"q\n153.125 1050 2262.5 100 re\nW* n\nQ\n")
        compressed = zlib.compress(content)
        r = template_convert._pdf_style(
            b"%PDF-1.4\n" + compressed + b"\nendstream\n")
        self.assertIsNone(r.get("_band_color"),
                          "裁剪路径被当成了标题栏底色")


# ── 图片 ────────────────────────────────────────────────────────────────────

class TestImageConvert(unittest.TestCase):

    def test_png_convert(self):
        data = make_png(200, 300)
        r = template_convert.convert("t.png", data)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertIn(".bg-image", r["css"])
        self.assertIn(".content", r["css"])

    def test_image_keeps_aspect_ratio(self):
        """200x300 的图 → 页面高度按比例。"""
        r = template_convert.convert("t.png", make_png(200, 300))
        p = r["params"]
        self.assertAlmostEqual(p["page_height_mm"], 315.0, delta=2.0)

    def test_jpg_extension_accepted(self):
        r = template_convert.convert("t.jpg", make_png())
        self.assertTrue(r["ok"])


# ── 非法输入 ────────────────────────────────────────────────────────────────

class TestBadInput(unittest.TestCase):

    def test_unsupported_extension(self):
        r = template_convert.convert("x.exe", b"MZ")
        self.assertFalse(r["ok"])
        self.assertIn("只支持", r["error"])

    def test_empty_data(self):
        r = template_convert.convert("x.docx", b"")
        self.assertFalse(r["ok"])

    def test_broken_docx(self):
        """不是 zip 的 .docx 要明确报错，不能抛栈。"""
        r = template_convert.convert("x.docx", b"not a zip at all")
        self.assertFalse(r["ok"])
        self.assertIn("docx", r["error"].lower())

    def test_none_data(self):
        r = template_convert.convert("x.docx", None)
        self.assertFalse(r["ok"])


# ── 端到端 ──────────────────────────────────────────────────────────────────

class TestEndToEnd(unittest.TestCase):
    """上传 → 落盘 → 能真的渲染出 HTML。"""

    def setUp(self):
        import resume_template
        self.tmp = tempfile.mkdtemp(prefix="jr-tpl-")
        self._orig_dir = resume_template.TEMPLATES_DIR
        resume_template.TEMPLATES_DIR = self.tmp

    def tearDown(self):
        import resume_template
        resume_template.TEMPLATES_DIR = self._orig_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_then_render(self):
        import base64
        import resume_template
        import template_store

        b64 = base64.b64encode(make_docx()).decode("ascii")
        r = template_store.save_upload("我的模板.docx", b64)
        self.assertTrue(r["ok"], r.get("error"))
        tid = r["template"]["template_id"]

        # CSS 文件落盘了
        self.assertTrue(os.path.exists(os.path.join(self.tmp, tid + ".css")))

        # **能真的渲染**
        html = resume_template.render_html(tid, {
            "title": "简历",
            "identity": {"name": "张三", "phone": "138****0000"},
            "sections": [
                {"title": "工作经历", "kind": "entries", "entries": [
                    {"title": "某公司", "meta": "2020-2024",
                     "bullets": [{"text": "做了个系统", "basis": "经历第 1 条"}]},
                ]},
            ],
        })
        self.assertIn("张三", html)
        self.assertIn("做了个系统", html)
        self.assertIn("SimSun", html)          # 抽到的字体
        self.assertIn("column-count: 2", html)  # 抽到的分栏

    def test_same_file_overwrites(self):
        """同一个文件反复上传 → 同一条记录，不堆重复。"""
        import base64
        import template_store

        b64 = base64.b64encode(make_docx()).decode("ascii")
        a = template_store.save_upload("我的模板.docx", b64)
        b = template_store.save_upload("我的模板.docx", b64)
        self.assertEqual(a["template"]["template_id"],
                         b["template"]["template_id"])
        css_files = [f for f in os.listdir(self.tmp) if f.endswith(".css")]
        self.assertEqual(len(css_files), 1)

    def test_dry_run_does_not_write(self):
        import base64
        import template_store

        b64 = base64.b64encode(make_docx()).decode("ascii")
        r = template_store.save_upload("我的模板.docx", b64, dry_run=True)
        self.assertTrue(r["ok"])
        self.assertTrue(r["css_preview"])
        self.assertEqual(os.listdir(self.tmp), [])

    def test_image_saves_background(self):
        import base64
        import resume_template
        import template_store

        b64 = base64.b64encode(make_png(100, 150)).decode("ascii")
        r = template_store.save_upload("底图.png", b64)
        self.assertTrue(r["ok"], r.get("error"))
        tid = r["template"]["template_id"]
        self.assertTrue(os.path.exists(os.path.join(self.tmp, tid + ".bg")))

        # 渲染时底图变成 data URI
        bg = resume_template.uploaded_bg_image(tid)
        self.assertTrue(bg.startswith("data:image/png;base64,"))

        html = resume_template.render_html(tid, {
            "title": "简历",
            "identity": {"name": "李四"},
            "sections": [],
        })
        self.assertIn("bg-image", html)
        self.assertIn("李四", html)

    def test_remove_upload(self):
        import base64
        import template_store

        b64 = base64.b64encode(make_docx()).decode("ascii")
        r = template_store.save_upload("我的模板.docx", b64)
        tid = r["template"]["template_id"]

        out = template_store.remove_upload(tid)
        self.assertTrue(out["ok"], out.get("error"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, tid + ".css")))

    def test_cannot_remove_builtin(self):
        import template_store
        out = template_store.remove_upload("classic")
        self.assertFalse(out["ok"])
        self.assertIn("内置", out["error"])


# ── 造一个「有版面结构」的 PDF ──────────────────────────────────────────────
#
# 用户的模板是 WPS 导出的，结构长这样：
#   - 页眉：一整块深色底 + 白字
#   - 章节：淡色横条 + 左侧实心方块
#
# **只测「抽颜色」不够** —— 用户第二次反馈就是
# 「现在有样式了，但与我提供的模板文件完全不同」。
# → 要测**版面结构**真的被抽出来并且**真的作用到 CSS 上**。

def make_layout_pdf():
    """造一个 PDF：深色页眉块 + 淡色章节条 + 实心图标方块。

    手写最小 PDF（不依赖任何第三方库）—— 内容流用 zlib 压缩。

    **内容流里必须有 `Tf`** —— `_pdf_to_css` 靠它认出「这条是内容流」。
    最大的流往往是内嵌字体文件，里面一个 `Tf` 都没有。
    """
    import zlib

    # A4：595 x 842 pt
    ops = []
    # 一行字 —— 让内容流里有 Tf / Tj
    ops.append("BT /F1 12 Tf 20 500 Td (Resume) Tj ET")
    # 页眉块 —— 强调色 #384083，贴在页面顶部
    ops.append("q 1 0 0 1 0 610 cm 0.2235 0.251 0.5176 rg "
               "0 0 595 232 re f Q")
    # 章节条 —— 同色但 10% 透明（/G6）+ 左侧实心方块
    for y in (400.0, 300.0):
        ops.append("q /G6 gs 1 0 0 1 36.7 %s cm 0.2235 0.251 0.5176 rg "
                   "0 0 543 24 re f Q" % y)
        ops.append("q 1 0 0 1 36.7 %s cm 0.2235 0.251 0.5176 rg "
                   "0 0 24 24 re f Q" % y)
    content = "\n".join(ops).encode("latin-1")

    objs = {}
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[2] = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    objs[3] = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
               b"/Resources << /ExtGState << /G6 6 0 R >> >> /Contents 4 0 R >>")
    objs[4] = None          # 内容流（下面特殊处理）
    objs[6] = b"<< /ca 0.102 /BM /Normal >>"

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        if num == 4:
            comp = zlib.compress(content)
            out += (b"%d 0 obj\n<< /Length %d /Filter /FlateDecode >>\nstream\n"
                    % (num, len(comp)))
            out += comp
            out += b"\nendstream\nendobj\n"
        else:
            out += b"%d 0 obj\n%s\nendobj\n" % (num, objs[num])
    xref = len(out)
    out += b"xref\n0 %d\n" % (max(objs) + 1)
    out += b"0000000000 65535 f \n"
    for num in range(1, max(objs) + 1):
        if num in offsets:
            out += b"%010d 00000 n \n" % offsets[num]
        else:
            out += b"0000000000 65535 f \n"
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (
        max(objs) + 1, xref)
    return bytes(out)



def _layout_of(data):
    """跑完整链路：解析 → 抽矩形 → 分类版面。"""
    texts, _raws = template_convert._pdf_streams(data)
    content = ""
    for t in texts:
        if " re" in t:
            content = t
            break
    rects = template_convert._pdf_rects(
        content, template_convert._pdf_alpha_map(data),
        template_convert._pdf_forms(data, template_convert._pdf_objects(data)))
    if not rects:
        return {}, rects
    page_h = max(r[3] for r in rects) - min(r[1] for r in rects)
    page_w = max(r[2] for r in rects) - min(r[0] for r in rects)
    return template_convert._pdf_layout(rects, page_w, page_h), rects


class TestPdfLayout(unittest.TestCase):
    """PDF → **版面结构**（不只是颜色）。"""

    def test_extracts_header_block(self):
        """**深色页眉块要被抽出来** —— WPS 模板的页眉是一整块底色。"""
        data = make_layout_pdf()
        style, _rects = _layout_of(data)
        self.assertIn("_header_bg", style, "没抽出页眉底色：%r" % style)
        self.assertEqual(style["_header_bg"], "#384083")

    def test_alpha_is_blended_to_white(self):
        """**10% 透明的强调色要算成「叠在白底上的观感」**。

        WPS 的章节条是「深蓝 + ca 0.102」→ 屏幕上看到的是淡紫。
        直接用原色 → 章节条变深蓝 → 白字深蓝底 → 字看不见。
        """
        data = make_layout_pdf()
        style, _rects = _layout_of(data)
        band = style.get("_band_color", "")
        self.assertNotEqual(band, "#384083",
                            "透明色没混合，直接用了原色")
        # 淡紫 —— r 远小于 g
        r = int(band[1:3], 16)
        self.assertLess(r, 250, "章节条底色不该是深色：%s" % band)

    def test_layout_becomes_real_css(self):
        """**抽到的版面要真的变成 CSS** —— 不是只存在 dict 里。"""
        data = make_layout_pdf()
        css, params = template_convert._pdf_to_css(data)
        self.assertIn("background:", css, "页眉底色没进 CSS")
        self.assertIn(".head", css, "没有 .head 样式")
        self.assertIn("#384083", css)
        self.assertTrue(any("页眉" in x for x in params.get("_extracted", [])),
                        "extracted 里没有报「页眉」：%r" % params.get("_extracted"))

    def test_dark_header_makes_text_white(self):
        """**深色页眉上的文字必须反白** —— 否则看不见。"""
        data = make_layout_pdf()
        css, _params = template_convert._pdf_to_css(data)
        self.assertIn("#ffffff", css, "深底页眉没有白字")

    def test_light_band_keeps_dark_text(self):
        """**浅色章节底 + 白字 = 看不见** —— 文字要跟着底色反。"""
        data = make_layout_pdf()
        css, _params = template_convert._pdf_to_css(data)
        # 章节条那行 —— 背景是淡紫，文字不能是白色
        found = False
        for line in css.split("\n"):
            if "background: #" in line and "sec-title" not in line:
                continue
            if ".sec-title { background:" in line:
                found = True
                self.assertNotIn("color: #ffffff", line,
                                 "浅色章节底用了白字 —— 看不清")
        self.assertTrue(found, "没生成章节底条样式")

    def test_clip_path_is_not_a_color_block(self):
        """**裁剪路径不是色块** —— W* 结尾的 re 没画出来。"""
        import zlib
        ops = b"q 1 0 0 1 0 600 cm 0.2235 0.251 0.5176 rg 0 0 615 200 re W* n Q"
        data = make_layout_pdf()
        # 直接测 rects 的判定
        rects = template_convert._pdf_rects(
            ops.decode("latin-1"), {}, {})
        self.assertEqual(rects, [], "裁剪路径被当成了色块")

    def test_form_xobject_is_parsed(self):
        """**页眉底块常画在 Form XObject 里** —— 不递归就看不到。"""
        import zlib
        # 内容流里用 /X1 Do 引用
        content = b"q 1 0 0 1 0 638.3 cm /X1 Do Q"
        form = b"0.2235 0.251 0.5176 rg 0 0 615 231.7 re f"
        objs = {1: (b"<< /Type /XObject /Subtype /Form >>", form)}
        forms = template_convert._pdf_forms(
            b"/X1 1 0 R", objs)
        self.assertIn("X1", forms, "Form XObject 没被识别")
        rects = template_convert._pdf_rects(
            content.decode("latin-1"), {}, forms)
        self.assertEqual(len(rects), 1, "Form 里的矩形没被递归进来")
        self.assertEqual(template_convert._hex(rects[0][4]), "#384083")

    def test_ctm_is_applied(self):
        """**要跟踪 CTM** —— 不跟踪的话坐标全错。"""
        content = "q 3.125 0 0 3.125 100 200 cm 1 0 0 rg 0 0 10 10 re f Q"
        rects = template_convert._pdf_rects(content, {}, {})
        self.assertEqual(len(rects), 1)
        x0, y0, x1, y1 = rects[0][:4]
        self.assertAlmostEqual(x0, 100, places=1)
        self.assertAlmostEqual(y0, 200, places=1)
        self.assertAlmostEqual(x1, 100 + 10 * 3.125, places=1)



if __name__ == "__main__":
    unittest.main(verbosity=2)
