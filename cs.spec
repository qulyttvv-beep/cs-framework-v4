# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for CS Framework.
#
#   pyinstaller cs.spec
#
# Produces ONE self-contained executable in dist/ — `cs` (`cs.exe` on
# Windows). It contains the CLI, the server and the CS Studio desktop app
# (its frontend is bundled from cs_studio/static). Double-clicking it opens
# Studio; running it from a terminal gives the CLI.
#
# Model runtimes (torch, transformers, llama.cpp python bindings …) are never
# bundled — GGUF models run through downloaded llama.cpp binaries and cloud
# models through their APIs. Computer-use libraries (mss, pyautogui, Pillow)
# ARE bundled when they are installed in the build environment.
import os

# Heavy / optional packages that must never be pulled into the binary even if
# they happen to be present in the build environment.
EXCLUDES = [
    "torch", "transformers", "tokenizers", "accelerate", "safetensors",
    "llama_cpp", "onnxruntime", "vllm", "mlx", "mlx_lm", "sentencepiece",
    "tiktoken", "huggingface_hub", "hf_transfer", "einops",
    "numpy", "scipy", "pandas", "matplotlib", "sklearn", "cv2",
    "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6",
    "pytest", "IPython", "notebook", "playwright",
]

ICON = "assets/cs.ico" if os.name == "nt" else ("assets/cs.icns" if os.path.exists("assets/cs.icns") and os.uname().sysname == "Darwin" else None)

a = Analysis(
    ["cs.py"],
    pathex=[],
    binaries=[],
    datas=[("cs_studio/static", "cs_studio/static")],
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
