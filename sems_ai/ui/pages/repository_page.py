"""Página del repositorio documental."""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from sems_ai.document_processing.extractors import SUPPORTED_EXTENSIONS
from sems_ai.ui import widgets as w

STATUSES = ["Pendiente de verificación", "Vigente (verificado)", "En revisión", "Obsoleto", "Borrador",
            "Aprobado (verificado)"]


class RepositoryPage(w.PageBase):
    COLS = ["ID", "Código", "Nombre", "Categoría", "Rev.", "Versión", "Estado", "Extracción", "Incorporado"]
    KEYS = ["id", "doc_code", "name", "category", "revision", "version_no", "status", "extraction_status", "added_at"]

    def __init__(self, master, app):
        super().__init__(master, app)
        self.header("Repositorio documental", "Formatos: " + ", ".join(SUPPORTED_EXTENSIONS) +
                    ". Los originales se copian a la bóveda y nunca se modifican.")
        tb = self.toolbar()
        for text, cmd in (("Importar archivos", self.import_files), ("Importar carpeta", self.import_folder),
                          ("Nueva versión", self.new_version), ("Editar ficha", self.edit),
                          ("Reprocesar", self.reprocess), ("Abrir original", self.open_original),
                          ("Nueva categoría", self.new_category), ("Verificar integridad", self.verify),
                          ("Exportar inventario", self.export_inventory)):
            ctk.CTkButton(tb, text=text, command=cmd, width=10).pack(side="left", padx=3)
        sb = self.toolbar()
        self.cat = w.combo(sb, values=["Todas"], width=260, command=lambda _: self.refresh())
        self.cat.pack(side="left", padx=3)
        self.search = ctk.CTkEntry(sb, placeholder_text="Nombre, código, revisión, fecha…", width=300)
        self.search.pack(side="left", padx=3)
        self.search.bind("<Return>", lambda e: self.refresh())
        ctk.CTkButton(sb, text="Filtrar ficha", command=self.refresh, width=10).pack(side="left", padx=3)
        ctk.CTkButton(sb, text="Buscar en texto completo", command=lambda: self.search_fulltext(self.search.get()),
                      width=10).pack(side="left", padx=3)
        pane = ctk.CTkFrame(self, fg_color="transparent")
        pane.pack(fill="both", expand=True, padx=12, pady=6)
        pane.grid_rowconfigure(0, weight=1)
        self.table = w.Table(pane, self.COLS, [40, 140, 260, 170, 45, 55, 150, 95, 130], height=20,
                             on_select=self.show_details, selectmode="extended")
        self.table.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.details = w.detail_pane(pane)

    def on_show(self) -> None:
        cats = ["Todas"] + [c["name"] for c in self.ctx.repository.categories()]
        self.cat.configure(values=cats)
        if not self.cat.get():
            self.cat.set("Todas")
        self.refresh()

    def refresh(self) -> None:
        repo = self.ctx.repository
        cid = None if self.cat.get() in ("", "Todas") else repo.category_id(self.cat.get())
        rows = repo.list_documents(cid, self.search.get().strip())
        self.table.set_rows(rows, self.KEYS)

    def search_fulltext(self, q: str) -> None:
        q = (q or "").strip()
        if not q:
            return
        hits = self.ctx.retriever().fulltext(q, k=50, current_only=False)
        seen, rows = set(), []
        for h in hits:
            if h.document_id in seen:
                continue
            seen.add(h.document_id)
            d = self.ctx.repository.get_document(h.document_id)
            if d:
                rows.append(d)
        self.table.set_rows(rows, self.KEYS)
        self.details.delete("1.0", "end")
        self.details.insert("1.0", f"Resultados de texto completo para «{q}»:\n\n" + "\n\n".join(
            f"• {h.citation()}\n  …{h.snippet}…" for h in hits[:25]) if hits else
            f"Sin coincidencias en el texto para «{q}».")

    def show_details(self, row) -> None:
        if not row:
            return
        repo = self.ctx.repository
        vers = repo.versions(row["id"])
        rels = repo.relations(row["id"])
        lines = [f"{k}: {row.get(v) or ''}" for k, v in (
            ("Nombre", "name"), ("Código documental", "doc_code"), ("Categoría", "category"), ("Área", "area"),
            ("Tipo", "doc_type"), ("Organización emisora", "issuer"), ("Revisión", "revision"),
            ("Fecha de emisión", "issue_date"), ("Fecha de vigencia (acreditada)", "effective_date"),
            ("Incorporado", "added_at"), ("Última verificación", "last_verified_at"), ("Estado", "status"),
            ("Fuente de origen", "source"), ("Responsable de verificación", "verifier"), ("SHA-256", "sha256"),
            ("Alertas de seguridad", "security_flags"), ("Notas", "notes"))]
        lines.append("\nHistorial de versiones:")
        for v in vers:
            lines.append(f"  v{v['version_no']} rev {v['revision'] or '-'} | {v['original_filename']} | "
                         f"{v['imported_at']} | extracción: {v['extraction_status']} {v['extraction_message'] or ''}"
                         f" | SHA-256 {v['sha256'][:16]}…")
        if rels:
            lines.append("\nDocumentos relacionados:")
            lines += [f"  {r['relation']}: [{r['id']}] {r['doc_code'] or ''} {r['name']}" for r in rels]
        self.details.delete("1.0", "end")
        self.details.insert("1.0", "\n".join(lines))

    # ------------------------------------------------------------ acciones
    def _ask_import_meta(self) -> dict | None:
        cats = [c["name"] for c in self.ctx.repository.categories()]
        return w.FormDialog.ask(self, "Datos de importación", [
            {"name": "category", "label": "Categoría", "type": "choice", "options": cats, "required": True},
            {"name": "area", "label": "Área responsable"},
            {"name": "issuer", "label": "Organización emisora"},
            {"name": "source", "label": "Fuente de origen"},
        ], note="Los demás datos (código, revisión, fechas) se completan en la ficha. Los códigos detectados "
                "automáticamente quedan marcados para verificación.")

    def _do_import(self, paths) -> None:
        meta = self._ask_import_meta()
        if meta is None:
            return
        cat = meta.pop("category")
        meta = {k: v for k, v in meta.items() if v}

        def work(job):
            return self.ctx.repository.import_paths(paths, cat, meta, progress=job.progress, cancel=job.cancelled)

        def done(outs):
            summary: dict[str, int] = {}
            for o in outs:
                summary[o.status] = summary.get(o.status, 0) + 1
            problems = [f"• {Path(o.path).name}: {o.status} — {o.message}" for o in outs
                        if o.status in ("rechazado", "error") or o.extraction_status in
                        ("no_compatible", "pendiente_ocr", "error", "parcial")]
            flags = [f"• {Path(o.path).name}: {', '.join(o.flags)}" for o in outs if o.flags]
            msg = "Resultado: " + ", ".join(f"{k}={v}" for k, v in summary.items())
            if problems:
                msg += "\n\nRequieren atención:\n" + "\n".join(problems[:25])
            if flags:
                msg += "\n\nAlertas de seguridad:\n" + "\n".join(flags[:15])
            w.info(msg)
            self.refresh()

        self.run("Importación", work, done)

    def import_files(self) -> None:
        paths = filedialog.askopenfilenames(title="Seleccione documentos")
        if paths:
            self._do_import(list(paths))

    def import_folder(self) -> None:
        p = filedialog.askdirectory(title="Seleccione carpeta")
        if p:
            self._do_import([p])

    def new_version(self) -> None:
        row = self.table.selected()
        if not row:
            return w.info("Seleccione el documento al que se agregará la nueva versión.")
        p = filedialog.askopenfilename(title="Archivo de la nueva revisión")
        if not p:
            return
        meta = w.FormDialog.ask(self, "Nueva versión", [{"name": "revision", "label": "Revisión", "required": True}])
        if not meta:
            return
        out = self.ctx.repository.import_file(p, metadata=meta, document_id=row["id"])
        w.info(f"{out.status}: {out.message or 'versión registrada; las anteriores se conservan.'}")
        self.refresh()

    def edit(self) -> None:
        row = self.table.selected()
        if not row:
            return w.info("Seleccione un documento.")
        cats = [c["name"] for c in self.ctx.repository.categories()]
        fields = [
            {"name": "name", "label": "Nombre", "default": row["name"], "required": True},
            {"name": "doc_code", "label": "Código documental", "default": row["doc_code"]},
            {"name": "category", "label": "Categoría", "type": "choice", "options": cats, "default": row["category"]},
            {"name": "area", "label": "Área responsable", "default": row["area"]},
            {"name": "doc_type", "label": "Tipo de documento", "default": row["doc_type"]},
            {"name": "issuer", "label": "Organización emisora", "default": row["issuer"]},
            {"name": "revision", "label": "Revisión", "default": row["revision"]},
            {"name": "issue_date", "label": "Fecha de emisión (AAAA-MM-DD)", "default": row["issue_date"]},
            {"name": "effective_date", "label": "Fecha de vigencia (solo si está acreditada)",
             "default": row["effective_date"]},
            {"name": "last_verified_at", "label": "Fecha de última verificación", "default": row["last_verified_at"]},
            {"name": "status", "label": "Estado documental", "type": "choice", "options": STATUSES,
             "default": row["status"]},
            {"name": "source", "label": "Fuente de origen", "default": row["source"]},
            {"name": "verifier", "label": "Responsable de verificación", "default": row["verifier"]},
            {"name": "notes", "label": "Notas", "type": "longtext", "default": row["notes"]},
        ]
        res = w.FormDialog.ask(self, "Ficha documental", fields)
        if res:
            if "verificado" in (res.get("status") or "").lower() and not res.get("verifier"):
                return w.error("Un estado verificado requiere indicar el responsable de verificación.")
            self.ctx.repository.update_metadata(row["id"], {k: (v or None) for k, v in res.items()})
            self.refresh()

    def reprocess(self) -> None:
        row = self.table.selected()
        if row:
            st = self.ctx.repository.reprocess(row["current_version_id"])
            w.info(f"Reprocesado: {st}")
            self.refresh()

    def open_original(self) -> None:
        row = self.table.selected()
        if row:
            w.open_path(self.ctx.repository.stored_file(row["current_version_id"]))

    def new_category(self) -> None:
        res = w.FormDialog.ask(self, "Nueva categoría", [{"name": "n", "label": "Nombre", "required": True}])
        if res:
            self.ctx.repository.add_category(res["n"])
            self.on_show()

    def verify(self) -> None:
        def done(res):
            bad = [r for r in res if r["estado"] != "OK"]
            w.info(f"Integridad verificada: {len(res)} versiones; {len(bad)} incidencias." +
                   ("\n" + "\n".join(f"• {b['file']}: {b['estado']}" for b in bad[:20]) if bad else ""))

        self.run("Verificación de integridad", lambda job: self.ctx.repository.verify_integrity(), done)

    def export_inventory(self) -> None:
        from sems_ai.excel.builder import WorkbookBuilder, unique_path

        rows = self.ctx.repository.list_documents()
        wb = WorkbookBuilder()
        ws = wb.sheet("Inventario documental")
        keys = ["id", "doc_code", "name", "category", "area", "doc_type", "issuer", "revision", "issue_date",
                "effective_date", "added_at", "last_verified_at", "status", "source", "verifier", "version_no",
                "original_filename", "sha256", "extraction_status"]
        wb.table(ws, ["ID", "Código", "Nombre", "Categoría", "Área", "Tipo", "Emisor", "Revisión", "Emisión",
                      "Vigencia", "Incorporado", "Última verificación", "Estado", "Fuente", "Verificador", "Versión",
                      "Archivo", "SHA-256", "Extracción"], [[r.get(k) for k in keys] for r in rows],
                 table_name="Inventario")
        p = wb.save(unique_path(self.ctx.export_dir, "inventario_documental", ".xlsx"))
        w.info(f"Exportado: {p}")
