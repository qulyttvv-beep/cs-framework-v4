# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the Spark X desktop app.
#
#   pyinstaller sparkx.spec
#
# Produces dist/Spark X/ — a folder app with
#   Spark X(.exe)   the app: a native window (pywebview → WebView2 on Windows,
#                   WebKit on macOS), no console
#   cs(.exe)        the command-line tool (Windows/Linux), sharing the same files
# On macOS the folder is wrapped as dist/Spark X.app.
#
# The Windows installer (packaging/sparkx.iss) and the macOS .dmg are built from
# this output by the Release workflow. The single-file CLI is built by cs.spec.
import os
import re
import sys

EXCLUDES = [
    "torch", "transformers", "tokenizers", "accelerate", "safetensors",
    "llama_cpp", "onnxruntime", "vllm", "mlx", "mlx_lm", "sentencepiece",
    "tiktoken", "huggingface_hub", "hf_transfer", "einops",
    "numpy", "scipy", "pandas", "matplotlib", "sklearn", "cv2",
    "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "qtpy", "gi",
    "pytest", "IPython", "notebook", "playwright",
]
IS_MAC = sys.platform == "darwin"
IS_WIN = os.name == "nt"
ICON = "assets/sparkx.ico" if IS_WIN else ("assets/sparkx.icns" if IS_MAC else None)

def app_files(folder):
    """(file, dest dir) pairs for a folder, minus Python caches."""
    from pathlib import Path
    return [(str(p), str(p.parent)) for p in sorted(Path(folder).rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts]

VERSION = re.search(r'^VERSION\s*=\s*"([^"]+)"', open("cs.py", encoding="utf-8").read(), re.M).group(1)

a = Analysis(
    ["cs.py"],
    pathex=[],
    binaries=[],
    datas=app_files("cs_studio/static") + app_files("cs_studio/blender"),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

app_exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Spark X", icon=ICON,
              console=False, debug=False, strip=False, upx=False,
              argv_emulation=False, codesign_identity=None, entitlements_file=None)
exes = [app_exe]
if not IS_MAC:
    exes.append(EXE(pyz, a.scripts, [], exclude_binaries=True, name="cs", icon=ICON,
                    console=True, debug=False, strip=False, upx=False))

coll = COLLECT(*exes, a.binaries, a.datas, name="Spark X", strip=False, upx=False)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="Spark X.app",
        icon=ICON,
        bundle_identifier="app.sparkx.desktop",
        version=VERSION,
        info_plist={
            "CFBundleName": "Spark X",
            "CFBundleDisplayName": "Spark X",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "11.0",
            "LSApplicationCategoryType": "public.app-category.productivity",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            # the window shows the app's own server on 127.0.0.1 (plain http)
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
            "NSAppleEventsUsageDescription": "Spark X controls other apps when you ask it to use your computer.",
        },
    )
