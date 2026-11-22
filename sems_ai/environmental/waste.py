"""Gestión ambiental de desechos: corrientes, movimientos, trazabilidad y formularios.

Los formularios incluidos son FORMATOS INTERNOS de SEMS AI. No representan
formatos oficiales de ninguna autoridad o empresa. Un formulario solo puede
marcarse como oficial si se indica la fuente documental que lo respalda.
"""
from __future__ import annotations

import json
from pathlib import Path

from sems_ai.database.db import Database, now_iso

STAGES = ["Generación", "Almacenamiento temporal", "Transporte", "Tratamiento", "Disposición final"]
HAZARD = ["Sí", "No", "Por determinar"]
UNITS = ["kg", "t", "L", "m3", "gal", "bbl", "unidades"]

DEFAULT_FORMS = {
    "Inspección de almacenamiento temporal (interno)": {
        "module": "desechos",
        "fields": [
            {"name": "fecha", "label": "Fecha", "type": "date", "required": True},
            {"name": "area", "label": "Área / instalación", "type": "text", "required": True},
            {"name": "inspector", "label": "Inspector", "type": "text", "required": True},
            {"name": "cubierta", "label": "¿Cuenta con cubierta?", "type": "choice",
             "options": ["Sí", "No", "No aplica"]},
            {"name": "senalizacion", "label": "¿Señalización visible?", "type": "choice",
             "options": ["Sí", "No", "No aplica"]},
            {"name": "contencion", "label": "¿Contención secundaria operativa?", "type": "choice",
             "options": ["Sí", "No", "No aplica"]},
            {"name": "observaciones", "label": "Observaciones", "type": "longtext"},
        ]},
    "Evaluación de gestor ambiental (interno)": {
        "module": "desechos",
        "fields": [
            {"name": "gestor", "label": "Gestor", "type": "text", "required": True},
            {"name": "fecha", "label": "Fecha de evaluación", "type": "date", "required": True},
            {"name": "licencia", "label": "Licencia / autorización (referencia documental)", "type": "text"},
            {"name": "vigencia_verificada", "label": "¿Vigencia de licencia verificada?", "type": "choice",
             "options": ["Sí", "No", "Pendiente"]},
            {"name": "evaluador", "label": "Evaluador", "type": "text", "required": True},
            {"name": "resultado", "label": "Resultado", "type": "longtext"},
        ]},
    "Registro de capacitación (interno)": {
        "module": "desechos",
        "fields": [
            {"name": "fecha", "label": "Fecha", "type": "date", "required": True},
            {"name": "tema", "label": "Tema", "type": "text", "required": True},
            {"name": "instructor", "label": "Instructor", "type": "text"},
            {"name": "participantes", "label": "N° de participantes", "type": "number"},
            {"name": "evidencia", "label": "Evidencia (registro de asistencia)", "type": "text"},
        ]},
    "Iniciativa de minimización (interno)": {
        "module": "desechos",
        "fields": [
            {"name": "corriente", "label": "Corriente de desecho", "type": "text", "required": True},
            {"name": "medida", "label": "Medida propuesta", "type": "longtext", "required": True},
            {"name": "responsable", "label": "Responsable", "type": "text"},
            {"name": "linea_base", "label": "Línea base (dato medido)", "type": "number"},
            {"name": "estado", "label": "Estado", "type": "choice", "options": ["Propuesta", "En curso", "Cerrada"]},
        ]},
}


class WasteError(Exception):
    pass


class WasteService:
    def __init__(self, db: Database, username: str = ""):
        self.db = db
        self.username = username

    # ------------------------------------------------------------ corrientes
    def add_stream(self, code: str, name: str, hazardous: str = "Por determinar", classification: str = "",
                   classification_basis: str = "", hazard_characteristics: str = "", generation_point: str = "",
                   unit: str = "kg", notes: str = "") -> int:
        if hazardous not in HAZARD:
            raise WasteError(f"Valor de peligrosidad no válido: {hazardous}")
        if hazardous != "Por determinar" and not classification_basis.strip():
            raise WasteError("Para declarar la peligrosidad indique la base documental (norma, análisis, ficha).")
        if not code.strip() or not name.strip():
            raise WasteError("Código y nombre son obligatorios.")
        return self.db.execute(
            "INSERT INTO waste_streams(code, name, classification, hazardous, hazard_characteristics,"
            " classification_basis, generation_point, unit, notes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (code.strip(), name.strip(), classification, hazardous, hazard_characteristics, classification_basis,
             generation_point, unit, notes, now_iso()))

    def streams(self) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM waste_streams ORDER BY code")]

    # ------------------------------------------------------------ movimientos
    def add_movement(self, stream_id: int, date: str, stage: str, quantity: float | None = None, unit: str = "",
                     **kw) -> tuple[int, list[str]]:
        if stage not in STAGES:
            raise WasteError(f"Etapa no válida: {stage}")
        if quantity is not None and quantity < 0:
            raise WasteError("La cantidad no puede ser negativa.")
        s = self.db.query_one("SELECT * FROM waste_streams WHERE id=?", (stream_id,))
        if not s:
            raise WasteError("Corriente de desecho inexistente")
        unit = unit or s["unit"]
        if unit != s["unit"]:
            raise WasteError(f"Unidad distinta a la de la corriente ({s['unit']}); registre en {s['unit']}.")
        warnings = []
        if stage == "Transporte" and s["hazardous"] == "Sí" and not kw.get("manifest_no"):
            warnings.append("Transporte de desecho peligroso sin número de manifiesto registrado.")
        if stage in ("Tratamiento", "Disposición final") and not kw.get("manager"):
            warnings.append(f"{stage} sin gestor registrado.")
        if quantity is None:
            warnings.append("Cantidad no registrada: el balance quedará incompleto.")
        cols = ["stream_id", "date", "stage", "quantity", "unit", "created_at"]
        vals = [stream_id, date, stage, quantity, unit, now_iso()]
        for k in ("location", "manager", "manifest_no", "transfer_note", "document_ref", "responsible", "notes"):
            if kw.get(k):
                cols.append(k)
                vals.append(kw[k])
        mid = self.db.execute(f"INSERT INTO waste_movements({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                              tuple(vals))
        return mid, warnings

    def movements(self, stream_id: int | None = None) -> list[dict]:
        sql = ("SELECT m.*, s.code, s.name, s.hazardous FROM waste_movements m JOIN waste_streams s"
               " ON s.id=m.stream_id")
        params: tuple = ()
        if stream_id:
            sql += " WHERE m.stream_id=?"
            params = (stream_id,)
        return [dict(r) for r in self.db.query(sql + " ORDER BY m.date, m.id", params)]

    def traceability(self, stream_id: int) -> dict:
        mv = self.movements(stream_id)
        tot = {st: 0.0 for st in STAGES}
        missing = 0
        for m in mv:
            if m["quantity"] is None:
                missing += 1
            else:
                tot[m["stage"]] += m["quantity"]
        closed = tot["Tratamiento"] + tot["Disposición final"]
        warnings = []
        if closed > tot["Generación"] + 1e-9:
            warnings.append("La cantidad tratada/dispuesta supera la generada registrada: revisar registros.")
        if missing:
            warnings.append(f"{missing} movimientos sin cantidad.")
        return {"movimientos": mv, "totales": tot, "pendiente_destino": round(tot["Generación"] - closed, 6),
                "advertencias": warnings}

    # ------------------------------------------------------------ formularios configurables
    def ensure_default_forms(self) -> None:
        for name, spec in DEFAULT_FORMS.items():
            self.db.execute("INSERT OR IGNORE INTO form_templates(name, module, fields_json, is_official, created_at)"
                            " VALUES (?,?,?,0,?)", (name, spec["module"], json.dumps(spec["fields"], ensure_ascii=False),
                                                    now_iso()))

    def create_template(self, name: str, module: str, fields: list[dict], is_official: bool = False,
                        official_source: str = "") -> int:
        if is_official and not official_source.strip():
            raise WasteError("Un formulario solo puede marcarse como oficial indicando su fuente documental.")
        for f in fields:
            if not f.get("name") or not f.get("label"):
                raise WasteError("Cada campo requiere 'name' y 'label'.")
        return self.db.execute("INSERT INTO form_templates(name, module, fields_json, is_official, official_source,"
                               " created_at) VALUES (?,?,?,?,?,?)",
                               (name, module, json.dumps(fields, ensure_ascii=False), int(is_official),
                                official_source, now_iso()))

    def templates(self, module: str | None = None) -> list[dict]:
        rows = self.db.query("SELECT * FROM form_templates" + (" WHERE module=?" if module else "") + " ORDER BY name",
                             (module,) if module else ())
        out = []
        for r in rows:
            d = dict(r)
            d["fields"] = json.loads(d["fields_json"])
            out.append(d)
        return out

    def add_record(self, template_id: int, data: dict) -> int:
        t = next((x for x in self.templates() if x["id"] == template_id), None)
        if t is None:
            raise WasteError("Formulario inexistente")
        for f in t["fields"]:
            v = data.get(f["name"])
            if f.get("required") and (v is None or str(v).strip() == ""):
                raise WasteError(f"Campo obligatorio vacío: {f['label']}")
            if f.get("type") == "choice" and v not in (None, "") and v not in f.get("options", []):
                raise WasteError(f"Valor no permitido en {f['label']}: {v}")
            if f.get("type") == "number" and v not in (None, ""):
                try:
                    float(v)
                except (TypeError, ValueError) as exc:
                    raise WasteError(f"{f['label']} debe ser numérico") from exc
        return self.db.execute("INSERT INTO form_records(template_id, data_json, created_at, created_by)"
                               " VALUES (?,?,?,?)", (template_id, json.dumps(data, ensure_ascii=False), now_iso(),
                                                     self.username))

    def records(self, template_id: int) -> list[dict]:
        return [dict(r) | {"data": json.loads(r["data_json"])} for r in
                self.db.query("SELECT * FROM form_records WHERE template_id=? ORDER BY id", (template_id,))]

    # ------------------------------------------------------------ exportación
    def export_excel(self, path: Path) -> Path:
        from sems_ai.excel.builder import WorkbookBuilder

        wb = WorkbookBuilder()
        streams = self.streams()
        ws = wb.sheet("Inventario")
        start = wb.title_block(ws, "Inventario de corrientes de desechos", [
            ("Generado", now_iso()), ("Aviso", "Formato interno SEMS AI; no es un formato oficial de autoridad "
                                               "ni empresa.")]) + 1
        wb.table(ws, ["Código", "Nombre", "Clasificación", "Peligroso", "Características de peligrosidad",
                      "Base de clasificación", "Punto de generación", "Unidad", "Notas"],
                 [[s["code"], s["name"], s["classification"], s["hazardous"], s["hazard_characteristics"],
                   s["classification_basis"], s["generation_point"], s["unit"], s["notes"]] for s in streams],
                 start_row=start, widths=[10, 30, 20, 12, 30, 35, 25, 9, 30],
                 validations={4: HAZARD, 8: UNITS}, table_name="Inventario", extra_blank_rows=10)
        ms = wb.sheet("Movimientos")
        mv = self.movements()
        first, last = wb.table(ms, ["Fecha", "Código", "Corriente", "Etapa", "Cantidad", "Unidad", "Ubicación",
                                    "Gestor", "N° manifiesto", "Nota de transferencia", "Documento soporte",
                                    "Responsable", "Notas"],
                               [[m["date"], m["code"], m["name"], m["stage"], m["quantity"], m["unit"], m["location"],
                                 m["manager"], m["manifest_no"], m["transfer_note"], m["document_ref"],
                                 m["responsible"], m["notes"]] for m in mv],
                               widths=[12, 10, 28, 22, 11, 9, 20, 22, 14, 16, 20, 16, 30],
                               validations={4: STAGES, 6: UNITS}, table_name="Movimientos", extra_blank_rows=50)
        wb.highlight_formula(ms, f"I{first}:I{last}",
                             f'AND($D{first}="Transporte",$I{first}="",COUNTIFS(Inventario!$A:$A,$B{first},'
                             f'Inventario!$D:$D,"Sí")>0)', "FFC7CE")
        ind = wb.sheet("Indicadores")
        ind["A1"] = "Balance por corriente (fórmulas SUMIFS sobre 'Movimientos')"
        heads = ["Código", "Unidad"] + STAGES + ["Pendiente de destino final"]
        for j, h in enumerate(heads, start=1):
            ind.cell(row=3, column=j, value=h)
        for i, s in enumerate(streams, start=4):
            ind.cell(row=i, column=1, value=s["code"])
            ind.cell(row=i, column=2, value=s["unit"])
            for j, st in enumerate(STAGES, start=3):
                ind.cell(row=i, column=j,
                         value=f'=SUMIFS(Movimientos!$E${first}:$E${last},Movimientos!$B${first}:$B${last},$A{i},'
                               f'Movimientos!$D${first}:$D${last},"{st}")')
            ind.cell(row=i, column=8, value=f"=C{i}-F{i}-G{i}")
        for j in range(1, 9):
            ind.column_dimensions[chr(64 + j)].width = 18
        return wb.save(path)
