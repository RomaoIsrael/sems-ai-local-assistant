"""Página de análisis de cumplimiento documental."""
from __future__ import annotations

import customtkinter as ctk

from sems_ai.compliance.gap_analysis import RESULTS, REVIEW_STATES, GapAnalyzer
from sems_ai.ui import widgets as w


class CompliancePage(w.PageBase):
    COLS = ["ID", "Numeral", "Pág.", "Tipo", "Requisito", "Resultado", "Sección local", "Confianza", "Revisión"]
    KEYS = ["ident", "numeral", "req_page", "obligation_type", "req_text", "result", "local_section", "confidence",
            "review_status"]

    def __init__(self, master, app):
        super().__init__(master, app)
        self.header("Análisis de cumplimiento documental",
                    "Compara requisitos de un estándar/procedimiento de referencia con un documento local. Los "
                    "resultados son preliminares; la ausencia de texto no prueba incumplimiento operativo.")
        tb = self.toolbar()
        ctk.CTkLabel(tb, text="Referencia:").pack(side="left")
        self.ref = w.combo(tb, values=[], width=330)
        self.ref.pack(side="left", padx=4)
        ctk.CTkLabel(tb, text="Evaluado:").pack(side="left")
        self.ev = w.combo(tb, values=[], width=330)
        self.ev.pack(side="left", padx=4)
        self.use_llm = ctk.CTkCheckBox(tb, text="Usar IA local")
        self.use_llm.pack(side="left", padx=4)
        ctk.CTkButton(tb, text="Ejecutar análisis", command=self.run_analysis).pack(side="left", padx=4)
        tb2 = self.toolbar()
        ctk.CTkLabel(tb2, text="Análisis:").pack(side="left")
        self.an = w.combo(tb2, values=[], width=520, command=lambda _: self.load_items())
        self.an.pack(side="left", padx=4)
        for text, cmd in (("Revisar ítem", self.review), ("Exportar matriz Excel", self.export),
                          ("Reporte Word", self.report), ("Ir a revisión de Word", self.to_word)):
            ctk.CTkButton(tb2, text=text, command=cmd, width=10).pack(side="left", padx=3)
        self.summary = ctk.CTkLabel(self, text="", anchor="w")
        self.summary.pack(fill="x", padx=12)
        pane = ctk.CTkFrame(self, fg_color="transparent")
        pane.pack(fill="both", expand=True, padx=12, pady=6)
        pane.grid_rowconfigure(0, weight=1)
        self.table = w.Table(pane, self.COLS, [130, 55, 40, 85, 330, 170, 150, 65, 130], height=18,
                             on_select=self.details, on_double=lambda r: self.review())
        self.table.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.detail = w.detail_pane(pane)
        self._analyses: dict[str, int] = {}

    def on_show(self) -> None:
        self._docs = self.doc_choices()
        vals = list(self._docs)
        self.ref.configure(values=vals)
        self.ev.configure(values=vals)
        an = GapAnalyzer(self.ctx.db).analyses()
        self._analyses = {f"[{a['id']}] {a['title']} — {a['created_at']} ({a['n_items']} req.)": a["id"] for a in an}
        self.an.configure(values=list(self._analyses))
        if self._analyses and self.an.get() not in self._analyses:
            self.an.set(next(iter(self._analyses)))
        self.load_items()

    def current_id(self) -> int | None:
        return self._analyses.get(self.an.get())

    def run_analysis(self) -> None:
        r, e = self._docs.get(self.ref.get()), self._docs.get(self.ev.get())
        if not r or not e:
            return w.info("Seleccione documento de referencia y documento evaluado.")
        if r["id"] == e["id"]:
            return w.info("Seleccione documentos distintos.")
        use_llm = bool(self.use_llm.get())

        def work(job):
            llm = self.ctx.llm() if use_llm else None
            if use_llm and llm is None:
                raise RuntimeError(f"IA local no disponible: {self.ctx.llm_status()}. Desmarque 'Usar IA local' "
                                   "para el análisis léxico.")
            return GapAnalyzer(self.ctx.db, llm, self.ctx.username).run(
                r["current_version_id"], e["current_version_id"], progress=job.progress, cancel=job.cancelled)

        def done(aid):
            self.on_show()
            for k, v in self._analyses.items():
                if v == aid:
                    self.an.set(k)
            self.load_items()

        self.run("Análisis de cumplimiento", work, done)

    def load_items(self) -> None:
        aid = self.current_id()
        if not aid:
            self.table.set_rows([])
            return
        ga = GapAnalyzer(self.ctx.db)
        self.table.set_rows(ga.items(aid), self.KEYS)
        s = ga.summary(aid)
        self.summary.configure(text="  |  ".join(f"{k}: {v}" for k, v in s.items() if v))

    def details(self, row) -> None:
        if not row:
            return
        fields = [("Identificador", "ident"), ("Fuente", "source"), ("Numeral", "numeral"), ("Página", "req_page"),
                  ("Requisito", "req_text"), ("Tipo de obligación", "obligation_type"),
                  ("Documento local", "local_document"), ("Sección", "local_section"), ("Página local", "local_page"),
                  ("Evidencia encontrada", "evidence"), ("Resultado preliminar", "result"), ("Brecha", "gap"),
                  ("Recomendación", "recommendation"), ("Justificación", "justification"),
                  ("Acción propuesta", "proposed_action"), ("Confianza", "confidence"),
                  ("Estado de revisión", "review_status"), ("Revisor", "reviewer"), ("Notas", "reviewer_notes")]
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", "\n\n".join(f"{k}: {row.get(v) or '-'}" for k, v in fields))

    def review(self) -> None:
        row = self.table.selected()
        if not row:
            return w.info("Seleccione un requisito.")
        res = w.FormDialog.ask(self, f"Revisión humana — {row['ident']}", [
            {"name": "review_status", "label": "Estado de revisión", "type": "choice", "options": REVIEW_STATES,
             "default": row["review_status"], "required": True},
            {"name": "result", "label": "Resultado", "type": "choice", "options": RESULTS, "default": row["result"],
             "required": True},
            {"name": "reviewer", "label": "Revisor", "default": row["reviewer"] or self.ctx.username, "required": True},
            {"name": "notes", "label": "Notas / justificación", "type": "longtext", "default": row["reviewer_notes"]},
        ])
        if res:
            try:
                GapAnalyzer(self.ctx.db).review(row["id"], res["review_status"], res["reviewer"], res["result"],
                                                res["notes"])
            except ValueError as exc:
                return w.error(str(exc))
            self.load_items()

    def export(self) -> None:
        from sems_ai.compliance.export import export_gap_matrix
        from sems_ai.excel.builder import unique_path

        aid = self.current_id()
        if aid:
            p = export_gap_matrix(self.ctx.db, aid, unique_path(self.ctx.export_dir, f"matriz_brechas_{aid}", ".xlsx"))
            w.info(f"Exportado: {p}")

    def report(self) -> None:
        from sems_ai.excel.builder import unique_path
        from sems_ai.reports.technical_report import compliance_report

        aid = self.current_id()
        if aid:
            p = compliance_report(self.ctx.db, aid, unique_path(self.ctx.export_dir, f"reporte_cumplimiento_{aid}",
                                                                ".docx"), self.ctx.username)
            w.info(f"Reporte generado: {p}")

    def to_word(self) -> None:
        aid = self.current_id()
        page = self.app.show("word")
        if aid:
            page.preselect_analysis(aid)
