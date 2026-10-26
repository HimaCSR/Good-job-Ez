"""简历匹配优化的测试。

重点：**不编造经历**（每条 bullet 都能追溯到原文）、JD 解析、模板渲染。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resume_builder import (  # noqa: E402
    build_sections, extract_requirements, match_experience,
    optimize_resume, split_experience,
)
from resume_template import BUILTIN, render_html, list_all, template_info  # noqa: E402


JD = """
负责核心产品的前端开发，要求精通 Vue 和 TypeScript。
熟悉 three.js / WebGL 等 3D 可视化技术，有性能优化经验。
本科及以上学历，3年以上前端开发经验。团队使用 React 和 Node.js。
"""

EXPERIENCE = """- 主导公司 3D 数据可视化平台的架构与前端实现，使用 Vue + TypeScript + three.js，将渲染帧率提升 60%
- 负责通用 WebGL 组件库建设，支持图表、模型、地图多种场景
- 搭建基于 Node.js 的构建与发布流程，缩短 CI 时间 40%
"""

PROFILE = {
    "skills": ["vue", "typescript", "three.js", "webgl", "node"],
    # 演示数据：虚构姓名 + 示例邮箱。**不写手机号** ——
    # 测试不需要它，仓库里也不该出现手机号形状的字符串。
    "identity": {"name": "张三", "email": "user@example.com",
                 "location": "杭州", "education": "本科"},
    "experience_text": EXPERIENCE,
}

JOB = {"job_id": "X1", "title": "高级前端工程师", "description": JD}


class TestExtractRequirements(unittest.TestCase):

    def test_finds_skills(self):
        reqs = extract_requirements(JD, PROFILE["skills"])
        names = {s["name"] for s in reqs["skills"]}
        self.assertIn("vue", names)
        self.assertIn("typescript", names)
        self.assertIn("three.js", names)
        self.assertIn("react", names)

    def test_marks_user_skills(self):
        reqs = extract_requirements(JD, PROFILE["skills"])
        by = {s["name"]: s for s in reqs["skills"]}
        self.assertTrue(by["vue"]["user_has"])
        self.assertFalse(by["react"]["user_has"])

    def test_degree(self):
        self.assertEqual(extract_requirements(JD, [])["degree"], "本科")

    def test_years(self):
        self.assertEqual(extract_requirements(JD, [])["min_years"], 3)

    def test_unlimited_experience_is_none(self):
        """「经验不限」不是 0 年，是没有年限要求。"""
        reqs = extract_requirements("经验不限，欢迎应届生", [])
        self.assertIsNone(reqs["min_years"])

    def test_sticky_tags_are_split(self):
        """JD 的 tags 常粘连（"CSSJavaScriptERP"）——
        不能把它当成一个怪词，否则既匹配不到技能也污染关键词。"""
        reqs = extract_requirements(
            "熟悉 CSSJavaScript 和 VueEcharts", PROFILE["skills"])
        names = {s["name"] for s in reqs["skills"]}
        self.assertIn("javascript", names)
        self.assertIn("vue", names)
        # 关键词里不能出现粘连碎片
        for kw in reqs["keywords"]:
            self.assertNotIn("CSSJava", kw)
            self.assertNotIn("VueEcharts", kw)


class TestSplitExperience(unittest.TestCase):

    def test_bullets(self):
        lines = split_experience(EXPERIENCE)
        self.assertEqual(len(lines), 3)

    def test_markers_stripped(self):
        lines = split_experience("- 第一条\n• 第二条\n* 第三条")
        self.assertEqual(lines, ["第一条", "第二条", "第三条"])

    def test_empty(self):
        self.assertEqual(split_experience(""), [])
        self.assertEqual(split_experience(None), [])


class TestMatchExperience(unittest.TestCase):

    def setUp(self):
        self.reqs = extract_requirements(JD, PROFILE["skills"])
        self.m = match_experience(self.reqs, EXPERIENCE, PROFILE["skills"])

    def test_finds_covered_bullets(self):
        self.assertEqual(len(self.m["covered"]), 3)

    def test_basis_is_a_pointer_not_a_copy(self):
        """依据是「经历第 N 条」，不是把原文重复一遍 ——
        重复一遍没有信息量，还把简历撑得很长。"""
        for c in self.m["covered"]:
            self.assertRegex(c["basis"], r"^经历第 \d+ 条$")
            # 原文另存一份，供预览时展开
            self.assertEqual(c["basis_text"], c["text"])

    def test_gaps_are_skills_not_mentioned(self):
        gap_names = {g["name"] for g in self.m["gaps"]}
        self.assertIn("react", gap_names)
        # 用户会的技能不该算缺口（只要经历里提过）
        self.assertNotIn("vue", gap_names)

    def test_strengths(self):
        self.assertIn("three.js", self.m["strengths"])


class TestOptimizeResume(unittest.TestCase):

    def setUp(self):
        self.out = optimize_resume(JOB, PROFILE, "classic")

    def test_no_fabrication(self):
        """生成的内容必须全部来自用户写过的原文。"""
        originals = {l.strip() for l in split_experience(EXPERIENCE)}
        for sec in build_sections(self.out["resume"]):
            if sec["kind"] != "entries":
                continue
            for e in sec["entries"]:
                for b in e["bullets"]:
                    self.assertIn(b["text"], originals)

    def test_bullets_carry_basis(self):
        for sec in build_sections(self.out["resume"]):
            if sec["kind"] != "entries":
                continue
            for e in sec["entries"]:
                for b in e["bullets"]:
                    self.assertTrue(b["basis"].startswith("经历第"))

    def test_skills_from_profile(self):
        self.assertTrue(set(self.out["resume"]["skills"]) <= set(PROFILE["skills"]))


class TestTemplate(unittest.TestCase):

    def test_four_builtin(self):
        self.assertEqual(set(BUILTIN), {"classic", "modern", "tech", "acad"})

    def test_list_all_includes_builtin(self):
        ids = {t["template_id"] for t in list_all()}
        self.assertTrue({"classic", "modern", "tech", "acad"} <= ids)

    def test_template_info(self):
        info = template_info("classic")
        self.assertTrue(info["builtin"])
        self.assertEqual(info["name"], "经典单栏")

    def test_render_has_identity(self):
        html = render_html("classic", {
            "title": "T", "identity": {"name": "张三"},
            "sections": [{"title": "工作经历", "kind": "entries",
                          "entries": [{"title": "X", "meta": "", "subtitle": "",
                                       "bullets": [{"text": "做了一件事",
                                                    "basis": "经历第 1 条"}]}]}],
        })
        self.assertIn("张三", html)
        self.assertIn("做了一件事", html)

    def test_basis_hidden_by_default(self):
        """正式输出不显示依据标注 —— 那是预览用的。"""
        html = render_html("classic", {
            "title": "T", "identity": {"name": "张三"},
            "sections": [{"title": "S", "kind": "list",
                          "bullets": [{"text": "x", "basis": "经历第 1 条"}]}],
        })
        self.assertIn("show-basis", html)   # CSS 规则在
        self.assertNotIn("show-basis show", html)

    def test_basis_shown_on_request(self):
        html = render_html("classic", {
            "title": "T", "identity": {"name": "张三"}, "show_basis": True,
            "sections": [{"title": "S", "kind": "list",
                          "bullets": [{"text": "x", "basis": "经历第 1 条"}]}],
        })
        self.assertIn('class="show-basis"', html)

    def test_all_builtin_render(self):
        """四套模板都要能渲染 —— 加新模板时别写坏旧的。"""
        for tid in BUILTIN:
            html = render_html(tid, {
                "title": "T", "identity": {"name": "张三"},
                "sections": [{"title": "S", "kind": "tags", "tags": ["vue"]}],
            })
            self.assertIn("张三", html, tid)
            self.assertIn("vue", html, tid)

    def test_unknown_template_raises(self):
        with self.assertRaises(FileNotFoundError):
            render_html("nope", {"title": "T", "identity": {}, "sections": []})


if __name__ == "__main__":
    unittest.main(verbosity=2)
