"""Página del revisor inteligente de Word."""
from __future__ import annotations

import customtkinter as ctk

from sems_ai.compliance.gap_analysis import GapAnalyzer
from sems_ai.ui import widgets as w
from sems_ai.word_review.service import CLASSIFICATIONS, ReviewError, WordReviewService


class WordReviewPage(w.PageBase):
    COLS = ["N°", "Decisión", "Clasificación", "Párrafo", "Texto propuesto", "Motivo", "Numeral", "Fuente"]
    KEYS = ["seq", "decision", "classification", "paragraph_index", "new_text", "reason", "numeral", "source_document"]

    def __init__(self, master, app):
        super().__init__(master, app)
        self.header("Revisión de Word", "Genera una COPIA del documento con las modificaciones aprobadas, resaltadas "
                                        "en amarillo y con comentarios de Word. El original no se modifica.")
        tb = self.toolbar()
        ctk.CTkLabel(tb, text="Documento Word:").pack(side="left")
        self.doc = w.combo(tb, values=[], width=300)
        self.doc.pack(side="left", padx=4)
        ctk.CTkLabel(tb, text="Análisis:").pack(side="left")
        self.an = w.combo(tb, values=[], width=300)
        self.an.pack(side="left", padx=4)
        self.use_llm = ctk.CTkCheckBox(tb, text="Redactar con IA local")
        self.use_llm.pack(side="left", padx=4)
        ctk.CTkButton(tb, text="Crear revisión y propuestas", command=self.create).pack(side="left", padx=4)
        tb2 = self.toolbar()
        ctk.CTkLabel(tb2, text="Revisión:").pack(side="left")
        self.rv = w.combo(tb2, values=[], width=360, command=lambda _: self.load())
        self.rv.pack(side="left", padx=4)
        for text, cmd in (("Aceptar / editar", lambda: self.decide("aceptada")),
                          ("Rechazar", lambda: self.decide("rechazada")),
                          ("Volver a pendiente", lambda: self.decide("pendiente")),
                          ("Cambio manual", self.manual), ("Generar copia revisada", self.generate)):
            ctk.CTkButton(tb2, text=text, command=cmd, width=10).pack(side="left", padx=3)
        pane = ctk.CTkFrame(self, fg_color="transparent")
        pane.pack(fill="both", expand=True, padx=12, pady=6)
        pane.grid_rowconfigure(0, weight=1)
        self.table = w.Table(pane, self.COLS, [40, 80, 120, 60, 360, 220, 60, 140], height=18,
                             on_select=self.details, on_double=lambda r: self.decide("aceptada"))
        self.table.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.detail = w.detail_pane(pane)
        self._pre_analysis = None

    def svc(self) -> WordReviewService:
        s = self.ctx.settings
        return WordReviewService(self.ctx.db, s.author_name, s.author_initials, self.ctx.username)

    def preselect_analysis(self, aid: int) -> None:
        self._pre_analysis = aid
        self.on_show()

    def on_show(self) -> None:
        self._docs = self.doc_choices((".docx",))
        self.doc.configure(values=list(self._docs))
        self._analyses = {"(sin análisis — solo cambios manuales)": None}
        for a in GapAnalyzer(self.ctx.db).analyses():
            self._analyses[f"[{a['id']}] {a['title']}"] = a["id"]
        self.an.configure(values=list(self._analyses))
        if self._pre_analysis:
            for k, v in self._analyses.items():
                if v == self._pre_analysis:
                    self.an.set(k)
            ev = self.ctx.db.query_one("SELECT d.id FROM compliance_analyses a JOIN document_versions v ON"
                                       " v.id=a.evaluated_version_id JOIN documents d ON d.id=v.document_id"
                                       " WHERE a.id=?", (self._pre_analysis,))
            for k, d in self._docs.items():
                if ev and d["id"] == ev["id"]:
                    self.doc.set(k)
            self._pre_analysis = None
        rows = self.ctx.db.query("SELECT id, created_at, source_path, status FROM word_reviews ORDER BY id DESC")
        self._reviews = {f"[{r['id']}] {r['source_path'].split('/')[-1].split(chr(92))[-1]} — {r['status']}": r["id"]
                         for r in rows}
        self.rv.configure(values=list(self._reviews))
        if self._reviews and self.rv.get() not in self._reviews:
            self.rv.set(next(iter(self._reviews)))
        self.load()

    def current(self) -> int | None:
        return self._reviews.get(self.rv.get()) if hasattr(self, "_reviews") else None

    def create(self) -> None:
        d = self._docs.get(self.doc.get())
        if not d:
            return w.info("Seleccione un documento Word del repositorio.")
        aid = self._analyses.get(self.an.get())
        use_llm = bool(self.use_llm.get())
        path = self.ctx.repository.stored_file(d["current_version_id"])

        def work(job):
            svc = self.svc()
            rid = svc.create_review(path, d["current_version_id"], aid)
            n = 0
            if aid:
                llm = self.ctx.llm() if use_llm else None
                n = svc.propose_from_analysis(rid, aid, llm)
            return rid, n

        def done(res):
            rid, n = res
            self.on_show()
            for k, v in self._reviews.items():
                if v == rid:
                    self.rv.set(k)
            self.load()
            w.info(f"Revisión creada con {n} propuestas pendientes de decisión.")

        self.run("Revisión de Word", work, done)

    def load(self) -> None:
        rid = self.current()
        self.table.set_rows(self.svc().changes(rid) if rid else [], self.KEYS)

    def details(self, row) -> None:
        if not row:
            return
        from sems_ai.word_review.service import build_comment

        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", f"Párrafo ancla ({row['paragraph_index']}): {row['anchor_text']}\n\n"
                                  f"Texto a incorporar:\n{row['new_text']}\n\nComentario de Word:\n{build_comment(row)}")

    def decide(self, decision: str) -> None:
        row = self.table.selected()
        if not row:
            return w.info("Seleccione una propuesta.")
        new_text, cls = None, None
        if decision == "aceptada":
            res = w.FormDialog.ask(self, "Aceptar modificación", [
                {"name": "text", "label": "Texto a incorporar", "type": "longtext", "default": row["new_text"],
                 "required": True},
                {"name": "cls", "label": "Clasificación", "type": "choice", "options": CLASSIFICATIONS,
                 "default": row["classification"], "required": True},
                {"name": "user", "label": "Aprobado por", "default": self.ctx.username, "required": True}],
                note="Revise y edite el texto. Las plantillas marcadas 'EDITAR ANTES DE ACEPTAR' deben reemplazarse.")
            if not res:
                return
            new_text, cls, user = res["text"], res["cls"], res["user"]
        else:
            res = w.FormDialog.ask(self, "Decisión", [{"name": "user", "label": "Responsable",
                                                       "default": self.ctx.username, "required": True}])
            if not res:
                return
            user = res["user"]
        try:
            self.svc().decide(row["id"], decision, user, new_text, cls)
        except ReviewError as exc:
            return w.error(str(exc))
        self.load()

    def manual(self) -> None:
        rid = self.current()
        if not rid:
            return w.info("Cree o seleccione una revisión.")
        paras = self.svc().paragraphs(rid)
        opts = [f"{p['index']}: {p['text'][:90]}" for p in paras if p["text"].strip()]
        res = w.FormDialog.ask(self, "Cambio manual", [
            {"name": "para", "label": "Párrafo ancla", "type": "choice", "options": opts, "required": True},
            {"name": "action", "label": "Acción", "type": "choice", "options": ["insert_after", "append_to"],
             "required": True},
            {"name": "text", "label": "Texto", "type": "longtext", "required": True},
            {"name": "reason", "label": "Motivo", "required": True},
            {"name": "requirement", "label": "Requisito relacionado"},
            {"name": "source", "label": "Fuente documental"},
            {"name": "numeral", "label": "Numeral aplicable"},
            {"name": "just", "label": "Justificación técnica", "type": "longtext"},
            {"name": "cls", "label": "Clasificación", "type": "choice", "options": CLASSIFICATIONS, "required": True}])
        if res:
            self.svc().add_change(rid, res["action"], int(res["para"].split(":")[0]), res["text"], reason=res["reason"],
                                  requirement=res["requirement"], source_document=res["source"],
                                  numeral=res["numeral"] or None, justification=res["just"], classification=res["cls"],
                                  anchor_text=res["para"].split(":", 1)[1].strip())
            self.load()

    def generate(self) -> None:
        rid = self.current()
        if not rid:
            return
        n_acc = sum(1 for c in self.svc().changes(rid) if c["decision"] == "aceptada")
        if not w.confirm(f"Se generará una copia con {n_acc} modificaciones aceptadas. ¿Continuar?"):
            return

        def done(res):
            self.on_show()
            w.info(f"Copia revisada: {res.output_path}\nRegistro de cambios: {res.log_path}\n"
                   f"Modificaciones aplicadas: {res.applied}")

        self.run("Generación de copia revisada", lambda job: self.svc().generate(rid, self.ctx.export_dir), done)
