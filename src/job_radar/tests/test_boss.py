"""BOSS 直聘接入的测试。

## 为什么单独一个文件

BOSS 和智联**完全不是一个体系**：

| | 智联 | BOSS |
| --- | --- | --- |
| 城市码 | 3~4 位 `jl`（重庆=551） | **9 位** `city`（重庆=101040100） |
| 页面 | **SSR** —— `fetch` 拿 HTML，DOMParser 解析 | **SPA** —— 必须真实加载页面 |
| API | 直接 fetch 就行 | **必须在 zhipin 页面上下文里**（要 anti-content token） |
| 社区 adapter | 能用 | **超时**（没页面上下文） |

## 本轮踩到的三个坑

### ① 社区 adapter 超时

`bb-browser site boss/search` 直接报 `Daemon request timed out`。
**原因**：它没有 BOSS 页面上下文，anti-content token 拿不到。

**修法**：本地 adapter（`~/.bb-browser/sites/boss/search.js`）+
`bbclient.ensure_boss_context()` 先 open 一个 BOSS 页面。

### ② 字段名对不上

社区 adapter 返回 `title`/`company`/`salary`/`area`，
但 `FIELD_MAP["boss"]` 认的是 `name`/`brandName`/`salaryDesc`/`cityName`
→ **抓回来的岗位标题和公司全是空**。

**修法**：FIELD_MAP 两套都认，**统一词表名放后面**（覆盖前面的）。

### ③ 城市码混用

智联码喂给 BOSS → 静默抓到别的城市。
**修法**：`boss_city_codes.py` 独立码表 + `scan` 里按站点分表。

## 城市码的来源 —— **官方接口，不是猜的**

    GET https://www.zhipin.com/wapi/zpgeek/common/data/city/site.json

实测抓到 400 个城市码。我一开始**按规律猜**了 60 个，
**6 个是错的**（东莞/宜昌/株洲/洛阳/衡阳/襄阳 —— 同省城市序号记错）。
全部用官方值覆盖。

**验证脚本**：`scripts/verify-boss-city-codes.sh`
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestBossCityCodes(unittest.TestCase):
    """BOSS 城市码表。"""

    def test_codes_are_9_digits(self):
        """BOSS 城市码是 **9 位**（101040100）。"""
        from boss_city_codes import CITY_CODES
        for name, code in CITY_CODES.items():
            self.assertEqual(len(code), 9, "%s 的码 %s 不是 9 位" % (name, code))
            self.assertTrue(code.isdigit(), "%s 的码 %s 不是纯数字" % (name, code))

    def test_known_cities(self):
        """重点城市码 —— 实测过的。"""
        from boss_city_codes import CITY_CODES
        expected = {
            "北京": "101010100", "上海": "101020100",
            "天津": "101030100", "重庆": "101040100",
            "广州": "101280100", "深圳": "101280600",
            "杭州": "101210100", "成都": "101270100",
            "西安": "101110100", "武汉": "101200100",
        }
        for name, code in expected.items():
            self.assertEqual(CITY_CODES.get(name), code,
                             "%s 的码不对" % name)

    def test_does_not_reuse_zhaopin_codes(self):
        """**不能和智联码混用** —— 混用会静默抓到别的城市。"""
        from boss_city_codes import CITY_CODES
        from city_codes import CITY_CODES as ZL
        overlap = set(CITY_CODES.values()) & set(ZL.values())
        self.assertEqual(overlap, set(),
                         "BOSS 和智联的码重了：%s" % overlap)

    def test_code_for_variants(self):
        from boss_city_codes import code_for
        self.assertEqual(code_for("重庆"), "101040100")
        self.assertEqual(code_for("重庆市"), "101040100")
        self.assertEqual(code_for("广东省深圳市"), "101280600")
        self.assertEqual(code_for("火星"), "")

    def test_cities_to_codes_skips_unknown(self):
        """认不出来的城市**直接跳过** —— 不然会塞空串。"""
        from boss_city_codes import cities_to_codes
        out = cities_to_codes(["重庆", "火星", "成都", "重庆"])
        self.assertEqual(out, ["101040100", "101270100"])

    def test_nationwide_code(self):
        """全国码也是 9 位。"""
        from boss_city_codes import NATIONWIDE
        self.assertEqual(len(NATIONWIDE), 9)


class TestBossFieldMap(unittest.TestCase):
    """BOSS 字段映射 —— 两套字段名都要认。"""

    def _normalize(self, job):
        import tools
        # 下划线开头是模块内部函数 —— 用 getattr 明确取，
        # 免得 Pyright 报「不是已知属性」（实际能用）。
        return getattr(tools, "_normalize")(job, "boss")

    def test_unified_names(self):
        """统一词表名（社区 adapter 返的这套）。"""
        n = self._normalize({
            "title": "运营", "company": "某公司", "salary": "10-15K",
            "area": "重庆·渝中区", "tags": ["TikTok"], "job_id": "abc",
        })
        self.assertEqual(n["title"], "运营")
        self.assertEqual(n["company"], "某公司")
        self.assertEqual(n["salary"], "10-15K")
        self.assertEqual(n["area"], "重庆·渝中区")

    def test_api_names(self):
        """原始 API 名（本地 adapter 也返这套）。"""
        n = self._normalize({
            "name": "运营", "brandName": "某公司", "salaryDesc": "10-15K",
            "cityName": "重庆", "skills": ["TikTok"], "jobId": "abc",
        })
        self.assertEqual(n["title"], "运营")
        self.assertEqual(n["company"], "某公司")
        self.assertEqual(n["salary"], "10-15K")
        self.assertEqual(n["job_id"], "abc")

    def test_cityname_does_not_clobber_area(self):
        """**cityName 不能覆盖 area** —— area 含区县，cityName 只有城市。"""
        n = self._normalize({
            "title": "运营", "area": "重庆·九龙坡区·杨家坪",
            "cityName": "重庆",
        })
        self.assertEqual(n["area"], "重庆·九龙坡区·杨家坪")
        self.assertEqual(n["city"], "重庆")

    def test_empty_title_is_rejected(self):
        """没标题的岗位要被丢掉 —— 否则推荐页出现空行。"""
        n = self._normalize({"company": "某公司"})
        self.assertEqual(n.get("title"), "")


class TestBossScanCityRouting(unittest.TestCase):
    """`scan` 里**每个站用自己那套城市码**。"""

    def test_scan_uses_boss_codes_for_boss(self):
        """BOSS 分支要用 BOSS 码表。"""
        import inspect
        import tools
        src = inspect.getsource(getattr(tools, "scan"))
        self.assertIn("boss_city_codes", src,
                      "scan 没引用 BOSS 城市码表")
        self.assertIn('site == "boss"', src,
                      "scan 没按站点分城市码表")

    def test_fetch_site_boss_calls_ensure_context(self):
        """**BOSS 抓取前必须先确保有页面上下文** —— 否则超时。"""
        import inspect
        import tools
        src = inspect.getsource(getattr(tools, "_fetch_site"))
        self.assertIn("ensure_boss_context", src,
                      "_fetch_site 抓 BOSS 前没调 ensure_boss_context")


class TestLocalAdapter(unittest.TestCase):
    """本地 adapter 文件 —— 存在且内容对。"""

    def _adapter(self):
        import glob
        home = os.path.expanduser("~")
        path = os.path.join(home, ".bb-browser", "sites", "boss", "search.js")
        if not os.path.exists(path):
            self.skipTest("本机没装本地 BOSS adapter（别的机器上跳过）")
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_adapter_exists(self):
        self._adapter()

    def test_adapter_returns_both_field_schemas(self):
        """**两套字段名都要返** —— 社区版和本地版都得能用。"""
        src = self._adapter()
        self.assertIn("title: j.jobName", src)
        self.assertIn("name: j.jobName", src)
        self.assertIn("company: j.brandName", src)
        self.assertIn("brandName: j.brandName", src)

    def test_adapter_has_hint_on_waf(self):
        """风控时要给提示，不能只说「失败」。"""
        src = self._adapter()
        self.assertIn("hint", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
