"""Biblioteca jurídica ambiental y matriz legal.

- Ningún instrumento se declara vigente automáticamente: el estado por defecto es
  "No verificado" y cualquier estado verificado exige responsable y fundamento.
- Las relaciones (reforma, deroga, sustituye...) las registra el usuario a partir
  de fuentes oficiales; el sistema detecta incoherencias y las advierte.
- La aplicación no contiene legislación precargada: el usuario incorpora los
  textos oficiales que haya verificado.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from sems_ai.database.db import Database, now_iso

VALIDITY = ["No verificado", "Vigente (verificado)", "Reformado (verificar texto consolidado)",
            "Derogado parcialmente (verificado)", "Derogado (verificado)", "En revisión"]
VERIFIED = {"Vigente (verificado)", "Derogado parcialmente (verificado)", "Derogado (verificado)",
            "Reformado (verificar texto consolidado)"}
RELATIONS = ["reforma", "deroga", "deroga_parcialmente", "sustituye", "complementa", "reglamenta",
             "posible_contradiccion"]
INSTRUMENT_TYPES = ["Constitución", "Ley / Código", "Reglamento", "Acuerdo Ministerial", "Resolución",
                    "Norma técnica", "Ordenanza", "Licencia ambiental", "Permiso / Autorización", "Otro"]
OBLIGATION_STATUS = ["No evaluado", "Cumple (verificado)", "No cumple (verificado)", "Parcial (verificado)",
                     "No aplica (justificado)", "Requiere validación"]


class LegalError(Exception):
    pass


class LegalService:
    def __init__(self, db: Database, username: str = ""):
        self.db = db
        self.username = username

    # ------------------------------------------------------------ instrumentos
    def add_instrument(self, official_id: str, title: str, **kw) -> int:
        if not official_id.strip() or not title.strip():
            raise LegalError("Identificación oficial y título son obligatorios.")
        if kw.get("validity_status") and kw["validity_status"] != "No verificado":
            raise LegalError("El estado de vigencia se registra con set_validity (requiere verificación).")
        cols = ["official_id", "title", "created_at"]
        vals = [official_id.strip(), title.strip(), now_iso()]
        for k in ("document_id", "instrument_type", "issuer", "publication_date", "official_source",
                  "effective_date", "notes"):
            if kw.get(k) not in (None, ""):
                cols.append(k)
                vals.append(kw[k])
        iid = self.db.execute(f"INSERT INTO legal_instruments({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                              tuple(vals))
        self.db.log("legal.add", "instrument", iid, official_id, self.username)
        return iid

    def update_instrument(self, iid: int, **kw) -> None:
        allowed = ("title", "instrument_type", "issuer", "publication_date", "official_source", "effective_date",
                   "notes", "document_id")
        sets = [(k, v) for k, v in kw.items() if k in allowed]
        if sets:
            self.db.execute(f"UPDATE legal_instruments SET {', '.join(k + '=?' for k, _ in sets)} WHERE id=?",
                            tuple(v for _, v in sets) + (iid,))

    def set_validity(self, iid: int, status: str, verified_by: str, basis: str, verified_at: str | None = None) -> None:
        if status not in VALIDITY:
            raise LegalError(f"Estado no válido: {status}")
        if status in VERIFIED and (not verified_by.strip() or not basis.strip()):
            raise LegalError("Un estado verificado requiere responsable y fundamento (fuente oficial consultada).")
        self.db.execute("UPDATE legal_instruments SET validity_status=?, verified_by=?, verification_basis=?,"
                        " verified_at=? WHERE id=?", (status, verified_by, basis, verified_at or now_iso()[:10], iid))
        self.db.log("legal.validity", "instrument", iid, f"{status} — {basis}", verified_by)

    def instruments(self) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM legal_instruments ORDER BY official_id")]

    def instrument(self, iid: int) -> dict:
        r = self.db.query_one("SELECT * FROM legal_instruments WHERE id=?", (iid,))
        if not r:
            raise LegalError("Instrumento inexistente")
        return dict(r)

    # ------------------------------------------------------------ relaciones
    def add_relation(self, from_id: int, to_id: int, relation: str, articles: str = "", notes: str = "") -> int:
        if relation not in RELATIONS:
            raise LegalError(f"Relación no válida: {relation}")
        if from_id == to_id:
            raise LegalError("Un instrumento no puede relacionarse consigo mismo.")
        return self.db.execute("INSERT OR IGNORE INTO legal_relations(from_instrument_id, to_instrument_id, relation,"
                               " articles, notes) VALUES (?,?,?,?,?)", (from_id, to_id, relation, articles, notes))

    def relations(self) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT r.*, a.official_id from_official, b.official_id to_official FROM legal_relations r"
            " JOIN legal_instruments a ON a.id=r.from_instrument_id JOIN legal_instruments b"
            " ON b.id=r.to_instrument_id ORDER BY r.id")]

    def warnings(self, max_age_days: int = 365) -> list[dict]:
        out: list[dict] = []
        inst = {i["id"]: i for i in self.instruments()}
        for r in self.relations():
            target = inst[r["to_instrument_id"]]
            if r["relation"] == "deroga" and target["validity_status"] == "Vigente (verificado)":
                out.append({"tipo": "Contradicción", "instrumento": target["official_id"],
                            "detalle": f"Marcado como vigente, pero {r['from_official']} lo deroga según la "
                                       "relación registrada. Validar."})
            if r["relation"] in ("reforma", "deroga_parcialmente") and target["validity_status"] == "Vigente (verificado)":
                out.append({"tipo": "Revisión", "instrumento": target["official_id"],
                            "detalle": f"{r['from_official']} lo {r['relation'].replace('_', ' ')}"
                                       f"{' (arts. ' + r['articles'] + ')' if r['articles'] else ''}; verificar "
                                       "que la matriz use el texto vigente."})
            if r["relation"] == "posible_contradiccion":
                out.append({"tipo": "Posible contradicción", "instrumento": f"{r['from_official']} / {r['to_official']}",
                            "detalle": r["notes"] or "Registrada por el usuario. Requiere validación jurídica."})
        by_id: dict[str, list[dict]] = {}
        for i in inst.values():
            by_id.setdefault(i["official_id"].strip().upper(), []).append(i)
        for oid, lst in by_id.items():
            if len(lst) > 1:
                keys = {(x["title"].strip().lower(), x["publication_date"], x["validity_status"]) for x in lst}
                if len(keys) > 1:
                    out.append({"tipo": "Versiones contradictorias", "instrumento": oid,
                                "detalle": f"{len(lst)} registros con la misma identificación y datos distintos. "
                                           "Validar cuál corresponde a la fuente oficial."})
        today = date.today()
        for i in inst.values():
            if i["validity_status"] == "No verificado":
                out.append({"tipo": "Sin verificar", "instrumento": i["official_id"],
                            "detalle": "Vigencia no verificada: no usar como obligación legal verificada."})
            elif i["validity_status"] in VERIFIED and i["verified_at"]:
                try:
                    age = (today - datetime.fromisoformat(i["verified_at"][:10]).date()).days
                except ValueError:
                    age = None
                if age is not None and age > max_age_days:
                    out.append({"tipo": "Verificación desactualizada", "instrumento": i["official_id"],
                                "detalle": f"Última verificación hace {age} días."})
        return out

    # ------------------------------------------------------------ obligaciones
    def add_obligation(self, iid: int, obligation: str, article: str = "", **kw) -> int:
        if not obligation.strip():
            raise LegalError("La obligación no puede estar vacía.")
        cols = ["instrument_id", "obligation", "article"]
        vals = [iid, obligation, article]
        for k in ("applicability", "frequency", "responsible", "evidence_required", "notes"):
            if kw.get(k):
                cols.append(k)
                vals.append(kw[k])
        return self.db.execute(f"INSERT INTO legal_obligations({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                               tuple(vals))

    def evaluate_obligation(self, oid: int, status: str, verified_by: str, evidence_found: str = "",
                            notes: str = "") -> None:
        if status not in OBLIGATION_STATUS:
            raise LegalError(f"Estado no válido: {status}")
        if "verificado" in status or "justificado" in status:
            if not verified_by.strip() or not (evidence_found.strip() or notes.strip()):
                raise LegalError("La evaluación requiere responsable y evidencia o justificación.")
        self.db.execute("UPDATE legal_obligations SET compliance_status=?, verified_by=?, verified_at=?,"
                        " evidence_found=?, notes=? WHERE id=?",
                        (status, verified_by, now_iso()[:10], evidence_found, notes, oid))

    def obligations(self) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT o.*, i.official_id, i.title instrument_title, i.validity_status FROM legal_obligations o"
            " JOIN legal_instruments i ON i.id=o.instrument_id ORDER BY i.official_id, o.id")]

    # ------------------------------------------------------------ exportación
    def export_matrix(self, path: Path) -> Path:
        from sems_ai.excel.builder import WorkbookBuilder

        wb = WorkbookBuilder()
        ws = wb.sheet("Matriz legal")
        start = wb.title_block(ws, "Matriz de requisitos legales", [
            ("Generado", now_iso()),
            ("Aviso", "La vigencia de cada instrumento corresponde a la verificación registrada por el usuario. "
                      "Los instrumentos 'No verificado' no deben considerarse obligaciones legales verificadas.")]) + 1
        rows = [[o["official_id"], o["instrument_title"], o["validity_status"], o["article"], o["obligation"],
                 o["applicability"], o["frequency"], o["responsible"], o["evidence_required"], o["evidence_found"],
                 o["compliance_status"], o["verified_by"], o["verified_at"], o["notes"]] for o in self.obligations()]
        first, last = wb.table(ws, ["Instrumento", "Título", "Estado de vigencia", "Artículo", "Obligación",
                                    "Aplicabilidad", "Frecuencia", "Responsable", "Evidencia requerida",
                                    "Evidencia encontrada", "Estado de cumplimiento", "Verificado por",
                                    "Fecha verificación", "Notas"], rows, start_row=start,
                               widths=[18, 35, 20, 10, 60, 25, 14, 18, 35, 35, 20, 16, 14, 30],
                               validations={11: OBLIGATION_STATUS}, table_name="MatrizLegal")
        wb.color_by_value(ws, f"C{first}:C{last}", {"No verificado": "FFC7CE", "Vigente (verificado)": "C6EFCE",
                                                    "Derogado (verificado)": "D9D9D9"})
        ws2 = wb.sheet("Instrumentos")
        wb.table(ws2, ["Identificación oficial", "Título", "Tipo", "Organismo emisor", "Fecha de publicación",
                       "Fuente oficial", "Entrada en vigor", "Estado de vigencia", "Verificado por",
                       "Fecha verificación", "Fundamento de verificación", "Notas"],
                 [[i["official_id"], i["title"], i["instrument_type"], i["issuer"], i["publication_date"],
                   i["official_source"], i["effective_date"], i["validity_status"], i["verified_by"],
                   i["verified_at"], i["verification_basis"], i["notes"]] for i in self.instruments()],
                 widths=[20, 45, 18, 22, 14, 35, 14, 22, 16, 14, 40, 30],
                 validations={3: INSTRUMENT_TYPES}, table_name="Instrumentos")
        ws3 = wb.sheet("Relaciones")
        wb.table(ws3, ["Instrumento origen", "Relación", "Instrumento afectado", "Artículos", "Notas"],
                 [[r["from_official"], r["relation"], r["to_official"], r["articles"], r["notes"]]
                  for r in self.relations()], widths=[22, 20, 22, 20, 50], validations={2: RELATIONS},
                 table_name="Relaciones")
        ws4 = wb.sheet("Advertencias")
        wb.table(ws4, ["Tipo", "Instrumento", "Detalle"],
                 [[w["tipo"], w["instrumento"], w["detalle"]] for w in self.warnings()], widths=[25, 30, 90],
                 table_name="Advertencias")
        return wb.save(path)
