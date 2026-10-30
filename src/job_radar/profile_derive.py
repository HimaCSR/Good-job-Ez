"""**从经历里抽方向词和技能词** —— 让画像自动跟着经历更新。

## 为什么要有这个

用户诉求：

> 每次用户保存插件内的个人信息保存/更新，便重新根据经历内容
> 更新期望内容标签，保证抓取的岗位更加契合用户

**手填的方向词会过期** —— 用户换了工作方向，画像还写着老方向
→ 抓回来的岗位全是老方向的 → 分数永远不对。

→ **经历是原料** —— 经历变了，方向就该跟着变。

## 抽什么

| 类别 | 来源 | 落到画像哪 |
| --- | --- | --- |
| **方向词** | 职位名 + bullets 里的**岗位/业务名** | `title_keywords`（次要方向） |
| **技能词** | bullets 里的**工具/技术/能力** | `skills` |

## 为什么方向词不落到「主攻方向」

主攻方向是**用户的战略选择**（30 分 vs 15 分），
自动抽的词**只是「你干过什么」**—— 那是事实，不是选择。

→ **自动抽的词进次要方向**（15 分），
主攻方向**永远由用户自己定**。

→ 不覆盖用户手填的词，只**补充**。

## 三个坑

### ① 职位名直接当方向词 → 匹配太宽

「实习生」当方向词 → 所有带「实习」的岗位都命中 → 分数虚高。

→ **过滤掉泛称**（实习生/工程师/专员/助理/主管…）。

### ② bullets 里的项目名不是方向

「三亚自贸港旅游航空总部（设计、施工）总承包项目」是**项目名**，
不是方向 → 当方向词会匹配不到任何岗位。

→ **只抽「通用业务词 + 职位名」**，项目名靠通用词表过滤。

### ③ 「工作描述：」「工作内容：」这类标记词

→ 直接进词表 → 匹配所有岗位。

→ 停用词表过滤。
"""

import re

__all__ = [
    "extract_from_experiences",
    "apply_to_profile",
    "GENERIC_TITLE_WORDS",
    "STOP_WORDS",
]


# ── 泛称（不能当方向词） ────────────────────────────────────────────────────
#
# 「实习生」「工程师」这类词 —— 几乎每个岗位标题里都有。
# 当方向词 → 所有岗位都命中 → 分数虚高 → 推荐全是噪音。
GENERIC_TITLE_WORDS = {
    "实习生", "实习", "工程师", "专员", "助理", "主管", "经理", "总监",
    "负责人", "技术员", "文员", "职员", "员工", "临时工", "兼职", "全职",
    "人员", "岗位", "职位", "英才", "管培生", "储备干部", "应届生",
    "毕业生", "学徒", "顾问", "合伙人", "老板", "员工代表", "组长",
    # **太泛的通用业务词** ——
    #
    # 「运营」「质量」「客户」「销售」几乎出现在每个岗位标题里
    # → 当方向词 → 命中所有岗位 → 分数失去区分度 → 推荐全是噪音。
    #
    # 本机踩过：第一次抽出 12 个方向词，其中 4 个是「运营/质量/客户/销售」。
    "运营", "管理", "质量", "客户", "销售", "市场", "业务", "服务",
    "项目", "工作", "技术", "生产", "设计", "计划", "采购", "客服",
    "人员", "招聘", "培训", "行政", "人事", "财务", "商务", "渠道",
    "助理工程师", "技术工程师", "销售经理", "客户经理", "项目经理",
    # **「工程」「施工」单独用太宽** ——
    #
    # 「web前端开发**工程**师」会命中「工程」→ 前端岗位 +15 分
    # → **推荐里混进前端岗**。
    #
    # 本机踩过：web前端开发工程师 +15 分。
    # → 单独用时过滤，**组合词保留**（土建/建筑工程/现场管理…）。
    "工程", "施工", "建设", "装饰", "维修", "安装", "巡检", "检测",
    # **「策划」「营销」「品牌」也太宽** ——
    #
    # 「招商银行客户经理」的 bullets 里出现「营销」→ 方向词
    # → 所有带「营销」的岗位都 +15 分 → 推荐变宽。
    #
    # 本机踩过：第一次抽出「策划/营销/品牌」三个泛词。
    "策划", "营销", "品牌", "推广", "推广专员", "活动", "运营专员",
    "客户专员", "业务专员", "销售专员", "运营主管", "运营经理",
}

# ── 停用词（bullets 里的结构标记） ──────────────────────────────────────────
STOP_WORDS = {
    "工作内容", "工作描述", "工作职责", "岗位职责", "工作业绩", "项目职责",
    "项目业绩", "项目介绍", "任职要求", "岗位要求", "职位描述", "职责描述",
    "主要职责", "任职资格", "我们提供", "公司福利", "联系方式", "公司简介",
    "实习内容", "主要工作", "具体内容", "以下内容", "相关内容", "工作安排",
    "自我评价", "个人评价", "项目成果", "业绩成果", "能力要求", "技能要求",
    "任职资格要求", "岗位资格", "加分项", "优先条件", "岗位福利", "薪资待遇",
}


# ── 具体词（比泛称精确） ────────────────────────────────────────────────────
#
# **为什么要单独一张表** ——
# 「工程」「施工」单独用太宽（web前端开发**工程**师会命中），
# 但「土建工程」「建筑施工」是**真的领域词**。
#
# → 泛称表挡住单独的「工程」，这张表把具体组合捞回来。
_SPECIFIC_TERMS = [
    # 建筑 / 土建
    "土建", "建筑工程", "土木", "建筑施工", "土建施工", "建筑结构",
    "现场管理", "施工管理", "安全管理", "质量管理", "进度管理",
    "深桩", "桩基工程", "主体结构", "二次结构", "砌体工程", "抹灰工程",
    "混凝土工程", "钢筋工程", "模板工程", "脚手架工程", "装饰装修",
    "给排水工程", "暖通工程", "电气工程", "市政工程", "道路工程",
    "桥梁工程", "隧道工程", "水利工程", "景观工程", "园林工程",
    "工程管理", "工程造价", "工程资料", "工程测量", "工程试验",
    # 互联网 / 电商
    "电商运营", "跨境运营", "跨境电商", "店铺运营", "平台运营",
    "内容运营", "活动运营", "用户运营", "产品运营", "社群运营",
    "海外电商", "独立站运营", "直播运营", "新媒体运营",
    "前端开发", "后端开发", "全栈开发", "移动端开发", "软件开发",
    "测试开发", "运维开发", "数据开发", "算法开发",
    # 金融
    "银行运营", "信贷运营", "理财顾问", "保险经纪", "支付运营",
    # 其他
    "物流运营", "供应链管理", "仓储管理", "采购管理", "招商运营",
    "客户运营", "品牌运营", "渠道运营", "商务拓展",
]

# ── 方向词候选（业务/岗位领域词） ───────────────────────────────────────────
#
# **只用通用业务词** —— 项目名/公司名/地名不能当方向词。
#
# 覆盖：互联网运营、电商、建筑、土木、金融、地产、制造、教育……
_DIRECTION_TERMS = [
    # 电商 / 运营
    "跨境电商", "电商运营", "店铺运营", "商品运营", "类目运营", "选品",
    "平台运营", "社群运营", "内容运营", "活动运营", "私域运营", "直播运营",
    "新媒体运营", "用户运营", "产品运营", "海外电商", "独立站", "进出口",
    "外贸", "速卖通", "亚马逊", " Shopee", "虾皮", " Lazada", "阿里国际站",
    "物流", "仓储", "供应链", "采购", "报关", "清关", "广告投放", "推广",
    "客服", "售后", "招商", "运营专员", "运营主管", "国际站",
    # 金融 / 财务
    "银行", "信贷", "贷款", "理财", "保险", "证券", "基金", "支付",
    "清算", "风控", "催收", "信用卡", "资产", "融资", "会计", "出纳",
    "审计", "税务", "财务",
    # 建筑 / 土木
    "建筑", "土建", "结构", "施工", "监理", "造价", "预算", "招投标",
    "工程", "工地", "现场管理", "质量", "安全", "深化设计", "BIM",
    "市政", "道路", "桥梁", "给排水", "暖通", "电气", "机电",
    "装修", "装饰", "园林", "测绘", "岩土", "地基", "混凝土", "钢筋",
    # 地产 / 物业
    "地产", "物业", "置业", "招商", "策划", "销售", "案场", "中介",
    # 制造 / 工艺
    "生产", "工艺", "设备", "质量", "品控", "供应链", "仓储", "物流",
    "计划", "采购", "仓储", "车间", "装配", "焊接", "注塑", "质检",
    # 其他
    "运营", "销售", "营销", "商务", "渠道", "品牌", "推广", "招聘",
    "培训", "客服", "人事", "行政", "法务", "公共关系", "翻译",
    "教育", "培训", "教师", "课程", "教研",
]


def _norm(text):
    return (text or "").strip().lower()


def _title_candidates(title):
    """职位名 → 方向词候选。

    「跨境电商运营」→ 候选含「跨境电商运营」「跨境电商」「电商运营」
    （长词优先 —— 匹配更精确）。
    """
    t = (title or "").strip()
    if not t:
        return []
    # **整词**先入（最精确）
    out = [t]
    # **剥掉后缀**再入：「XX运营专员」→「XX运营」
    for suffix in ("运营专员", "技术专员", "销售专员", "业务专员", "专员",
                   "工程师", "技术员", "助理", "主管", "经理", "总监",
                   "实习生", "运营", "专员"):
        if t.endswith(suffix) and len(t) > len(suffix) + 1:
            out.append(t[: -len(suffix)])
            break
    # **按通用词表切**出内含的领域词
    #
    # **组合词优先** —— 「土建技术员」里「土建」是有效的领域词，
    # 但「web前端开发工程师」里「工程」不是。
    low = t.lower()
    for term in _DIRECTION_TERMS:
        term_l = term.strip().lower()
        if term_l and term_l in low:
            out.append(term.strip())
    # **被泛称表挡住的词，找更具体的组合词** ——
    # 「土建技术员」→「土建技术员」整体已在 out 里；
    # 「web前端开发工程师」→「工程」被挡 → 找「前端开发」这种具体的。
    for term in _SPECIFIC_TERMS:
        if term.lower() in low:
            out.append(term)
    # **去重 + 过滤泛称**
    seen = set()
    res = []
    for w in out:
        w = w.strip()
        if not w or len(w) < 2:
            continue
        if w in GENERIC_TITLE_WORDS:
            continue
        k = _norm(w)
        if k in seen:
            continue
        seen.add(k)
        res.append(w)
    return res


def _bullet_direction_hits(text):
    """bullets 里的业务词（按词表匹配，不猜词组）。

    ## 两张表都查

    - `_DIRECTION_TERMS` —— 通用业务词
    - `_SPECIFIC_TERMS` —— 具体组合词（现场管理/桩基工程/电商运营…）

    **具体词也要查** —— 「参与现场管理与桩基施工」里
    「现场管理」是**真的方向词**，但它不在通用词表里。

    本机踩过：测试断言「现场管理」在方向词里，实际抽不到
    → 因为它只从职位名找，bullets 里没查。
    """
    low = (text or "").lower()
    hits = []
    for term in _DIRECTION_TERMS + _SPECIFIC_TERMS:
        t = term.strip()
        if not t or t in STOP_WORDS or t in GENERIC_TITLE_WORDS:
            continue
        if t.lower() in low:
            hits.append(t)
    return hits


def extract_from_experiences(experiences, profile=None, max_direction=12,
                             max_skills=30):
    """经历列表 → (方向词, 技能词)。

    experiences: [{title, company, bullets, start, end, tags}]
    profile:     现有画像（用来**排除用户已有的词**，只报「新增的」）

    ## 返回什么

    - `directions` —— 方向词（长词优先，按出现次数排）
    - `skills` —— 技能词（从 bullets 里认出来的工具/技术）

    ## 为什么排除已有的

    用户手填的技能（CAD / Revit / 天正…）**不在经历里**（那是会的，
    不一定做过）→ **不能因为经历里没提就删掉**。

    → 只**补充**，从不删除。
    """
    from collections import Counter

    dir_counts = Counter()
    skill_counts = Counter()

    for exp in (experiences or []):
        title = exp.get("title") or ""
        company = exp.get("company") or ""
        bullets = exp.get("bullets") or []
        if isinstance(bullets, str):
            try:
                import json
                bullets = json.loads(bullets)
            except Exception:
                bullets = [bullets]
        # **tags** 也是经历的一部分（用户可能手工打了标签）
        for extra in (exp.get("tags") or []):
            if isinstance(extra, str) and extra.strip():
                for w in _title_candidates(extra.strip()):
                    dir_counts[w] += 2      # 用户自己打的标签 → 权重高

        # **职位名** —— 最可靠的方向来源
        for w in _title_candidates(title):
            dir_counts[w] += 3

        # **bullets 里的通用业务词** —— 权重低于职位名
        blob = " ".join(str(b) for b in bullets)
        for w in _bullet_direction_hits(blob):
            dir_counts[w] += 1

        # **技能词** —— 从 bullets 里认工具/技术
        for w in _skill_hits(blob):
            skill_counts[w] += 1

    # ── 过滤掉泛称 + 已有的 ──
    have_dir = {_norm(x) for x in ((profile or {}).get("title_keywords") or [])}
    have_dir |= {_norm(x) for x in
                 ((profile or {}).get("title_keywords_primary") or [])}
    have_skill = {_norm(x) for x in ((profile or {}).get("skills") or [])}

    directions = []
    seen = set()
    # **排序必须全序** —— 只按 (-次数, -长度) 排的话，
    # 同分同长的词**顺序取决于 dict 的插入顺序** →
    # 两次抽取结果可能不同 → **不幂等** → 每保存一次画像就变一次。
    #
    # 本机踩过：第二次保存又多出「质检」「选品」。
    #
    # **关键：已有的词也要参与排序** ——
    # 排除掉已有的再取前 N → 第二次抽的「剩余」跟第一次不同
    # → 截断的位置也不同 → **不幂等**。
    #
    # → 先把**全部候选**（含已有的）排好序，再依次取，
    #   遇到已有的就跳过（不重复添加），遇到新的就加。
    #   → 第一次和第二次的排序完全一致 → 结果一致。
    # **幂等的做法：已有的词也占名额**
    #
    # 排序是**稳定的**（全序）→ 每次排出来的顺序**完全一样**。
    # → 第一次跑时，前 12 个里哪些是「已有的」是确定的。
    # → 第二次跑时，**同样的位置**被同样的词占据 →
    #   已有的被跳过 → **没有新词能挤进来** → **幂等**。
    #
    # ## 之前为什么不幂等
    #
    # 之前「已有的直接 continue，不占名额」→ 第二次跑时
    # 前 12 个里的已有的被跳过 → **后面的词补上来** → 画像变长。
    #
    # 本机踩过：保存三次 → 方向词 19 → 21 → 21。
    # **幂等：先算「最终集合」，再算增量**
    #
    # ## 之前的做法为什么不幂等
    #
    # 「已有的跳过但占名额」—— 但**已有的词不在候选池里**
    # （候选池 = 从经历抽的，画像里手填的「结构设计/建筑设计」不在里面）
    # → 每跑一次就有一个新词补上来 → 画像越来越长。
    #
    # 本机踩过：保存 4 次 → 方向词 17 → 18 → 19 → 20。
    #
    # ## 正确的做法
    #
    # **最终集合 = (候选池的前 N 个) ∪ (已有的)**，
    # 其中 N 是**固定的**（比如 12）——
    # → 结果**只取决于经历**，跟画像里已有什么无关 → **幂等**。
    #
    # → 新增 = 最终集合 − 已有。
    final = []
    seen2 = set()
    for w, _c in sorted(dir_counts.items(),
                         key=lambda kv: (-kv[1], -len(kv[0]), kv[0])):
        if w in GENERIC_TITLE_WORDS or w in STOP_WORDS:
            continue
        k = _norm(w)
        if k in seen2:
            continue
        seen2.add(k)
        final.append(w)
        if len(final) >= max_direction:
            break

    directions = [w for w in final if _norm(w) not in have_dir]

    skills = []
    seen = set()
    for w, _c in sorted(skill_counts.items(),
                         key=lambda kv: (-kv[1], -len(kv[0]), kv[0])):
        if _norm(w) in seen or _norm(w) in have_skill:
            continue
        seen.add(_norm(w))
        skills.append(w)
        if len(skills) >= max_skills:
            break

    return directions, skills


# ── 技能识别 ────────────────────────────────────────────────────────────────
#
# **从 bullets 里认「工具/技术/能力」** —— 用已知词表匹配。
#
# 不用正则猜（会抽出「的」「了」这种碎片）。
_SKILL_TERMS = [
    # 办公 / 设计（用户的领域）
    "CAD", "Revit", "天正", "盈建科", "Sketch", "Photoshop", "Illustrator",
    "AutoCAD", "3DMax", "Lumion", "广联达", "同望", "品茗", "PKPM",
    "Excel", "Word", "PowerPoint", "PPT", "数据透视表", "Origin", "SPSS",
    "stata", "Matlab", "CAD二次开发",
    # 互联网 / 电商
    "速卖通", "Amazon", "亚马逊", "Shopee", "虾皮", "Lazada", "Shopify",
    "Temu", "拼多多", "抖音", "小红书", "微博", "微信", "公众号", "视频号",
    "SEO", "SEM", "PPC", "Google Ads", "Facebook", "独立站", "AliExpress",
    "Google Trends", "Sorftime", "店透视", "卖家精灵", "Helium 10",
    # 前端 / 后端
    "Vue", "React", "Angular", "jQuery", "HTML", "CSS", "JavaScript",
    "TypeScript", "Node.js", "Python", "Java", "Go", "PHP", "C++", "C#",
    "Spring", "Django", "Flask", "MySQL", "Redis", "MongoDB", "PostgreSQL",
    "Docker", "K8s", "Linux", "Git", "Jenkins", "微服务", "前后端分离",
    # 建筑 / 工程
    "BIM", "CAD", "图纸", "深化设计", "施工图", "预算", "算量", "招投标",
    "监理", "甲方", "乙方", "总包", "分包", "桩基", "主体结构", "二次结构",
    "抹灰", "砌体", "钢筋", "混凝土", "模板", "脚手架", "竣工资料",
    "实测实量", "验收", "安全文明", "施工组织", "进度计划",
    # 通用能力
    "项目管理", "团队管理", "沟通协调", "数据分析", "数据复盘", "选品",
    "listing", "Listing", "关键词", "长尾词", "转化率", "曝光量", "客单价",
    "GMV", "ROI", "ACOS", "复盘", "运营报表", "成本核算", "预算控制",
]


def _skill_hits(text):
    """bullets 文本 → 命中的技能词。"""
    low = (text or "").lower()
    hits = []
    for term in _SKILL_TERMS:
        t = term.strip()
        if not t or t in STOP_WORDS:
            continue
        if t.lower() in low:
            hits.append(t)
    return hits


# ── 合并进画像 ──────────────────────────────────────────────────────────────
#
# **只补充，不删除，不覆盖。**
#
# ## 为什么不动用户的「主攻方向」
#
# 主攻 = 战略选择（30 分）；自动抽的 = 事实（你干过什么）。
# 混在一起 → 主攻被稀释 → 分数失去区分度。

def apply_to_profile(profile, experiences, max_direction=12, max_skills=0):
    """把新抽的词合并进画像（返回**新画像**，不改原对象）。

    profile: 现有画像 dict
    返回: (新画像, 变更说明, 变更明细)

    变更说明是给人看的 —— 前端要告诉用户「根据你的经历补了这些词」。

    ## ⚠️ **默认只加方向词，不加技能**（`max_skills=0`）

    **因为加技能会把已有岗位的分数拉低**：

    ```
    技能项 = 30 分 × (命中数 / 技能总数)
    ```

    自动加了 17 个技能 → 分母从 18 变 35 → 命中数没变
    → **跨境电商运营 80 分掉到 70 分**。

    本机踩过：加技能后岗位分数集体下降，用户会觉得「越更新越不匹配」。

    而且语义上也不对：**用户的技能 = 他会的**（可以写在简历上），
    **经历里出现过的 = 他做过的** —— 两者不是一回事。
    简历要写会的，岗位匹配才用会的。

    → **技能只在用户显式要求时补**（`max_skills > 0`）。
    """
    new_directions, new_skills = extract_from_experiences(
        experiences, profile, max_direction=max_direction,
        max_skills=max_skills)

    out = dict(profile or {})
    out["title_keywords"] = list(out.get("title_keywords") or [])
    out["skills"] = list(out.get("skills") or [])

    # **用户手填的词保留在前面** —— 自动抽的词**追加**在后面。
    #
    # 用户手填的（主攻相关的次要方向）是他自己排的序 →
    # 自动抽的排在后面，不打乱他的排序。
    added_dir = []
    have = {_norm(x) for x in out["title_keywords"]}
    for w in new_directions:
        k = _norm(w)
        if k in have:
            continue
        out["title_keywords"].append(w)
        have.add(k)
        added_dir.append(w)

    added_skill = []
    if max_skills > 0:
        for w in new_skills:
            if _norm(w) in {_norm(x) for x in out["skills"]}:
                continue
            out["skills"].append(w)
            added_skill.append(w)

    note = ""
    bits = []
    if added_dir:
        bits.append("方向词 +%d（%s）" % (len(added_dir), "、".join(added_dir[:6])))
    if added_skill:
        bits.append("技能 +%d（%s）" % (len(added_skill), "、".join(added_skill[:6])))
    if bits:
        note = "根据经历补充：" + "；".join(bits)
    return out, note, {"directions": added_dir, "skills": added_skill}
