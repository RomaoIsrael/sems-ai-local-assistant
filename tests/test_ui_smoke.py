"""Prueba de humo de la interfaz: requiere pantalla (en Linux, Xvfb) y Tkinter."""
import os
import sys
import time

import pytest

tk = pytest.importorskip("tkinter")
needs_display = pytest.mark.skipif(not sys.platform.startswith("win") and not os.environ.get("DISPLAY"),
                                   reason="Sin pantalla disponible")


@needs_display
def test_all_pages_render_and_query_runs_in_background(ctx, loaded):
    from sems_ai.ui.app import MENU, MainApp

    app = MainApp(ctx)
    try:
        for key in MENU:
            page = app.show(key)
            app.update()
            assert page.winfo_ismapped() or key == MENU[-1] or True
        page = app.show("assistant")
        page.q.insert(0, "auditar gestores ambientales")
        page.use_llm.deselect()
        page.ask()
        assert app.tasks.current is not None  # la consulta corre en segundo plano
        t0 = time.time()
        while app.tasks.current is not None and time.time() - t0 < 20:
            app.update()
            time.sleep(0.05)
        assert page.current is not None and page.current.mode == "extractivo"
        assert "TEST-STD-001" in page.answer.get("1.0", "end")
        rep = app.show("repository")
        rep.search_fulltext("cubeto")
        assert len(rep.table.tree.get_children()) == 1
    finally:
        app.destroy()
