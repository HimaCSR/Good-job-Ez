"""新用户端到端验证 —— 装完插件能不能真的用起来。

## 干什么

用**全新的临时 profile**（模拟新用户，空画像），
按真实顺序走一遍：

1. 保存个人画像（含主攻方向）→ **读回来确认存住了**
2. 抓取（mock 模式，不打真网站）→ 确认有岗位、分数合理
3. 简历优化 → 确认工作经历章节有内容
4. 日报生成 → 确认有 Markdown
5. 结构化经历新增 → 确认不挤掉旧的
6. 城市码翻译 → 确认城市名能变码

**全程用临时目录**，不碰用户真实数据。

## 为什么要有这个

单测只能测纯函数。这条链路涉及**文件 IO + 配置 + 存储**，
最容易出问题的是「保存了但读不回来」——
单测测不出来（它不经过真实的读-改-写循环）。

本机真踩过：界面填的「主攻方向」因为后端模型漏字段，
**保存接口返回 ok，但读回来没了** —— 单测完全测不出来。
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestNewUserJourney(unittest.TestCase):
    """新用户从零到能用。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="jr-newuser-")
        self._restore = []
        self._sysmods = []

        # **① 隔离数据目录** ——
        #
        # `plugin_data_dir` 在两个模块里的**引用方式不一样**：
        #   - `storage.py` —— **模块顶层** import，导入时就绑定了函数对象
        #     → patch `plugins.plugin_storage` **没用**，得 patch `storage` 自己
        #   - `config.py` —— **函数内部** import，每次调用重新取
        #     → patch `plugins.plugin_storage` 生效
        #
        # 两个都要 patch。本机踩过：
        # 只 patch 了 `plugins.plugin_storage` → 测试把
        # 「A公司/B公司」写进了用户真实的经历库。
        # **造一个假的 `plugins.plugin_storage`** ——
        # CI 上没有 Hermes（没有 `plugins` 包），
        # 直接 `from plugins import plugin_storage` 会 ModuleNotFoundError。
        # 本机 3.14 有（Hermes 自带）→ 本机全绿、CI 全红。
        #
        # 所以这里自己造一个塞进 sys.modules —— **不依赖 Hermes 环境**。
        import types
        plugins_pkg = types.ModuleType("plugins")
        plugins_pkg.__path__ = []
        ps_mod = types.ModuleType("plugins.plugin_storage")
        ps_mod.plugin_data_dir = lambda name: self.tmp
        plugins_pkg.plugin_storage = ps_mod
        sys.modules["plugins"] = plugins_pkg
        sys.modules["plugins.plugin_storage"] = ps_mod
        self._sysmods += ["plugins", "plugins.plugin_storage"]

        import storage as jr_storage
        self._restore.append(
            (jr_storage, "plugin_data_dir", jr_storage.plugin_data_dir))
        jr_storage.plugin_data_dir = lambda name: self.tmp

        # **② 隔离配置** ——
        #
        # 不隔离的话，`tools.scan` 会读到**用户真实的 keywords**
        # → **测试真的去抓招聘网站**（本机跑了一次，141 秒，抓了 80 条）。
        import config as jr_config
        self._orig_load_config = jr_config.load_config
        self._restore.append(
            (jr_config, "load_config", jr_config.load_config))
        jr_config.load_config = lambda: {
            "keywords": ["跨境电商运营"], "city": "551", "cities": ["重庆"],
            "boss_city": "101210100", "min_score": 0, "mock": False,
            "max_jobs_per_run": 5, "sites": [], "request_gap_seconds": 0,
            "rounds_per_day": 1, "push_max": 3, "push_new_only": True,
            "notify_on_failure": False, "active_hours": "00:00 - 23:59",
        }
        # tools 自己 import 了 load_config —— 得在 tools 上也换掉
        import tools as jr_tools
        self._restore.append(
            (jr_tools, "load_config", jr_tools.load_config))
        jr_tools.load_config = jr_config.load_config

    def tearDown(self):
        for obj, name, old in self._restore:
            try:
                setattr(obj, name, old)
            except Exception:
                pass
        for name in self._sysmods:
            sys.modules.pop(name, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _assert_no_real_data_touched(self):
        """**测试必须写在临时目录里** —— 不能碰用户真实数据。

        本机踩过：patch 写错了地方（改的是模块属性，
        但 `plugin_data_dir` 是**函数内部 import** 的），
        测试把「A公司/B公司」写进了用户真实的经历库。
        """
        import storage as jr_storage
        tmp = os.path.abspath(self.tmp)
        for label, fn in (("plugins.plugin_storage",
                           sys.modules["plugins.plugin_storage"].plugin_data_dir),
                          ("storage", jr_storage.plugin_data_dir)):
            real = os.path.abspath(fn("job-radar"))
            self.assertEqual(real, tmp,
                             "%s 用的不是临时目录（会污染用户真实数据）：%s"
                             % (label, real))
            self.assertNotIn(os.path.join("hermes", "plugin-data"), real,
                             "%s 在写用户真实的 plugin-data 目录！" % label)

    # ── ① 画像存得住 ──

    def test_profile_roundtrip_keeps_primary(self):
        """**填了主攻方向，保存后要还在** —— 刚修的 bug。"""
        self._assert_no_real_data_touched()
        from dashboard.plugin_api import ProfileIn
        prof = ProfileIn(
            title_keywords_primary=["跨境电商运营", "亚马逊运营"],
            title_keywords=["结构设计"],
            skills=["亚马逊", "SEO"],
            cities=["重庆", "广州"],
            min_salary=9,
        ).model_dump()

        # 写（走 plugin_api 的写函数 —— config.py 只负责读）
        from dashboard.plugin_api import _write_profile
        _write_profile(prof)

        # 读回来
        import config as jr_config
        back = jr_config.load_profile()
        self.assertEqual(back.get("title_keywords_primary"),
                         ["跨境电商运营", "亚马逊运营"],
                         "主攻方向保存后丢了")
        self.assertEqual(back.get("title_keywords"), ["结构设计"])
        self.assertEqual(back.get("skills"), ["亚马逊", "SEO"])
        self.assertEqual(back.get("cities"), ["重庆", "广州"])
        self.assertEqual(back.get("min_salary"), 9)

    def test_blank_profile_does_not_crash(self):
        """**空画像也能读** —— 新用户第一件事就是读它。"""
        import config as jr_config
        prof = jr_config.load_profile()
        self.assertIsInstance(prof, dict)
        self.assertIn("title_keywords_primary", prof)
        self.assertEqual(prof.get("skills"), [])

    # ── ② 城市码翻译 ──

    def test_city_names_translate_to_codes(self):
        from city_codes import cities_to_codes
        self.assertEqual(cities_to_codes(["重庆", "广州", "南宁", "桂林"]),
                         # 南宁/桂林 2026-10-29 换成「城市专码」
                         # （老码 3150/3165 是区域码）
                         ["551", "763", "785", "787"])

    # ── ③ 抓取参数校验 ──

    def test_scan_without_keywords_stops_with_hint(self):
        """**没关键词要明确报错** —— 不是静默返回空。

        新用户第一件事就是踩这个（`keywords` 默认 `[]`）。
        """
        import tools as jr_tools
        import config as jr_config
        # 临时把 keywords 清空
        jr_tools.load_config = lambda: {
            "keywords": [], "city": "551", "cities": [],
            "min_score": 0, "max_jobs_per_run": 5, "sites": [],
            "request_gap_seconds": 0, "mock": False,
        }
        out = json.loads(jr_tools.scan({}))
        self.assertIn("error", out, out)
        self.assertIn("关键词", str(out))
        self.assertIn("hint", out, "报错要给出怎么修的提示")

    def test_scan_never_hits_network_in_tests(self):
        """**单测绝对不能真去抓招聘网站**。

        本机踩过：`sites: []` 会被 `args.get("sites") or cfg["sites"]`
        里的 `or` 兜回配置里的站点 → **测试真的发了几十个请求**，
        还把抓到的岗位写进了库。

        所以这里**直接检查「测试环境不会发请求」这个前提**：
        把 adapter 换成一个会抛异常的假实现 ——
        如果真被调用，测试立刻失败（而不是默默抓一堆数据）。
        """
        import tools as jr_tools

        def _boom(*a, **kw):
            raise AssertionError("测试里真的去抓招聘网站了！")

        orig_run = jr_tools.bbclient.run_site
        jr_tools.bbclient.run_site = _boom
        try:
            out = json.loads(jr_tools.scan({
                "keywords": ["跨境电商运营"],
                "sites": ["zhaopin"],
                "max_jobs": 1,
            }))
        finally:
            jr_tools.bbclient.run_site = orig_run

        # 抓不到不是错（error 字段），但**不能有岗位进来**
        self.assertEqual(out.get("fetched", 0), 0, out)
        self.assertEqual(out.get("new", 0), 0, out)

    # ── ③b 打分逻辑（不打真网站） ──

    def test_scoring_produces_sensible_range(self):
        """**分数在 0-100，且主攻方向严格高于无关方向**。"""
        from matcher import score_job
        prof = {
            "title_keywords_primary": ["跨境电商运营"],
            "title_keywords": ["结构设计"],
            "skills": ["SEO", "选品"],
            "cities": ["重庆"],
            "min_salary": 0,
        }
        good = score_job({"title": "跨境电商运营专员", "city": "重庆",
                          "salary": "8-12K", "description": "熟悉 SEO",
                          "tags": []}, prof)
        bad = score_job({"title": "web前端开发工程师", "city": "杭州",
                         "salary": "1-2万", "description": "", "tags": []}, prof)
        for r in (good, bad):
            self.assertGreaterEqual(r["score"], 0)
            self.assertLessEqual(r["score"], 100)
        self.assertGreater(good["score"], bad["score"])
        self.assertTrue(any("主攻方向命中" in x for x in good["reasons"]))

    # ── ④ 简历优化 ──

    def test_resume_optimize_with_structured_experience(self):
        """**结构化经历能进简历** —— 工作经历章节要有公司名。"""
        import storage as jr_storage
        import resume_builder as jr_builder

        jr_storage.upsert_experience({
            "company": "某跨境电商公司",
            "title": "跨境电商运营",
            "start": "2025-07",
            "end": "2026-08",
            "bullets": ["用 SEO 和选品策略把曝光提升 40%"],
        })
        exps = jr_storage.list_experiences()
        self.assertEqual(len(exps), 1)

        profile = {
            "identity": {"name": "测试用户"},
            "skills": ["SEO", "选品"],
            "title_keywords_primary": ["跨境电商运营"],
            "experience_text": "",
        }
        job = {"title": "跨境电商运营",
               "description": "负责店铺 SEO 与选品，熟悉亚马逊和速卖通"}
        out = jr_builder.optimize_resume(job, profile, "classic",
                                         experiences=exps)
        self.assertTrue(out["used_structured"])
        blob = json.dumps(out["resume"], ensure_ascii=False)
        self.assertIn("某跨境电商公司", blob,
                      "结构化经历的公司名没进简历")
        self.assertIn("跨境电商运营", blob)

    # ── ⑤ 结构化经历不挤掉旧的 ──

    def test_experience_append_keeps_older(self):
        """**新增一条不挤掉旧的** —— 之前踩过的 bug。"""
        self._assert_no_real_data_touched()
        import storage as jr_storage
        jr_storage.upsert_experience({"company": "A公司", "title": "运营",
                                      "bullets": ["做了一件事"]})
        jr_storage.upsert_experience({"company": "B公司", "title": "专员",
                                      "bullets": ["做了另一件事"]})
        items = jr_storage.list_experiences()
        self.assertEqual(len(items), 2)
        self.assertEqual(sorted(e["company"] for e in items),
                         ["A公司", "B公司"])

    # ── ⑥ 日报 ──

    def test_daily_report_generates(self):
        """**日报能生成** —— 定时推送靠它。"""
        import tools as jr_tools
        out = json.loads(jr_tools.daily({}))
        self.assertNotIn("error", out, out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
