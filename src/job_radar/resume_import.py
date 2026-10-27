"""简历文件解析 —— 从 .docx / .pdf / .txt 里抽字段，填进画像表单。

## 铁律

1. **不调大模型** —— 简历内容是个人信息，发出去就是泄露。
   全部走本地规则（段落结构 + 字段关键词）。
2. **文件不离开本机** —— 读进来就在内存里解析，不落盘、不外传。
3. **结果是草稿** —— 解析出来的是「一份草稿」，
   用户核对后点保存才写进 profile.yaml。

## 支持的格式

| 格式 | 怎么读 | 精度 |
| --- | --- | --- |
| `.txt` | 直接读文本 | 最高 |
| `.docx` | `zipfile` 读 `word/document.xml`，抽 `<w:t>` 文本 | 高 |
| `.pdf` | 抽文本流里的 `(...) Tj` / `[...] TJ` | 中（版式复杂的会丢） |

**`.pdf` 的局限**：真正的 PDF 文本抽取需要字体映射表，纯正则只能拿到
大部分可读文本，遇到复杂排版会漏。抽不全就返回空，让用户知道
「这个 PDF 抽不出来，建议用 .docx 或 .txt」—— **不要瞎猜填**。

## 抽哪些字段

- **身份信息**：姓名 / 电话 / 邮箱 / 学历 / 毕业院校
- **技能**：从「技能」段落里切词
- **经历**：按时间倒序的段落（公司 / 职位 / 起止 / 描述）
- **期望条件**：城市 / 岗位方向 / 最低薪资

**抽不到就留空**，不编造。
"""

import io
import os
import re
import zipfile

# ── 文本抽取 ────────────────────────────────────────────────────────────────

def extract_text(filename, data):
    """从文件字节里抽纯文本。

    返回 (text, note)。note 说明抽的情况（给用户看）。
    """
    ext = os.path.splitext(filename or "")[1].lower()
    if ext == ".txt":
        return _decode(data), ""
    if ext == ".docx":
        return _read_docx(data), ""
    if ext == ".pdf":
        return _read_pdf(data)
    return "", "不支持的格式：%s（支持 .docx / .pdf / .txt）" % (ext or "未知")


def _decode(data):
    for enc in ("utf-8", "gbk", "gb18030", "utf-16"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _read_docx(data):
    """从 .docx 抽文本。

    .docx 是 zip，文档正文在 `word/document.xml`。
    **段落边界必须保留** —— 后面按段落切经历靠它，
    把内容连成一坨就切不出经历了。
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            xml_name = None
            for cand in ("word/document.xml", "word/document2.xml"):
                if cand in names:
                    xml_name = cand
                    break
            if xml_name is None:
                return ""
            xml = z.read(xml_name).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError, OSError):
        return ""
    return _docx_text_ordered(xml)


def _docx_text_ordered(xml):
    """按 XML 顺序还原文本（段落之间换行）。

    **不能先把 `<w:p>` 替换掉再抽文本** —— 那样段落标记就没了。
    正确做法：一次扫描，同时认「标签」和「文本」。
    """
    out = []
    for m in re.finditer(
            r"<w:p\b[^>]*/?>"          # 段落开始
            r"|<w:br\b[^>]*/?>"         # 段内换行
            r"|<w:tab\b[^>]*/?>"        # 制表符
            r"|<w:tc\b[^>]*/?>"         # 表格单元格
            r"|</w:tc>"
            r"|<w:t(?:\s[^>]*)?>(.*?)</w:t>",   # 文本
            xml, re.S):
        token = m.group(0)
        if token.startswith("<w:t"):
            content = m.group(1) or ""
            content = (content.replace("&amp;", "&").replace("&lt;", "<")
                       .replace("&gt;", ">").replace("&quot;", '"')
                       .replace("&apos;", "'"))
            out.append(content)
        elif token == "</w:tc>":
            out.append(" | ")
        elif token.startswith("<w:tc"):
            out.append("\t")
        else:
            # <w:p> / <w:br> / <w:tab>
            out.append("\n" if not token.startswith("<w:tab") else "\t")
    # 连续空行压成一个（段落之间留一个空行，_paragraphs 靠它切）
    text = "".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _read_pdf(data):
    """从 .pdf 抽文本（尽力而为）。

    PDF 里文字通常在 `(...) Tj` 或 `[...] TJ` 里。
    复杂排版会丢 —— 抽不全就老实说，别瞎填。
    """
    try:
        raw = data.decode("latin-1", errors="replace")
    except Exception:      # noqa: BLE001
        return "", "PDF 读取失败"

    chunks = []

    # (字串) Tj
    for m in re.finditer(r"\(((?:[^()\\]|\\.)*)\)\s*Tj", raw):
        chunks.append(_pdf_unescape(m.group(1)))
    # [ (a) -10 (b) ] TJ
    for m in re.finditer(r"\[((?:[^\[\]\\]|\\.)*)\]\s*TJ", raw):
        parts = re.findall(r"\(((?:[^()\\]|\\.)*)\)", m.group(1))
        if parts:
            chunks.append("".join(_pdf_unescape(p) for p in parts))

    text = "\n".join(c for c in chunks if c.strip())
    note = ""
    if not text.strip():
        note = ("这个 PDF 没抽出文字（可能是扫描件或字体是图片嵌入）。"
                "建议用 .docx 或 .txt 导出后再导入。")
    return text, note


def _pdf_unescape(s):
    s = s.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")
    s = re.sub(r"\\(\d{1,3})", lambda m: chr(int(m.group(1), 8)), s)
    return s


# ── 字段抽取 ────────────────────────────────────────────────────────────────

# 身份字段的标签词 → profile.identity 的键
IDENTITY_LABELS = {
    "name": ("姓名", "名字", "name"),
    "phone": ("手机", "电话", "手机号", "联系电话", "phone", "tel"),
    "email": ("邮箱", "电子邮箱", "email", "mail"),
    "school": ("毕业院校", "学校", "院校", "毕业学校"),
    "major": ("专业", "所学专业"),
}

DEGREE_WORDS = ("博士", "硕士", "本科", "大专", "高中", "中专")

# 手机号
RE_PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
# 邮箱
RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# 学历
RE_DEGREE = re.compile(r"(博士|硕士|本科|大专|高中|中专|研究生)")


def _paragraphs(text):
    """切段落（空行分隔）。"""
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def _lines(text):
    """切行。"""
    return [l.strip() for l in (text or "").splitlines() if l.strip()]


def _find_labeled(text, labels, max_len=40):
    """找「标签: 值」这种行。

    简历里常见：`姓名：张三`、`手机 138xxxxxxxx`、`邮箱 a@b.com`
    """
    for line in _lines(text):
        for lab in labels:
            # 标签后跟可选的冒号/空格/全角冒号
            m = re.search(
                re.escape(lab) + r"\s*[:：]?\s*(.{0,%d})" % max_len, line)
            if m:
                val = m.group(1).strip()
                val = re.split(r"[\s|｜,，;；]{2,}|\t", val)[0].strip()
                if val:
                    return val
    return ""


def parse_identity(text):
    """抽身份信息。抽不到就留空 —— 不猜。"""
    out = {}
    flat = re.sub(r"\n+", " ", text or "")

    # 姓名：优先带标签的
    name = _find_labeled(text, IDENTITY_LABELS["name"], 20)
    if not name:
        # 第一行短且不含数字/符号，像姓名
        first = _lines(text)[:1]
        if first:
            cand = first[0].strip()
            if 2 <= len(cand) <= 8 and not RE_PHONE.search(cand) \
                    and not RE_EMAIL.search(cand) and "简历" not in cand \
                    and not re.search(r"[0-9]", cand):
                name = cand
    if name:
        out["name"] = name

    m = RE_PHONE.search(flat)
    if m:
        out["phone"] = m.group(1)
    m = RE_EMAIL.search(flat)
    if m:
        out["email"] = m.group(0)

    degree = RE_DEGREE.search(text or "")
    if degree:
        out["degree"] = degree.group(1)

    school = _find_labeled(text, IDENTITY_LABELS["school"], 30)
    if school:
        out["school"] = school
    major = _find_labeled(text, IDENTITY_LABELS["major"], 30)
    if major:
        out["major"] = major
    return out


# 技能段落的小标题
SKILL_SECTION_WORDS = ("技能", "专业技能", "技术栈", "掌握技能", "技能特长",
                       "IT技能", "IT 技能", "Skills", "SKILLS", "Skill")
# 经历段落的小标题
EXP_SECTION_WORDS = ("工作经历", "工作经验", "职业经历", "实习经历", "项目经历",
                     "工作履历", "Work Experience", "EXPERIENCE")


def _section_lines(lines, titles):
    """取某个小标题下面的若干行。"""
    out = []
    in_section = False
    for l in lines:
        norm = l.strip().rstrip(":：")
        if any(norm.startswith(t) or norm == t for t in titles):
            in_section = True
            # 同一行后面可能直接跟着内容
            rest = l.strip()
            for t in titles:
                if rest.startswith(t):
                    rest = rest[len(t):].lstrip(":： ").strip()
            if rest:
                out.append(rest)
            continue
        if in_section:
            # 遇到下一个标题行就停
            if re.match(r"^(教育背景|自我评价|获奖|证书|项目经历|工作经历|"
                        r"工作经验|实习经历|联系方式|基本信息|求职意向)", l.strip()):
                break
            out.append(l)
    return out


def parse_skills(text):
    """抽技能列表。"""
    lines = _lines(text)
    sec = _section_lines(lines, SKILL_SECTION_WORDS)
    blob = " ".join(sec) if sec else ""

    # 从技能段落里切词
    raw = re.split(r"[,，、;；/|｜\s]+", blob)
    skills = []
    for w in raw:
        w = w.strip(" .·-—")
        if not w or len(w) > 24:
            continue
        # 过滤明显不是技能的
        if re.search(r"(序号|技能|掌握|熟练|精通|了解|熟悉)", w):
            continue
        if w in skills:
            continue
        skills.append(w)

    # 技能段落没找到 → 从全文里扫已知技能别名
    if not skills:
        try:
            from .resume_builder import SKILL_ALIASES
        except ImportError:
            from resume_builder import SKILL_ALIASES
        low = (text or "").lower()
        for name in SKILL_ALIASES:
            for alias in SKILL_ALIASES[name][:2]:
                if alias.lower() in low and name not in skills:
                    skills.append(name)
                    break
    return skills[:30]


# 时间区间。分隔符有多种写法：`.` `-` `/` `年` `-` `至` …
#
# 「2021/07/2023/03」这种**两边都带斜杠**的写法也要认 ——
# 用 `[-~－—至到]` 做中间分隔符时，斜杠会被吃掉，
# 所以结束年份前面单独允许一个分隔符。
RE_DATE_RANGE = re.compile(
    r"(20\d{2})\s*[.\-/年]\s*(\d{1,2})?\s*月?\s*"
    r"[-~－—至到/\s]+\s*"
    r"(至今|现在|now|20\d{2})\s*[.\-/年]?\s*(\d{1,2})?\s*月?")


def _parse_date(text):
    """从一段文字里抽起止时间。"""
    m = RE_DATE_RANGE.search(text or "")
    if not m:
        return "", ""
    y1, m1, y2, m2 = m.group(1), m.group(2), m.group(3), m.group(4)
    start = "%s-%02d" % (y1, int(m1 or 1))
    if y2 in ("至今", "现在", "now"):
        end = "至今"
    else:
        end = "%s-%02d" % (y2, int(m2 or 1))
    return start, end


def parse_experiences(text):
    """抽结构化经历。

    一条经历 = 标题行（公司 + 职位）+ 时间 + 描述行。
    **只重组原文，不改写**。
    """
    lines = _lines(text)
    sec = _section_lines(lines, EXP_SECTION_WORDS)
    if not sec:
        return []

    experiences = []
    current = None
    for l in sec:
        start, end = _parse_date(l)
        has_date = bool(start)

        if has_date:
            # 有时间 → 可能是经历标题行
            if current:
                experiences.append(current)
            current = {
                "company": "",
                "title": "",
                "start": start,
                "end": end,
                "bullets": [],
                "raw": l,
            }
            # 标题行里公司/职位
            head = re.sub(RE_DATE_RANGE, "", l).strip(" |｜·—-– ")
            parts = [p.strip() for p in re.split(r"[|｜\t]|\s{2,}", head) if p.strip()]
            if len(parts) >= 2:
                current["company"] = parts[0]
                current["title"] = parts[1]
            elif parts:
                current["title"] = parts[0]
            continue

        if current is None:
            continue
        # 描述行
        b = l.strip(" |｜·—-– ")
        if b:
            current["bullets"].append(b)
    if current:
        experiences.append(current)

    # 丢掉没有描述的（多半是误判）
    out = []
    for i, e in enumerate(experiences, 1):
        if not e["bullets"]:
            continue
        e["id"] = "imp-%d" % i
        out.append(e)
    return out[:12]


def parse_expectations(text):
    """抽期望条件：城市 / 岗位方向 / 最低薪资。"""
    out = {}
    lines = _lines(text)

    # 城市：找「意向城市 / 期望城市 / 城市」
    for line in lines:
        m = re.search(r"(?:意向|期望|目标|所在)?城市\s*[:：]?\s*(.{0,40})", line)
        if m:
            raw = m.group(1)
            cities = [c.strip() for c in re.split(r"[,，、/|｜\s]+", raw) if c.strip()]
            cities = [c for c in cities if c not in ("不限", "无", "全国", "/")][:6]
            if cities:
                out["cities"] = cities
            break

    # 岗位方向：找「求职意向 / 意向岗位 / 期望职位」
    for line in lines:
        m = re.search(r"(?:求职意向|意向岗位|期望职位|应聘岗位|目标岗位)\s*[:：]?\s*(.{0,40})", line)
        if m:
            raw = m.group(1)
            kws = [k.strip() for k in re.split(r"[,，、/|｜\s]+", raw) if k.strip()]
            kws = [k for k in kws if k not in ("无", "不限", "/")][:6]
            if kws:
                out["title_keywords"] = kws
            break

    # 最低薪资：找「期望薪资 / 薪资要求」
    for line in lines:
        m = re.search(r"(?:期望|意向|最低)?薪资(?:要求|期望)?\s*[:：]?\s*(.{0,20})", line)
        if m:
            raw = m.group(1)
            nums = re.findall(r"(\d+)\s*[kK]", raw)
            if nums:
                out["min_salary"] = int(nums[0])
            else:
                nums = re.findall(r"(\d{4,6})\s*元", raw)
                if nums:
                    out["min_salary"] = int(nums[0]) // 1000
            break

    return out


def parse_resume(filename, data):
    """解析一份简历文件，返回草稿。

    返回 {
      "ok": bool,
      "note": str,          # 提示（抽得怎么样）
      "draft": {
        "identity": {...},
        "skills": [...],
        "cities": [...],
        "title_keywords": [...],
        "min_salary": int,
        "experiences": [{company,title,start,end,bullets}],
        "experience_text": str,   # 原文拼回去，供「真实经历」字段用
      },
      "found": {"identity": n, "skills": n, "experiences": n},
    }
    """
    text, note = extract_text(filename, data)
    if not text.strip():
        return {"ok": False,
                "note": note or "没从这个文件里读出文字，试试 .docx 或 .txt",
                "draft": {}, "found": {}}

    identity = parse_identity(text)
    skills = parse_skills(text)
    experiences = parse_experiences(text)
    expectations = parse_expectations(text)

    # 经历原文（供「真实经历」字段）
    exp_text = "\n\n".join(
        ("【%s%s】%s" % (e.get("company", ""),
                        (" · " + e["title"]) if e.get("title") else "",
                        e.get("start", "")))
        + "\n" + "\n".join(e["bullets"])
        for e in experiences)

    draft = {
        "identity": identity,
        "skills": skills,
        "cities": expectations.get("cities", []),
        "title_keywords": expectations.get("title_keywords", []),
        "min_salary": expectations.get("min_salary", 0),
        "experiences": experiences,
        "experience_text": exp_text,
    }
    found = {
        "identity": len(identity),
        "skills": len(skills),
        "experiences": len(experiences),
    }
    if not any(found.values()):
        note = (note + " " if note else "") + \
            "没识别出姓名/技能/经历 —— 这份简历的排版可能比较特殊，手动填更稳妥。"
    return {"ok": True, "note": note, "draft": draft, "found": found}
