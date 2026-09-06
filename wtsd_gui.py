#!/usr/bin/env python3
"""WTSD Studio — import ordinary manuscripts and export EPUB."""
from __future__ import annotations
import sys, tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from txt2epub import WTSDError, build_epub, build_epub_from_text, infer_metadata, parse_text, read_source

APP = "WTSD Studio"
FILES = [("稿件", "*.txt *.md *.markdown *.docx *.html *.htm *.wtsd"), ("所有文件", "*.*")]
STARTER = "第一章\n\n在这里开始正文。\n"

class Studio(tk.Tk):
    def __init__(self):
        super().__init__(); self.geometry("1220x780"); self.minsize(920, 600)
        self.source: Path | None = None; self.base = Path.cwd(); self.source_format = "TXT"; self.notes=[]
        self.title_v=tk.StringVar(); self.author_v=tk.StringVar(); self.lang_v=tk.StringVar(); self._job=None
        self._build(); self._set_text(STARTER); self.redetect(False); self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build(self):
        style=ttk.Style(self)
        if "clam" in style.theme_names(): style.theme_use("clam")
        bar=ttk.Frame(self,padding=10); bar.pack(fill="x")
        ttk.Label(bar,text=APP,font=("TkDefaultFont",13,"bold")).pack(side="left",padx=(0,14))
        for label,cmd in [("导入文件",self.open_file),("快速转换",self.quick_convert),("重新识别",lambda:self.redetect(True)),("插入图片",self.insert_image)]:
            ttk.Button(bar,text=label,command=cmd).pack(side="left",padx=3)
        ttk.Button(bar,text="导出 EPUB",command=self.export_epub).pack(side="right")

        pane=ttk.Panedwindow(self,orient="horizontal"); pane.pack(fill="both",expand=True,padx=10,pady=(0,10))
        left=ttk.Frame(pane,padding=8); right=ttk.Frame(pane,padding=12); pane.add(left,weight=7); pane.add(right,weight=3)
        head=ttk.Frame(left); head.pack(fill="x",pady=(0,6)); ttk.Label(head,text="正文",font=("TkDefaultFont",12,"bold")).pack(side="left")
        self.path_label=ttk.Label(head,text="未导入"); self.path_label.pack(side="right")
        self.editor=tk.Text(left,wrap="word",undo=True,padx=16,pady=14,font=("Microsoft YaHei UI" if sys.platform.startswith("win") else "TkDefaultFont",11),spacing3=5)
        self.editor.pack(fill="both",expand=True); self.editor.bind("<KeyRelease>",lambda _e:self.schedule())

        ttk.Label(right,text="自动识别",font=("TkDefaultFont",12,"bold")).pack(anchor="w")
        self.state=ttk.Label(right,text="",wraplength=300); self.state.pack(anchor="w",fill="x",pady=(4,10))
        self._field(right,"书名",self.title_v); self._field(right,"作者",self.author_v); self._field(right,"语言",self.lang_v)
        for v in (self.title_v,self.author_v,self.lang_v): v.trace_add("write",lambda *_:self.schedule())
        self.count=ttk.Label(right,text="章节 0"); self.count.pack(anchor="w",pady=(8,5))
        self.outline=ttk.Treeview(right,show="tree",height=13); self.outline.pack(fill="both",expand=True)
        ttk.Separator(right).pack(fill="x",pady=10)
        ttk.Label(right,text="识别规则",font=("TkDefaultFont",10,"bold")).pack(anchor="w")
        self.rule=ttk.Label(right,wraplength=300,justify="left",text="TXT/Markdown：文件名、首部书名/作者字段、常见章节行。\nDOCX：文档元数据、Heading/标题样式；必要时参考字号。\n语言按正文字符分布判断。识别不准时直接修改上面的字段。\n@image 等只用于插图等高级需求，普通原稿无需编写。")
        self.rule.pack(anchor="w",fill="x",pady=(4,0))

    def _field(self,parent,label,var):
        row=ttk.Frame(parent); row.pack(fill="x",pady=3); ttk.Label(row,text=label,width=6).pack(side="left"); ttk.Entry(row,textvariable=var).pack(side="left",fill="x",expand=True)

    def _set_text(self,text):
        self.editor.delete("1.0","end"); self.editor.insert("1.0",text); self.refresh()

    def metadata(self):
        return dict(title=self.title_v.get().strip() or None,author=self.author_v.get().strip(),language=self.lang_v.get().strip() or None,source_name=self.source.name if self.source else None)

    def schedule(self):
        if self._job: self.after_cancel(self._job)
        self._job=self.after(220,self.refresh)

    def refresh(self):
        self._job=None; text=self.editor.get("1.0","end-1c")
        try: book=parse_text(text,self.base,**self.metadata())
        except WTSDError as e: self.state.config(text=f"结构错误：{e}"); return
        self.state.config(text=f"{self.source_format} · 已识别，可直接导出")
        self.count.config(text=f"章节 {len(book.chapters)} · 图片 {len(book.images)}")
        self.outline.delete(*self.outline.get_children())
        for ch in book.chapters:
            root=self.outline.insert("","end",text=ch.title,open=True)
            for b in ch.blocks:
                if b.kind in {"h2","h3"}: self.outline.insert(root,"end",text=b.text)

    def load_path(self,path:Path):
        try: src=read_source(path)
        except (WTSDError,OSError) as e: messagebox.showerror("导入失败",str(e)); return False
        self.source=src.path; self.base=src.base_dir; self.source_format=src.source_format; self.notes=src.notes; self.path_label.config(text=src.path.name)
        self._set_text(src.text)
        book=parse_text(src.text,src.base_dir,title=src.title or None,author=src.author or None,language=src.language or None,source_name=src.path.name)
        self.title_v.set(book.title); self.author_v.set(book.author); self.lang_v.set(book.language); self.refresh(); return True

    def open_file(self):
        name=filedialog.askopenfilename(title="导入稿件",filetypes=FILES)
        if name: self.load_path(Path(name))

    def redetect(self,show=True):
        text=self.editor.get("1.0","end-1c"); title,author,lang,_=infer_metadata(text,self.source.name if self.source else None)
        if self.source and self.source.suffix.lower() in {".docx",".html",".htm"}:
            try:
                src=read_source(self.source); title=src.title or title; author=src.author or author; lang=src.language or lang
            except (WTSDError,OSError): pass
        self.title_v.set(title); self.author_v.set(author); self.lang_v.set(lang); self.refresh()
        if show: self.state.config(text="已重新识别；字段仍可手动修改")

    def quick_convert(self):
        name=filedialog.askopenfilename(title="选择稿件并自动转换",filetypes=FILES)
        if not name: return
        src=Path(name); out=src.with_suffix(".epub")
        if out.exists() and not messagebox.askyesno("覆盖",f"{out.name} 已存在，覆盖吗？"): return
        try: build_epub(src,out)
        except (WTSDError,OSError) as e: messagebox.showerror("转换失败",str(e)); return
        messagebox.showinfo("完成",f"已生成：\n{out}")

    def insert_image(self):
        name=filedialog.askopenfilename(title="选择插图",filetypes=[("图片","*.png *.jpg *.jpeg *.gif *.webp *.svg")])
        if not name: return
        p=Path(name); ref=p.as_posix()
        if self.source:
            try: ref=p.relative_to(self.base).as_posix()
            except ValueError: pass
        self.editor.insert("insert",f'\n@image "{ref}" alt="" width=80%\n'); self.refresh()

    def export_epub(self):
        text=self.editor.get("1.0","end-1c"); default=(self.source.stem if self.source else (self.title_v.get().strip() or "book"))+".epub"
        out=filedialog.asksaveasfilename(title="导出 EPUB",defaultextension=".epub",initialfile=default,filetypes=[("EPUB","*.epub")])
        if not out: return
        try: build_epub_from_text(text,self.base,Path(out),**self.metadata())
        except (WTSDError,OSError) as e: messagebox.showerror("导出失败",str(e)); return
        messagebox.showinfo("完成",f"EPUB 已生成：\n{out}")


def main():
    app=Studio()
    if len(sys.argv)>1 and Path(sys.argv[1]).is_file(): app.after(80,lambda:app.load_path(Path(sys.argv[1])))
    app.mainloop(); return 0

if __name__=="__main__": raise SystemExit(main())
