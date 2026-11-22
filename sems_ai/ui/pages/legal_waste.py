"""Páginas de gestión de desechos y matriz legal."""
from __future__ import annotations

import customtkinter as ctk

from sems_ai.environmental.waste import HAZARD, STAGES, UNITS, WasteError, WasteService
from sems_ai.legal.service import (INSTRUMENT_TYPES, OBLIGATION_STATUS, RELATIONS, VALIDITY, LegalError,
                                   LegalService)
from sems_ai.ui import widgets as w


class WastePage(w.PageBase):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.header("Gestión de desechos", "Trazabilidad desde la generación hasta el destino final. Los formularios "
                                           "son formatos internos y no oficiales salvo que se acredite su fuente.")
        tb = self.toolbar()
        for text, cmd in (("Nueva corriente", self.new_stream), ("Registrar movimiento", self.new_movement),
                          ("Trazabilidad", self.trace), ("Formularios", self.forms), ("Exportar Excel", self.export)):
            ctk.CTkButton(tb, text=text, command=cmd, width=10).pack(side="left", padx=3)
        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, padx=12, pady=6)
        tabs.add("Inventario")
        tabs.add("Movimientos")
        self.streams = w.Table(tabs.tab("Inventario"), ["Código", "Nombre", "Clasificación", "Peligroso",
                                                         "Base de clasificación", "Punto de generación", "Unidad"],
                               [80, 220, 150, 80, 220, 180, 60], height=14)
        self.streams.pack(fill="both", expand=True)
        self.moves = w.Table(tabs.tab("Movimientos"), ["Fecha", "Código", "Etapa", "Cantidad", "Unidad", "Gestor",
                                                        "Manifiesto", "Documento", "Responsable"],
                             [90, 80, 160, 80, 60, 180, 100, 140, 120], height=14)
        self.moves.pack(fill="both", expand=True)

    def svc(self) -> WasteService:
        return WasteService(self.ctx.db, self.ctx.username)

    def on_show(self) -> None:
        svc = self.svc()
        svc.ensure_default_forms()
        self.streams.set_rows(svc.streams(), ["code", "name", "classification", "hazardous", "classification_basis",
                                              "generation_point", "unit"])
        self.moves.set_rows(svc.movements(), ["date", "code", "stage", "quantity", "unit", "manager", "manifest_no",
                                              "document_ref", "responsible"])

    def new_stream(self) -> None:
        res = w.FormDialog.ask(self, "Corriente de desecho", [
            {"name": "code", "label": "Código", "required": True}, {"name": "name", "label": "Nombre", "required": True},
            {"name": "classification", "label": "Clasificación"},
            {"name": "hazardous", "label": "¿Peligroso?", "type": "choice", "options": HAZARD, "default": "Por determinar"},
            {"name": "hazard_characteristics", "label": "Características de peligrosidad"},
            {"name": "classification_basis", "label": "Base documental de la clasificación"},
            {"name": "generation_point", "label": "Punto de generación"},
            {"name": "unit", "label": "Unidad", "type": "choice", "options": UNITS, "default": "kg"},
            {"name": "notes", "label": "Notas", "type": "longtext"}])
        if res:
            try:
                self.svc().add_stream(**res)
            except WasteError as exc:
                return w.error(str(exc))
            self.on_show()

    def new_movement(self) -> None:
        streams = {f"{s['code']} — {s['name']} ({s['unit']})": s for s in self.svc().streams()}
        if not streams:
            return w.info("Registre primero una corriente de desecho.")
        res = w.FormDialog.ask(self, "Movimiento", [
            {"name": "s", "label": "Corriente", "type": "choice", "options": list(streams), "required": True},
            {"name": "date", "label": "Fecha (AAAA-MM-DD)", "required": True},
            {"name": "stage", "label": "Etapa", "type": "choice", "options": STAGES, "required": True},
            {"name": "quantity", "label": "Cantidad (vacío si no se dispone del dato)"},
            {"name": "location", "label": "Ubicación"}, {"name": "manager", "label": "Gestor"},
            {"name": "manifest_no", "label": "N° manifiesto"}, {"name": "transfer_note", "label": "Nota de transferencia"},
            {"name": "document_ref", "label": "Documento soporte"}, {"name": "responsible", "label": "Responsable"},
            {"name": "notes", "label": "Notas", "type": "longtext"}])
        if not res:
            return
        s = streams[res.pop("s")]
        q = res.pop("quantity")
        try:
            qty = float(q.replace(",", ".")) if q else None
            _, warns = self.svc().add_movement(s["id"], res.pop("date"), res.pop("stage"), qty, s["unit"], **res)
        except (WasteError, ValueError) as exc:
            return w.error(str(exc))
        if warns:
            w.info("Movimiento registrado con advertencias:\n" + "\n".join("• " + x for x in warns))
        self.on_show()

    def trace(self) -> None:
        s = self.streams.selected()
        if not s:
            return w.info("Seleccione una corriente en la pestaña Inventario.")
        tr = self.svc().traceability(s["id"])
        lines = [f"Trazabilidad {s['code']} — {s['name']}", ""]
        lines += [f"{m['date']}  {m['stage']:<26} {m['quantity'] if m['quantity'] is not None else 's/d'} {m['unit']}"
                  f"  gestor: {m['manager'] or '-'}  manifiesto: {m['manifest_no'] or '-'}" for m in tr["movimientos"]]
        lines += ["", "Totales: " + ", ".join(f"{k}={v:g}" for k, v in tr["totales"].items()),
                  f"Pendiente de destino final: {tr['pendiente_destino']:g} {s['unit']}"]
        lines += ["⚠ " + x for x in tr["advertencias"]]
        w.info("\n".join(lines), "Trazabilidad")

    def forms(self) -> None:
        svc = self.svc()
        tpls = {("[OFICIAL] " if t["is_official"] else "[Interno] ") + t["name"]: t for t in svc.templates()}
        res = w.FormDialog.ask(self, "Formularios", [
            {"name": "t", "label": "Formulario", "type": "choice", "options": list(tpls), "required": True}])
        if not res:
            return
        t = tpls[res["t"]]
        fields = [{"name": f["name"], "label": f["label"], "required": f.get("required"),
                   "type": {"choice": "choice", "longtext": "longtext"}.get(f.get("type"), "text"),
                   "options": [""] + f.get("options", [])} for f in t["fields"]]
        data = w.FormDialog.ask(self, t["name"], fields,
                                note="" if t["is_official"] else "Formato interno SEMS AI — no oficial.")
        if data:
            try:
                svc.add_record(t["id"], data)
            except WasteError as exc:
                return w.error(str(exc))
            w.info("Registro guardado.")

    def export(self) -> None:
        from sems_ai.excel.builder import unique_path

        p = self.svc().export_excel(unique_path(self.ctx.export_dir, "gestion_desechos", ".xlsx"))
        w.info(f"Exportado: {p}")


class LegalPage(w.PageBase):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.header("Matriz legal", "Biblioteca de instrumentos incorporados por el usuario. Ningún instrumento se "
                                    "declara vigente sin verificación registrada (responsable y fundamento).")
        tb = self.toolbar()
        for text, cmd in (("Nuevo instrumento", self.new_inst), ("Verificar vigencia", self.validity),
                          ("Relación entre normas", self.relation), ("Nueva obligación", self.obligation),
                          ("Evaluar obligación", self.evaluate), ("Exportar matriz", self.export)):
            ctk.CTkButton(tb, text=text, command=cmd, width=10).pack(side="left", padx=3)
        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, padx=12, pady=6)
        for n in ("Instrumentos", "Obligaciones", "Relaciones", "Advertencias"):
            tabs.add(n)
        self.inst = w.Table(tabs.tab("Instrumentos"), ["Identificación", "Título", "Tipo", "Emisor", "Publicación",
                                                        "Vigencia", "Verificado por", "Fecha verif."],
                            [140, 300, 120, 140, 90, 180, 110, 90], height=14)
        self.inst.pack(fill="both", expand=True)
        self.obl = w.Table(tabs.tab("Obligaciones"), ["Instrumento", "Artículo", "Obligación", "Responsable",
                                                       "Estado", "Evidencia"], [140, 70, 420, 120, 150, 220], height=14)
        self.obl.pack(fill="both", expand=True)
        self.rel = w.Table(tabs.tab("Relaciones"), ["Origen", "Relación", "Afectado", "Artículos", "Notas"],
                           [160, 140, 160, 120, 300], height=14)
        self.rel.pack(fill="both", expand=True)
        self.warn = w.Table(tabs.tab("Advertencias"), ["Tipo", "Instrumento", "Detalle"], [170, 170, 650], height=14)
        self.warn.pack(fill="both", expand=True)

    def svc(self) -> LegalService:
        return LegalService(self.ctx.db, self.ctx.username)

    def on_show(self) -> None:
        s = self.svc()
        self.inst.set_rows(s.instruments(), ["official_id", "title", "instrument_type", "issuer", "publication_date",
                                             "validity_status", "verified_by", "verified_at"])
        self.obl.set_rows(s.obligations(), ["official_id", "article", "obligation", "responsible", "compliance_status",
                                            "evidence_found"])
        self.rel.set_rows(s.relations(), ["from_official", "relation", "to_official", "articles", "notes"])
        self.warn.set_rows(s.warnings(), ["tipo", "instrumento", "detalle"])

    def _inst_choices(self) -> dict:
        return {f"{i['official_id']} — {i['title'][:60]}": i["id"] for i in self.svc().instruments()}

    def new_inst(self) -> None:
        legal_docs = {"(ninguno)": None, **{k: v["id"] for k, v in self.doc_choices().items()}}
        res = w.FormDialog.ask(self, "Instrumento jurídico", [
            {"name": "official_id", "label": "Identificación oficial", "required": True},
            {"name": "title", "label": "Título", "required": True},
            {"name": "instrument_type", "label": "Tipo", "type": "choice", "options": INSTRUMENT_TYPES},
            {"name": "issuer", "label": "Organismo emisor"},
            {"name": "publication_date", "label": "Fecha de publicación"},
            {"name": "official_source", "label": "Fuente oficial (p.ej. Registro Oficial N°)"},
            {"name": "effective_date", "label": "Fecha de entrada en vigor"},
            {"name": "doc", "label": "Texto en el repositorio", "type": "choice", "options": list(legal_docs)},
            {"name": "notes", "label": "Notas", "type": "longtext"}],
            note="Registre solo instrumentos cuyo texto oficial disponga. El estado inicial es 'No verificado'.")
        if res:
            doc = legal_docs.get(res.pop("doc"))
            try:
                self.svc().add_instrument(res.pop("official_id"), res.pop("title"), document_id=doc, **res)
            except LegalError as exc:
                return w.error(str(exc))
            self.on_show()

    def validity(self) -> None:
        ch = self._inst_choices()
        res = w.FormDialog.ask(self, "Verificación de vigencia", [
            {"name": "i", "label": "Instrumento", "type": "choice", "options": list(ch), "required": True},
            {"name": "status", "label": "Estado", "type": "choice", "options": VALIDITY, "required": True},
            {"name": "by", "label": "Verificado por", "default": self.ctx.username},
            {"name": "basis", "label": "Fundamento (fuente oficial consultada, fecha)", "type": "longtext"}])
        if res:
            try:
                self.svc().set_validity(ch[res["i"]], res["status"], res["by"], res["basis"])
            except LegalError as exc:
                return w.error(str(exc))
            self.on_show()

    def relation(self) -> None:
        ch = self._inst_choices()
        res = w.FormDialog.ask(self, "Relación entre instrumentos", [
            {"name": "a", "label": "Instrumento origen", "type": "choice", "options": list(ch), "required": True},
            {"name": "rel", "label": "Relación", "type": "choice", "options": RELATIONS, "required": True},
            {"name": "b", "label": "Instrumento afectado", "type": "choice", "options": list(ch), "required": True},
            {"name": "art", "label": "Artículos"}, {"name": "notes", "label": "Notas / fuente", "type": "longtext"}])
        if res:
            try:
                self.svc().add_relation(ch[res["a"]], ch[res["b"]], res["rel"], res["art"], res["notes"])
            except LegalError as exc:
                return w.error(str(exc))
            self.on_show()

    def obligation(self) -> None:
        ch = self._inst_choices()
        res = w.FormDialog.ask(self, "Obligación legal", [
            {"name": "i", "label": "Instrumento", "type": "choice", "options": list(ch), "required": True},
            {"name": "article", "label": "Artículo / numeral (según texto oficial)"},
            {"name": "obligation", "label": "Obligación", "type": "longtext", "required": True},
            {"name": "applicability", "label": "Aplicabilidad"}, {"name": "frequency", "label": "Frecuencia"},
            {"name": "responsible", "label": "Responsable"},
            {"name": "evidence_required", "label": "Evidencia requerida"}])
        if res:
            self.svc().add_obligation(ch[res.pop("i")], res.pop("obligation"), res.pop("article"), **res)
            self.on_show()

    def evaluate(self) -> None:
        o = self.obl.selected()
        if not o:
            return w.info("Seleccione una obligación en la pestaña Obligaciones.")
        res = w.FormDialog.ask(self, "Evaluar obligación", [
            {"name": "status", "label": "Estado", "type": "choice", "options": OBLIGATION_STATUS, "required": True},
            {"name": "by", "label": "Verificado por", "default": self.ctx.username},
            {"name": "ev", "label": "Evidencia encontrada", "type": "longtext", "default": o["evidence_found"]},
            {"name": "notes", "label": "Notas / justificación", "type": "longtext", "default": o["notes"]}])
        if res:
            try:
                self.svc().evaluate_obligation(o["id"], res["status"], res["by"], res["ev"], res["notes"])
            except LegalError as exc:
                return w.error(str(exc))
            self.on_show()

    def export(self) -> None:
        from sems_ai.excel.builder import unique_path

        p = self.svc().export_matrix(unique_path(self.ctx.export_dir, "matriz_legal", ".xlsx"))
        w.info(f"Exportado: {p}")
