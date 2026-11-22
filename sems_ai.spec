# -*- mode: python ; coding: utf-8 -*-
# Especificación PyInstaller para SEMS AI — Local Assistant
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [("sems_ai/database/schema.sql", "sems_ai/database")]
datas += collect_data_files("customtkinter")
hidden = collect_submodules("sems_ai") + ["pymupdf", "openpyxl", "docx", "pptx", "PIL._tkinter_finder"]

a = Analysis(["run.py"], pathex=["."], datas=datas, hiddenimports=hidden,
             excludes=["matplotlib", "scipy", "notebook", "IPython", "pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SEMS_AI", console=False,
          upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="SEMS_AI", upx=False)
