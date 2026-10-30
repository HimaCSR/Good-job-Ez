"""**同类型岗位只推最高分前 3 项** 的测试。

## 用户诉求

> 同时同一类型岗位只推最高分前 3 项。

## 为什么需要

实测：主攻「跨境电商运营」→ 岗位池前 30 条**全是**跨境电商运营的
不同措辞 → 推荐列表被同一个方向刷屏 → 用户看不到别的机会。

## 测什么

1. **后端** `/jobs` 返回 `type_key` 和 `_over_type_limit`
2. **分组规则**：每类最多 3 条，多的排到最后（不删，「看全部」还要能翻到）
3. **前端去重**：折叠区默认只显示前 N 条，每类最多 3 条
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPerTypeLimit(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, HERE)
        os.environ["JOB_RADAR_HOT_RELOAD"] = "1"
        pkg = types.ModuleType("job-radar")
        pkg.__path__ = [HERE]
        pkg.__package__ = "job-radar"
        sys.modules["job-radar"] = pkg
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "api", os.path.join(HERE, "dashboard", "plugin_api.py"))
        cls.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.api)

    def test_type_key_present(self):
        """**每个岗位都有类型标识** —— 前端靠它分组。"""
        r = self.api.list_jobs(limit=10, min_score=0, per_type=3)
        self.assertIn("jobs", r)
        for j in r["jobs"]:
            self.assertIn("type_key", j)

    def test_over_limit_flagged(self):
        """**超额的岗位打标记** —— 前端要知道哪些被折叠了。"""
        r = self.api.list_jobs(limit=30, min_score=0, per_type=3)
        jobs = r["jobs"]
        # **按类型数一遍** —— 每类超额数必须对得上标记数
        counts = {}
        over = 0
        for j in jobs:
            k = j.get("type_key") or "__other__"
            counts[k] = counts.get(k, 0) + 1
            if j.get("_over_type_limit"):
                over += 1
        expected_over = sum(max(0, c - 3) for c in counts.values())
        self.assertEqual(over, expected_over,
                         "超额标记数和实际超额数对不上")

    def test_over_limit_pushed_to_back(self):
        """**超额的排到最后** —— 不删（用户「看全部」还要能翻到）。"""
        r = self.api.list_jobs(limit=30, min_score=0, per_type=3)
        jobs = r["jobs"]
        flags = [bool(j.get("_over_type_limit")) for j in jobs]
        # **False 应该在 True 前面**
        first_true = next((i for i, f in enumerate(flags) if f), len(flags))
        last_false = max((i for i, f in enumerate(flags) if not f), default=-1)
        self.assertLess(last_false, first_true,
                        "超额岗位没排到最后")

    def test_per_type_zero_disables(self):
        """**per_type=0 → 不限制**（「看全部」时用）。"""
        r = self.api.list_jobs(limit=30, min_score=0, per_type=0)
        for j in r["jobs"]:
            self.assertFalse(j.get("_over_type_limit"))

    def test_front_dedup_logic(self):
        """**前端去重：每类最多 3 条** —— 跟后端一致。"""
        r = self.api.list_jobs(limit=30, min_score=0, per_type=3)
        jobs = r["jobs"]
        seen = {}
        deduped = []
        for j in jobs:
            k = j.get("type_key") or ""
            if not k:
                deduped.append(j)
                continue
            n = seen.get(k, 0)
            seen[k] = n + 1
            if n < 3:
                deduped.append(j)
        # **每类最多 3 条**
        counts = {}
        for j in deduped:
            k = j.get("type_key") or ""
            if k:
                counts[k] = counts.get(k, 0) + 1
        for k, c in counts.items():
            self.assertLessEqual(c, 3, "类型 %r 有 %d 条" % (k, c))
        # **去重后比原来少**（说明确实折叠了）
        self.assertLess(len(deduped), len(jobs))

    def test_top_n_contains_mixed_types(self):
        """**默认显示的前 5 条不该全是同一类**。

        ## 为什么用 limit=120

        池子**顶部 30 条常常全是同一个方向**（实测 30/30 都是跨境电商运营）
        → 只取 30 条 → 去重后只剩 3 条 → 用户看不到别的机会。

        → 前端取 **120 条**（见 plugin.js 的 useJobs），
        去重后才有别的类型可选。
        """
        r = self.api.list_jobs(limit=120, min_score=0, per_type=3)
        jobs = r["jobs"]
        seen = {}
        deduped = []
        for j in jobs:
            k = j.get("type_key") or ""
            if not k:
                deduped.append(j)
                continue
            n = seen.get(k, 0)
            seen[k] = n + 1
            if n < 3:
                deduped.append(j)
        top5 = deduped[:5]
        types = set(j.get("type_key") for j in top5 if j.get("type_key"))
        self.assertGreaterEqual(len(types), 2,
                                "前 5 条全是同一类：%r" % (types,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
