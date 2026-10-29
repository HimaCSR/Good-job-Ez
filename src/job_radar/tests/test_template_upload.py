"""模板上传的**真机 bug** 回归测试。

## 本轮真机踩到的

用户：「我上传 C:\\Users\\19863\\Desktop\\简历模板 文件夹里的简历模板，会报错。
而且无法上传 word 相关格式的模板！」

那个文件夹里是：

| 文件 | 真实情况 |
| --- | --- |
| `后端开发.doc` | **内容其实是 docx**（文件头 `PK\\x03\\x04`）—— 只是扩展名写成 .doc |
| `现场管理.pdf` | 正常 PDF |
| `稻壳儿.pdf` | 正常 PDF |

## 两个根因

### ① 只认扩展名 → `.doc` 里装 docx 被拒

`convert()` 原本只看 `os.path.splitext(filename)`。
**扩展名是用户随手改的，文件头不会骗人。**

修法：加 `_sniff_format(data)` —— 按 magic number 判断真实格式。

| 文件头 | 格式 |
| --- | --- |
| `PK\\x03\\x04` | zip → docx |
| `\\xd0\\xcf\\x11\\xe0` | OLE2 → **真正的旧版 .doc**（明确报错让用户另存为 .docx） |
| `%PDF-` | PDF |
| `\\x89PNG` / `\\xff\\xd8\\xff` | 图片 |

### ② `<input type="file">` 选文件夹 → 浏览器直接报错

选目录**必须**用带 `webkitdirectory` 的**另一个** input。
而且那个 input **不能带 `accept`** —— 带了会把目录里的文件全过滤掉。

前端修法：
- `accept` 加上 `.doc`（不然文件选择框里根本选不到）
- 新增 `uploadDirRef` + 一个 `webkitdirectory` 的 input
- `onPickTemplate` 改成**支持多文件**，逐个转换并汇总成败
"""

import os
import struct
import sys
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _png(w=200, h=300):
    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"")) + chunk(b"IEND", b""))


def _minimal_docx():
    """造一个**最小可解析**的 docx（zip + word/document.xml）。"""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '</Types>')
        z.writestr("word/document.xml",
                   '<?xml version="1.0" encoding="UTF-8"?>'
                   '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   '<w:body><w:p><w:r><w:t>简历</w:t></w:r></w:p></w:body>'
                   '</w:document>')
    return buf.getvalue()


class TestSniffFormat(unittest.TestCase):
    """**按文件头判断格式** —— 扩展名不可信。"""

    def test_sniff_docx(self):
        from template_convert import _sniff_format
        self.assertEqual(_sniff_format(_minimal_docx()), "docx")

    def test_sniff_ole2_is_real_doc(self):
        """OLE2 = **真正的旧版 .doc**（Word 97-2003）。"""
        from template_convert import _sniff_format
        self.assertEqual(_sniff_format(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100),
                         "ole2")

    def test_sniff_others(self):
        from template_convert import _sniff_format
        self.assertEqual(_sniff_format(b"%PDF-1.4 ..."), "pdf")
        self.assertEqual(_sniff_format(_png()), "png")
        self.assertEqual(_sniff_format(b"\xff\xd8\xff\xe0" + b"\x00" * 40), "jpeg")
        self.assertEqual(_sniff_format(b"GIF89a" + b"\x00" * 40), "gif")
        self.assertEqual(_sniff_format(b""), None)
        self.assertEqual(_sniff_format(b"random junk"), None)


class TestConvertIgnoresWrongExtension(unittest.TestCase):
    """**扩展名错但内容对** —— 要按内容走。"""

    def test_doc_extension_with_docx_content(self):
        """**用户的真实文件**：叫 .doc，内容是 docx。"""
        from template_convert import convert
        out = convert("后端开发.doc", _minimal_docx())
        self.assertTrue(out.get("ok"),
                        "`.doc` 里装 docx 应该能转，实际：%s" % out.get("error"))

    def test_real_ole2_doc_gives_clear_message(self):
        """**真正的旧版 .doc** → 要说清楚怎么改，别只说「不支持」。"""
        from template_convert import convert
        out = convert("老简历.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)
        self.assertFalse(out.get("ok"))
        err = out.get("error") or ""
        self.assertIn("另存为", err, "错误提示要告诉用户怎么改：%s" % err)
        self.assertIn(".docx", err)

    def test_pdf_extension_with_png_content(self):
        """扩展名说 pdf、内容是 PNG → 信内容。"""
        from template_convert import convert
        out = convert("fake.pdf", _png(200, 300))
        self.assertTrue(out.get("ok"))

    def test_doc_is_in_supported(self):
        """`.doc` 要在支持列表里 —— 前端 accept 才能对上。"""
        from template_convert import SUPPORTED
        self.assertIn("doc", SUPPORTED)
        self.assertIn("docx", SUPPORTED)


class TestDesktopFolderUpload(unittest.TestCase):
    """前端：**选文件夹**要带 webkitdirectory 的独立 input。"""

    def _plugin_js(self):
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(os.path.dirname(here), "desktop", "plugin.js")
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_accept_includes_doc(self):
        """`accept` 里有 `.doc` —— 否则文件选择框里根本选不到。"""
        src = self._plugin_js()
        self.assertIn(".docx,.doc,.pdf", src.replace("'", '"').replace("'", '"'),
                      "accept 里没有 .doc")

    def test_has_webkitdirectory_input(self):
        """**必须有 webkitdirectory** —— 普通 input 选文件夹会报错。"""
        src = self._plugin_js()
        self.assertIn("webkitdirectory", src,
                      "没有 webkitdirectory → 选文件夹浏览器直接报错")

    def test_directory_input_has_no_accept(self):
        """**目录 input 不能带 accept** —— 带了会把文件全过滤掉。"""
        src = self._plugin_js()
        i = src.find("webkitdirectory")
        self.assertGreater(i, 0)
        # 往后看 600 字符（那个 input 块）
        block = src[i:i + 600]
        j = block.find("type: 'file'")
        k = block.find("accept:")
        if j >= 0:
            seg = block[j:j + 300]
            self.assertNotIn("accept:", seg,
                             "目录 input 带了 accept → 选目录时文件会被全过滤")

    def test_onpicktemplate_supports_multiple_files(self):
        """`onPickTemplate` 要处理**多个**文件。"""
        src = self._plugin_js()
        self.assertIn("Array.from((e.target.files) || [])", src,
                      "onPickTemplate 没做多文件处理")

    def test_folder_button_exists(self):
        """要有「上传文件夹」入口。"""
        src = self._plugin_js()
        self.assertIn("uploadDirRef", src)
        self.assertIn("上传文件夹", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
