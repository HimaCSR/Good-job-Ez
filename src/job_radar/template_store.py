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
        # **dry_run 也要抽骨架** —— 预览要显示**模板自己的结构**，
        # 不能用内置骨架预览（那是「个人简介/工作经历」，不是模板的章节）。
        spec = None
        skeleton = ""
        if ext == "pdf":
            try:
                import template_slots
                spec, _n = template_slots.extract_slots(raw, "pdf")
                if spec:
                    import template_convert as _tc
                    _css, _params = _tc._pdf_to_css(raw)
                    skeleton = template_slots.build_slot_html(spec, {
                        "font_family": _params.get("font_family"),
                        "text_color": "#333333",
                        "page_width_mm": _params.get("page_width_mm"),
                        "page_height_mm": _params.get("page_height_mm"),
                        "accent_color": _params.get("accent_color"),
                        "title_color": _params.get("title_color"),
                        "extra_css": _css,
                    })
            except Exception:      # noqa: BLE001
                spec = None
                skeleton = ""
        return {"ok": True, "template": info,
                "spec": spec, "skeleton": skeleton,
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

    # ── 骨架规格 + 骨架 HTML ──
    #
    # **为什么不只存 CSS** ——
    # 存 CSS 只能换颜色，HTML 结构还是内置那套。
    # 用户：「现在有样式了，但与我提供的模板文件完全不同。」
    #
    # → 存**模板自己的骨架**（章节结构 + 槽位），
    # 渲染时按骨架填内容 —— 章节标题用模板的，内容用用户的。
    spec = None
    skeleton = ""
    if ext == "pdf":
        try:
            import template_slots
            spec, _note = template_slots.extract_slots(raw, "pdf")
            if spec:
                import template_convert as _tc
                _css, _params = _tc._pdf_to_css(raw)
                style = {
                    "font_family": _params.get("font_family"),
                    "text_color": "#333333",
                    "page_width_mm": _params.get("page_width_mm"),
                    "page_height_mm": _params.get("page_height_mm"),
                    "accent_color": _params.get("accent_color"),
                    "title_color": _params.get("title_color"),
                    "extra_css": _css,
                    # **页眉是不是深色** —— 决定页眉文字要不要反白。
                    # 白底模板用白字 = 隐形（本机踩过：稻壳儿的电话邮箱看不见）。
                    "header_is_dark": bool(
                        (spec.get("head") or {}).get("header_is_dark")),
                }
                skeleton = template_slots.build_slot_html(spec, style)
        except Exception as e:      # noqa: BLE001
            # **骨架抽取失败不能影响模板落盘** ——
            # 至少还能当「只有 CSS 的模板」用。
            spec = None
            skeleton = ""

    if spec:
        import json
        spec_path = os.path.join(templates_dir, tid + ".spec.json")
        try:
            with open(spec_path, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(spec, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass
    if skeleton:
        sk_path = os.path.join(templates_dir, tid + ".skeleton.html")
        try:
            with open(sk_path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(skeleton)
        except OSError:
            pass

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

def save_slots(template_id, edit):
    """保存用户编辑后的槽位 → 重建骨架 → 返回新骨架 HTML。

    ## 为什么「编辑后要重建骨架」

    骨架 HTML 里**章节标题是按模板的章节列表生成的**
    （求职意向/自我评价/实习经历…），字段标签也是。
    改了槽位 → 骨架要跟着重生成，否则改了也不生效。

    ## 为什么不重新转换

    **原始文件可能已经不在了**（用户上传完就删了），
    而且重新转换会把用户的编辑覆盖掉。
    → 只改 spec + 重建骨架，CSS 保持不变。

    返回 {"ok": True, "spec": ..., "skeleton": html}
    """
    import json
    import os

    if not template_id:
        return {"ok": False, "error": "缺少 template_id"}
    templates_dir = resume_template.TEMPLATES_DIR
    spec_path = os.path.join(templates_dir, template_id + ".spec.json")
    css_path = os.path.join(templates_dir, template_id + ".css")

    spec = None
    try:
        with open(spec_path, encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, ValueError):
        spec = None
    if not spec:
        return {"ok": False, "error": "这个模板没有骨架规格（不是 PDF 模板？）"}

    try:
        import template_slots
    except ImportError:
        import template_slots

    try:
        spec = template_slots.apply_slot_edit(spec, edit or {})
    except Exception as e:      # noqa: BLE001
        return {"ok": False, "error": "槽位编辑失败：%s" % e}

    # ── 重建骨架 ──
    css = ""
    try:
        with open(css_path, encoding="utf-8") as fh:
            css = fh.read()
    except OSError:
        css = ""
    style = {
        "extra_css": css,
        "text_color": "#333333",
        # **页眉深浅要跟着规格走** —— 否则重建骨架后反白规则丢了
        # → 深底白底判断错 → 白底模板的字段隐形。
        "header_is_dark": bool((spec.get("head") or {}).get("header_is_dark")),
    }
    try:
        skeleton = template_slots.build_slot_html(spec, style)
    except Exception as e:      # noqa: BLE001
        return {"ok": False, "error": "重建骨架失败：%s" % e}

    # ── 落盘 ──
    try:
        with open(spec_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(spec, fh, ensure_ascii=False, indent=2)
    except OSError as e:
        return {"ok": False, "error": "写槽位规格失败：%s" % e}
    sk_path = os.path.join(templates_dir, template_id + ".skeleton.html")
    try:
        with open(sk_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(skeleton)
    except OSError as e:
        return {"ok": False, "error": "写骨架失败：%s" % e}

    return {
        "ok": True,
        "spec": spec,
        "skeleton": skeleton,
        "edit": template_slots.spec_to_edit(spec),
    }


def load_slots(template_id):
    """读一个模板的槽位规格（给前端编辑用）。"""
    import json
    import os

    if not template_id:
        return {"ok": False, "error": "缺少 template_id"}
    templates_dir = resume_template.TEMPLATES_DIR
    spec_path = os.path.join(templates_dir, template_id + ".spec.json")
    try:
        with open(spec_path, encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, ValueError):
        return {"ok": False, "error": "没有槽位规格", "has_slots": False}
    try:
        import template_slots
    except ImportError:
        import template_slots
    return {
        "ok": True,
        "has_slots": True,
        "edit": template_slots.spec_to_edit(spec),
        "roles": template_slots.slot_role_labels(),
    }
