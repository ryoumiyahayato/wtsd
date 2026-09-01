# WTSD Studio

WTSD Studio lets you write a book as a plain UTF-8 text file and export it as a self-contained EPUB 3 with embedded images.

It includes two interfaces:

- **Visual desktop editor** (`wtsd_gui.py`) — edit source, inspect chapter/image structure live, insert images, and export EPUB from one window.
- **Command-line converter** (`txt2epub.py`) — convenient for scripts, automation, and version-controlled writing workflows.

No third-party Python packages are required.

## Visual editor

Python 3.10+ with Tkinter is required. Tkinter ships with the normal Windows/macOS Python installers and many Linux Python packages.

```bash
python wtsd_gui.py
```

On Windows you can also double-click `wtsd_gui.pyw` to launch without a console window.

The editor provides:

- WTSD/TXT open, save, and save-as
- live syntax validation
- chapter outline preview
- image reference validation
- portable image insertion into a local `assets/` folder for saved documents
- one-click EPUB export
- line numbers and directive highlighting
- common shortcuts: `Ctrl+N`, `Ctrl+O`, `Ctrl+S`, `Ctrl+Shift+S`, `Ctrl+E`

## Command line

```bash
python txt2epub.py examples/book.wtsd output.epub
```

The source is ordinary UTF-8 text. Each non-directive line is one paragraph. Directives begin with `@`.

```text
@title 雪降之时
@author 作者名
@language zh-CN
@cover "assets/cover.jpg" alt="封面"

@chapter 第一章
这是第一段。
这是第二段。

@image "assets/scene.png" alt="雪中的车站" caption="冬夜" width=80%

@h2 小节
正文继续。
@pagebreak
下一页开始。
```

### Directives

- `@title TEXT` — book title
- `@author TEXT` — author
- `@language CODE` — language such as `zh-CN`, `ja`, `en`
- `@identifier TEXT` — optional EPUB identifier; a UUID is generated when omitted
- `@cover PATH [alt=...]` — embedded cover image
- `@chapter TEXT` — starts a chapter
- `@h2 TEXT`, `@h3 TEXT` — subheadings
- `@image PATH [alt=...] [caption=...] [width=80%]` — embeds an image in the current chapter
- `@pagebreak` — forces a page break in readers that honor CSS paged-media rules
- `@@TEXT` — escape a literal paragraph that must begin with `@`

Paths are resolved relative to the source file (or the visual editor's current document directory). Spaces are supported when the path/value is quoted.

Supported image types: JPEG, PNG, GIF, SVG, WebP. For the widest reader compatibility, prefer JPEG/PNG.

## Why this format

The source remains diff-friendly and editable like code, while the generated EPUB packages XHTML, CSS, navigation metadata, cover art, and referenced images into one self-contained file. Images are embedded in the EPUB rather than referenced through external URLs.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Requirements

- Python 3.10+
- Tkinter for the visual editor
- no third-party packages
