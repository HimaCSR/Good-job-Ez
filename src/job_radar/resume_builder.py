"""简历匹配优化 —— 四步流程的核心。

**铁律：不编造经历。**
每一条 bullet 都必须能追溯到 profile.yaml 里用户写过的内容，
生成时自动带上「← 依据：原始片段」，让用户一眼看出哪句是真的。

四步（每步都能中止）：
1. 读该岗位 JD 全文
2. 挑出 JD 核心要求（技能 / 学历 / 年限 / 关键词）
3. 对照用户经历，标出可写进简历的点
4. 按模板生成

**全部本地规则，不用大模型。**（「AI 根据经历推荐」是另一条路，允许调模型；
这两条别混 —— 见 skill job-radar 的硬性约束）
"""

import os
import re


# ── 第 2 步：从 JD 挑出核心要求 ──────────────────────────────────────────────

# JD 里常见的技术词 → 归一化。匹配时用「小写 + 去空格」比较。
SKILL_ALIASES = {
    "vue": ["vue", "vue.js", "vuejs"],
    "react": ["react", "react.js", "reactjs"],
    "angular": ["angular", "angularjs"],
    "typescript": ["typescript", "ts"],
    "javascript": ["javascript", "js", "es6", "ecmascript"],
    "node": ["node", "node.js", "nodejs"],
    "three.js": ["three.js", "threejs", "three"],
    "webgl": ["webgl", "web gl"],
    "html5": ["html5", "html 5", "html"],
    "css3": ["css3", "css 3", "css", "scss", "sass", "less"],
    "webpack": ["webpack", "vite", "rollup"],
    "pinia": ["pinia", "vuex", "redux"],
    "jquery": ["jquery"],
    "flutter": ["flutter", "dart"],
    "reactnative": ["react native", "react-native", "rn"],
    "小程序": ["小程序", "miniprogram", "taro", "uniapp"],
    "java": ["java", "spring", "springboot", "spring boot"],
    "python": ["python", "django", "flask", "fastapi"],
    "go": ["go", "golang"],
    "php": ["php", "laravel"],
    "c++": ["c++", "cpp"],
    "sql": ["sql", "mysql", "postgresql", "sqlite"],
    "redis": ["redis", "缓存"],
    "k8s": ["k8s", "kubernetes", "docker", "容器"],
    "git": ["git", "svn"],
    "linux": ["linux", "unix"],
    "设计": ["ui", "ux", "设计", "交互", "figma", "sketch"],
    "可视化": ["可视化", "d3", "echarts", "canvas", "svg", "three.js"],
    # JD 的 tags 字段常把多个技能粘在一起（"CSSJavaScriptERP"），
    # 这些别名让切分能认出边界。
}

# 只用来做「粘连串切分」的词 —— **不是技能**，不进技能表。
# JD 的 tags 常粘在一起（"CSSJavaScriptERP"），这些词提供切分边界。
SPLIT_ONLY = [
    "echarts", "erp", "oa", "office", "windows", "linux", "运维",
    "javascript", "typescript", "webpack", "react", "vue", "node",
    "webgl", "canvas", "svg", "html", "css", "java", "python", "go",
    "sql", "mysql", "redis", "docker", "k8s", "git", "android", "ios",
]

# 学历关键词 → 规范化
DEGREE_ORDER = ["博士", "硕士", "本科", "大专", "高中"]

# 年限关键词
YEARS_RE = re.compile(r"(\d+)\s*[-~到至]?\s*(\d+)?\s*年")


def normalize(text):
    """归一化用于比较：小写、去空格与常见分隔符。"""
    if not text:
        return ""
    s = str(text).lower()
    s = re.sub(r"[\s\-_/\\.,、，·:：()（）\[\]]+", "", s)
    return s


def extract_requirements(jd_text, user_skills=None):
    """第 2 步：从 JD 全文里挑出核心要求。

    返回：
    {
      "skills":     [{"name","aliases","hits","user_has"}],
      "degree":     "本科" | None,
      "min_years":  3 | None,
      "keywords":   ["性能优化", ...]   # JD 里反复出现的名词短语
    }
    """
    text = jd_text or ""
    low = normalize(text)
    user_set = {normalize(s) for s in (user_skills or [])}

    # 技能
    skills = []
    for name, aliases in SKILL_ALIASES.items():
        hits = 0
        for a in aliases:
            hits += low.count(normalize(a))
        if hits:
            skills.append({
                "name": name,
                "aliases": aliases,
                "hits": hits,
                "user_has": normalize(name) in user_set
                or any(normalize(a) in user_set for a in aliases),
            })

    # **用户自己的技能也要当候选** ——
    #
    # 内置别名表只覆盖常见技术词。用户简历里的技能（CAD / Revit /
    # 盈建科 / 天正 / 数据透视表…）常常**不在表里**，
    # 于是 JD 明明写了「熟悉 CAD、Revit、盈建科」，
    # 抽出来的要求里却**一个都没有** →
    # 用户的 CAD / Revit 经历**一条都匹配不上** → 简历被写成空的。
    #
    # 规则：**用户会的技能 + 它出现在 JD 里** = 一条 JD 要求。
    # （JD 里没提的不要加 —— 那是用户会的，不是岗位要的。）
    known = {normalize(s["name"]) for s in skills}
    for raw in (user_skills or []):
        name = str(raw).strip()
        if not name:
            continue
        n = normalize(name)
        if n in known:
            continue
        hits = low.count(n)
        if hits:
            skills.append({
                "name": name,
                "aliases": [name],
                "hits": hits,
                "user_has": True,
            })
            known.add(n)

    # 命中多的排前面
    skills.sort(key=lambda s: (-s["hits"], s["name"]))

    # 学历
    degree = None
    for d in DEGREE_ORDER:
        if d in text:
            degree = d
            break

    # 年限：取 JD 里最大的那个下限
    #
    # 「经验不限 / 不限经验 / 无经验要求」→ 没有年限要求，**不是 0 年**。
    if re.search(r"经验不限|不限经验|无经验要求|经验不限者优先", text):
        years = []
    else:
        years = []
        for m in YEARS_RE.finditer(text):
            lo = int(m.group(1))
            hi = int(m.group(2)) if m.group(2) else lo
            years.append(lo)
            # 「3-5年经验」→ 要求 3 年；「1年以上」→ 1
    min_years = max(years) if years else None

    # 关键词：JD 里出现频次高的技术名词（2-6 字的中文短语 + 常见英文词）
    keywords = _extract_keywords(text)

    return {"skills": skills, "degree": degree, "min_years": min_years,
            "keywords": keywords}


_STOP = set("""的 了 和 与 及 或 在 有 是 为 以 于 我们 你们 他们 公司 岗位 职责 要求
工作 相关 以上 包括 主要 负责 熟悉 熟练 掌握 具备 能够 良好 优先 加分 有过 经验
""".split())


def _split_known_skills(text):
    """把粘连的英文技能串按已知技能边界切开。

    JD 的 tags 字段经常是「VueEchartsNode.jsWebGL」这样粘着的 ——
    正则会当成一个怪词，既匹配不到技能表，也会污染关键词。
    """
    # 按已知技能名（长的优先）做边界切分
    names = []
    for aliases in SKILL_ALIASES.values():
        names.extend(aliases)
    names.extend(SPLIT_ONLY)
    names = [n for n in names if len(n) >= 2]
    names.sort(key=len, reverse=True)
    if not names:
        return text

    # 先把已知技能名用分隔符包起来
    pattern = "(" + "|".join(re.escape(n) for n in names if len(n) >= 3) + ")"
    out = re.sub(pattern, lambda m: " \1 ", text)
    return out


# JD 里常见的业务/能力词。命中就是关键词。
# 比「从文本里猜词组」可靠得多 —— 猜出来的碎片没法用。
_DOMAIN_TERMS = [
    "性能优化", "性能", "架构", "设计", "开发", "重构", "组件化", "工程化",
    "团队协作", "跨部门", "项目管理", "技术方案", "代码评审", "单元测试",
    "自动化测试", "持续集成", "持续交付", "部署", "运维", "监控", "告警",
    "数据结构", "算法", "复杂度", "内存", "渲染", "帧率", "首屏", "白屏",
    "响应式", "移动端", "桌面端", "跨端", "可视化", "大屏", "图表",
    "数据挖掘", "数据分析", "业务分析", "用户研究", "交互设计", "视觉设计",
    "规范", "文档", "沉淀", "复用", "开源", "前沿", "调研",
    "大规模", "高并发", "海量", "实时", "离线",
]


def _extract_keywords(text, top=12):
    """从 JD 里提关键词。

    **用已知词表匹配，不猜词组** —— 猜出来的碎片（「 和」「js」）没法用。
    词表覆盖 JD 里最常见的业务/能力词；命中按出现次数排。
    """
    if not text:
        return []
    from collections import Counter
    counts = Counter()

    low = text.lower()
    for term in _DOMAIN_TERMS:
        c = low.count(term.lower())
        if c:
            counts[term] = c

    # 英文技术词（长度 >= 3，排除常见虚词）
    #
    # JD 里的 tags 常是粘连的（"VueEchartsNode.jsWebGL"）——
    # 先按已知技能的 camelCase 边界切开，否则会当成一个怪词。
    text2 = _split_known_skills(text)
    # camelCase 兜底：Node.jsWebGL 这种没有明显边界的，按大写字母切
    text2 = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text2)
    # 全大写连写（"CSSJavaScript"）：小写→大写的边界切一次
    text2 = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", text2)
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9+.#\-]{2,}", text2):
        w = m.group(0)
        if w.lower() in ("and", "the", "with", "for", "you", "our", "are", "etc",
                         "etc.", "requirements", "responsibilities", "job",
                         "description", "company", "city", "salary"):
            continue
        counts[w] += 1

    ranked = [(w, c) for w, c in counts.items() if c >= 1]
    # 频次高的排前面；同频次长词优先（更具体）
    ranked.sort(key=lambda x: (-x[1], -len(x[0])))
    return [w for w, _ in ranked[:top]]


# ── 第 3 步：对照经历，标出可写进简历的点 ────────────────────────────────────

# 经历原文里的段落 → 一条 bullet
def split_experience(experience_text):
    """把经历原文切成一条条。

    支持三种写法：
    - 每行一条
    - 用「-」「•」「*」开头
    - 空行分段
    """
    if not experience_text:
        return []
    lines = []
    for raw in str(experience_text).splitlines():
        s = raw.strip()
        if not s:
            continue
        for marker in ("- ", "• ", "* ", "· "):
            if s.startswith(marker):
                s = s[len(marker):].strip()
                break
        if s:
            lines.append(s)
    return lines


def _hit_skills(text, requirements):
    """这段文字命中了 JD 要求的哪些技能。

    抽出来是为了**两处共用**：
    - `match_experience`（自由文本 / 拼接后的结构化经历）
    - `_build_work_entries`（逐条结构化经历）

    两处规则必须一样 —— 否则「结构化经历版简历」和「自由文本版简历」
    的筛选结果会不一致。
    """
    low = normalize(text or "")
    hit = []
    for sk in (requirements or {}).get("skills", []):
        for a in sk.get("aliases", []):
            if normalize(a) in low:
                hit.append(sk["name"])
                break
    return sorted(set(hit))


def match_experience(requirements, experience_text, user_skills=None):
    """第 3 步：把 JD 要求和用户经历对上。

    **只从用户写过的内容里挑**，一条也不加。返回的每条都带 basis（原始片段）。

    返回：
    {
      "covered":  [{"text","basis","matched":[技能名]}],   # 有经历支撑的
      "gaps":     [{"name","reason"}],                    # JD 要但经历里没有
      "strengths": [技能名]                                # 经历里提到最多的
    }
    """
    lines = split_experience(experience_text)
    user_skill_set = {normalize(s) for s in (user_skills or [])}

    # 每条经历命中哪些技能
    #
    # **命中的是「JD 要的技能」** —— 用户会的技能（user_has）恰恰是最该写出来的，
    # 不能跳过。这里要判断的是「这条经历提到了哪些 JD 要求的技能」，
    # 不管用户会不会（会不会在 gaps 里单独看）。
    #
    # basis 记的是**第几条经历**（不是原文）—— 原文和 bullet 是同一句话，
    # 重复贴一遍没有信息量，还把简历撑得很长。
    per_line = []
    for idx, line in enumerate(lines, 1):
        hit = _hit_skills(line, requirements)
        per_line.append((line, hit, idx))

    # 挑出「命中 JD 要求」的经历 —— 这些是最该写进简历的
    covered = []
    for line, hit, idx in per_line:
        if hit:
            covered.append({"text": line,
                            "basis": "经历第 %d 条" % idx,
                            "basis_text": line,
                            "matched": hit})

    # JD 要、但用户**经历里一次都没提过**的 → 缺口
    mentioned = set()
    for _line, hit, _idx in per_line:
        mentioned.update(hit)
    gaps = []
    for sk in requirements.get("skills", []):
        if sk["name"] not in mentioned:
            gaps.append({
                "name": sk["name"],
                "reason": "经历里没提到" if not sk["user_has"]
                          else "技能表里有，但经历里没具体写过",
            })

    # 经历里提到最多的技能（= 用户真正的强项）
    from collections import Counter
    strength_count = Counter()
    for line, _, _idx in per_line:
        low = normalize(line)
        for s in (user_skills or []):
            if normalize(s) in low:
                strength_count[s] += 1
    strengths = [s for s, _ in strength_count.most_common()]

    return {"covered": covered, "gaps": gaps, "strengths": strengths}


# ── 第 4 步：按模板生成 ──────────────────────────────────────────────────────

def build_sections(resume_data):
    """把简历数据整理成模板要的 sections 结构。

    resume_data:
      {
        "identity": {...},
        "summary":  "一段自我介绍"（可选）,
        "skills":   ["vue","three.js"],
        "experiences": [{"title","meta","subtitle","bullets":[{text,basis}]}],
        "projects":    同上,
        "education":   [{"title","meta","subtitle"}],
      }
    """
    sections = []

    if resume_data.get("summary"):
        sections.append({"title": "个人简介", "kind": "text",
                         "paragraphs": [resume_data["summary"]]})

    if resume_data.get("skills"):
        sections.append({"title": "专业技能", "kind": "tags",
                         "tags": resume_data["skills"]})

    for key, title in (("experiences", "工作经历"),
                       ("projects", "项目经历"),
                       ("education", "教育背景")):
        entries = resume_data.get(key) or []
        if not entries:
            continue
        norm = []
        for e in entries:
            norm.append({
                "title": e.get("title", ""),
                "meta": e.get("meta", ""),
                "subtitle": e.get("subtitle", ""),
                "bullets": [{"text": b.get("text", ""),
                             "basis": b.get("basis", ""),
                             "basis_text": b.get("basis_text", "")}
                            for b in (e.get("bullets") or [])],
            })
        sections.append({"title": title, "kind": "entries", "entries": norm})

    return sections



def _build_identity(job, profile):
    """**按岗位把身份信息补齐** —— 模板页眉那些字段自动填。

    ## 为什么

    简历模板（WPS 系）的页眉上常有「意向岗位 / 意向城市 /
    期望薪资 / 求职类型 / 学历」。这些**每个岗位都不一样** ——
    拿画像里的固定值填就错了（投重庆的岗位，简历写着意向城市「广州」）。

    → **优先用岗位自己的信息**，画像里没填的再退回。

    ## 字段对应

    | 模板字段 | 来源 |
    | --- | --- |
    | 意向岗位（headline） | **岗位标题** |
    | 意向城市（location） | **岗位城市**（去掉区县） |
    | 期望薪资（salary） | **岗位薪资** |
    | 求职类型（job_type） | 画像（默认「社招」） |
    | 学历（degree） | 岗位学历要求（画像优先） |
    | 姓名 / 电话 / 邮箱 | **画像**（跟岗位无关） |

    ## 城市要洗成「城市」不是「城市+区县」

    岗位城市是「重庆 两江新区」→ 简历上写「重庆 两江新区」不好看，
    而且跟用户设置的投递城市对不上 → **取第一个词**（重庆）。
    """
    identity = dict(profile.get("identity") or {})

    # **意向岗位 = 岗位标题** —— 这是这份简历投的什么岗，最该准确。
    title = (job.get("title") or "").strip()
    if title:
        identity["headline"] = title

    # **意向城市 = 岗位城市**（洗掉区县）
    #
    # **岗位城市优先** —— 投的哪个城就写哪个城。
    # 画像里的 location 是「用户想去哪」，跟这份简历投的城市不一定一致。
    city = (job.get("city") or "").strip()
    if city:
        first = re.split(r"[\s,，、/]+", city)[0].strip()
        # **洗掉脱敏星号** —— 招聘网站未登录时城市显示成
        # 「杭州*********」→ 直接写进简历 → 简历上一串星号。
        #
        # 本机踩过：意向城市 = "杭州*********"。
        first = first.replace("*", "").strip()
        if first:
            identity["location"] = first

    # **期望薪资** —— 画像填了用画像的（用户自己填的是期望），
    # 没填才用岗位上的（那是招聘方开的价，不是你的期望）。
    if not identity.get("salary"):
        salary = (job.get("salary") or "").strip()
        if salary:
            identity["salary"] = salary

    # **学历** —— 岗位要求的学历（画像填了就用画像的）
    degree = (job.get("degree") or "").strip()
    if degree and not identity.get("degree"):
        identity["degree"] = degree

    # **求职类型** —— 岗位标题里带「实习」就是实习
    if not identity.get("job_type"):
        identity["job_type"] = "实习" if "实习" in title else "社招"

    return identity


def optimize_resume(job, profile, template_id="classic", experiences=None):
    """跑完四步，返回一份可渲染的简历数据。

    job:        岗位（含 description/JD）
    profile:    个人画像（profile.yaml）
    experiences: **结构化经历**列表（公司/职位/起止/bullets）
                —— 有就用它生成「工作经历」章节（信息更全），
                没有就退回 profile["experience_text"] 自由文本模式。
    """
    jd = (job.get("description") or "") + "\n" + (job.get("title") or "")
    user_skills = profile.get("skills") or []
    experience_text = profile.get("experience_text") or ""
    experiences = list(experiences or [])

    # 1) 读 JD（这里 JD 已经在 job 里了）
    # 2) 挑要求
    reqs = extract_requirements(jd, user_skills)
    # 3) 对照经历
    #
    # **有结构化经历就用它** —— 它的 bullets 更干净（有公司/职位/时间），
    # 而且 free-text 里可能有跟结构化经历重复的内容。
    if experiences:
        matched = match_experience(
            reqs, _structured_to_text(experiences), user_skills)
    else:
        matched = match_experience(reqs, experience_text, user_skills)

    # **requirements 要先挂进 matched** ——
    # `_build_work_entries` 靠它逐条判断 bullet 该不该留。
    # （之前挂晚了 → 拿到的 requirements 是空的 → 所有 bullet 都被丢掉）
    matched = dict(matched)
    matched["requirements"] = reqs

    # 组装简历
    identity = _build_identity(job, profile)

    # 经历 → 工作经历 / 项目经历
    project_kw = ["项目", "负责", "主导", "独立", "从 0 到 1", "0-1"]

    if experiences:
        # **结构化经历** → 直接生成「工作经历」章节
        # （公司/职位/起止齐全 —— 这是自由文本给不了的）
        work_entries = _build_work_entries(experiences, matched)
        # 结构化经历不再靠关键词猜「项目」—— 全归工作经历
        project_entries = []
    else:
        # 自由文本 → 靠关键词猜「项目」还是「工作」
        work_bullets = []
        project_bullets = []
        for c in matched["covered"]:
            if any(k in c["text"] for k in project_kw):
                project_bullets.append(c)
            else:
                work_bullets.append(c)
        work_entries = [{"title": "工作经历", "meta": "", "subtitle": "",
                         "bullets": work_bullets}]
        project_entries = [{"title": "项目经历", "meta": "", "subtitle": "",
                            "bullets": project_bullets}]

    resume_data = {
        "identity": identity,
        "summary": _build_summary(job, matched, profile),
        "skills": matched["strengths"] or user_skills[:8],
        "experiences": work_entries,
        "projects": project_entries,
        "education": _build_education(profile),
    }
    return {
        "resume": resume_data,
        "requirements": reqs,
        "matched": matched,
        "template_id": template_id,
        "used_structured": bool(experiences),
    }


def _structured_to_text(experiences):
    """把结构化经历拼成「一行一条」的文本，给 match_experience 用。

    这样**筛选逻辑不用写两遍** —— 结构化经历和自由文本走同一条路。
    """
    out = []
    for e in experiences or []:
        head = " ".join(x for x in [
            e.get("company") or "", e.get("title") or "",
            e.get("start") or "", e.get("end") or "",
        ] if x)
        if head:
            out.append(head)
        for b in (e.get("bullets") or []):
            if str(b).strip():
                out.append(str(b).strip())
    return "\n".join(out)


def _build_work_entries(experiences, matched):
    """结构化经历 → 简历的「工作经历」条目列表。

    每条经历一个条目（公司·职位 + 起止 + bullets）。

    **bullets 只留命中 JD 要求的** —— 全写进去简历会太长，
    而简历优化要的就是「针对这个岗位挑最相关的」。

    没命中任何 JD 要求的经历**仍然保留标题**（公司/职位/时间是硬信息），
    只是不放 bullet —— 那是经历本身的价值，不该因为对不上 JD 就抹掉。
    """
    # JD 要求（用于逐条判断 bullet 该不该留）
    requirements = matched.get("requirements") or {}

    entries = []
    for e in experiences or []:
        company = (e.get("company") or "").strip()
        title = (e.get("title") or "").strip()
        start = (e.get("start") or "").strip()
        end = (e.get("end") or "").strip()

        # **职位名里也有技能证据** —— 「Java 后端工程师」命中 Java，
        # 这是硬事实（比 bullet 里提一句更可靠）。
        head_hit = _hit_skills(" ".join(x for x in (company, title) if x),
                               requirements)

        bullets = []
        for b in (e.get("bullets") or []):
            text = str(b).strip()
            if not text:
                continue
            # **逐条自己算命中** —— 不能靠「拼接后哪些行命中了」反查，
            # 那样 basis 序号会变成拼接后的行号（对不上用户填的顺序）。
            hit = _hit_skills(text, requirements)
            if not hit:
                continue
            bullets.append({"text": text, "basis": "", "matched": hit})

        head = " · ".join(x for x in (company, title) if x)
        meta = " - ".join(x for x in (start, end) if x)
        if not head and not bullets:
            continue
        entries.append({
            "title": head or company or title,
            "meta": meta,
            "subtitle": "",
            "bullets": bullets,
            # 职位命中的技能 —— 供上层判断「这段经历整体和 JD 的相关度」
            "head_matched": head_hit,
        })
    return entries


def _build_summary(job, matched, profile):
    """一段自我介绍 —— 只用经历里出现过的技能，不吹。"""
    strengths = matched.get("strengths") or []
    if not strengths:
        return ""
    top = "、".join(strengths[:3])
    return "针对「%s」岗位，%s 等方面有直接项目经验。" % (
        job.get("title") or "该岗位", top)


def _build_education(profile):
    ident = profile.get("identity") or {}
    edu = ident.get("education") or ""
    school = ident.get("school") or ""
    major = ident.get("major") or ""
    if not (edu or school):
        return []
    title = " ".join(x for x in [school, major] if x)
    return [{"title": title or edu, "meta": edu, "subtitle": ""}]
