"""岗位匹配度打分。纯函数，无 IO —— 这是唯一需要认真写单测的部分。"""

import re


# ── 岗位类型 ────────────────────────────────────────────────────────────────
#
# ## 为什么需要
#
# 用户诉求：「**同一类型岗位只推最高分前 3 项**」。
#
# 实测：用户主攻「跨境电商运营」→ 岗位池里 30 条全是
# 「跨境电商运营 / 跨境电商运营主管 / 跨境电商运营专员 / 跨境电商运营助理」
# → 推荐列表被**同一个方向的不同措辞**刷屏。
#
# → 要能认出「这 10 条其实是同一类」。
#
# ## 怎么判类型
#
# **把标题归一化**：去掉括号内容、去掉职级/修饰后缀、去掉数字和标点。
#
# ```
# 跨境电商运营助理              → 跨境电商运营
# 跨境电商运营专员（速卖通/eBay） → 跨境电商运营
# 跨境电商运营主管              → 跨境电商运营
# 国内电商运营主管              → 国内电商运营
# ```
#
# **职级后缀要全去掉** —— 助理/专员/主管/经理都是同一类岗位的
# 不同层级，**不该拆成不同类型**。

_TITLE_NOISE = [
    # **括号里的补充说明**（**任意位置**）——
    #
    # 「ebay（易贝）shopee（虾皮）跨境电商运营」→ 括号在**中间**，
    # 只去首尾括号会留下「ebayshopee跨境电商运营」
    # → 归一化不到「跨境电商运营」→ 被当成另一类 → 去重失效。
    #
    # 本机踩过：「跨境电商运营助理」和「ebay…跨境电商运营」没归到一起。
    r"[（(【\[].*?[)）】\]]",
    # 英文逗号后的补充
    r"[,，、;；|/]+.*$",
]
# **层级后缀** —— 同一岗位的不同层级，**该剥掉**
_LEVEL_SUFFIXES = [
    "实习生", "助理", "专员", "主管", "经理", "总监", "负责人",
    "工程师", "技术员", "顾问", "组长", "领班", "储备干部", "管培生",
    "员", "工", "岗", "职位",
]

# **角色词** —— 是岗位名**的一部分**，**不该剥**
#
# 「电商运营」剥掉「运营」→ 「电商」→ 太粗，
# 会把「跨境电商」和「电商运营」并成一类，也会跟别的撞。
#
# 本机踩过：剥掉后 type_key 变成「电商」，而「跨境电商运营」变「跨境电商」
# → 明明一类，分成两个桶 → 各推 3 个 → 还是刷屏。
_ROLE_SUFFIXES = ["运营"]

_TITLE_SUFFIXES = _LEVEL_SUFFIXES
_TITLE_PREFIX_NOISE = ["急招", "诚聘", "高薪", "急聘", "最新", "直招"]

# **福利/待遇噪音** —— 招聘标题常挂在后面
#
# 「亚马逊选品销售专员双休+五险一金」→ 该归到「亚马逊选品销售」
# 不去掉的话 → 每个福利组合都是**一个类型** → 去重完全失效。
_TITLE_TAIL_NOISE = [
    "双休", "五险一金", "五险", "一金", "包工作午餐", "包吃住",
    "朝九晚六", "双休包吃", "年终奖", "带薪年假", "五险一金双休",
    "免费班车", "节日福利", "定期体检", "带薪休假", "无经验可",
    "接受应届生", "接受无经验", "可接受无经验",
]


def job_type_key(title, strip_role=False):
    """岗位标题 → **类型标识**（用于「同类型只推前 N」）。

    ## 返回什么

    归一化后的类型名。空标题返回 `""`。

    ## 归一化步骤

    1. **去括号内容** —— 「跨境电商运营专员（速卖通/eBay）」→「跨境电商运营专员」
    2. **去英文逗号后的补充** —— 「电商运营，双休」→「电商运营」
    3. **去前缀噪音** —— 「急招电商运营」→「电商运营」
    4. **去职级后缀** —— 「跨境电商运营主管」→「跨境电商运营」
    5. **去数字和标点** —— 「运营2组」→「运营」

    ## 为什么职级后缀要去全

    **助理/专员/主管/经理是同一类岗位的不同层级** ——
    分成不同类型就等于没去重（还是 4 类）。

    本机踩过：不去职级后缀 → 「跨境电商运营助理」和
    「跨境电商运营主管」被当成两类 → 每类各推 3 个 → 还是刷屏。
    """
    t = str(title or "").strip()
    if not t:
        return ""
    for pat in _TITLE_NOISE:
        t = re.sub(pat, "", t)
    for pfx in _TITLE_PREFIX_NOISE:
        if t.startswith(pfx):
            t = t[len(pfx):]
    # ── 福利/待遇噪音 ──
    #
    # 「亚马逊选品销售专员双休+五险一金」→ 只留前半段
    # 不切的话 → 「…双休」和「…双休+五险一金」是两个类型 → 去重失效。
    for sep in ("+", "＋", "/", "／"):
        if sep in t:
            t = t.split(sep)[0]
    # **去尾部福利词**（反复去）
    changed_tail = True
    while changed_tail:
        changed_tail = False
        for noise in _TITLE_TAIL_NOISE:
            if len(t) > len(noise) + 1 and t.endswith(noise):
                t = t[: -len(noise)]
                changed_tail = True
                break

    t = re.sub(r"[\s\u3000]+", "", t)
    # **去后缀**（反复去，「运营专员主管」→「运营」）
    #
    # `strip_role=True` 才剥角色词（运营）——
    # **方向词走这条**（角色词是岗位名的一部分），
    # 标题兜底走默认（不剥）。
    sufs = list(_TITLE_SUFFIXES)
    if strip_role:
        sufs = sufs + list(_ROLE_SUFFIXES)
    changed = True
    while changed:
        changed = False
        for suf in sufs:
            if len(t) > len(suf) + 1 and t.endswith(suf):
                t = t[: -len(suf)]
                changed = True
                break
    # **去数字**（「运营2组」→「运营组」→「运营」）
    t = re.sub(r"\d+", "", t)
    t = re.sub(r"[\-—_·•\s]+", "", t)
    # **英文小写化** —— 「web前端开发」和「Web前端开发」是同一类。
    #
    # 不小写化 → 每种大小写写法各推 3 个 → 去重形同虚设。
    t = t.lower()
    return t.strip()


def job_type_by_direction(title, haystack=None, direction_words=None,
                          direction_weights=None):
    """按**命中的方向词**定岗位类型 —— 比标题归一化更准。

    ## 为什么标题归一化不够

    ```
    ebay（易贝）shopee（虾皮） 跨境电商运营  → 归一化后是
    「ebayshopee跨境电商运营」  ← 平台前缀挡着，跟「跨境电商运营」不是一类
    ```

    平台前缀（ebay/shopee/amazon/ozon…）是**销售渠道**，不是**岗位类型**。

    ## 怎么定

    **取命中的方向词里「权重最高、长度最短」的那个** ——

    - **权重高** → 那是用户真正的主线方向
    - **长度短** → 「跨境电商」比「跨境电商运营」更**通用**
      → 亚马逊/速卖通/ebay 这些**平台岗位**也能归到「跨境电商」

    ## 为什么要「最短」

    只取最长的话：

    ```
    亚马逊运营专员      → 命中「亚马逊运营」  → 归一化 →「亚马逊」
    速卖通运营          → 命中「速卖通运营」  → 归一化 →「速卖通」
    跨境电商运营        → 命中「跨境电商运营」→ 归一化 →「跨境电商」
    ```

    → **三个类型** → 各推 3 个 → 还是刷屏。

    取最短的通用词 → 全归到「跨境电商」→ **一类推 3 个** → 干净。

    ## 找不到方向词 → 退回标题归一化

    没命中任何方向词 → 用 `job_type_key()` 的结果。
    """
    if direction_words:
        low = (haystack or title or "").lower()
        weights = direction_weights or {}
        hits = []
        for w in direction_words:
            if not w or len(w) < 3:
                continue
            if w.lower() in low:
                hits.append(w)
        if hits:
            # ── 选「根词」 ──
            #
            # **三级排序**：
            #
            # 1. **权重高**优先 —— 用户的主线方向
            # 2. **前缀根词**优先 —— 中文岗位名根词在前
            # 3. **短**优先 —— 更通用
            #
            # ## 为什么用「前缀」而不是「包含」
            #
            # ```
            # 命中：跨境电商运营(3.0)、电商运营(3.0)、跨境电商(3.0)
            #
            # 按「包含」：电商运营 ⊂ 跨境电商运营、跨境电商 ⊂ 跨境电商运营
            #            → 平手 → 按字典序 → 选「电商运营」→ 桶名太粗
            # 按「前缀」：只有「跨境电商」是「跨境电商运营」的前缀
            #            → 选「跨境电商」→ 桶名准
            # ```
            def root_count(w):
                return sum(1 for o in hits
                           if o != w and o.lower().startswith(w.lower()))

            best = min(hits, key=lambda w: (
                -float(weights.get(w, 1.0)), -root_count(w), len(w), w))
            # **归一化它**（剥层级后缀，**保留角色词**）
            return job_type_key(best, strip_role=False) or best
    return job_type_key(title)



def score_job(job: dict, profile: dict, experiences=None) -> dict:
    """返回 {"score": 0-100, "reasons": [...], "missing": [...]}

    experiences: **结构化经历**（公司/职位/起止/bullets）
                —— 用来判断「这个岗位的方向和你干过的对不对得上」。
                没有就只看 profile 里的 title_keywords。
    """
    score = 0
    reasons, missing = [], []

    title = (job.get("title") or job.get("name") or "").lower()

    # 1) 职位名关键词命中（30 分）
    # 命中判定要宽松：岗位名常写「web前端」「前端开发工程师」，
    # 关键词在标题里出现即算命中；找不到再退到 tags + 公司描述里找。
    haystack = " ".join([
        title,
        str(job.get("tags") or ""),
        str(job.get("raw") or ""),
    ]).lower()

    # **主攻方向优先** ——
    #
    # 用户同时投多个方向时（比如「主攻运营，顺便看结构设计」），
    # 关键词混在一张列表里会**平分 30 分** → 两个方向岗位混排，
    # 主攻方向被次要方向挤下去。
    #
    # 分两级：
    #   title_keywords_primary —— 主攻，命中给满 30 分
    #   title_keywords          —— 次要，命中给 15 分
    # 这样主攻方向**一定排在前面**，次要方向也不会被丢掉。
    # ── 方向词命中：**不分主次，按「命中强度」给分 ──
    #
    # ## 为什么要改
    #
    # 用户诉求：「根据经历内容评定，灵活调整期望方向，**不分主次**」。
    #
    # 原来分两级（主攻 30 分 / 次要 15 分）的问题是：
    #
    # 1. **主次是用户手填的** —— 但方向应该**按经历评定**，
    #    用户干过什么、干了多久、干了多深，比他自己勾的「主攻」更准。
    # 2. **两级会互相压制** —— 主攻只命中一个弱词（比如「运营」），
    #    次要命中三个强词（比如「跨境电商运营」「速卖通运营」「电商运营」）
    #    → 主攻 30 分 > 次要 15 分 → **明显更相关的岗位排在后面**。
    # 3. **经历推出来的方向进不了主攻** —— 只能进次要（15 分），
    #    永远被用户手填的主攻压在下面。
    #
    # ## 现在的规则
    #
    # **命中词越多、词越具体 → 分越高**（上限 30）：
    #
    # | 命中 | 分数 |
    # | --- | --- |
    # | 1 个泛词（长度 ≤ 3） | 10 |
    # | 1 个具体词 | 15 |
    # | 2 个词 | 22 |
    # | 3 个及以上 | 30 |
    #
    # **主攻词和次要词一视同仁** —— 主攻词只多一个**权重加成**（×1.2，
    # 上限仍是 30），让用户显式标过的方向略微靠前，但**不被压制**。
    #
    # ## 方向词的「具体程度」怎么判
    #
    # **按词长** —— 「运营」(2 字) 泛，「跨境电商运营」(6 字) 具体。
    # 泛词命中所有岗位 → 具体词才有区分度。
    # ── 方向词命中：**按权重，不分主次** ──
    #
    # 用户诉求：「根据经历内容评定，灵活调整期望方向，不分主次」。
    #
    # ## 两套规则
    #
    # **有 `direction_weights`**（新版，保存画像时自动算的）→
    #   命中词的**权重之和**决定分数（上限 30）。
    #   权重来自经历（干多久、多深、多近）→ **按经历评定**。
    #
    # **没有 `direction_weights`**（老画像）→ 退回旧的两级规则，
    #   保证老用户分数不突变。
    #
    # ## 为什么权重能替代「主攻/次要」
    #
    # 原来「主攻 30 分 / 次要 15 分」有个硬伤：
    # 主攻只命中一个**泛词**（比如「运营」），次要命中三个**具体词**
    # （「跨境电商运营」「速卖通运营」「电商运营」）
    # → 主攻 30 分 > 次要 15 分 → **明显更相关的岗位排在后面**。
    #
    # 权重制下：三个具体词权重和 > 一个泛词 → 顺序自然对。
    weights = profile.get("direction_weights") or {}
    primary_kw = [k for k in (profile.get("title_keywords_primary") or [])
                  if k and k.lower() in haystack]
    secondary_kw = [k for k in (profile.get("title_keywords") or [])
                    if k and k.lower() in haystack]

    # ── 统一走权重，**不分主次** ──
    #
    # ## 权重从哪来
    #
    # | 画像 | 权重 |
    # | --- | --- |
    # | 有 `direction_weights`（保存画像时按经历算的） | 0.5 ~ 3.0 |
    # | 没有（老画像） | 每个词 1.0（中性） |
    #
    # **老画像不再有两级规则** —— 统一 1.0，
    # 命中 1 个 = 10 分、2 个 = 20 分、3 个以上 = 30 分。
    #
    # ## 为什么删掉两级规则
    #
    # 用户诉求：「根据经历内容评定，灵活调整期望方向，**不分主次**」。
    #
    # 旧规则「主攻 30 / 次要 15」有个硬伤：
    # 主攻只命中一个**泛词**（「运营」），次要命中三个**具体词**
    # → 30 > 15 → **明显更相关的岗位排在后面**。
    #
    # 权重制下：三个具体词（权重和 > 1）> 一个泛词 → 顺序自然对。
    #
    # **主攻的加成在权重表里**（`score_direction_weights` 给主攻 +1.5）——
    # 是**同一张表里的一个数**，不是另一套规则。
    hit_kw = []
    hit_weight = 0.0
    seen_k = set()
    for k in primary_kw + secondary_kw:
        kk = k.lower()
        if kk in seen_k:
            continue
        seen_k.add(kk)
        w = None
        for wkey, wval in weights.items():
            if wkey.lower() == kk:
                w = float(wval)
                break
        if w is None:
            # **不在权重表里** —— 用户手填但经历里没有 → 中性权重
            w = 1.0
        hit_kw.append(k)
        hit_weight += w
    hits = hit_kw
    if hit_kw:
        # **权重和 → 分数**（上限 30）
        #
        # 权重 0.5 ~ 3.0/词 → 命中 1 个强词（3.0）= 30 分，
        # 命中 3 个普通词（1.0×3）= 30 分。
        base = int(round(min(30.0, hit_weight * 10.0)))
        score += base
        reasons.append("方向命中（按经历评定）: %s（%d 分）" % (
            "、".join(hit_kw[:5]), base))
    else:
        missing.append("职位名未命中期望方向词")

    # 2) 技能覆盖（30 分）
    jd = " ".join([
        title,
        str(job.get("tags") or ""),
        str(job.get("description") or ""),
        str(job.get("raw") or ""),
    ]).lower()
    skills = profile.get("skills") or []
    if skills:
        covered = [s for s in skills if s.lower() in jd]
        score += int(30 * len(covered) / len(skills))
        if covered:
            reasons.append("技能覆盖 %d/%d: %s" % (
                len(covered), len(skills), "、".join(covered)))
        miss_sk = [s for s in skills if s.lower() not in jd]
        if miss_sk:
            missing.append("技能未提及: " + "、".join(miss_sk))

    # 3) 城市（20 分）—— 多选，命中任一即算符合
    want_cities = _wanted_cities(profile)
    job_city = (job.get("area") or job.get("city") or "")
    if want_cities:
        matched = [c for c in want_cities if c and c in job_city]
        if matched:
            score += 20
            reasons.append("城市符合 %s: %s" % ("、".join(matched), job_city))
        else:
            missing.append("城市不符（期望 %s，实际 %s）" % (
                "、".join(want_cities), job_city or "未知"))

    # 4) 薪资（20 分）
    score += _salary_score(job.get("salary") or "", profile.get("min_salary", 0))

    # 5) 方向匹配（最多 10 分）—— **结构化经历里的职位名**
    #
    # 用户填的「期望岗位词」是**主动设的意向**，
    # 而结构化经历里的职位名是**干过的真实岗位** ——
    # 后者是更硬的证据（干过 = 会）。
    #
    # 只在 title_keywords 没命中时给分：
    # 否则同一件事会被算两遍（意向 + 经历），虚高。
    #
    # 上限 10 分，最后被 min(100) 夹住 —— 不会撑破分数分布。
    if not hits:
        dir_hit = _direction_from_experiences(title, experiences)
        if dir_hit:
            score += 10
            reasons.append("方向匹配经历: " + "、".join(dir_hit))

    # 经验项：2026-10-26 起暂不纳入评分（字段保留，等评分模型稳定再启用）

    return {"score": max(0, min(100, score)), "reasons": reasons, "missing": missing}


def _direction_from_experiences(title, experiences):
    """岗位标题命中了结构化经历里的职位名 —— 返回命中的职位词。

    **只比职位名，不比公司名** ——
    公司名太泛（「某某科技」在哪个岗位标题里都可能出现）。
    """
    if not title or not experiences:
        return []
    out = []
    for e in experiences:
        pos = (e.get("title") or "").strip()
        if not pos or len(pos) < 2:
            continue
        # 职位名整体出现在岗位标题里
        if pos.lower() in title:
            out.append(pos)
            continue
        # 反向：职位名的核心词（去掉「工程师/专员/经理」这类后缀）
        core = re.sub(
            r"(工程师|设计师|专员|经理|主管|技师|助理|实习生|技术员)$",
            "", pos).strip()
        if len(core) >= 2 and core.lower() in title:
            out.append(pos)
    # 去重
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _wanted_cities(profile: dict) -> list:
    """期望城市列表。兼容旧的单城市字段 city。"""
    cities = profile.get("cities") or []
    if isinstance(cities, str):
        cities = [cities] if cities else []
    if not cities:
        legacy = profile.get("city") or ""
        cities = [legacy] if legacy else []
    return [str(c).strip() for c in cities if str(c).strip()]


def _experience_score(text: str, min_years: int) -> int:
    """经验匹配。min_years=0 表示不要求，给满分 15。"""
    if not min_years:
        return 15
    m = re.search(r"(\d+)\s*-\s*(\d+)\s*年", text)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"(\d+)\s*年以上", text)
        if m:
            lo, hi = int(m.group(1)), int(m.group(1))
        elif "经验不限" in text or "应届" in text or "在校" in text:
            return 0
        else:
            return 5
    if lo >= min_years:
        return 15
    if hi >= min_years:
        return 10
    return 5


def _salary_score(text: str, min_k: int) -> int:
    """薪资匹配。min_k=0 表示不要求，给满分 20。"""
    if not min_k:
        return 20
    if not text or "*" in text:
        return 10         # 薪资被遮罩，给中性分
    # 支持四种写法：「15-25K」「1.5-1.8万」「5-6千」「8000-12000」
    m = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*([kK万千])", text)
    if m:
        hi = float(m.group(2))
        unit = m.group(3)
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*([kK万千])", text)
        if m:
            hi = float(m.group(1))
            unit = m.group(2)
        else:
            # 「8000-12000」这种不带单位的，按元/月的常见写法当成 K
            m = re.search(r"(\d{4,})\s*-\s*(\d{4,})", text)
            if m:
                hi = float(m.group(2)) / 1000.0
                unit = "K"
            else:
                return 10         # 完全读不懂薪资，给中性分
    if unit == "万":
        hi *= 10                # 1.8万 = 18K
    elif unit == "千":
        hi /= 10                # 6千 = 0.6K
    if hi >= min_k:
        return 20
    if hi >= min_k * 0.8:
        return 12      # 略低于期望，但接近
    if hi >= min_k * 0.5:
        return 6       # 明显低于期望
    return 0           # 完全够不着
