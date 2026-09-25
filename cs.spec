# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for CS Framework.
#
#   pyinstaller cs.spec
#
# Produces a single self-contained executable in dist/ named `cs`
# (`cs.exe` on Windows). The framework is pure standard library, so the
# binary is small — model runtimes (torch, transformers, llama.cpp, …) are
# never bundled; they are installed on demand at runtime via `cs install`.

# Heavy / optional packages that must never be pulled into the binary even if
# they happen to be present in the build environment.
EXCLUDES = [
    "torch", "transformers", "tokenizers", "accelerate", "safetensors",
    "llama_cpp", "onnxruntime", "vllm", "mlx", "mlx_lm", "sentencepiece",
    "tiktoken", "huggingface_hub", "hf_transfer", "einops",
    "numpy", "scipy", "pandas", "matplotlib", "sklearn",
    "PIL", "cv2", "mss", "pyautogui", "pytesseract",
    "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6",
    "pytest", "IPython", "notebook",
]

a = Analysis(
    ["cs.py"],
    pathex=[],
    binaries=[],
    datas=[],
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
