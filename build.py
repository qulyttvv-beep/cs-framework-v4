#!/usr/bin/env python3
"""build.py — package cs.py + cs_data into a portable zip."""
import argparse, shutil, sys, zipfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
CS_PY = HERE / "cs.py"
DATA  = HERE / "cs_data"


def bundle(out: Path, include_tools=False, include_models=False):
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.write(CS_PY, "cs.py")
        z.write(HERE / "logo.svg" if (HERE / "logo.svg").exists() else CS_PY, "logo.svg")
        # the Studio app's frontend (served by `cs studio`)
        for f in (HERE / "cs_studio").rglob("*"):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, str(f.relative_to(HERE)))
        # README if present
        if (HERE / "README.md").exists():
            z.write(HERE / "README.md", "README.md")
        # portable config + chats + contexts (never the caches)
        if DATA.exists():
            for f in DATA.rglob("*"):
                if not f.is_file(): continue
                rel = f.relative_to(DATA)
                parts = rel.parts
                if not include_tools and "tools" in parts: continue
                if not include_models and "models" in parts: continue
                if "cache" in parts: continue
                if "downloads" in parts: continue
                if f.suffix == ".log": continue
                z.write(f, str(Path("cs_data") / rel))
    size = out.stat().st_size / (1024 * 1024)
    print(f"  [+] {out}  ({size:.2f} MB)")
    print(f"    extract anywhere, then: python cs.py")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--with-tools", action="store_true",
                    help="include downloaded binaries (large)")
    ap.add_argument("--with-models", action="store_true",
                    help="include local models (huge)")
    a = ap.parse_args()
    out = Path(a.out) if a.out else HERE / f"cs-portable-{date.today().isoformat()}.zip"
    print(f"packaging from: {HERE}")
    bundle(out, a.with_tools, a.with_models)


if __name__ == "__main__":
    main()