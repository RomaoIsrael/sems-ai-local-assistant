#!/usr/bin/env bash
# Ejecución en Linux/macOS (desarrollo)
cd "$(dirname "$0")"
exec .venv/bin/python run.py "$@"
