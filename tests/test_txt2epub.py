import tempfile
import unittest
import zipfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from txt2epub import WTSDError, build_epub, build_epub_from_text, parse_text


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
                chapter = zf.read("EPUB/text/chapter-001.xhtml").decode("utf-8")
                self.assertIn("../images/", chapter)
                self.assertIn("一张嵌入 EPUB 的示意图", chapter)

    def test_in_memory_parse_for_gui(self):
        book = parse_text("@title Demo\n@chapter A\nhello", ".")
        self.assertEqual(book.title, "Demo")
        self.assertEqual(book.chapters[0].title, "A")
        self.assertEqual(book.chapters[0].blocks[0].text, "hello")

    def test_in_memory_build_for_gui(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "examples" / "book.wtsd").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "gui.epub"
            build_epub_from_text(text, root / "examples", out)
            self.assertTrue(out.is_file())

    def test_unknown_directive_is_user_facing_error(self):
        with self.assertRaises(WTSDError):
            parse_text("@chapter A\n@unknown x", ".")


if __name__ == "__main__":
    unittest.main()
