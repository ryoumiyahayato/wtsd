#!/usr/bin/env python3
"""WTSD Studio: a dependency-free Tkinter editor for WTSD -> EPUB."""

from __future__ import annotations

import os
import shutil
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from txt2epub import WTSDError, build_epub_from_text, parse_text


APP_NAME = "WTSD Studio"
SUPPORTED_IMAGES = [("Images", "*.png *.jpg *.jpeg *.gif *.webp *.svg"), ("All files", "*.*")]
SOURCE_TYPES = [("WTSD / Text", "*.wtsd *.txt"), ("WTSD", "*.wtsd"), ("Text", "*.txt"), ("All files", "*.*")]
STARTER = """@title 新书
@author 作者名
@language zh-CN

@chapter 第一章
在这里开始正文。

@image \"assets/example.png\" alt=\"插图说明\" caption=\"可选图注\" width=80%
"""


class LineNumbers(tk.Canvas):
    def __init__(self, master: tk.Misc, text_widget: tk.Text, **kwargs):
        super().__init__(master, width=46, highlightthickness=0, **kwargs)
        self.text_widget = text_widget

    def redraw(self) -> None:
        self.delete("all")
        index = self.text_widget.index("@0,0")
        while True:
            info = self.text_widget.dlineinfo(index)
            if info is None:
                break
            y = info[1]
            line = str(index).split(".")[0]
            self.create_text(38, y, anchor="ne", text=line, fill="#7a8391", font=("TkFixedFont", 10))
            index = self.text_widget.index(f"{index}+1line")


class WTSDStudio(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1280x820")
        self.minsize(980, 640)

        self.source_path: Path | None = None
        self.base_dir = Path.cwd()
        self.modified = False
        self._parse_job: str | None = None
        self._last_parse_ok = True

        self._configure_style()
        self._build_ui()
        self._bind_shortcuts()
        self._set_text(STARTER, mark_clean=True)
        self.after(50, self._refresh_preview)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_style(self) -> None:
        self.configure(bg="#f5f7fa")
        style = ttk.Style(self)
        available = style.theme_names()
        if "clam" in available:
            style.theme_use("clam")
        style.configure("TFrame", background="#f5f7fa")
        style.configure("Surface.TFrame", background="#ffffff")
        style.configure("Toolbar.TFrame", background="#ffffff")
        style.configure("TLabel", background="#f5f7fa", foreground="#202632")
        style.configure("Surface.TLabel", background="#ffffff", foreground="#202632")
        style.configure("Muted.Surface.TLabel", background="#ffffff", foreground="#6d7684")
        style.configure("Title.Surface.TLabel", background="#ffffff", foreground="#151a22", font=("TkDefaultFont", 13, "bold"))
        style.configure("Primary.TButton", padding=(14, 7), font=("TkDefaultFont", 10, "bold"))
        style.configure("Toolbar.TButton", padding=(10, 6))
        style.configure("Treeview", rowheight=26, background="#ffffff", fieldbackground="#ffffff", borderwidth=0)
        style.configure("Treeview.Heading", font=("TkDefaultFont", 9, "bold"))

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, style="Toolbar.TFrame", padding=(12, 10))
        toolbar.pack(fill="x")

        ttk.Label(toolbar, text="WTSD Studio", style="Title.Surface.TLabel").pack(side="left", padx=(2, 18))
        for text, command in [
            ("新建", self.new_file),
            ("打开", self.open_file),
            ("保存", self.save_file),
            ("插入图片", self.insert_image),
        ]:
            ttk.Button(toolbar, text=text, command=command, style="Toolbar.TButton").pack(side="left", padx=3)
        ttk.Button(toolbar, text="导出 EPUB", command=self.export_epub, style="Primary.TButton").pack(side="right", padx=3)

        main = ttk.Panedwindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        editor_surface = ttk.Frame(main, style="Surface.TFrame", padding=0)
        inspector = ttk.Frame(main, style="Surface.TFrame", padding=14)
        main.add(editor_surface, weight=7)
        main.add(inspector, weight=3)

        editor_header = ttk.Frame(editor_surface, style="Surface.TFrame", padding=(14, 10))
        editor_header.pack(fill="x")
        ttk.Label(editor_header, text="源文本", style="Title.Surface.TLabel").pack(side="left")
        self.path_label = ttk.Label(editor_header, text="未保存", style="Muted.Surface.TLabel")
        self.path_label.pack(side="right")

        editor_body = ttk.Frame(editor_surface, style="Surface.TFrame")
        editor_body.pack(fill="both", expand=True)
        self.editor = tk.Text(
            editor_body,
            wrap="word",
            undo=True,
            autoseparators=True,
            maxundo=-1,
            relief="flat",
            borderwidth=0,
            padx=18,
            pady=14,
            bg="#fbfcfe",
            fg="#1d2430",
            insertbackground="#1d2430",
            selectbackground="#d8e8ff",
            font=("Consolas" if sys.platform.startswith("win") else "TkFixedFont", 11),
            spacing1=2,
            spacing3=4,
        )
        self.line_numbers = LineNumbers(editor_body, self.editor, bg="#f1f4f8")
        scrollbar = ttk.Scrollbar(editor_body, orient="vertical", command=self._scroll_editor)
        self.editor.configure(yscrollcommand=lambda a, b: self._on_editor_scroll(a, b, scrollbar))
        self.line_numbers.pack(side="left", fill="y")
        scrollbar.pack(side="right", fill="y")
        self.editor.pack(side="left", fill="both", expand=True)

        self.editor.tag_configure("directive", foreground="#235da8")
        self.editor.tag_configure("chapter", foreground="#8f4f00", font=("TkFixedFont", 11, "bold"))
        self.editor.tag_configure("errorline", background="#ffe8e8")
        self.editor.bind("<<Modified>>", self._on_text_modified)
        self.editor.bind("<KeyRelease>", lambda _e: self._schedule_parse())
        self.editor.bind("<Configure>", lambda _e: self.line_numbers.redraw())

        ttk.Label(inspector, text="文档检查器", style="Title.Surface.TLabel").pack(anchor="w")
        self.parse_state = ttk.Label(inspector, text="正在解析…", style="Muted.Surface.TLabel")
        self.parse_state.pack(anchor="w", pady=(3, 12))

        meta = ttk.Frame(inspector, style="Surface.TFrame")
        meta.pack(fill="x", pady=(0, 12))
        self.meta_title = self._meta_row(meta, "标题")
        self.meta_author = self._meta_row(meta, "作者")
        self.meta_language = self._meta_row(meta, "语言")
        self.meta_chapters = self._meta_row(meta, "章节")
        self.meta_images = self._meta_row(meta, "图片")

        ttk.Separator(inspector).pack(fill="x", pady=(0, 12))
        ttk.Label(inspector, text="章节结构", style="Surface.TLabel", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(0, 6))
        self.outline = ttk.Treeview(inspector, show="tree", height=9)
        self.outline.pack(fill="both", expand=False)

        ttk.Label(inspector, text="图片引用", style="Surface.TLabel", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(14, 6))
        self.image_list = tk.Listbox(
            inspector,
            height=7,
            relief="flat",
            borderwidth=0,
            bg="#f8fafc",
            fg="#29313d",
            selectbackground="#d8e8ff",
            activestyle="none",
        )
        self.image_list.pack(fill="both", expand=True)

        guide = ttk.Frame(inspector, style="Surface.TFrame")
        guide.pack(fill="x", pady=(12, 0))
        ttk.Label(guide, text="常用语法", style="Surface.TLabel", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        ttk.Label(
            guide,
            text="@chapter 章节名\n@image \"assets/a.png\" alt=\"说明\" width=80%\n@h2 小节标题   @pagebreak",
            style="Muted.Surface.TLabel",
            justify="left",
        ).pack(anchor="w", pady=(5, 0))

        status = ttk.Frame(self, style="Toolbar.TFrame", padding=(12, 6))
        status.pack(fill="x")
        self.status_left = ttk.Label(status, text="就绪", style="Muted.Surface.TLabel")
        self.status_left.pack(side="left")
        self.status_right = ttk.Label(status, text="0 字符", style="Muted.Surface.TLabel")
        self.status_right.pack(side="right")

    def _meta_row(self, parent: ttk.Frame, label: str) -> ttk.Label:
        row = ttk.Frame(parent, style="Surface.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, style="Muted.Surface.TLabel", width=7).pack(side="left")
        value = ttk.Label(row, text="—", style="Surface.TLabel")
        value.pack(side="left", fill="x", expand=True)
        return value

    def _bind_shortcuts(self) -> None:
        self.bind_all("<Control-n>", lambda _e: self.new_file())
        self.bind_all("<Control-o>", lambda _e: self.open_file())
        self.bind_all("<Control-s>", lambda _e: self.save_file())
        self.bind_all("<Control-Shift-S>", lambda _e: self.save_file_as())
        self.bind_all("<Control-e>", lambda _e: self.export_epub())

    def _on_editor_scroll(self, first: str, last: str, scrollbar: ttk.Scrollbar) -> None:
        scrollbar.set(first, last)
        self.line_numbers.redraw()

    def _scroll_editor(self, *args: str) -> None:
        self.editor.yview(*args)
        self.line_numbers.redraw()

    def _on_text_modified(self, _event: tk.Event | None = None) -> None:
        if not self.editor.edit_modified():
            return
        self.editor.edit_modified(False)
        self.modified = True
        self._update_title()
        self._schedule_parse()

    def _schedule_parse(self) -> None:
        if self._parse_job:
            self.after_cancel(self._parse_job)
        self._parse_job = self.after(250, self._refresh_preview)

    def _refresh_preview(self) -> None:
        self._parse_job = None
        text = self.editor.get("1.0", "end-1c")
        self._apply_syntax_highlight()
        self.status_right.configure(text=f"{len(text):,} 字符 · {int(self.editor.index('end-1c').split('.')[0]):,} 行")
        try:
            book = parse_text(text, self.base_dir)
        except WTSDError as exc:
            self._last_parse_ok = False
            self.parse_state.configure(text=f"语法错误：{exc}", foreground="#a12a2a")
            self.status_left.configure(text="存在语法错误")
            self._show_parse_error_line(str(exc))
            return

        self._last_parse_ok = True
        self.editor.tag_remove("errorline", "1.0", "end")
        missing = [image for image in book.images if not image.source.is_file()]
        if missing:
            self.parse_state.configure(text=f"语法正常 · {len(missing)} 个图片文件缺失", foreground="#9a6200")
            self.status_left.configure(text="可编辑；导出前需补齐图片")
        else:
            self.parse_state.configure(text="语法正常 · 可导出", foreground="#1e7a45")
            self.status_left.configure(text="文档结构正常")

        self.meta_title.configure(text=book.title)
        self.meta_author.configure(text=book.author)
        self.meta_language.configure(text=book.language)
        self.meta_chapters.configure(text=str(len(book.chapters)))
        self.meta_images.configure(text=str(len(book.images)))

        self.outline.delete(*self.outline.get_children())
        for chapter in book.chapters:
            chapter_id = self.outline.insert("", "end", text=chapter.title, open=True)
            for block in chapter.blocks:
                if block.kind in {"h2", "h3"}:
                    self.outline.insert(chapter_id, "end", text=block.text)

        self.image_list.delete(0, "end")
        for image in book.images:
            status = "✓" if image.source.is_file() else "!"
            self.image_list.insert("end", f"{status} {image.source.name}")

    def _apply_syntax_highlight(self) -> None:
        self.editor.tag_remove("directive", "1.0", "end")
        self.editor.tag_remove("chapter", "1.0", "end")
        line_count = int(self.editor.index("end-1c").split(".")[0])
        for n in range(1, line_count + 1):
            value = self.editor.get(f"{n}.0", f"{n}.end")
            stripped = value.lstrip()
            if stripped.startswith("@") and not stripped.startswith("@@"):
                tag = "chapter" if stripped.lower().startswith("@chapter ") else "directive"
                self.editor.tag_add(tag, f"{n}.0", f"{n}.end")
        self.line_numbers.redraw()

    def _show_parse_error_line(self, message: str) -> None:
        self.editor.tag_remove("errorline", "1.0", "end")
        prefix = "line "
        if prefix not in message:
            return
        try:
            line_no = int(message.split(prefix, 1)[1].split(":", 1)[0])
        except ValueError:
            return
        self.editor.tag_add("errorline", f"{line_no}.0", f"{line_no}.end")
        self.editor.see(f"{line_no}.0")

    def _set_text(self, text: str, mark_clean: bool = False) -> None:
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)
        self.editor.edit_modified(False)
        if mark_clean:
            self.modified = False
        self._update_title()
        self._refresh_preview()

    def _update_title(self) -> None:
        name = self.source_path.name if self.source_path else "未命名.wtsd"
        marker = " *" if self.modified else ""
        self.title(f"{name}{marker} — {APP_NAME}")
        self.path_label.configure(text=str(self.source_path) if self.source_path else "未保存")

    def _confirm_discard_or_save(self) -> bool:
        if not self.modified:
            return True
        answer = messagebox.askyesnocancel("未保存的修改", "当前文档有未保存的修改。是否先保存？")
        if answer is None:
            return False
        if answer:
            return self.save_file()
        return True

    def new_file(self) -> None:
        if not self._confirm_discard_or_save():
            return
        self.source_path = None
        self.base_dir = Path.cwd()
        self._set_text(STARTER, mark_clean=True)

    def open_file(self) -> None:
        if not self._confirm_discard_or_save():
            return
        selected = filedialog.askopenfilename(title="打开 WTSD 文档", filetypes=SOURCE_TYPES)
        if not selected:
            return
        path = Path(selected)
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            messagebox.showerror("打开失败", str(exc))
            return
        self.source_path = path
        self.base_dir = path.parent
        self._set_text(text, mark_clean=True)
        self.status_left.configure(text=f"已打开 {path.name}")

    def save_file(self) -> bool:
        if self.source_path is None:
            return self.save_file_as()
        return self._write_source(self.source_path)

    def save_file_as(self) -> bool:
        selected = filedialog.asksaveasfilename(
            title="保存 WTSD 文档",
            defaultextension=".wtsd",
            filetypes=SOURCE_TYPES,
        )
        if not selected:
            return False
        path = Path(selected)
        if path.suffix.lower() not in {".wtsd", ".txt"}:
            path = path.with_suffix(".wtsd")
        if self._write_source(path):
            self.source_path = path
            self.base_dir = path.parent
            self._update_title()
            self._refresh_preview()
            return True
        return False

    def _write_source(self, path: Path) -> bool:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.editor.get("1.0", "end-1c"), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc))
            return False
        self.source_path = path
        self.base_dir = path.parent
        self.modified = False
        self.editor.edit_modified(False)
        self._update_title()
        self.status_left.configure(text=f"已保存 {path.name}")
        return True

    def insert_image(self) -> None:
        selected = filedialog.askopenfilename(title="选择插图", filetypes=SUPPORTED_IMAGES)
        if not selected:
            return
        source = Path(selected)
        target = source

        # Saved documents get portable assets by default.
        if self.source_path is not None:
            assets = self.source_path.parent / "assets"
            assets.mkdir(parents=True, exist_ok=True)
            target = assets / source.name
            if source.resolve() != target.resolve():
                stem, suffix = source.stem, source.suffix
                counter = 2
                while target.exists() and target.read_bytes() != source.read_bytes():
                    target = assets / f"{stem}-{counter}{suffix}"
                    counter += 1
                if not target.exists():
                    try:
                        shutil.copy2(source, target)
                    except OSError as exc:
                        messagebox.showerror("复制图片失败", str(exc))
                        return
            path_text = target.relative_to(self.source_path.parent).as_posix()
        else:
            path_text = target.as_posix()

        directive = f'@image "{path_text}" alt="" width=80%'
        insertion = self.editor.index("insert")
        if self.editor.get(f"{insertion} linestart", insertion).strip():
            directive = "\n" + directive
        directive += "\n"
        self.editor.insert("insert", directive)
        self.editor.focus_set()
        self.modified = True
        self._update_title()
        self._schedule_parse()

    def export_epub(self) -> None:
        text = self.editor.get("1.0", "end-1c")
        try:
            parse_text(text, self.base_dir)
        except WTSDError as exc:
            messagebox.showerror("无法导出", f"请先修正文档语法：\n\n{exc}")
            return

        default_name = (self.source_path.stem if self.source_path else "book") + ".epub"
        selected = filedialog.asksaveasfilename(
            title="导出 EPUB",
            defaultextension=".epub",
            initialfile=default_name,
            filetypes=[("EPUB", "*.epub")],
        )
        if not selected:
            return
        output = Path(selected)
        try:
            build_epub_from_text(text, self.base_dir, output)
        except (WTSDError, OSError) as exc:
            messagebox.showerror("导出失败", str(exc))
            return

        self.status_left.configure(text=f"已导出 {output.name}")
        open_now = messagebox.askyesno("导出完成", f"EPUB 已生成：\n{output}\n\n是否打开所在文件夹？")
        if open_now:
            self._open_folder(output.parent)

    def _open_folder(self, folder: Path) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                os.system(f'open "{folder}"')
            else:
                os.system(f'xdg-open "{folder}"')
        except OSError:
            pass

    def _on_close(self) -> None:
        if self._confirm_discard_or_save():
            self.destroy()


def main() -> int:
    app = WTSDStudio()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
