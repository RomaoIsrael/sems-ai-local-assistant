"""Bloqueo de conexiones salientes.

Cuando está activo, cualquier intento de conexión a un host que no sea de bucle
local (127.0.0.0/8, ::1, localhost) lanza ``OfflineViolation``. Esto garantiza
que ni la aplicación ni sus dependencias transmitan documentos o consultas a
servicios externos. El motor Ollama local (127.0.0.1:11434) sigue permitido.

Nota: es un control a nivel de proceso Python. Para defensa en profundidad se
recomienda además una regla de Firewall de Windows (ver docs/SEGURIDAD.md).
"""
from __future__ import annotations

import ipaddress
import socket
import threading

_lock = threading.Lock()
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_original_getaddrinfo = socket.getaddrinfo
_original_create_connection = socket.create_connection
_enabled = False

LOCAL_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", ""}


class OfflineViolation(ConnectionRefusedError):
    """Intento de conexión externa bloqueado por la política offline."""


def _is_local_host(host: object) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode(errors="ignore")
    host = str(host).strip("[]").lower()
    if host in LOCAL_NAMES:
        return True
    try:
        ip = ipaddress.ip_address(host.split("%")[0])
        return ip.is_loopback
    except ValueError:
        return False


def _check_address(address: object) -> None:
    if isinstance(address, tuple) and address:
        host = address[0]
    elif isinstance(address, (str, bytes)):
        # sockets AF_UNIX
        return
    else:
        host = address
    if not _is_local_host(host):
        raise OfflineViolation(f"Conexión externa bloqueada por SEMS AI (modo offline): {host}")


def _guarded_connect(self, address):  # type: ignore[no-untyped-def]
    if self.family in (socket.AF_INET, socket.AF_INET6):
        _check_address(address)
    return _original_connect(self, address)


def _guarded_connect_ex(self, address):  # type: ignore[no-untyped-def]
    if self.family in (socket.AF_INET, socket.AF_INET6):
        _check_address(address)
    return _original_connect_ex(self, address)


def _guarded_getaddrinfo(host, *args, **kwargs):  # type: ignore[no-untyped-def]
    if not _is_local_host(host):
        raise OfflineViolation(f"Resolución DNS externa bloqueada por SEMS AI (modo offline): {host}")
    return _original_getaddrinfo(host, *args, **kwargs)


def enable() -> None:
    global _enabled
    with _lock:
        socket.socket.connect = _guarded_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = _guarded_getaddrinfo  # type: ignore[assignment]
        _enabled = True


def disable() -> None:
    global _enabled
    with _lock:
        socket.socket.connect = _original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = _original_connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = _original_getaddrinfo  # type: ignore[assignment]
        _enabled = False


def is_enabled() -> bool:
    return _enabled


def is_local_url(url: str) -> bool:
    from urllib.parse import urlparse

    return _is_local_host(urlparse(url).hostname)
