"""上传模板的完整流程：文件 → 转换 → 落盘 → 登记。

## 流程

    上传的文件（base64）
      → template_convert.convert()      抽版式 → CSS 片段
      → 落 <templates>/<id>.css          （图片模板再落 <id>.bg）
      → storage.upsert_template()        登记到 SQLite
      → 返回模板信息

## 为什么拆成两个模块

- `template_convert` —— **纯函数**，不碰磁盘不碰数据库，好测
- 本模块 —— 副作用（写文件、写库）

## 模板 id 怎么来

**由文件名派生，不是随机的** —— 同一个文件反复转换应该覆盖同一条，
随机会在模板库里堆一堆「我的简历」。跟 mock 层的行为保持一致。

## 落盘位置

`resume_template.TEMPLATES_DIR` —— 相对插件目录，不是相对 cwd。
相对 cwd 的话换个目录跑脚本就找不到模板了。
"""

import hashlib
import os
import shutil

try:  # 包内导入
    from . import template_convert
    from . import resume_template
except ImportError:  # 独立脚本 / 平铺导入
    import template_convert  # type: ignore
    import resume_template  # type: ignore


def _template_id(filename, ext):
    """从文件名派生模板 id —— 同一个文件反复转换覆盖同一条。"""
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    digest = hashlib.md5((stem + "|" + ext).encode("utf-8")).hexdigest()[:8]
    # 文件名里的危险字符去掉
    safe = "".join(ch for ch in stem if ch.isalnum() or ch in "-_")[:24]
    if not safe:
        safe = "template"
    return "user-%s-%s" % (safe, digest)


def _storage():
    """拿 storage 模块（包内/独立两种导入路径）。"""
    try:
        from . import storage
        return storage
    except ImportError:      # pragma: no cover
        import storage  # type: ignore
        return storage


def save_upload(filename, data_base64, kind=None, name=None,
                description=None, dry_run=False):
    """上传 → 转换 → 落盘 → 登记。

    dry_run=True 时只转换不落盘（用来「先看看能抽出什么」）。

    返回 {"ok": True, "template": {...}, "extracted": [...], "note": ""}
         或 {"ok": False, "error": "..."}
    """
    import base64

    if not filename:
        return {"ok": False, "error": "缺少文件名"}

    raw = b""
    if data_base64:
        try:
            # base64 可能带换行/空白
            clean = "".join(str(data_base64).split())
            raw = base64.b64decode(clean, validate=False)
        except Exception as e:      # noqa: BLE001
            return {"ok": False, "error": "文件内容解码失败：%s" % e}

    result = template_convert.convert(filename, raw, kind=kind)
    if not result.get("ok"):
        return result

    ext = os.path.splitext(os.path.basename(filename))[1].lower().lstrip(".")
    if kind:
        ext = str(kind).lower().lstrip(".")
    tid = _template_id(filename, ext)

    tpl_name = (name or os.path.splitext(os.path.basename(filename))[0]
                or "我的模板")
    desc = description or ("从 %s 转换" % os.path.basename(filename))

    info = {
        "template_id": tid,
        "name": tpl_name,
        "description": desc,
        "format": ext or "docx",
        "builtin": 0,
        "source_path": os.path.basename(filename),
        "preview_path": "",
        "created": None,
    }

    if dry_run:
        info["_dry_run"] = True
        return {"ok": True, "template": info,
                "extracted": result.get("extracted") or [],
                "note": result.get("note") or "",
                "css_preview": result.get("css") or ""}

    # ── 落盘 ──
    templates_dir = resume_template.TEMPLATES_DIR
    try:
        os.makedirs(templates_dir, exist_ok=True)
    except OSError as e:
        return {"ok": False, "error": "建模板目录失败：%s" % e}

    css_path = os.path.join(templates_dir, tid + ".css")
    try:
        with open(css_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(result["css"])
    except OSError as e:
        return {"ok": False, "error": "写模板文件失败：%s" % e}

    # 图片模板：底图单独存一份（渲染时转成 data URI）
    if ext in ("png", "jpg", "jpeg", "webp") and raw:
        bg_path = os.path.join(templates_dir, tid + ".bg")
        try:
            with open(bg_path, "wb") as fh:
                fh.write(raw)
        except OSError as e:
            return {"ok": False, "error": "写底图失败：%s" % e}

    # ── 登记 ──
    try:
        storage = _storage()
        storage.upsert_template(info)
    except Exception as e:      # noqa: BLE001
        return {"ok": False, "error": "登记模板失败：%s" % e}

    return {"ok": True, "template": info,
            "extracted": result.get("extracted") or [],
            "note": result.get("note") or ""}


def remove_upload(template_id):
    """删掉一个上传的模板（内置的不给删）。"""
    if template_id in resume_template.BUILTIN:
        return {"ok": False, "error": "内置模板不能删"}

    templates_dir = resume_template.TEMPLATES_DIR
    removed = []
    for suffix in (".css", ".bg"):
        path = os.path.join(templates_dir, template_id + suffix)
        if os.path.exists(path):
            try:
                os.remove(path)
                removed.append(suffix)
            except OSError as e:
                return {"ok": False, "error": "删文件失败：%s" % e}

    try:
        storage = _storage()
        storage.delete_template(template_id)
    except Exception:      # noqa: BLE001
        pass

    return {"ok": True, "removed": removed}
