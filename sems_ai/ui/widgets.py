"""Componentes reutilizables de la interfaz."""
from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable, Sequence

import customtkinter as ctk


def combo(master, **kw) -> ctk.CTkComboBox:
    """ComboBox que inicia vacío (evita el texto por defecto del widget)."""
    c = ctk.CTkComboBox(master, **kw)
    c.set("")
    return c


def detail_pane(pane, width: int = 400) -> ctk.CTkTextbox:
    """Panel de detalle lateral de ancho fijo."""
    pane.grid_columnconfigure(0, weight=1)
    pane.grid_columnconfigure(1, weight=0, minsize=width)
    box = ctk.CTkTextbox(pane, wrap="word", width=width)
    box.grid(row=0, column=1, sticky="nsew")
    return box


class Table(ctk.CTkFrame):
    """Tabla basada en ttk.Treeview con barras de desplazamiento."""

    def __init__(self, master, columns: Sequence[str], widths: Sequence[int] | None = None, height: int = 12,
                 on_select: Callable[[dict | None], None] | None = None, on_double: Callable[[dict], None] | None = None,
                 selectmode: str = "browse"):
        super().__init__(master)
        self.columns = list(columns)
        self.tree = ttk.Treeview(self, columns=self.columns, show="headings", height=height, selectmode=selectmode)
        for i, c in enumerate(self.columns):
            self.tree.heading(c, text=c, command=lambda c=c: self._sort(c))
            self.tree.column(c, width=(widths[i] if widths and i < len(widths) else 120), stretch=True, anchor="w")
        ys = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._rows: dict[str, dict] = {}
        self._sort_desc = False
        if on_select:
            self.tree.bind("<<TreeviewSelect>>", lambda e: on_select(self.selected()))
        if on_double:
            self.tree.bind("<Double-1>", lambda e: (self.selected() and on_double(self.selected())))

    def set_rows(self, rows: list[dict], keys: Sequence[str] | None = None) -> None:
        keys = list(keys or self.columns)
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        for r in rows:
            vals = ["" if r.get(k) is None else str(r.get(k)).replace("\n", " ")[:300] for k in keys]
            iid = self.tree.insert("", "end", values=vals)
            self._rows[iid] = r

    def selected(self) -> dict | None:
        sel = self.tree.selection()
        return self._rows.get(sel[0]) if sel else None

    def selected_all(self) -> list[dict]:
        return [self._rows[i] for i in self.tree.selection() if i in self._rows]

    def _sort(self, col: str) -> None:
        items = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        items.sort(reverse=self._sort_desc)
        for idx, (_, k) in enumerate(items):
            self.tree.move(k, "", idx)
        self._sort_desc = not self._sort_desc


class FormDialog(ctk.CTkToplevel):
    """Diálogo modal genérico. ``fields``: lista de dicts con
    name, label, type (text|longtext|choice|bool|password), options, default, required."""

    def __init__(self, master, title: str, fields: list[dict], width: int = 620, note: str = ""):
        super().__init__(master)
        self.title(title)
        self.geometry(f"{width}x{min(120 + 56 * len(fields), 760)}")
        self.result: dict | None = None
        self.fields = fields
        self.widgets: dict[str, Any] = {}
        body = ctk.CTkScrollableFrame(self)
        body.pack(fill="both", expand=True, padx=10, pady=10)
        if note:
            ctk.CTkLabel(body, text=note, wraplength=width - 60, justify="left", text_color="#B36B00").pack(
                anchor="w", pady=(0, 8))
        for f in fields:
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", pady=3)
            lbl = f["label"] + (" *" if f.get("required") else "")
            ctk.CTkLabel(row, text=lbl, width=190, anchor="w", wraplength=185, justify="left").pack(side="left")
            typ = f.get("type", "text")
            default = f.get("default")
            if typ == "choice":
                w = ctk.CTkComboBox(row, values=[str(o) for o in f.get("options", [])], width=360)
                w.set(str(default) if default not in (None, "") else (str(f["options"][0]) if f.get("options") and
                                                                      f.get("required") else ""))
            elif typ == "bool":
                w = ctk.CTkCheckBox(row, text="")
                if default:
                    w.select()
            elif typ == "longtext":
                w = ctk.CTkTextbox(row, width=360, height=90)
                if default:
                    w.insert("1.0", str(default))
            else:
                w = ctk.CTkEntry(row, width=360, show="•" if typ == "password" else None)
                if default not in (None, ""):
                    w.insert(0, str(default))
            w.pack(side="left", fill="x", expand=True)
            self.widgets[f["name"]] = (w, typ)
        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(btns, text="Aceptar", command=self._ok).pack(side="right", padx=4)
        ctk.CTkButton(btns, text="Cancelar", fg_color="gray", command=self.destroy).pack(side="right", padx=4)
        self.transient(master)
        self.after(50, self._grab)

    def _grab(self):
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _ok(self) -> None:
        out = {}
        for f in self.fields:
            w, typ = self.widgets[f["name"]]
            if typ == "bool":
                v = bool(w.get())
            elif typ == "longtext":
                v = w.get("1.0", "end").strip()
            else:
                v = w.get().strip()
            if f.get("required") and (v == "" or v is None):
                messagebox.showwarning("Campo obligatorio", f"Complete: {f['label']}", parent=self)
                return
            out[f["name"]] = v
        self.result = out
        self.destroy()

    @classmethod
    def ask(cls, master, title: str, fields: list[dict], **kw) -> dict | None:
        d = cls(master, title, fields, **kw)
        master.wait_window(d)
        return d.result


def info(msg: str, title: str = "SEMS AI") -> None:
    messagebox.showinfo(title, msg)


def error(msg: str, title: str = "SEMS AI — Error") -> None:
    messagebox.showerror(title, msg)


def confirm(msg: str, title: str = "SEMS AI") -> bool:
    return messagebox.askyesno(title, msg)


def open_path(path: Path | str, page: int | None = None, viewer_cmd: str = "") -> None:
    """Abre un archivo con la aplicación predeterminada (o el visor PDF configurado en la página citada)."""
    path = str(path)
    if viewer_cmd and page and path.lower().endswith(".pdf"):
        import shlex

        cmd = viewer_cmd.replace("{page}", str(page)).replace("{file}", path)
        subprocess.Popen(shlex.split(cmd, posix=not sys.platform.startswith("win")))
        return
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class PageBase(ctk.CTkFrame):
    title_key = ""

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.ctx = app.ctx

    def on_show(self) -> None:  # refrescar al mostrar
        pass

    def header(self, text: str, subtitle: str = "") -> None:
        ctk.CTkLabel(self, text=text, font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", padx=12, pady=(10, 0))
        if subtitle:
            ctk.CTkLabel(self, text=subtitle, text_color="gray", wraplength=1000, justify="left").pack(
                anchor="w", padx=12, pady=(0, 6))

    def toolbar(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self, fg_color="transparent")
        f.pack(fill="x", padx=12, pady=4)
        return f

    def run(self, name, fn, on_done=None):
        return self.app.run_task(name, fn, on_done)

    def doc_choices(self, ext: tuple[str, ...] | None = None) -> dict[str, dict]:
        out = {}
        for d in self.ctx.repository.list_documents():
            if ext and (d.get("extension") or "") not in ext:
                continue
            label = f"[{d['id']}] {d['doc_code'] or ''} {d['name']} (v{d['version_no']})".replace("  ", " ")
            out[label] = d
        return out
