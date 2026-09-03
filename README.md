# WTSD Studio

WTSD Studio converts existing manuscripts into self-contained EPUB 3 files with as little preprocessing as possible.

The default workflow is now **import first**, not “write metadata as code”:

1. choose an existing TXT, Markdown, DOCX, HTML, or WTSD file;
2. WTSD Studio automatically detects the likely title, author, language, and chapter structure;
3. review or override the detected metadata in ordinary GUI fields;
4. export EPUB.

The optional WTSD directives still exist for cases that need explicit image placement or fine structural control, but they are no longer required for normal conversion.

No third-party Python packages are required.

## Fastest path

For a normal text manuscript such as:

```text
作者：林某

第一章 雪夜
雪开始下了。

第二章 清晨
天亮了。
```

save it as `雪降之时.txt`, then either use **快速转换** in the desktop app or run:

```bash
python txt2epub.py 雪降之时.txt
```

The default output is `雪降之时.epub`. No `@title`, `@author`, or `@language` lines are necessary.

## Visual desktop app

Python 3.10+ with Tkinter is required.

```bash
python wtsd_gui.py
```

On Windows you can also double-click `wtsd_gui.pyw`.

The main interface provides:

- **导入文件** — import TXT / Markdown / DOCX / HTML / WTSD;
- **快速转换** — choose a source file and immediately create an EPUB beside it;
- editable **书名 / 作者 / 语言** fields populated by automatic recognition;
- live chapter outline;
- **重新识别** after editing the source;
- **插入图片** for explicit local image placement;
- **导出 EPUB** with a chosen output path;
- ordinary text editing without requiring WTSD syntax.

A file can also be passed when launching the GUI:

```bash
python wtsd_gui.py manuscript.docx
```

## Automatic recognition

Recognition intentionally differs by source format because plain text does not contain typography information.

### TXT / Markdown

WTSD Studio uses, in priority order:

- explicit `书名：...` / `标题：...` / `Title: ...` lines when present;
- the source filename as the normal title fallback;
- `作者：...`, `著：...`, `Author: ...`, or `By ...` patterns near the beginning;
- language inference from Unicode character distribution instead of assuming Chinese;
- ordinary chapter patterns such as `第一章`, `第三卷`, `序章`, `后记`, `Chapter 2`, `Part IV`, and similar lines;
- Markdown `# / ## / ###` headings when present.

If no author can be identified, the author is left empty. The EPUB does not invent an `Unknown` creator.

### DOCX

DOCX import additionally reads information that TXT simply does not have:

- filename and DOCX core metadata for title hints;
- DOCX creator metadata for the author, with obvious generated/tool identities rejected;
- `Heading 1 / Heading 2 / Heading 3` (including localized `标题`) paragraph styles;
- a conservative font-size fallback when meaningful heading styles are absent;
- DOCX language metadata when available, otherwise text-based language inference.

The imported Word text is normalized into editable plain text. Heading styles become lightweight Markdown-style heading hints internally so the EPUB builder can preserve structure without requiring the original document to contain WTSD code.

### HTML

HTML `<title>`, author metadata, document language, and H1/H2/H3 structure are used when available.

## Command line

One-shot conversion:

```bash
python txt2epub.py manuscript.txt
python txt2epub.py manuscript.docx output.epub
```

Manual metadata overrides are optional:

```bash
python txt2epub.py manuscript.txt output.epub \
  --title "Book title" \
  --author "Author name" \
  --language zh-CN
```

Supported source formats:

- `.txt`
- `.md`, `.markdown`
- `.docx`
- `.html`, `.htm`
- `.wtsd`

## Optional advanced WTSD directives

These are retained for explicit control and image insertion. They are not prerequisites for importing a normal manuscript.

```text
@cover "assets/cover.jpg" alt="封面"
@image "assets/scene.png" alt="雪中的车站" caption="冬夜" width=80%
@chapter 强制章节标题
@h2 小节标题
@h3 三级标题
@pagebreak
```

Metadata directives such as `@title`, `@author`, and `@language` remain backward compatible, but the GUI no longer expects users to type them.

Unknown lines beginning with `@` are treated as ordinary text for normal TXT/Markdown imports. `.wtsd` files retain strict directive checking.

Supported embedded image types: JPEG, PNG, GIF, SVG, and WebP.

## EPUB output

Generated EPUBs include:

- EPUB 3 package metadata;
- navigation document;
- chapter XHTML;
- CSS;
- local referenced images embedded in the archive;
- optional creator metadata only when an author is actually known.

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests cover:

- legacy WTSD directive compatibility;
- zero-directive TXT conversion;
- automatic title/author/language/chapter detection;
- non-fixed language detection;
- DOCX metadata and Heading-style import;
- optional metadata overrides;
- EPUB packaging and embedded images.

## Requirements

- Python 3.10+
- Tkinter only for the desktop GUI
- no third-party Python packages
