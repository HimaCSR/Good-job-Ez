"""新用户首次使用的路径 —— 装完能不能真的用起来。

## 为什么测这个

插件要发布给别的用户。检查了一遍，发现**三个真问题**：

### ① `ProfileIn` 没有 `title_keywords_primary` 字段

界面上有「主攻方向」输入框，前端也把它放进 payload 了，
但**后端模型里没这个字段** → Pydantic **直接丢掉** →

    填了 → 保存 → 刷新 → 没了

而且不会有任何报错 —— 保存接口返回 `{"ok": true}`。

### ② `cities` 的 description 写错了

`plugin.yaml` 里写「要抓的城市**码**列表（如 [551, 763, 3150]）」，
但代码只认**城市名**（`city_codes.cities_to_codes` 翻译）。

新用户照着描述填码 → `cities_to_codes(["551","763"])` 返回 `[]`
→ **静默退回默认城市（杭州）**，用户完全不知道。

### ③ 新用户没有任何画像

`load_profile()` 读不到文件就返回**空画像** ——
方向、技能、城市全空 → 所有岗位分都很低 → 看起来像插件坏了。

所以：
- ① 用测试锁住（模型必须有主攻字段）
- ② 描述改成「填城市名」
- ③ 桌面端加引导条 + 「填一份示例」按钮

## 测什么

1. `ProfileIn` 有 `title_keywords_primary`，且能存住
2. `cities_to_codes` 认城市名、**不认码**（码会被跳过 → 退回默认）
3. `plugin.yaml` 的 `cities` 描述说的是**城市名**
4. `plugin.yaml` 的 `keywords` 描述提到「空 = 抓不到」
5. 桌面端有引导条和「填一份示例」
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from city_codes import cities_to_codes  # noqa: E402


def _plugin_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestProfileModelKeepsPrimaryDirection(unittest.TestCase):
    """**① 主攻方向必须能存住** —— 模型里漏字段 = 填了白填。"""

    def test_profile_in_has_primary_field(self):
        from dashboard.plugin_api import ProfileIn
        fields = ProfileIn.model_fields
        self.assertIn("title_keywords_primary", fields,
                      "ProfileIn 没有 title_keywords_primary —— "
                      "界面填的主攻方向会被 Pydantic 丢掉")
        self.assertIn("title_keywords", fields)

    def test_primary_survives_model(self):
        from dashboard.plugin_api import ProfileIn
        m = ProfileIn(title_keywords_primary=["跨境电商运营"],
                      title_keywords=["结构设计"],
                      skills=["亚马逊"])
        d = m.model_dump()
        self.assertEqual(d["title_keywords_primary"], ["跨境电商运营"])
        self.assertEqual(d["title_keywords"], ["结构设计"])


class TestCitiesDescriptionMatchesImplementation(unittest.TestCase):
    """**② 描述说的和代码做的一致** —— 否则用户照着填却没反应。"""

    def _schema_text(self):
        with open(os.path.join(_plugin_root(), "plugin.yaml"),
                  encoding="utf-8") as f:
            return f.read()

    def test_description_says_city_names(self):
        text = self._schema_text()
        m = re.search(r"^  cities:.*$", text, re.M)
        self.assertIsNotNone(m, "plugin.yaml 里没有 cities 配置")
        line = m.group(0)
        self.assertIn("城市名", line,
                      "cities 的描述没说清楚要填城市名（实际只认城市名）")
        self.assertNotIn("[551, 763, 3150]", line,
                         "cities 的描述还在举城市码的例子 —— "
                         "照着填码会被静默忽略")

    def test_keywords_description_mentions_empty(self):
        text = self._schema_text()
        m = re.search(r"^  keywords:.*$", text, re.M)
        self.assertIsNotNone(m)
        self.assertIn("空", m.group(0),
                      "keywords 的描述该说明「空 = 抓不到任何东西」")

    def test_codes_are_not_accepted_as_city_names(self):
        """**填码会被跳过** —— 这就是描述必须写清楚的原因。"""
        self.assertEqual(cities_to_codes(["重庆", "广州"]), ["551", "763"])
        # 填码 → 空 → 调用方会退回默认城市（杭州）
        self.assertEqual(cities_to_codes(["551", "763"]), [])


class TestOnboardingHints(unittest.TestCase):
    """**③ 新用户要看得见引导** —— 否则不知道从哪开始。"""

    def _plugin_js(self):
        with open(os.path.join(_plugin_root(), "desktop", "plugin.js"),
                  encoding="utf-8") as f:
            return f.read()

    def test_has_sample_profile(self):
        src = self._plugin_js()
        self.assertIn("SAMPLE_PROFILE", src,
                      "没有示例画像 —— 新用户不知道每个字段填什么")

    def test_sample_profile_is_complete(self):
        """示例要覆盖关键字段。"""
        src = self._plugin_js()
        m = re.search(r"const SAMPLE_PROFILE = \{(.*?)\n\}", src, re.S)
        self.assertIsNotNone(m, "找不到 SAMPLE_PROFILE")
        body = m.group(1)
        for key in ("title_keywords_primary", "title_keywords", "skills",
                    "cities", "min_salary"):
            self.assertIn(key, body,
                          "示例画像缺 %s —— 用户看不到这一项长什么样" % key)

    def test_profile_view_shows_guide_when_blank(self):
        src = self._plugin_js()
        self.assertIn("isBlank", src,
                      "个人信息页没有「还没填」的判断 —— 新用户看不到引导")
        self.assertIn("填一份示例", src,
                      "没有「填一份示例」按钮")

    def test_settings_view_warns_without_keywords(self):
        src = self._plugin_js()
        self.assertIn("noKeywords", src,
                      "设置页没有「没关键词」的提示 —— 抓不到岗位却不知道为什么")


if __name__ == "__main__":
    unittest.main(verbosity=2)
