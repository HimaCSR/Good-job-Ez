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
.head { margin-bottom: 14px; }
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


def render_html(template_id, context, css_override=None):
    """渲染一份简历 HTML。

    template_id: 内置 id，或用户上传转换出来的模板 id
    context:     {'title','identity','sections'} —— sections 每项：
                  {title, kind, paragraphs|bullets|tags|entries}
                  bullets/entries 的项：{text, basis}
    css_override: **直接给 CSS**，跳过「找模板」这一步。

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

    ctx = dict(context)
    ctx["style"] = css
    ctx.setdefault("show_basis", False)
    ctx.setdefault("bg_image", uploaded_bg_image(template_id))
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
