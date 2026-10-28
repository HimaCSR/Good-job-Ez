"""简历优化消费「结构化经历」的测试。

## 为什么测这个

用户诉求：**「AI 优化简历与岗位方向推荐的原料，除了真实经历、还有结构化经历内容。」**

之前的实现只读 `profile["experience_text"]`（自由文本）——
**结构化经历（有公司/职位/起止）完全没进优化流程**。

结果：
- 只填结构化经历 → 简历生成不了
- 填了结构化经历 → 简历里公司名/时间是空的（自由文本给不了）

## 测什么

1. 有结构化经历 → 走结构化模式
2. 工作经历章节有公司、职位、起止
3. bullets 只留命中 JD 要求的（不命中的不写进简历）
4. 没命中任何 JD 的经历**仍保留标题**（公司/时间是硬信息）
5. 没有结构化经历 → 退回自由文本模式（老行为不变）
6. 职位名里的技能也算证据（「Java 后端工程师」命中 Java）
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resume_builder import optimize_resume  # noqa: E402


JOB = {
    "title": "Java 后端工程师",
    "description": (
        "负责后端服务开发，要求熟悉 Java、Spring、MySQL，"
        "有高并发经验优先。"
    ),
}

PROFILE = {
    "identity": {"name": "张三", "phone": "000-0000-0000"},
    "skills": ["Java", "Spring", "MySQL"],
    "experience_text": "",
}

EXPERIENCES = [
    {
        "id": "exp-1",
        "company": "某某科技",
        "title": "Java 后端工程师",
        "start": "2021-03",
        "end": "至今",
        "bullets": [
            "用 Java 和 Spring 重构订单系统，QPS 从 800 提升到 3000",
            "负责周会汇报和团队协调工作",
        ],
        "tags": [],
    },
    {
        "id": "exp-2",
        "company": "某某外企",
        "title": "运营专员",
        "start": "2019-06",
        "end": "2021-02",
        "bullets": [
            "负责日常活动策划与执行",
            "整理每周数据报表",
        ],
        "tags": [],
    },
]


class TestStructuredExperienceUsed(unittest.TestCase):

    def _opt(self, **kw):
        params = dict(job=JOB, profile=PROFILE, template_id="classic")
        params.update(kw)
        return optimize_resume(**params)

    # ── 基本行为 ──

    def test_uses_structured_when_given(self):
        out = self._opt(experiences=EXPERIENCES)
        self.assertTrue(out["used_structured"])
        self.assertEqual(out["template_id"], "classic")

    def test_falls_back_to_free_text(self):
        """没有结构化经历 → 老行为（自由文本）。"""
        p = dict(PROFILE)
        p["experience_text"] = "用 Java 和 Spring 做过订单系统重构"
        out = optimize_resume(job=JOB, profile=p)
        self.assertFalse(out["used_structured"])
        self.assertTrue(out["matched"]["covered"])

    def test_empty_experiences_list_falls_back(self):
        """空列表 → 当作没有（不是「有但没内容」）。"""
        p = dict(PROFILE)
        p["experience_text"] = "用 Java 做过重构"
        out = optimize_resume(job=JOB, profile=p, experiences=[])
        self.assertFalse(out["used_structured"])

    # ── 工作经历章节 ──

    def test_work_section_has_company_title_period(self):
        """**公司、职位、起止要出现在简历里** —— 这是结构化经历最大的价值。"""
        out = self._opt(experiences=EXPERIENCES)
        entries = out["resume"]["experiences"]
        self.assertTrue(entries, "工作经历章节是空的")

        blob = " ".join(
            "%s %s %s" % (e.get("title", ""), e.get("meta", ""),
                          " ".join(b.get("text", "") for b in e.get("bullets", [])))
            for e in entries
        )
        self.assertIn("某某科技", blob)
        self.assertIn("Java 后端工程师", blob)
        self.assertIn("2021-03", blob)
        self.assertIn("至今", blob)

    def test_each_experience_is_separate_entry(self):
        """两条经历 → 两个条目（不能挤成一条）。"""
        out = self._opt(experiences=EXPERIENCES)
        entries = out["resume"]["experiences"]
        self.assertEqual(len(entries), 2)
        titles = [e.get("title", "") for e in entries]
        self.assertTrue(any("某某科技" in t for t in titles))
        self.assertTrue(any("某某外企" in t for t in titles))

    def test_bullets_only_ones_matching_jd(self):
        """**只写命中 JD 的 bullet** —— 不相关的别塞进简历。"""
        out = self._opt(experiences=EXPERIENCES)
        entries = out["resume"]["experiences"]
        texts = [b.get("text", "") for e in entries for b in e.get("bullets", [])]

        self.assertTrue(any("Spring" in t for t in texts),
                        "命中 JD 的 bullet 没被保留")
        self.assertFalse(any("周会汇报" in t for t in texts),
                         "不相关的 bullet 被写进简历了")
        self.assertFalse(any("数据报表" in t for t in texts),
                         "运营经历的不相关 bullet 被写进简历了")

    def test_unmatched_experience_keeps_header(self):
        """**没命中任何 JD 的经历仍保留标题** ——
        公司/职位/时间是硬信息，不该因为对不上 JD 就抹掉。"""
        out = self._opt(experiences=EXPERIENCES)
        entries = out["resume"]["experiences"]
        titles = [e.get("title", "") for e in entries]
        self.assertTrue(
            any("某某外企" in t for t in titles),
            "不相关经历的标题被抹掉了")

    def test_title_skill_counts_as_evidence(self):
        """职位名里的技能算证据（「Java 后端工程师」命中 Java）。

        **技能名是 normalize 过的小写**（`java`）——
        所以断言也要用小写。
        """
        out = self._opt(experiences=EXPERIENCES)
        entries = out["resume"]["experiences"]
        tech = [e for e in entries if "某某科技" in e.get("title", "")][0]
        self.assertIn("java", tech.get("head_matched", []))

    def test_no_fabrication(self):
        """**不能编造** —— 简历里只能有用户写过的内容。"""
        out = self._opt(experiences=EXPERIENCES)
        blob = str(out["resume"])
        # JD 提到「高并发」但用户没写过 → 不该出现在简历里
        self.assertNotIn("高并发", blob)
        # 用户的原话应该在
        self.assertIn("订单系统", blob)

    def test_gaps_still_reported(self):
        """缺口还是要报（JD 要但经历里一次都没提过的）。

        技能名是 normalize 过的小写：`sql`（JD 要 MySQL，
        但用户经历里没写过任何 SQL 相关的东西）。
        """
        out = self._opt(experiences=EXPERIENCES)
        gap_names = [g["name"] for g in out["matched"]["gaps"]]
        self.assertIn("sql", gap_names)


class TestUserSkillsAsRequirements(unittest.TestCase):
    """**用户自己的技能出现在 JD 里 → 也是一条 JD 要求。**

    ## 为什么

    内置别名表只覆盖常见技术词。用户简历里的技能
    （CAD / Revit / 盈建科 / 天正 / 数据透视表…）常常**不在表里**。

    后果（本机真实踩到）：
    JD 写「熟悉 CAD、Revit、盈建科」，
    抽出来的要求里**一个都没有** →
    用户的 CAD / Revit 经历**一条都匹配不上** →
    **简历的工作经历章节被写成空的**。

    ## 规则

    - 用户会的技能 + 它出现在 JD 里 → 一条要求
    - 用户会的技能 + JD 里没提 → **不加**（那是用户会的，不是岗位要的）
    """

    JD = ("负责工业厂房结构设计，熟悉 CAD、Revit、盈建科，"
          "需要具备结构计算与建模能力。")
    SKILLS = ["CAD", "Revit", "盈建科", "天正", "Photoshop"]

    def test_user_skill_in_jd_becomes_requirement(self):
        from resume_builder import extract_requirements
        reqs = extract_requirements(self.JD, self.SKILLS)
        names = [s["name"] for s in reqs["skills"]]
        self.assertIn("CAD", names)
        self.assertIn("Revit", names)
        self.assertIn("盈建科", names)

    def test_user_skill_not_in_jd_is_not_added(self):
        """**JD 没提的技能不加** —— 否则缺口报告会全是噪音。"""
        from resume_builder import extract_requirements
        reqs = extract_requirements(self.JD, self.SKILLS)
        names = [s["name"] for s in reqs["skills"]]
        self.assertNotIn("天正", names)
        self.assertNotIn("Photoshop", names)

    def test_structured_bullets_now_match(self):
        """**端到端** —— 用户的 CAD 经历要能进简历。"""
        profile = {
            "identity": {"name": "李四"},
            "skills": self.SKILLS,
            "experience_text": "",
        }
        exps = [{
            "id": "e1",
            "company": "某设计院",
            "title": "结构设计工程师",
            "start": "2022-07",
            "end": "至今",
            "bullets": [
                "用 CAD 完成 12 万平米工业厂房结构设计",
                "用 Revit 做主体结构三维建模",
                "用天正做施工图深化设计",
            ],
            "tags": [],
        }]
        out = optimize_resume(
            job={"title": "结构设计工程师", "description": self.JD},
            profile=profile,
            experiences=exps,
        )
        texts = [b.get("text", "")
                 for e in out["resume"]["experiences"]
                 for b in e.get("bullets", [])]
        self.assertTrue(any("CAD" in t for t in texts),
                        "CAD 经历没进简历（JD 里的技能没被识别）")
        self.assertTrue(any("Revit" in t for t in texts),
                        "Revit 经历没进简历")

    def test_bullet_only_in_unrelated_skill_is_dropped(self):
        """**只沾了无关技能的 bullet 不该进简历。**

        注意「用天正做施工图深化设计」在上一条测试里**会**被保留 ——
        因为它命中了 JD 里的「设计」（结构设计），
        那是**正确行为**。

        这里用一个 JD 里没有「设计」的岗位，
        验证「天正」既不是要求、bullet 也不该留下。
        """
        profile = {
            "identity": {"name": "李四"},
            "skills": self.SKILLS,
            "experience_text": "",
        }
        exps = [{
            "id": "e1",
            "company": "某设计院",
            "title": "结构设计工程师",
            "start": "2022-07",
            "end": "至今",
            "bullets": ["用天正做施工图深化设计"],
            "tags": [],
        }]
        out = optimize_resume(
            job={"title": "施工员", "description": "现场施工技术交底，负责图纸会审。"},
            profile=profile,
            experiences=exps,
        )
        texts = [b.get("text", "")
                 for e in out["resume"]["experiences"]
                 for b in e.get("bullets", [])]
        self.assertFalse(any("天正" in t for t in texts),
                         "JD 没提的技能被硬塞进简历了")


if __name__ == "__main__":
    unittest.main(verbosity=2)
