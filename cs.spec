# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the portable `cs` CLI.
#
#   pyinstaller cs.spec
#
# Produces ONE self-contained executable in dist/ — `cs` (`cs.exe` on
# Windows). It contains the CLI, the server and the Spark X app (its frontend
# is bundled from cs_studio/static). Double-clicking it opens Spark X in the
# browser; running it from a terminal gives the CLI. The installable desktop
# app with its own native window is built by sparkx.spec.
#
# Model runtimes (torch, transformers, llama.cpp python bindings …) are never
# bundled — GGUF models run through downloaded llama.cpp binaries and cloud
# models through their APIs. Computer-use libraries (mss, pyautogui, Pillow)
# ARE bundled when they are installed in the build environment.
import os
import sys

# Heavy / optional packages that must never be pulled into the binary even if
# they happen to be present in the build environment.
EXCLUDES = [
    "torch", "transformers", "tokenizers", "accelerate", "safetensors",
    "llama_cpp", "onnxruntime", "vllm", "mlx", "mlx_lm", "sentencepiece",
    "tiktoken", "huggingface_hub", "hf_transfer", "einops",
    "numpy", "scipy", "pandas", "matplotlib", "sklearn", "cv2",
    "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "qtpy", "gi",
    "webview", "pytest", "IPython", "notebook", "playwright",
]

ICON = "assets/sparkx.ico" if os.name == "nt" else ("assets/sparkx.icns" if sys.platform == "darwin" else None)

def app_files(folder):
    """(file, dest dir) pairs for a folder, minus Python caches."""
    from pathlib import Path
    return [(str(p), str(p.parent)) for p in sorted(Path(folder).rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts]


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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="cs",
    icon=ICON,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
