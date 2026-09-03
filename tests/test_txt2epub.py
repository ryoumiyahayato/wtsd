import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt2epub import (
    WTSDError,
    build_epub,
    build_epub_from_text,
    infer_language,
    parse_text,
    read_source,
)


class Txt2EpubTest(unittest.TestCase):
    def test_builds_epub_and_embeds_image(self):
        root = Path(__file__).resolve().parents[1]
        source = root / "examples" / "book.wtsd"
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "book.epub"
            build_epub(source, out)
            self.assertTrue(out.is_file())
            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
                self.assertEqual(names[0], "mimetype")
                self.assertEqual(zf.read("mimetype"), b"application/epub+zip")
                self.assertIn("META-INF/container.xml", names)
                self.assertIn("EPUB/content.opf", names)
                self.assertIn("EPUB/nav.xhtml", names)
                self.assertIn("EPUB/text/chapter-001.xhtml", names)
                self.assertTrue(any(name.startswith("EPUB/images/") for name in names))

    def test_directives_still_work_in_memory(self):
        book = parse_text("@title Demo\n@author A\n@chapter A\nhello", ".")
        self.assertEqual(book.title, "Demo")
        self.assertEqual(book.author, "A")
        self.assertEqual(book.chapters[0].title, "A")
        self.assertEqual(book.chapters[0].blocks[0].text, "hello")

    def test_plain_txt_needs_no_directives(self):
        text = "作者：林某\n\n第一章 雪夜\n雪开始下了。\n\n第二章 清晨\n天亮了。"
        book = parse_text(text, ".", source_name="雪降之时.txt")
        self.assertEqual(book.title, "雪降之时")
        self.assertEqual(book.author, "林某")
        self.assertEqual(book.language, "zh-CN")
        self.assertEqual([c.title for c in book.chapters], ["第一章 雪夜", "第二章 清晨"])

    def test_unknown_at_line_is_plain_text_by_default(self):
        book = parse_text("第一章\n@someone 这是一句正文", ".", source_name="demo.txt")
        self.assertEqual(book.chapters[0].blocks[0].text, "@someone 这是一句正文")
        with self.assertRaises(WTSDError):
            parse_text("@unknown x", ".", strict_directives=True)

    def test_language_is_detected_not_fixed(self):
        self.assertEqual(infer_language("This is an English manuscript with enough ordinary words to classify it."), "en")
        self.assertEqual(infer_language("これは日本語の文章です。ひらがなとカタカナを含んでいます。テスト文章です。"), "ja")

    def test_plain_file_one_shot_build(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "普通小说.txt"
            source.write_text("第一章\n这是一段不含任何 WTSD 元数据的正文。这里再补充一些中文字符用于语言识别。", encoding="utf-8")
            out = source.with_suffix(".epub")
            build_epub(source, out)
            self.assertTrue(out.exists())
            with zipfile.ZipFile(out) as zf:
                opf = zf.read("EPUB/content.opf").decode("utf-8")
                self.assertIn("<dc:title>普通小说</dc:title>", opf)
                self.assertIn("<dc:language>zh-CN</dc:language>", opf)
                self.assertNotIn("<dc:creator>", opf)

    def test_docx_import_uses_metadata_and_heading_styles(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "document.docx"
            self._write_minimal_docx(path)
            imported = read_source(path)
            self.assertEqual(imported.source_format, "DOCX")
            self.assertEqual(imported.title, "示例书名")
            self.assertEqual(imported.author, "Jane Doe")
            self.assertIn("# 第一章", imported.text)
            self.assertIn("## 第一节", imported.text)
            book = parse_text(
                imported.text,
                imported.base_dir,
                title=imported.title,
                author=imported.author,
                language=imported.language,
                source_name=path.name,
            )
            self.assertEqual(book.chapters[0].title, "第一章")
            self.assertEqual(book.chapters[0].blocks[0].kind, "h2")

    def test_in_memory_build_accepts_metadata_overrides(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "gui.epub"
            build_epub_from_text(
                "第一章\nhello world this is enough English text for a small test manuscript.",
                td,
                out,
                title="Manual Title",
                author="Manual Author",
                language="en",
                source_name="input.txt",
            )
            with zipfile.ZipFile(out) as zf:
                opf = zf.read("EPUB/content.opf").decode("utf-8")
                self.assertIn("Manual Title", opf)
                self.assertIn("Manual Author", opf)
                self.assertIn("<dc:language>en</dc:language>", opf)

    @staticmethod
    def _write_minimal_docx(path: Path) -> None:
        document = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>第一章</w:t></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>第一节</w:t></w:r></w:p>
<w:p><w:r><w:t>这是一段普通中文正文，用于验证自动语言识别和 DOCX 导入。</w:t></w:r></w:p>
</w:body></w:document>'''
        styles = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/></w:style>
</w:styles>'''
        core = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>示例书名</dc:title><dc:creator>Jane Doe</dc:creator><dc:language>zh-CN</dc:language>
</cp:coreProperties>'''
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("word/document.xml", document)
            zf.writestr("word/styles.xml", styles)
            zf.writestr("docProps/core.xml", core)


if __name__ == "__main__":
    unittest.main()
