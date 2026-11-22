"""Crea documentos SINTÉTICOS de demostración (prefijo TEST-) para probar la aplicación.
No representan documentos corporativos reales.
Uso: python scripts/crear_datos_demo.py carpeta_destino
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import synthetic_docs  # noqa: E402

dest = Path(sys.argv[1] if len(sys.argv) > 1 else "datos_demo_sinteticos")
for k, p in synthetic_docs.build_all(dest).items():
    print(f"{k}: {p}")
