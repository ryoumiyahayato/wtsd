#!/usr/bin/env python3
"""Convert WTSD text DSL (.wtsd/.txt) into a self-contained EPUB 3 file.

The module also exposes in-memory parsing/building helpers used by the GUI.
No third-party dependencies are required.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import mimetypes
import re
import shlex
import sys
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


EPUB_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
DEFAULT_CSS = """html { writing-mode: horizontal-tb; }
body { margin: 5%; line-height: 1.75; font-family: serif; }
h1, h2, h3 { line-height: 1.3; }
p { margin: 0 0 0.9em 0; text-indent: 2em; }
figure { margin: 1.5em auto; text-align: center; }
figure img { max-width: 100%; height: auto; }
figcaption { margin-top: 0.5em; font-size: 0.9em; opacity: 0.8; }
.pagebreak { break-before: page; page-break-before: always; }
.cover { margin: 0; padding: 0; text-align: center; }
.cover img { max-width: 100%; max-height: 100vh; }
"""


class WTSDError(Exception):
    """User-facing syntax, asset, or build error."""


@dataclass
class ImageRef:
    source: Path
    alt: str = ""
    caption: str = ""
    width: str | None = None
    target: str = ""
    manifest_id: str = ""
    media_type: str = ""


@dataclass
class Block:
    kind: str
    text: str = ""
    image: ImageRef | None = None


@dataclass
class Chapter:
    title: str
    blocks: list[Block] = field(default_factory=list)
    file_name: str = ""
    manifest_id: str = ""


@dataclass
class Book:
    title: str = "Untitled"
    author: str = "Unknown"
    language: str = "zh-CN"
    identifier: str = ""
    cover: ImageRef | None = None
    chapters: list[Chapter] = field(default_factory=list)
    images: list[ImageRef] = field(default_factory=list)


def fail(message: str) -> "NoReturn":
    raise WTSDError(message)


def parse_kv_tokens(raw: str, directive: str) -> tuple[str, dict[str, str]]:
    try:
        tokens = shlex.split(raw, posix=True)
    except ValueError as exc:
        fail(f"invalid @{directive} syntax: {exc}")
    if not tokens:
        fail(f"@{directive} requires a path")
    path = tokens[0]
    options: dict[str, str] = {}
    for token in tokens[1:]:
        if "=" not in token:
            fail(f"@{directive} option must use key=value: {token}")
        key, value = token.split("=", 1)
        options[key.lower()] = value
    return path, options


def normalized_width(value: str | None) -> str | None:
    if value is None:
        return None
    if re.fullmatch(r"(?:100|[1-9]?\d)%", value):
        return value
    if re.fullmatch(r"\d+(?:\.\d+)?(?:px|em|rem|vw|vh)", value):
        return value
    fail(f"unsupported image width: {value!r}; use e.g. 80%, 480px, 32em")


def parse_text(text: str, base_dir: Path | str = ".") -> Book:
    """Parse WTSD source from memory.

    Image paths are resolved relative to ``base_dir``. Parsing validates syntax but
    deliberately does not require referenced images to exist; export performs that
    validation so editors can preview partially written documents.
    """
    base = Path(base_dir).expanduser().resolve()
    book = Book()
    current: Chapter | None = None

    for line_no, original in enumerate(text.splitlines(), 1):
        line = original.strip()
        if not line:
            continue

        if line.startswith("@@"):
            line = line[1:]
        elif line.startswith("@"):
            name, _, arg = line[1:].partition(" ")
            name = name.lower().strip()
            arg = arg.strip()

            if name in {"title", "author", "language", "identifier"}:
                if not arg:
                    fail(f"line {line_no}: @{name} requires a value")
                setattr(book, name, arg)
                continue

            if name == "cover":
                path_text, options = parse_kv_tokens(arg, name)
                unknown = set(options) - {"alt", "caption"}
                if unknown:
                    fail(f"line {line_no}: unknown @cover option(s): {', '.join(sorted(unknown))}")
                image = ImageRef(
                    source=(base / path_text).resolve(),
                    alt=options.get("alt", "Cover"),
                    caption=options.get("caption", ""),
                )
                book.cover = image
                book.images.append(image)
                continue

            if name == "chapter":
                if not arg:
                    fail(f"line {line_no}: @chapter requires a title")
                current = Chapter(arg)
                book.chapters.append(current)
                continue

            if current is None:
                current = Chapter("正文")
                book.chapters.append(current)

            if name in {"h2", "h3"}:
                if not arg:
                    fail(f"line {line_no}: @{name} requires text")
                current.blocks.append(Block(name, text=arg))
                continue

            if name == "image":
                path_text, options = parse_kv_tokens(arg, name)
                unknown = set(options) - {"alt", "caption", "width"}
                if unknown:
                    fail(f"line {line_no}: unknown @image option(s): {', '.join(sorted(unknown))}")
                image = ImageRef(
                    source=(base / path_text).resolve(),
                    alt=options.get("alt", ""),
                    caption=options.get("caption", ""),
                    width=normalized_width(options.get("width")),
                )
                book.images.append(image)
                current.blocks.append(Block("image", image=image))
                continue

            if name == "pagebreak":
                current.blocks.append(Block("pagebreak"))
                continue

            fail(f"line {line_no}: unknown directive @{name}")

        if current is None:
            current = Chapter("正文")
            book.chapters.append(current)
        current.blocks.append(Block("p", text=line))

    if not book.chapters:
        book.chapters.append(Chapter("正文"))
    if not book.identifier:
        book.identifier = f"urn:uuid:{uuid.uuid4()}"
    return book


def parse_source(source: Path) -> Book:
    source = Path(source)
    if not source.is_file():
        fail(f"source file not found: {source}")
    return parse_text(source.read_text(encoding="utf-8-sig"), source.parent)


def guess_media_type(path: Path) -> str:
    media_type, _ = mimetypes.guess_type(path.name)
    aliases = {"image/jpg": "image/jpeg"}
    media_type = aliases.get(media_type or "", media_type or "")
    if media_type not in {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/svg+xml",
        "image/webp",
    }:
        fail(f"unsupported image format for {path.name}: {media_type or 'unknown'}")
    return media_type


def prepare_assets(book: Book) -> None:
    seen: dict[Path, ImageRef] = {}
    next_index = 1
    for image in book.images:
        if not image.source.is_file():
            fail(f"image not found: {image.source}")
        resolved = image.source.resolve()
        if resolved in seen:
            existing = seen[resolved]
            image.target = existing.target
            image.manifest_id = existing.manifest_id
            image.media_type = existing.media_type
            continue
        ext = image.source.suffix.lower()
        digest = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:8]
        image.target = f"images/img-{next_index:03d}-{digest}{ext}"
        image.manifest_id = f"img{next_index}"
        image.media_type = guess_media_type(image.source)
        seen[resolved] = image
        next_index += 1

    for idx, chapter in enumerate(book.chapters, 1):
        chapter.file_name = f"text/chapter-{idx:03d}.xhtml"
        chapter.manifest_id = f"chapter{idx}"


def xml(text: str) -> str:
    return html.escape(text, quote=True)


def render_chapter(chapter: Chapter, book_title: str, language: str) -> str:
    body: list[str] = [f"<h1>{xml(chapter.title)}</h1>"]
    for block in chapter.blocks:
        if block.kind == "p":
            body.append(f"<p>{xml(block.text)}</p>")
        elif block.kind in {"h2", "h3"}:
            body.append(f"<{block.kind}>{xml(block.text)}</{block.kind}>")
        elif block.kind == "pagebreak":
            body.append('<div class="pagebreak" aria-hidden="true"></div>')
        elif block.kind == "image" and block.image:
            image = block.image
            style = f' style="width:{xml(image.width)}"' if image.width else ""
            caption = f"<figcaption>{xml(image.caption)}</figcaption>" if image.caption else ""
            body.append(
                f'<figure><img src="../{xml(image.target)}" alt="{xml(image.alt)}"{style}/>{caption}</figure>'
            )

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{xml(language)}" lang="{xml(language)}">
<head>
  <meta charset="utf-8"/>
  <title>{xml(chapter.title)} — {xml(book_title)}</title>
  <link rel="stylesheet" type="text/css" href="../style.css"/>
</head>
<body>
{chr(10).join(body)}
</body>
</html>
'''


def render_nav(book: Book, include_cover: bool) -> str:
    items = []
    if include_cover:
        items.append('<li><a href="cover.xhtml">封面</a></li>')
    for chapter in book.chapters:
        items.append(f'<li><a href="{xml(chapter.file_name)}">{xml(chapter.title)}</a></li>')
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{xml(book.language)}" lang="{xml(book.language)}">
<head><meta charset="utf-8"/><title>目录</title></head>
<body>
<nav epub:type="toc" id="toc">
  <h1>目录</h1>
  <ol>{''.join(items)}</ol>
</nav>
</body>
</html>
'''


def render_cover_xhtml(book: Book) -> str:
    assert book.cover is not None
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{xml(book.language)}" lang="{xml(book.language)}">
<head><meta charset="utf-8"/><title>封面</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body class="cover"><img src="{xml(book.cover.target)}" alt="{xml(book.cover.alt)}"/></body>
</html>
'''


def unique_images(images: Iterable[ImageRef]) -> list[ImageRef]:
    result: list[ImageRef] = []
    seen: set[str] = set()
    for image in images:
        if image.target not in seen:
            result.append(image)
            seen.add(image.target)
    return result


def render_opf(book: Book) -> str:
    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
    ]
    spine = []

    if book.cover:
        manifest.append('<item id="coverpage" href="cover.xhtml" media-type="application/xhtml+xml"/>')
        spine.append('<itemref idref="coverpage"/>')

    for chapter in book.chapters:
        manifest.append(
            f'<item id="{chapter.manifest_id}" href="{xml(chapter.file_name)}" media-type="application/xhtml+xml"/>'
        )
        spine.append(f'<itemref idref="{chapter.manifest_id}"/>')

    for image in unique_images(book.images):
        properties = ' properties="cover-image"' if book.cover and image.target == book.cover.target else ""
        manifest.append(
            f'<item id="{image.manifest_id}" href="{xml(image.target)}" media-type="{xml(image.media_type)}"{properties}/>'
        )

    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="{EPUB_NS}" unique-identifier="book-id" version="3.0" xml:lang="{xml(book.language)}">
  <metadata xmlns:dc="{DC_NS}">
    <dc:identifier id="book-id">{xml(book.identifier)}</dc:identifier>
    <dc:title>{xml(book.title)}</dc:title>
    <dc:creator>{xml(book.author)}</dc:creator>
    <dc:language>{xml(book.language)}</dc:language>
    <meta property="dcterms:modified">{modified}</meta>
  </metadata>
  <manifest>{''.join(manifest)}</manifest>
  <spine>{''.join(spine)}</spine>
</package>
'''


def write_epub(book: Book, output: Path) -> Path:
    prepare_assets(book)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output, "w") as zf:
        # EPUB requires mimetype to be the first entry and stored without compression.
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER_XML, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("EPUB/style.css", DEFAULT_CSS, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("EPUB/nav.xhtml", render_nav(book, bool(book.cover)), compress_type=zipfile.ZIP_DEFLATED)
        if book.cover:
            zf.writestr("EPUB/cover.xhtml", render_cover_xhtml(book), compress_type=zipfile.ZIP_DEFLATED)
        for chapter in book.chapters:
            zf.writestr(
                f"EPUB/{chapter.file_name}",
                render_chapter(chapter, book.title, book.language),
                compress_type=zipfile.ZIP_DEFLATED,
            )
        zf.writestr("EPUB/content.opf", render_opf(book), compress_type=zipfile.ZIP_DEFLATED)
        for image in unique_images(book.images):
            zf.write(image.source, f"EPUB/{image.target}", compress_type=zipfile.ZIP_DEFLATED)
    return output


def build_epub(source: Path, output: Path) -> Path:
    return write_epub(parse_source(Path(source)), Path(output))


def build_epub_from_text(text: str, base_dir: Path | str, output: Path) -> Path:
    """Build an EPUB from editor text without requiring a saved source file."""
    return write_epub(parse_text(text, base_dir), Path(output))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert WTSD text DSL to EPUB 3")
    parser.add_argument("source", type=Path, help="input .wtsd or .txt file")
    parser.add_argument("output", nargs="?", type=Path, help="output .epub path")
    args = parser.parse_args(argv)
    output = args.output or args.source.with_suffix(".epub")
    if output.suffix.lower() != ".epub":
        parser.error("output file must end in .epub")
    try:
        build_epub(args.source, output)
    except WTSDError as exc:
        parser.exit(2, f"error: {exc}\n")
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
