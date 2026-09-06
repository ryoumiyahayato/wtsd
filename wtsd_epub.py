"""EPUB 3 renderer and archive writer."""
from __future__ import annotations
import hashlib
import html
import mimetypes
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from wtsd_common import *

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
    creator = f"    <dc:creator>{xml(book.author)}</dc:creator>\n" if book.author else ""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="{EPUB_NS}" unique-identifier="book-id" version="3.0" xml:lang="{xml(book.language)}">
  <metadata xmlns:dc="{DC_NS}">
    <dc:identifier id="book-id">{xml(book.identifier)}</dc:identifier>
    <dc:title>{xml(book.title)}</dc:title>
{creator}    <dc:language>{xml(book.language)}</dc:language>
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
