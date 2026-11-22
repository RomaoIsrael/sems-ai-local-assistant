"""Páginas Generador de Excel, Reportes y Configuración; diálogo de inicio de sesión."""
from __future__ import annotations

import json
from tkinter import filedialog

import customtkinter as ctk

from sems_ai.excel.builder import WorkbookBuilder, unique_path
from sems_ai.security import network_guard
from sems_ai.security.auth import ROLES, AuthError, AuthService
from sems_ai.ui import widgets as w


class ExcelPage(w.PageBase):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.header("Generador de Excel", "Libros editables con tablas, listas desplegables, fórmulas, formato "
                                          "condicional y gráficos. Los datos faltantes se dejan vacíos.")
        box = ctk.CTkFrame(self)
        box.pack(fill="x", padx=12, pady=8)
        for text, cmd in (("Matriz de brechas (desde Análisis de cumplimiento)", lambda: app.show("compliance")),
                          ("Auditoría SEMS (9 pestañas)", lambda: app.show("audits")),
                          ("Matriz legal", lambda: app.show("legal").export()),
                          ("Gestión de desechos e indicadores", lambda: app.show("waste").export()),
                          ("Inventario documental", lambda: app.show("repository").export_inventory()),
                          ("Historial de consultas", self.export_history),
                          ("Matriz personalizada en blanco", self.custom_matrix)):
            ctk.CTkButton(box, text=text, anchor="w", command=cmd).pack(fill="x", padx=8, pady=3)

    def export_history(self) -> None:
        rows = self.ctx.db.query("SELECT ts, username, query, mode, model, answer, sources_json, warnings_json"
                                 " FROM query_history ORDER BY id")
        wb = WorkbookBuilder()
        ws = wb.sheet("Historial de consultas")
        wb.table(ws, ["Fecha", "Usuario", "Consulta", "Modo", "Modelo", "Respuesta", "Fuentes (JSON)",
                      "Advertencias"], [list(r) for r in rows], widths=[18, 12, 50, 12, 16, 80, 60, 50],
                 table_name="Historial")
        p = wb.save(unique_path(self.ctx.export_dir, "historial_consultas", ".xlsx"))
        w.info(f"Exportado: {p}")

    def custom_matrix(self) -> None:
        res = w.FormDialog.ask(self, "Matriz personalizada", [
            {"name": "title", "label": "Título", "required": True},
            {"name": "cols", "label": "Columnas (separadas por ;)", "required": True,
             "default": "ID; Requisito; Fuente; Numeral; Responsable; Estado; Evidencia; Fecha"},
            {"name": "list_col", "label": "Columna con lista desplegable (nombre)", "default": "Estado"},
            {"name": "list_vals", "label": "Valores de la lista (;)", "default": "Pendiente; En proceso; Cerrado"},
            {"name": "rows", "label": "Filas vacías con formato", "default": "50"}])
        if not res:
            return
        cols = [c.strip() for c in res["cols"].split(";") if c.strip()]
        val = {}
        if res["list_col"].strip() in cols and res["list_vals"].strip():
            val[cols.index(res["list_col"].strip()) + 1] = [v.strip() for v in res["list_vals"].split(";") if v.strip()]
        wb = WorkbookBuilder()
        ws = wb.sheet(res["title"][:31])
        start = wb.title_block(ws, res["title"]) + 1
        first, last = wb.table(ws, cols, [], start_row=start, validations=val, table_name="Matriz",
                               extra_blank_rows=int(res["rows"] or 50), widths=[25] * len(cols))
        p = wb.save(unique_path(self.ctx.export_dir, "matriz_personalizada", ".xlsx"))
        w.info(f"Exportado: {p}")


class ReportsPage(w.PageBase):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.header("Reportes", "Reportes técnicos editables (Word) con trazabilidad a las fuentes.")
        box = ctk.CTkFrame(self)
        box.pack(fill="x", padx=12, pady=8)
        ctk.CTkButton(box, text="Reporte técnico de cumplimiento (seleccionar análisis)",
                      command=lambda: app.show("compliance").report(), anchor="w").pack(fill="x", padx=8, pady=3)
        ctk.CTkButton(box, text="Informe de auditoría (seleccionar auditoría)",
                      command=lambda: app.show("audits").report(), anchor="w").pack(fill="x", padx=8, pady=3)
        ctk.CTkButton(box, text="Registro de actividad (bitácora) a Excel", command=self.audit_log,
                      anchor="w").pack(fill="x", padx=8, pady=3)
        ctk.CTkButton(box, text="Abrir directorio de exportación", anchor="w",
                      command=lambda: w.open_path(self.ctx.export_dir)).pack(fill="x", padx=8, pady=3)

    def audit_log(self) -> None:
        rows = self.ctx.db.query("SELECT ts, username, action, entity, entity_id, details FROM audit_log ORDER BY id")
        wb = WorkbookBuilder()
        ws = wb.sheet("Bitácora")
        wb.table(ws, ["Fecha", "Usuario", "Acción", "Entidad", "ID", "Detalle"], [list(r) for r in rows],
                 widths=[18, 14, 24, 16, 10, 90], table_name="Bitacora")
        p = wb.save(unique_path(self.ctx.export_dir, "bitacora", ".xlsx"))
        w.info(f"Exportado: {p}")


class SettingsPage(w.PageBase):
    FIELDS = [
        ("language", "Idioma (es/en)", "choice", ["es", "en"]),
        ("llm_enabled", "Habilitar IA local", "bool", None),
        ("ollama_url", "URL de Ollama (solo local)", "text", None),
        ("llm_model", "Modelo LLM", "text", None),
        ("embedding_model", "Modelo de embeddings", "text", None),
        ("semantic_search_enabled", "Búsqueda semántica", "bool", None),
        ("llm_context_chunks", "Fragmentos por consulta", "text", None),
        ("block_outbound_network", "Bloquear conexiones externas", "bool", None),
        ("require_login", "Requerir inicio de sesión", "bool", None),
        ("export_dir", "Directorio de exportación", "text", None),
        ("author_name", "Autor de comentarios Word", "text", None),
        ("author_initials", "Iniciales", "text", None),
        ("pdf_viewer_command", "Visor PDF (usar {file} y {page})", "text", None),
        ("tesseract_cmd", "Ruta de Tesseract OCR", "text", None),
        ("max_file_size_mb", "Tamaño máximo de archivo (MB)", "text", None),
    ]

    def __init__(self, master, app):
        super().__init__(master, app)
        self.header("Configuración")
        tb = self.toolbar()
        for text, cmd in (("Editar configuración", self.edit), ("Probar IA local", self.test_llm),
                          ("Generar embeddings", self.embeddings), ("Usuarios", self.users),
                          ("Crear respaldo", self.backup), ("Verificar respaldo", self.verify_backup),
                          ("Restaurar respaldo", self.restore), ("Evaluar recuperación (JSON)", self.evaluate)):
            ctk.CTkButton(tb, text=text, command=cmd, width=10).pack(side="left", padx=3)
        self.text = ctk.CTkTextbox(self, wrap="word")
        self.text.pack(fill="both", expand=True, padx=12, pady=8)

    def on_show(self) -> None:
        s = self.ctx.settings
        lines = [f"{label}: {getattr(s, name)}" for name, label, _, _ in self.FIELDS]
        lines += ["", f"Datos: {s.base}", f"Base de datos: {s.db_path}", f"Bóveda: {s.vault_dir}",
                  f"Bloqueo de red activo en este proceso: {network_guard.is_enabled()}"]
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(lines))

    def edit(self) -> None:
        s = self.ctx.settings
        fields = [{"name": n, "label": l, "type": t, "options": o or [], "default": getattr(s, n)}
                  for n, l, t, o in self.FIELDS]
        res = w.FormDialog.ask(self, "Configuración", fields)
        if not res:
            return
        from sems_ai.security.network_guard import is_local_url

        if not is_local_url(res["ollama_url"]):
            return w.error("Solo se admite un servidor Ollama local (127.0.0.1 / localhost).")
        for n, _, t, _ in self.FIELDS:
            v = res[n]
            cur = getattr(s, n)
            if isinstance(cur, bool):
                v = bool(v)
            elif isinstance(cur, int):
                try:
                    v = int(v)
                except ValueError:
                    return w.error(f"Valor numérico no válido: {n}")
            setattr(s, n, v)
        s.save()
        if s.block_outbound_network:
            network_guard.enable()
        else:
            network_guard.disable()
        self.app._update_net_label()
        self.app.refresh_model_status()
        self.on_show()
        w.info("Configuración guardada. El cambio de idioma se aplica al reiniciar.")

    def test_llm(self) -> None:
        self.run("Prueba de IA local", lambda job: self.ctx.llm_status(), lambda msg: w.info(msg))

    def embeddings(self) -> None:
        def work(job):
            llm = self.ctx.llm()
            if llm is None:
                raise RuntimeError(self.ctx.llm_status())
            if not llm.has_embedding_model():
                raise RuntimeError(f"Modelo de embeddings '{llm.embedding_model}' no instalado en Ollama.")
            return self.ctx.retriever(llm).index_embeddings(progress=job.progress, cancel=job.cancelled)

        self.run("Embeddings locales", work, lambda n: w.info(f"{n} fragmentos vectorizados."))

    def users(self) -> None:
        auth = AuthService(self.ctx.db)
        existing = "\n".join(f"{u['username']} ({u['role']})" for u in auth.list_users()) or "(sin usuarios)"
        res = w.FormDialog.ask(self, "Nuevo usuario", [
            {"name": "u", "label": "Usuario", "required": True},
            {"name": "p", "label": "Contraseña (mín. 10)", "type": "password", "required": True},
            {"name": "r", "label": "Rol", "type": "choice", "options": list(ROLES), "required": True}],
            note=f"Usuarios existentes:\n{existing}")
        if res:
            try:
                auth.create_user(res["u"], res["p"], res["r"])
            except AuthError as exc:
                return w.error(str(exc))
            w.info("Usuario creado.")

    def _password(self, title: str, optional: bool = True) -> str | None:
        res = w.FormDialog.ask(self, title, [{"name": "p", "label": "Contraseña" + (" (vacío = sin cifrar)"
                                                                                  if optional else ""),
                                              "type": "password"}])
        return None if res is None else res["p"]

    def backup(self) -> None:
        from sems_ai.security.backup import create_backup

        pw = self._password("Respaldo cifrado")
        if pw is None:
            return
        self.run("Respaldo", lambda job: create_backup(self.ctx.settings, pw or None),
                 lambda p: w.info(f"Respaldo creado: {p}"))

    def verify_backup(self) -> None:
        from sems_ai.security.backup import verify_backup

        p = filedialog.askopenfilename(filetypes=[("Respaldo", "*.zip *.semsbak")],
                                       initialdir=str(self.ctx.settings.backups_dir))
        if not p:
            return
        pw = self._password("Contraseña del respaldo")
        self.run("Verificación de respaldo", lambda job: verify_backup(p, pw or None),
                 lambda m: w.info(f"Respaldo íntegro: {len(m['files'])} archivos verificados."))

    def restore(self) -> None:
        from sems_ai.security.backup import restore_backup

        p = filedialog.askopenfilename(filetypes=[("Respaldo", "*.zip *.semsbak")])
        if not p:
            return
        target = filedialog.askdirectory(title="Carpeta de destino (vacía, o nueva)")
        if not target:
            return
        pw = self._password("Contraseña del respaldo")
        self.run("Restauración", lambda job: restore_backup(p, target, pw or None),
                 lambda t: w.info(f"Restaurado en {t}. Para usarlo, defina SEMS_AI_HOME={t} y reinicie."))

    def evaluate(self) -> None:
        from sems_ai.rag.evaluation import run_evaluation

        p = filedialog.askopenfilename(title="Conjunto de evaluación (JSON)", filetypes=[("JSON", "*.json")])
        if not p:
            return

        def done(s):
            out = unique_path(self.ctx.export_dir, "evaluacion_rag", ".json")
            out.write_text(json.dumps(s.as_dict(), indent=1, ensure_ascii=False, default=str), encoding="utf-8")
            w.info(f"Preguntas: {s.n}\nTasa de acierto (doc. esperado): {s.hit_rate:.0%}\nMRR: {s.mrr:.2f}\n"
                   f"Cobertura de términos: {s.mean_term_recall:.0%}\nPrecisión 'sin evidencia': "
                   f"{'n/a' if s.no_evidence_accuracy is None else f'{s.no_evidence_accuracy:.0%}'}\n"
                   f"Respuestas con advertencias: {s.answers_with_warnings}\n\nDetalle: {out}")

        self.run("Evaluación", lambda job: run_evaluation(self.ctx.answer_engine(use_llm=False), p), done)


def login_dialog(app, ctx):
    auth = AuthService(ctx.db)
    if not auth.has_users():
        res = w.FormDialog.ask(app, "Crear administrador", [
            {"name": "u", "label": "Usuario administrador", "required": True},
            {"name": "p", "label": "Contraseña (mín. 10)", "type": "password", "required": True}],
            note="No existen usuarios. Cree la cuenta de administrador local.")
        if not res:
            return None
        try:
            auth.create_user(res["u"], res["p"], "admin")
        except AuthError as exc:
            w.error(str(exc))
            return None
    for _ in range(5):
        res = w.FormDialog.ask(app, "Iniciar sesión — SEMS AI", [
            {"name": "u", "label": "Usuario", "required": True},
            {"name": "p", "label": "Contraseña", "type": "password", "required": True}])
        if res is None:
            return None
        try:
            return auth.authenticate(res["u"], res["p"])
        except AuthError as exc:
            w.error(str(exc))
    return None
