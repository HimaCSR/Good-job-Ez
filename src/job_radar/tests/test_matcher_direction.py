"""岗位打分的「方向匹配」测试 —— 结构化经历也参与打分。

## 为什么

用户诉求：

> AI 优化简历与**岗位方向推荐**的原料，除了真实经历、还有结构化经历内容。

「岗位方向推荐」= 岗位打分（`matcher.score_job`）——
分数决定哪些岗位排在前面。

之前打分只看 `profile`：
- `title_keywords`（用户主动填的期望岗位词）
- `skills`（用户填的技能）
- 城市、薪资

**结构化经历里的职位名完全没参与** ——
但那是**干过的真实岗位**，比「意向」更硬（干过 = 会）。

## 规则

1. 岗位标题命中结构化经历里的职位名 → **+10 分**，理由里写「方向匹配经历」
2. **只在 title_keywords 没命中时给分** —— 否则同一件事算两遍，虚高
3. 只比**职位名**，不比公司名（公司名太泛）
4. 分数上限 100 不破
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matcher import score_job  # noqa: E402


PROFILE = {
    "title_keywords": [],          # 用户没填期望岗位词
    "skills": ["CAD"],
    "cities": [],
    "min_salary": 0,
}

EXPERIENCES = [
    {"id": "e1", "company": "某设计院", "title": "结构设计工程师",
     "start": "2022-07", "end": "至今", "bullets": [], "tags": []},
    {"id": "e2", "company": "某施工公司", "title": "施工员",
     "start": "2020-08", "end": "2022-06", "bullets": [], "tags": []},
]


def job(title, city="杭州", salary="15-25K", desc=""):
    return {"title": title, "city": city, "salary": salary,
            "description": desc, "tags": []}


class TestDirectionMatching(unittest.TestCase):

    def test_exact_title_match_gets_bonus(self):
        out = score_job(job("结构设计工程师"), PROFILE, experiences=EXPERIENCES)
        self.assertTrue(any("方向匹配" in r for r in out["reasons"]),
                        "职位名命中经历却没有方向加分")
        self.assertGreater(out["score"], 0)

    def test_core_word_match(self):
        """去掉「工程师」后缀的核心词也算命中。

        「结构设计工程师」→ 核心词「结构设计」——
        岗位写「结构设计员」也算同一个方向。
        """
        out = score_job(job("结构设计员"), PROFILE, experiences=EXPERIENCES)
        self.assertTrue(any("方向匹配" in r for r in out["reasons"]),
                        "核心词命中没有加分")

    def test_unrelated_title_no_bonus(self):
        out = score_job(job("餐饮服务员"), PROFILE, experiences=EXPERIENCES)
        self.assertFalse(any("方向匹配" in r for r in out["reasons"]),
                         "无关岗位拿到了方向加分")

    def test_no_experiences_means_no_bonus(self):
        """没有结构化经历 → 行为跟以前一样（不加分，也不报错）。"""
        out = score_job(job("结构设计工程师"), PROFILE)
        self.assertFalse(any("方向匹配" in r for r in out["reasons"]))

    def test_empty_experiences_is_safe(self):
        out = score_job(job("结构设计工程师"), PROFILE, experiences=[])
        self.assertFalse(any("方向匹配" in r for r in out["reasons"]))

    def test_title_keywords_hit_does_not_double_count(self):
        """**title_keywords 命中时不重复加分** —— 意向 + 经历是同一件事。"""
        prof = dict(PROFILE)
        prof["title_keywords"] = ["结构设计"]
        base = score_job(job("结构设计工程师"), prof)
        with_exp = score_job(job("结构设计工程师"), prof, experiences=EXPERIENCES)
        self.assertEqual(base["score"], with_exp["score"],
                         "title_keywords 命中时又加了方向分（虚高）")
        self.assertFalse(any("方向匹配" in r for r in with_exp["reasons"]))

    def test_company_name_not_matched(self):
        """**只比职位名，不比公司名** —— 公司名太泛。"""
        out = score_job(job("某设计院"), PROFILE, experiences=EXPERIENCES)
        self.assertFalse(any("方向匹配" in r for r in out["reasons"]),
                         "公司名被当成了方向信号")

    def test_score_never_over_100(self):
        """分数不会破 100。"""
        prof = {
            "title_keywords": [], "skills": ["CAD"],
            "cities": ["杭州"], "min_salary": 15,
        }
        out = score_job(job("结构设计工程师", city="杭州", salary="15-25K"),
                        prof, experiences=EXPERIENCES)
        self.assertLessEqual(out["score"], 100)
        self.assertGreaterEqual(out["score"], 0)

    def test_reason_is_readable(self):
        """理由要写清楚是哪条经历命中的。"""
        out = score_job(job("结构设计工程师"), PROFILE, experiences=EXPERIENCES)
        hit = [r for r in out["reasons"] if "方向匹配" in r][0]
        self.assertIn("结构设计工程师", hit)


if __name__ == "__main__":
    unittest.main(verbosity=2)
