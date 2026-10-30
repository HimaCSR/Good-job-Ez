"""简历模板的**骨架规格**（slot spec）—— 从模板文件里抽出「槽位」。

## 这解决什么问题

用户：「你是不是做不到简历模板识别生成对应的 html，
然后简历优化时根据个人信息填入相应的内容？」

**以前确实做不到** —— 原因不是「识别不了」，是**架构里没有这一层**：

```
旧：模板文件 → 只产出一份 CSS
    内置骨架 → 固定的 HTML 结构（所有模板共用）
```

→ 传什么模板，最终 HTML 结构都一样，只是换了颜色。

**现在**：

```
模板文件 → 骨架规格（槽位表）+ CSS
骨架规格 → 生成 HTML（模板自己的结构）
个人信息 → 按槽位填进去
```

## 骨架规格长什么样

```json
{
  "version": 1,
  "source": "pdf",
  "head": {
    "name": {"text": "稻壳儿", "size": 26.33, "color": "#4066b0"},
    "fields": [
      {"label": "电话", "value": "1388888888", "size": 10.24},
      {"label": "邮箱", "value": "docker@wps.cn", "size": 10.24}
    ],
    "photo": {"x": 430, "y": 680, "w": 124, "h": 161}
  },
  "sections": [
    {"title": "求职意向", "kind": "paragraph", "sample": "意向城市: 珠海"},
    {"title": "自我评价", "kind": "list", "sample": ["1. 拥有3年…", "2. 在项目…"]}
  ]
}
```

**`sample` 是模板自带的示例内容** —— 只是给人看的，
**填内容时会被替换掉**（绝不填进你的简历）。

## 槽位角色（role）

| role | 含义 | 填充来源 |
| --- | --- | --- |
| `name` | 姓名 | `identity.name` |
| `field` | 联系方式项（电话/邮箱…） | `identity.*` |
| `section` | 章节标题 | 章节名 |
| `body` | 正文段落 | 章节内容 |
| `photo` | 照片位 | 设置页上传的证件照 |

**半自动**：`_guess_slots` 先猜一遍，用户在预览里点选修正。
猜不准很正常 —— 「电话：」后面那串数字到底该填到哪，
机器只能猜。

## 坐标约定

PDF 用户坐标：**y 向上**（左下原点）。
本模块内部统一转成 **y 向下**（左上原点，跟 CSS 一致），
避免下游再转一次。
"""

import os
import re

__all__ = [
    "extract_slots",
    "build_slot_html",
    "fill_slots",
    "SPEC_VERSION",
]

SPEC_VERSION = 1


# ── 章节类型 ────────────────────────────────────────────────────────────────
#
# 模板里的章节长什么样，从内容能看出来：
#   - 「1. xxx」「2. xxx」→ 编号列表（list）
#   - 「2020.06 - 2024.06」开头 → 条目（entry）
#   - 一整段 → 段落（paragraph）
#   - 一堆短词 → 标签（tags）

_KIND_LIST = "list"
_KIND_ENTRY = "entry"
_KIND_PARAGRAPH = "paragraph"
_KIND_TAGS = "tags"

# 「2020.06 - 2024.06」「2019.1-2019.1」「2023.08 — 至今」
_DATE_RANGE = re.compile(
    r"^\s*\d{4}[.\-/年]\s*\d{0,2}\s*[-–—~至到]\s*"
    r"(\d{4}[.\-/年]\s*\d{0,2}|至今|现在|今|\d{4})")
# 编号列表「1. 」「1、」「(1)」「①」
_NUMBERED = re.compile(r"^\s*(\d{1,2}\s*[.、．)）]|[①-⑳]|\([1-9]\))")
# 「电话：」「手机:」
_LABEL = re.compile(r"^\s*([\u4e00-\u9fff A-Za-z]{1,8})\s*[:：]\s*(.*)$")


def _to_top_down(y, page_h):
    """PDF 坐标（y 向上）→ CSS 坐标（y 向下）。"""
    return round(page_h - y, 2)


def _group_lines(items, tol=2.5):
    """文字块 → 行（同一行的合并）。

    PDF 里一行可能被拆成好几块（「意向岗位:」+「现场管理」）。
    按 y 聚类 → 合成一行。
    """
    rows = []
    for it in sorted(items, key=lambda i: (-i["y"], i["x"])):
        placed = False
        for row in rows:
            if abs(row["y"] - it["y"]) <= tol:
                row["items"].append(it)
                row["y"] = (row["y"] * (len(row["items"]) - 1) + it["y"]) / len(row["items"])
                placed = True
                break
        if not placed:
            rows.append({"y": it["y"], "items": [it]})
    out = []
    for row in rows:
        its = sorted(row["items"], key=lambda i: i["x"])
        text = "".join(i["text"] for i in its)
        out.append({
            "y": row["y"],
            "x": its[0]["x"],
            "text": text,
            "items": its,
            "size": max(i["size"] for i in its),
            "color": its[0]["color"],
        })
    return out


def _classify_section(lines):
    """一行内容 → 章节类型。"""
    if not lines:
        return _KIND_PARAGRAPH
    texts = [l["text"].strip() for l in lines if l["text"].strip()]
    if not texts:
        return _KIND_PARAGRAPH
    numbered = sum(1 for t in texts if _NUMBERED.match(t))
    if numbered >= max(2, len(texts) // 2):
        return _KIND_LIST
    if _DATE_RANGE.match(texts[0]):
        return _KIND_ENTRY
    # 全是短词（< 12 字）且超过 2 条 → 标签
    if len(texts) >= 3 and all(len(t) <= 12 for t in texts):
        return _KIND_TAGS
    return _KIND_PARAGRAPH


def _split_fields(line):
    """一行拆成 [{label, value}]。

    「电话：1388888888」→ [{label: 电话, value: 1388888888}]
    「电话：1388888888  邮箱：docker@wps.cn」→ 两条

    ## 为什么要按 x 坐标先分组

    PDF 里「性别：女」和「年龄：25」是**左右两栏**，
    两块文字**各占一半宽度**。直接拼成一行 → 「性别：女年龄：25」
    → 标签被切成「女年龄」（标签正则吃到跨栏内容）。

    本机踩过：字段切分后标签变成「女年龄」「k求职类型」——
    全是跨栏粘连。→ 先按 x 间隙切栏，再在栏内切标签。

    ## 怎么判断是「两栏」还是「紧挨着」

    同一行里两块文字的 x 间隙 **> 前一块宽度的 60%** → 两栏。
    「意向岗位:现场管理」两块挨得很近（间隙小）→ 一栏。
    """
    items = line.get("items") or []
    text = line["text"]
    out = []

    # ── 没有分块信息 → 直接按文本切 ──
    if len(items) < 2:
        return _split_fields_text(text, line)

    # ── 按 x 间隙分栏 ──
    span = max(i["x"] for i in items) - min(i["x"] for i in items)
    if span <= 0:
        return _split_fields_text(text, line)
    groups = [[items[0]]]
    for prev, cur in zip(items, items[1:]):
        # **间隙 = 起点差 - 前一块的宽度** ——
        #
        # 用 `cur.x - prev.x` 是错的：「电话：」（x=47.17）和
        # 「1388888888」（x=77.88）**首尾相接**（前一块结束于 77.87），
        # 但起点差是 30.7 → 误判成两栏 → 值被切走 → value 空了。
        #
        # 本机踩过：字段 value 全空。
        prev_end = prev["x"] + _text_width(prev["text"], prev["size"])
        gap = cur["x"] - prev_end
        if gap > 8:
            groups.append([cur])
        else:
            groups[-1].append(cur)
    for g in groups:
        # **栏内所有块拼起来** —— 「电话：」和「1388888888」是**两块**
        # （x 挨得很近 → 同一栏），值在第二块里。
        #
        # 不拼 → 每块单独切 → 值那块没有「标签：」→ value 空了。
        seg = "".join(i["text"] for i in g)
        out.extend(_split_fields_text(seg, line))
    return out


def _text_width(text, size):
    """粗略估文字宽度（pt）—— 中日韩按 1 个字宽，ASCII 按 0.5。"""
    w = 0.0
    for ch in str(text):
        if ord(ch) > 0x2E80:
            w += 1.0
        else:
            w += 0.5
    return w * size


def _split_fields_text(text, line):
    """文本 → [{label, value}]。"""
    out = []
    marks = list(re.finditer(r"([一-鿿 A-Za-z]{1,8})\s*[:：]", text))
    if not marks:
        return out
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        value = text[m.end():end].strip()
        label = m.group(1).strip()
        # **标签不能太长** —— 中文标签一般 ≤ 5 字
        if len(label) > 6:
            continue
        out.append({
            "label": label,
            "value": value,
            "size": line["size"],
            "color": line["color"],
        })
    return out


def _size_tiers(lines):
    """字号分层 —— 从大到小。

    WPS 模板里字号是分层的：姓名 > 章节标题 > 条目 > 正文。
    **分层比「固定百分比」可靠** —— 页眉区多高取决于模板，
    不是取决于页面高度的百分之多少。
    """
    from collections import Counter
    sizes = Counter(round(l["size"], 1) for l in lines if l["text"].strip())
    if not sizes:
        return []
    ordered = sorted(sizes.items(), key=lambda kv: -kv[0])
    # **合并相近的字号** —— 25.5 和 26.33 其实是同一档
    tiers = []
    for size, _n in ordered:
        if tiers and abs(size - tiers[-1]) < 1.2:
            continue
        tiers.append(size)
    return tiers


def _pick_name(lines, tiers):
    """姓名 = 页眉区里字号最大的那块。

    ## 排除「标签：」型

    「电话：1388888888」也是大字号（有些模板就长这样）——
    但它不是姓名。用 `_LABEL` 排除。
    """
    if not tiers:
        return None, None
    big = tiers[0]
    cand = [l for l in lines
            if l["text"].strip() and abs(l["size"] - big) < 1.2]
    # **排除标签型**
    cand = [l for l in cand if not _LABEL.match(l["text"].strip())]
    if not cand:
        return None, big
    # **取最靠上的那个** —— 姓名总在页眉最上面
    cand.sort(key=lambda l: -l["y"])
    line = cand[0]
    return {
        "text": line["text"].strip(),
        "size": line["size"],
        "color": line["color"],
        "x": line["x"],
        "y": line["y"],
    }, big


def _guess_sections(lines, tiers, name_y):
    """猜章节。

    ## 章节标题的判据

    - **字号是第二大那档**（比正文大，比姓名小）
    - **文字短**（≤ 20 字）
    - **在姓名下方**（页眉区不算章节）

    ## 页眉区的边界怎么定

    **不用固定百分比** —— 用「第一个章节标题的位置」。
    稻壳儿模板的联系方式一直排到 y=660（占页面 24%），
    固定 25% 会把它切掉。

    本机踩过：固定百分比 → 「求职意向」被当成页眉里的字段 →
    章节少了一个 → 内容填不进去。
    """
    if len(tiers) < 2:
        return []
    sec_size = tiers[1]
    candidates = [l for l in lines
                  if l["text"].strip()
                  and abs(l["size"] - sec_size) < 1.2
                  and len(l["text"].strip()) <= 20
                  and (name_y is None or l["y"] < name_y - 1)]
    if not candidates:
        return []

    sections = []
    cur = None
    for line in sorted(candidates + [l for l in lines
                                     if l not in candidates],
                       key=lambda l: -l["y"]):
        txt = line["text"].strip()
        if not txt:
            continue
        is_title = line in candidates
        if is_title:
            cur = {"title": txt, "lines": [], "size": line["size"],
                   "color": line["color"], "y": line["y"]}
            sections.append(cur)
            continue
        if cur is not None:
            cur["lines"].append(line)
    for sec in sections:
        sec["kind"] = _classify_section(sec["lines"])
        sec["sample"] = [l["text"].strip() for l in sec["lines"]
                         if l["text"].strip()][:6]
        sec.pop("lines", None)
        sec.pop("y", None)
    return sections


def _guess_fields(lines, header_bottom):
    """猜联系方式项。

    ## 页眉区边界

    **= 第一个章节标题的 y**（不是页面高度的百分比）。

    ## 字段的判据

    1. 在页眉区内
    2. 含「标签：」
    3. 标签 ≤ 6 字
    """
    fields = []
    for line in lines:
        if header_bottom is not None and line["y"] < header_bottom:
            continue
        for f in _split_fields(line):
            if f["label"] and (f["value"] or len(f["label"]) <= 4):
                fields.append(f)
    return fields


def _body_size(lines, page_h):
    """正文字号 = 页眉区外、最常见的字号。"""
    from collections import Counter
    sizes = Counter()
    for line in lines:
        if line["y"] <= page_h * 0.75 and line["text"].strip():
            sizes[round(line["size"], 1)] += 1
    if not sizes:
        return 10.5
    return sizes.most_common(1)[0][0]


def extract_slots(data, source="pdf"):
    """模板文件 → 骨架规格。

    返回 (spec, note)。spec 为 None 表示抽不出来。
    """
    if source == "pdf":
        import template_convert as tc
        items = tc._pdf_text_items(data)
        if not items:
            return None, "这个 PDF 里没抽出文字（可能是扫描件）。"
        # 页面高
        rects = []
        alphas = tc._pdf_alpha_map(data)
        objs = tc._pdf_objects(data)
        forms = tc._pdf_forms(data, objs)
        texts, _ = tc._pdf_streams(data)
        content = ""
        for t in texts:
            if re.search(r"/\S+\s+[\d.]+\s+Tf", t):
                content = t
                break
        if content:
            rects = tc._pdf_rects(content, alphas, forms)
        # **页面尺寸要用 MediaBox，不能用矩形坐标范围** ——
        # 很多模板在开头用 `0.24 0 0 -0.24 0 870 cm` **上下翻转**，
        # 翻转后 y 从 870 变成 -870 → 范围是 1740（翻倍了）。
        #
        # 本机踩过：page_h 算成 1740 → 「页眉区」判定全错 →
        # 姓名被当成章节标题、联系方式一个都抽不到。
        page_w = page_h = None
        try:
            size = tc._pdf_page_size(data)      # mm
            if size:
                page_h = size[1] / 25.4 * 72.0    # mm → pt
                page_w = size[0] / 25.4 * 72.0
        except Exception:
            pass
        if not page_h:
            page_h = max(i["y"] for i in items) or 842.0
        if not page_w:
            page_w = max(i["x"] for i in items) or 595.0
    else:
        return None, "暂不支持 %s 的骨架提取。" % source

    lines = _group_lines(items)
    body = _body_size(lines, page_h)
    tiers = _size_tiers(lines)

    # ── 姓名 ──
    name_slot, big = _pick_name(lines, tiers)
    name_y = name_slot["y"] if name_slot else None

    # ── 章节（先定章节，页眉边界才有着落）──
    sections = _guess_sections(lines, tiers, name_y)
    # **页眉区下边界 = 第一个章节标题的 y**
    header_bottom = None
    if sections:
        header_bottom = min(
            l["y"] for l in lines
            if l["text"].strip() and abs(l["size"] - sections[0]["size"]) < 1.2
            and len(l["text"].strip()) <= 20 and
            (name_y is None or l["y"] < name_y - 1))
    elif name_y is not None:
        header_bottom = name_y - 60

    fields = _guess_fields(lines, header_bottom)
    if name_slot:
        name_slot["y"] = _to_top_down(name_slot["y"], page_h)

    # **页眉是不是深色** ——
    # 从 PDF 版面结构里看「页眉底块」的亮度。
    # 深底 → 页眉文字要反白；白底 → 用深色字。
    #
    # **不能一律反白** —— 白底模板上白字 = 隐形（本机踩过）。
    header_is_dark = False
    try:
        import template_convert as _tc
        _alphas = _tc._pdf_alpha_map(data)
        _objs = _tc._pdf_objects(data)
        _forms = _tc._pdf_forms(data, _objs)
        _texts, _ = _tc._pdf_streams(data)
        _content = ""
        for _t in _texts:
            if re.search(r"/\S+\s+[\d.]+\s+Tf", _t):
                _content = _t
                break
        if _content:
            _rects = _tc._pdf_rects(_content, _alphas, _forms)
            if _rects:
                _ph = max(r[3] for r in _rects) - min(r[1] for r in _rects)
                _pw = max(r[2] for r in _rects) - min(r[0] for r in _rects)
                _lay = _tc._pdf_layout(_rects, _pw, _ph)
                header_is_dark = bool(_lay.get("_header_is_dark"))
    except Exception:
        header_is_dark = False

    spec = {
        "version": SPEC_VERSION,
        "source": source,
        "page": {"width": round(page_w, 1), "height": round(page_h, 1)},
        "body_size": body,
        "head": {"name": name_slot, "fields": fields,
                 "header_is_dark": header_is_dark},
        "sections": sections,
    }
    note = ""
    if not name_slot:
        note = "没认出姓名位置（页眉最大号的那块文字）。"
    elif not sections:
        note = "没认出章节标题（字号比正文大、且较短的那些行）。"
    return spec, note


# ── 槽位编辑（半自动） ─────────────────────────────────────────────────────
#
# **用户选的方案**：解析出骨架后，**在预览里点一下「这段是什么」**，
# 存进模板。一次确认，永久复用。
#
# ## 为什么需要「点选」这一层
#
# 自动推断**必然有猜错的时候**：
# 「电话：1388888888」到底是**联系方式**还是**正文**？
# 「意向城市：珠海」算**页眉字段**还是**求职意向章节**？
#
# 猜错 → 填错位置 → 简历看起来不对，但用户不知道错在哪。
# → 让用户点一下就解决了 —— **一次确认，永久复用**。

# 可选的槽位角色（前端菜单里列的就是这些）
ROLES = [
    {"role": "name", "label": "姓名", "hint": "最大的那行字（页眉）"},
    {"role": "field", "label": "联系方式", "hint": "电话 / 邮箱 / 性别…"},
    {"role": "section", "label": "章节标题", "hint": "分段的大标题"},
    {"role": "body", "label": "正文", "hint": "段落内容"},
    {"role": "skip", "label": "忽略", "hint": "不管它"},
]

_ROLE_LABELS = {r["role"]: r["label"] for r in ROLES}


def apply_slot_edit(spec, edit):
    """把用户的点选结果应用到槽位规格。

    ## edit 的形状

    ```json
    {
      "name": {"text": "张三"},              // 或 null（取消姓名）
      "fields": [{"label": "电话", "value": "138..."}],
      "sections": [{"title": "工作经历", "kind": "entry"}]
    }
    ```

    ## 为什么要整体替换而不是「打补丁」

    用户点选是**在完整列表上编辑** —— 删了一个字段、
    改了一个章节标题。前端传完整列表，后端整体写回。
    打补丁要处理增删改三种情况，容易出边界 bug。

    ## 字段标签要能映射到 identity 的键

    「电话」→ `phone`。映射不出来的字段**不渲染**（免得出现空标签）。
    """
    if not isinstance(spec, dict):
        return spec
    spec = dict(spec)
    head = dict(spec.get("head") or {})

    if "name" in edit:
        name = edit.get("name")
        if not name:
            head["name"] = None
        else:
            old = head.get("name") or {}
            merged = dict(old)
            merged.update({k: v for k, v in (name or {}).items()
                           if k in ("text", "size", "color", "x", "y")})
            head["name"] = merged

    if "fields" in edit:
        fields = []
        for f in (edit.get("fields") or []):
            if not isinstance(f, dict):
                continue
            label = str(f.get("label") or "").strip()
            if not label:
                continue
            fields.append({
                "label": label,
                "value": str(f.get("value") or ""),
                "size": f.get("size") or 10,
                "color": f.get("color") or "#444444",
            })
        head["fields"] = fields

    if "sections" in edit:
        secs = []
        old_sections = spec.get("sections") or []
        for idx, sc in enumerate(edit.get("sections") or []):
            if not isinstance(sc, dict):
                continue
            title = str(sc.get("title") or "").strip()
            if not title:
                continue
            kind = sc.get("kind")
            if kind not in (_KIND_LIST, _KIND_ENTRY, _KIND_PARAGRAPH, _KIND_TAGS):
                kind = _KIND_PARAGRAPH
            item = {"title": title, "kind": kind}
            # **按「位置」找旧章节保留样式** ——
            # 按标题找的话，用户**改了标题**就找不到旧的了 →
            # 字号/颜色全丢 → 改完标题，章节大小跟原来不一样。
            #
            # 本机踩过：改标题后 size 没了。
            old = None
            if idx < len(old_sections):
                old = old_sections[idx]
            elif old_sections:
                # 位置对不上（用户调整了顺序）→ 退回按标题找
                for o in old_sections:
                    if o.get("title") == title:
                        old = o
                        break
            if old:
                if old.get("size") is not None:
                    item["size"] = old.get("size")
                if old.get("color") is not None:
                    item["color"] = old.get("color")
                if old.get("sample") is not None:
                    item["sample"] = old.get("sample")
            secs.append(item)
        spec["sections"] = secs

    spec["head"] = head
    spec["edited"] = True
    return spec


def spec_to_edit(spec):
    """槽位规格 → 前端好编辑的形状。"""
    spec = spec or {}
    head = spec.get("head") or {}
    name = head.get("name") or {}
    return {
        "header_is_dark": bool(head.get("header_is_dark")),
        "name": {
            "text": name.get("text") or "",
            "size": name.get("size") or 0,
            "color": name.get("color") or "",
        } if name else None,
        "fields": [{
            "label": f.get("label") or "",
            "value": f.get("value") or "",
            "size": f.get("size") or 0,
            "color": f.get("color") or "",
        } for f in (head.get("fields") or [])],
        "sections": [{
            "title": s.get("title") or "",
            "kind": s.get("kind") or _KIND_PARAGRAPH,
            "size": s.get("size") or 0,
            "color": s.get("color") or "",
            "sample": s.get("sample") or [],
        } for s in (spec.get("sections") or [])],
    }


def slot_role_labels():
    """前端菜单用的角色列表。"""
    return [{"role": r["role"], "label": r["label"], "hint": r["hint"]}
            for r in ROLES]

# ── HTML 生成 ───────────────────────────────────────────────────────────────
#
# **生成的 HTML 要能被 Jinja 填内容** —— 所以用占位符变量名，
# 不是写死的文字。

_CSS = """
/* 从模板抽出的骨架样式 */
.tpl-body { font-family: %(font_family)s; font-size: %(font_size)spx; color: %(text_color)s; }
.tpl-page { position: relative; width: %(page_width)smm; min-height: %(page_height)smm; margin: 0 auto; }
.tpl-head { position: relative; margin-bottom: 8mm; %(head_extra)s }
/* **深色页眉上的字段要反白** ——
   PDF 抽出来的 `.contact span` 是深色（#444）→ 深蓝底上**看不清**。

   ⚠️ **只能给深色页眉加** —— 白底模板上白字 = **隐形**。
   本机踩过：稻壳儿（白底）的电话邮箱在 HTML 里但**看不见**。
   → 靠 `.tpl-head-dark` 类区分，不是一律反白。 */
.tpl-head-dark .tpl-field { color: rgba(255,255,255,.9); }
.tpl-head-dark .tpl-field b { color: #ffffff; }
.tpl-head-dark .tpl-name { color: #ffffff; }
.tpl-head-dark .tpl-sub { color: rgba(255,255,255,.85); }
.tpl-name { font-size: %(name_size)spx; font-weight: 700; color: %(name_color)s; line-height: 1.25; }
.tpl-sub { font-size: %(sub_size)spx; color: %(sub_color)s; margin-top: 2px; }
.tpl-fields { margin-top: 4px; display: flex; flex-wrap: wrap; gap: 2px 14px; }
.tpl-field { font-size: %(field_size)spx; color: %(field_color)s; }
.tpl-field b { font-weight: 600; color: %(label_color)s; }
.tpl-photo { position: absolute; top: 0; right: 0; width: %(photo_w)smm; height: %(photo_h)smm; overflow: hidden; border-radius: 2px; }
.tpl-photo img { width: 100%%; height: 100%%; object-fit: cover; display: block; }
.tpl-sec { margin-bottom: 6mm; }
.tpl-sec-title { font-size: %(sec_size)spx; font-weight: 700; color: %(sec_color)s; margin-bottom: 2.5mm; %(sec_title_extra)s }
.tpl-body-text { font-size: %(body_size)spx; line-height: 1.55; color: %(text_color)s; }
.tpl-list { margin: 0; padding-left: 4mm; }
.tpl-list li { font-size: %(body_size)spx; line-height: 1.55; color: %(text_color)s; margin-bottom: 1px; }
.tpl-entry { margin-bottom: 3mm; }
.tpl-entry-head { display: flex; align-items: baseline; gap: 8px; }
.tpl-entry-title { font-size: %(entry_size)spx; font-weight: 650; color: %(entry_color)s; }
.tpl-entry-meta { font-size: %(meta_size)spx; color: %(meta_color)s; margin-left: auto; }
.tpl-entry-sub { font-size: %(entry_sub_size)spx; color: %(entry_sub_color)s; }
.tpl-tags { display: flex; flex-wrap: wrap; gap: 2px 6px; }
.tpl-tag { font-size: %(tag_size)spx; padding: 1px 7px; border-radius: 2px; background: %(tag_bg)s; color: %(tag_color)s; }
"""

_BUILTIN_FONT = '"Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif'


def _px(pt):
    try:
        v = round(float(pt) * 4 / 3, 1)
    except (TypeError, ValueError):
        return 12
    return int(v) if float(v).is_integer() else v


# PDF 抽出来的 CSS 用的类名 → 骨架用的类名
#
# **为什么要映射**
#
# `_pdf_to_css` 生成的样式是给**内置骨架**用的（`.sec-title` / `.head` …），
# 而骨架用的是另一套类名（`.tpl-sec-title` / `.tpl-head` …）。
#
# 不映射 → PDF 抽出来的装饰（侧边竖带、章节方块、分隔线）**全落空**
# → 用户看到的还是「只有文字的简历」，跟原模板不像。
#
# 本机踩过：骨架对了但装饰层全丢 → 「骨架像、皮肤不像」。

_CSS_ALIASES = {
    # **`.page` 必须有** —— PDF 的侧边竖带是靠
    # `.page { border-left: 4.2mm solid #d8dff0 }` 实现的。
    # 不映射 → 竖带落空 → 模板少了最显眼的那条竖色带。
    #
    # 本机踩过：别名表里漏了 `.page` → 竖带没了。
    ".page": ".tpl-page",
    ".content": ".tpl-content",
    ".head": ".tpl-head",
    ".name": ".tpl-name",
    ".sub": ".tpl-sub",
    ".contact": ".tpl-fields",
    ".contact span": ".tpl-field",
    ".sec-title": ".tpl-sec-title",
    ".item-title": ".tpl-entry-title",
    ".item-meta": ".tpl-entry-meta",
    ".bullets": ".tpl-list",
    ".bullets li": ".tpl-list li",
    ".tags": ".tpl-tags",
    ".tag": ".tpl-tag",
    ".sec": ".tpl-sec",
    ".item": ".tpl-entry",
}


def _remap_css(css):
    """把 PDF 抽出来的 CSS 类名映射到骨架类名。

    **只改选择器，不改声明** —— 颜色/尺寸/边框都原样保留。

    ## 为什么要映射

    `_pdf_to_css` 产出的是给**内置骨架**的样式（`.sec-title`），
    骨架用的是 `.tpl-sec-title` —— 不映射的话装饰全落空。
    """
    if not css:
        return ""
    # **长类名先替换** —— `.sec-title` 和 `.sec-title::before`
    # 同时存在，先替换长的，否则伪元素会漏掉。
    for src in sorted(_CSS_ALIASES, key=len, reverse=True):
        dst = _CSS_ALIASES[src]
        # **只在选择器位置替换** —— 声明里可能出现同名字符串。
        # 用「前后不是标识符字符」界定选择器边界。
        css = re.sub(r"(?<![\w\-])" + re.escape(src) + r"(?![\w\-])",
                     dst, css)
    return css


def build_slot_html(spec, style=None):
    """骨架规格 + 样式 → HTML 模板字符串（带 Jinja 占位符）。

    ## 为什么要单独一套骨架

    内置骨架写死了「个人简介/专业技能/工作经历/教育背景」——
    但模板自己的章节可能是「求职意向/自我评价/项目经历/实习经历」。

    → 章节标题**从模板来**，内容**从数据来**。
    """
    style = style or {}
    head = spec.get("head") or {}
    name = head.get("name") or {}
    fields = head.get("fields") or []
    sections = spec.get("sections") or []
    page = spec.get("page") or {}

    # ── 页眉 ──
    # **深色页眉要加类名** —— 白底模板不能用白字（隐形）。
    #
    # **spec 优先于 style** —— `header_is_dark` 是**从 PDF 版面算出来的**，
    # 存在 spec 里；style 是「额外传进来的样式参数」。
    # 只看 style → 重建骨架时忘了传 → 深底模板的字段看不清。
    head_dark = bool(
        (spec.get("head") or {}).get("header_is_dark")
        or style.get("header_is_dark"))
    head_html = ['  <div class="tpl-head' + (' tpl-head-dark' if head_dark else '') + '">']
    if head.get("photo"):
        head_html.append(
            '    <div class="tpl-photo">{% if photo %}'
            '<img src="{{ photo }}" alt="证件照">{% endif %}</div>')
    head_html.append(
        '    <div class="tpl-name">{{ identity.name or "姓名" }}</div>')
    if name:
        head_html.append(
            '    {% if identity.headline %}'
            '<div class="tpl-sub">{{ identity.headline }}</div>{% endif %}')
    if fields:
        head_html.append('    <div class="tpl-fields">')
        seen = set()
        for f in fields:
            key = _field_key(f.get("label") or "")
            # **认不出来的字段不渲染** —— `identity` 里没这个键，
            # Jinja 会渲染成空（undefined），模板上出现一个空标签。
            if not key or key in seen:
                continue
            seen.add(key)
            head_html.append(
                "      {% if identity." + key + " %}<span class=\"tpl-field\">"
                "<b>" + f.get("label", "") + "</b>{{ identity." + key
                + " }}</span>{% endif %}")
        head_html.append('    </div>')
    head_html.append('  </div>')

    # ── 章节 ──
    #
    # **每种 kind 一段独立的循环** ——
    # Jinja 里 `sec.kind` 是运行时的值，不能在生成时决定用哪个分支。
    # → 四种 kind 各写一段循环，段内用 `sec.kind == "xxx"` 过滤。
    #
    # （之前只按第一个章节的 kind 生成一段 → 列表章节渲染成段落
    #   → 「1. xxx」编号丢了。）
    # **章节标题用 `{{ sec.title }}`** ——
    # 标题**由调用方塞进来**，而且塞的是**模板自己的标题**
    # （「求职意向」「自我评价」「实习经历」），
    # 不是数据里的（「个人简介」「工作经历」）。
    #
    # 标题写死在这里会出错：外面套着 `{% for sec in sections %}`，
    # 每个 section 都会重复一次标题。
    #
    # 模板章节 vs 用户章节的对应关系，在 `resume_template._align_to_skeleton`
    # 里做 —— 按语义匹配（工作经历 ↔ 实习经历 ↔ 项目经历 都是 entry）。
    sec_html = ['  {% for sec in sections %}']
    sec_html.append('  <div class="tpl-sec">')
    sec_html.append(
        '    <div class="tpl-sec-title">{{ sec.title }}</div>')

    # 段落
    sec_html.append(
        '    {% if sec.kind == "paragraph" and sec.paragraphs %}'
        '<div class="tpl-body-text">')
    sec_html.append(
        '      {% for p in sec.paragraphs %}<p>{{ p }}</p>{% endfor %}')
    sec_html.append('    </div>{% endif %}')

    # 编号列表
    sec_html.append(
        '    {% if sec.kind == "list" and sec.bullets %}'
        '<ul class="tpl-list">')
    sec_html.append(
        '      {% for b in sec.bullets %}<li>{{ b.text }}</li>{% endfor %}')
    sec_html.append('    </ul>{% endif %}')

    # 标签
    sec_html.append(
        '    {% if sec.kind == "tags" and sec.tags %}'
        '<div class="tpl-tags">')
    sec_html.append(
        '      {% for t in sec.tags %}<span class="tpl-tag">{{ t }}</span>'
        '{% endfor %}')
    sec_html.append('    </div>{% endif %}')

    # 条目
    sec_html.append(
        '    {% if sec.kind == "entry" %}'
        '{% for e in sec.entries %}<div class="tpl-entry">')
    sec_html.append(
        '      <div class="tpl-entry-head">'
        '<span class="tpl-entry-title">{{ e.title }}</span>'
        '<span class="tpl-entry-meta">{{ e.meta }}</span></div>')
    sec_html.append(
        '      {% if e.subtitle %}<div class="tpl-entry-sub">'
        '{{ e.subtitle }}</div>{% endif %}')
    sec_html.append(
        '      {% if e.bullets %}<ul class="tpl-list">')
    sec_html.append(
        '        {% for b in e.bullets %}<li>{{ b.text }}</li>{% endfor %}')
    sec_html.append('      </ul>{% endif %}')
    sec_html.append('    </div>{% endfor %}{% endif %}')

    sec_html.append('  </div>')
    sec_html.append('  {% endfor %}')

    css = _CSS % {
        "font_family": style.get("font_family") or _BUILTIN_FONT,
        "font_size": _px(spec.get("body_size") or 10.5),
        "text_color": style.get("text_color") or "#333333",
        "page_width": _num(style.get("page_width_mm") or 178),
        "page_height": _num(style.get("page_height_mm") or 269),
        "head_extra": style.get("head_extra") or "",
        "name_size": _px(name.get("size") or 20),
        "name_color": name.get("color") or style.get("accent_color") or "#2f6fd0",
        "sub_size": _px((name.get("size") or 20) * 0.55),
        "sub_color": "#555555",
        "field_size": _px((fields[0].get("size") or 10) if fields else 10),
        # **颜色可能是 None** —— `.get("color")` 在键不存在时返回 None，
        # 直接塞进 CSS 会变成 `color: None` → 浏览器忽略 → 颜色丢失。
        #
        # 本机踩过：`.tpl-field { color: None; }` → 联系方式没有颜色。
        "field_color": (fields[0].get("color") or "#444444") if fields else "#444444",
        "label_color": style.get("accent_color") or "#2f6fd0",
        "photo_w": _num(style.get("photo_w_mm") or 30),
        "photo_h": _num(style.get("photo_h_mm") or 38),
        # **size / color 都可能是 None** —— `.get()` 在键不存在时返回 None，
        # 直接进 CSS 会变成 `font-size: Nonepx` / `color: None`
        # → 浏览器忽略 → 样式丢失。
        "sec_size": _px(((sections[0].get("size") or 13) if sections else 13)),
        "sec_color": ((sections[0].get("color") or style.get("accent_color")
                       or "#2f6fd0") if sections
                      else (style.get("accent_color") or "#2f6fd0")),
        "sec_title_extra": style.get("sec_title_extra") or "",
        "body_size": _px(spec.get("body_size") or 10.5),
        "entry_size": _px((spec.get("body_size") or 10.5) * 1.15),
        "entry_color": style.get("title_color") or "#1a1a1a",
        "meta_size": _px((spec.get("body_size") or 10.5) * 1.05),
        "meta_color": "#666666",
        "entry_sub_size": _px((spec.get("body_size") or 10.5) * 1.0),
        "entry_sub_color": "#525252",
        "tag_size": _px((spec.get("body_size") or 10.5) * 0.95),
        "tag_bg": style.get("tag_bg") or "#f2f4f7",
        "tag_color": style.get("tag_color") or "#333333",
    }

    html = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>{{ title }}</title>",
        "<style>",
        "body { margin: 0; padding: 16mm; background: #fff; }",
        css,
        _remap_css(style.get("extra_css") or ""),
        "</style>",
        "</head>",
        "<body>",
        '<div class="tpl-page">',
    ] + head_html + sec_html + [
        "</div>",
        "</body>",
        "</html>",
    ]
    return "\n".join(html)


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return int(f) if f == int(f) else round(f, 2)


# ── 字段名 → identity 键 ───────────────────────────────────────────────────

_FIELD_KEYS = {
    "电话": "phone", "手机": "phone", "联系电话": "phone", "移动电话": "phone",
    "邮箱": "email", "邮件": "email", "电子邮箱": "email", "email": "email",
    "微信": "link", "wechat": "link", "weixin": "link",
    "学校": "school", "毕业院校": "school", "院校": "school",
    "专业": "major", "所学专业": "major",
    "城市": "location", "所在城市": "location", "地点": "location",
    "籍贯": "location", "意向城市": "location",
    "性别": "gender", "年龄": "age", "生日": "age", "出生年月": "age",
    "求职意向": "headline", "意向岗位": "headline", "期望职位": "headline",
    "期望薪资": "salary", "薪资": "salary",
    "学历": "education", "最高学历": "education",
    "政治面貌": "political", "婚姻状况": "marital",
    "身份": "identity_label", "求职类型": "job_type",
    "当前状态": "status", "当前状愿": "status",
}


def _field_key(label):
    """「电话」→ `phone`。认不出来就返回空（不渲染）。"""
    key = (label or "").strip()
    if not key:
        return ""
    if key in _FIELD_KEYS:
        return _FIELD_KEYS[key]
    # 「求职意向」这类有值但没在 identity 里 → 退回 headline
    for k, v in _FIELD_KEYS.items():
        if k in key:
            return v
    return ""
