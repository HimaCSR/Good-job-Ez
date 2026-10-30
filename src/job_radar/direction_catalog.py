"""**方向分类** —— 把岗位归到「电商运营」「建筑施工管理」这类**方向**。

## 用户诉求（原文）

> 同类型岗位只留最高分的意思是：
> 例如：电商运营（速卖通、ozon、阿里国际站、虾皮等国际电商平台相关的
> 运营工作归为一类）、建筑施工管理等方向归为一类、AI产品开发等方向归为一类
> 由 Agent 评估用户经历，确定用户可选方向、根据可选方向每天只推荐
> **单个方向中评分最高的 5 条**简历内容、按评分进行排序。

## 为什么需要这个模块

**「类型」不是标题的字面去噪。**

- 字面去噪（去掉「助理/专员/主管」）→ 只能把**同一措辞**归一
- **方向分类** → 能把「速卖通运营」「ozon运营」「阿里国际站运营」
  「虾皮运营」**全部归到「电商运营」**

这两个是**不同层级**的东西：

| 层级 | 例子 | 用途 |
| --- | --- | --- |
| **具体岗位** | 速卖通运营专员 | 池子里的一条 |
| **方向** | 电商运营 | 推荐的单位 |

→ 推荐单位是**方向**（每天推一个方向的 5 条）。

## 分类怎么做的

**两级**：

1. **规则分类**（`RULES`）—— 确定性的、可测试的、零成本
   「速卖通/ozon/虾皮/亚马逊/阿里国际站 + 运营」→ `电商运营`
2. **Agent 分类**（兜底）—— 规则没命中时，交给 Agent 判断

规则优先 —— 因为**可预测、可测试、不烧 token**。

## 规则表怎么组织的

**「平台词 + 职能词」组合**，而不是穷举岗位名：

```
平台: 速卖通 ozon 虾皮 shopee 亚马逊 amazon ebay 阿里国际站 拼多多 抖音
职能: 运营 推广 选品 客服 广告 投放
```

→ 「速卖通运营」「ozon运营专员」「虾皮店铺运营」都命中 **平台+职能** → `电商运营`。

同理：

```
建筑: 建筑 施工 土建 工地 现场 装饰 幕墙 钢筋 模板 监理 造价
AI:   AI 人工智能 大模型 LLM 算法 机器学习 AIGC
```

## 为什么不只靠关键词

**关键词会把不同方向混在一起**：

- 「运营」→ 电商运营 / 新媒体运营 / 直播运营 / 物流运营 **全都命中**
- 「设计」→ UI设计 / 平面设计 / 结构设计 / 室内设计 **全都命中**

→ 所以关键词**必须成组**（平台词 + 职能词），且**每个方向有独立的词表**。

**泛词单独出现 → 不分类**（归到 `其它`），宁可漏也不要错分。

## 一个方向一条规则

`DirectionRule(name, keywords, co_keywords=None, exclude=None)`

- `keywords` —— 该方向的**特征词**（任一命中即算）
- `co_keywords` —— **协同词**（需要跟 keywords 同时命中才算）——
  用来区分同词不同义（「运营」要配合平台词才算电商运营）
- `exclude` —— **排除词**（命中就否决）——
  「新媒体运营」里有「运营」但不含平台词 → 排除掉电商规则
"""


import re

__all__ = [
    "DirectionRule", "RULES", "classify", "classify_many",
    "direction_names", "UNKNOWN",
]

# **未分类** —— 规则没命中
UNKNOWN = "其它"


class DirectionRule(object):
    """一个方向的分类规则。

    ## 三段式

    - `keywords` —— **特征词**，任一命中即算这个方向
    - `co_keywords` —— **协同词**，必须同时命中（区分同词不同义）
    - `exclude` —— **排除词**，命中就否决这个方向
    """

    def __init__(self, name, keywords=(), co_keywords=(), exclude=(),
                 aliases=()):
        self.name = name
        self.keywords = tuple(keywords)
        self.co_keywords = tuple(co_keywords)
        self.exclude = tuple(exclude)
        # **别名** —— 方向名本身的同义写法（「电商运营」=「跨境电商」）
        self.aliases = tuple(aliases)

    def matches(self, text):
        """这段文字属不属于这个方向。"""
        low = (text or "").lower()
        if not low:
            return False
        for bad in self.exclude:
            if bad.lower() in low:
                return False
        if self.co_keywords:
            # **协同词必须命中** —— 否则否决
            if not any(c.lower() in low for c in self.co_keywords):
                return False
        return any(k.lower() in low for k in self.keywords)


# ── 词表 ────────────────────────────────────────────────────────────────────
#
# **分四层**：
#
# | 层 | 例子 | 作用 |
# | --- | --- | --- |
# | **平台** | 速卖通 ozon 虾皮 amazon 阿里国际站 | 电商方向的核心识别 |
# | **职能** | 运营 推广 选品 广告 投放 | 配合平台词 |
# | **场景** | 直播 短视频 私域 | 新媒体方向 |
# | **领域** | 建筑 施工 土建 监理 | 建筑方向 |

# **电商平台**（国际 + 国内）
ECOM_PLATFORMS = (
    "速卖通", "ozon", "虾皮", "shopee", "亚马逊", "amazon", "ebay", "易贝",
    "阿里国际站", "国际站", "alibaba", "阿里巴巴国际", "lazada", "temu",
    "shein", "希音", "拼多多", "tiktok", "抖音电商", "小红书", "得物",
    "wish", "etsy", "mercari", "yoho", "philips",
    # **短视频平台也算电商平台** ——
    # 「抖音账号运营」「快手店铺运营」→ 也是做电商/内容的平台运营。
    "抖音", "快手", "视频号",
)

# **电商职能**
ECOM_FUNCS = (
    "运营", "推广", "选品", "客服", "广告", "投放", "流量", "listing",
    "店铺", "跨境", "外贸", "外贸业务", "erp", "仓储", "履约",
)

# **新媒体 / 内容**
NEW_MEDIA = (
    "新媒体", "自媒体", "短视频", "直播", "内容运营", "社媒", "小红书运营",
    "抖音运营", "快手", "b站", "哔哩", "公众号", "视频号", "kol", "koc",
    "主播", "编导", "文案", "品牌营销", "品牌策划", "seo", "sem",
    # **红人/达人** —— 海外红人运营 = 找 KOL 带货 = 新媒体
    "红人", "达人", "tiktok运营", "海外tiktok",
)

# **建筑 / 土木 / 施工**
CONSTRUCTION = (
    "建筑", "施工", "土建", "工地", "现场管理", "装饰", "装修", "幕墙",
    "钢筋", "模板", "混凝土", "砌筑", "脚手架", "塔吊", "深基坑", "桩基",
    "监理", "造价", "预算", "招投标", "图纸", "审图", "深化设计", "bim",
    "施工员", "安全员", "质量员", "资料员", "测量员", "试验员",
    "总包", "总承包", "监理员", "bjl", "jll", "土建技术",
    # **结构相关** —— 土木结构是建筑方向
    "结构设计", "钢结构", "混凝土结构", "结构工程",
)

# **AI / 算法**
AI = (
    "ai", "人工智能", "大模型", "llm", "算法", "机器学习", "深度学习",
    "aigc", "提示词", "prompt", "智能体", "agent", "神经网络", "计算机视觉",
    "nlp", "自然语言", "推荐算法", "深度seek", "chatgpt", "多模态", "向量",
    "知识图谱", "语音识别", "rAG",
)

# **软件 / 前端 / 后端**
SOFTWARE = (
    "前端", "后端", "java", "python", "go语言", "golang", "c++", "c#", ".net",
    "php", "node", "react", "vue", "angular", "小程序", "安卓", "ios",
    "android", "web", "全栈", "架构师", "开发工程师", "测试开发",
    "unity", "ue", "虚幻", "游戏开发", "服务器", "运维", "devops",
    "数据库", "mysql", "redis", "linux", "docker", "k8s",
)

# **设计**
DESIGN = (
    "平面设计", "ui设计", "交互设计", "视觉设计", "室内设计", "景观设计",
    "服装设计", "产品设计", "工业设计", "插画", "原画", "ui", "ux",
)

# **销售 / 商务**
SALES = (
    "销售", "商务", "客户经理", "大客户", "渠道", "经销商", "bd",
    "售前", "售后", "招商", "经销",
)

# **数据 / 运营分析**
DATA = (
    "数据分析", "数据运营", "商业分析", "bi", "报表", "数据仓库", "数据治理",
    "sql", "excel",
)


# ── 规则表 ──────────────────────────────────────────────────────────────────
#
# **顺序重要** —— 先命中的赢。
#
# 「新媒体运营」含「运营」→ 如果电商规则在前会被误分
# → 所以**新媒体在电商前面**，且电商规则**要求协同词**（平台词）。

RULES = [
    # ── 电商 ──
    DirectionRule(
        "电商运营",
        keywords=ECOM_FUNCS,
        co_keywords=ECOM_PLATFORMS,
        # **排除新媒体** —— 「新媒体运营」也含「运营」
        exclude=("新媒体", "自媒体", "短视频", "直播",
                 "品牌策划", "品牌营销", "内容运营"),
        aliases=("跨境电商", "跨境电商运营", "国际电商", "海外电商", "电商"),
    ),
    DirectionRule(
        "电商运营",
        # **「跨境电商」本身就够明确** —— 不含具体平台词也要能归类。
        #
        # 本机踩过：「跨境电商运营」不含任何平台词
        # → 电商规则要求协同词 → 不命中 → 掉进「其它」。
        keywords=("跨境电商", "跨境运营", "国际电商", "海外电商", "外贸电商",
                  "进出口", "外贸运营",
                  # **纯电商词** —— 「电商运营」不含任何平台词
                  #
                  # 本机踩过：「电商运营」「国内电商运营主管」「电商运营专员」
                  # 全部掉进「其它」→ 推送推出来一堆「其它」。
                  # 但「电商运营」本身**就是**电商方向，够明确。
                  "电商运营", "电商专员", "电商助理", "电商",
                  # **外贸** —— 「外贸业务员」也是跨境电商的一部分
                  "外贸业务", "外贸业务员", "外贸销售"),
        exclude=("新媒体", "短视频", "直播"),
    ),
    DirectionRule(
        "电商运营",
        # **国内电商平台直接命中**（不需要协同词 —— 「拼多多运营」够明确）
        keywords=("拼多多运营", "抖店", "抖音电商", "小红书电商", "淘宝运营",
                  "天猫运营", "京东运营", "淘宝客", "代运营"),
        exclude=("新媒体", "短视频", "直播"),
    ),

    # ── 用户运营（私域/社群/会员）──
    #
    # **不算数据分析** —— 「私域运营」是运营岗，不是分析岗。
    #
    # 本机踩过：私域在 DATA 的词表里 → 「私域运营」被分成「数据分析」。
    DirectionRule(
        "用户运营",
        keywords=("私域", "社群运营", "用户运营", "会员运营", "私域运营",
                  "社群维护", "用户增长"),
        exclude=("数据分析", "分析师"),
    ),

    # ── 新媒体 / 内容 ──
    DirectionRule(
        "新媒体运营",
        keywords=NEW_MEDIA,
        exclude=(),
        aliases=("内容运营", "自媒体运营", "短视频运营"),
    ),

    # ── 建筑 / 土木 ──
    DirectionRule(
        "建筑施工管理",
        keywords=CONSTRUCTION,
        exclude=("平面设计", "室内设计", "景观设计"),
        aliases=("建筑施工", "施工管理", "土建", "土木", "建筑工程",
                 "施工员", "现场管理", "监理"),
    ),

    # ── AI / 算法 ──
    DirectionRule(
        "AI产品开发",
        keywords=AI,
        exclude=(),
        aliases=("人工智能", "算法", "大模型", "AI开发"),
    ),

    # ── 软件开发 ──
    DirectionRule(
        "软件开发",
        keywords=SOFTWARE,
        exclude=("ai", "人工智能", "大模型", "算法"),
        aliases=("前端开发", "后端开发", "全栈开发", "开发工程师"),
    ),

    # ── 设计 ──
    DirectionRule(
        "设计",
        keywords=DESIGN,
        exclude=("土建", "结构", "深化设计", "施工图"),
        aliases=("平面设计", "UI设计", "交互设计"),
    ),

    # ── 数据 ──
    DirectionRule(
        "数据分析",
        keywords=DATA,
        exclude=(),
        aliases=("数据运营", "BI"),
    ),

    # ── 供应链 / 物流 ──
    DirectionRule(
        "供应链物流",
        keywords=("供应链", "物流", "仓储", "配送", "调度", "货运", "采购",
                  "货代", "报关", "库存", "履约", "干线", "承运"),
        exclude=(),
        aliases=("物流", "仓储", "采购"),
    ),

    # ── 销售 ──
    DirectionRule(
        "销售",
        keywords=SALES,
        exclude=("销售运营",),
        aliases=("销售顾问", "商务拓展", "BD"),
    ),
]

# **方向的显示名映射** —— 别名归到主名
_ALIAS_MAP = {}
for _rule in RULES:
    for _a in _rule.aliases:
        _ALIAS_MAP[_a] = _rule.name


def direction_names():
    """所有规则方向名（去重、保序）。"""
    out = []
    for r in RULES:
        if r.name not in out:
            out.append(r.name)
    return out


def classify(text, extra_rules=None):
    """一段文字 → 方向名。

    ## 参数

    - `text` —— 岗位标题 + JD（拼一起，命中任一即可）
    - `extra_rules` —— **Agent 给的额外规则**（用户自定义方向）

    ## 返回

    方向名，或 `UNKNOWN`（"其它"）。

    ## 顺序

    1. **用户自定义规则**（`extra_rules`）优先 —— 用户说了算
    2. **内置规则表**（`RULES`）按顺序，第一个命中的赢
    3. 都不命中 → `UNKNOWN`
    """
    rules = list(extra_rules or []) + list(RULES)
    for rule in rules:
        try:
            if rule.matches(text):
                return rule.name
        except Exception:
            continue
    return UNKNOWN


def classify_many(items, key_fn=None, extra_rules=None):
    """批量分类。

    ## 参数

    - `items` —— 岗位列表
    - `key_fn` —— 取文字的函数（默认直接用 dict 的 title+description）
    - `extra_rules` —— 用户自定义规则

    ## 返回

    `[(原对象, 方向名), ...]`
    """
    if key_fn is None:
        def key_fn(j):
            return " ".join(str(j.get(k) or "") for k in
                           ("title", "description", "jd_text", "company"))
    out = []
    for it in items:
        try:
            out.append((it, classify(key_fn(it), extra_rules)))
        except Exception:
            out.append((it, UNKNOWN))
    return out
