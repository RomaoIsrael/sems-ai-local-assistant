"""Ventana principal de SEMS AI — Local Assistant."""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from sems_ai import APP_NAME, __version__
from sems_ai.core.context import AppContext
from sems_ai.core.i18n import set_language, t
from sems_ai.core.tasks import TaskRunner
from sems_ai.security import network_guard
from sems_ai.ui import widgets as w

log = logging.getLogger("sems_ai.ui")

MENU = ["home", "assistant", "repository", "compliance", "word", "audits", "waste", "legal", "excel", "reports",
        "settings"]


class MainApp(ctk.CTk):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        set_language(ctx.settings.language)
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        self.title(f"{APP_NAME}  v{__version__}")
        self.geometry("1360x820")
        self.minsize(1100, 680)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=24, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        self.report_callback_exception = self._tk_error
        self._build()
        self.tasks = TaskRunner(self, on_progress=self._progress, on_state=self._task_state)
        self.pages: dict[str, w.PageBase] = {}
        self.show("home")
        self.after(300, self.refresh_model_status)

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(self, height=52, corner_radius=0, fg_color="#1F4E78")
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        ctk.CTkLabel(top, text=t("app_title"), text_color="white",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(side="left", padx=16, pady=10)
        self.search_var = tk.StringVar()
        e = ctk.CTkEntry(top, textvariable=self.search_var, placeholder_text=t("search"), width=380)
        e.pack(side="left", padx=20)
        e.bind("<Return>", lambda ev: self.global_search())
        ctk.CTkButton(top, text="🔍", width=40, command=self.global_search).pack(side="left")
        self.model_lbl = ctk.CTkLabel(top, text="IA local: comprobando…", text_color="#FFE699")
        self.model_lbl.pack(side="right", padx=16)
        self.net_lbl = ctk.CTkLabel(top, text="", text_color="#C6EFCE")
        self.net_lbl.pack(side="right", padx=8)

        side = ctk.CTkFrame(self, width=210, corner_radius=0)
        side.grid(row=1, column=0, sticky="ns")
        self.menu_buttons = {}
        for key in MENU:
            b = ctk.CTkButton(side, text=t(key), anchor="w", width=200, fg_color="transparent",
                              text_color=("gray10", "gray90"), hover_color=("gray80", "gray30"),
                              command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=5, pady=2)
            self.menu_buttons[key] = b

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.grid(row=1, column=1, sticky="nsew")
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        status = ctk.CTkFrame(self, height=30, corner_radius=0)
        status.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.status_lbl = ctk.CTkLabel(status, text=t("ready"), anchor="w")
        self.status_lbl.pack(side="left", padx=10)
        self.cancel_btn = ctk.CTkButton(status, text=t("cancel"), width=80, state="disabled", command=self.cancel_task)
        self.cancel_btn.pack(side="right", padx=6, pady=2)
        self.progress = ctk.CTkProgressBar(status, width=260)
        self.progress.set(0)
        self.progress.pack(side="right", padx=6)
        self.export_lbl = ctk.CTkLabel(status, text=f"{t('export_dir')}: {self.ctx.export_dir}", text_color="gray")
        self.export_lbl.pack(side="right", padx=12)
        self._update_net_label()

    def _update_net_label(self) -> None:
        on = network_guard.is_enabled()
        self.net_lbl.configure(text="🔒 " + (t("offline_on") if on else t("offline_off")),
                               text_color="#C6EFCE" if on else "#FFC7CE")

    # ------------------------------------------------------------------ navegación
    def page_class(self, key: str):
        from sems_ai.ui.pages import (audits_page, compliance_page, home_assistant, legal_waste, repository_page,
                                      tools_pages, word_page)

        return {
            "home": home_assistant.HomePage, "assistant": home_assistant.AssistantPage,
            "repository": repository_page.RepositoryPage, "compliance": compliance_page.CompliancePage,
            "word": word_page.WordReviewPage, "audits": audits_page.AuditsPage, "waste": legal_waste.WastePage,
            "legal": legal_waste.LegalPage, "excel": tools_pages.ExcelPage, "reports": tools_pages.ReportsPage,
            "settings": tools_pages.SettingsPage,
        }[key]

    def show(self, key: str):
        if key not in self.pages:
            page = self.page_class(key)(self.container, self)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page
        page = self.pages[key]
        page.tkraise()
        for k, b in self.menu_buttons.items():
            b.configure(fg_color=("#D9E1F2", "#1F4E78") if k == key else "transparent")
        try:
            page.on_show()
        except Exception as exc:
            log.exception("Error al mostrar %s", key)
            w.error(f"Error al cargar la página: {exc}")
        return page

    def global_search(self) -> None:
        q = self.search_var.get().strip()
        if q:
            self.show("repository").search_fulltext(q)

    # ------------------------------------------------------------------ tareas
    def run_task(self, name, fn, on_done=None):
        if self.tasks.current is not None:
            w.info("Hay una tarea en curso. Espere a que finalice o cancélela.")
            return None
        return self.tasks.submit(name, fn, on_done, self._task_error)

    def cancel_task(self) -> None:
        if self.tasks.current:
            self.tasks.current.cancel()
            self.status_lbl.configure(text="Cancelando…")

    def _progress(self, job, done, total, msg) -> None:
        self.progress.set(done / total if total else 0)
        self.status_lbl.configure(text=f"{job.name}: {msg} ({done}/{total})")

    def _task_state(self, job) -> None:
        if job is None:
            self.progress.set(0)
            self.cancel_btn.configure(state="disabled")
            self.status_lbl.configure(text=t("ready"))
        else:
            self.progress.configure(mode="indeterminate")
            self.progress.configure(mode="determinate")
            self.cancel_btn.configure(state="normal")
            self.status_lbl.configure(text=f"{job.name}…")

    def _task_error(self, exc, tb) -> None:
        w.error(f"La operación no pudo completarse:\n\n{type(exc).__name__}: {exc}\n\n"
                "Detalle técnico registrado en el archivo de log.")

    def _tk_error(self, exc, val, tb) -> None:
        import traceback

        log.error("Error de interfaz: %s", "".join(traceback.format_exception(exc, val, tb)))
        w.error(f"Error inesperado: {val}")

    def refresh_model_status(self) -> None:
        def check(job):
            return self.ctx.llm() is not None, self.ctx.llm_status()

        def done(res):
            ok, msg = res
            self.model_lbl.configure(text=("🟢 " if ok else "⚪ ") + msg, text_color="#C6EFCE" if ok else "#FFE699")

        import threading

        def bg():
            try:
                r = check(None)
            except Exception as exc:
                r = (False, f"IA local no disponible: {exc}")
            self.after(0, lambda: done(r))

        threading.Thread(target=bg, daemon=True).start()


def main() -> None:
    ctx = AppContext()
    app = MainApp(ctx)
    if ctx.settings.require_login:
        from sems_ai.ui.pages.tools_pages import login_dialog

        app.withdraw()
        user = login_dialog(app, ctx)
        if user is None:
            app.destroy()
            return
        ctx.username = user.username
        app.deiconify()
    app.mainloop()
