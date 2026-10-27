"""简历文件导出与档案管理。

**PDF 走 Chrome headless** —— 不装 weasyprint/reportlab。
本机有 Chrome，HTML→PDF 的还原度也比纯排版库好。

**投递成功的简历自动存 PDF + 打标签**（2026-10-26 用户定），
标签是后续简历评分推荐的依据。
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime

# 已知可用的 Chrome / Edge
_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_chrome():
    """找一个能用的浏览器。找不到返回 None。"""
    for p in _CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    for name in ("chrome", "msedge", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return None


def html_to_pdf(html, out_path, timeout=60):
    """HTML → PDF。用 Chrome headless。

    返回 True/False（失败不抛，调用方决定怎么办）。
    """
    browser = find_chrome()
    if not browser:
        return False
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp_html = None
    try:
        fd, tmp_html = tempfile.mkstemp(suffix=".html", prefix="jr-resume-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(html)
        proc = subprocess.run(
            [browser, "--headless", "--disable-gpu", "--no-sandbox",
             "--print-to-pdf=" + out_path, "--no-pdf-header-footer",
             "--virtual-time-budget=6000",
             "file:///" + tmp_html.replace("\\", "/")],
            capture_output=True, timeout=timeout)
        return os.path.exists(out_path) and os.path.getsize(out_path) > 0
    except Exception:
        return False
    finally:
        if tmp_html and os.path.exists(tmp_html):
            try:
                os.remove(tmp_html)
            except OSError:
                pass


# ── 简历档案目录 ─────────────────────────────────────────────────────────────

def _plugin_data_dir() -> str:
    try:
        from plugins.plugin_storage import plugin_data_dir
        return plugin_data_dir("job-radar")
    except ImportError:
        return os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "hermes", "plugin-data", "job-radar")


def resume_dir() -> str:
    """投递成功的简历档案目录。"""
    d = os.path.join(_plugin_data_dir(), "resume")
    os.makedirs(d, exist_ok=True)
    return d


def upload_dir() -> str:
    """用户上传的原件目录。"""
    d = os.path.join(_plugin_data_dir(), "uploads")
    os.makedirs(d, exist_ok=True)
    return d


def drafts_dir() -> str:
    """生成但还没确认的草稿目录。"""
    d = os.path.join(_plugin_data_dir(), "drafts")
    os.makedirs(d, exist_ok=True)
    return d


# ── 标签 ─────────────────────────────────────────────────────────────────────

def _storage():
    """取 storage 模块。

    独立跑（单测、脚本）时没有父包，相对导入会炸 —— 退化到同目录导入。
    """
    try:
        from . import storage
    except ImportError:
        import storage
    return storage


def build_tags(job, matched):
    """投递时打的标签 = 岗位方向 + 命中技能 + 岗位关键词。

    **只从真实命中项来**，不凭空生成 —— 标签是后续简历评分的依据，
    编造的标签会污染推荐。
    """
    tags = []
    title = (job.get("title") or "").strip()
    if title:
        tags.append(title)
    for sk in (matched.get("covered") and
               [s for c in matched["covered"] for s in c["matched"]] or []):
        if sk not in tags:
            tags.append(sk)
    for kw in (matched.get("requirements", {}).get("keywords") or [])[:5]:
        if kw not in tags:
            tags.append(kw)
    return tags[:12]


def save_resume(job, matched, html, pdf_path=None, template_id="classic"):
    """把一份简历存进档案：PDF + 标签 + 元信息。

    返回 resume_id。PDF 生成失败也存（只是没有 PDF）—— 宁可少个文件，
    也别丢标签。
    """
    storage = _storage()

    rid = uuid.uuid4().hex[:12]
    base = os.path.join(resume_dir(), rid)
    tags = build_tags(job, matched)

    html_path = base + ".html"
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    ok_pdf = False
    if pdf_path is None:
        pdf_path = base + ".pdf"
        ok_pdf = html_to_pdf(html, pdf_path)
    else:
        ok_pdf = os.path.exists(pdf_path)

    storage.upsert_resume({
        "resume_id": rid,
        "title": "%s · %s" % (job.get("title") or "简历",
                              datetime.now().strftime("%m-%d")),
        "file_path": pdf_path if ok_pdf else html_path,
        "format": "pdf" if ok_pdf else "html",
        "tags": tags,
        "source": "optimized",
        "job_id": job.get("job_id") or "",
        "created": datetime.now().isoformat(timespec="seconds"),
    })
    return {"resume_id": rid, "path": pdf_path if ok_pdf else html_path,
            "pdf": ok_pdf, "tags": tags}


def list_resumes(limit=50):
    """简历档案列表（含标签）。"""
    return _storage().list_resumes(limit=limit)


def resume_matches(job, resume):
    """历史简历 × 岗位的匹配分 —— 投递时排序用。

    用简历的标签和岗位要求算重合度。**不调大模型。**
    """
    try:
        from .resume_builder import extract_requirements, normalize
    except ImportError:
        from resume_builder import extract_requirements, normalize

    reqs = extract_requirements(job.get("description") or "", None)
    wanted = {normalize(s["name"]) for s in reqs.get("skills", [])}
    tags = {normalize(t) for t in (resume.get("tags") or [])}

    if not wanted:
        return 0
    hit = len(wanted & tags)
    return int(round(100 * hit / len(wanted)))
