"""Página de auditorías SEMS."""
from __future__ import annotations

from tkinter import filedialog

import customtkinter as ctk

from sems_ai.audits.service import AuditError, AuditService, Methodology
from sems_ai.ui import widgets as w


def _split(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split(";") if x.strip()]


class AuditsPage(w.PageBase):
    COLS = ["ID", "Origen", "Numeral", "Pregunta", "Resultado", "Evidencia encontrada", "Hallazgo", "Responsable"]
    KEYS = ["qid", "origin", "numeral", "question", "result", "evidence_found", "finding", "responsible"]

    def __init__(self, master, app):
        super().__init__(master, app)
        self.header("Auditorías SEMS", "Preguntas oficiales solo desde checklists identificados; las complementarias "
                                       "se etiquetan como tales. Métricas según la metodología configurada.")
        tb = self.toolbar()
        self.sel = w.combo(tb, values=[], width=380, command=lambda _: self.load())
        self.sel.pack(side="left", padx=4)
        for text, cmd in (("Nueva auditoría", self.new_audit), ("Datos", self.edit_audit),
                          ("Metodología", self.edit_methodology), ("Importar checklist oficial", self.import_checklist),
                          ("Preguntas complementarias", self.complementary)):
            ctk.CTkButton(tb, text=text, command=cmd, width=10).pack(side="left", padx=3)
        tb2 = self.toolbar()
        for text, cmd in (("Registrar respuesta", self.record), ("Adjuntar evidencia", self.evidence),
                          ("Emitir hallazgo", self.finding), ("Acción correctiva", self.action),
                          ("Seguimiento", self.follow_up), ("Exportar Excel", self.export),
                          ("Informe Word", self.report)):
            ctk.CTkButton(tb2, text=text, command=cmd, width=10).pack(side="left", padx=3)
        self.meth = ctk.CTkLabel(self, text="", anchor="w", text_color="#B36B00", wraplength=1100, justify="left")
        self.meth.pack(fill="x", padx=12)
        self.table = w.Table(self, self.COLS, [80, 100, 60, 440, 110, 220, 80, 110], height=16,
                             on_double=lambda r: self.record())
        self.table.pack(fill="both", expand=True, padx=12, pady=6)
        self.counts = ctk.CTkLabel(self, text="", anchor="w")
        self.counts.pack(fill="x", padx=12, pady=(0, 6))

    def svc(self) -> AuditService:
        return AuditService(self.ctx.db, self.ctx.username)

    def on_show(self) -> None:
        self._audits = {f"[{a['id']}] {a['title']} — {a['asset'] or ''}": a["id"] for a in self.svc().audits()}
        self.sel.configure(values=list(self._audits))
        if self._audits and self.sel.get() not in self._audits:
            self.sel.set(next(iter(self._audits)))
        self.load()

    def current(self) -> int | None:
        return self._audits.get(self.sel.get())

    def load(self) -> None:
        aid = self.current()
        if not aid:
            self.table.set_rows([])
            self.meth.configure(text="Cree una auditoría para comenzar.")
            return
        svc = self.svc()
        m = svc.methodology(aid)
        self.meth.configure(text=f"Metodología: {m.name}. " + (f"Fuente: {m.source}." if m.source else m.notes))
        self.table.set_rows(svc.questions(aid), self.KEYS)
        self.counts.configure(text="  |  ".join(f"{k}: {v}" for k, v in svc.counts(aid).items()))

    def _need(self) -> int | None:
        aid = self.current()
        if not aid:
            w.info("Seleccione o cree una auditoría.")
        return aid

    AUDIT_FORM = [("title", "Título", True), ("code", "Código", False), ("standard", "Estándar", False),
                  ("sop", "SOP", False), ("asset", "Activo", False), ("scope", "Alcance", False),
                  ("start_date", "Fecha inicio", False), ("end_date", "Fecha fin", False),
                  ("lead_auditor", "Auditor líder", False), ("auditors", "Equipo auditor", False),
                  ("auditees", "Auditados", False)]

    def new_audit(self) -> None:
        res = w.FormDialog.ask(self, "Nueva auditoría", [{"name": n, "label": l, "required": r}
                                                         for n, l, r in self.AUDIT_FORM])
        if res:
            title = res.pop("title")
            self.svc().create_audit(title, **{k: v for k, v in res.items() if v})
            self.on_show()

    def edit_audit(self) -> None:
        aid = self._need()
        if not aid:
            return
        a = self.svc().audit(aid)
        fields = [{"name": n, "label": l, "required": r, "default": a[n]} for n, l, r in self.AUDIT_FORM]
        fields.append({"name": "status", "label": "Estado", "type": "choice", "default": a["status"],
                       "options": ["Planificada", "En ejecución", "Informe emitido", "Seguimiento", "Cerrada"]})
        res = w.FormDialog.ask(self, "Datos de la auditoría", fields)
        if res:
            self.svc().update_audit(aid, **res)
            self.on_show()

    def edit_methodology(self) -> None:
        aid = self._need()
        if not aid:
            return
        m = self.svc().methodology(aid)
        res = w.FormDialog.ask(self, "Metodología de auditoría", [
            {"name": "name", "label": "Nombre", "default": m.name, "required": True},
            {"name": "source", "label": "Fuente documental (documento y numeral)", "default": m.source},
            {"name": "opts", "label": "Opciones de respuesta (separadas por ;)", "default": "; ".join(m.response_options),
             "required": True},
            {"name": "types", "label": "Tipos de hallazgo (separados por ;)", "default": "; ".join(m.finding_types),
             "required": True},
            {"name": "pct", "label": "Calcular % de conformidad (solo si la fuente lo define)", "type": "bool",
             "default": m.allow_percentage},
            {"name": "ok", "label": "Respuestas conformes (;)", "default": "; ".join(m.compliant_values)},
            {"name": "nok", "label": "Respuestas no conformes (;)", "default": "; ".join(m.noncompliant_values)},
            {"name": "notes", "label": "Notas", "type": "longtext", "default": m.notes}],
            note="Conserve el sistema de respuestas del estándar aplicable. Sin fuente documental no se calculan "
                 "porcentajes ni ponderaciones.")
        if res:
            nm = Methodology(res["name"], res["source"], _split(res["opts"]), _split(res["ok"]), _split(res["nok"]),
                             res["pct"], _split(res["types"]), res["notes"])
            try:
                self.svc().set_methodology(aid, nm)
            except AuditError as exc:
                return w.error(str(exc))
            self.load()

    def import_checklist(self) -> None:
        aid = self._need()
        if not aid:
            return
        p = filedialog.askopenfilename(title="Checklist oficial (Excel)", filetypes=[("Excel", "*.xlsx *.xlsm")])
        if not p:
            return
        res = w.FormDialog.ask(self, "Columnas del checklist", [
            {"name": "ref", "label": "Identificación del checklist oficial", "required": True},
            {"name": "sheet", "label": "Hoja (vacío = primera)"},
            {"name": "header_row", "label": "Fila de encabezado", "default": "1", "required": True},
            {"name": "qid", "label": "Columna ID", "default": "A"},
            {"name": "numeral", "label": "Columna numeral", "default": "B"},
            {"name": "question", "label": "Columna pregunta", "default": "C", "required": True},
            {"name": "auditor_guide", "label": "Columna guía del auditor"},
            {"name": "required_evidence", "label": "Columna evidencia requerida"},
            {"name": "source", "label": "Columna fuente"}],
            note="Las preguntas se copiarán literalmente y se registrará el archivo y su SHA-256 como origen.")
        if not res:
            return
        cols = {k: res[k].upper() for k in ("qid", "numeral", "question", "auditor_guide", "required_evidence", "source")
                if res.get(k)}
        try:
            n = self.svc().import_official_checklist(aid, p, cols, res["sheet"] or None, int(res["header_row"]),
                                                     res["ref"])
        except (AuditError, ValueError, KeyError) as exc:
            return w.error(str(exc))
        w.info(f"{n} preguntas oficiales importadas.")
        self.load()

    def complementary(self) -> None:
        aid = self._need()
        if not aid:
            return
        docs = self.doc_choices()
        res = w.FormDialog.ask(self, "Preguntas complementarias", [
            {"name": "doc", "label": "Procedimiento fuente", "type": "choice", "options": list(docs), "required": True},
            {"name": "excl", "label": "Excluir numerales ya cubiertos por el checklist oficial (;)"}],
            note="Se generarán preguntas a partir de los requisitos extraídos. Se etiquetarán como "
                 "complementarias (no oficiales).")
        if res and res["doc"] in docs:
            n = self.svc().generate_complementary(aid, docs[res["doc"]]["current_version_id"], set(_split(res["excl"])))
            w.info(f"{n} preguntas complementarias generadas.")
            self.load()

    def _q(self) -> dict | None:
        q = self.table.selected()
        if not q:
            w.info("Seleccione una pregunta.")
        return q

    def record(self) -> None:
        q = self._q()
        if not q:
            return
        m = self.svc().methodology(q["audit_id"])
        res = w.FormDialog.ask(self, f"Respuesta — {q['qid']}", [
            {"name": "result", "label": "Resultado", "type": "choice", "options": [""] + m.response_options,
             "default": q["result"]},
            {"name": "translation", "label": "Traducción técnica", "type": "longtext", "default": q["translation"]},
            {"name": "evidence_found", "label": "Evidencia encontrada", "type": "longtext",
             "default": q["evidence_found"]},
            {"name": "observations", "label": "Observaciones", "type": "longtext", "default": q["observations"]},
            {"name": "responsible", "label": "Responsable", "default": q["responsible"]},
            {"name": "close_date", "label": "Fecha de cierre", "default": q["close_date"]},
            {"name": "effectiveness", "label": "Verificación de eficacia", "default": q["effectiveness"]}],
            note=f"Pregunta ({q['origin']}): {q['question']}")
        if res:
            try:
                self.svc().record(q["id"], **res)
            except AuditError as exc:
                return w.error(str(exc))
            self.load()

    def evidence(self) -> None:
        q = self._q()
        if not q:
            return
        docs = {"(ninguno)": None, **{k: v["id"] for k, v in self.doc_choices().items()}}
        res = w.FormDialog.ask(self, "Evidencia", [
            {"name": "doc", "label": "Documento del repositorio", "type": "choice", "options": list(docs)},
            {"name": "reference", "label": "Referencia (registro, folio…)"},
            {"name": "desc", "label": "Descripción", "type": "longtext", "required": True}],
            note="Para adjuntar un archivo nuevo, impórtelo primero al repositorio (categoría Evidencias).")
        if res:
            self.svc().add_evidence(q["audit_id"], res["desc"], q["id"], docs.get(res["doc"]), res["reference"])
            w.info("Evidencia registrada.")

    def finding(self) -> None:
        q = self._q()
        if not q:
            return
        m = self.svc().methodology(q["audit_id"])
        res = w.FormDialog.ask(self, "Hallazgo", [
            {"name": "type", "label": "Tipo", "type": "choice", "options": m.finding_types, "required": True},
            {"name": "desc", "label": "Descripción", "type": "longtext", "required": True},
            {"name": "req", "label": "Requisito", "default": f"{q['source'] or ''} {q['numeral'] or ''}".strip()},
            {"name": "ev", "label": "Evidencia", "type": "longtext", "default": q["evidence_found"]},
            {"name": "resp", "label": "Responsable"}, {"name": "due", "label": "Fecha compromiso"}])
        if res:
            self.svc().add_finding(q["audit_id"], res["desc"], res["type"], q["id"], res["req"], res["ev"],
                                   res["resp"], res["due"])
            self.load()

    def action(self) -> None:
        aid = self._need()
        if not aid:
            return
        f = {f"{x['ref']}: {x['description'][:70]}": x["id"] for x in self.svc().findings(aid)}
        if not f:
            return w.info("No hay hallazgos registrados.")
        res = w.FormDialog.ask(self, "Acción correctiva", [
            {"name": "f", "label": "Hallazgo", "type": "choice", "options": list(f), "required": True},
            {"name": "cause", "label": "Causa raíz", "type": "longtext"},
            {"name": "action", "label": "Acción", "type": "longtext", "required": True},
            {"name": "resp", "label": "Responsable"}, {"name": "due", "label": "Fecha compromiso"}])
        if res:
            self.svc().add_action(f[res["f"]], res["action"], res["resp"], res["due"], res["cause"])
            w.info("Acción registrada.")

    def follow_up(self) -> None:
        aid = self._need()
        if not aid:
            return
        acts = {f"AC-{a['id']} ({a['finding_ref']}): {a['action'][:60]} [{a['status']}]": a for a in
                self.svc().actions(aid)}
        if not acts:
            return w.info("No hay acciones correctivas.")
        res = w.FormDialog.ask(self, "Seguimiento de acción", [
            {"name": "a", "label": "Acción", "type": "choice", "options": list(acts), "required": True},
            {"name": "status", "label": "Estado", "type": "choice", "required": True,
             "options": ["Abierta", "En proceso", "Cerrada", "Cerrada - eficaz", "Cerrada - no eficaz"]},
            {"name": "closed", "label": "Fecha de cierre"},
            {"name": "eff", "label": "Verificación de eficacia", "type": "longtext"}])
        if res:
            self.svc().update_action(acts[res["a"]]["id"], status=res["status"], closed_date=res["closed"] or None,
                                     effectiveness_check=res["eff"] or None)
            w.info("Seguimiento registrado.")

    def export(self) -> None:
        from sems_ai.audits.excel_export import export_audit
        from sems_ai.excel.builder import unique_path

        aid = self._need()
        if aid:
            p = export_audit(self.ctx.db, aid, unique_path(self.ctx.export_dir, f"auditoria_{aid}", ".xlsx"))
            w.info(f"Exportado: {p}")

    def report(self) -> None:
        from sems_ai.excel.builder import unique_path
        from sems_ai.reports.technical_report import audit_report

        aid = self._need()
        if aid:
            p = audit_report(self.ctx.db, aid, unique_path(self.ctx.export_dir, f"informe_auditoria_{aid}", ".docx"))
            w.info(f"Informe generado: {p}")
