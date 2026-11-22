"""Páginas Inicio y Asistente IA."""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

from sems_ai.core.i18n import t
from sems_ai.security import network_guard
from sems_ai.ui import widgets as w


class HomePage(w.PageBase):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.header(t("app_title"), "Asistente local para SEMS, HSE, ambiente y QA/QC. Todo el procesamiento ocurre "
                                    "en este equipo; los documentos y consultas no se envían a servicios externos.")
        self.cards = ctk.CTkFrame(self, fg_color="transparent")
        self.cards.pack(fill="x", padx=12, pady=10)
        self.info = ctk.CTkTextbox(self, height=260)
        self.info.pack(fill="both", expand=True, padx=12, pady=8)
        tb = self.toolbar()
        ctk.CTkButton(tb, text=t("import_files"), command=lambda: app.show("repository").import_files()).pack(
            side="left", padx=4)
        ctk.CTkButton(tb, text="Hacer una consulta", command=lambda: app.show("assistant")).pack(side="left", padx=4)
        ctk.CTkButton(tb, text="Verificar integridad", command=lambda: app.show("repository").verify()).pack(
            side="left", padx=4)

    def on_show(self) -> None:
        for c in self.cards.winfo_children():
            c.destroy()
        st = self.ctx.repository.stats()
        labels = [("Documentos", st["documentos"]), ("Versiones", st["versiones"]),
                  ("Fragmentos indexados", st["fragmentos"]), ("Pendientes / no compatibles", st["pendientes"]),
                  ("Embeddings", st["embeddings"])]
        for name, val in labels:
            f = ctk.CTkFrame(self.cards, width=180, height=80)
            f.pack(side="left", padx=6)
            ctk.CTkLabel(f, text=str(val), font=ctk.CTkFont(size=24, weight="bold")).pack(padx=18, pady=(10, 0))
            ctk.CTkLabel(f, text=name, text_color="gray").pack(padx=18, pady=(0, 10))
        s = self.ctx.settings
        lines = [
            f"Directorio de datos: {s.base}",
            f"Directorio de exportación: {self.ctx.export_dir}",
            f"Bloqueo de conexiones externas: {'ACTIVO' if network_guard.is_enabled() else 'DESACTIVADO'}",
            f"Motor de IA local: Ollama en {s.ollama_url} — modelo '{s.llm_model}' "
            f"({'habilitado' if s.llm_enabled else 'deshabilitado'})",
            f"Búsqueda semántica: {'habilitada' if s.semantic_search_enabled else 'deshabilitada (solo texto completo)'}",
            "",
            "Principios de funcionamiento:",
            " • Los originales se conservan intactos en la bóveda (solo lectura, con SHA-256).",
            " • Las respuestas citan documento, revisión, sección y página cuando están disponibles.",
            " • Si no hay respaldo documental, el asistente lo indica expresamente.",
            " • Los resultados de cumplimiento son preliminares y requieren validación humana.",
            " • Las modificaciones a documentos Word requieren aprobación individual y generan una copia.",
        ]
        self.info.configure(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("1.0", "\n".join(lines))
        self.info.configure(state="disabled")


class AssistantPage(w.PageBase):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.header(t("assistant"), "Consultas sobre los documentos del repositorio, con fuentes verificables.")
        tb = self.toolbar()
        self.q = ctk.CTkEntry(tb, placeholder_text="Escriba su consulta…", width=620)
        self.q.pack(side="left", padx=4)
        self.q.bind("<Return>", lambda e: self.ask())
        self.use_llm = ctk.CTkCheckBox(tb, text=t("use_llm"))
        self.use_llm.select()
        self.use_llm.pack(side="left", padx=6)
        self.cat = w.combo(tb, values=["Todas las categorías"], width=230)
        self.cat.pack(side="left", padx=4)
        ctk.CTkButton(tb, text=t("ask"), command=self.ask).pack(side="left", padx=4)
        ctk.CTkButton(tb, text="Exportar respuesta", command=self.export).pack(side="left", padx=4)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=4)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=3)
        body.grid_rowconfigure(1, weight=2)
        self.answer = ctk.CTkTextbox(body, wrap="word")
        self.answer.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 6))
        right = ctk.CTkFrame(body)
        right.grid(row=0, column=1, rowspan=2, sticky="nsew")
        ctk.CTkLabel(right, text="Visor de referencias", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=8)
        self.ref_text = ctk.CTkTextbox(right, wrap="word", height=200)
        self.ref_text.pack(fill="both", expand=True, padx=8, pady=4)
        self.page_img = ctk.CTkLabel(right, text="")
        self.page_img.pack(padx=8, pady=4)
        rb = ctk.CTkFrame(right, fg_color="transparent")
        rb.pack(fill="x", padx=8, pady=4)
        ctk.CTkButton(rb, text="Abrir documento original", command=self.open_source).pack(side="left", padx=2)
        ctk.CTkButton(rb, text="Ver página", command=self.render_page).pack(side="left", padx=2)
        lower = ctk.CTkTabview(body, height=220)
        lower.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        lower.add("Fuentes")
        lower.add("Advertencias")
        lower.add("Historial")
        self.sources = w.Table(lower.tab("Fuentes"), ["N", "Documento", "Código", "Rev.", "Sección", "Pág.",
                                                      "Cobertura", "Método"],
                               [30, 200, 130, 40, 200, 40, 70, 70], height=6, on_select=self.show_ref)
        self.sources.pack(fill="both", expand=True)
        self.warn = ctk.CTkTextbox(lower.tab("Advertencias"), wrap="word")
        self.warn.pack(fill="both", expand=True)
        self.hist = w.Table(lower.tab("Historial"), ["Fecha", "Consulta", "Modo", "Modelo"], [130, 420, 90, 120],
                            height=6, on_double=self.load_history)
        self.hist.pack(fill="both", expand=True)
        self.current = None

    def on_show(self) -> None:
        cats = ["Todas las categorías"] + [c["name"] for c in self.ctx.repository.categories()]
        self.cat.configure(values=cats)
        if not self.cat.get():
            self.cat.set(cats[0])
        self.hist.set_rows([{"Fecha": h["ts"], "Consulta": h["query"], "Modo": h["mode"], "Modelo": h["model"],
                             **h} for h in self.ctx.answer_engine(use_llm=False).history()])

    def ask(self) -> None:
        query = self.q.get().strip()
        if not query:
            return
        use_llm = bool(self.use_llm.get())
        cat = self.cat.get()
        filters = {}
        if cat and cat != "Todas las categorías":
            cid = self.ctx.repository.category_id(cat)
            filters["category_ids"] = [cid]
        self.answer.delete("1.0", "end")
        self.answer.insert("1.0", "Buscando en el repositorio local…\n")
        stream_buf: list[str] = []

        def on_token(tok):
            stream_buf.append(tok)

        def work(job):
            eng = self.ctx.answer_engine(use_llm=use_llm)
            return eng.ask(query, filters, on_token=on_token if use_llm else None, cancel=job.cancelled,
                           use_llm=use_llm)

        def tick():
            if self.app.tasks.current is not None and stream_buf:
                self.answer.delete("1.0", "end")
                self.answer.insert("1.0", "".join(stream_buf))
                self.answer.see("end")
            if self.app.tasks.current is not None:
                self.after(250, tick)

        self.run("Consulta", work, self.show_answer)
        self.after(250, tick)

    def show_answer(self, ans) -> None:
        self.current = ans
        head = {"llm": f"Respuesta generada por IA local ({ans.model}) a partir de las fuentes citadas:",
                "extractivo": "", "sin_evidencia": ""}[ans.mode]
        self.answer.delete("1.0", "end")
        self.answer.insert("1.0", (head + "\n\n" if head else "") + ans.text)
        self.sources.set_rows([{"N": f"S{i + 1}", "Documento": h.doc_name, "Código": h.doc_code, "Rev.": h.revision,
                                "Sección": h.section, "Pág.": h.page or h.location,
                                "Cobertura": f"{h.term_coverage:.0%}", "Método": h.method, "_hit": h}
                               for i, h in enumerate(ans.sources)])
        self.warn.delete("1.0", "end")
        self.warn.insert("1.0", "\n".join("⚠ " + x for x in ans.warnings) or "Sin advertencias de verificación.")
        self.on_show()

    def show_ref(self, row) -> None:
        if not row:
            return
        h = row["_hit"]
        self.ref_text.delete("1.0", "end")
        self.ref_text.insert("1.0", f"{h.citation()}\nArchivo: {h.filename}\n\n{h.text}")

    def _selected_hit(self):
        row = self.sources.selected()
        return row["_hit"] if row else None

    def open_source(self) -> None:
        h = self._selected_hit()
        if not h:
            return w.info("Seleccione una fuente.")
        path = self.ctx.repository.stored_file(h.version_id)
        w.open_path(path, h.page, self.ctx.settings.pdf_viewer_command)

    def render_page(self) -> None:
        h = self._selected_hit()
        if not h or not h.page:
            return w.info("Seleccione una fuente con número de página (PDF).")
        path = self.ctx.repository.stored_file(h.version_id)
        if path.suffix.lower() != ".pdf":
            return w.info("La vista de página está disponible para PDF.")
        import pymupdf
        from PIL import Image

        with pymupdf.open(path) as doc:
            page = doc[h.page - 1]
            pix = page.get_pixmap(dpi=60)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        self._img = ctk.CTkImage(light_image=img, dark_image=img, size=(pix.width, pix.height))
        self.page_img.configure(image=self._img)

    def load_history(self, row) -> None:
        self.answer.delete("1.0", "end")
        self.answer.insert("1.0", f"[Historial {row['ts']}] {row['query']}\n\n{row['answer']}")
        try:
            src = json.loads(row["sources_json"] or "[]")
            self.warn.delete("1.0", "end")
            self.warn.insert("1.0", "Fuentes registradas:\n" + "\n".join(
                f"S{s['n']}: {s['code'] or s['doc']} sec. {s['section']} pág. {s['page']}" for s in src))
        except json.JSONDecodeError:
            pass

    def export(self) -> None:
        if not self.current:
            return w.info("No hay respuesta para exportar.")
        p = filedialog.asksaveasfilename(defaultextension=".docx", initialdir=str(self.ctx.export_dir),
                                         filetypes=[("Word", "*.docx")])
        if not p:
            return
        import docx

        d = docx.Document()
        d.add_heading("Consulta SEMS AI", 1)
        d.add_paragraph(f"Consulta: {self.current.query}")
        d.add_paragraph(f"Modo: {self.current.mode} {self.current.model}")
        d.add_heading("Respuesta", 2)
        d.add_paragraph(self.current.text)
        d.add_heading("Fuentes", 2)
        for i, h in enumerate(self.current.sources, start=1):
            d.add_paragraph(f"[S{i}] {h.citation()} — {h.filename}")
        if self.current.warnings:
            d.add_heading("Advertencias de verificación", 2)
            for x in self.current.warnings:
                d.add_paragraph(x)
        d.save(p)
        w.info(f"Exportado: {p}")


_ = tk
