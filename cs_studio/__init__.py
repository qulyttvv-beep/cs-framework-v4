"""CS Studio — the graphical app for CS Framework.

The backend lives in ``cs.py`` (it serves this package's ``static/`` folder);
this package only ships the frontend assets so they can be bundled into the
single-file executable and installed with pip.
"""
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"
