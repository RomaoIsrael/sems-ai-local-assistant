"""Traducciones de la interfaz (español principal, inglés opcional)."""
from __future__ import annotations

STRINGS = {
    "app_title": {"es": "SEMS AI — Local Assistant", "en": "SEMS AI — Local Assistant"},
    "home": {"es": "Inicio", "en": "Home"},
    "assistant": {"es": "Asistente IA", "en": "AI Assistant"},
    "repository": {"es": "Repositorio documental", "en": "Document repository"},
    "compliance": {"es": "Análisis de cumplimiento", "en": "Compliance analysis"},
    "word": {"es": "Revisión de Word", "en": "Word review"},
    "audits": {"es": "Auditorías SEMS", "en": "SEMS audits"},
    "waste": {"es": "Gestión de desechos", "en": "Waste management"},
    "legal": {"es": "Matriz legal", "en": "Legal matrix"},
    "excel": {"es": "Generador de Excel", "en": "Excel generator"},
    "reports": {"es": "Reportes", "en": "Reports"},
    "settings": {"es": "Configuración", "en": "Settings"},
    "search": {"es": "Buscar en el repositorio…", "en": "Search the repository…"},
    "cancel": {"es": "Cancelar", "en": "Cancel"},
    "ready": {"es": "Listo", "en": "Ready"},
    "export_dir": {"es": "Exportación", "en": "Export"},
    "ask": {"es": "Consultar", "en": "Ask"},
    "use_llm": {"es": "Usar IA local", "en": "Use local AI"},
    "import_files": {"es": "Importar archivos", "en": "Import files"},
    "import_folder": {"es": "Importar carpeta", "en": "Import folder"},
    "offline_on": {"es": "Offline", "en": "Offline"},
    "offline_off": {"es": "Red NO bloqueada", "en": "Network NOT blocked"},
}

_lang = "es"


def set_language(lang: str) -> None:
    global _lang
    _lang = lang if lang in ("es", "en") else "es"


def t(key: str) -> str:
    entry = STRINGS.get(key)
    if not entry:
        return key
    return entry.get(_lang) or entry["es"]
