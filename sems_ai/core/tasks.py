"""Ejecución de tareas en segundo plano para no bloquear la interfaz.

Cada tarea corre en un hilo; la comunicación con la UI se hace por una cola que
la UI consulta periódicamente con ``after`` (Tkinter no es seguro entre hilos).
Las tareas reciben un objeto ``Job`` con ``progress()`` y ``cancelled()``.
"""
from __future__ import annotations

import logging
import queue
import threading
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("sems_ai.tasks")


@dataclass
class Job:
    name: str
    _cancel: threading.Event = field(default_factory=threading.Event)
    _queue: "queue.Queue | None" = None

    def cancel(self) -> None:
        self._cancel.set()

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def progress(self, done: int, total: int, message: str = "") -> None:
        if self._queue is not None:
            self._queue.put(("progress", self, (done, total, message)))


class TaskRunner:
    def __init__(self, tk_root, on_progress: Callable[[Job, int, int, str], None] | None = None,
                 on_state: Callable[[Job | None], None] | None = None, interval_ms: int = 100):
        self.root = tk_root
        self.q: queue.Queue = queue.Queue()
        self.on_progress = on_progress
        self.on_state = on_state
        self.interval = interval_ms
        self.current: Job | None = None
        self._callbacks: dict[int, tuple] = {}
        self.root.after(self.interval, self._poll)

    def submit(self, name: str, fn: Callable[[Job], Any], on_done: Callable[[Any], None] | None = None,
               on_error: Callable[[BaseException, str], None] | None = None) -> Job:
        job = Job(name, _queue=self.q)
        self._callbacks[id(job)] = (on_done, on_error)
        self.current = job
        if self.on_state:
            self.on_state(job)

        def run():
            try:
                res = fn(job)
                self.q.put(("done", job, res))
            except BaseException as exc:  # se comunica a la UI
                log.error("Tarea %s falló: %s", name, traceback.format_exc())
                self.q.put(("error", job, (exc, traceback.format_exc())))

        threading.Thread(target=run, name=f"sems-{name}", daemon=True).start()
        return job

    def _poll(self) -> None:
        try:
            while True:
                kind, job, payload = self.q.get_nowait()
                if kind == "progress":
                    if self.on_progress:
                        self.on_progress(job, *payload)
                    continue
                on_done, on_error = self._callbacks.pop(id(job), (None, None))
                if job is self.current:
                    self.current = None
                    if self.on_state:
                        self.on_state(None)
                if kind == "done" and on_done:
                    on_done(payload)
                elif kind == "error" and on_error:
                    on_error(*payload)
        except queue.Empty:
            pass
        except Exception:  # nunca detener el ciclo de consulta
            log.error("Error en callback de UI: %s", traceback.format_exc())
        self.root.after(self.interval, self._poll)
