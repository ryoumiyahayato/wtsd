"""Shared WTSD data model and text inference helpers."""
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
import statistics
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, NoReturn


EPUB_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CORE_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC_META_NS = "http://purl.org/dc/elements/1.1/"
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

SUPPORTED_SOURCE_SUFFIXES = {".wtsd", ".txt", ".md", ".markdown", ".docx", ".html", ".htm"}
TEXT_ENCODINGS = ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "gb18030")
GENERIC_FILE_STEMS = {"untitled", "document", "new", "book", "novel", "text", "文件", "文档", "新建文档", "未命名"}
GENERIC_CREATORS = {"microsoft office user", "wps office", "user", "unknown", "作者名"}

CHAPTER_RE = re.compile(
    r"^(?:"
    r"第[0-9〇零一二三四五六七八九十百千万两]+[卷章回节篇部幕](?:[：:、.\-— ]?.*)?"
    r"|序章|楔子|引子|终章|尾声|后记|番外|前言|序言"
    r"|(?:chapter|part|book|volume)\s+[0-9ivxlcdm]+(?:\b.*)?"
    r"|(?:the\s+)?(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+chapter\b.*"
    r")$",
    re.IGNORECASE,
)
SECTION_RE = re.compile(r"^(?:0*\d{1,3}|[一二三四五六七八九十百]+)[.、]?$", re.IGNORECASE)
TITLE_LABEL_RE = re.compile(r"^(?:书名|标题|title)\s*[：:]\s*(.+)$", re.IGNORECASE)
AUTHOR_LABEL_RE = re.compile(r"^(?:作者|著者|著|文|author|by)\s*[：:]?\s*(.+)$", re.IGNORECASE)
LANGUAGE_LABEL_RE = re.compile(r"^(?:语言|language)\s*[：:]\s*([A-Za-z]{2,3}(?:-[A-Za-z0-9]+)*)$", re.IGNORECASE)


class WTSDError(Exception):
    """User-facing syntax, asset, import, or build error."""


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
    author: str = ""
    language: str = "und"
    identifier: str = ""
    cover: ImageRef | None = None
    chapters: list[Chapter] = field(default_factory=list)
    images: list[ImageRef] = field(default_factory=list)


@dataclass
class SourceDocument:
    """Normalized imported source plus metadata hints discovered from its format."""

    path: Path
    text: str
    base_dir: Path
    source_format: str
    title: str = ""
    author: str = ""
    language: str = ""
    notes: list[str] = field(default_factory=list)


def fail(message: str) -> NoReturn:
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


def _clean_candidate(value: str) -> str:
    value = value.strip().strip("\ufeff").strip()
    value = re.sub(r"\.(?:docx|txt|md|markdown|html?)$", "", value, flags=re.IGNORECASE).strip()
    return value


def title_from_filename(path_or_name: Path | str | None) -> str:
    if not path_or_name:
        return ""
    name = Path(str(path_or_name)).name
    stem = _clean_candidate(Path(name).stem)
    if not stem or stem.casefold() in GENERIC_FILE_STEMS:
        return ""
    stem = re.sub(r"\s*[-_—–]\s*第[0-9〇零一二三四五六七八九十百千万两]+卷\s*$", "", stem).strip()
    return stem


def infer_language(text: str) -> str:
    counts = {"cjk": 0, "kana": 0, "hangul": 0, "cyrillic": 0, "latin": 0}
    for ch in text[:200_000]:
        code = ord(ch)
        if 0x3040 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF:
            counts["kana"] += 1
        elif 0xAC00 <= code <= 0xD7AF:
            counts["hangul"] += 1
        elif 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
            counts["cjk"] += 1
        elif 0x0400 <= code <= 0x052F:
            counts["cyrillic"] += 1
        elif ("A" <= ch <= "Z") or ("a" <= ch <= "z"):
            counts["latin"] += 1
    if counts["kana"] >= 8:
        return "ja"
    if counts["hangul"] >= 8 and counts["hangul"] >= counts["cjk"] // 4:
        return "ko"
    if counts["cyrillic"] >= 20 and counts["cyrillic"] > counts["latin"]:
        return "ru"
    if counts["cjk"] >= 20:
        return "zh-CN"
    if counts["latin"] >= 20:
        return "en"
    return "und"


def is_chapter_heading(line: str) -> bool:
    value = line.strip()
    if not value or len(value) > 120:
        return False
    if value.startswith("# "):
        return True
    return bool(CHAPTER_RE.fullmatch(value))


def is_section_heading(line: str) -> bool:
    value = line.strip()
    if value.startswith("## ") or value.startswith("### "):
        return True
    return len(value) <= 16 and bool(SECTION_RE.fullmatch(value))


def infer_metadata(text: str, source_name: Path | str | None = None) -> tuple[str, str, str, set[int]]:
    """Infer title/author/language from ordinary text without requiring directives."""
    title = ""
    author = ""
    language = ""
    consumed: set[int] = set()
    lines = text.splitlines()
    first_nonblank: tuple[int, str] | None = None

    for idx, raw in enumerate(lines[:80]):
        line = raw.strip()
        if not line:
            continue
        if first_nonblank is None:
            first_nonblank = (idx, line)
        title_match = TITLE_LABEL_RE.match(line)
        if title_match and not title:
            title = _clean_candidate(title_match.group(1))
            consumed.add(idx)
            continue
        author_match = AUTHOR_LABEL_RE.match(line)
        if author_match and not author:
            candidate = author_match.group(1).strip()
            if candidate and len(candidate) <= 100:
                author = candidate
                consumed.add(idx)
            continue
        language_match = LANGUAGE_LABEL_RE.match(line)
        if language_match and not language:
            language = language_match.group(1)
            consumed.add(idx)

    if not title:
        title = title_from_filename(source_name)
    if not title and first_nonblank:
        idx, line = first_nonblank
        markdown_title = re.match(r"^#\s+(.+)$", line)
        candidate = markdown_title.group(1).strip() if markdown_title else line
        if (
            len(candidate) <= 80
            and not line.startswith("@")
            and not is_chapter_heading(candidate)
            and not AUTHOR_LABEL_RE.match(candidate)
        ):
            title = _clean_candidate(candidate)
            consumed.add(idx)
    if not language:
        language = infer_language(text)
    return title or "Untitled", author, language or "und", consumed
