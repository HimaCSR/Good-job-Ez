"""简历模板库。

**统一存 HTML 模板**（2026-10-26 判定）：内置 4 套和用户上传转换的
用同一份 HTML + CSS 结构，缩略图 = 同一模板的缩小渲染 ——
一套渲染器吃下所有模板，生成简历时不必区分来源。

四套内置：
- classic 经典单栏：通用性最强，HR 都看得惯
- modern  现代双栏：技能多的岗位适合，视觉清爽
- tech    技术极客：极客风，适合技术岗投递
- acad    学术风：论文/研究岗

每个模板 = 一个 CSS 片段 + 一份共享的 HTML 骨架。
这样加模板只要写 CSS，不用碰 HTML。
"""

import os
import re

# 模板目录 —— **放 plugin-data，不放插件目录**。
#
# ## 为什么不能放插件目录
#
# 插件目录在开发模式下是 **junction 指向仓库** →
# 用户上传的模板会**落进 git 仓库**（`git status` 里冒出未跟踪文件）。
#
# 上传的模板是**用户的数据**，不该进版本管理 ——
# 跟 `profile.yaml` 一样，该在 `<plugin-data>/job-radar/` 下。
#
# 兜底：拿不到 plugin_data_dir 时（脱离包单测）→ 用环境变量指定，
# 再兜底用插件目录下的 `templates/`（**只读场景够用**）。
def _templates_dir() -> str:
    try:
        try:
            from . import storage as _storage
            base = _storage.plugin_data_dir("job-radar")
        except ImportError:
            import storage as _storage
            base = _storage.plugin_data_dir("job-radar")
        d = os.path.join(base, "templates")
        os.makedirs(d, exist_ok=True)
        return d
    except Exception:
        env = os.environ.get("JOB_RADAR_TEMPLATES_DIR", "").strip()
        if env:
            os.makedirs(env, exist_ok=True)
            return env
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "templates")


TEMPLATES_DIR = _templates_dir()

# ── 共享 HTML 骨架 ───────────────────────────────────────────────────────────
# 所有模板共用同一份 DOM，只有 CSS 不同。
# 这样「缩略图 = 实际输出」自动成立，不需要两套渲染逻辑。

_SKELETON = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{{ title }}</title>
<style>
/* ── 基础 ── */
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
  color: #222; line-height: 1.55; font-size: 13px;
  background: #fff;
}
/* A4 + 打印边距。headless 打印 PDF 时这个 @page 决定纸面大小和留白。 */
@page { size: A4; margin: 14mm 16mm; }
.page {
  width: 178mm;          /* A4 210mm - 左右各 16mm */
  min-height: 269mm;     /* A4 297mm - 上下各 14mm */
  margin: 0 auto;
  padding: 0;
}
/* 屏幕上预览时也给个像样的留白（PDF 打印时 @page 会再算一次） */
@media screen {
  body { padding: 16mm; }
  .page { width: 178mm; }
}

/* ── 抬头 ── */
.head { margin-bottom: 14px; position: relative; }

/* 证件照 —— 页眉右上角圆形。
   **没有照片时整个 div 都不渲染**，所以不会留下空白占位。

   ⚠️ **CSS 注释里不能出现 Jinja 标签** ——
   CSS 注释（斜杠星号）里的 Jinja 标签**照样会被解析**。
   本机踩过：注释里写了一个 if 标签 → Jinja 找不到对应的 endif
   → TemplateSyntaxError: Unexpected end of template。

   **教训**：要提 Jinja 标签，就写在花括号井号注释里，
   或者干脆用文字描述（像这里这样）。 */
.photo {
  position: absolute; top: 0; right: 0;
  width: 22mm; height: 22mm; overflow: hidden;
  border-radius: 50%;
  box-shadow: 0 0 0 1.5px rgba(0,0,0,.08);
}
.photo img { width: 100%; height: 100%; object-fit: cover; display: block; }
/* 有照片时，正文别压到照片下面 */
.head:has(.photo) .name { padding-right: 24mm; }
.head:has(.photo) .contact { padding-right: 24mm; }
.name { font-size: 24px; font-weight: 700; letter-spacing: .5px; }
.sub { font-size: 12px; color: #555; margin-top: 3px; }
.contact { font-size: 11.5px; color: #444; margin-top: 5px; }
.contact span { margin-right: 12px; }

/* ── 章节 ── */
.sec { margin-bottom: 13px; }
.sec-title {
  font-size: 13px; font-weight: 700; margin-bottom: 6px;
  padding-bottom: 3px; border-bottom: 1px solid #ddd;
}
.item { margin-bottom: 8px; }
.item-head { display: flex; align-items: baseline; gap: 8px; }
.item-title { font-weight: 650; font-size: 12.5px; }
.item-meta { font-size: 11px; color: #666; margin-left: auto; }
.bullets { margin-top: 3px; padding-left: 15px; }
.bullets li {
  font-size: 12px; margin-bottom: 2px;
  /* 中文没有词边界 —— 不加这个，「分钟」会被拆成「分」「钟」。
     line-break: strict 按词断行；overflow-wrap 兜底长英文不溢出。 */
  line-break: strict; overflow-wrap: break-word;
}
.bullets .basis {
  color: #8a6410; font-size: 10.5px; margin-left: 4px;
}
.tags { margin-top: 3px; }
.tag {
  display: inline-block; font-size: 10.5px; padding: 1px 6px; margin: 2px 3px 0 0;
  border-radius: 2px; background: #f2f4f7; color: #333;
}
.empty { color: #999; font-size: 11.5px; font-style: italic; }

/* 「← 依据」标注：预览时显示，正式输出隐藏 */
.basis { display: none; }
.show-basis .basis { display: inline; }
.basis {
  color: #8a6410; font-size: 10.5px; margin-left: 4px;
}

/* ── 由模板 CSS 追加的样式 ── */
{{ style }}
</style>
</head>
<body class="{% if show_basis %}show-basis{% endif %}">
<div class="page">
  {# 图片模板：底图铺在文字层下面 #}
  {% if bg_image %}<div class="bg-image" style="background-image: url('{{ bg_image }}')"></div>{% endif %}
  <div class="content">
  <div class="head">
    {# 证件照 —— 放在页眉右上角（圆形）。没有照片就不占位。 #}
    {% if photo %}<div class="photo"><img src="{{ photo }}" alt="证件照"></div>{% endif %}
    <div class="name">{{ identity.name or "姓名" }}</div>
    {% if identity.headline %}<div class="sub">{{ identity.headline }}</div>{% endif %}
    <div class="contact">
      {% if identity.phone %}<span>{{ identity.phone }}</span>{% endif %}
      {% if identity.email %}<span>{{ identity.email }}</span>{% endif %}
      {% if identity.location %}<span>{{ identity.location }}</span>{% endif %}
      {% if identity.education %}<span>{{ identity.education }}</span>{% endif %}
      {% if identity.link %}<span>{{ identity.link }}</span>{% endif %}
    </div>
  </div>

  {% for sec in sections %}
  <div class="sec">
    <div class="sec-title">{{ sec.title }}</div>

    {% if sec.kind == "text" %}
      {% for para in sec.paragraphs %}
      <div class="item"><div class="bullets"><ul><li>{{ para }}</li></ul></div></div>
      {% endfor %}

    {% elif sec.kind == "list" %}
      {% for b in sec.bullets %}
      <div class="item"><div class="bullets"><ul><li>{{ b.text }}{% if b.basis %} <span class="basis">← 依据：{{ b.basis }}</span>{% endif %}</li></ul></div>
      {% endfor %}

    {% elif sec.kind == "tags" %}
      <div class="item"><div class="tags">
        {% for t in sec.tags %}<span class="tag">{{ t }}</span>{% endfor %}
      </div></div>

    {% elif sec.kind == "entries" %}
      {% for e in sec.entries %}
      <div class="item">
        {% if e.title and e.title != sec.title %}
        <div class="item-head">
          <span class="item-title">{{ e.title }}</span>
          {% if e.meta %}<span class="item-meta">{{ e.meta }}</span>{% endif %}
        </div>
        {% elif e.meta %}
        <div class="item-head"><span class="item-meta">{{ e.meta }}</span></div>
        {% endif %}
        {% if e.subtitle %}<div class="item-meta" style="margin-left:0">{{ e.subtitle }}</div>{% endif %}
        {% if e.bullets %}
        <div class="bullets"><ul>
          {% for b in e.bullets %}
          <li>{{ b.text }}{% if b.basis %} <span class="basis">← 依据：{{ b.basis }}</span>{% endif %}</li>
          {% endfor %}
        </ul></div>
        {% endif %}
      </div>
      {% endfor %}
    {% endif %}
  </div>
  {% endfor %}
  </div>
</div>
</body>
</html>
"""


# ── 四套内置模板的 CSS ───────────────────────────────────────────────────────

_CSS_CLASSIC = """
.sec-title { border-color: #d8dde3; }
.item-title { color: #1a1a1a; }
"""

_CSS_MODERN = """
body { font-size: 12.5px; }
.page { display: flex; gap: 20px; }
.head { width: 34%; border-right: 2px solid #2f6fd0; padding-right: 16px; }
.name { font-size: 21px; color: #2f6fd0; }
.sec { width: 100%; }
.sec-title { border: none; color: #2f6fd0; font-size: 12.5px; letter-spacing: .5px; }
.tag { background: #eaf1fc; color: #2f6fd0; }
"""

_CSS_TECH = """
body { font-family: "Consolas", "SF Mono", "Microsoft YaHei", monospace; font-size: 12px; }
.name { font-size: 22px; letter-spacing: 1px; }
.sec-title {
  border: none; border-left: 3px solid #111; padding-left: 8px;
  text-transform: uppercase; letter-spacing: 1.5px; font-size: 11.5px;
}
.item-title { font-weight: 700; }
.tag { background: #111; color: #fff; border-radius: 0; }
.bullets .basis { color: #666; font-style: italic; }
"""

_CSS_ACAD = """
body { font-family: Georgia, "Songti SC", "SimSun", serif; font-size: 12.5px; }
.name { font-size: 22px; font-weight: 600; }
.sec-title { border-color: #b8b0a0; font-family: Georgia, serif; letter-spacing: .5px; }
.item-title { font-weight: 600; }
.tag { background: #f5f1e8; color: #6b5b3e; }
"""


BUILTIN = {
    "classic": {
        "name": "经典单栏",
        "description": "通用性最强，HR 都看得惯",
        "css": _CSS_CLASSIC,
    },
    "modern": {
        "name": "现代双栏",
        "description": "技能多的岗位适合，视觉清爽",
        "css": _CSS_MODERN,
    },
    "tech": {
        "name": "技术极客",
        "description": "极客风，适合技术岗投递",
        "css": _CSS_TECH,
    },
    "acad": {
        "name": "学术风",
        "description": "论文、研究岗，或看重学历背景的岗位",
        "css": _CSS_ACAD,
    },
}


def builtin_ids():
    return list(BUILTIN.keys())


def get_builtin(template_id):
    """取内置模板的 CSS；不是内置返回 None。"""
    tpl = BUILTIN.get(template_id)
    return tpl["css"] if tpl else None


def _uploaded_css(template_id):
    """读上传模板的 CSS 片段；不是上传模板返回 None。

    **上传的模板和内置模板是同一个形态**：一份 CSS 片段，
    渲染时套进同一份 HTML 骨架。
    这样「缩略图 = 实际输出」自动成立 —— 不需要两套渲染逻辑。
    """
    path = os.path.join(TEMPLATES_DIR, template_id + ".css")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# 证件照的 data URI 缓存
#
# **为什么要缓存** —— 证件照 1~2 MB，base64 后 1.4~2.7 MB。
# 每次渲染都读文件 + 编码 → 预览一页要几百毫秒。
#
# 用 mtime 做 key —— 换了照片自动失效。
_PHOTO_CACHE = {"key": None, "uri": None}


def _current_photo():
    """当前证件照（data URI）—— 没有就返回 None。

    ## 照片在哪

    `<plugin-data>/job-radar/photo/` 目录下的第一张图片
    （设置页「证件照上传」放进去的）。

    ## 为什么照片要跟着简历模板走

    用户给的模板是**WPS 风格**：页眉右上角有个**圆形照片位**。
    模板转换出来的 CSS 还原了配色，但**照片位是骨架的一部分** ——
    不加的话，生成的简历永远没有照片。
    """
    try:
        from . import storage as _storage
        base = _storage.plugin_data_dir("job-radar")
    except ImportError:
        try:
            import storage as _storage
            base = _storage.plugin_data_dir("job-radar")
        except Exception:
            base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes",
                                "plugin-data", "job-radar")
    d = os.path.join(base, "photo")
    if not os.path.isdir(d):
        return None

    for name in sorted(os.listdir(d)):
        ext = os.path.splitext(name)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        path = os.path.join(d, name)
        try:
            mtime = os.path.getmtime(path)
            key = (path, mtime)
        except OSError:
            continue
        if _PHOTO_CACHE["key"] == key:
            return _PHOTO_CACHE["uri"]
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        import base64
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "webp": "image/webp"}.get(ext.lstrip("."),
                                                              "image/png")
        uri = "data:%s;base64,%s" % (mime,
                                     base64.b64encode(raw).decode("ascii"))
        _PHOTO_CACHE["key"] = key
        _PHOTO_CACHE["uri"] = uri
        return uri
    return None


def uploaded_bg_image(template_id):
    """上传模板的底图（图片模板才有）—— 返回 data URI 或 None。"""
    path = os.path.join(TEMPLATES_DIR, template_id + ".bg")
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        raw = fh.read()
    if not raw:
        return None
    import base64
    ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp"}.get(ext, "image/png")
    return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))


def _uploaded_skeleton(template_id):
    """读上传模板的**骨架 HTML**；没有返回 None。

    骨架是「模板自己的 HTML 结构」——
    章节标题、页眉布局、字段位置全来自模板文件。
    """
    if not template_id or template_id.startswith("classic"):
        return None
    path = os.path.join(TEMPLATES_DIR, template_id + ".skeleton.html")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


# ── 模板章节 ↔ 用户内容的语义对齐 ──────────────────────────────────────────
#
# **为什么要对齐**
#
# 模板的章节（来自模板文件）：
#     求职意向 / 自我评价 / 工作经历 / 教育经历
# 用户数据的章节（来自 profile + 岗位 JD）：
#     个人简介 / 专业技能 / 工作经历 / 项目经历 / 教育背景
#
# **标题要用模板的**（否则跟原文件不像），
# **内容要用用户的**（否则就是模板的示例内容）。
#
# ## 匹配规则
#
# 1. **标题完全相同** → 直接对上
# 2. **同一「语义类」** → 对上
#    - entry 类：工作经历 / 工作经验 / 实习经历 / 项目经历 / 教育背景 / 教育经历
#    - list 类：自我评价 / 个人评价 / 个人优势
#    - tags 类：专业技能 / 技能 / 技能特长
#    - paragraph 类：求职意向 / 个人信息 / 个人简介
# 3. 对不上 → **留空**（模板里那个章节显示为空）

# 语义类
_CLASS_BY_TITLE = {
    # **paragraph 只有「求职意向/个人信息」** ——
    # 「个人简介」归 list（跟自我评价同类）。
    #
    # 本机踩过：个人简介归 paragraph → 模板的「求职意向」(paragraph)
    # 抢走了个人简介 → 而「自我评价」(list) 空着 →
    # 章节内容全错位。
    "求职意向": "paragraph", "个人信息": "paragraph",
    "自我评价": "list", "个人评价": "list", "个人优势": "list",
    "个人简介": "list", "自我介绍": "list",
    "专业技能": "tags", "技能": "tags", "技能特长": "tags",
    "工作经历": "entry", "工作经验": "entry", "实习经历": "entry",
    "项目经历": "entry", "项目经验": "entry",
    "教育背景": "entry", "教育经历": "entry",
}


# 标题里出现的关键词 → 该章节想要的「内容特征」
#
# **为什么要打分而不是「同类型第一个抢」**
#
# 模板有 4 个 entry 类章节（工作经历/项目经历/教育经历/实习经历），
# 用户数据也有 4 个 entry 类章节 —— **光看类型分不出来**。
#
# 本机踩过：按类型贪心 → 「教育经历」抢到了「工作经历」的内容 →
# 简历里「教育经历」下写着公司名，「自我评价」空着。
#
# → **按关键词相似度打分**，全局最优分配。

_TITLE_KEYWORDS = {
    "工作经历": ("工作", "公司", "岗位", "职责", "在职"),
    "工作经验": ("工作", "公司", "岗位", "职责", "在职"),
    "实习经历": ("实习", "公司", "岗位"),
    "项目经历": ("项目",),
    "项目经验": ("项目",),
    "教育背景": ("学校", "大学", "学院", "学历", "毕业"),
    "教育经历": ("学校", "大学", "学院", "学历", "毕业"),
    "求职意向": ("意向", "岗位", "城市", "薪资"),
    "个人信息": ("电话", "邮箱", "地址"),
    "自我评价": ("评价", "优势", "特长", "能力"),
    "个人评价": ("评价", "优势", "特长", "能力"),
    "个人优势": ("优势", "特长", "能力"),
    "个人简介": ("简介", "介绍", "概述"),
    "专业技能": ("技能", "工具", "掌握"),
    "技能": ("技能", "工具", "掌握"),
    "技能特长": ("技能", "特长"),
}

# 标题同义词 —— 「教育背景」=「教育经历」
#
# **必须有这张表** —— 模板叫「教育经历」，数据叫「教育背景」，
# 字面不同但**是同一个东西**。
#
# 本机踩过：没有同义词表 → 「教育经历 vs 教育背景」只有 13 分
# → 被「专业技能」以 25 分抢走（"专业"二字误命中）→
# 教育章节里塞了技能，工作经历塞了教育。
_SYNONYMS = [
    {"教育背景", "教育经历", "教育情况", "学历信息"},
    {"工作经历", "工作经验", "工作履历", "职业经历"},
    {"实习经历", "实习经验", "实习情况"},
    {"项目经历", "项目经验", "项目情况"},
    {"自我评价", "个人评价", "个人优势", "自我描述", "个人简介", "自我介绍"},
    {"专业技能", "技能", "技能特长", "专业能力", "技术能力"},
    {"求职意向", "求职目标", "职位意向", "意向岗位"},
    {"个人信息", "基本信息", "联系方式"},
]


def _is_synonym(a, b):
    """两个标题是不是同义。"""
    if a == b:
        return True
    for group in _SYNONYMS:
        if a in group and b in group:
            return True
    return False


def _section_text(sec):
    """章节的全部文字（用来判特征）。"""
    parts = []
    for p in (sec.get("paragraphs") or []):
        parts.append(str(p))
    for b in (sec.get("bullets") or []):
        parts.append(str(b.get("text", "")))
    for e in (sec.get("entries") or []):
        parts.append(str(e.get("title", "")))
        parts.append(str(e.get("subtitle", "")))
    for t in (sec.get("tags") or []):
        parts.append(str(t))
    return " ".join(parts)


def _match_score(tpl_title, sec):
    """模板章节 ↔ 用户章节 的匹配分（越高越合适）。

    ## 打分项

    1. **标题完全相同** → 100（直接对上）
    2. **关键词命中** —— 模板标题要的词在内容里出现 → 每个 +10
    3. **同类**（list/entry/tags/paragraph）→ +3
    4. **不同类** → 0
    """
    src_title = sec.get("title") or ""
    if src_title == tpl_title:
        return 100.0
    # **同义词** —— 「教育背景」vs「教育经历」= 90
    # （同义但不完全一样，留 10 分差距给完全相同的）
    if _is_synonym(tpl_title, src_title):
        return 90.0
    text = _section_text(sec)
    score = 0.0
    for kw in _TITLE_KEYWORDS.get(tpl_title, ()):
        if kw in src_title:
            score += 25        # 标题里就有 → 强信号
        elif kw in text:
            score += 10        # 内容里提到 → 弱信号
    tpl_cls = _CLASS_BY_TITLE.get(tpl_title)
    src_cls = _CLASS_BY_TITLE.get(src_title, sec.get("kind"))
    if tpl_cls and src_cls and tpl_cls == src_cls:
        score += 3
    return score


def _align_to_skeleton(sections, skeleton_spec, identity=None):
    """把用户数据的 sections 对齐到**模板的章节列表**。

    skeleton_spec: 模板的槽位规格（含 sections）。
    返回的每个 section 的 title 是**模板的标题**。

    ## 分配策略

    **全局最优贪心**：对每个（模板章节, 用户章节）组合打分，
    反复取分数最高的组合，已分配的跳过。

    → 比「同类第一个抢」准得多。
    本机踩过：同类贪心 → 「教育经历」抢到工作经历的内容。
    """
    spec_sections = (skeleton_spec or {}).get("sections") or []
    if not spec_sections:
        return _sections_for_skeleton(sections)

    # ── 「求职意向」这类章节从 identity 填 ──
    #
    # 模板的页眉字段（意向城市/期望薪资/求职类型）本来就来自 identity，
    # **不该从 sections 里找** —— 数据里没有对应章节。
    #
    # 不做这步 → 「求职意向」章节空白（本机踩过）。
    _INTENT_KEYS = {
        "求职意向": ("headline", "location", "salary", "job_type"),
        "个人信息": ("phone", "email", "location"),
    }

    # 所有组合打分
    pairs = []
    for ti, tpl_sec in enumerate(spec_sections):
        tpl_title = tpl_sec.get("title") or ""
        for si, sec in enumerate(sections):
            pairs.append((_match_score(tpl_title, sec), ti, si))
    pairs.sort(key=lambda x: -x[0])

    assign = {}
    used_src = set()
    for score, ti, si in pairs:
        if score <= 0:
            break
        if ti in assign or si in used_src:
            continue
        assign[ti] = si
        used_src.add(si)

    out = []
    for ti, tpl_sec in enumerate(spec_sections):
        tpl_title = tpl_sec.get("title") or ""
        tpl_kind = tpl_sec.get("kind") or "paragraph"
        item = {"title": tpl_title, "kind": tpl_kind}

        si = assign.get(ti)
        if si is None:
            # ── 特殊章节：从 identity 填 ──
            intent = _INTENT_KEYS.get(tpl_title)
            if intent:
                bits = []
                for k in intent:
                    v = (identity or {}).get(k)
                    if v:
                        bits.append(str(v))
                if bits:
                    item["paragraphs"] = ["  |  ".join(bits)]
            else:
                item["paragraphs"] = []
                item["bullets"] = []
                item["entries"] = []
                item["tags"] = []
            out.append(item)
            continue

        sec = sections[si]
        # **内容形态看「源」里实际有什么** ——
        # 不能只看 kind 名字。
        #
        # 本机踩过：源章节是 `kind="text"`（有 paragraphs），
        # 模板章节是 `kind="list"`（要 bullets）→
        # 按 kind 名字取 → bullets 空了 → 「自我评价」章节空白。
        #
        # → 按**实际有哪些键**来取，缺了就从别的形态转。
        if sec.get("tags"):
            src_shape = "tags"
        elif sec.get("bullets"):
            src_shape = "list"
        elif sec.get("entries"):
            src_shape = "entry"
        else:
            src_shape = "paragraph"

        item.update(_convert_shape(sec, src_shape, tpl_kind))
        out.append(item)
    return out


def _convert_shape(sec, src_shape, tpl_kind):
    """把源章节的内容转成模板要的形态。

    ## 为什么必须转

    **模板的 kind 和数据的 kind 不一定一样** ——
    稻壳儿模板的「工作经历」被判成 `list`（因为下面有「1. 2. 3.」编号），
    而数据里是 `entry`（公司+日期+要点）。

    不转 → 模板要 bullets，数据只有 entries → **章节空白**。

    本机踩过：「工作经历」章节空着。

    ## 转换表

    | 源 → 目标 | 怎么转 |
    | --- | --- |
    | entry → list | 每个条目的标题 + 要点各成一条 |
    | entry → paragraph | 标题 + 要点拼成段落 |
    | list → entry | 整段当作一个条目的正文 |
    | paragraph → list | 每个段落一条 |
    | paragraph → entry | 整段当作一个条目 |
    | tags → list | 每个标签一条 |
    | tags → paragraph | 标签用「、」连接 |
    | 任意 → tags | 抽文本里的短词 |
    """
    out = {"paragraphs": [], "bullets": [], "entries": [], "tags": []}

    def _texts():
        if src_shape == "tags":
            return list(sec.get("tags") or [])
        if src_shape == "list":
            return [b.get("text", "") for b in (sec.get("bullets") or [])]
        if src_shape == "entry":
            res = []
            for e in (sec.get("entries") or []):
                res.append(e.get("title", ""))
                for b in (e.get("bullets") or []):
                    res.append(b.get("text", ""))
            return res
        return list(sec.get("paragraphs") or [])

    if tpl_kind == "tags":
        if src_shape == "tags":
            out["tags"] = list(sec.get("tags") or [])
        else:
            # 从文本里抽「短词」当标签
            tags = []
            for t in _texts():
                for part in re.split(r"[、,，/\s]+", t):
                    part = part.strip()
                    if 1 < len(part) <= 12:
                        tags.append(part)
            out["tags"] = tags[:24]
    elif tpl_kind == "list":
        if src_shape == "list":
            out["bullets"] = list(sec.get("bullets") or [])
        else:
            out["bullets"] = [{"text": t, "basis": ""}
                              for t in _texts() if t]
    elif tpl_kind == "entry":
        if src_shape == "entry":
            out["entries"] = list(sec.get("entries") or [])
        else:
            texts = [t for t in _texts() if t]
            if texts:
                out["entries"] = [{
                    "title": texts[0],
                    "meta": "",
                    "subtitle": "",
                    "bullets": [{"text": t, "basis": ""} for t in texts[1:]],
                }]
    else:
        if src_shape == "paragraph":
            out["paragraphs"] = list(sec.get("paragraphs") or [])
        elif src_shape == "tags":
            out["paragraphs"] = ["、".join(sec.get("tags") or [])]
        else:
            out["paragraphs"] = [t for t in _texts() if t]
    return out


def _uploaded_spec(template_id):
    """读上传模板的槽位规格（JSON）；没有返回 None。"""
    if not template_id:
        return None
    path = os.path.join(TEMPLATES_DIR, template_id + ".spec.json")
    if not os.path.exists(path):
        return None
    try:
        import json
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _sections_for_skeleton(sections):
    """把内置骨架的 sections 形态 → 骨架要的形态（无模板规格时的兜底）。"""
    out = []
    for sec in sections:
        title = sec.get("title") or ""
        kind = _CLASS_BY_TITLE.get(title, sec.get("kind") or "paragraph")
        item = {"title": title, "kind": kind}
        if kind == "tags":
            item["tags"] = sec.get("tags") or []
        elif kind == "list":
            item["bullets"] = sec.get("bullets") or []
        elif kind == "entry":
            item["entries"] = sec.get("entries") or []
        else:
            item["paragraphs"] = sec.get("paragraphs") or []
        out.append(item)
    return out


def render_html(template_id, context, css_override=None, photo=None,
                skeleton_override=None):
    """渲染一份简历 HTML。

    template_id: 内置 id，或用户上传转换出来的模板 id
    context:     {'title','identity','sections'} —— sections 每项：
                  {title, kind, paragraphs|bullets|tags|entries}
                  bullets/entries 的项：{text, basis}
    css_override: **直接给 CSS**，跳过「找模板」这一步。
    photo: 证件照的 data URI。None = 用设置页上传的那张；"" = 不要照片。
    skeleton_override: **直接给骨架 HTML** —— dry_run 预览用（骨架还没落盘）。

    ## 为什么需要 css_override

    **上传流程的「先预览再加入」**：
    转换时（dry_run）**不落盘** —— 用户不点确认就不会留下垃圾模板。
    但预览要渲染出真实版式 → **得用刚转换出来的 CSS**。

    没有这个参数就只能「先落盘再预览」——
    用户点了取消，磁盘上就多了一个模板（还要清理）。

    → dry_run 预览时把 CSS 直接传进来。
    """
    from jinja2 import Template

    css = css_override
    if css is None:
        css = get_builtin(template_id)
    if css is None:
        css = _uploaded_css(template_id)
    if css is None:
        raise FileNotFoundError("模板不存在: %s" % template_id)

    # ── 骨架选择 ──
    #
    # **上传的 PDF 模板有自己的骨架**（章节结构从模板来）。
    # 有骨架 → 用骨架（内容按模板的槽位填）。
    # 没骨架 → 用内置骨架（CSS 换色）。
    #
    # 用户：「现在有样式了，但与我提供的模板文件完全不同。」
    # → 差别就在这儿：**结构** vs **颜色**。
    # **骨架优先级**：显式传入 > 磁盘上的 > 无（走内置骨架）
    skeleton = skeleton_override or _uploaded_skeleton(template_id)

    ctx = dict(context)
    ctx["style"] = css
    ctx.setdefault("show_basis", False)
    ctx.setdefault("bg_image", uploaded_bg_image(template_id))
    # **证件照** —— 有就渲染圆形照片位，没有就不占位
    #
    # `photo=None` → 用设置页上传的那张（`_current_photo()`）
    # `photo=""` → 强制不要照片（测试用）
    if photo is None:
        photo = _current_photo()
    ctx["photo"] = photo

    if skeleton:
        # **骨架自带样式** —— 不再套 `{{ style }}`，
        # 骨架里的 CSS 已经包含了从 PDF 抽出来的配色/版面。
        ctx["style"] = ""
        spec = _uploaded_spec(template_id)
        ctx["sections"] = _align_to_skeleton(
            ctx.get("sections") or [], spec, ctx.get("identity") or {})
        return Template(skeleton).render(**ctx)
    return Template(_SKELETON).render(**ctx)


def template_info(template_id):
    """模板的展示信息（名字、描述、格式、是否内置）。

    ## `format` **必须有** —— 少一个字段前端就崩

    前端渲染模板卡时写了 `tpl.format.toUpperCase()`
    （显示「DOCX」「PDF」这种角标）。

    **本机真崩过**：`template_info` 原来只返回
    `name`/`description`/`builtin` —— **没有 `format`** →
    `Cannot read properties of undefined (reading 'toUpperCase')`
    → **整个路由渲染失败**（不是卡片不好看，是整页白屏报错）。

    → **这里必须给 `format`**，前端才拿得到。
    前端也要有兜底（`(tpl.format || 'docx')`）—— 两边都做。
    """
    tpl = BUILTIN.get(template_id)
    if tpl:
        return {"template_id": template_id, "name": tpl["name"],
                "description": tpl["description"],
                # 内置模板是 **HTML 模板**（不是某个上传文件的格式）
                "format": tpl.get("format") or "html",
                "builtin": True}
    path = os.path.join(TEMPLATES_DIR, template_id + ".css")
    if os.path.exists(path):
        return {"template_id": template_id, "name": template_id,
                "description": "上传的模板",
                # 上传的 .css 是从 docx/pdf 转换来的 —— 默认 docx
                "format": "docx",
                "builtin": False}
    return None


def list_all():
    """全部可用模板（内置 + 上传的）。

    **两个来源都要收**：
    - TEMPLATES_DIR 里的 .css 文件（上传转换出来的 CSS 片段）
    - SQLite 的 resume_templates 表（上传转换时登记的记录）

    只扫目录会漏掉「已登记但还没生成文件」的模板 ——
    上传转换是两步：先登记，再落文件。第二步没做完时，
    模板在库里但不在目录里，列表就少了它。
    """
    out = [template_info(t) for t in BUILTIN]
    seen = set(BUILTIN)

    if os.path.isdir(TEMPLATES_DIR):
        for name in sorted(os.listdir(TEMPLATES_DIR)):
            if not name.endswith(".css"):
                continue
            tid = name[:-4]
            if tid in seen:
                continue
            info = template_info(tid)
            if info:
                out.append(info)
                seen.add(tid)

    # 数据库里的登记记录（还没生成 HTML 的也算，标记清楚）
    #
    # 内置模板**不进这张表** —— 它们的真源是代码里的 BUILTIN，
    # 存一份到数据库只会造成两个真源打架。
    try:
        from . import storage as _storage
        for row in _storage.list_templates():
            tid = row.get("template_id")
            if not tid or tid in seen:
                continue
            if row.get("builtin"):
                continue
            out.append({
                "template_id": tid,
                "name": row.get("name") or tid,
                "description": row.get("description") or "",
                "format": row.get("format") or "docx",
                "builtin": False,
                "source_path": row.get("source_path") or "",
                "preview_path": row.get("preview_path") or "",
                "pending": True,      # 还没生成 HTML —— 渲染时回退到默认模板
            })
            seen.add(tid)
    except Exception:
        pass

    return out
