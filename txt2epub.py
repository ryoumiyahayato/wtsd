#!/usr/bin/env python3
"""Import-first TXT/Markdown/HTML/DOCX/WTSD to EPUB 3 converter."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from wtsd_common import WTSDError, infer_language, infer_metadata, is_chapter_heading
from wtsd_importers import SourceDocument, read_source
from wtsd_parser import parse_source, parse_text
from wtsd_epub import write_epub


def build_epub(source: Path | str, output: Path | str) -> Path:
    return write_epub(parse_source(source), Path(output))


def build_epub_from_text(
    text: str,
    base_dir: Path | str,
    output: Path | str,
    *,
    title: str | None = None,
    author: str | None = None,
    language: str | None = None,
    source_name: Path | str | None = None,
) -> Path:
    return write_epub(
        parse_text(
            text,
            base_dir,
            title=title,
            author=author,
            language=language,
            source_name=source_name,
        ),
        Path(output),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert TXT/Markdown/HTML/DOCX/WTSD to EPUB 3")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", nargs="?", type=Path)
    parser.add_argument("--title")
    parser.add_argument("--author")
    parser.add_argument("--language")
    args = parser.parse_args(argv)
    output = args.output or args.source.with_suffix(".epub")
    if output.suffix.lower() != ".epub":
        parser.error("output file must end in .epub")
    try:
        imported = read_source(args.source)
        book = parse_text(
            imported.text,
            imported.base_dir,
            title=args.title if args.title is not None else (imported.title or None),
            author=args.author if args.author is not None else (imported.author or None),
            language=args.language if args.language is not None else (imported.language or None),
            source_name=imported.path.name,
            strict_directives=imported.path.suffix.lower() == ".wtsd",
        )
        write_epub(book, output)
    except (WTSDError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
