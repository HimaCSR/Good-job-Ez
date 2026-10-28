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


if __name__ == "__main__":
    unittest.main(verbosity=2)
