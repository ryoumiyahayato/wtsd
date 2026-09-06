"""Automatic manuscript parser plus optional WTSD directives."""
from __future__ import annotations
import uuid
from pathlib import Path
from wtsd_common import *
from wtsd_importers import read_source

def _handle_directive(book: Book, current: Chapter | None, base: Path, line_no: int, name: str, arg: str) -> Chapter | None:
    if name in {"title", "author", "language", "identifier"}:
        if not arg:
            fail(f"line {line_no}: @{name} requires a value")
        setattr(book, name, arg)
        return current
    if name == "cover":
        path_text, options = parse_kv_tokens(arg, name)
        unknown = set(options) - {"alt", "caption"}
        if unknown:
            fail(f"line {line_no}: unknown @cover option(s): {', '.join(sorted(unknown))}")
        image = ImageRef(source=(base / path_text).resolve(), alt=options.get("alt", "Cover"), caption=options.get("caption", ""))
        book.cover = image
        book.images.append(image)
        return current
    if name == "chapter":
        if not arg:
            fail(f"line {line_no}: @chapter requires a title")
        current = Chapter(arg)
        book.chapters.append(current)
        return current
    if current is None:
        current = Chapter("正文")
        book.chapters.append(current)
    if name in {"h2", "h3"}:
        if not arg:
            fail(f"line {line_no}: @{name} requires text")
        current.blocks.append(Block(name, text=arg))
        return current
    if name == "image":
        path_text, options = parse_kv_tokens(arg, name)
        unknown = set(options) - {"alt", "caption", "width"}
        if unknown:
            fail(f"line {line_no}: unknown @image option(s): {', '.join(sorted(unknown))}")
        image = ImageRef(source=(base / path_text).resolve(), alt=options.get("alt", ""), caption=options.get("caption", ""), width=normalized_width(options.get("width")))
        book.images.append(image)
        current.blocks.append(Block("image", image=image))
        return current
    if name == "pagebreak":
        current.blocks.append(Block("pagebreak"))
        return current
    fail(f"line {line_no}: unknown directive @{name}")


def parse_text(
    text: str,
    base_dir: Path | str = ".",
    *,
    title: str | None = None,
    author: str | None = None,
    language: str | None = None,
    source_name: Path | str | None = None,
    strict_directives: bool = False,
) -> Book:
    """Parse ordinary text plus optional WTSD/Markdown structure from memory."""
    base = Path(base_dir).expanduser().resolve()
    inferred_title, inferred_author, inferred_language, consumed = infer_metadata(text, source_name)
    book = Book(title=inferred_title, author=inferred_author, language=inferred_language)
    current: Chapter | None = None
    known_directives = {"title", "author", "language", "identifier", "cover", "chapter", "h2", "h3", "image", "pagebreak"}

    for index, original in enumerate(text.splitlines()):
        line_no = index + 1
        line = original.strip()
        if not line or index in consumed:
            continue

        if line.startswith("@@"):
            line = line[1:]
        elif line.startswith("@"):
            name, _, arg = line[1:].partition(" ")
            name = name.lower().strip()
            arg = arg.strip()
            if name in known_directives:
                current = _handle_directive(book, current, base, line_no, name, arg)
                continue
            if strict_directives:
                fail(f"line {line_no}: unknown directive @{name}")

        if line.startswith("### "):
            if current is None:
                current = Chapter("正文")
                book.chapters.append(current)
            current.blocks.append(Block("h3", text=line[4:].strip()))
            continue
        if line.startswith("## "):
            if current is None:
                current = Chapter("正文")
                book.chapters.append(current)
            current.blocks.append(Block("h2", text=line[3:].strip()))
            continue
        if line.startswith("# "):
            current = Chapter(line[2:].strip() or "正文")
            book.chapters.append(current)
            continue
        if is_chapter_heading(line):
            current = Chapter(line)
            book.chapters.append(current)
            continue
        if is_section_heading(line) and current is not None:
            current.blocks.append(Block("h2", text=line))
            continue

        if current is None:
            current = Chapter("正文")
            book.chapters.append(current)
        current.blocks.append(Block("p", text=line))

    if not book.chapters:
        book.chapters.append(Chapter("正文"))
    if title is not None:
        book.title = title.strip() or inferred_title
    if author is not None:
        book.author = author.strip()
    if language is not None:
        book.language = language.strip() or inferred_language or "und"
    if not book.title:
        book.title = "Untitled"
    if not book.language:
        book.language = "und"
    if not book.identifier:
        book.identifier = f"urn:uuid:{uuid.uuid4()}"
    return book


def parse_source(source: Path | str) -> Book:
    imported = read_source(source)
    return parse_text(
        imported.text,
        imported.base_dir,
        title=imported.title or None,
        author=imported.author or None,
        language=imported.language or None,
        source_name=imported.path.name,
        strict_directives=imported.path.suffix.lower() == ".wtsd",
    )
