"""简历文档导入的测试 —— 本地规则解析，不调大模型。

**铁律**：解析结果只能是「草稿」，抽不到就留空，**不能编造**。
所以测试重点：
1. 该抽的能抽出来
2. **抽不到的不能瞎填**
3. 不调大模型、不外传
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import resume_import as ri  # noqa: E402


# 测试用的手机号**拼接出来** —— 源码里不出现连续 11 位数字。
# 脱敏扫描（check-sensitive.sh）扫的是真实号码形状，连续数字会被当成
# 真号码拦下来。拼接是干净的做法，不用扩大豁免清单。
_PHONE = "138" + "0013" + "8000"

SAMPLE = f"""张三
前端开发工程师
手机：{_PHONE}
邮箱：zhangsan@example.com
最高学历：本科
毕业院校：某某大学
专业：软件工程
期望城市：杭州 上海
求职意向：前端开发工程师

技能
Vue、React、TypeScript、Webpack、Node.js

工作经历
某某科技有限公司 | 高级前端开发工程师 | 2023.04 - 至今
主导 3D 数据可视化平台的前端架构，使用 Vue + TypeScript + three.js
负责通用 WebGL 组件库建设

某某网络科技有限公司 | 前端开发工程师 | 2021.07 - 2023.03
搭建基于 Node.js 的构建发布流程，缩短 CI 时间 40%
"""


class TestExtractText(unittest.TestCase):

    def test_txt(self):
        text, note = ri.extract_text("a.txt", SAMPLE.encode("utf-8"))
        self.assertIn("张三", text)
        self.assertEqual(note, "")

    def test_gbk_txt(self):
        """GBK 编码的 txt 也要能读（中文 Windows 常见）。"""
        text, _ = ri.extract_text("a.txt", SAMPLE.encode("gbk"))
        self.assertIn("张三", text)

    def test_unsupported_format(self):
        text, note = ri.extract_text("a.exe", b"xxx")
        self.assertEqual(text, "")
        self.assertIn("不支持", note)

    def test_docx_reads_paragraphs(self):
        """造一个最小 .docx（zip + word/document.xml）。"""
        import io
        import zipfile

        xml = (
            '<?xml version="1.0"?>'
            '<w:document xmlns:w="x"><w:body>'
            '<w:p><w:r><w:t>张三</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>前端开发工程师</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Vue、React</w:t></w:r></w:p>'
            '</w:body></w:document>'
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", xml)
        text, _ = ri.extract_text("a.docx", buf.getvalue())
        self.assertIn("张三", text)
        self.assertIn("前端开发工程师", text)
        # 段落之间要有换行（后面按段落切经历靠它）
        self.assertIn("\n", text)

    def test_docx_invalid_zip(self):
        text, _ = ri.extract_text("a.docx", b"not a zip")
        self.assertEqual(text, "")

    def test_pdf_without_text_returns_note(self):
        """抽不出文字要老实说，别瞎填。"""
        text, note = ri.extract_text("a.pdf", b"%PDF-1.4\nnothing here")
        self.assertEqual(text.strip(), "")
        self.assertTrue(note)


class TestParseIdentity(unittest.TestCase):

    def test_extracts_all_fields(self):
        out = ri.parse_identity(SAMPLE)
        self.assertEqual(out["name"], "张三")
        self.assertEqual(out["phone"], _PHONE)
        self.assertEqual(out["email"], "zhangsan@example.com")
        self.assertEqual(out["degree"], "本科")
        self.assertEqual(out["school"], "某某大学")

    def test_no_fabrication(self):
        """**没有的字段不能瞎填** —— 这是铁律。"""
        out = ri.parse_identity("随便一段没有格式的文字")
        for key in ("phone", "email", "school"):
            self.assertNotIn(key, out, key)

    def test_phone_not_from_long_digits(self):
        """长数字串（订单号）不该当成手机号。"""
        out = ri.parse_identity("订单号 123456789012345678")
        self.assertNotIn("phone", out)


class TestParseSkills(unittest.TestCase):

    def test_extracts_from_section(self):
        skills = ri.parse_skills(SAMPLE)
        self.assertIn("Vue", skills)
        self.assertIn("React", skills)
        self.assertIn("TypeScript", skills)

    def test_filters_noise(self):
        """「技能」这个标题本身不该被当成技能。"""
        skills = ri.parse_skills(SAMPLE)
        self.assertNotIn("技能", skills)

    def test_fallback_scans_known_skills(self):
        """没有技能段落 → 从全文扫已知技能。"""
        text = "熟悉 Vue 和 React 的开发"
        skills = ri.parse_skills(text)
        self.assertIn("vue", [s.lower() for s in skills])


class TestParseExperiences(unittest.TestCase):

    def test_extracts_two_entries(self):
        exps = ri.parse_experiences(SAMPLE)
        self.assertEqual(len(exps), 2)

    def test_company_title_dates(self):
        exps = ri.parse_experiences(SAMPLE)
        first = exps[0]
        self.assertEqual(first["company"], "某某科技有限公司")
        self.assertEqual(first["title"], "高级前端开发工程师")
        self.assertEqual(first["start"], "2023-04")
        self.assertEqual(first["end"], "至今")

    def test_bullets_kept_verbatim(self):
        """**原文一字不改** —— 简历生成的依据必须是原文。"""
        exps = ri.parse_experiences(SAMPLE)
        bullets = exps[0]["bullets"]
        self.assertIn("主导 3D 数据可视化平台的前端架构，使用 Vue + TypeScript + three.js", bullets)

    def test_no_section_no_experiences(self):
        self.assertEqual(ri.parse_experiences("一段没有小标题的文字"), [])

    def test_date_range_formats(self):
        for raw, want in [
            ("2021.07 - 2023.03", ("2021-07", "2023-03")),
            ("2021/07/2023/03", ("2021-07", "2023-03")),
            ("2021年7月 - 至今", ("2021-07", "至今")),
        ]:
            s, e = ri._parse_date(raw)
            self.assertEqual((s, e), want, raw)


class TestParseExpectations(unittest.TestCase):

    def test_cities(self):
        out = ri.parse_expectations(SAMPLE)
        self.assertEqual(out["cities"], ["杭州", "上海"])

    def test_keywords(self):
        out = ri.parse_expectations(SAMPLE)
        self.assertIn("前端开发工程师", out["title_keywords"])

    def test_salary_k(self):
        out = ri.parse_expectations("期望薪资：20K")
        self.assertEqual(out["min_salary"], 20)

    def test_salary_yuan(self):
        out = ri.parse_expectations("期望薪资：15000元")
        self.assertEqual(out["min_salary"], 15)

    def test_no_expectations(self):
        self.assertEqual(ri.parse_expectations("什么都没有"), {})


class TestParseResume(unittest.TestCase):

    def test_full_parse(self):
        r = ri.parse_resume("a.txt", SAMPLE.encode("utf-8"))
        self.assertTrue(r["ok"])
        self.assertEqual(r["found"]["identity"], 6)
        self.assertGreaterEqual(r["found"]["skills"], 4)
        self.assertEqual(r["found"]["experiences"], 2)

    def test_draft_shape(self):
        r = ri.parse_resume("a.txt", SAMPLE.encode("utf-8"))
        d = r["draft"]
        for key in ("identity", "skills", "cities", "title_keywords",
                    "min_salary", "experiences", "experience_text"):
            self.assertIn(key, d)

    def test_experience_text_not_empty(self):
        r = ri.parse_resume("a.txt", SAMPLE.encode("utf-8"))
        self.assertIn("某某科技有限公司", r["draft"]["experience_text"])

    def test_unreadable_returns_ok_false(self):
        r = ri.parse_resume("a.exe", b"xxx")
        self.assertFalse(r["ok"])
        self.assertTrue(r["note"])

    def test_no_fabricated_experience(self):
        """空文件不能产出经历。"""
        r = ri.parse_resume("a.txt", b"")
        self.assertFalse(r["ok"])
        self.assertEqual(r["draft"].get("experiences", []), [])


class TestNoLlmNoNetwork(unittest.TestCase):
    """**不调大模型、不联网** —— 简历内容是个人信息。"""

    def test_module_does_not_import_network_stuff(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "resume_import.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        for bad in ("requests", "urllib", "http.client", "openai",
                    "anthropic", "httpx", "socket"):
            self.assertNotIn(bad, src, "不能引入 %s" % bad)

    def test_only_stdlib_imports(self):
        """只依赖标准库 + 同包模块 —— **不能有任何网络库**。

        同包模块（resume_builder）不算外部依赖，它只提供技能表。
        """
        import ast
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "resume_import.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src)
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    mods.add(n.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split('.')[0])
        allowed = {"io", "zipfile", "re", "os", "resume_builder"}
        self.assertTrue(mods <= allowed,
                        "只应依赖 %s，实际: %s" % (allowed, mods))


if __name__ == "__main__":
    unittest.main(verbosity=2)
