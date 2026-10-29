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
- 图片尺寸用**标准库读文件头**（PNG/JPEG/GIF/WebP），不依赖 PIL

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

# ── PDF 图形层：CTM / 透明度 / 版面结构 ─────────────────────────────────────
#
# **为什么要有这一层**
#
# 用户：「现在有样式了，但与我提供的模板文件完全不同。」
#
# 只抽颜色是不够的 —— WPS 简历模板的骨架长这样：
#
#   ┌──────────────────────────────┐
#   │  ▓▓▓▓ 深蓝页眉底 ▓▓▓▓       │  ← 页眉整块是背景色，文字是白的
#   │  ▓ 姓名   联系方式    (照片) ▓│
#   │  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │
#   │  ▪ 个人简介                  │  ← 章节 = 淡色底条 + 左侧实心方块
#   │  ▪ 经历……                   │
#   └──────────────────────────────┘
#
# 这些「色块在哪、有多大、什么颜色」全在**绘图指令**里，
# 不解析就只剩颜色 → 排版完全对不上。

def _mat_mul(m1, m2):
    """两个 2D 仿射矩阵相乘（PDF 的 `cm` 是「后乘」）。"""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + b1 * c2,
            a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2,
            c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2,
            e1 * b2 + f1 * d2 + f2)


def _mat_apply(m, x, y):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def _pdf_alpha_map(data):
    """`/G<n>` → 填充透明度（ca）。

    PDF 里颜色可以是**半透明**的 —— WPS 模板的章节底条就是
    「强调色 + 10% 透明度」画出来的，屏幕上看着是淡紫，
    但 PDF 里存的是「深蓝 + alpha 0.1」。

    **不读 alpha 就直接用颜色** → 章节底条变成深蓝 → 白字蓝底，
    跟原设计完全不是一回事（本机踩过）。

    `ca` 是填充透明度，`CA` 是描边的 —— 这里只用 `ca`。
    """
    ca = {}
    for m in re.finditer(rb"(\d+)\s+0\s+obj\s*<<[^<>]*?/ca\s+([\d.]+)", data):
        ca[int(m.group(1))] = float(m.group(2))
    out = {}
    for m in re.finditer(rb"/G(\d+)\s+(\d+)\s+0\s+R", data):
        out[int(m.group(1))] = ca.get(int(m.group(2)), 1.0)
    return out


def _pdf_objects(data):
    """PDF 对象表：obj 号 → (字典字节, 流字节或 None)。

    **为什么要解析对象** —— 页眉那块大色块常常画在
    **Form XObject** 里（内容单独放一个对象，页面上用 `Do` 引用）。
    不解析对象就看不到它。
    """
    objs = {}
    for m in re.finditer(rb"(?<![0-9])(\d+)\s+0\s+obj", data):
        num = int(m.group(1))
        end = data.find(b"endobj", m.end())
        if end < 0:
            continue
        body = data[m.end():end]
        sm = re.search(rb"stream\r?\n", body)
        if sm:
            dict_bytes = body[:sm.start()]
            se = body.find(b"endstream", sm.end())
            stream = body[sm.end():se] if se > 0 else b""
        else:
            dict_bytes = body
            stream = None
        objs[num] = (dict_bytes, stream)
    return objs


def _stream_text(dict_bytes, stream):
    """对象里的流 → 文本（能解压就解压；是明文就直接读）。"""
    if not stream:
        return ""
    if b"/FlateDecode" in dict_bytes:
        import zlib
        try:
            return zlib.decompress(stream).decode("latin-1", errors="replace")
        except Exception:
            return ""
    # 明文流 —— 一半以上是可打印字符才算
    try:
        txt = stream.decode("latin-1")
    except Exception:
        return ""
    printable = sum(1 for ch in txt[:400] if ch.isprintable() or ch in "\r\n\t")
    if txt and printable / float(len(txt[:400])) > 0.85:
        return txt
    return ""


def _pdf_forms(data, objs):
    """Form XObject：资源名 → 内容文本。

    **只认 `/Subtype /Form`** —— 图片（`/Subtype /Image`）不是版面。
    """
    forms = {}
    for m in re.finditer(rb"/(\w+)\s+(\d+)\s+0\s+R", data):
        name = m.group(1).decode("latin-1")
        num = int(m.group(2))
        if name in forms or num not in objs:
            continue
        d, s = objs[num]
        if b"/Form" not in d or s is None:
            continue
        txt = _stream_text(d, s)
        if txt:
            forms[name] = txt
    return forms


# 内容流里的绘图操作（顺序扫一遍）
_OP_RE = re.compile(
    r"(?P<q>\bq\b)"
    r"|(?P<Q>\bQ\b)"
    r"|(?P<cm>(?P<ma>[-\d.]+)\s+(?P<mb>[-\d.]+)\s+(?P<mc>[-\d.]+)\s+"
    r"(?P<md>[-\d.]+)\s+(?P<me>[-\d.]+)\s+(?P<mf>[-\d.]+)\s+cm)"
    r"|(?P<rg>(?P<cr>[-\d.]+)\s+(?P<cg>[-\d.]+)\s+(?P<cb2>[-\d.]+)\s+rg)"
    r"|(?P<gs>/G(?P<gsn>\d+)\s+gs)"
    r"|(?P<re>(?P<rx>[-\d.]+)\s+(?P<ry>[-\d.]+)\s+(?P<rw>[-\d.]+)\s+"
    r"(?P<rh>[-\d.]+)\s+re)"
    r"|(?P<do>/(?P<don>\w+)\s+Do)")


def _pdf_rects(content, alphas, forms=None, ctm=None, depth=0):
    """遍历内容流，返回**真正画出来**的矩形（PDF 用户坐标，y 向上）。

    返回 [(x0, y0, x1, y1, (r,g,b), alpha)]。

    ## 三个必须注意的点

    **① 跟踪 CTM** —— `q`/`Q`/`cm` 决定当前变换。
    不跟踪的话，套在 XObject 里的形状坐标是「对象空间」，
    跟页面上的位置对不上 → 什么都分类不了。

    **② 区分「填充」和「裁剪」** —— `re` 后面跟什么决定它画没画：
    - `f` / `f*` → 真的画了（填充）
    - `W` / `W*` → 裁剪路径（**没画**）
    - `n` → 不画

    把裁剪路径当色块 → 页眉底色 = 强调色 → 白字蓝底 → 字看不见。
    本机踩过这个。

    **③ `Do` 要递归进 Form** —— 页眉底块就在里面。
    """
    forms = forms or {}
    cur = ctm or (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    stack = []
    color = (0.0, 0.0, 0.0)
    alpha = 1.0
    out = []
    for m in _OP_RE.finditer(content):
        if m.group("q"):
            stack.append(cur)
        elif m.group("Q"):
            if stack:
                cur = stack.pop()
        elif m.group("cm"):
            cur = _mat_mul(
                (float(m.group("ma")), float(m.group("mb")),
                 float(m.group("mc")), float(m.group("md")),
                 float(m.group("me")), float(m.group("mf"))), cur)
        elif m.group("rg"):
            color = (float(m.group("cr")), float(m.group("cg")),
                     float(m.group("cb2")))
        elif m.group("gs"):
            alpha = alphas.get(int(m.group("gsn")), 1.0)
        elif m.group("do"):
            if depth < 3:
                sub = forms.get(m.group("don"))
                if sub:
                    out.extend(_pdf_rects(sub, alphas, forms, cur, depth + 1))
        else:  # re
            tail = content[m.end():m.end() + 16]
            if not re.match(r"\s*(f\*|f)\b", tail):
                continue          # 裁剪路径 / 只结束路径 → 没画
            x = float(m.group("rx"))
            y = float(m.group("ry"))
            w = float(m.group("rw"))
            h = float(m.group("rh"))
            p0 = _mat_apply(cur, x, y)
            p1 = _mat_apply(cur, x + w, y + h)
            out.append((min(p0[0], p1[0]), min(p0[1], p1[1]),
                        max(p0[0], p1[0]), max(p0[1], p1[1]),
                        color, alpha))
    return out


def _blend_white(rgb, alpha):
    """半透明颜色叠在白底上的实际观感。

    WPS 的章节底条 = 强调色 alpha 0.1 画在白底上 →
    屏幕上看到的是**淡紫**，不是深蓝。
    """
    a = max(0.0, min(1.0, float(alpha)))
    return tuple(a * c + (1.0 - a) * 1.0 for c in rgb)


def _hex(rgb):
    return "#%02x%02x%02x" % (int(max(0.0, min(1.0, rgb[0])) * 255),
                               int(max(0.0, min(1.0, rgb[1])) * 255),
                               int(max(0.0, min(1.0, rgb[2])) * 255))

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


# PDF 的 PostScript 字体名 → CSS font-family
#
# **不能靠「驼峰拆词」** —— `MicrosoftYaHei` 拆出来是
# `Microsoft Ya Hei`（多了个空格，**认不出来**）。
#
# 常见中文字体的正确写法在表里；表里没有就**保持原样**
# （浏览器认不出来也比写错强 —— 写错会落到别的字体上）。
_PDF_FONT_NAMES = {
    "MicrosoftYaHei": "Microsoft YaHei",
    "MicrosoftYaHeiUI": "Microsoft YaHei UI",
    "SimSun": "SimSun",
    "SimHei": "SimHei",
    "KaiTi": "KaiTi",
    "FangSong": "FangSong",
    "DengXian": "DengXian",
    "SourceHanSansSC": "Source Han Sans SC",
    "SourceHanSerifSC": "Source Han Serif SC",
    "NotoSansCJKSC": "Noto Sans CJK SC",
    "ArialUnicodeMS": "Arial Unicode MS",
    "TimesNewRoman": "Times New Roman",
    "ArialMT": "Arial",
    "ArialBoldMT": "Arial",
    "Calibri": "Calibri",
    "Helvetica": "Helvetica",
}


def _pdf_font_to_css(name):
    """PDF 的 PostScript 字体名 → CSS font-family 用的名字。"""
    if not name:
        return ""
    if name in _PDF_FONT_NAMES:
        return _PDF_FONT_NAMES[name]
    # **带连字符/空格的**（已经是 CSS 写法）直接用
    if "-" in name or " " in name:
        return name
    # 认不出来 → 保持原样（CSS 里加引号不会更糟）
    if re.match(r"^[A-Za-z][A-Za-z0-9]*$", name) and len(name) >= 3:
        return name
    return ""


def _pdf_streams(data):
    """解压 PDF 里所有能解的流（FlateDecode）。

    **内容流是压缩的** —— 直接在原始字节上找 `rg`/`Tf`/`Tj` **找不到**。
    本机踩过：正则扫原始字节 → 一个 `rg` 都没有 → 以为 PDF 没样式。

    → 先解压，再抽。

    返回 (内容流文本列表, 原始二进制流列表)。
    """
    import zlib
    texts, raws = [], []
    for m in re.finditer(rb"stream\r?\n", data):
        start = m.end()
        end = data.find(b"endstream", start)
        if end < 0:
            continue
        blob = data[start:end]
        try:
            texts.append(zlib.decompress(blob).decode("latin-1", errors="replace"))
        except Exception:
            raws.append(blob)
    return texts, raws


def _pdf_style(data):
    """从 PDF 内容流抽**视觉风格**（配色 / 字号 / 字体）。

    ## 抽得到什么

    PDF 里没有「样式表」，但绘图指令里有：

    | 指令 | 含义 |
    | --- | --- |
    | `r g b rg` | 填充色 |
    | `r g b RG` | 描边色 |
    | `/F4 34 Tf` | 字号（`Tf` 的第二个参数） |
    | `/BaseFont /XXX` | 字体名 |

    → **强调色** = 出现最多、且**不是灰度**的颜色
    （灰度 = r==g==b，那是正文色不是强调色）。

    ## 抽不到什么

    **布局**（谁在哪、什么字号对应什么层级）——
    PDF 只给坐标，不给语义层级。
    所以字号只能**按大小映射**到「标题 / 姓名 / 正文」——
    这是**近似**，不是精确还原。
    """
    texts, _raws = _pdf_streams(data)
    if not texts:
        return {}

    # 找内容流 —— **要含字体指令（`Tf`）的那条**。
    #
    # **不能取最大的流** —— 最大的往往是**内嵌字体文件**
    # （几百 KB 的 TTF 二进制），里面一个 `Tf` 都没有。
    # 本机踩过：取最大流 → 字号一个都抽不到。
    content = ""
    for t in texts:
        if re.search(r"/\S+\s+[\d.]+\s+Tf", t):
            content = t
            break
    if not content:
        for t in texts:
            if re.search(r"\bre\b|\bTm\b|\bBT\b", t):
                content = t
                break
    if not content:
        content = max(texts, key=len)

    out = {}

    # ── 配色 ──
    from collections import Counter
    fills = Counter(re.findall(
        r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg", content))
    strokes = Counter(re.findall(
        r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+RG", content))
    colors = fills or strokes
    if colors:
        accent = None
        for (r, g, b), n in colors.most_common():
            try:
                rv, gv, bv = float(r), float(g), float(b)
            except ValueError:
                continue
            # **灰度**（r≈g≈b）不算强调色
            if abs(rv - gv) < 0.02 and abs(gv - bv) < 0.02:
                continue
            if rv > 0.95 and gv > 0.95 and bv > 0.95:
                continue      # 纯白
            accent = "#%02x%02x%02x" % (int(rv * 255), int(gv * 255), int(bv * 255))
            break
        if accent:
            out["accent_color"] = accent

        # **正文色** = 用得最多的灰度色（偏深的那个）
        for (r, g, b), n in colors.most_common():
            try:
                rv = float(r)
            except ValueError:
                continue
            if abs(float(r) - float(g)) < 0.02 and abs(float(g) - float(b)) < 0.02:
                if 0.05 <= rv <= 0.75:
                    out["title_color"] = "#%02x%02x%02x" % (
                        int(rv * 255), int(rv * 255), int(rv * 255))
                    break

    # ── 几何（竖条 / 分隔线 / 横条） ──
    #
    # PDF 里没有「样式表」，但**形状是画出来的**：
    # - **竖条**（高 >> 宽）→ 侧边色带 / 标题左侧色块
    # - **细横线**（宽 >> 高，高度只有 1~3）→ 章节分隔线
    # - **粗横条**（宽 >> 高，高度几十以上）→ 章节标题栏底色
    geo = _pdf_geometry(content)
    out.update(geo)

    # ── 字号 ──
    sizes = []
    for m in re.finditer(r"/\S+\s+([\d.]+)\s+Tf", content):
        try:
            sizes.append(float(m.group(1)))
        except ValueError:
            continue
    if sizes:
        uniq = sorted(set(sizes))
        out["_font_sizes"] = uniq
        out["name_size_pt"] = max(uniq)
        # **正文字号 = 出现最多的那个** ——
        #
        # 不要用中位数：设计稿里大标题只有 1 处，
        # 正文出现几十次 → **众数才是正文**。
        # 用中位数会把正文算大一号（实测 24px → 简历正文巨大）。
        out["font_size_pt"] = Counter(sizes).most_common(1)[0][0]

    # ── 字体名 ──
    #
    # **BaseFont 在 PDF 的「对象定义」部分**（`/BaseFont /AAAAAA+MicrosoftYaHei`），
    # **不在压缩流里** —— 只在解压结果里找是找不到的。
    # 本机踩过：查了 15 个流一个都没有 → 字体名抽不到。
    raw = data.decode("latin-1", errors="replace")
    m = re.search(r"/BaseFont\s*/([A-Za-z0-9+\-_]+)", raw)
    if not m:
        for t in texts:
            m = re.search(r"/BaseFont\s*/([A-Za-z0-9+\-_]+)", t)
            if m:
                break
    if m:
        name = m.group(1)
        # **去掉子集前缀**（`AAAAAA+MicrosoftYaHei` → `MicrosoftYaHei`）
        name = name.split("+")[-1]
        if name:
            out["_pdf_font_name"] = name

    return out


def _color_close(a, b, tol=40):
    """两个十六进制颜色接不接近（按 RGB 距离）。"""
    try:
        ar, ag, ab = (int(a[i:i + 2], 16) for i in (1, 3, 5))
        br, bg, bb = (int(b[i:i + 2], 16) for i in (1, 3, 5))
    except (ValueError, IndexError):
        return False
    return abs(ar - br) <= tol and abs(ag - bg) <= tol and abs(ab - bb) <= tol


def _pdf_geometry(content):
    """从 PDF 内容流抽**几何特征**（竖条 / 分隔线 / 横条）。

    ## 为什么要抽

    PDF 是**画出来的** —— 配色、字号、分隔线、色带全在绘图指令里。
    之前只抽尺寸 → 用户看到的模板「跟原文件不像」。

    ## 三种形状

    | 形状 | 判据 | 对应什么 |
    | --- | --- | --- |
    | 竖条 | 高 > 宽 × 20 | 侧边色带 / 标题左侧色块 |
    | 细横线 | 宽 > 高 × 100 且高 ≤ 4 | 章节分隔线 |
    | 粗横条 | 宽 > 高 × 5 且高 > 20 | 章节标题栏底色 |

    **颜色**取「填这个形状的那个 `rg`」—— 紧挨在 `re` 前面的那个。
    """
    out = {}

    # **颜色 + 矩形配对** ——
    #
    # **不能靠「rg 后面紧跟 re」的正则** ——
    # 真实 PDF 里中间隔着路径指令（`q` / `Q` / `n` / `W*`）：
    #
    #     .2235 .251 .5176 rg
    #     q
    #     153.125 1050 2262.5 100 re
    #     W* n
    #
    # → 改成**按位置配对**：先找出所有 `rg` 的位置和值，
    # 再对每个 `re` 取**它前面最近的、还没被用过的 `rg`**。
    colors = [(m.start(), m.group(1), m.group(2), m.group(3))
              for m in re.finditer(
                  r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg", content)]
    # **矩形 + 它后面的绘制方式** ——
    #
    # `re` 后面跟什么决定了这个形状是**填充**还是**裁剪**：
    # - `f` / `f*` → **真的画出来了**（填充）
    # - `W` / `W*` → **裁剪路径**（不画）
    # - `n` → 不画（只结束路径）
    #
    # **不区分就会把「裁剪路径」当成色块** ——
    # 本机踩过：把强调色 #384083 当成标题栏底色 → 白字蓝底 → 字看不见。
    rects = []
    for m in re.finditer(
            r"([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+re", content):
        tail = content[m.end():m.end() + 12]
        if re.match(r"\s*W", tail):
            continue          # 裁剪路径 —— 不画
        if re.match(r"\s*n\b", tail):
            continue          # 只结束路径 —— 不画
        rects.append((m.start(), m.group(1), m.group(2), m.group(3), m.group(4)))

    verticals = []
    hlines = []
    bands = []
    ci = 0
    for (pos, x, y, w, h) in rects:
        # 找**前面最近的** rg
        while ci < len(colors) and colors[ci][0] < pos:
            ci += 1
        if ci == 0:
            continue
        _, r, g, b = colors[ci - 1]
        try:
            rv, gv, bv = float(r), float(g), float(b)
            wf, hf = abs(float(w)), abs(float(h))
        except ValueError:
            continue
        if wf < 0.5 and hf < 0.5:
            continue
        color = "#%02x%02x%02x" % (int(rv * 255), int(gv * 255), int(bv * 255))
        # **纯白不算装饰**
        if rv > 0.97 and gv > 0.97 and bv > 0.97:
            continue
        if hf > wf * 20 and wf <= 40:
            verticals.append((wf, hf, color))
        elif wf > hf * 100 and hf <= 4:
            hlines.append((wf, hf, color))
        elif wf > hf * 5 and hf > 20:
            bands.append((wf, hf, color))

    # **竖条** —— 取最细的那根（最像「色带」）
    if verticals:
        verticals.sort(key=lambda v: v[0])
        w, h, color = verticals[0]
        out["_accent_bar_px"] = round(w * 0.75, 1)   # PDF 单位 → px 近似
        out["_accent_bar_color"] = color

    # **分隔线** —— 取最常见的高度和颜色
    if hlines:
        from collections import Counter
        hh = Counter(round(h) for _, h, _ in hlines)
        h = hh.most_common(1)[0][0]
        cols = Counter(c for _, hh2, c in hlines if round(hh2) == h)
        out["_divider_px"] = max(1, round(h * 0.75))
        out["_divider_color"] = cols.most_common(1)[0][0]

    # **标题栏底色** —— 取最宽的那条横条的**浅色**版本
    if bands:
        bands.sort(key=lambda b: -b[0])
        wf, hf, color = bands[0]
        # 底色通常是**淡**的（接近白）—— 强调色已经单独抽了
        out["_band_color"] = color

    return out


def _pdf_layout(rects, page_w, page_h):
    """把矩形分类成**版面结构**（页眉 / 竖带 / 章节条 / 图标块）。

    ## 判据

    | 结构 | 判据 |
    | --- | --- |
    | **页眉底块** | 宽 ≥ 内容宽 80%，**贴在页面顶部**，且不是白色 |
    | **侧边竖带** | 高 ≥ 页面高 50%，宽很窄（≤ 内容宽 8%） |
    | **章节底条** | 宽 ≥ 内容宽 40%，高在 10~120 之间，**不在页面顶部** |
    | **图标方块** | 宽高接近（0.7~1.4），且 ≤ 60 |
    | **分隔线** | 宽长、高 ≤ 4 |

    ## 为什么按「位置 + 尺寸」而不是「颜色」

    颜色会撞 —— 深蓝页眉和深蓝图标块颜色一样，
    靠颜色分不开。位置和尺寸才是「角色」。

    ## 白色要排除

    每页都有一大块白底 —— 当成「页眉」就完了。
    """
    out = {}
    if not rects:
        return out
    content_w = max((r[2] - r[0]) for r in rects) or 1.0
    top = max(r[3] for r in rects)          # 页面顶（y 向上）

    header = None
    sidebars = []
    bands = []
    icons = []
    lines = []

    for (x0, y0, x1, y1, rgb, al) in rects:
        w = x1 - x0
        h = y1 - y0
        eff = _blend_white(rgb, al)
        white = all(c > 0.97 for c in eff)
        # **分隔线** —— 又宽又扁
        if w > content_w * 0.2 and h <= 4:
            lines.append((w, h, eff, x0, y1))
            continue
        if white:
            continue
        # **侧边竖带** —— 贯穿大半页
        if h >= page_h * 0.45 and w <= content_w * 0.08 and w > 2:
            sidebars.append((w, h, eff, x0, y0, x1, y1))
            continue
        # **图标方块** —— 方方正正且小
        if 8 <= w <= 60 and 0.7 <= w / max(h, 1e-6) <= 1.4 and h <= 60:
            icons.append((w, h, eff, x0, y0))
            continue
        # **页眉底块** —— 顶部 + 宽
        if y1 >= top - max(12.0, page_h * 0.02) and w >= content_w * 0.75:
            if header is None or h > header[1]:
                header = (w, h, eff, x0, y0, x1, y1)
            continue
        # **章节底条** —— 够宽、**不在页面顶部**、高度适中
        #
        # 「不在顶部」很关键 —— 稻壳儿模板顶部有条 #f1f1f1 浅灰横条，
        # 那是**页眉的一部分**，不是章节底条。
        # 不排除 → 章节标题被涂成浅灰底 → 跟原设计完全不是一回事。
        if y1 >= top - max(12.0, page_h * 0.02):
            continue
        if w >= content_w * 0.35 and 8 <= h <= 140:
            bands.append((w, h, eff, x0, y0))
            continue
        if w >= content_w * 0.35 and h > 140:
            # 大块但不在顶部 —— 可能是侧栏卡片
            bands.append((w, h, eff, x0, y0))

    if header:
        w, h, eff, x0, y0, x1, y1 = header
        out["_header_bg"] = _hex(eff)
        out["_header_h_ratio"] = round(h / max(page_h, 1e-6), 3)
        out["_header_is_dark"] = 1 if sum(eff) / 3 < 0.62 else 0
    if sidebars:
        sidebars.sort(key=lambda v: -v[1])
        w, h, eff, x0, y0, x1, y1 = sidebars[0]
        out["_sidebar_color"] = _hex(eff)
        out["_sidebar_w_ratio"] = round(w / max(content_w, 1e-6), 4)
        # 竖带在左还是右 —— 相对内容区中心判断
        out["_sidebar_side"] = "left" if x0 < content_w / 2 else "right"
    if bands:
        bands.sort(key=lambda b: (b[1], -b[0]))
        # **章节底条** = 高度小、出现多次的那个
        from collections import Counter
        hs = Counter(round(b[1]) for b in bands)
        common_h = hs.most_common(1)[0][0]
        same = [b for b in bands if abs(b[1] - common_h) <= 2]
        if same:
            out["_band_color"] = _hex(same[0][2])
            out["_band_h_ratio"] = round(common_h / max(page_h, 1e-6), 4)
            out["_band_count"] = len(same)
    if icons:
        icons.sort(key=lambda v: -v[0] * v[1])
        out["_icon_color"] = _hex(icons[0][2])
        out["_icon_size"] = round(icons[0][0], 1)
        out["_icon_count"] = len(icons)
    if lines:
        lines.sort(key=lambda l: -l[0])
        out["_divider_px"] = max(1, round(lines[0][1]))
        out["_divider_color"] = _hex(lines[0][2])
    return out

def _pdf_layout_css(lay, page_h_mm):
    """版面结构 → CSS。

    ## 生成的样式

    | 结构 | CSS |
    | --- | --- |
    | 深色页眉底 | `.head` 整块铺强调色 + 文字反白 + 负外边距顶到纸边 |
    | 侧边竖带 | `.page` 左边框 |
    | 章节底条 | `.sec-title` 背景色 + 反白文字 |
    | 图标方块 | `.sec-title::before` 一个小方块 |
    | 分隔线 | `.sec-title` 下边框 |

    ## 为什么要「反白」

    深色底上的文字必须是浅色 —— 原设计就是「深蓝页眉 + 白字」。
    直接套强调色 → 深蓝底深蓝字 → **字看不见**（本机踩过）。
    """
    lines = []

    # ── 深色页眉底 ──
    hb = lay.get("_header_bg")
    if hb and lay.get("_header_is_dark"):
        # 页眉高度占比 → 换成大致 mm
        h_mm = max(28, round((lay.get("_header_h_ratio") or 0.13)
                             * page_h_mm, 1))
        lines.append(
            "/* 页眉底色 —— 原设计是一整块深色 */\n"
            ".head { background: %s; color: #ffffff; "
            "margin: -%smm -%smm 6mm; padding: %smm %smm %smm %smm; }\n"
            ".head .name { color: #ffffff; }\n"
            ".head .sub, .head .contact { color: rgba(255,255,255,.85); }"
            % (hb, _num(14), _num(16), _num(6), _num(6), _num(8), _num(8)))

    # ── 侧边竖带 ──
    sb = lay.get("_sidebar_color")
    if sb:
        w_ratio = lay.get("_sidebar_w_ratio") or 0.024
        w_mm = max(1.5, round(w_ratio * 178, 1))
        lines.append(
            "/* 侧边竖带 */\n"
            ".page { border-left: %smm solid %s; padding-left: 5mm; }"
            % (_num(w_mm), sb))

    # ── 章节底条 ──
    bc = lay.get("_band_color")
    if bc and (lay.get("_band_count") or 0) >= 2:
        # **底色是深还是浅，文字颜色要跟着反** ——
        # 淡紫底 (#eaebf2) + 白字 = **字看不见**。
        # 深底（现场管理的 #384083）才用白字。
        title_color = "#ffffff"
        try:
            r_, g_, b_ = (int(bc[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
            if (r_ + g_ + b_) / 3.0 > 0.62:
                title_color = lay.get("_icon_color") or "#333333"
        except (ValueError, IndexError):
            pass
        lines.append(
            "/* 章节标题栏底色 */\n"
            ".sec-title { background: %s; color: %s; "
            "padding: 4px 8px; }" % (bc, title_color))

    # ── 章节图标方块 ──
    ic = lay.get("_icon_color")
    if ic and (lay.get("_icon_count") or 0) >= 2:
        sz = lay.get("_icon_size") or 24
        # PDF 用户坐标 → mm（页面高 1740 ≈ 297mm → 约 0.17mm/单位）
        size_mm = max(3.0, round(sz * (page_h_mm / 1740.0), 1))
        lines.append(
            "/* 章节标题前的实心方块 */\n"
            ".sec-title { padding-left: %smm; position: relative; }\n"
            ".sec-title::before { content: ''; position: absolute; "
            "left: 0; top: 50%%; transform: translateY(-50%%); "
            "width: %smm; height: %smm; background: %s; }"
            % (_num(size_mm + 2), _num(size_mm), _num(size_mm), ic))

    # ── 分隔线 ──
    if lay.get("_divider_px") and not bc:
        lines.append(
            "/* 章节分隔线 */\n"
            ".sec-title { border-bottom: %spx solid %s; padding-bottom: 3px; }"
            % (_num(lay["_divider_px"]), lay.get("_divider_color") or "#cccccc"))
    return lines



def _pdf_to_css(data):
    """PDF → CSS（尽力而为，但**尽量把视觉风格抽出来**）。

    ## 之前的问题

    原来只抽**页面尺寸**，配色/字号/字体全丢 →
    用户看到的模板**跟原文件不像**（"UI 风格设计没有跟着转换过来"）。

    → 现在抽 **强调色 / 正文色 / 字号 / 字体名**（见 `_pdf_style`）。

    ## 仍然做不到的

    **精确的版式还原** —— PDF 只给坐标，不给语义层级。
    字号只能**按大小映射**到「姓名 / 正文 / 章节标题」——
    是**近似**，不是像素级还原。

    **抽不出文字的 PDF（扫描件）** 会如实告诉用户，不瞎填。
    """
    p = dict(DEFAULTS)
    p["_extracted"] = []
    size = _pdf_page_size(data)
    if size:
        p["page_width_mm"], p["page_height_mm"] = size
        p["_extracted"].append("页面尺寸")

    # **视觉风格** —— 配色 / 字号 / 字体
    style = _pdf_style(data)
    if style.get("accent_color"):
        p["accent_color"] = style["accent_color"]
        p["_extracted"].append("强调色")
    if style.get("title_color"):
        p["title_color"] = style["title_color"]
    if style.get("name_size_pt"):
        p["name_size_pt"] = style["name_size_pt"]
        p["_extracted"].append("字号")
    if style.get("font_size_pt"):
        p["font_size_pt"] = style["font_size_pt"]
    # **几何特征** —— 竖条 / 分隔线 / 横条
    #
    # **颜色字段也要一起搬** —— 只搬 px 不搬 color，
    # CSS 里就会用默认色（竖条变强调色 / 分隔线变 #cccccc）。
    for key, label in (("_accent_bar_px", "侧边色带"),
                       ("_accent_bar_color", "侧边色带"),
                       ("_divider_px", "分隔线"),
                       ("_divider_color", "分隔线"),
                       ("_band_color", "标题栏底色")):
        if style.get(key):
            p[key] = style[key]
            if label not in p["_extracted"]:
                p["_extracted"].append(label)
    if style.get("_pdf_font_name"):
        p["_extracted"].append("字体")
        # **PDF 字体名 → CSS font-family** ——
        # `SimSun`/`MicrosoftYaHei`/`SimHei` 这些能直接用；
        # 认不出来的（`ABCDEF+xxx`）不要瞎猜。
        fam = style["_pdf_font_name"]
        css_fam = _pdf_font_to_css(fam)
        if css_fam:
            p["font_family"] = '"%s", %s' % (css_fam, p["font_family"])

    # ── 版面结构 ──
    #
    # **配色对了但排版完全不像** —— 用户第二次反馈就是这个。
    # 光抽颜色不够，得抽「哪块是页眉 / 哪条是竖带 / 章节条什么色」。
    layout = {}
    try:
        alphas = _pdf_alpha_map(data)
        objs = _pdf_objects(data)
        forms = _pdf_forms(data, objs)
        texts, _raws = _pdf_streams(data)
        content = ""
        for t in texts:
            if re.search(r"/\S+\s+[\d.]+\s+Tf", t):
                content = t
                break
        if not content:
            for t in texts:
                if " re" in t and ("Tj" in t or " Do" in t):
                    content = t
                    break
        if content:
            rects = _pdf_rects(content, alphas, forms)
            if rects:
                page_h = max(r[3] for r in rects) - min(r[1] for r in rects)
                page_w = max(r[2] for r in rects) - min(r[0] for r in rects)
                layout = _pdf_layout(rects, page_w, page_h)
                for key in ("_header_bg", "_sidebar_color", "_band_color",
                            "_icon_color"):
                    if layout.get(key):
                        p[key] = layout[key]
                # **新版版面判定要覆盖旧的几何抽取** ——
                # 旧的 `_pdf_geometry` 只按形状猜「标题栏底色」，
                # 会把**页眉顶部的浅灰横条**当成章节底条
                # （稻壳儿模板就踩过 → 章节标题被涂成浅灰底）。
                # 新版会排除「贴顶」的块 → 没找到章节条就清掉。
                if "band" not in layout and "_band_color" in p:
                    p.pop("_band_color", None)
                    p["_extracted"] = [x for x in p["_extracted"]
                                       if x != "标题栏底色"]
    except Exception:
        # 版面解析失败**不能影响配色抽取** —— 宁可少还原一点
        layout = {}

    text, note = _pdf_text(data)
    if not text.strip():
        p["_note"] = note or ("这个 PDF 里没抽出文字（可能是扫描件）。"
                              "版式按 A4 近似还原。")
    else:
        p["_extracted"].append("文本内容")

    lines = [
        "/* 从 PDF 抽取的版式（PDF 没有样式表 —— 配色/字号按内容流近似还原） */",
        "body { font-family: %s; font-size: %spx; line-height: %s; }"
        % (p["font_family"], _pt_to_px(p["font_size_pt"]), p["line_height"]),
        "@page { size: %smm %smm; margin: %smm %smm %smm %smm; }"
        % (_num(p["page_width_mm"]), _num(p["page_height_mm"]),
           _num(p["margin_top_mm"]), _num(p["margin_right_mm"]),
           _num(p["margin_bottom_mm"]), _num(p["margin_left_mm"])),
        ".page { width: %smm; min-height: %smm; }"
        % (_num(p["page_width_mm"] - p["margin_left_mm"] - p["margin_right_mm"]),
           _num(p["page_height_mm"] - p["margin_top_mm"] - p["margin_bottom_mm"])),
        # **抽到的风格要真的作用到元素上** ——
        # 否则抽了也白抽（页面上还是默认蓝）。
        ".name { color: %s; font-size: %spx; }"
        % (p["accent_color"], _pt_to_px(p["name_size_pt"])),
        ".sec-title { color: %s; }" % p["accent_color"],
        ".item-title { color: %s; }" % p["title_color"],
        ".tag { border-color: %s; }" % p["accent_color"],
    ]

    # ── 几何特征 → CSS ──
    #
    # **竖条**（侧边色带）：贴在抬头左边
    if p.get("_accent_bar_px"):
        lines.append(
            ".head { border-left: %spx solid %s; padding-left: 10px; }"
            % (_num(p["_accent_bar_px"]), p.get("_accent_bar_color")
               or p["accent_color"]))
    # **细横线**（章节分隔线）
    if p.get("_divider_px"):
        lines.append(
            ".sec-title { border-bottom: %spx solid %s; padding-bottom: 3px; }"
            % (_num(p["_divider_px"]), p.get("_divider_color") or "#cccccc"))
    # **横条**（章节标题栏底色）
    #
    # **底色和文字色可能撞色** ——
    # 原设计常常是「深色底 + 白字」，但我们把标题文字也设成了强调色
    # → **深蓝底 + 深蓝字 = 字看不见**。
    #
    # → 底色**接近强调色**时，文字反过来用白色。
    band = p.get("_band_color")
    if band:
        title_color = p["accent_color"]
        if _color_close(band, p["accent_color"]):
            title_color = "#ffffff"
        lines.append(
            ".sec-title { background: %s; color: %s; padding: 3px 6px; }"
            % (band, title_color))

    # ── 版面结构 CSS ──
    if layout:
        try:
            lines.extend(_pdf_layout_css(layout, p["page_height_mm"]))
            labels = []
            # **只有真的生成了 CSS 才报这个特征** ——
            # 浅色页眉块（比如稻壳儿的 #f1f1f1 横条）不会变成
            # `.head { background }` → 报了就是虚报。
            if layout.get("_header_bg") and layout.get("_header_is_dark"):
                labels.append("页眉")
            if layout.get("_sidebar_color"):
                labels.append("侧边竖带")
            if layout.get("_band_color") and (layout.get("_band_count") or 0) >= 2:
                labels.append("章节底条")
            if layout.get("_icon_color") and (layout.get("_icon_count") or 0) >= 2:
                labels.append("章节图标")
            for lb in labels:
                if lb not in p["_extracted"]:
                    p["_extracted"].append(lb)
        except Exception:
            pass

    return "\n".join(lines) + "\n", p


def _pdf_text(data):
    """从 PDF 抽文本（纯正则抽文本流，不依赖字体映射表）。"""
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

def _image_size(data):
    """图片像素尺寸 —— **只用标准库**。

    ## 为什么不用 PIL

    项目的硬规矩是「零额外依赖」（见 CONTRIBUTING）。
    而 PIL 在本机 3.14（Hermes 自带）有、**CI 的 3.11/3.12/3.13 没有**
    → 本机测试全绿、CI 全红。

    PNG 和 JPEG 的尺寸都在文件头里，标准库够用：
    - **PNG**：8 字节签名 + IHDR chunk，宽高是 4 字节大端
    - **JPEG**：扫 SOF0~SOF15 标记（**排除 DHT/DAC/RSTn**），取段里的宽高
    - **GIF**：头 6 字节后是宽高（小端）
    - **WebP**：RIFF 容器，分 VP8 / VP8L / VP8X 三种
    """
    if not data:
        return None, None

    # ── PNG ──
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        # IHDR：长度(4) 类型(4) 宽(4) 高(4)
        if len(data) >= 24 and data[12:16] == b"IHDR":
            w = int.from_bytes(data[16:20], "big")
            h = int.from_bytes(data[20:24], "big")
            return w, h
        return None, None

    # ── GIF ──
    if data[:6] in (b"GIF87a", b"GIF89a"):
        if len(data) >= 10:
            w = int.from_bytes(data[6:8], "little")
            h = int.from_bytes(data[8:10], "little")
            return w, h
        return None, None

    # ── JPEG ──
    if data[:2] == b"\xff\xd8":
        i = 2
        n = len(data)
        while i + 9 < n:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            # 填充字节
            if marker in (0xFF, 0x01) or 0xD0 <= marker <= 0xD9:
                i += 2
                continue
            seg_len = int.from_bytes(data[i + 2:i + 4], "big")
            # SOF0~SOF15（排除 DHT=c4 / DAC=cc / RSTn=d0-d7）
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h = int.from_bytes(data[i + 5:i + 7], "big")
                w = int.from_bytes(data[i + 7:i + 9], "big")
                return w, h
            i += 2 + seg_len
        return None, None

    # ── WebP ──
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            w = int.from_bytes(data[24:27], "little") + 1
            h = int.from_bytes(data[27:30], "little") + 1
            return w, h
        if chunk == b"VP8 " and len(data) >= 30:
            # 有损：帧头里找 0x9d012a 标记
            k = data.find(b"\x9d\x01\x2a", 20)
            if k >= 0 and k + 7 <= len(data):
                w = int.from_bytes(data[k + 3:k + 5], "little") & 0x3FFF
                h = int.from_bytes(data[k + 5:k + 7], "little") & 0x3FFF
                return w, h
        if chunk == b"VP8L" and len(data) >= 25:
            b = data[21:25]
            bits = int.from_bytes(b, "little")
            w = (bits & 0x3FFF) + 1
            h = ((bits >> 14) & 0x3FFF) + 1
            return w, h
        return None, None

    return None, None


def _image_to_css(data, ext):
    """图片 → 「底图 + 文字层」。

    图片本身当背景，文字浮在上面（绝对定位在页面上）。
    **这是视觉还原，不是结构还原** —— 文字层的位置是估算的。
    """
    p = dict(DEFAULTS)
    p["_extracted"] = []
    width_px = height_px = None
    try:
        width_px, height_px = _image_size(data)
        if width_px and height_px:
            p["_extracted"].append("图片尺寸")
    except Exception:      # noqa: BLE001
        # 读不到尺寸也能做 —— 只是按 A4 兜底
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

SUPPORTED = ("docx", "doc", "pdf", "png", "jpg", "jpeg", "webp")


def _sniff_format(data):
    """按**文件头**判断真实格式（magic number）。

    返回 'docx' / 'ole2' / 'pdf' / 'png' / 'jpeg' / 'gif' / 'webp'，
    认不出来返回 None。

    ## 为什么不能只看扩展名

    本机踩过：用户的模板叫「后端开发.doc」，内容其实是 docx
    （Word 存成了 docx 但改了扩展名）。只看扩展名 → 直接拒绝 →
    用户说「无法上传 word 格式的模板」。

    **扩展名是用户随手改的，文件头不会骗人。**
    """
    if not data:
        return None
    head = data[:16]
    if head[:4] == b"PK\x03\x04" or head[:4] == b"PK\x05\x06":
        return "docx"
    if head[:4] == b"\xd0\xcf\x11\xe0":
        return "ole2"
    if head[:5] == b"%PDF-":
        return "pdf"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


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
                "error": "只支持 .docx / .doc / .pdf / .png / .jpg / .webp（收到 .%s）" % ext}

    if not data:
        return {"ok": False, "error": "文件内容是空的"}

    # **扩展名不可信 —— 按内容判断真实格式**
    #
    # 本机真踩过：用户的模板文件叫「后端开发.**doc**」，
    # 但内容其实是 **docx**（Word 存成了 docx 只是改了扩展名）。
    # 只看扩展名 → 直接拒绝 → 用户说「无法上传 word 格式的模板」。
    #
    # 判据（文件头 magic number）：
    #   PK\x03\x04      → zip → docx
    #   \xd0\xcf\x11\xe0 → OLE2 → **真正的旧版 .doc**（不支持）
    #   %PDF             → PDF
    #   \x89PNG / \xff\xd8\xff → 图片
    real = _sniff_format(data)
    if real == "docx":
        ext = "docx"          # .doc 里装的是 docx
    elif real == "ole2":
        return {"ok": False,
                "error": "这是旧版 .doc（Word 97-2003 二进制格式），不支持。"
                          "请在 Word 里另存为 .docx 再上传"}
    elif real and real != ext:
        # 扩展名说 .pdf，内容却是图片之类 —— **信内容**
        ext = real if real in SUPPORTED else ext

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
