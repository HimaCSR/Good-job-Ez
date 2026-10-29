"""模板**骨架规格**（槽位）的测试。

## 为什么要有这层测试

用户：「你是不是做不到简历模板识别生成对应的 html，
然后简历优化时根据个人信息填入相应的内容？」

**以前做不到** —— 架构里只有「模板 → CSS」，没有「模板 → 骨架」。
光测颜色不够 —— 要测**骨架、槽位、填充**。

## 测什么

1. PDF → 槽位规格（姓名 / 联系方式 / 章节）
2. 章节类型判定（段落 / 列表 / 条目 / 标签）
3. 模板章节 ↔ 用户内容的**语义对齐**
4. 内容形态转换（entry → list 等）
5. 骨架 HTML 能被 Jinja 渲染
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import resume_template        # noqa: E402
import template_slots        # noqa: E402


def make_pdf(text_items):
    """造一个最小 PDF，内容流里放给定的文字块。

    text_items: [(text, x, y, size)]
    """
    import zlib
    ops = []
    for text, x, y, size in text_items:
        # **用 CID 形式**（<hex>）—— 真实的中文 PDF 都是这样。
        #
        # **编码必须是 2 字节 CID**（UTF-16BE 的前两字节），
        # 不是 4 位的码点 —— 抽文字时按 2 字节切 CID。
        hexs = "".join("%04X" % ord(ch) for ch in text)
        ops.append("BT /F1 %s Tf 1 0 0 1 %s %s Tm <%s> Tj ET"
                   % (size, x, y, hexs))
    ops.append("q 1 0 0 1 0 0 cm 1 0 0 rg 0 0 595 100 re f Q")
    content = "\n".join(ops).encode("latin-1")

    # ── ToUnicode CMap ──
    #
    # **必须有** —— 中文 PDF 的文字是 CID 编码，
    # 没有映射表就抽不出文字（本机踩过：以为「PDF 抽不出文字」）。
    chars = {}
    for text, _x, _y, _s in text_items:
        for ch in text:
            chars[ord(ch)] = ch
    # **bfchar 的源必须是 `<XXXX>` 形式** ——
    # CMap 规范：`<src> <dst>`。少了左尖括号 → 正则匹配不上
    # → 映射表 0 条 → 文字全是乱码。
    #
    # 本机踩过：写成 `%04X <%04X>`（缺左括号）→ 解析出 0 条。
    entries = "".join("<%04X> <%04X>\n" % (c, c) for c in sorted(chars))
    cmap = ("/CIDInit /ProcSet findresource begin\n"
            "12 dict begin\nbegincmap\n"
            "/CMapName /A def\n/CMapType 2 def\n"
            "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
            "%d beginbfchar\n%sendbfchar\nendcmap\n"
            "CMapName currentdict /CMap defineresource pop\nend\nend"
            % (len(chars), entries)).encode("latin-1")
    cmap_comp = zlib.compress(cmap)

    # ── 写文件 ──
    #
    # **对象 4（内容流）和 7（ToUnicode）不在 objs 字典里** ——
    # 它们是流，要单独写。
    #
    # 本机踩过：把 4 放进字典但用 `if num == 4` 分支写 →
    # 循环走不到（4 在字典里但 sorted 到了… 实际是流对象根本没进字典）
    # → 文件里只有 1,2,3,5,6 → ToUnicode 引用了不存在的对象 7
    # → 映射表 0 条 → 文字全空 → 测试报「没抽出姓名」。
    objs = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"),
        5: (b"<< /Type /Font /Subtype /Type0 /BaseFont /Test /Encoding /Identity-H "
            b"/DescendantFonts [6 0 R] /ToUnicode 7 0 R >>"),
        6: (b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /Test "
            b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) "
            b"/Supplement 0 >> >>"),
    }
    streams = {
        4: zlib.compress(content),
        7: cmap_comp,
    }
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(list(objs) + list(streams)):
        offsets[num] = len(out)
        if num in streams:
            blob = streams[num]
            out += (b"%d 0 obj\n<< /Length %d /Filter /FlateDecode >>\nstream\n"
                    % (num, len(blob)))
            out += blob + b"\nendstream\nendobj\n"
        else:
            out += b"%d 0 obj\n%s\nendobj\n" % (num, objs[num])
    xref = len(out)
    out += b"xref\n0 8\n0000000000 65535 f \n"
    for num in range(1, 8):
        out += b"%010d 00000 n \n" % offsets.get(num, 0)
    out += b"trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % xref
    return bytes(out)


class TestPdfSlots(unittest.TestCase):

    def test_extracts_name(self):
        """**姓名 = 页眉里字号最大的那块**。"""
        data = make_pdf([
            ("张三", 50, 780, 26),
            ("电话：13800000000", 50, 740, 10),
            ("邮箱：a@b.cn", 250, 740, 10),
            ("工作经历", 50, 600, 14),
            ("某公司", 50, 570, 11),
        ])
        spec, note = template_slots.extract_slots(data, "pdf")
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec["head"]["name"], "没抽出姓名：%r" % spec)
        self.assertEqual(spec["head"]["name"]["text"], "张三")

    def test_extracts_sections(self):
        """**章节标题 = 字号第二档、比正文大、且短**。"""
        data = make_pdf([
            ("张三", 50, 780, 26),
            ("工作经历", 50, 600, 14),
            ("某公司 2020-2024", 50, 570, 11),
            ("自我评价", 50, 400, 14),
            ("1. 认真负责", 50, 370, 10),
        ])
        spec, _ = template_slots.extract_slots(data, "pdf")
        titles = [s["title"] for s in spec["sections"]]
        self.assertIn("工作经历", titles, "没抽出章节：%r" % titles)
        self.assertIn("自我评价", titles, "没抽出章节：%r" % titles)

    def test_section_kind_detected(self):
        """**章节类型要判对** —— 编号列表 → list，日期开头 → entry。"""
        data = make_pdf([
            ("张三", 50, 780, 26),
            ("自我评价", 50, 600, 14),
            ("1. 第一点说明", 50, 570, 10),
            ("2. 第二点说明", 50, 550, 10),
        ])
        spec, _ = template_slots.extract_slots(data, "pdf")
        sec = next(s for s in spec["sections"] if s["title"] == "自我评价")
        self.assertEqual(sec["kind"], "list", "编号列表没判成 list")

    def test_fields_split_by_column(self):
        """**左右两栏的字段要分开** —— 「性别：女年龄：25」不能连一起。"""
        data = make_pdf([
            ("张三", 50, 780, 26),
            ("电话：", 50, 740, 10),
            ("13800000000", 90, 740, 10),
            ("邮箱：", 250, 740, 10),
            ("a@b.cn", 290, 740, 10),
        ])
        spec, _ = template_slots.extract_slots(data, "pdf")
        labels = [f["label"] for f in spec["head"]["fields"]]
        self.assertIn("电话", labels, "没抽出电话：%r" % labels)
        self.assertIn("邮箱", labels, "没抽出邮箱：%r" % labels)
        for f in spec["head"]["fields"]:
            self.assertLessEqual(len(f["label"]), 6,
                                 "标签太长 —— 跨栏粘连了：%r" % f["label"])

    def test_page_height_from_mediabox(self):
        """**页面高要用 MediaBox** —— 不能用矩形坐标范围。

        很多模板开头用翻转矩阵 → 坐标范围会翻倍。
        本机踩过：page_h 翻倍 → 页眉区判定全错。
        """
        data = make_pdf([("张三", 50, 780, 26)])
        spec, _ = template_slots.extract_slots(data, "pdf")
        self.assertAlmostEqual(spec["page"]["height"], 842.0, delta=2.0,
                               msg="页面高算错：%r" % spec["page"])


class TestSkeletonHtml(unittest.TestCase):

    def test_builds_renderable_html(self):
        """**骨架 HTML 要能被 Jinja 渲染**。"""
        spec = {
            "version": 1, "source": "pdf",
            "page": {"width": 595, "height": 842},
            "body_size": 10.5,
            "head": {"name": {"text": "张三", "size": 26, "color": "#4066b0"},
                     "fields": [{"label": "电话", "value": "138", "size": 10}]},
            "sections": [{"title": "工作经历", "kind": "entry", "size": 14}],
        }
        html = template_slots.build_slot_html(spec, {})
        from jinja2 import Template
        out = Template(html).render(
            title="简历",
            identity={"name": "李四", "phone": "139"},
            sections=[{"title": "工作经历", "kind": "entry",
                       "entries": [{"title": "某公司", "meta": "2020",
                                    "subtitle": "", "bullets": []}]}],
            photo="")
        self.assertIn("李四", out)
        self.assertIn("工作经历", out)
        self.assertIn("某公司", out)

    def test_unknown_field_not_rendered(self):
        """**认不出来的字段不渲染** —— 免得出现空标签。"""
        spec = {
            "version": 1, "source": "pdf",
            "page": {"width": 595, "height": 842}, "body_size": 10.5,
            "head": {"name": None,
                     "fields": [{"label": "祖籍", "value": "x", "size": 10}]},
            "sections": [],
        }
        html = template_slots.build_slot_html(spec, {})
        self.assertNotIn("祖籍", html, "认不出来的字段也渲染了")

    def test_css_aliases_applied(self):
        """**PDF 的 CSS 类名要映射到骨架** —— 不映射装饰全落空。"""
        css = ".sec-title { color: #4066b0; } .head { border-left: 3px solid #d8dff0; }"
        out = template_slots._remap_css(css)
        self.assertIn(".tpl-sec-title", out)
        self.assertIn(".tpl-head", out)
        self.assertNotIn(".sec-title", out)


class TestAlignment(unittest.TestCase):
    """模板章节 ↔ 用户内容的语义对齐。"""

    def _spec(self, titles_kinds):
        return {"sections": [{"title": t, "kind": k}
                             for t, k in titles_kinds]}

    def test_exact_title_wins(self):
        """**标题完全相同 → 直接对上**。"""
        sections = [{"title": "工作经历", "kind": "entries",
                     "entries": [{"title": "A公司", "meta": "", "subtitle": "",
                                  "bullets": []}]}]
        spec = self._spec([("工作经历", "entry"), ("教育经历", "entry")])
        out = resume_template._align_to_skeleton(sections, spec)
        by_title = {s["title"]: s for s in out}
        self.assertEqual(len(by_title["工作经历"]["entries"]), 1)
        self.assertEqual(by_title["教育经历"]["entries"], [])

    def test_synonym_matches(self):
        """**「教育背景」=「教育经历」** —— 字面不同但同义。"""
        sections = [{"title": "教育背景", "kind": "entries",
                     "entries": [{"title": "某大学", "meta": "", "subtitle": "",
                                  "bullets": []}]}]
        spec = self._spec([("教育经历", "entry")])
        out = resume_template._align_to_skeleton(sections, spec)
        self.assertEqual(len(out[0]["entries"]), 1,
                         "同义标题没对上：%r" % out)

    def test_entry_converted_to_list(self):
        """**entry → list 要能转** —— 模板要 list、数据是 entry。

        本机踩过：模板的「工作经历」是 list（因为下面有编号），
        数据是 entry → 不转 → 章节空白。
        """
        sections = [{"title": "工作经历", "kind": "entries",
                     "entries": [{"title": "A公司", "meta": "2020",
                                  "subtitle": "",
                                  "bullets": [{"text": "做了啥", "basis": ""}]}]}]
        spec = self._spec([("工作经历", "list")])
        out = resume_template._align_to_skeleton(sections, spec)
        self.assertTrue(out[0]["bullets"], "entry → list 没转：%r" % out)
        # **条目标题和要点都要在** ——
        # 模板的「工作经历」是编号列表，所以公司名、职责都得变成列表项。
        texts = [b["text"] for b in out[0]["bullets"]]
        self.assertIn("A公司", texts, "条目标题丢了：%r" % texts)
        self.assertIn("做了啥", texts, "要点丢了：%r" % texts)

    def test_intent_section_filled_from_identity(self):
        """**「求职意向」从 identity 填** —— 数据里没这个章节。"""
        sections = [{"title": "个人简介", "kind": "text",
                     "paragraphs": ["自我介绍"]}]
        spec = self._spec([("求职意向", "paragraph")])
        out = resume_template._align_to_skeleton(
            sections, spec, {"headline": "前端工程师", "location": "重庆"})
        self.assertTrue(out[0]["paragraphs"], "求职意向没填：%r" % out)
        self.assertIn("前端工程师", " ".join(out[0]["paragraphs"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
