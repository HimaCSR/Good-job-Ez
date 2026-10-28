"""用户上传的模板 → 转换成可渲染的 HTML 模板。

## 为什么要有这个

内置 4 套模板（classic/modern/tech/acad）是给不了的 ——
用户有自己的 Word 版式，想要「生成出来的简历长这样」。

## 转换的三条路

| 输入 | 做法 | 精度 |
| --- | --- | --- |
| `.docx` | zipfile + XML 抽**版式参数**（页边距/字号/栏数/字体/标题样式）→ 生成 CSS | 最高 |
| `.pdf` | 抽页面尺寸 + 文本位置（尽力而为）→ 生成还原样式 | 中 |
| 图片 | **底图 + 文字层**：图当背景，文字浮在上面 | 低但可用 |

**全部在本机完成，不调大模型** —— 简历内容不外传。

## 关键约束

**转换出来的是「同一份骨架 + 自己的 CSS」**，
不是一份独立的 HTML —— 这样：
- 缩略图 = 实际输出（同一套渲染器）
- 生成简历时不必区分来源

`resume_template.render_html()` 已经支持这个形态：
模板文件里带 `{{ ... }}` 占位，渲染时用同一份 context。

## 零额外依赖

环境里没有 python-docx、没有 PDF 库 —— 所以：
- `.docx` 用标准库 `zipfile` + `xml.etree`（docx 就是 zip + XML）
- `.pdf` 用正则抽文本流（`Tj` / `TJ` 操作符）
- 图片用 PIL 拿尺寸

**不新增依赖**是这个项目的硬规矩（见 CONTRIBUTING）。
"""

import io
import os
import re
import zipfile

# ── 版式参数的默认值 ────────────────────────────────────────────────────────
# 抽不到某个参数就用这个兜底 —— 宁可保守，也不要生成一版没法看的。

DEFAULTS = {
    "page_width_mm": 210,     # A4
    "page_height_mm": 297,
    "margin_top_mm": 14,
    "margin_bottom_mm": 14,
    "margin_left_mm": 16,
    "margin_right_mm": 16,
    "font_family": '"Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif',
    "font_size_pt": 10.5,
    "name_size_pt": 20,
    "line_height": 1.5,
    "title_color": "#1a1a1a",
    "accent_color": "#2f6fd0",
    "columns": 1,
    "column_gap_px": 20,
}

# 一英寸 = 25.4mm；twip（1/20 磅）= 1/1440 英寸
_MM_PER_TWIP = 25.4 / 1440.0
_PT_PER_HALF_POINT = 0.5


def _twip_to_mm(twip):
    try:
        return round(int(twip) * _MM_PER_TWIP, 1)
    except (TypeError, ValueError):
        return None


def _half_point_to_pt(hp):
    try:
        return round(int(hp) * _PT_PER_HALF_POINT, 1)
    except (TypeError, ValueError):
        return None


def _pt_to_px(pt):
    """pt → px（1pt = 4/3 px，CSS 里 96dpi）。

    **整数值不要小数尾巴** —— `14px` 比 `14.0px` 干净。
    """
    try:
        v = round(float(pt) * 4 / 3, 1)
    except (TypeError, ValueError):
        return None
    if v == int(v):
        return int(v)
    return v


def _num(v):
    """数值 → CSS 里好看的写法（整数值不带小数尾巴）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    if f == int(f):
        return int(f)
    return round(f, 2)


def _esc_css(value):
    """把字符串安全地放进 CSS 值里。"""
    if value is None:
        return ""
    s = str(value).strip()
    # 只允许常规字符 —— 防止注入 CSS
    if not re.match(r"^[A-Za-z0-9\u4e00-\u9fff ,.\-_#()\"'/]+$", s):
        return ""
    return s.replace("\\", "").replace(";", "").replace("{", "").replace("}", "")


# ── .docx ───────────────────────────────────────────────────────────────────

def _docx_styles(data):
    """从 .docx 抽版式参数。

    .docx 是 zip：
      word/document.xml  正文
      word/styles.xml    样式定义（字号/字体/颜色）
      word/sectPr        页面设置（在 document.xml 末尾）

    **全部用标准库** —— 环境里没有 python-docx。
    """
    out = dict(DEFAULTS)
    out["_extracted"] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            doc = z.read("word/document.xml").decode("utf-8", errors="replace") \
                if "word/document.xml" in names else ""
            styles = z.read("word/styles.xml").decode("utf-8", errors="replace") \
                if "word/styles.xml" in names else ""
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        raise ValueError("读不了这个 .docx（可能不是真的 Word 文件）：%s" % e)

    # ① 页面设置 —— sectPr 里的 pgSz / pgMar
    m = re.search(r"<w:pgSz\b[^>]*>", doc)
    if m:
        w = re.search(r'w:w="(\d+)"', m.group(0))
        h = re.search(r'w:h="(\d+)"', m.group(0))
        if w and h:
            out["page_width_mm"] = _twip_to_mm(w.group(1)) or out["page_width_mm"]
            out["page_height_mm"] = _twip_to_mm(h.group(1)) or out["page_height_mm"]
            out["_extracted"].append("纸张尺寸")
    m = re.search(r"<w:pgMar\b[^>]*>", doc)
    if m:
        for key, attr in (("margin_top_mm", "top"), ("margin_bottom_mm", "bottom"),
                          ("margin_left_mm", "left"), ("margin_right_mm", "right")):
            mm = re.search(r'w:%s="(-?\d+)"' % attr, m.group(0))
            if mm:
                v = _twip_to_mm(mm.group(1))
                if v is not None and v >= 0:
                    out[key] = v
        if m:
            out["_extracted"].append("页边距")

    # ② 正文默认字号 —— docDefaults 里的 sz
    m = re.search(r"<w:docDefaults>.*?</w:docDefaults>", styles, re.S)
    if m:
        sz = re.search(r'<w:sz w:val="(\d+)"', m.group(0))
        if sz:
            pt = _half_point_to_pt(sz.group(1))
            if pt and 6 <= pt <= 24:
                out["font_size_pt"] = pt
                out["_extracted"].append("正文字号")

    # ③ 正文里出现最多的字号 —— 比 docDefaults 更贴近实际
    sizes = []
    for m in re.finditer(r'<w:sz w:val="(\d+)"', doc):
        pt = _half_point_to_pt(m.group(1))
        if pt and 6 <= pt <= 24:
            sizes.append(pt)
    if sizes:
        common = max(set(sizes), key=sizes.count)
        if common != out["font_size_pt"]:
            out["font_size_pt"] = common
            out["_extracted"].append("正文字号（按出现频率）")

    # ④ 字体 —— rFonts 里 ascii/hAnsi 出现最多的
    fonts = []
    for m in re.finditer(r'<w:rFonts\b[^>]*>', doc):
        f = re.search(r'w:(?:ascii|hAnsi|eastAsia)="([^"]+)"', m.group(0))
        if f:
            fonts.append(f.group(1))
    if fonts:
        common = max(set(fonts), key=fonts.count)
        safe = _esc_css(common)
        if safe:
            out["font_family"] = '"%s", "Microsoft YaHei", "PingFang SC", sans-serif' % safe
            out["_extracted"].append("字体")

    # ⑤ 栏数 —— sectPr 里的 cols
    m = re.search(r"<w:cols\b[^>]*>", doc)
    if m:
        num = re.search(r'w:num="(\d+)"', m.group(0))
        if num and int(num.group(1)) in (1, 2, 3):
            out["columns"] = int(num.group(1))
            out["_extracted"].append("分栏")

    # ⑥ 标题颜色 —— 出现最多的非自动颜色
    colors = []
    for m in re.finditer(r'<w:color w:val="([0-9A-Fa-f]{6})"', doc):
        c = m.group(1).lower()
        if c in ("000000", "auto"):
            continue
        colors.append("#" + c)
    if colors:
        out["accent_color"] = max(set(colors), key=colors.count)
        out["_extracted"].append("强调色")

    # ⑦ 名字字号 —— 第一个 run 的 sz（简历里名字最大）
    first = re.search(r"<w:body>.*?</w:p>", doc, re.S)
    if first:
        sz = re.search(r'<w:sz w:val="(\d+)"', first.group(0))
        if sz:
            pt = _half_point_to_pt(sz.group(1))
            if pt and 12 <= pt <= 40:
                out["name_size_pt"] = pt
                out["_extracted"].append("姓名字号")

    return out


def _docx_to_css(params):
    """把版式参数变成 CSS 片段。"""
    p = params
    cols = int(p.get("columns") or 1)
    lines = []
    lines.append("/* 从 .docx 抽取的版式 */")
    lines.append("body { font-family: %s; font-size: %spx; line-height: %s; }"
                 % (p["font_family"], _pt_to_px(p["font_size_pt"]), p["line_height"]))
    lines.append("@page { size: %smm %smm; margin: %smm %smm %smm %smm; }"
                 % (_num(p["page_width_mm"]), _num(p["page_height_mm"]),
                    _num(p["margin_top_mm"]), _num(p["margin_right_mm"]),
                    _num(p["margin_bottom_mm"]), _num(p["margin_left_mm"])))
    lines.append(".page { width: %smm; min-height: %smm; }"
                 % (_num(p["page_width_mm"] - p["margin_left_mm"] - p["margin_right_mm"]),
                    _num(p["page_height_mm"] - p["margin_top_mm"] - p["margin_bottom_mm"])))
    if cols > 1:
        # **用 CSS columns（分栏流），不用 flex** ——
        # flex 是「并排」，Word 的分栏是「内容流到第二栏」。
        # flex 会把 .head 和每个 .sec 都并排，版式直接乱。
        lines.append(".content { column-count: %d; column-gap: %dpx; }" % (cols, p["column_gap_px"]))
        lines.append(".head { break-inside: avoid; }")
        lines.append(".sec { break-inside: avoid; }")
        lines.append(".sec-title { border: none; color: %s; }" % p["accent_color"])
        lines.append(".name { color: %s; }" % p["accent_color"])
    lines.append(".name { font-size: %spx; }" % _pt_to_px(p["name_size_pt"]))
    # 抬头一行放不下时整块换行 —— 不能把「杭州」拆成「杭」「州」
    lines.append(".contact { display: flex; flex-wrap: wrap; gap: 2px 12px; }")
    lines.append(".contact span { white-space: nowrap; margin-right: 0; }")
    lines.append(".item-title { color: %s; }" % p["title_color"])
    return "\n".join(lines) + "\n"


# ── .pdf ────────────────────────────────────────────────────────────────────

def _pdf_page_size(data):
    """从 PDF 抽页面尺寸（点，1pt = 1/72 英寸）。

    MediaBox 形如 `[0 0 595.28 841.89]`。
    """
    try:
        raw = data.decode("latin-1", errors="replace")
    except Exception:      # noqa: BLE001
        return None
    m = re.search(r"/MediaBox\s*\[\s*([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s*\]", raw)
    if not m:
        return None
    try:
        w = float(m.group(3)) - float(m.group(1))
        h = float(m.group(4)) - float(m.group(2))
    except ValueError:
        return None
    if w < 50 or h < 50:
        return None
    # pt → mm
    return (round(w * 25.4 / 72, 1), round(h * 25.4 / 72, 1))


def _pdf_to_css(data):
    """PDF → CSS（尽力而为）。

    PDF 里没有「样式表」这回事，只有坐标指令。
    我们只能拿到页面尺寸 + 文本是否存在 ——
    **抽不出文字的 PDF（扫描件）会如实告诉用户**，不瞎填。
    """
    p = dict(DEFAULTS)
    p["_extracted"] = []
    size = _pdf_page_size(data)
    if size:
        p["page_width_mm"], p["page_height_mm"] = size
        p["_extracted"].append("页面尺寸")

    text, note = _pdf_text(data)
    if not text.strip():
        p["_note"] = note or ("这个 PDF 里没抽出文字（可能是扫描件）。"
                              "版式按 A4 近似还原。")
    else:
        p["_extracted"].append("文本内容")

    lines = [
        "/* 从 PDF 抽取的版式（PDF 没有样式表，只能还原到这个程度） */",
        "body { font-family: %s; font-size: %spx; line-height: %s; }"
        % (p["font_family"], _pt_to_px(p["font_size_pt"]), p["line_height"]),
        "@page { size: %smm %smm; margin: %smm %smm %smm %smm; }"
        % (_num(p["page_width_mm"]), _num(p["page_height_mm"]),
           _num(p["margin_top_mm"]), _num(p["margin_right_mm"]),
           _num(p["margin_bottom_mm"]), _num(p["margin_left_mm"])),
        ".page { width: %smm; min-height: %smm; }"
        % (_num(p["page_width_mm"] - p["margin_left_mm"] - p["margin_right_mm"]),
           _num(p["page_height_mm"] - p["margin_top_mm"] - p["margin_bottom_mm"])),
    ]
    return "\n".join(lines) + "\n", p


def _pdf_text(data):
    """从 PDF 抽文本（跟 resume_import 同一套思路）。"""
    try:
        raw = data.decode("latin-1", errors="replace")
    except Exception:      # noqa: BLE001
        return "", "PDF 读取失败"
    chunks = []
    for m in re.finditer(r"\(((?:[^()\\]|\\.)*)\)\s*Tj", raw):
        chunks.append(_pdf_unescape(m.group(1)))
    for m in re.finditer(r"\[((?:[^\[\]\\]|\\.)*)\]\s*TJ", raw):
        parts = re.findall(r"\(((?:[^()\\]|\\.)*)\)", m.group(1))
        if parts:
            chunks.append("".join(_pdf_unescape(x) for x in parts))
    text = "\n".join(c for c in chunks if c.strip())
    note = ""
    if not text.strip():
        note = ("这个 PDF 没抽出文字（可能是扫描件或字体是图片嵌入）。"
                "版式按 A4 近似还原。")
    return text, note


def _pdf_unescape(s):
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            mapping = {"n": "\n", "r": "\r", "t": "\t", "b": "\b",
                       "f": "\f", "(": "(", ")": ")", "\\": "\\"}
            if nxt in mapping:
                out.append(mapping[nxt])
                i += 2
                continue
            if nxt.isdigit():
                m = re.match(r"[0-7]{1,3}", s[i + 1:])
                if m:
                    out.append(chr(int(m.group(0), 8)))
                    i += 1 + len(m.group(0))
                    continue
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


# ── 图片 ────────────────────────────────────────────────────────────────────

def _image_to_css(data, ext):
    """图片 → 「底图 + 文字层」。

    图片本身当背景，文字浮在上面（绝对定位在页面上）。
    **这是视觉还原，不是结构还原** —— 文字层的位置是估算的。
    """
    p = dict(DEFAULTS)
    p["_extracted"] = []
    width_px = height_px = None
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        width_px, height_px = img.size
        p["_extracted"].append("图片尺寸")
    except Exception:      # noqa: BLE001
        # 没有 PIL 也能做 —— 只是拿不到尺寸
        pass

    if width_px and height_px:
        # 图片比例 → A4 宽度下的高度
        ratio = height_px / float(width_px)
        p["page_height_mm"] = round(p["page_width_mm"] * ratio, 1)
        p["_extracted"].append("按图片比例还原页面高度")
    else:
        p["_note"] = ("读不出图片尺寸（可能没装 Pillow）。"
                      "按 A4 还原，图片铺满整页。")

    lines = [
        "/* 从图片还原：底图 + 文字层 */",
        "@page { size: %smm %smm; margin: 0; }"
        % (_num(p["page_width_mm"]), _num(p["page_height_mm"])),
        ".page { position: relative; width: %smm; min-height: %smm; padding: 0; }"
        % (_num(p["page_width_mm"]), _num(p["page_height_mm"])),
        ".bg-image {",
        "  position: absolute; inset: 0; width: 100%; height: 100%;",
        "  background-repeat: no-repeat; background-size: 100% 100%;",
        "  z-index: 0;",
        "}",
        ".content { position: relative; z-index: 1; }",
        "body { font-family: %s; font-size: %spx; line-height: %s; }"
        % (p["font_family"], _pt_to_px(p["font_size_pt"]), p["line_height"]),
    ]
    return "\n".join(lines) + "\n", p


# ── 统一入口 ────────────────────────────────────────────────────────────────

SUPPORTED = ("docx", "pdf", "png", "jpg", "jpeg", "webp")


def convert(filename, data, kind=None):
    """把上传的文件转成模板。

    返回：
      {"ok": True, "template": {...}, "css": "...", "params": {...}}
      {"ok": False, "error": "..."}
    """
    name = os.path.basename(filename or "template.docx")
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    if kind:
        ext = str(kind).lower().lstrip(".")
    if ext not in SUPPORTED:
        return {"ok": False,
                "error": "只支持 .docx / .pdf / .png / .jpg / .webp（收到 .%s）" % ext}

    if not data:
        return {"ok": False, "error": "文件内容是空的"}

    try:
        if ext == "docx":
            params = _docx_styles(data)
            css = _docx_to_css(params)
        elif ext == "pdf":
            css, params = _pdf_to_css(data)
        else:
            css, params = _image_to_css(data, ext)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:      # noqa: BLE001
        return {"ok": False, "error": "转换失败：%s" % e}

    params["_extracted"] = list(params.get("_extracted") or [])
    return {
        "ok": True,
        "css": css,
        "params": params,
        "note": params.get("_note", ""),
        "extracted": params["_extracted"],
    }
