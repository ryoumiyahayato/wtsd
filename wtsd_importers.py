"""Source-file importers for TXT/Markdown/DOCX/HTML."""
from __future__ import annotations
import re
import statistics
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from wtsd_common import *
from wtsd_common import _clean_candidate

def _decode_text_bytes(data: bytes, path: Path) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in TEXT_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    fail(f"cannot decode text file {path.name}; expected UTF-8/UTF-16/GB18030 ({last_error})")


def _is_generic_creator(value: str) -> bool:
    low = value.strip().casefold()
    return not low or low in GENERIC_CREATORS or "作家助手" in low or "generated" in low


def _docx_style_level(style_id: str | None, style_name: str | None) -> int | None:
    raw = f"{style_id or ''} {style_name or ''}".casefold().replace("_", " ")
    for level in range(1, 10):
        if re.search(rf"(?:heading|标题)\s*{level}\b", raw) or re.search(rf"heading{level}\b", raw):
            return level
    return None


def _read_docx_source(path: Path) -> SourceDocument:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        fail(f"cannot read DOCX {path.name}: {exc}")
    with archive:
        try:
            document_root = ET.fromstring(archive.read("word/document.xml"))
        except (KeyError, ET.ParseError) as exc:
            fail(f"invalid DOCX {path.name}: missing or malformed word/document.xml ({exc})")

        style_names: dict[str, str] = {}
        style_sizes: dict[str, float] = {}
        try:
            styles_root = ET.fromstring(archive.read("word/styles.xml"))
        except (KeyError, ET.ParseError):
            styles_root = None
        if styles_root is not None:
            for style in styles_root.findall(f"{{{W_NS}}}style"):
                sid = style.get(f"{{{W_NS}}}styleId", "")
                name_node = style.find(f"{{{W_NS}}}name")
                if name_node is not None:
                    style_names[sid] = name_node.get(f"{{{W_NS}}}val", sid)
                rpr = style.find(f"{{{W_NS}}}rPr")
                if rpr is not None:
                    size_node = rpr.find(f"{{{W_NS}}}sz")
                    if size_node is not None:
                        try:
                            style_sizes[sid] = int(size_node.get(f"{{{W_NS}}}val", "0")) / 2
                        except ValueError:
                            pass

        core_title = ""
        core_author = ""
        core_language = ""
        try:
            core = ET.fromstring(archive.read("docProps/core.xml"))
            core_title_node = core.find(f"{{{DC_META_NS}}}title")
            core_author_node = core.find(f"{{{DC_META_NS}}}creator")
            core_language_node = core.find(f"{{{DC_META_NS}}}language")
            core_title = _clean_candidate(core_title_node.text or "") if core_title_node is not None else ""
            core_author = (core_author_node.text or "").strip() if core_author_node is not None else ""
            core_language = (core_language_node.text or "").strip() if core_language_node is not None else ""
        except (KeyError, ET.ParseError):
            pass

        paragraphs: list[tuple[str, str | None, str | None, float | None]] = []
        for paragraph in document_root.iter(f"{{{W_NS}}}p"):
            value = "".join((node.text or "") for node in paragraph.iter(f"{{{W_NS}}}t")).strip()
            if not value:
                continue
            style_id: str | None = None
            ppr = paragraph.find(f"{{{W_NS}}}pPr")
            if ppr is not None:
                pstyle = ppr.find(f"{{{W_NS}}}pStyle")
                if pstyle is not None:
                    style_id = pstyle.get(f"{{{W_NS}}}val")
            direct_sizes: list[float] = []
            for run in paragraph.findall(f"{{{W_NS}}}r"):
                rpr = run.find(f"{{{W_NS}}}rPr")
                if rpr is None:
                    continue
                size = rpr.find(f"{{{W_NS}}}sz")
                if size is not None:
                    try:
                        direct_sizes.append(int(size.get(f"{{{W_NS}}}val", "0")) / 2)
                    except ValueError:
                        pass
            font_size = max(direct_sizes) if direct_sizes else style_sizes.get(style_id or "")
            paragraphs.append((value, style_id, style_names.get(style_id or ""), font_size))

    filename_title = title_from_filename(path)
    title = filename_title or core_title
    if core_title and not title:
        title = core_title
    author = "" if _is_generic_creator(core_author) else core_author

    body_sizes = [size for text, sid, sname, size in paragraphs if size and len(text) >= 20 and _docx_style_level(sid, sname) is None]
    body_median = statistics.median(body_sizes) if body_sizes else None
    candidate_large = [size for text, _sid, _sname, size in paragraphs if size and len(text) <= 100]
    max_short_size = max(candidate_large) if candidate_large else None

    normalized: list[str] = []
    notes: list[str] = []
    title_from_style = ""
    for position, (value, style_id, style_name, font_size) in enumerate(paragraphs):
        style_low = (style_name or style_id or "").casefold().strip()
        level = _docx_style_level(style_id, style_name)
        if level is None and style_low in {"title", "标题", "书名"} and len(value) <= 120:
            if not title_from_style:
                title_from_style = value.strip()
            continue
        if level == 1:
            normalized.append(f"# {value}")
            continue
        if level == 2:
            normalized.append(f"## {value}")
            continue
        if level is not None and level >= 3:
            normalized.append(f"### {value}")
            continue

        size_heading = (
            level is None
            and font_size is not None
            and max_short_size is not None
            and body_median is not None
            and font_size >= max_short_size - 0.1
            and font_size >= body_median + 2
            and len(value) <= 100
        )
        if size_heading:
            if position < 10 and not title and not title_from_style:
                title_from_style = value.strip()
                continue
            normalized.append(f"# {value}")
            continue
        normalized.append(value)

    if title_from_style:
        title = title_from_style
        notes.append("书名来自 DOCX 标题样式/字号层级")
    elif title:
        notes.append("书名来自文件名或 DOCX 元数据")
    if author:
        notes.append("作者来自 DOCX 元数据")
    notes.append("章节优先按 DOCX Heading/标题样式识别；无样式时保守参考字号层级")
    return SourceDocument(
        path=path,
        text="\n".join(normalized),
        base_dir=path.parent,
        source_format="DOCX",
        title=title,
        author=author,
        language=core_language or infer_language("\n".join(value for value, *_ in paragraphs)),
        notes=notes,
    )


class _HTMLSourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.buffer: list[str] = []
        self.lines: list[str] = []
        self.title = ""
        self.author = ""
        self.language = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        if tag == "html" and attrs_dict.get("lang"):
            self.language = attrs_dict["lang"]
        if tag == "meta" and attrs_dict.get("name", "").lower() == "author":
            self.author = attrs_dict.get("content", "").strip()
        if tag in {"title", "p", "h1", "h2", "h3", "li", "blockquote"}:
            self.stack.append(tag)
            self.buffer = []

    def handle_data(self, data: str) -> None:
        if self.stack:
            self.buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self.stack or self.stack[-1] != tag:
            return
        value = re.sub(r"\s+", " ", "".join(self.buffer)).strip()
        self.stack.pop()
        self.buffer = []
        if not value:
            return
        if tag == "title":
            self.title = value
        elif tag == "h1":
            self.lines.append(f"# {value}")
        elif tag == "h2":
            self.lines.append(f"## {value}")
        elif tag == "h3":
            self.lines.append(f"### {value}")
        else:
            self.lines.append(value)


def read_source(source: Path | str) -> SourceDocument:
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        fail(f"source file not found: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SOURCE_SUFFIXES:
        fail(f"unsupported source format: {suffix or '(none)'}")
    if suffix == ".docx":
        return _read_docx_source(path)
    data = path.read_bytes()
    text = _decode_text_bytes(data, path)
    if suffix in {".html", ".htm"}:
        parser = _HTMLSourceParser()
        try:
            parser.feed(text)
        except Exception as exc:
            fail(f"cannot parse HTML {path.name}: {exc}")
        normalized = "\n".join(parser.lines)
        return SourceDocument(
            path=path,
            text=normalized,
            base_dir=path.parent,
            source_format="HTML",
            title=_clean_candidate(parser.title) or title_from_filename(path),
            author=parser.author,
            language=parser.language or infer_language(normalized),
            notes=["标题/作者优先来自 HTML 元数据；H1/H2/H3 用作结构提示"],
        )
    fmt = "WTSD" if suffix == ".wtsd" else ("Markdown" if suffix in {".md", ".markdown"} else "TXT")
    title, author, language, _ = infer_metadata(text, path.name)
    return SourceDocument(
        path=path,
        text=text,
        base_dir=path.parent,
        source_format=fmt,
        title=title,
        author=author,
        language=language,
        notes=["普通文本通过文件名、首部字段、章节模式和字符分布自动识别"],
    )
