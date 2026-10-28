"""模板上传转换的真实验证 —— 造文件 → 转换 → 渲染 → 出 PDF。

跟单测不同，这里跑**真实链路**：
  1. 造一个带版式参数的 .docx
  2. 走 template_store.save_upload()（真实落盘 + 真实入库）
  3. 用 resume_template.render_html() 渲染
  4. **用 Chrome headless 出 PDF** —— 看版式是不是真的能用

**为什么一定要出 PDF**：HTML 字符串对了不代表版式对了。
分栏、页边距、字号这些只有打印出来才看得出问题。

用法：
    python scripts/verify_template_convert.py
"""

import base64
import io
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path.insert(0, SRC)

import resume_template          # noqa: E402
import template_store           # noqa: E402

OK = "  ✔"
BAD = "  ✘"
fails = []


def check(label, cond, detail=""):
    global fails
    if cond:
        print(OK, label, detail)
    else:
        print(BAD, label, detail)
        fails.append(label)


# ── 造一个双栏 Word 模板 ────────────────────────────────────────────────────

DOC_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:p><w:r><w:rPr><w:rFonts w:ascii="SimSun" w:hAnsi="SimSun"/>
  <w:sz w:val="44"/><w:color w:val="1F4E79"/></w:rPr><w:t>张三</w:t></w:r></w:p>
<w:p><w:r><w:rPr><w:sz w:val="21"/></w:rPr><w:t>高级后端工程师</w:t></w:r></w:p>
<w:p><w:r><w:rPr><w:sz w:val="21"/></w:rPr><w:t>负责核心服务</w:t></w:r></w:p>
<w:sectPr>
  <w:pgSz w:w="11906" w:h="16838"/>
  <w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1701"/>
  <w:cols w:num="2"/>
</w:sectPr>
</w:body></w:document>"""

STYLES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:sz w:val="21"/></w:rPr></w:rPrDefault>
</w:docDefaults></w:styles>"""


def make_docx():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.'
                   'openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", DOC_XML)
        z.writestr("word/styles.xml", STYLES_XML)
    return buf.getvalue()


CONTEXT = {
    "title": "张三的简历",
    "identity": {
        "name": "张三",
        "headline": "高级后端工程师",
        "phone": "138****0000",
        "email": "zhangsan@example.com",
        "location": "杭州",
        "education": "本科 · 软件工程",
    },
    "sections": [
        {"title": "专业技能", "kind": "tags",
         "tags": ["Python", "Go", "PostgreSQL", "Kubernetes", "Redis"]},
        {"title": "工作经历", "kind": "entries", "entries": [
            {"title": "某科技公司 · 高级后端工程师", "meta": "2021.03 - 至今",
             "subtitle": "杭州",
             "bullets": [
                 {"text": "负责核心服务架构设计，支撑日均千万级请求",
                  "basis": "经历第 1 条"},
                 {"text": "主导数据库分库分表改造，查询延迟下降 60%",
                  "basis": "经历第 2 条"},
             ]},
            {"title": "某网络公司 · 后端工程师", "meta": "2018.07 - 2021.02",
             "bullets": [
                 {"text": "搭建 CI/CD 流水线，发布耗时从 40 分钟降到 6 分钟",
                  "basis": "经历第 3 条"},
             ]},
        ]},
        {"title": "教育背景", "kind": "entries", "entries": [
            {"title": "某某大学 · 软件工程", "meta": "2014 - 2018"},
        ]},
    ],
}


def main():
    tmp = tempfile.mkdtemp(prefix="jr-verify-tpl-")
    orig = resume_template.TEMPLATES_DIR
    resume_template.TEMPLATES_DIR = tmp

    try:
        print("=" * 62)
        print("模板上传转换 —— 真实链路验证")
        print("=" * 62)

        # ① 上传
        data = make_docx()
        b64 = base64.b64encode(data).decode("ascii")
        r = template_store.save_upload("我的双栏模板.docx", b64)
        check("上传转换返回 ok", r.get("ok"), r.get("error", ""))
        if not r.get("ok"):
            return 1
        tid = r["template"]["template_id"]
        print("     模板 id:", tid)
        print("     识别到:", "、".join(r.get("extracted") or []))

        # ② 落盘
        css_path = os.path.join(tmp, tid + ".css")
        check("CSS 文件已落盘", os.path.exists(css_path))
        with open(css_path, encoding="utf-8") as fh:
            css = fh.read()
        check("CSS 里有分栏", "display: flex" in css)
        check("CSS 里有页面尺寸", "@page" in css and "210mm" in css)
        check("CSS 里有抽到的字体", "SimSun" in css)
        check("CSS 里没有 %% 这种坏值", "%%" not in css)

        # ③ 渲染
        html = resume_template.render_html(tid, CONTEXT)
        check("HTML 渲染成功", len(html) > 500, "%d 字节" % len(html))
        check("HTML 含姓名", "张三" in html)
        check("HTML 含工作经历", "某科技公司" in html)
        check("HTML 含技能标签", "Kubernetes" in html)
        check("HTML 含模板 CSS", "SimSun" in html)

        # ④ 出 PDF —— 版式只有打印出来才知道对不对
        html_path = os.path.join(tmp, "out.html")
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(html)

        pdf_path = os.path.join(tmp, "out.pdf")
        ok_pdf = _chrome_pdf(html_path, pdf_path)
        check("Chrome headless 出 PDF", ok_pdf)
        if ok_pdf:
            size = os.path.getsize(pdf_path)
            check("PDF 不太小", size > 3000, "%d 字节" % size)
            print("     PDF:", pdf_path)

        # ⑤ 同一个文件再传一次 → 不堆重复
        r2 = template_store.save_upload("我的双栏模板.docx", b64)
        check("重复上传覆盖同一条", r2["template"]["template_id"] == tid)
        css_files = [f for f in os.listdir(tmp) if f.endswith(".css")]
        check("模板库没堆重复项", len(css_files) == 1, "共 %d 个" % len(css_files))

        # ⑥ 删除
        d = template_store.remove_upload(tid)
        check("删除上传的模板", d.get("ok"), d.get("error", ""))
        check("文件已清理", not os.path.exists(css_path))

        # ⑦ 内置模板不能删
        d2 = template_store.remove_upload("classic")
        check("内置模板拒绝删除", not d2.get("ok"), d2.get("error", ""))

        # ⑧ 内置模板仍然正常渲染（别被改坏）
        html2 = resume_template.render_html("classic", CONTEXT)
        check("内置模板仍能渲染", "张三" in html2 and len(html2) > 500)

        print("=" * 62)
        if fails:
            print("失败 %d 项：%s" % (len(fails), "、".join(fails)))
            return 1
        print("全部通过")
        return 0
    finally:
        resume_template.TEMPLATES_DIR = orig
        shutil.rmtree(tmp, ignore_errors=True)


def _chrome_pdf(html_path, pdf_path):
    """用 Chrome headless 把 HTML 打成 PDF。"""
    chrome = None
    for cand in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ):
        if os.path.exists(cand):
            chrome = cand
            break
    if not chrome:
        print("     (没找到 Chrome，跳过 PDF)")
        return False
    try:
        subprocess.run(
            [chrome, "--headless", "--disable-gpu", "--no-sandbox",
             "--print-to-pdf=" + pdf_path,
             "--no-pdf-header-footer",
             "file:///" + html_path.replace("\\", "/")],
            timeout=90, capture_output=True)
    except Exception as e:      # noqa: BLE001
        print("     Chrome 出错:", e)
        return False
    return os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1000


if __name__ == "__main__":
    sys.exit(main())
