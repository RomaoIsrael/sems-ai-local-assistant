"""Auditorías SEMS: planificación, checklist, respuestas, evidencias, hallazgos y acciones.

Reglas:
- Preguntas OFICIALES: solo se crean importándolas de un checklist identificado
  (``origin_reference`` obligatorio). Se copian literalmente.
- Preguntas COMPLEMENTARIAS: propuestas a partir de requisitos del procedimiento;
  siempre etiquetadas como tales. Nunca se presentan como oficiales.
- El sistema de respuestas, tipos de hallazgo y métricas provienen de la
  metodología configurada. Si no hay metodología documentada, se usa una
  configuración PROVISIONAL claramente marcada y sin porcentajes ni ponderaciones.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sems_ai.database.db import Database, now_iso
from sems_ai.document_processing.safety import sha256_file


class AuditError(Exception):
    pass


@dataclass
class Methodology:
    name: str = "Configuración provisional (sin metodología documentada)"
    source: str = ""  # documento/numeral que define la metodología; vacío = provisional
    response_options: list[str] = field(default_factory=lambda: [
        "Conforme", "No conforme", "Observación", "No aplica", "No verificado"])
    compliant_values: list[str] = field(default_factory=list)
    noncompliant_values: list[str] = field(default_factory=list)
    allow_percentage: bool = False
    finding_types: list[str] = field(default_factory=lambda: ["No conformidad", "Observación",
                                                              "Oportunidad de mejora"])
    notes: str = ("PROVISIONAL: reemplace las opciones de respuesta y tipos de hallazgo por los definidos en el "
                  "procedimiento/checklist oficial. No se calculan porcentajes ni ponderaciones.")

    @property
    def provisional(self) -> bool:
        return not self.source.strip()

    def validate(self) -> None:
        if not self.response_options:
            raise AuditError("La metodología debe definir opciones de respuesta.")
        if self.allow_percentage:
            if self.provisional:
                raise AuditError("Solo se permiten porcentajes si la metodología cita su fuente documental.")
            if not self.compliant_values or not self.noncompliant_values:
                raise AuditError("Para porcentajes defina valores conformes y no conformes.")
            unknown = set(self.compliant_values + self.noncompliant_values) - set(self.response_options)
            if unknown:
                raise AuditError(f"Valores no incluidos en las opciones de respuesta: {unknown}")

    @classmethod
    def from_json(cls, s: str) -> "Methodology":
        return cls(**json.loads(s))

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


AUDIT_FIELDS = ("code", "title", "standard", "sop", "asset", "scope", "start_date", "end_date", "lead_auditor",
                "auditors", "auditees", "status")
QUESTION_EDITABLE = ("translation", "auditor_guide", "required_evidence", "result", "evidence_found",
                     "observations", "finding", "responsible", "close_date", "effectiveness")


class AuditService:
    def __init__(self, db: Database, username: str = ""):
        self.db = db
        self.username = username

    # ---------------------------------------------------------------- auditoría
    def create_audit(self, title: str, methodology: Methodology | None = None, **fields_) -> int:
        m = methodology or Methodology()
        m.validate()
        if not title.strip():
            raise AuditError("La auditoría requiere un título.")
        cols = ["title", "methodology_json", "created_at", "created_by"]
        vals = [title, m.to_json(), now_iso(), self.username]
        for k, v in fields_.items():
            if k in AUDIT_FIELDS and k != "title":
                cols.append(k)
                vals.append(v)
        aid = self.db.execute(f"INSERT INTO audits({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                              tuple(vals))
        self.db.log("audit.create", "audit", aid, title, self.username)
        return aid

    def update_audit(self, audit_id: int, **fields_) -> None:
        sets = [(k, v) for k, v in fields_.items() if k in AUDIT_FIELDS]
        if sets:
            self.db.execute(f"UPDATE audits SET {', '.join(k + '=?' for k, _ in sets)} WHERE id=?",
                            tuple(v for _, v in sets) + (audit_id,))

    def set_methodology(self, audit_id: int, m: Methodology) -> None:
        m.validate()
        used = {r["result"] for r in self.db.query("SELECT DISTINCT result FROM audit_questions WHERE audit_id=?"
                                                    " AND result IS NOT NULL", (audit_id,))}
        if used - set(m.response_options):
            raise AuditError(f"Respuestas registradas no compatibles con la nueva metodología: {used - set(m.response_options)}")
        self.db.execute("UPDATE audits SET methodology_json=? WHERE id=?", (m.to_json(), audit_id))

    def audit(self, audit_id: int) -> dict:
        r = self.db.query_one("SELECT * FROM audits WHERE id=?", (audit_id,))
        if not r:
            raise AuditError(f"Auditoría {audit_id} inexistente")
        return dict(r)

    def methodology(self, audit_id: int) -> Methodology:
        return Methodology.from_json(self.audit(audit_id)["methodology_json"])

    def audits(self) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM audits ORDER BY id DESC")]

    # ---------------------------------------------------------------- preguntas
    def import_official_checklist(self, audit_id: int, xlsx: Path | str, columns: dict[str, str],
                                  sheet: str | None = None, header_row: int = 1,
                                  checklist_reference: str = "") -> int:
        """Importa preguntas oficiales desde un Excel. ``columns`` mapea campos a letras de columna,
        p.ej. {"qid": "A", "numeral": "B", "question": "C", "auditor_guide": "D", "required_evidence": "E"}."""
        import openpyxl

        if "question" not in columns:
            raise AuditError("Debe indicar la columna de la pregunta.")
        xlsx = Path(xlsx)
        ref = checklist_reference.strip() or xlsx.name
        ref += f" (SHA-256 {sha256_file(xlsx)[:16]}…)"
        wb = openpyxl.load_workbook(str(xlsx), read_only=True, data_only=True)
        try:
            ws = wb[sheet] if sheet else wb.worksheets[0]
            n = 0
            for r_idx, row in enumerate(ws.iter_rows(min_row=header_row + 1, values_only=True),
                                        start=header_row + 1):
                def col(name):
                    letter = columns.get(name)
                    if not letter:
                        return None
                    from openpyxl.utils import column_index_from_string

                    i = column_index_from_string(letter) - 1
                    v = row[i] if i < len(row) else None
                    return str(v).strip() if v is not None and str(v).strip() else None

                q = col("question")
                if not q:
                    continue
                n += 1
                self._insert_question(audit_id, col("qid") or f"OF-{n:03d}", "oficial",
                                      f"{ref}, fila {r_idx}", col("source") or ref, col("numeral"), q,
                                      auditor_guide=col("auditor_guide"), required_evidence=col("required_evidence"))
        finally:
            wb.close()
        self.db.log("audit.import_checklist", "audit", audit_id, f"{n} preguntas oficiales de {ref}", self.username)
        return n

    def add_official_question(self, audit_id: int, qid: str, question: str, checklist_reference: str,
                              source: str = "", numeral: str | None = None, **extra) -> int:
        if not checklist_reference.strip():
            raise AuditError("Una pregunta oficial requiere identificar el checklist corporativo de origen.")
        return self._insert_question(audit_id, qid, "oficial", checklist_reference, source or checklist_reference,
                                     numeral, question, **extra)

    def generate_complementary(self, audit_id: int, requirement_version_id: int,
                               exclude_numerals: set[str] | None = None) -> int:
        reqs = self.db.query("SELECT r.*, d.doc_code, d.name FROM requirements r JOIN documents d ON d.id=r.document_id"
                             " WHERE r.version_id=? ORDER BY r.id", (requirement_version_id,))
        if not reqs:
            from sems_ai.compliance.requirements import RequirementService

            RequirementService(self.db).extract_for_version(requirement_version_id)
            reqs = self.db.query("SELECT r.*, d.doc_code, d.name FROM requirements r JOIN documents d"
                                 " ON d.id=r.document_id WHERE r.version_id=? ORDER BY r.id", (requirement_version_id,))
        n = 0
        for r in reqs:
            if exclude_numerals and r["numeral"] in exclude_numerals:
                continue
            n += 1
            num = f" (numeral {r['numeral']})" if r["numeral"] else ""
            self._insert_question(
                audit_id, f"COMP-{n:03d}", "complementaria",
                f"Propuesta generada a partir del requisito {r['req_code']}{num}; NO es pregunta oficial",
                r["doc_code"] or r["name"], r["numeral"],
                f"¿Se evidencia el cumplimiento de lo establecido{num}: «{r['text']}»?",
                auditor_guide="Verificar documentación, registros y entrevistas que demuestren la implementación. "
                              "Pregunta complementaria: confirmar pertinencia antes de usarla.",
                required_evidence="A definir por el auditor según el requisito.")
        self.db.log("audit.complementary", "audit", audit_id, f"{n} preguntas complementarias", self.username)
        return n

    def _insert_question(self, audit_id, qid, origin, origin_reference, source, numeral, question, **extra) -> int:
        cols = ["audit_id", "qid", "origin", "origin_reference", "source", "numeral", "question", "updated_at"]
        vals = [audit_id, qid, origin, origin_reference, source, numeral, question, now_iso()]
        for k in ("translation", "auditor_guide", "required_evidence"):
            if extra.get(k):
                cols.append(k)
                vals.append(extra[k])
        return self.db.execute(f"INSERT INTO audit_questions({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                               tuple(vals))

    def questions(self, audit_id: int, origin: str | None = None) -> list[dict]:
        sql = "SELECT * FROM audit_questions WHERE audit_id=?"
        params: tuple = (audit_id,)
        if origin:
            sql += " AND origin=?"
            params += (origin,)
        return [dict(r) for r in self.db.query(sql + " ORDER BY id", params)]

    def record(self, question_id: int, **fields_) -> None:
        q = self.db.query_one("SELECT audit_id FROM audit_questions WHERE id=?", (question_id,))
        if not q:
            raise AuditError("Pregunta inexistente")
        m = self.methodology(q["audit_id"])
        if fields_.get("result") not in (None, "") and fields_["result"] not in m.response_options:
            raise AuditError(f"Respuesta '{fields_['result']}' no definida en la metodología: {m.response_options}")
        sets = [(k, v) for k, v in fields_.items() if k in QUESTION_EDITABLE]
        if not sets:
            return
        self.db.execute(f"UPDATE audit_questions SET {', '.join(k + '=?' for k, _ in sets)}, updated_at=? WHERE id=?",
                        tuple(v for _, v in sets) + (now_iso(), question_id))
        self.db.log("audit.record", "question", question_id, repr(fields_), self.username)

    # ---------------------------------------------------------------- evidencias / hallazgos
    def add_evidence(self, audit_id: int, description: str, question_id: int | None = None,
                     document_id: int | None = None, reference: str = "") -> int:
        sha = None
        if document_id:
            v = self.db.query_one("SELECT v.sha256 FROM documents d JOIN document_versions v"
                                  " ON v.id=d.current_version_id WHERE d.id=?", (document_id,))
            sha = v["sha256"] if v else None
        return self.db.execute("INSERT INTO audit_evidence(audit_id, question_id, document_id, reference, description,"
                               " sha256, added_at, added_by) VALUES (?,?,?,?,?,?,?,?)",
                               (audit_id, question_id, document_id, reference, description, sha, now_iso(),
                                self.username))

    def evidence(self, audit_id: int) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT e.*, q.qid, d.name doc_name, d.doc_code FROM audit_evidence e LEFT JOIN audit_questions q"
            " ON q.id=e.question_id LEFT JOIN documents d ON d.id=e.document_id WHERE e.audit_id=? ORDER BY e.id",
            (audit_id,))]

    def add_finding(self, audit_id: int, description: str, finding_type: str, question_id: int | None = None,
                    requirement: str = "", evidence: str = "", responsible: str = "", due_date: str = "") -> int:
        m = self.methodology(audit_id)
        if finding_type not in m.finding_types:
            raise AuditError(f"Tipo de hallazgo no definido en la metodología: {m.finding_types}")
        n = self.db.query_one("SELECT COUNT(*) n FROM audit_findings WHERE audit_id=?", (audit_id,))["n"] + 1
        fid = self.db.execute("INSERT INTO audit_findings(audit_id, question_id, ref, finding_type, description,"
                              " requirement, evidence, responsible, due_date, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                              (audit_id, question_id, f"H-{n:03d}", finding_type, description, requirement, evidence,
                               responsible, due_date, now_iso()))
        if question_id:
            self.db.execute("UPDATE audit_questions SET finding=COALESCE(finding || '; ', '') || ? WHERE id=?",
                            (f"H-{n:03d}", question_id))
        return fid

    def findings(self, audit_id: int) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT f.*, q.qid FROM audit_findings f LEFT JOIN audit_questions q ON q.id=f.question_id"
            " WHERE f.audit_id=? ORDER BY f.id", (audit_id,))]

    def update_finding(self, finding_id: int, **fields_) -> None:
        allowed = ("status", "responsible", "due_date", "description", "evidence")
        sets = [(k, v) for k, v in fields_.items() if k in allowed]
        if sets:
            self.db.execute(f"UPDATE audit_findings SET {', '.join(k + '=?' for k, _ in sets)} WHERE id=?",
                            tuple(v for _, v in sets) + (finding_id,))

    def add_action(self, finding_id: int, action: str, responsible: str = "", due_date: str = "",
                   root_cause: str = "") -> int:
        if not action.strip():
            raise AuditError("La acción correctiva no puede estar vacía.")
        return self.db.execute("INSERT INTO corrective_actions(finding_id, root_cause, action, responsible, due_date,"
                               " created_at) VALUES (?,?,?,?,?,?)",
                               (finding_id, root_cause, action, responsible, due_date, now_iso()))

    def update_action(self, action_id: int, **fields_) -> None:
        allowed = ("status", "closed_date", "effectiveness_check", "effectiveness_date", "responsible", "due_date")
        if fields_.get("effectiveness_check") and not fields_.get("effectiveness_date"):
            fields_["effectiveness_date"] = now_iso()[:10]
        sets = [(k, v) for k, v in fields_.items() if k in allowed]
        if sets:
            self.db.execute(f"UPDATE corrective_actions SET {', '.join(k + '=?' for k, _ in sets)} WHERE id=?",
                            tuple(v for _, v in sets) + (action_id,))

    def actions(self, audit_id: int) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT a.*, f.ref finding_ref FROM corrective_actions a JOIN audit_findings f ON f.id=a.finding_id"
            " WHERE f.audit_id=? ORDER BY a.id", (audit_id,))]

    def counts(self, audit_id: int) -> dict[str, int]:
        m = self.methodology(audit_id)
        out = {o: 0 for o in m.response_options}
        out["Sin respuesta"] = 0
        for r in self.db.query("SELECT result, COUNT(*) n FROM audit_questions WHERE audit_id=? GROUP BY result",
                               (audit_id,)):
            out[r["result"] or "Sin respuesta"] = out.get(r["result"] or "Sin respuesta", 0) + r["n"]
        return out
