"""**从经历抽方向词** 的测试。

## 为什么测这个

用户诉求：

> 每次用户保存插件内的个人信息保存/更新，便重新根据经历内容
> 更新期望内容标签，保证抓取的岗位更加契合用户

## 测什么

1. 职位名 → 方向词
2. 泛称过滤（实习生/工程师/运营…不能当方向词）
3. 「工程」单独用太宽 → 前端岗位不该被提上来
4. **幂等** —— 保存几次结果都一样
5. 不动用户的「主攻方向」
6. 技能**不自动补**（会把分数拉低）
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import profile_derive  # noqa: E402


def exp(title, bullets=None, company="某公司", tags=None):
    return {"title": title, "company": company,
            "bullets": bullets or [], "tags": tags or []}


class TestExtractDirections(unittest.TestCase):

    def test_title_becomes_direction(self):
        """**职位名是最可靠的方向来源**。"""
        dirs, _ = profile_derive.extract_from_experiences(
            [exp("跨境电商运营", ["负责速卖通店铺运营与选品"])])
        self.assertIn("跨境电商运营", dirs)

    def test_generic_titles_filtered(self):
        """**泛称不能当方向词** —— 「实习生」几乎每个岗位都有。"""
        dirs, _ = profile_derive.extract_from_experiences(
            [exp("实习生", ["参与项目实施"])])
        self.assertNotIn("实习生", dirs)
        self.assertNotIn("实习", dirs)

    def test_generic_business_words_filtered(self):
        """**「运营」「质量」「客户」「销售」太宽** → 会命中所有岗位。"""
        dirs, _ = profile_derive.extract_from_experiences(
            [exp("客户经理", ["主导多渠道获客体系搭建"])])
        for w in ("运营", "质量", "客户", "销售", "营销", "策划", "品牌"):
            self.assertNotIn(w, dirs, "泛词 %r 不该当方向词：%r" % (w, dirs))

    def test_engineering_alone_filtered(self):
        """**「工程」单独用太宽** —— 「web前端开发工程师」会命中。

        本机踩过：web前端开发工程师 +15 分 → 推荐混进前端岗。
        """
        dirs, _ = profile_derive.extract_from_experiences(
            [exp("web前端开发工程师", ["负责 Vue 和 React 开发"])])
        self.assertNotIn("工程", dirs)

    def test_specific_building_terms_kept(self):
        """**具体的组合词要留** —— 「土建」「现场管理」是真的领域词。"""
        dirs, _ = profile_derive.extract_from_experiences(
            [exp("土建技术员", ["参与现场管理与桩基工程、主体结构施工"])])
        self.assertIn("土建", dirs)
        self.assertIn("现场管理", dirs)
        self.assertIn("桩基工程", dirs)

    def test_bullets_contribute_direction(self):
        """**bullets 里的业务词也算**（权重低于职位名）。"""
        dirs, _ = profile_derive.extract_from_experiences(
            [exp("技术员", ["负责速卖通店铺的选品与 listing 优化"])])
        self.assertIn("速卖通", dirs)
        self.assertIn("选品", dirs)

    def test_stop_words_not_directions(self):
        """**「工作描述：」这类结构标记不能当方向词**。"""
        dirs, _ = profile_derive.extract_from_experiences(
            [exp("技术员", ["工作描述：", "工作内容：", "项目职责："])])
        for w in ("工作描述", "工作内容", "项目职责"):
            self.assertNotIn(w, dirs)


class TestApplyToProfile(unittest.TestCase):

    def test_adds_directions_not_skills(self):
        """**只加方向词，不加技能**。

        技能项 = 30 分 × (命中数 / 技能总数) → 加技能会让分数**变低**。
        本机踩过：加 17 个技能 → 跨境电商运营 80 分掉到 70 分。
        """
        prof = {"title_keywords_primary": ["跨境电商运营"],
                "title_keywords": ["结构设计"], "skills": ["CAD", "Revit"]}
        out, note, ch = profile_derive.apply_to_profile(
            prof, [exp("跨境电商运营", ["负责速卖通店铺运营与选品"])])
        self.assertTrue(ch["directions"], "没抽出方向词")
        self.assertEqual(ch["skills"], [], "不该自动加技能")
        self.assertIn("CAD", out["skills"], "原有技能被动了")

    def test_primary_direction_untouched(self):
        """**主攻方向永远不动** —— 那是用户的战略选择（30 分 vs 15 分）。"""
        prof = {"title_keywords_primary": ["跨境电商运营"],
                "title_keywords": [], "skills": []}
        out, _note, _ch = profile_derive.apply_to_profile(
            prof, [exp("土建技术员", ["参与桩基施工"])])
        self.assertEqual(out["title_keywords_primary"], ["跨境电商运营"])

    def test_user_words_kept_first(self):
        """**用户手填的词保留在前面** —— 不打乱他的排序。"""
        prof = {"title_keywords_primary": [], "title_keywords": ["建筑设计"],
                "skills": []}
        out, _note, _ch = profile_derive.apply_to_profile(
            prof, [exp("土建技术员", ["参与施工"])])
        self.assertEqual(out["title_keywords"][0], "建筑设计")

    def test_idempotent(self):
        """**幂等** —— 保存几次结果都一样。

        本机踩过：保存 4 次 → 方向词 17 → 18 → 19 → 20（每次多一个）。
        """
        prof = {"title_keywords_primary": ["跨境电商运营"],
                "title_keywords": ["结构设计", "建筑设计"], "skills": []}
        exps = [exp("跨境电商运营", ["负责速卖通店铺运营与选品"]),
                exp("土建技术员", ["参与桩基工程与主体结构施工"])]
        first, _n1, ch1 = profile_derive.apply_to_profile(prof, exps)
        second, _n2, ch2 = profile_derive.apply_to_profile(first, exps)
        third, _n3, ch3 = profile_derive.apply_to_profile(second, exps)
        self.assertTrue(ch1["directions"], "第一次没抽出方向词")
        self.assertEqual(ch2["directions"], [], "第二次不该有新增")
        self.assertEqual(ch3["directions"], [], "第三次不该有新增")
        self.assertEqual(first["title_keywords"], second["title_keywords"])
        self.assertEqual(second["title_keywords"], third["title_keywords"])

    def test_note_for_user(self):
        """**要给用户看得懂的变更说明**。"""
        prof = {"title_keywords_primary": [], "title_keywords": [], "skills": []}
        _out, note, _ch = profile_derive.apply_to_profile(
            prof, [exp("跨境电商运营", ["负责速卖通店铺运营"])])
        self.assertIn("方向词", note)
        self.assertIn("跨境电商运营", note)


if __name__ == "__main__":
    unittest.main(verbosity=2)
