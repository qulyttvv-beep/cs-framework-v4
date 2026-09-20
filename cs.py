#!/usr/bin/env python3
# ═════════════════════════════════════════════════════════════════════════════
#   C S   F R A M E W O R K   v4
#   single-file portable model runner, agent hub, and dev environment
# ═════════════════════════════════════════════════════════════════════════════
from __future__ import annotations
import base64

import argparse, contextlib, datetime as _dt, fnmatch, getpass, hashlib
import importlib.util, io, json, math, os, platform, re, shlex, shutil
import signal, socket, struct, subprocess, sys, tarfile, tempfile, textwrap
import threading, time, traceback, types, urllib.error, urllib.parse
import urllib.request, uuid, zipfile

def _force_utf8_stdout():
    """Replace sys.stdout/stderr with UTF-8 writers that bypass Windows CP."""
    import io as _io
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
            continue
        except Exception:
            pass
        try:
            buf = stream.buffer
        except AttributeError:
            buf = None
        if buf is None:
            continue
        setattr(sys, name,
                _io.TextIOWrapper(buf, encoding="utf-8", errors="replace",
                                  line_buffering=True, write_through=True))


_force_utf8_stdout()

from dataclasses import dataclass, field, asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
import pathlib

APP       = "cs"
APP_LONG  = "CS Framework"
VERSION   = "4.1.0"
CODENAME  = "hex-4.1"


# --- forced constants (repair patch) ---
DEFAULT_TIMEOUT = 3600
DOWNLOAD_CHUNK = 1 << 16
HASH_CHUNK = 1 << 20
MAX_SAFETENSORS_HDR = 200_000_000
MAX_ARRAY_PREVIEW = 20_000
MAX_HISTORY = 40
MAX_TOOL_ROUNDS = 12
MAX_TOOL_OUTPUT = 8000


# --- forced PLATFORM_DEFS (repair) ---
if "PLATFORM_DEFS" not in globals():
    PLATFORM_DEFS = {
        "openai":     {"base_url": "https://api.openai.com/v1",
                       "model": "gpt-4o-mini"},
        "anthropic":  {"base_url": "https://api.anthropic.com/v1",
                       "model": "claude-3-5-sonnet-20241022"},
        "lmstudio":   {"base_url": "http://localhost:1234/v1",
                       "model": "local", "no_key": True, "key": "lm-studio"},
        "ollama":     {"base_url": "http://localhost:11434/v1",
                       "model": "local", "no_key": True, "key": "ollama"},
        "openrouter": {"base_url": "https://openrouter.ai/api/v1",
                       "model": "anthropic/claude-3.5-sonnet"},
        "groq":       {"base_url": "https://api.groq.com/openai/v1",
                       "model": "llama-3.1-8b-instant"},
        "together":   {"base_url": "https://api.together.xyz/v1",
                       "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo"},
        "mistral":    {"base_url": "https://api.mistral.ai/v1",
                       "model": "mistral-large-latest"},
    }


# --- forced PIP_TARGETS (repair) ---
if "PIP_TARGETS" not in globals():
    PIP_TARGETS = {
        "llama-cpp":    ["llama-cpp-python"],
        "transformers": ["transformers", "tokenizers", "accelerate", "safetensors"],
        "torch":        ["torch"],
        "onnx":         ["onnxruntime"],
        "hub":          ["huggingface_hub"],
        "sentencepiece":["sentencepiece", "protobuf"],
        "einops":       ["einops"],
        "tiktoken":     ["tiktoken"],
    }


# --- forced TOOLS_HEADER (repair) ---
if "TOOLS_HEADER" not in globals():
    try:
        _th_lines = ["- " + t["name"] + ": " + (t.get("desc") or "")
                     for t in TOOLS_SPEC]
    except Exception:
        _th_lines = []
    TOOLS_HEADER = (
        "You are running inside CS Framework's coding mode.\n"
        "\n"
        "To call a tool, emit a single JSON object wrapped in <tool>...</tool>:\n"
        "<tool>{\"name\":\"bash\",\"args\":{\"cmd\":\"ls -la\"}}</tool>\n"
        "\n"
        "Wait for the <tool_result>...</tool_result> before continuing.\n"
        "When done, reply normally with no <tool> block.\n"
        "\n"
        "Available tools:\n" + "\n".join(_th_lines) + "\n"
    )


# --- forced TOOLS_SPEC (repair) ---
if "TOOLS_SPEC" not in globals():
    TOOLS_SPEC = []
    for _n in ("bash","read","write","append","ls","glob","grep","web_fetch",
               "python","http","download","extract","tree","diff","find","wc",
               "notify","clip_read","clip_write","screen","screen_size",
               "mouse_move","mouse_click","mouse_drag","scroll","key","type",
               "window_list","window_focus","app_start","sleep","ocr"):
        TOOLS_SPEC.append({"name": _n, "desc": ""})



def build_cli():
    """Return an argparse parser with every subcommand."""
    import argparse as _ap
    ap = _ap.ArgumentParser(prog=APP,
                            description=APP_LONG + " — portable LLM runner")
    sub = ap.add_subparsers(dest="cmd")

    sp = sub.add_parser("setup"); sp.add_argument("--full", action="store_true"); sp.add_argument("--quiet", action="store_true")
    sub.add_parser("install-self"); sub.add_parser("scan"); sub.add_parser("list")
    sub.add_parser("venvs")
    vr = sub.add_parser("venv-repair")
    vr.add_argument("name", nargs="?")
    lo = sub.add_parser("locate")
    lo.add_argument("agent", nargs="?")
    ra = sub.add_parser("run-agent")
    ra.add_argument("agent", nargs="?")
    ra.add_argument("model", nargs="?")
    actx = sub.add_parser("auto-ctx")
    actx.add_argument("value", nargs="?", choices=["on","off","true","false","1","0"])
    sub.add_parser("doctor"); sub.add_parser("selftest"); sub.add_parser("logo")
    sub.add_parser("bonsai-setup"); sub.add_parser("ll-log"); sub.add_parser("menu")
    sub.add_parser("explore"); sub.add_parser("health"); sub.add_parser("agent")
    sub.add_parser("stop"); sub.add_parser("hex"); sub.add_parser("rig")
    sub.add_parser("screen"); sub.add_parser("windows"); sub.add_parser("size")
    sub.add_parser("platforms")

    v = sub.add_parser("verify"); v.add_argument("query", nargs="?"); v.add_argument("--deep", action="store_true"); v.add_argument("--online", action="store_true")
    r = sub.add_parser("run"); r.add_argument("model", nargs="?"); r.add_argument("-p","--prompt", default=None)
    c = sub.add_parser("chat"); c.add_argument("model", nargs="?"); c.add_argument("--incognito", action="store_true")
    sub.add_parser("incognito").add_argument("model", nargs="?")
    cd = sub.add_parser("code"); cd.add_argument("model", nargs="?"); cd.add_argument("--cwd", default=None)
    b = sub.add_parser("bench"); b.add_argument("model"); b.add_argument("-n","--tokens", type=int, default=128)
    i = sub.add_parser("install"); i.add_argument("target")
    ct = sub.add_parser("ctx"); ct.add_argument("model")
    sv = sub.add_parser("serve"); sv.add_argument("--host", default="127.0.0.1"); sv.add_argument("--port", type=int, default=8686); sv.add_argument("--model", default=None)
    ag = sub.add_parser("agents"); ag.add_argument("action", nargs="?", default="list", choices=["list","install","launch"]); ag.add_argument("agent", nargs="?"); ag.add_argument("--model", default=None)
    pi = sub.add_parser("plugin-init"); pi.add_argument("name")
    cl = sub.add_parser("clean"); cl.add_argument("--downloads", action="store_true")
    ex = sub.add_parser("export"); ex.add_argument("archive", nargs="?")
    md = sub.add_parser("model"); md.add_argument("name", nargs="?")
    sub.add_parser("config"); sub.add_parser("perms"); sub.add_parser("settings")
    dp = sub.add_parser("doctor2")  # alias so doctor doesn't conflict
    dp.add_argument("--deep", action="store_true")
    fx = sub.add_parser("fix"); fx.add_argument("--apply", action="store_true")
    cg = sub.add_parser("chatgpt"); cg.add_argument("model", nargs="?")

    # computer use subcommands
    sc = sub.add_parser("click"); sc.add_argument("x", nargs="?", type=int); sc.add_argument("y", nargs="?", type=int)
    sc.add_argument("--button", default="left"); sc.add_argument("--clicks", type=int, default=1)
    mv = sub.add_parser("move"); mv.add_argument("x", type=int); mv.add_argument("y", type=int)
    dr = sub.add_parser("drag"); dr.add_argument("x1", type=int); dr.add_argument("y1", type=int); dr.add_argument("x2", type=int); dr.add_argument("y2", type=int)
    ty = sub.add_parser("type"); ty.add_argument("text")
    ky = sub.add_parser("key"); ky.add_argument("keys")
    scr = sub.add_parser("scroll"); scr.add_argument("amount", type=int)
    fo = sub.add_parser("focus"); fo.add_argument("title")
    ap2 = sub.add_parser("app"); ap2.add_argument("name"); ap2.add_argument("args", nargs="*")
    oc = sub.add_parser("ocr"); oc.add_argument("path", nargs="?")
    return ap


def cmd_model(name=None):
    if not name:
        cur = CFG["prefs"].get("default_model") or "(not set)"
        print("  default model: " + col(47) + cur + RSTC)
        return
    if name == "-":
        CFG["prefs"]["default_model"] = ""
        save_cfg()
        print(GR + "  default cleared" + RSTC)
        return
    rec = match_model(name)
    if not rec:
        print(RD + "  no match: " + name + RSTC)
        return
    CFG["prefs"]["default_model"] = rec.name
    save_cfg()
    print(GR + "  default model: " + rec.name + RSTC)


def cmd_config():
    print(json.dumps(CFG, indent=2, default=str))




def cmd_auto_ctx(arg=None):
    if arg is None:
        cur = CFG["prefs"].get("auto_ctx", True)
        print("  auto context adapt: " +
              (GR + "ON" + RSTC if cur else YL + "OFF" + RSTC))
        return
    val = str(arg).lower() in ("on", "1", "true", "yes", "y")
    CFG["prefs"]["auto_ctx"] = val
    save_cfg()
    print(GR + "  auto context adapt: " + ("ON" if val else "OFF") + RSTC)


def cmd_perms():
    cur = CFG["prefs"].get("auto_approve", True)
    CFG["prefs"]["auto_approve"] = not cur
    save_cfg()
    print("  auto-approve tools: " + (GR + "ON" + RSTC if not cur else YL + "OFF" + RSTC))


# --- Hex Agent system prompt ---
def _quiet_unraisable(u):
    if u.exc_type is AttributeError and u.object is not None:
        if type(u.object).__name__ in ("LlamaModel", "Llama", "LlamaContext",
                                       "LlamaGrammar", "LlamaSamplingContext"):
            return
    try:
        tb = u.exc_traceback
        while tb is not None:
            if "llama_cpp" in tb.tb_frame.f_code.co_filename:
                return
            tb = tb.tb_next
    except Exception:
        pass
    try:
        sys.__unraisablehook__(u)
    except Exception:
        pass

try: sys.unraisablehook = _quiet_unraisable
except Exception: pass

# ─── portable data dir ─────────────────────────────────────────────────────
def _find_data_home() -> Path:
    env = os.environ.get("CS_HOME")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve().parent
    portable = here / "cs_data"
    # Portable mode if PORTABLE marker exists or cs_data/ already in use
    if (here / "PORTABLE").exists() or (portable / "config.json").exists():
        portable.mkdir(parents=True, exist_ok=True)
        return portable
    # Otherwise try to create it locally (running from writable dir)
    try:
        portable.mkdir(parents=True, exist_ok=True)
        t = portable / ".w"; t.write_text("x"); t.unlink()
        return portable
    except Exception:
        return Path.home() / ".cs"


DATA_HOME   = _find_data_home()
MODELS_D    = DATA_HOME / "models"
DL_D        = DATA_HOME / "downloads"
CHATS_D     = DATA_HOME / "chats"
CTX_D       = DATA_HOME / "contexts"
CACHE_D     = DATA_HOME / "cache"
TOOLS_D     = DATA_HOME / "tools"
PLUGINS_D   = DATA_HOME / "plugins"
AGENT_D          = DATA_HOME / "agent"
AGENT_MEM        = AGENT_D / "memory.json"
AGENT_LOG        = AGENT_D / "session.jsonl"
AGENT_CHECKPOINT = AGENT_D / "checkpoints"
AGENT_SCREENS    = AGENT_D / "screenshots"
PLUGIN_TOOLS_D   = PLUGINS_D / "tools"
LOGS_D      = DATA_HOME / "logs"
BIN_D       = DATA_HOME / "bin"
AGENTS_D    = DATA_HOME / "agents"
CONFIG_P    = DATA_HOME / "config.json"
CTX_P       = CTX_D / "contexts.json"
SCAN_P      = CACHE_D / "scan.json"
HASH_P      = CACHE_D / "hashes.json"
VER_P       = CACHE_D / "verify.json"
LOG_P       = LOGS_D / "cs.log"


def _mkdirs():
    for d in (DATA_HOME, MODELS_D, CHATS_D, CTX_D, CACHE_D, TOOLS_D,
              PLUGINS_D, AGENT_D, AGENT_CHECKPOINT, AGENT_SCREENS, PLUGIN_TOOLS_D, LOGS_D, BIN_D, AGENTS_D):
        try: d.mkdir(parents=True, exist_ok=True)
        except Exception: pass

_mkdirs()

# ─── logging ───────────────────────────────────────────────────────────────
_LOG_LOCK = threading.Lock()

def log(msg: str, level: str = "info") -> None:
    line = f"[{_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{level.upper():5}] {msg}"
    with _LOG_LOCK:
        try:
            with open(LOG_P, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass

def log_exc(prefix: str = "exc"):
    try: log(prefix + ": " + traceback.format_exc(), "error")
    except Exception: pass

# ─── UI ────────────────────────────────────────────────────────────────────
CIN = sys.stdout.isatty() and os.environ.get("CS_NO_COLOR") != "1"

def col(c: int) -> str: return f"\x1b[38;5;{c}m" if CIN else ""
RSTC  = "\x1b[0m" if CIN else ""
BOLD  = "\x1b[1m" if CIN else ""
def paint(c, s): return col(c) + s + RSTC

_GRAD = [51, 45, 39, 33, 27, 21, 57, 93, 129, 165, 201, 207, 213, 219, 225]
def grad(f: float) -> str:
    i = max(0, min(len(_GRAD) - 1, int(f * len(_GRAD))))
    return col(_GRAD[i])

DIM = col(240); CY = col(51); MG = col(201); GR = col(47)
YL  = col(220); RD = col(196); BL = col(39); OR = col(208)

def human(n) -> str:
    try: n = float(n)
    except Exception: return "?"
    for u in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024 or u == "PB":
            return f"{int(n)}B" if u == "B" else f"{n:.2f}{u}"
        n /= 1024.0
    return f"{n:.2f}PB"

def trunc(s, n):
    s = str(s); return s if len(s) <= n else s[:n-1] + "..."

def bar(p: float, w: int = 28, tag: str = "") -> None:
    p = max(0.0, min(1.0, p)); n = int(p * w)
    sys.stdout.write("\r  " + col(51) + "▓" * n + col(240) + "░" * (w - n) + RSTC +
                     f" {p*100:5.1f}% {tag}   ")
    sys.stdout.flush()
    if p >= 1.0:
        sys.stdout.write("\n"); sys.stdout.flush()

def clearscr():
    if CIN:
        try: os.system("cls" if os.name == "nt" else "clear")
        except Exception: pass

class Spinner:
    FR = "⠋⠹⠼⠦⠇"
    def __init__(self, msg=""):
        self.msg = msg
        self._s = threading.Event()
        self._t = threading.Thread(target=self._r, daemon=True)
    def _r(self):
        i = 0
        while not self._s.is_set():
            sys.stdout.write("\r  " + col(201) + self.FR[i % len(self.FR)] + RSTC + " " + self.msg + "   ")
            sys.stdout.flush(); i += 1; time.sleep(0.09)
        sys.stdout.write("\r" + " " * (len(self.msg) + 8) + "\r"); sys.stdout.flush()
    def __enter__(self):
        if CIN: self._t.start()
        return self
    def __exit__(self, *a):
        self._s.set()
        if CIN: self._t.join(timeout=1.0)
        return False

def box(title: str, lines) -> str:
    lines = [str(l) for l in lines]
    w = max([len(title) + 2] + [len(l) for l in lines] + [20])
    out = [col(51) + "╔" + "═" * (w + 2) + "╗" + RSTC,
           col(51) + "║ " + RSTC + paint(220, title.ljust(w)) + col(51) + " ║" + RSTC,
           col(51) + "╠" + "═" * (w + 2) + "╣" + RSTC]
    for l in lines:
        out.append(col(51) + "║ " + RSTC + l.ljust(w) + col(51) + " ║" + RSTC)
    out.append(col(51) + "╚" + "═" * (w + 2) + "╝" + RSTC)
    return "\n".join(out)

def table(rows, headers, pad: int = 2) -> str:
    rows = [[str(c) for c in r] for r in rows]
    w = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            if i < len(w): w[i] = max(w[i], len(c))
    def fmt(cells): return (" " * pad).join(c.ljust(w[i]) for i, c in enumerate(cells))
    out = [paint(220, fmt(headers)),
           paint(240, "─" * (sum(w) + pad * (len(w) - 1)))]
    for r in rows: out.append(fmt(r))
    return "\n".join(out)

# ─── logo ──────────────────────────────────────────────────────────────────
def _segd(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = dx*dx + dy*dy or 1e-9
    t = max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy) / L))
    return math.hypot(px - (ax + t*dx), py - (ay + t*dy))

def render_logo(H: int = 11):
    # width factor tuned so hexagon isn't horizontally stretched
    W = int(H * 1.75) + 2
    V = [(math.cos(math.radians(a)), math.sin(math.radians(a))) for a in (90,30,-30,-90,-150,150)]
    segs = [(V[i], V[(i+1) % 6]) for i in range(6)] + [((0.0,0.0), V[i]) for i in (1,3,5)]
    rows = []
    for r in range(H):
        y = 1.0 - 2.0*r/(H-1); line = ""
        for c in range(W):
            x = -1.15 + 2.3*c/(W-1)
            d = min(_segd(x, y, a[0], a[1], b[0], b[1]) for a, b in segs)
            line += "█" if d < 0.06 else ("░" if d < 0.13 else " ")
        rows.append(line)
    return rows

def show_logo(sub=""):
    clearscr()
    rows = render_logo()
    for i, rw in enumerate(rows):
        print(grad(i / max(len(rows), 1)) + rw + RSTC)
    print()
    print(grad(0.55) + f"   C S   F R A M E W O R K   " + DIM + f"v{VERSION} ({CODENAME})" + RSTC)
    if sub: print("   " + DIM + sub + RSTC)
    print()

# ─── json helpers ──────────────────────────────────────────────────────────
def jload(p: Path, default):
    try:
        p = Path(p)
        if p.exists(): return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e: log(f"jload {p}: {e}", "warn")
    return default

def jsave(p: Path, data):
    try:
        p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
        tmp.replace(p)
    except Exception as e: log(f"jsave {p}: {e}", "error")

# ─── config ────────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "setup_done": False, "version": VERSION,
    "platforms": {}, "paths": [],
    "prefs": {"default_mode": "chat", "stream": True, "auto_verify": False},
    "portable": DATA_HOME.name == "cs_data",
    "first_run_ts": None,
}
CFG = jload(CONFIG_P, dict(DEFAULT_CONFIG))
_SERVE = {"rec": None}

# -- new settings defaults --
CFG.setdefault("prefs", {})
CFG["prefs"].setdefault("auto_approve", True)
CFG["prefs"].setdefault("auto_ctx", True)
CFG["prefs"].setdefault("default_model", "")
CFG.setdefault("global_installed", False)

# -- new settings defaults --
CFG.setdefault("prefs", {})
CFG["prefs"].setdefault("auto_approve", True)
CFG["prefs"].setdefault("default_model", "")
CFG.setdefault("global_installed", False)

def save_cfg():
    CFG["version"] = VERSION; jsave(CONFIG_P, CFG)

# ─── utils ─────────────────────────────────────────────────────────────────
def run_cmd(cmd, shell=False, timeout=900, cwd=None, env=None):
    try:
        p = subprocess.run(cmd, shell=shell, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd, errors="replace", env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired: return 124, "timeout"
    except FileNotFoundError as e: return 127, str(e)
    except Exception as e: return 1, str(e)

def find_tool(name):
    w = shutil.which(name)
    if w: return w
    for ext in ("", ".exe", ".cmd", ".bat", ".ps1"):
        try:
            h = list(TOOLS_D.rglob(name + ext))
            if h: return str(h[0])
        except Exception: pass
    return None

def fuzzy(q, s):
    if not q: return True
    q, s = q.lower(), s.lower()
    if q in s: return True
    it = iter(s); return all(c in it for c in q)

def ask(prompt, default=""):
    try:
        s = input(prompt).strip()
        return s if s else default
    except (EOFError, KeyboardInterrupt):
        print(); return default

def ask_yn(prompt, default=False):
    d = "Y/n" if default else "y/N"
    s = ask(f"{prompt} [{d}] ").lower()
    return default if not s else s in ("y","yes","1","true","t")

def ask_int(prompt, default):
    s = ask(f"{prompt} [{default}] ")
    try: return int(s) if s else default
    except ValueError: return default

def ask_float(prompt, default):
    s = ask(f"{prompt} [{default}] ")
    try: return float(s) if s else default
    except ValueError: return default

def read_multiline(prompt):
    print(prompt); lines = []
    while True:
        try: l = input("  | ")
        except (EOFError, KeyboardInterrupt): print(); break
        if l.strip() == ".": break
        lines.append(l)
    return lines

# ─── sha256 ────────────────────────────────────────────────────────────────
def sha256_file(p, cb=None):
    p = Path(p); hc = jload(HASH_P, {}); k = str(p)
    try: st = p.stat()
    except OSError: return ""
    if k in hc and hc[k].get("mtime") == st.st_mtime and hc[k].get("size") == st.st_size:
        if cb: cb(1.0)
        return hc[k]["sha"]
    h = hashlib.sha256(); done = 0
    try:
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(HASH_CHUNK), b""):
                h.update(chunk); done += len(chunk)
                if cb: cb(done / max(st.st_size, 1))
    except OSError as e: log(f"sha256 {p}: {e}", "error"); return ""
    d = h.hexdigest()
    hc[k] = {"sha": d, "mtime": st.st_mtime, "size": st.st_size}; jsave(HASH_P, hc)
    return d

# ─── downloader ────────────────────────────────────────────────────────────
def download_file(url, dest, sha=None, resume=True, timeout=300, silent=False):
    dest = Path(dest); dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": f"{APP}/{VERSION}"}
    if resume and have > 0: headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 416 and have > 0:
            if not silent: bar(1.0, tag=dest.name[:26])
            if sha and sha256_file(part) != sha:
                part.unlink(missing_ok=True); raise ValueError("sha256 mismatch")
            part.replace(dest); return dest
        raise
    with resp:
        cl = resp.headers.get("Content-Length")
        total = (have + int(cl)) if cl else 0
        mode = "ab" if resp.status == 206 else "wb"
        if resp.status != 206: have = 0
        with open(part, mode) as fh:
            while True:
                chunk = resp.read(DOWNLOAD_CHUNK)
                if not chunk: break
                fh.write(chunk); have += len(chunk)
                if total and not silent: bar(have/total, tag=dest.name[:26])
    if not silent: bar(1.0, tag=dest.name[:26])
    if sha and sha256_file(part) != sha:
        part.unlink(missing_ok=True); raise ValueError("sha256 mismatch")
    part.replace(dest); log(f"downloaded {url} -> {dest}"); return dest

def fetch_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP}/{VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def fetch_text(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP}/{VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

# ─── system probe ──────────────────────────────────────────────────────────
def probe():
    info = {"os": sys.platform, "arch": platform.machine(),
            "python": sys.version.split()[0],
            "cpu": f"{os.cpu_count() or '?'} threads",
            "ram": "?", "gpu": "cpu-only", "disk": "?",
            "venv": sys.prefix != sys.base_prefix,
            "cuda": None, "metal": False, "rocm": False}
    try: info["ram"] = human(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except Exception:
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal"):
                    info["ram"] = human(int(line.split()[1]) * 1024); break
        except Exception: pass
    try: info["disk"] = human(shutil.disk_usage(str(DATA_HOME)).free) + " free"
    except Exception: pass
    if shutil.which("nvidia-smi"):
        rc, out = run_cmd(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], timeout=10)
        if rc == 0 and out.strip():
            info["gpu"] = "CUDA: " + out.strip().splitlines()[0]; info["cuda"] = True
    elif sys.platform == "darwin":
        if platform.machine() == "arm64":
            info["gpu"] = "Apple Silicon (Metal/MPS)"; info["metal"] = True
    elif shutil.which("rocminfo"):
        info["gpu"] = "AMD ROCm"; info["rocm"] = True
    return info

# ─── parsers ───────────────────────────────────────────────────────────────
_GGUF_SZ = {0:1,1:1,2:2,3:2,4:4,5:4,6:4,7:1,10:8,11:8,12:8}



# =====================================================================
#  Agent naming (derived from OS user)
# =====================================================================
def _current_user():
    for k in ("USERNAME", "USER", "LOGNAME", "USERPROFILE"):
        v = os.environ.get(k)
        if not v:
            continue
        if k == "USERPROFILE":
            v = v.replace("\\", "/").rstrip("/").split("/")[-1]
        v = v.split("@")[0].strip()
        if v:
            return v
    try:
        import getpass
        return getpass.getuser().split("@")[0].strip() or "user"
    except Exception:
        return "user"


CS_USER = _current_user()
AGENT_NAME = CS_USER + " Agent"
AGENT_PROMPT = CS_USER.lower() + " \u203a "


# =====================================================================
#  VRAM probe + auto n_ctx
# =====================================================================
def _vram_info():
    """Return (total_mb, free_mb) for GPU 0, or (0,0) if no NVIDIA."""
    if not shutil.which("nvidia-smi"):
        return 0, 0
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=6)
        lines = (r.stdout or "").strip().splitlines()
        if not lines:
            return 0, 0
        parts = [p.strip() for p in lines[0].split(",")]
        return int(parts[0]), int(parts[1])
    except Exception:
        return 0, 0


def _auto_n_ctx(rec, requested=None, floor=2048, cap=32768):
    """Pick an n_ctx that fits in current free VRAM.
    Uses a heuristic of ~64 MiB per 1k tokens of KV (empirical for
    Qwen3 / Bonsai ternary with f16 KV).
    """
    try:
        req = int(requested or 4096)
    except Exception:
        req = 4096
    try:
        total, free = _vram_info()
        if total == 0:
            return req
        model_mb = max(0, getattr(rec, "size", 0)) / (1024.0 * 1024.0)
        # reserve for CUDA context, recurrent state, activations
        overhead = 800
        try:
            if needs_prism_fork(rec):
                overhead += 400
        except Exception:
            pass
        budget = free - model_mb - overhead
        if budget <= 200:
            return max(1024, min(floor, req))
        # 64 MiB / 1k tokens (worst case, f16 KV)
        max_tokens = int(budget / 64.0 * 1024)
        # largest power of 2 <= max_tokens
        k = 1024
        while k * 2 <= max_tokens and k < cap:
            k *= 2
        return max(floor, min(k, cap))
    except Exception:
        return req


def parse_gguf(p, want_tensors=False):
    try:
        with open(p, "rb") as f:
            if f.read(4) != b"GGUF": return None
            ver = int.from_bytes(f.read(4), "little")
            nt  = int.from_bytes(f.read(8), "little")
            nkv = int.from_bytes(f.read(8), "little")
            meta = {}
            def rs():
                n = int.from_bytes(f.read(8), "little")
                if n > 10_000_000: raise ValueError("string too long")
                return f.read(n).decode("utf-8", "replace")
            def rv(t):
                if t == 8: return rs()
                if t == 9:
                    et = int.from_bytes(f.read(4), "little")
                    cn = int.from_bytes(f.read(8), "little")
                    if cn > MAX_ARRAY_PREVIEW:
                        for _ in range(cn):
                            if et == 8: f.seek(int.from_bytes(f.read(8), "little"), 1)
                            else: f.seek(_GGUF_SZ.get(et, 1), 1)
                        return f"<array:{cn}>"
                    return [rv(et) for _ in range(cn)]
                if t == 6: return struct.unpack("<f", f.read(4))[0]
                if t == 12: return struct.unpack("<d", f.read(8))[0]
                if t == 7: return f.read(1)[0] != 0
                return int.from_bytes(f.read(_GGUF_SZ.get(t, 1)), "little", signed=t in (1,3,5,11))
            for _ in range(nkv):
                k = rs(); vt = int.from_bytes(f.read(4), "little"); meta[k] = rv(vt)
            out = {"version": ver, "tensors": nt, "meta": meta}
            if want_tensors and nt:
                names = []
                for _ in range(min(nt, 500)):
                    try:
                        names.append(rs())
                        nd = int.from_bytes(f.read(4), "little")
                        f.seek(8*nd + 4 + 4 + 8, 1)
                    except Exception: break
                out["tensor_names"] = names
            return out
    except Exception as e:
        log(f"gguf parse fail {p}: {e}", "warn"); return None

def parse_safetensors(p):
    try:
        with open(p, "rb") as f:
            nb = f.read(8)
            if len(nb) < 8: return None
            n = int.from_bytes(nb, "little")
            if n <= 0 or n > MAX_SAFETENSORS_HDR: return None
            hb = f.read(n)
            if len(hb) < n: return None
            hdr = json.loads(hb.decode("utf-8"))
        size = Path(p).stat().st_size; bad = []; dtypes = set(); count = 0
        for k, v in hdr.items():
            if k == "__metadata__": continue
            count += 1; dtypes.add(v.get("dtype", "?"))
            off = v.get("data_offsets") or v.get("offsets") or [0,0]
            if len(off) != 2 or off[1] < off[0] or off[1] > size: bad.append(k)
        return {"tensors": count, "dtypes": sorted(dtypes),
                "meta": hdr.get("__metadata__", {}), "ok": not bad, "bad": bad}
    except Exception: return None

def check_onnx(p):
    try:
        with open(p, "rb") as f: head = f.read(32)
        if not head: return None
        ok = head[0] in (0x08,0x10,0x18,0x20) or head[:2] == b"\x08\x03"
        return {"ok": ok, "head": head[:8].hex()}
    except Exception: return None

def check_torch_zip(p):
    try:
        with zipfile.ZipFile(p) as z:
            return {"entries": len(z.namelist()), "ok": z.testzip() is None}
    except Exception: return None

def read_config_json(d):
    try: return json.loads((Path(d) / "config.json").read_text(encoding="utf-8"))
    except Exception: return None

def read_index_json(d):
    try: return json.loads((Path(d) / "model.safetensors.index.json").read_text(encoding="utf-8"))
    except Exception: return None

# ─── architecture resolver ─────────────────────────────────────────────────
ARCH_ALIASES = {
    "qwen":"QwenForCausalLM","qwen2":"Qwen2ForCausalLM","qwen2.5":"Qwen2ForCausalLM",
    "qwen25":"Qwen2ForCausalLM","qwen3":"Qwen3ForCausalLM","qwen3.5":"Qwen3ForCausalLM",
    "qwen35":"Qwen3ForCausalLM","qwen3moe":"Qwen3MoeForCausalLM","qwen2moe":"Qwen2MoeForCausalLM",
    "qwen2vl":"Qwen2VLForConditionalGeneration","qwen25vl":"Qwen2_5_VLForConditionalGeneration",
    "bonsai":"Qwen2ForCausalLM","bonsai2":"Qwen2ForCausalLM","bonsai3":"Qwen3ForCausalLM",
    "bonsaiforcausallm":"Qwen2ForCausalLM","bonsai2forcausallm":"Qwen2ForCausalLM",
    "llama":"LlamaForCausalLM","llama2":"LlamaForCausalLM","llama3":"LlamaForCausalLM",
    "llama3.1":"LlamaForCausalLM","llama31":"LlamaForCausalLM","llama3.2":"LlamaForCausalLM",
    "llama32":"LlamaForCausalLM","codellama":"LlamaForCausalLM",
    "mistral":"MistralForCausalLM","mixtral":"MixtralForCausalLM",
    "gemma":"GemmaForCausalLM","gemma2":"Gemma2ForCausalLM","gemma3":"Gemma3ForCausalLM",
    "paligemma":"PaliGemmaForConditionalGeneration",
    "phi":"PhiForCausalLM","phi3":"Phi3ForCausalLM","phi4":"Phi3ForCausalLM","phimoe":"PhimoeForCausalLM",
    "deepseek":"DeepseekForCausalLM","deepseek2":"DeepseekV2ForCausalLM",
    "deepseekv2":"DeepseekV2ForCausalLM","deepseekv3":"DeepseekV3ForCausalLM","deepseek3":"DeepseekV3ForCausalLM",
    "gpt2":"GPT2LMHeadModel","gptj":"GPTJForCausalLM","gptneox":"GPTNeoXForCausalLM",
    "falcon":"FalconForCausalLM","mpt":"MptForCausalLM","bloom":"BloomForCausalLM",
    "olmo":"OlmoForCausalLM","olmo2":"Olmo2ForCausalLM","stablelm":"StableLmForCausalLM",
    "granite":"GraniteForCausalLM","cohere":"CohereForCausalLM","commandr":"CohereForCausalLM",
}

_FALLBACKS = ["AutoModelForCausalLM","Qwen2ForCausalLM","Qwen3ForCausalLM",
              "LlamaForCausalLM","MistralForCausalLM","Gemma2ForCausalLM","Phi3ForCausalLM"]

def normalize_arch(name):
    if not name: return "?"
    raw = str(name).strip()
    if not raw or raw == "?": return "?"
    for suf in ("ForCausalLM","ForConditionalGeneration","LMHeadModel"):
        if raw.endswith(suf):
            base = raw[:-len(suf)]
            m = ARCH_ALIASES.get(base.lower())
            return m if m else raw
    k = raw.lower()
    if k in ARCH_ALIASES: return ARCH_ALIASES[k]
    k2 = re.sub(r"[^a-z0-9]", "", k)
    if k2 in ARCH_ALIASES: return ARCH_ALIASES[k2]
    return raw

def arch_chain(arch):
    real = normalize_arch(arch); c = []
    if real and real not in ("?", "AutoModelForCausalLM"): c.append(real)
    for fb in _FALLBACKS:
        if fb not in c: c.append(fb)
    return c

def arch_disp(arch):
    if not arch or arch == "?": return "?"
    real = normalize_arch(arch)
    return arch if real == arch else f"{arch} → {real}"

# ─── model record ──────────────────────────────────────────────────────────
@dataclass
class ModelRec:
    name: str
    path: Path
    kind: str
    size: int = 0
    arch: str = "?"
    source: str = "local"
    expected_sha: Optional[str] = None
    meta: dict = field(default_factory=dict)

    def slug(self):
        return re.sub(r"[^A-Za-z0-9._-]+", "_", self.name)[:80] or "model"

    def to_dict(self):
        d = asdict(self); d["path"] = str(self.path); return d

def rec_from_dict(d):
    return ModelRec(d.get("name","?"), Path(d.get("path","")), d.get("kind","?"),
                    int(d.get("size",0)), d.get("arch","?"), d.get("source","local"),
                    d.get("expected_sha"), d.get("meta",{}) or {})

# ─── scanner ───────────────────────────────────────────────────────────────
def fetch_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "cs/" + VERSION})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_text(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "cs/" + VERSION})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def hf_search(q, limit=12):
    url = ("https://huggingface.co/api/models?search=" +
           urllib.parse.quote(q) +
           "&limit=" + str(limit) + "&sort=downloads&direction=-1")
    return fetch_json(url, timeout=30)


def hf_siblings(repo):
    url = "https://huggingface.co/api/models/" + repo
    return fetch_json(url, timeout=30).get("siblings", [])


def hf_download_repo(repo, only=None):
    dest_root = DL_D / "hf" / repo.replace("/", "__")
    sib = hf_siblings(repo)
    files = [x["rfilename"] for x in sib]
    pats = ("*.safetensors", "*.gguf", "*.bin", "*.onnx", "config.json",
            "*.index.json", "tokenizer*", "special_tokens_map.json",
            "generation_config.json", "*.model", "vocab.*", "merges.txt")
    pick = [f for f in files
            if (only and fnmatch.fnmatch(f, only)) or
            (not only and any(fnmatch.fnmatch(f, p) for p in pats))]
    print(CY + "  " + repo + ": " + str(len(pick)) + " file(s)" + RSTC)
    for f in pick:
        url = "https://huggingface.co/" + repo + "/resolve/main/" + f
        dest = dest_root / f
        if dest.exists():
            print(DIM + "    = skip " + f + RSTC)
            continue
        try:
            download_file(url, dest)
        except Exception as e:
            print(RD + "    x " + f + ": " + str(e) + RSTC)
    print(GR + "  v downloaded to " + str(dest_root) + RSTC)
    return dest_root


def model_roots():
    roots = [
        MODELS_D,
        Path.home() / ".cache/huggingface/hub",
        Path.home() / ".lmstudio/models",
        Path.home() / ".ollama/models",
        Path.home() / "models",
        Path.cwd() / "models",
    ]
    roots += [Path(x) for x in os.environ.get("CS_MODEL_PATHS", "").split(os.pathsep) if x]
    roots += [Path(x) for x in CFG.get("paths", [])]
    seen, out = set(), []
    for r in roots:
        try: r = Path(r).expanduser().resolve()
        except Exception: continue
        if r.exists() and str(r) not in seen:
            seen.add(str(r)); out.append(r)
    return out

def _blob_sha_of(p):
    try:
        if p.is_symlink():
            tn = p.resolve().name
            if len(tn) == 64 and all(c in "0123456789abcdef" for c in tn): return tn
    except Exception: pass
    return None

def _arch_from_cfg(cj):
    if not cj: return "?"
    a = cj.get("architectures") or []
    if a: return normalize_arch(a[0])
    mt = cj.get("model_type")
    return normalize_arch(mt) if mt else "?"

def _arch_from_gguf(g):
    if not g: return "?"
    meta = g.get("meta", {})
    raw = meta.get("general.architecture") or meta.get("general.name", "?")
    norm = normalize_arch(str(raw))
    if norm == raw and meta.get("general.name"):
        alt = normalize_arch(str(meta["general.name"]))
        if alt != meta["general.name"]: return alt
    return norm

def scan_models():
    recs, seen = [], set()
    def add(r):
        k = str(r.path)
        if k not in seen: seen.add(k); recs.append(r)

    # ollama manifests
    man = Path.home() / ".ollama/models/manifests"
    if man.exists():
        for mf in man.rglob("*.json"):
            try:
                d = json.loads(mf.read_text(encoding="utf-8"))
                for ly in d.get("layers", []):
                    if "image.model" in ly.get("mediaType", ""):
                        blob = Path.home() / ".ollama/models/blobs" / ly["digest"].replace(":", "-")
                        if blob.exists():
                            parts = mf.relative_to(man).parts
                            nm = "/".join(parts[1:]) if len(parts) > 2 else mf.stem
                            g = parse_gguf(blob)
                            add(ModelRec(nm, blob, "gguf", blob.stat().st_size,
                                         _arch_from_gguf(g), "ollama",
                                         ly["digest"].split(":")[-1]))
            except Exception: pass

    for root in model_roots():
        if root.name == "models" and root.parent.name == ".ollama": continue
        for dirpath, dirnames, filenames in os.walk(root):
            d = Path(dirpath)
            dirnames[:] = [x for x in dirnames if x not in ("blobs",".git",".cache","__pycache__",".venv","node_modules")]
            if "config.json" in filenames:
                cj = read_config_json(d) or {}
                arch = _arch_from_cfg(cj)
                shards = [f for f in filenames if f.endswith((".safetensors",".bin"))]
                has_onnx = any(f.endswith(".onnx") for f in filenames)
                try: size = sum((d/f).stat().st_size for f in filenames)
                except Exception: size = 0
                exp = None
                for f in shards: exp = _blob_sha_of(d/f) or exp
                src = ("hf-hub" if "huggingface" in str(d) else
                       "lmstudio" if ".lmstudio" in str(d) else "local")
                add(ModelRec(d.name, d, "tf-dir", size, arch, src, exp,
                             {"shards": shards, "onnx": has_onnx}))
                dirnames[:] = []; continue
            for fn in filenames:
                p = d/fn; ext = p.suffix.lower()
                if ext not in (".gguf",".safetensors",".onnx",".bin"): continue
                try: sz = p.stat().st_size
                except OSError: continue
                kind = {".gguf":"gguf",".safetensors":"safetensors",".onnx":"onnx",".bin":"bin"}[ext]
                arch = "?"
                if kind == "gguf":
                    g = parse_gguf(p)
                    if not g: continue
                    arch = _arch_from_gguf(g)
                src = ("hf-hub" if "huggingface" in str(p) else
                       "lmstudio" if ".lmstudio" in str(p) else "local")
                add(ModelRec(fn, p, kind, sz, arch, src, _blob_sha_of(p)))
    jsave(SCAN_P, [r.to_dict() for r in recs]); log(f"scan: {len(recs)}")
    return recs

def load_scan(rescan=False):
    if not rescan and SCAN_P.exists():
        try: return [rec_from_dict(x) for x in json.loads(SCAN_P.read_text(encoding="utf-8"))]
        except Exception: pass
    return scan_models()

def platform_records():
    return [ModelRec(p, Path(p), "platform", 0, "remote-api", "platform")
            for p in CFG.get("platforms", {})]

# ─── verify ────────────────────────────────────────────────────────────────
def sidecar_sha(p):
    for c in (Path(p).with_name(Path(p).name + ".sha256"),
              Path(p).with_suffix(Path(p).suffix + ".sha256")):
        if c.exists():
            t = c.read_text().split()
            if t and len(t[0]) == 64: return t[0]
    return None

def verify_rec(r, deep=False, online=False):
    res = []
    def chk(l, ok, info=""): res.append((l, bool(ok), str(info)))
    p = Path(r.path)
    chk("exists", p.exists(), str(p))
    if not p.exists(): return res, False
    chk("size>0", r.size > 0, human(r.size))
    if r.kind == "gguf":
        g = parse_gguf(p) if p.is_file() else None
        chk("gguf header", g is not None, f"arch={r.arch} v{(g or {}).get('version','?')}")
        chk("arch recognized", normalize_arch(r.arch) != "?", arch_disp(r.arch))
    elif r.kind == "safetensors":
        s = parse_safetensors(p)
        chk("safetensors header", s is not None, f"{(s or {}).get('tensors',0)} tensors")
        if s: chk("tensor offsets", s["ok"], ",".join(s["bad"][:3]))
    elif r.kind == "tf-dir":
        chk("config.json", (p/"config.json").exists(), r.arch)
        idx = read_index_json(p)
        if idx:
            wm = set(idx.get("weight_map", {}).values())
            miss = [s for s in wm if not (p/s).exists()]
            chk("shard completeness", not miss, f"{len(wm)} shards")
    elif r.kind == "onnx":
        o = check_onnx(p); chk("onnx header", bool(o and o["ok"]))
    elif r.kind == "bin":
        z = check_torch_zip(p); chk("pytorch zip", z is not None)
    exp = r.expected_sha or sidecar_sha(p)
    if p.is_file() and (exp or deep):
        got = sha256_file(p, cb=(lambda f: bar(f, tag=p.name[:24])) if CIN else None)
        if exp: chk("sha256", got == exp, got[:16])
        else: chk("sha256 (recorded)", True, got[:16])
    ok = all(o for _, o, _ in res)
    vc = jload(VER_P, {}); vc[str(p)] = {"ok": ok, "ts": time.time()}; jsave(VER_P, vc)
    return res, ok

# ─── context ───────────────────────────────────────────────────────────────
DEFAULT_CONTEXT = {
    "system": "You are a helpful, precise assistant.",
    "n_ctx": 4096, "max_new_tokens": 512,
    "temperature": 0.7, "top_p": 0.95, "top_k": 40, "repeat_penalty": 1.1,
    "n_gpu_layers": -1, "threads": 0, "seed": -1, "stop": [],
}

def load_contexts(): return jload(CTX_P, {})
def save_contexts(d): jsave(CTX_P, d)

def get_context(rec):
    d = load_contexts(); ctx = dict(DEFAULT_CONTEXT)
    ctx.update(d.get(rec.slug(), {})); return ctx

def set_context(rec, ctx):
    d = load_contexts(); d[rec.slug()] = ctx; save_contexts(d)

def edit_context(rec):
    ctx = get_context(rec)
    print()
    print(box(f"CONTEXT — {rec.name}",
              [f"kind/arch : {rec.kind} / {arch_disp(rec.arch)}",
               f"size      : {human(rec.size)}",
               "", "Enter keeps the current value.",
               "'::' enters multiline mode for the system prompt."]))
    s = ask("  system prompt (Enter keep, '::' multiline): ")
    if s == "::":
        lines = read_multiline("  system prompt, '.' to end:")
        if lines: ctx["system"] = "\n".join(lines)
    elif s: ctx["system"] = s
    ctx["n_ctx"]          = ask_int("  n_ctx", ctx["n_ctx"])
    ctx["max_new_tokens"] = ask_int("  max_new_tokens", ctx["max_new_tokens"])
    ctx["temperature"]    = ask_float("  temperature", ctx["temperature"])
    ctx["top_p"]          = ask_float("  top_p", ctx["top_p"])
    ctx["top_k"]          = ask_int("  top_k", ctx["top_k"])
    ctx["repeat_penalty"] = ask_float("  repeat_penalty", ctx["repeat_penalty"])
    ctx["n_gpu_layers"]   = ask_int("  n_gpu_layers (-1 all, 0 cpu)", ctx["n_gpu_layers"])
    ctx["threads"]        = ask_int("  threads (0 auto)", ctx["threads"])
    set_context(rec, ctx)
    print(GR + f"  v saved context for {rec.name}" + RSTC)
    return ctx

# ─── runtimes ──────────────────────────────────────────────────────────────
ARCH_HOOKS: dict = {}
_PLUGIN_RTS: list = []
_RUNTIME_PICK: dict = {}



# --- force-register all computer-use + extras (defensive; overwrites dupes) ---
_CU_MAP = {
    "screen":       ("Screenshot to a file. args: {path:str=''}", globals().get("_t_screen")),
    "screen_size":  ("Screen resolution. args: {}",              globals().get("_t_screen_size")),
    "mouse_move":   ("Move mouse. args: {x:int, y:int}",         globals().get("_t_mouse_move")),
    "mouse_click":  ("Click. args: {x:int, y:int, button:str='left', clicks:int=1}", globals().get("_t_mouse_click")),
    "mouse_drag":   ("Drag. args: {x1,y1,x2,y2}",                globals().get("_t_mouse_drag")),
    "scroll":       ("Scroll. args: {amount:int=3}",             globals().get("_t_scroll")),
    "key":          ("Press key or hotkey. args: {keys:str}",    globals().get("_t_key")),
    "type":         ("Type text. args: {text:str}",              globals().get("_t_type")),
    "window_list":  ("List visible windows. args: {}",           globals().get("_t_window_list")),
    "window_focus": ("Focus a window. args: {title:str}",        globals().get("_t_window_focus")),
    "app_start":    ("Launch an app. args: {name:str, args:list=[]}", globals().get("_t_app_start")),
    "sleep":        ("Sleep N seconds. args: {seconds:float}",   globals().get("_t_sleep")),
    "ocr":          ("OCR a screenshot. args: {path:str=''}",    globals().get("_t_ocr")),
    "python":       ("Run Python. args: {code:str}",             globals().get("_t_python")),
    "http":         ("HTTP GET. args: {url:str}",                globals().get("_t_http")),
    "download":     ("Download to file. args: {url:str, path:str}", globals().get("_t_download")),
    "extract":      ("Extract archive. args: {path:str}",        globals().get("_t_extract")),
    "tree":         ("Directory tree. args: {path:str='.', depth:int=3}", globals().get("_t_tree")),
    "diff":         ("Unified diff. args: {a:str, b:str}",       globals().get("_t_diff")),
    "find":         ("Find files. args: {name:str, root:str='.'}", globals().get("_t_find")),
    "wc":           ("Line/word/char count. args: {path:str}",   globals().get("_t_wc")),
    "notify":       ("Desktop notification. args: {title:str, msg:str}", globals().get("_t_notify")),
    "clip_read":    ("Read clipboard. args: {}",                 globals().get("_t_clip_read")),
    "clip_write":   ("Write clipboard. args: {text:str}",        globals().get("_t_clip_write")),
}
try:
    TOOLS_IMPL = globals().setdefault("TOOLS_IMPL", {})
    _spec_by_name = {d.get("name"): d for d in TOOLS_SPEC} if "TOOLS_SPEC" in globals() else {}
    for _n, (_desc, _fn) in _CU_MAP.items():
        if _fn is None:
            continue
        TOOLS_IMPL[_n] = _fn
        if _n not in _spec_by_name:
            TOOLS_SPEC.append({"name": _n, "desc": _desc})
            _spec_by_name[_n] = {"name": _n, "desc": _desc}
except Exception:
    pass

# --- rolling context / scratchpad ---
SCRATCH_P = DATA_HOME / "agent" / "scratchpad.md"
SCRATCH_P.parent.mkdir(parents=True, exist_ok=True)
_SCRATCH_STATE = {"last_save": 0.0, "pending": []}


def _uv_bin():
    """Find or install `uv`. Returns a path or None."""
    u = shutil.which("uv") or shutil.which("uv.exe")
    if u:
        return u
    print(DIM + "  installing uv (fast package manager)..." + RSTC)
    try:
        subprocess.call([sys.executable, "-m", "pip", "install", "-q",
                         "--user", "uv"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    for p in (Path.home() / ".local" / "bin",
              Path.home() / "AppData" / "Roaming" / "Python" /
              f"Python{sys.version_info.major}{sys.version_info.minor}" / "Scripts",
              Path.home() / "AppData" / "Roaming" / "Python" / "Scripts"):
        for exe in ("uv", "uv.exe"):
            q = p / exe
            if q.exists():
                return str(q)
    u = shutil.which("uv") or shutil.which("uv.exe")
    return u


def _venv_python(vid):
    d = VENVS_D / vid
    if os.name == "nt":
        return d / "Scripts" / "python.exe"
    return d / "bin" / "python"


def _venv_stamp(vid):
    return VENVS_D / vid / ".specs"


def _venv_wipe(vid):
    d = VENVS_D / vid
    if d.exists():
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass


def _venv_ensure(vid, force=False, system_site=True):
    """Create venv if missing. Returns (python_path, specs_list)."""
    specs = _VENV_SPECS.get(vid, [])
    py = _venv_python(vid)
    want = "|".join(specs)
    have = ""
    sp = _venv_stamp(vid)
    if sp.exists():
        try:
            have = sp.read_text(encoding="utf-8").strip()
        except Exception:
            have = ""

    if force or not py.exists() or have != want:
        if force:
            print(CY + "  wiping venv " + vid + "..." + RSTC)
        else:
            print(CY + "  building venv " + vid + "..." + RSTC)
        _venv_wipe(vid)
        VENVS_D.mkdir(parents=True, exist_ok=True)
        uv = _uv_bin()
        args = []
        if uv:
            args = [uv, "venv", str(VENVS_D / vid),
                    "--python", sys.executable]
            if system_site:
                args.append("--system-site-packages")
        else:
            args = [sys.executable, "-m", "venv",
                    str(VENVS_D / vid)]
            if system_site:
                args.append("--system-site-packages")
        subprocess.call(args)
        if not py.exists():
            raise RuntimeError("venv creation failed for " + vid)

        if specs:
            print(DIM + "  installing " + str(len(specs)) +
                  " packages into " + vid + "..." + RSTC)
            if uv:
                inst = [uv, "pip", "install",
                        "--python", str(py),
                        "--quiet"] + specs
            else:
                inst = [str(py), "-m", "pip", "install",
                        "-q"] + specs
            rc = subprocess.call(inst)
            if rc != 0:
                # try again without --quiet to see the real error
                if uv:
                    inst = [uv, "pip", "install",
                            "--python", str(py)] + specs
                else:
                    inst = [str(py), "-m", "pip", "install"] + specs
                rc = subprocess.call(inst)
                if rc != 0:
                    raise RuntimeError("pip install failed in " + vid)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(want, encoding="utf-8")
        print(GR + "  v venv " + vid + " ready" + RSTC)
    return py, specs


def _venv_run_json(vid, payload, timeout=3600, on_token=None):
    """Run a worker in the venv. payload is a dict; worker emits JSON lines."""
    py, _ = _venv_ensure(vid)
    import tempfile, json as _j
    # write worker script to a temp file
    script_path = VENVS_D / vid / "_worker.py"
    script_path.write_text(WORKER_SOURCE, encoding="utf-8")
    body = _j.dumps(payload)
    proc = subprocess.Popen(
        [str(py), str(script_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1,
        errors="replace",
    )
    try:
        proc.stdin.write(body + "\n")
        proc.stdin.flush()
        proc.stdin.close()
    except Exception:
        pass
    final_err = ""
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            obj = _j.loads(line)
        except Exception:
            continue
        if "token" in obj and on_token:
            on_token(obj["token"])
        elif "error" in obj:
            final_err = obj["error"]
        elif obj.get("done"):
            break
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    err_out = ""
    try:
        err_out = proc.stderr.read() or ""
    except Exception:
        pass
    if final_err:
        raise RuntimeError(final_err)
    if proc.returncode != 0 and err_out:
        raise RuntimeError(err_out[-2000:])


WORKER_SOURCE = base64.b64decode(
    'aW1wb3J0IHN5cywganNvbiwgdGhyZWFkaW5nCmRlZiBtYWluKCk6CiAgICBsaW5lID0gc3lzLnN0'
    'ZGluLnJlYWRsaW5lKCkKICAgIHRyeToKICAgICAgICByZXEgPSBqc29uLmxvYWRzKGxpbmUpCiAg'
    'ICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgcHJpbnQoanNvbi5kdW1wcyh7J2Vycm9y'
    'JzogJ2JhZCByZXF1ZXN0OiAnICsgc3RyKGUpfSkpOyBzeXMuc3Rkb3V0LmZsdXNoKCk7IHJldHVy'
    'bgogICAgb3AgPSByZXEuZ2V0KCdvcCcsICdjaGF0JykKICAgIGlmIG9wID09ICdwaW5nJzoKICAg'
    'ICAgICBwcmludChqc29uLmR1bXBzKHsnZG9uZSc6IFRydWUsICdwb25nJzogVHJ1ZX0pKTsgc3lz'
    'LnN0ZG91dC5mbHVzaCgpOyByZXR1cm4KICAgIGlmIG9wID09ICdjaGF0JzoKICAgICAgICBtb2Rl'
    'bF9kaXIgPSByZXEuZ2V0KCdtb2RlbF9kaXInLCAnJykKICAgICAgICBhcmNoID0gcmVxLmdldCgn'
    'YXJjaCcsICcnKQogICAgICAgIHByb21wdCA9IHJlcS5nZXQoJ3Byb21wdCcsICcnKQogICAgICAg'
    'IG1heF9uZXcgPSBpbnQocmVxLmdldCgnbWF4X25ld190b2tlbnMnLCA1MTIpKQogICAgICAgIHRl'
    'bXAgPSBmbG9hdChyZXEuZ2V0KCd0ZW1wZXJhdHVyZScsIDAuNykpCiAgICAgICAgdG9wX3AgPSBm'
    'bG9hdChyZXEuZ2V0KCd0b3BfcCcsIDAuOTUpKQogICAgICAgIHRvcF9rID0gaW50KHJlcS5nZXQo'
    'J3RvcF9rJywgNDApKQogICAgICAgIHJlcCA9IGZsb2F0KHJlcS5nZXQoJ3JlcGVhdF9wZW5hbHR5'
    'JywgMS4xKSkKICAgICAgICB0cnk6CiAgICAgICAgICAgIGltcG9ydCB0b3JjaAogICAgICAgICAg'
    'ICBmcm9tIHRyYW5zZm9ybWVycyBpbXBvcnQgKEF1dG9Ub2tlbml6ZXIsIEF1dG9Nb2RlbEZvckNh'
    'dXNhbExNLCBUZXh0SXRlcmF0b3JTdHJlYW1lcikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFz'
    'IGU6CiAgICAgICAgICAgIHByaW50KGpzb24uZHVtcHMoeydlcnJvcic6ICdpbXBvcnQ6ICcgKyBz'
    'dHIoZSl9KSk7IHN5cy5zdGRvdXQuZmx1c2goKTsgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAg'
    'ICAgICB0b2sgPSBBdXRvVG9rZW5pemVyLmZyb21fcHJldHJhaW5lZChtb2RlbF9kaXIsIHRydXN0'
    'X3JlbW90ZV9jb2RlPVRydWUpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAg'
    'dHJ5OgogICAgICAgICAgICAgICAgdG9rID0gQXV0b1Rva2VuaXplci5mcm9tX3ByZXRyYWluZWQo'
    'bW9kZWxfZGlyLCB0cnVzdF9yZW1vdGVfY29kZT1UcnVlLCB1c2VfZmFzdD1GYWxzZSkKICAgICAg'
    'ICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgcHJpbnQoanNvbi5k'
    'dW1wcyh7J2Vycm9yJzogJ3Rva2VuaXplcjogJyArIHN0cihlKX0pKTsgc3lzLnN0ZG91dC5mbHVz'
    'aCgpOyByZXR1cm4KICAgICAgICBpbXBvcnQgdHJhbnNmb3JtZXJzIGFzIF90cgogICAgICAgIGNo'
    'YWluID0gW10KICAgICAgICBpZiBhcmNoIGFuZCBhcmNoICE9ICc/JzogY2hhaW4uYXBwZW5kKGFy'
    'Y2gpCiAgICAgICAgZm9yIG4gaW4gKCdBdXRvTW9kZWxGb3JDYXVzYWxMTScsJ1F3ZW4yRm9yQ2F1'
    'c2FsTE0nLCdRd2VuM0ZvckNhdXNhbExNJywnTGxhbWFGb3JDYXVzYWxMTScsJ01pc3RyYWxGb3JD'
    'YXVzYWxMTScsJ0dlbW1hMkZvckNhdXNhbExNJywnUGhpM0ZvckNhdXNhbExNJyk6CiAgICAgICAg'
    'ICAgIGlmIG4gbm90IGluIGNoYWluOiBjaGFpbi5hcHBlbmQobikKICAgICAgICBtb2QgPSBOb25l'
    'OyBlcnJzID0gW10KICAgICAgICBmb3IgY24gaW4gY2hhaW46CiAgICAgICAgICAgIHRyeToKICAg'
    'ICAgICAgICAgICAgIGNscyA9IGdldGF0dHIoX3RyLCBjbiwgTm9uZSkKICAgICAgICAgICAgICAg'
    'IGlmIGNscyBpcyBOb25lOiBjb250aW51ZQogICAgICAgICAgICAgICAgbW9kID0gY2xzLmZyb21f'
    'cHJldHJhaW5lZChtb2RlbF9kaXIsIHRydXN0X3JlbW90ZV9jb2RlPVRydWUsIGRldmljZV9tYXA9'
    'J2F1dG8nKQogICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlv'
    'biBhcyBlOgogICAgICAgICAgICAgICAgZXJycy5hcHBlbmQoY24gKyAnOiAnICsgc3RyKGUpWzox'
    'NTBdKQogICAgICAgIGlmIG1vZCBpcyBOb25lOgogICAgICAgICAgICBwcmludChqc29uLmR1bXBz'
    'KHsnZXJyb3InOiAnbG9hZDogJyArICc7ICcuam9pbihlcnJzWy0zOl0pfSkpOyBzeXMuc3Rkb3V0'
    'LmZsdXNoKCk7IHJldHVybgogICAgICAgIHN0ID0gVGV4dEl0ZXJhdG9yU3RyZWFtZXIodG9rLCBz'
    'a2lwX3Byb21wdD1UcnVlLCBza2lwX3NwZWNpYWxfdG9rZW5zPVRydWUpCiAgICAgICAgdHJ5Ogog'
    'ICAgICAgICAgICBpbnAgPSB0b2socHJvbXB0LCByZXR1cm5fdGVuc29ycz0ncHQnKS50byhtb2Qu'
    'ZGV2aWNlKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIGlucCA9IHRvayhw'
    'cm9tcHQsIHJldHVybl90ZW5zb3JzPSdwdCcpCiAgICAgICAga3cgPSB7J2lucHV0X2lkcyc6IGlu'
    'cC5pbnB1dF9pZHMsICdzdHJlYW1lcic6IHN0LCAnbWF4X25ld190b2tlbnMnOiBtYXhfbmV3LAog'
    'ICAgICAgICAgICAgICdkb19zYW1wbGUnOiB0ZW1wID4gMCwgJ3RlbXBlcmF0dXJlJzogbWF4KDAu'
    'MDEsIHRlbXApLAogICAgICAgICAgICAgICd0b3BfcCc6IHRvcF9wLCAndG9wX2snOiB0b3Bfaywg'
    'J3JlcGV0aXRpb25fcGVuYWx0eSc6IHJlcH0KICAgICAgICBpZiBoYXNhdHRyKGlucCwgJ2F0dGVu'
    'dGlvbl9tYXNrJyk6IGt3WydhdHRlbnRpb25fbWFzayddID0gaW5wLmF0dGVudGlvbl9tYXNrCiAg'
    'ICAgICAgdGggPSB0aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1tb2QuZ2VuZXJhdGUsIGt3YXJncz1r'
    'dywgZGFlbW9uPVRydWUpOyB0aC5zdGFydCgpCiAgICAgICAgZm9yIHQgaW4gc3Q6CiAgICAgICAg'
    'ICAgIGlmIHQ6CiAgICAgICAgICAgICAgICBzeXMuc3Rkb3V0LndyaXRlKGpzb24uZHVtcHMoeyd0'
    'b2tlbic6IHR9KSArICdcbicpOyBzeXMuc3Rkb3V0LmZsdXNoKCkKICAgICAgICB0aC5qb2luKHRp'
    'bWVvdXQ9NjApCiAgICAgICAgc3lzLnN0ZG91dC53cml0ZShqc29uLmR1bXBzKHsnZG9uZSc6IFRy'
    'dWV9KSArICdcbicpOyBzeXMuc3Rkb3V0LmZsdXNoKCkKICAgICAgICByZXR1cm4KICAgIHByaW50'
    'KGpzb24uZHVtcHMoeydlcnJvcic6ICd1bmtub3duIG9wOiAnICsgb3B9KSk7IHN5cy5zdGRvdXQu'
    'Zmx1c2goKQptYWluKCkK'
).decode('utf-8')

# === SCRATCHPAD (canonical) ===
def _scratch_path():
    p = DATA_HOME / "agent" / "scratchpad.md"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p


def _scratch_load(max_lines=30):
    """Return the last N lines of the scratchpad."""
    try:
        p = _scratch_path()
        if not p.exists():
            return ""
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        n = int(max_lines) if max_lines else 0
        if n > 0:
            lines = lines[-n:]
        return "\n".join(lines)
    except Exception:
        return ""


def _scratch_append(role, text, force_save=True):
    """Append one compact line. `role` is 'user' / 'hex' / 'tool' etc."""
    try:
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if not text:
            return
        p = _scratch_path()
        stamp = time.strftime("%H:%M")
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("[" + stamp + " " + str(role) + "] " + text[:260] + "\n")
    except Exception:
        pass


def _scratch_clear():
    try:
        p = _scratch_path()
        if p.exists():
            p.unlink()
    except Exception:
        pass


def _scratch_compact(max_lines=220):
    try:
        p = _scratch_path()
        if not p.exists():
            return
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) <= max_lines:
            return
        p.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")
    except Exception:
        pass


# === end SCRATCHPAD ===

class BaseRuntime:
    id = "base"; kinds = ()
    def available(self): return True, ""
    def can_run(self, r): return r.kind in self.kinds
    def stream(self, r, prompt, hist, ctx): yield "[no output]"

class PrismForkRT(BaseRuntime):
    """Uses the PrismML fork binaries for ternary models."""
    id = "prism-fork"
    kinds = ("gguf",)

    def available(self):
        return (True, "") if _prism_server() else (False, "prism fork not installed")

    def can_run(self, r): return needs_prism_fork(r)

    def stream(self, r, prompt, hist, ctx):
        # delegated to LlamaServerRT / LlamaCliRT which check needs_prism_fork
        yield "[prism-fork delegated]"

class LlamaCppPyRT(BaseRuntime):
    id = "llama.cpp-py"
    kinds = ("gguf",)
    _cache = {}
    _lock = threading.Lock()

    def available(self):
        return (True, "") if importlib.util.find_spec("llama_cpp") else \
               (False, "pip install llama-cpp-python")

    def can_run(self, r):
        try:
            if needs_prism_fork(r):
                return False
        except Exception:
            pass
        return r.kind in self.kinds

    def stream(self, r, prompt, hist, ctx):
        try:
            from llama_cpp import Llama
        except Exception as e:
            yield "[llama.cpp-py unavailable: " + str(e) + "]"; return
        key = (str(r.path), int(ctx["n_ctx"]), int(ctx["n_gpu_layers"]))
        with self._lock:
            llm = self._cache.get(key)
        if llm is None:
            try:
                llm = Llama(model_path=str(r.path),
                            n_ctx=int(ctx["n_ctx"]),
                            n_gpu_layers=int(ctx["n_gpu_layers"]),
                            n_threads=int(ctx.get("threads", 0)) or None,
                            verbose=False)
                with self._lock:
                    self._cache = {key: llm}
            except Exception as e:
                msg = str(e)
                hint = ("  (try: cs install llamacpp-bin for the standalone "
                        "binary, or cs install llama-cpp-src)")
                if "unknown" in msg.lower() or needs_prism_fork(r):
                    yield ("[llama.cpp-py failed]\n    " + msg + "\n" + hint)
                else:
                    yield ("[llama.cpp-py failed]\n    " + msg)
                return
        try:
            for o in llm(prompt, stream=True,
                        max_tokens=int(ctx["max_new_tokens"]),
                        temperature=float(ctx["temperature"]),
                        top_p=float(ctx["top_p"]),
                        top_k=int(ctx["top_k"]),
                        repeat_penalty=float(ctx["repeat_penalty"])):
                t2 = o["choices"][0].get("text")
                if t2:
                    yield t2
        except Exception as e:
            yield "[stream error: " + str(e) + "]"


class LlamaServerRT(BaseRuntime):
    id = "llama-server"; kinds = ("gguf",)
    _proc = None; _key = None; _port = 0; _log_path = None; _log_fh = None

    def available(self): return (True, "") if find_tool("llama-server") else (False, "not installed")

    def _pick_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0)); return s.getsockname()[1]

    def _logfile(self, port):
        LOGS_D.mkdir(parents=True, exist_ok=True)
        return LOGS_D / f"llama-server-{port}.log"

    def _tail(self, n=80):
        if not self._log_path: return "(no log)"
        try:
            lines = Path(self._log_path).read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(lines[-n:])
        except Exception: return "(read failed)"

    def _kill(self):
        if self._proc is not None:
            try:
                if self._proc.poll() is None:
                    self._proc.terminate()
                    try: self._proc.wait(timeout=5)
                    except Exception: self._proc.kill()
            except Exception: pass
            self._proc = None
        if self._log_fh:
            try: self._log_fh.close()
            except Exception: pass
            self._log_fh = None

    def _wait_health(self, port, proc, timeout=300):
        url = f"http://127.0.0.1:{port}/health"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None: return False
            try:
                with urllib.request.urlopen(url, timeout=3) as r:
                    if r.status == 200: return True
            except urllib.error.HTTPError: pass
            except Exception: pass
            time.sleep(0.75)
        return False

    def _ensure(self, r, ctx):
        ternary = False
        try:
            ternary = bool(needs_prism_fork(r))
        except Exception:
            pass

        # ---- auto-adapt n_ctx to free VRAM ----
        if CFG.get("prefs", {}).get("auto_ctx", True):
            try:
                want = int(ctx.get("n_ctx", 4096))
                got = _auto_n_ctx(r, want)
                if got and got != want:
                    log("auto_ctx: " + str(want) + " -> " + str(got) +
                        " for " + r.name)
                    ctx = dict(ctx)
                    ctx["n_ctx"] = got
            except Exception:
                pass

        key = (str(r.path), int(ctx["n_ctx"]), int(ctx["n_gpu_layers"]),
               ternary)
        if self._proc and self._key == key and self._proc.poll() is None:
            return
        self._kill()

        tool = find_tool("llama-server")
        if ternary:
            ps = _prism_server()
            if ps:
                tool = ps
        if not tool:
            raise RuntimeError("llama-server binary not found")

        ngl_raw = int(ctx["n_gpu_layers"])
        ngl = 99 if ngl_raw < 0 else ngl_raw
        want_ctx = int(ctx["n_ctx"])

        # KEY FIX: --parallel 1 (was defaulting to 4)
        base = [tool, "-m", str(r.path),
                "--host", "127.0.0.1",
                "--parallel", "1",
                "-v", "-lv", "5"]
        if ctx.get("threads"):
            base += ["-t", str(int(ctx["threads"]))]
        fa = ["-fa", "on"] if ternary else []

        # context sizes to try: requested, half, quarter, 2048
        ctx_steps = []
        for v in (want_ctx, max(2048, want_ctx // 2),
                  max(2048, want_ctx // 4), 2048):
            if v not in ctx_steps and v >= 1024:
                ctx_steps.append(v)

        offloads = [
            ("full", ngl),
            ("40",   40),
            ("cpu",  0),
        ]

        last_tail = ""
        attempts_used = []
        for c_val in ctx_steps:
            for oname, olay in offloads:
                label = "ctx=" + str(c_val) + " ngl=" + str(olay)
                attempts_used.append(label)
                port = self._pick_port()
                log_path = self._logfile(port)
                self._log_path = log_path
                extra = ["-c", str(c_val), "-ngl", str(olay)] + fa
                args = base + extra + ["--port", str(port)]
                try:
                    self._log_fh = open(log_path, "w", encoding="utf-8",
                                        errors="replace")
                    self._log_fh.write("attempt: " + label + "\n")
                    self._log_fh.write("spawn: " + " ".join(args) + "\n")
                    self._log_fh.flush()
                except Exception:
                    self._log_fh = None
                try:
                    self._proc = subprocess.Popen(
                        args,
                        stdout=self._log_fh if self._log_fh
                               else subprocess.DEVNULL,
                        stderr=subprocess.STDOUT,
                        cwd=str(Path(r.path).parent),
                    )
                except FileNotFoundError:
                    self._kill()
                    raise RuntimeError(
                        "llama-server binary not found: " + str(tool))
                self._key = (str(r.path), c_val, olay, ternary)
                self._port = port
                if self._wait_health(port, self._proc, timeout=300):
                    log("llama-server ready: " + label +
                        " port " + str(port))
                    if c_val != want_ctx:
                        print()
                        print(YL + "  n_ctx auto-lowered to " + str(c_val) +
                              " (was " + str(want_ctx) + ") - OOM avoided"
                              + RSTC)
                    if olay != ngl:
                        print()
                        print(YL + "  ngl auto-lowered to " + str(olay) +
                              " (was " + str(ngl) + ")" + RSTC)
                    return
                last_tail = self._tail(60)
                self._kill()

        raise RuntimeError(
            "llama-server failed every attempt.\n"
            "  tried: " + ", ".join(attempts_used) + "\n"
            "  log: " + str(self._log_path) + "\n"
            "  tail:\n    " + last_tail.replace("\n", "\n    "))


    def stream(self, r, prompt, hist, ctx):
        self._ensure(r, ctx)
        msgs = []
        if ctx.get("system"): msgs.append({"role": "system", "content": ctx["system"]})
        if hist: msgs.extend(hist)
        else: msgs.append({"role": "user", "content": prompt})

        body = json.dumps({
            "messages": msgs, "stream": True,
            "max_tokens": int(ctx["max_new_tokens"]),
            "temperature": float(ctx["temperature"]),
            "top_p": float(ctx["top_p"]), "top_k": int(ctx["top_k"]),
            "repeat_penalty": float(ctx["repeat_penalty"]), "cache_prompt": True,
        }).encode()
        url = f"http://127.0.0.1:{self._port}/v1/chat/completions"
        req = urllib.request.Request(url, data=body, headers={"Content-Type":"application/json"})
        chars = 0
        try:
            with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    if not line or not line.startswith("data:"): continue
                    payload = line[5:].strip()
                    if payload == "[DONE]": break
                    try: obj = json.loads(payload)
                    except Exception: continue
                    choices = obj.get("choices") or [{}]
                    delta = choices[0].get("delta") or {}
                    t = delta.get("content")
                    if t: chars += len(t); yield t
        except Exception as e:
            yield f"[stream error: {e}]"; return
        if chars == 0: yield "[no tokens returned — check cs ll-log]"


class LlamaCliRT(BaseRuntime):
    id = "llama-cli"; kinds = ("gguf",)
    def available(self): return (True, "") if find_tool("llama-cli") else (False, "not installed")

    def stream(self, r, prompt, hist, ctx):
        tool = find_tool("llama-cli")
        if needs_prism_fork(r) and _prism_cli(): tool = _prism_cli()
        ngl_raw = int(ctx["n_gpu_layers"])
        args = [tool, "-m", str(r.path), "-p", prompt,
                "-n", str(int(ctx["max_new_tokens"])),
                "-c", str(int(ctx["n_ctx"])),
                "-ngl", str(99 if ngl_raw < 0 else ngl_raw),
                "--temp", str(ctx["temperature"]),
                "--top-p", str(ctx["top_p"]),
                "--top-k", str(ctx["top_k"]),
                "--no-display-prompt"]
        if needs_prism_fork(r): args += ["-fa", "on"]
        if ctx.get("threads"): args += ["-t", str(int(ctx["threads"]))]
        try:
            pr = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, errors="replace", bufsize=1)
        except FileNotFoundError:
            yield "[llama-cli not found]"; return
        for line in pr.stdout: yield line
        pr.wait()


class TransformersRT(BaseRuntime):
    id = "transformers"
    kinds = ("tf-dir", "safetensors", "bin")
    _cache = {}
    _lock = threading.Lock()
    _broken = False
    _bad_archs = {"DistilBertForMaskedLM", "SpeechT5ForTextToSpeech",
                  "SpeechT5HifiGan", "SpeechT5ForSpeechToText",
                  "Gemma4ForConditionalGeneration", "PaliGemmaForConditionalGeneration",
                  "Wav2Vec2ForCTC", "WhisperForConditionalGeneration"}

    def available(self):
        return True, ""

    def can_run(self, r):
        # never claim models that aren't chat-capable
        if r.arch in self._bad_archs:
            return False
        if r.kind == "tf-dir":
            return True
        return r.kind in self.kinds and (r.path.parent / "config.json").exists()

    def _dir(self, r):
        return str(r.path if r.kind == "tf-dir" else r.path.parent)

    def _try_local(self, r):
        d = self._dir(r)
        with self._lock:
            if d in self._cache:
                return self._cache[d]
        import transformers
        from transformers import AutoTokenizer
        try:
            tok = AutoTokenizer.from_pretrained(d, trust_remote_code=True)
        except Exception:
            tok = AutoTokenizer.from_pretrained(d, trust_remote_code=True,
                                                 use_fast=False)
        mod = None; last = None; errs = []
        for cls_name in arch_chain(r.arch):
            cls = getattr(transformers, cls_name, None)
            if cls is None:
                errs.append(cls_name + ": not in transformers")
                continue
            try:
                mod = cls.from_pretrained(d, trust_remote_code=True,
                                          device_map="auto")
                break
            except Exception as e:
                last = e
                errs.append(cls_name + ": " + str(e)[:120])
        if mod is None:
            raise RuntimeError("load failed. tried:\n  " + "\n  ".join(errs[-6:]))
        with self._lock:
            self._cache[d] = (tok, mod)
        return tok, mod

    def stream(self, r, prompt, hist, ctx):
        if r.arch in ARCH_HOOKS:
            for t in ARCH_HOOKS[r.arch](r, prompt, ctx):
                yield t
            return

        # 1. in-process first
        if not TransformersRT._broken:
            try:
                from transformers import TextIteratorStreamer
                tok, mod = self._try_local(r)
                st = TextIteratorStreamer(tok, skip_prompt=True,
                                          skip_special_tokens=True)
                try:
                    inp = tok(prompt, return_tensors="pt").to(mod.device)
                except Exception:
                    inp = tok(prompt, return_tensors="pt")
                kwargs = {"input_ids": inp.input_ids, "streamer": st,
                          "max_new_tokens": int(ctx["max_new_tokens"]),
                          "do_sample": float(ctx["temperature"]) > 0,
                          "temperature": max(0.01, float(ctx["temperature"])),
                          "top_p": float(ctx["top_p"]),
                          "top_k": int(ctx["top_k"]),
                          "repetition_penalty": float(ctx["repeat_penalty"])}
                if hasattr(inp, "attention_mask"):
                    kwargs["attention_mask"] = inp.attention_mask
                th = threading.Thread(target=mod.generate, kwargs=kwargs,
                                      daemon=True)
                th.start()
                for t in st:
                    yield t
                th.join(timeout=3600)
                return
            except Exception as e:
                msg = str(e)
                if ("tokenizers" in msg.lower() or "version" in msg.lower()
                        or "ImportError" in type(e).__name__):
                    TransformersRT._broken = True
                    print()
                    print(YL + "  transformers version mismatch" + RSTC)
                    print(DIM + "    switching to isolated venv" + RSTC)
                else:
                    yield ("[transformers: load failed]\n  " +
                           msg.replace("\n", "\n  "))
                    return

        # 2. venv fallback
        import queue as _queue
        payload = {
            "op": "chat",
            "model_dir": self._dir(r),
            "arch": normalize_arch(r.arch),
            "prompt": prompt,
            "max_new_tokens": int(ctx["max_new_tokens"]),
            "temperature": float(ctx["temperature"]),
            "top_p": float(ctx["top_p"]),
            "top_k": int(ctx["top_k"]),
            "repeat_penalty": float(ctx["repeat_penalty"]),
        }

        # We'll consume the worker in a thread and pull from a queue
        q = _queue.Queue()
        err_box = {"err": None}

        def runner():
            try:
                def emit(tok):
                    q.put(("tok", tok))
                _venv_run_json("transformers", payload, on_token=emit)
            except Exception as e:
                err_box["err"] = str(e)
            finally:
                q.put(("done", None))

        th = threading.Thread(target=runner, daemon=True)
        th.start()

        got_any = False
        while True:
            kind, val = q.get()
            if kind == "done":
                break
            if kind == "tok":
                got_any = True
                yield val

        if err_box["err"]:
            yield ("\n[transformers venv: " +
                   err_box["err"].replace("\n", "\n  ") + "]")
        elif not got_any:
            yield "[transformers venv: no tokens produced]"


class OllamaRT(BaseRuntime):
    id = "ollama"; kinds = ("gguf",)
    def available(self):
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1) as r:
                r.read(); return True, ""
        except Exception: return False, "ollama not running"
    def can_run(self, r): return r.source == "ollama"
    def stream(self, r, prompt, hist, ctx):
        body = json.dumps({"model": r.name.split(":")[0], "prompt": prompt, "stream": True,
                           "options": {"num_ctx": int(ctx["n_ctx"]),
                                       "temperature": float(ctx["temperature"]),
                                       "top_p": float(ctx["top_p"]),
                                       "top_k": int(ctx["top_k"]),
                                       "num_predict": int(ctx["max_new_tokens"])}}).encode()
        req = urllib.request.Request("http://127.0.0.1:11434/api/generate",
                                     data=body, headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            for raw in resp:
                try: d = json.loads(raw)
                except Exception: continue
                if d.get("response"): yield d["response"]
                if d.get("done"): break


class OpenAIRT(BaseRuntime):
    id = "openai-compat"; kinds = ("platform",)
    def __init__(self, name, cfg): self.pname, self.pcfg = name, cfg
    def available(self):
        if self.pcfg.get("key") or self.pcfg.get("no_key"): return True, ""
        return False, f"cs connect {self.pname}"
    def can_run(self, r): return r.kind == "platform" and r.name == self.pname
    def stream(self, r, prompt, hist, ctx):
        msgs = list(hist) if hist else [{"role":"user","content":prompt}]
        if ctx.get("system"): msgs = [{"role":"system","content":ctx["system"]}] + msgs
        body = json.dumps({"model": self.pcfg.get("model","gpt-4o-mini"),
                           "messages": msgs, "stream": True,
                           "temperature": float(ctx["temperature"]),
                           "max_tokens": int(ctx["max_new_tokens"])}).encode()
        headers = {"Content-Type":"application/json"}
        if self.pcfg.get("key"): headers["Authorization"] = "Bearer " + self.pcfg["key"]
        req = urllib.request.Request(self.pcfg["base_url"].rstrip("/") + "/chat/completions",
                                     data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"): continue
                d = line[5:].strip()
                if d == "[DONE]": break
                try:
                    c = json.loads(d)["choices"][0]["delta"].get("content")
                    if c: yield c
                except Exception: pass


# ─── prism fork helpers ────────────────────────────────────────────────────
def _prism_dirs():
    home = Path.home()
    dirs = [
        TOOLS_D / "llamacpp-prism",
        TOOLS_D / "llamacpp-prism-src/build/bin",
        TOOLS_D / "llamacpp-prism-src/build/bin/Release",
    ]
    old = home / ".cs/tools"
    if old.exists() and old != TOOLS_D:
        dirs += [
            old / "llamacpp-prism",
            old / "llamacpp-prism-src/build/bin",
            old / "llamacpp-prism-src/build/bin/Release",
        ]
    return dirs


def _prism_server():
    for d in _prism_dirs():
        for exe in ("llama-server.exe", "llama-server"):
            p = d / exe
            if p.exists():
                return str(p)
    return None


def _prism_cli():
    for d in _prism_dirs():
        for exe in ("llama-cli.exe", "llama-cli"):
            p = d / exe
            if p.exists():
                return str(p)
    return None

def needs_prism_fork(rec) -> bool:
    if getattr(rec, "kind", "") != "gguf": return False
    low = (getattr(rec, "name", "") or "").lower()
    if any(k in low for k in ("pq2", "ptq1", "ternary")): return True
    try:
        g = parse_gguf(rec.path, want_tensors=False)
        if not g: return False
        ft = g.get("meta", {}).get("general.file_type")
        if ft in (141, 142, 143): return True
        for k in g.get("meta", {}):
            if str(k).startswith("prism.hadamard"): return True
    except Exception: pass
    return False


def load_plugins():
    global _PLUGIN_RTS
    _PLUGIN_RTS = []
    if not PLUGINS_D.exists(): return _PLUGIN_RTS
    api = types.ModuleType("cs_api")
    api.BaseRuntime = BaseRuntime
    api.register = lambda cls: _PLUGIN_RTS.append(cls())
    api.register_arch = lambda name, fn: ARCH_HOOKS.__setitem__(name, fn)
    api.log = lambda s: print(MG + "[plugin]" + RSTC, s)
    api.normalize_arch = normalize_arch
    api.arch_alias_chain = arch_chain
    api.DATA_HOME = DATA_HOME
    sys.modules["cs_api"] = api
    for pf in sorted(PLUGINS_D.glob("*.py")):
        try:
            exec(compile(pf.read_text(encoding="utf-8"), str(pf), "exec"),
                 {"__name__": "csplug_" + pf.stem})
            print(GR + "  v plugin" + RSTC, pf.name)
        except Exception as e:
            print(RD + "  x plugin" + RSTC, pf.name, e)
            log(f"plugin {pf}: {e}", "error")
    return _PLUGIN_RTS

def all_runtimes():
    rts = list(load_plugins())
    prefer_py = os.environ.get("CS_PREFER_PY") == "1"
    order = ([LlamaCppPyRT(), LlamaServerRT(), LlamaCliRT()] if prefer_py else
             [LlamaServerRT(), LlamaCliRT(), LlamaCppPyRT()])
    rts += order
    rts += [TransformersRT(), OllamaRT()]
    for pn, pc in CFG.get("platforms", {}).items():
        rts.append(OpenAIRT(pn, pc))
    return rts

def pick_runtime(rec):
    # ternary models MUST use the PrismML fork
    try:
        if needs_prism_fork(rec):
            if _prism_server():
                _RUNTIME_PICK[rec.slug()] = "llama-server"
                return LlamaServerRT()
            if _prism_cli():
                _RUNTIME_PICK[rec.slug()] = "llama-cli"
                return LlamaCliRT()
    except Exception:
        pass

    cached_id = _RUNTIME_PICK.get(rec.slug())
    if cached_id:
        for rt in all_runtimes():
            try:
                ok, _ = rt.available()
            except Exception:
                ok = False
            if ok and rt.can_run(rec) and rt.id == cached_id:
                return rt
    for rt in all_runtimes():
        try:
            ok, _ = rt.available()
        except Exception:
            ok = False
        if ok and rt.can_run(rec):
            _RUNTIME_PICK[rec.slug()] = rt.id
            return rt
    return None
def _t_bash(a, cwd=None):
    rc, out = run_cmd(a.get("cmd",""), shell=True, timeout=600, cwd=cwd)
    return f"[exit {rc}]\n{out[:MAX_TOOL_OUTPUT]}"

def _t_read(a, cwd=None):
    p = Path(a.get("path",""))
    if cwd and not p.is_absolute(): p = Path(cwd)/p
    off = int(a.get("offset",0) or 0); lim = int(a.get("limit",200) or 200)
    try: text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e: return f"[read error: {e}]"
    lines = text.splitlines(); chunk = lines[off:off+lim]
    return f"{p} [{off}:{off+len(chunk)}/{len(lines)}]\n" + "\n".join(chunk)

def _t_write(a, cwd=None):
    p = Path(a.get("path",""))
    if cwd and not p.is_absolute(): p = Path(cwd)/p
    c = a.get("content","")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(c, encoding="utf-8"); return f"wrote {p} ({len(c)} chars)"
    except Exception as e: return f"[write error: {e}]"

def _t_append(a, cwd=None):
    p = Path(a.get("path",""))
    if cwd and not p.is_absolute(): p = Path(cwd)/p
    c = a.get("content","")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh: fh.write(c)
        return f"appended {len(c)} chars"
    except Exception as e: return f"[append error: {e}]"

def _t_ls(a, cwd=None):
    p = Path(a.get("path","."))
    if cwd and not p.is_absolute(): p = Path(cwd)/p
    try:
        entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name))
        return "\n".join(f"{'d' if e.is_dir() else 'f'} {e.name}" for e in entries[:500])
    except Exception as e: return f"[ls error: {e}]"

def _t_glob(a, cwd=None):
    pat = a.get("pattern","*"); root = Path(a.get("root","."))
    if cwd and not root.is_absolute(): root = Path(cwd)/root
    try:
        hits = sorted(str(x.relative_to(root)) for x in root.glob(pat))
        return "\n".join(hits[:500]) or "(no matches)"
    except Exception as e: return f"[glob error: {e}]"

def _t_grep(a, cwd=None):
    pat = a.get("pattern",""); root = Path(a.get("root","."))
    if cwd and not root.is_absolute(): root = Path(cwd)/root
    g = a.get("glob","**/*")
    try: rx = re.compile(pat)
    except re.error as e: return f"[regex error: {e}]"
    out = []
    for f in root.glob(g):
        if not f.is_file(): continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    out.append(f"{f}:{i}: {line[:200]}")
                    if len(out) >= 300: return "\n".join(out)
        except Exception: continue
    return "\n".join(out) or "(no matches)"

def _t_webfetch(a, cwd=None):
    try: return fetch_text(a.get("url",""))[:MAX_TOOL_OUTPUT]
    except Exception as e: return f"[fetch error: {e}]"


def _t_python(a, cwd=None):
    code = a.get("code") or a.get("src") or ""
    if not code:
        return "[python: missing code]"
    try:
        r = subprocess.run([sys.executable, "-c", code],
                           capture_output=True, text=True, timeout=60,
                           cwd=cwd, errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        return "[exit " + str(r.returncode) + "]\n" + out[:MAX_TOOL_OUTPUT]
    except Exception as e:
        return "[python error: " + str(e) + "]"


def _t_http(a, cwd=None):
    url = a.get("url") or ""
    if not url:
        return "[http: missing url]"
    try:
        return fetch_text(url, timeout=30)[:MAX_TOOL_OUTPUT]
    except Exception as e:
        return "[http error: " + str(e) + "]"


def _t_download(a, cwd=None):
    url = a.get("url") or ""
    dest = a.get("path") or a.get("dest") or ""
    if not url or not dest:
        return "[download: url and path required]"
    p = Path(dest)
    if cwd and not p.is_absolute():
        p = Path(cwd) / p
    try:
        download_file(url, p)
        return "saved " + str(p) + " (" + human(p.stat().st_size) + ")"
    except Exception as e:
        return "[download error: " + str(e) + "]"


def _t_extract(a, cwd=None):
    src = a.get("path") or a.get("src") or ""
    dest = a.get("dest") or ""
    if not src:
        return "[extract: missing path]"
    p = Path(src)
    if cwd and not p.is_absolute():
        p = Path(cwd) / p
    if not p.exists():
        return "[extract: not found: " + str(p) + "]"
    d = Path(dest) if dest else p.with_suffix("")
    if cwd and not d.is_absolute():
        d = Path(cwd) / d
    try:
        d.mkdir(parents=True, exist_ok=True)
        if p.suffix.lower() == ".zip" or ".zip" in p.name.lower():
            with zipfile.ZipFile(p) as z:
                z.extractall(d)
        elif ".tar" in p.name.lower() or p.suffix.lower() in (".tar", ".gz", ".tgz", ".bz2", ".xz"):
            with tarfile.open(p) as tt:
                tt.extractall(d)
        else:
            return "[extract: unknown archive type: " + p.name + "]"
        return "extracted " + str(p) + " -> " + str(d)
    except Exception as e:
        return "[extract error: " + str(e) + "]"


def _t_tree(a, cwd=None):
    root = Path(a.get("path", "."))
    if cwd and not root.is_absolute():
        root = Path(cwd) / root
    depth = int(a.get("depth", 3) or 3)
    if not root.exists():
        return "[tree: not found: " + str(root) + "]"
    lines = [str(root)]
    def walk(d, prefix, level):
        if level > depth:
            return
        try:
            entries = sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name))
        except Exception:
            return
        for i, e in enumerate(entries[:200]):
            last = (i == len(entries[:200]) - 1)
            mark = "`-- " if last else "|-- "
            lines.append(prefix + mark + e.name + ("/" if e.is_dir() else ""))
            if e.is_dir():
                walk(e, prefix + ("    " if last else "|   "), level + 1)
    walk(root, "", 1)
    return "\n".join(lines[:500])


def _t_diff(a, cwd=None):
    p1 = a.get("a") or a.get("left") or ""
    p2 = a.get("b") or a.get("right") or ""
    if not p1 or not p2:
        return "[diff: a and b required]"
    f1 = Path(p1); f2 = Path(p2)
    if cwd:
        if not f1.is_absolute(): f1 = Path(cwd) / f1
        if not f2.is_absolute(): f2 = Path(cwd) / f2
    try:
        import difflib
        t1 = f1.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        t2 = f2.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        d = difflib.unified_diff(t1, t2, fromfile=str(f1), tofile=str(f2))
        return "".join(d)[:MAX_TOOL_OUTPUT] or "(identical)"
    except Exception as e:
        return "[diff error: " + str(e) + "]"


def _t_find(a, cwd=None):
    root = Path(a.get("root", "."))
    if cwd and not root.is_absolute():
        root = Path(cwd) / root
    pat = a.get("name") or a.get("pattern") or "*"
    try:
        hits = [str(x.relative_to(root)) for x in root.rglob(pat)]
        return "\n".join(hits[:500]) or "(no matches)"
    except Exception as e:
        return "[find error: " + str(e) + "]"


def _t_wc(a, cwd=None):
    p = Path(a.get("path", ""))
    if cwd and not p.is_absolute():
        p = Path(cwd) / p
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
        lines = txt.count("\n") + (0 if txt.endswith("\n") else 1)
        words = len(txt.split())
        return str(lines) + " lines, " + str(words) + " words, " + str(len(txt)) + " chars"
    except Exception as e:
        return "[wc error: " + str(e) + "]"


def _t_notify(a, cwd=None):
    title = a.get("title", "CS")
    msg = a.get("msg") or a.get("message") or ""
    try:
        if os.name == "nt":
            ps = ('[reflection.assembly]::loadwithpartialname("System.Windows.Forms") | Out-Null; '
                  '$n = New-Object System.Windows.Forms.NotifyIcon; '
                  '$n.Icon = [System.Drawing.SystemIcons]::Information; '
                  '$n.Visible = $true; '
                  '$n.ShowBalloonTip(5000, "' + title.replace(chr(34), chr(39)) + '", "'
                  + msg.replace(chr(34), chr(39)) + '", [System.Windows.Forms.ToolTipIcon]::Info)')
            subprocess.Popen(["powershell", "-NoProfile", "-Command", ps])
        elif sys.platform == "darwin":
            subprocess.Popen(["osascript", "-e",
                              'display notification "' + msg.replace(chr(34), chr(39)) +
                              '" with title "' + title.replace(chr(34), chr(39)) + '"'])
        else:
            subprocess.Popen(["notify-send", title, msg])
        return "notified"
    except Exception as e:
        return "[notify error: " + str(e) + "]"


def _t_clip_read(a, cwd=None):
    try:
        if os.name == "nt":
            r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                               capture_output=True, text=True, timeout=10)
            return (r.stdout or "")[:MAX_TOOL_OUTPUT]
        elif sys.platform == "darwin":
            r = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=10)
            return (r.stdout or "")[:MAX_TOOL_OUTPUT]
        else:
            r = subprocess.run(["xclip", "-selection", "clipboard", "-o"],
                               capture_output=True, text=True, timeout=10)
            return (r.stdout or "")[:MAX_TOOL_OUTPUT]
    except Exception as e:
        return "[clip_read error: " + str(e) + "]"


def _t_clip_write(a, cwd=None):
    text = a.get("text", "")
    try:
        if os.name == "nt":
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            "$input | Set-Clipboard"],
                           input=text, capture_output=True, text=True, timeout=10)
        elif sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text, text=True, timeout=10)
        else:
            subprocess.run(["xclip", "-selection", "clipboard"],
                           input=text, text=True, timeout=10)
        return "clipboard updated (" + str(len(text)) + " chars)"
    except Exception as e:
        return "[clip_write error: " + str(e) + "]"


TOOLS_IMPL = {"bash":_t_bash,"read":_t_read,"write":_t_write,"append":_t_append,
              "ls":_t_ls,"glob":_t_glob,"grep":_t_grep,"web_fetch":_t_webfetch}

_TOOL_RX = re.compile(r"<tool>\s*(\{.*?\})\s*</tool>", re.S)

def run_tool_blocks(text, cwd=None):
    calls = _TOOL_RX.findall(text)
    results = []
    auto = CFG.get("prefs", {}).get("auto_approve", True)
    for raw in calls:
        try:
            obj = json.loads(raw)
            name = obj.get("name", "")
            args = obj.get("args", {}) or {}
        except Exception as e:
            results.append("[parse error: " + str(e) + "]")
            continue
        fn = TOOLS_IMPL.get(name)
        if not fn:
            results.append("[unknown tool: " + name + "]")
            continue
        if not auto:
            preview = json.dumps(args)[:80]
            if not ask_yn("  run " + name + " " + preview + "?", default=True):
                results.append("[skipped by user]")
                continue
        try:
            results.append(fn(args, cwd=cwd))
        except Exception as e:
            results.append("[tool error: " + str(e) + "]")
    return results, bool(calls)


def build_prompt(hist, ctx):
    parts = []
    if ctx.get("system"): parts.append(f"system: {ctx['system']}")
    for m in hist: parts.append(f"{m.get('role','user')}: {m.get('content','')}")
    parts.append("assistant:")
    return "\n".join(parts)

def build_messages(hist, ctx):
    msgs = []
    if ctx.get("system"): msgs.append({"role":"system","content":ctx["system"]})
    msgs.extend(hist); return msgs

# ─── sessions ──────────────────────────────────────────────────────────────
def stream_session(rec, rt, hist, ctx, silent=False, indent=""):
    if not silent: print(grad(0.7) + f"  ──[{rt.id}]──" + RSTC, flush=True)
    prompt = build_prompt(hist, ctx)
    t0 = time.time(); chars = 0; buf = []; err = None
    try:
        for chunk in rt.stream(rec, prompt, hist, ctx):
            if isinstance(chunk, str) and (
                chunk.startswith("[llama.cpp-py failed]") or
                chunk.startswith("[stream error") or
                chunk.startswith("[no tokens")
            ): err = chunk
            sys.stdout.write(chunk); sys.stdout.flush()
            chars += len(chunk); buf.append(chunk)
    except KeyboardInterrupt:
        print(YL + "\n  ⌁ interrupted" + RSTC)
    except Exception as e:
        print(RD + f"\n  x runtime error: {e}" + RSTC); log(f"stream: {e}", "error")
    dt = max(time.time() - t0, 1e-6); out = "".join(buf)
    if not silent:
        print(f"\n{DIM}  ⌁ ~{chars/4/dt:.1f} tok/s · {dt:.1f}s · {rt.id}{RSTC}")
    if err: _RUNTIME_PICK.pop(rec.slug(), None)
    return out

def append_history(rec, role, content, incognito=False):
    if incognito: return
    try:
        fp = CHATS_D / (rec.slug() + ".jsonl")
        with open(fp, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"role":role,"content":content,"ts":time.time()}) + "\n")
    except Exception: pass

def load_history(rec, limit=20):
    fp = CHATS_D / (rec.slug() + ".jsonl")
    if not fp.exists(): return []
    try:
        lines = fp.read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(l) for l in lines]
    except Exception: return []

# ─── chat / code loops ─────────────────────────────────────────────────────
def chat_loop(rec, rt, ctx, incognito=False):
    hist = []
    tag = " [incognito]" if incognito else ""
    print(MG + f"  chat{tag}: {rec.name} via {rt.id}" + RSTC)
    print(DIM + "  /help · Ctrl-C to exit" + RSTC)
    while True:
        try: line = input(CY + "  you › " + RSTC)
        except (EOFError, KeyboardInterrupt): print(); break
        s = line.strip()
        if s in ("/exit","/quit"): break
        if s in ("/help", "/"):
            _hex_list_commands()
            continue
        if s.startswith("/") and s.split()[0] not in _HEX_COMMANDS:
            _hex_list_commands(prefix=s.split()[0])
            continue
        if s == "/context":
            print()
            print("  " + col(51) + "context" + RSTC)
            for k in sorted(ctx):
                print("    " + DIM + k.ljust(18) + RSTC + trunc(str(ctx[k]), 60))
            print()
            continue
        if s.startswith("/model"):
            arg = s.split(maxsplit=1)[1] if len(s.split()) > 1 else ""
            new_rec = match_model(arg) or rec
            new_rt = pick_runtime(new_rec) or rt
            rec, rt = new_rec, new_rt; ctx = get_context(rec)
            print(DIM + f"  → {rec.name} via {rt.id}" + RSTC); continue
        if not s: continue
        hist.append({"role":"user","content":s})
        append_history(rec, "user", s, incognito)
        out = stream_session(rec, rt, hist, ctx)
        hist.append({"role":"assistant","content":out})
        append_history(rec, "assistant", out, incognito)
        if len(hist) > MAX_HISTORY*2: hist = hist[-MAX_HISTORY*2:]


def code_loop(rec, rt, ctx, cwd=None):
    cwd = cwd or os.getcwd()
    print(MG + f"  code mode: {rec.name} via {rt.id}" + RSTC)
    print(DIM + f"  cwd: {cwd}" + RSTC)
    print(DIM + "  tools: bash, read, write, append, ls, glob, grep, web_fetch" + RSTC)
    ctx_code = dict(ctx)
    ctx_code["system"] = ((ctx.get("system") or "") + "\n\n" + TOOLS_HEADER).strip()
    hist = []
    while True:
        try: line = input(CY + "  task › " + RSTC)
        except (EOFError, KeyboardInterrupt): print(); break
        s = line.strip()
        if s in ("/exit","/quit"): break
        if s == "/ctx":
            ctx = edit_context(rec); ctx_code = dict(ctx)
            ctx_code["system"] = ((ctx.get("system") or "") + "\n\n" + TOOLS_HEADER).strip()
            continue
        if s == "/runtime": list_runtimes(); continue
        if s.startswith("/run "):
            _, out = run_cmd(s[5:], shell=True, cwd=cwd); print(out); continue
        if not s: continue
        hist.append({"role":"user","content":s})
        for _ in range(MAX_TOOL_ROUNDS):
            out = stream_session(rec, rt, hist, ctx_code)
            hist.append({"role":"assistant","content":out})
            results, had = run_tool_blocks(out, cwd=cwd)
            if not had: break
            for r in results:
                print(DIM + "  ── tool result ──" + RSTC)
                print(textwrap.indent(r[:4000], "    "))
                hist.append({"role":"user","content":f"<tool_result>\n{r[:MAX_TOOL_OUTPUT]}\n</tool_result>"})
        if len(hist) > MAX_HISTORY*2: hist = hist[-MAX_HISTORY*2:]

# ─── coding agents ─────────────────────────────────────────────────────────
@dataclass
class Agent:
    id: str
    name: str
    kind: str          # "cli", "vscode", "desktop"
    install_cmds: list
    check_bin: str
    launch_cmd: list
    env: dict = field(default_factory=dict)
    config_path: Optional[Path] = None
    config_content: Optional[Callable] = None

def _mk_agents():
    home = Path.home()
    return {
        "claude-code": Agent(
            id="claude-code", name="Claude Code (Anthropic)", kind="cli",
            install_cmds=[["npm","install","-g","@anthropic-ai/claude-code"]],
            check_bin="claude",
            launch_cmd=["claude"],
            env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:{port}/v1",
                 "ANTHROPIC_API_KEY": "cs-local"},
        ),
        "chatgpt-desktop": Agent(
            id="chatgpt-desktop", name="ChatGPT Desktop (Codex mode)", kind="cli",
            install_cmds=[["npm","install","-g","@openai/codex"]],
            check_bin="codex",
            launch_cmd=["codex"],
            env={"OPENAI_BASE_URL": "http://127.0.0.1:{port}/v1",
                 "OPENAI_API_KEY": "cs-local"},
        ),
        "opencode": Agent(
            id="opencode", name="OpenCode", kind="cli",
            install_cmds=[["npm","install","-g","opencode-ai"]],
            check_bin="opencode",
            launch_cmd=["opencode"],
            env={"OPENAI_BASE_URL": "http://127.0.0.1:{port}/v1",
                 "OPENAI_API_KEY": "cs-local"},
        ),
        "aider": Agent(
            id="aider", name="Aider", kind="cli",
            install_cmds=[["{python}","-m","pip","install","aider-chat"]],
            check_bin="aider",
            launch_cmd=["aider","--openai-api-base","http://127.0.0.1:{port}/v1",
                        "--openai-api-key","cs-local","--model","openai/{model}"],
            env={},
        ),
        "goose": Agent(
            id="goose", name="Goose (Block)", kind="cli",
            install_cmds=[["curl","-fsSL","https://github.com/block/goose/releases/download/stable/download_cli.sh"]],
            check_bin="goose",
            launch_cmd=["goose"],
            env={"OPENAI_HOST": "http://127.0.0.1:{port}",
                 "OPENAI_API_KEY": "cs-local"},
        ),
        "open-interpreter": Agent(
            id="open-interpreter", name="Open Interpreter", kind="cli",
            install_cmds=[["{python}","-m","pip","install","open-interpreter"]],
            check_bin="interpreter",
            launch_cmd=["interpreter","--api_base","http://127.0.0.1:{port}/v1",
                        "--api_key","cs-local","--model","openai/{model}"],
        ),
        "crush": Agent(
            id="crush", name="Crush (Charm)", kind="cli",
            install_cmds=[["go","install","github.com/charmbracelet/crush@latest"]],
            check_bin="crush",
            launch_cmd=["crush"],
            env={"OPENAI_BASE_URL": "http://127.0.0.1:{port}/v1",
                 "OPENAI_API_KEY": "cs-local"},
        ),
    }

AGENTS = _mk_agents()


def cmd_agents(action="list", agent_id=None, model=None):
    if action == "list":
        rows = []
        for aid, a in AGENTS.items():
            inst = "v" if agent_installed(a) else "·"
            rows.append([inst, aid, a.name, a.kind])
        print(YL + "  CODING AGENTS" + RSTC)
        print(table(rows, ["OK","ID","NAME","KIND"]))
        print(DIM + "  cs agents install <id>    install an agent" + RSTC)
        print(DIM + "  cs agents launch  <id>    start server + agent" + RSTC)
        return

    if action == "install":
        a = AGENTS.get(agent_id)
        if not a: print(RD + f"  unknown agent: {agent_id}" + RSTC); return
        if agent_installed(a):
            print(GR + f"  v {a.name} already installed" + RSTC); return
        print(CY + f"▸ installing {a.name}" + RSTC)
        for cmd in a.install_cmds:
            cmd = [c.replace("{python}", sys.executable) for c in cmd]
            rc = subprocess.call(cmd)
            if rc != 0:
                print(RD + f"  x install failed (rc={rc})" + RSTC); return
        print(GR + f"  v {a.name} installed" + RSTC)
        return


    if action == "launch":
        a = AGENTS.get(agent_id)
        if not a:
            print(RD + "  unknown agent: " + str(agent_id) + RSTC)
            return

        # desktop-app agents have their own path
        if a.id == "chatgpt-desktop":
            cmd_chatgpt(model)
            return

        if not agent_installed(a):
            print(YL + "  " + a.name + " not installed" + RSTC)
            print(DIM + "    press i to install, or: cs locate " + agent_id + RSTC)
            return

        rec = match_model(model) if model else None
        if not rec:
            recs = load_scan()
            if not recs:
                print(RD + "  no models" + RSTC); return
            rec = recs[0]
        rt = pick_runtime(rec)
        if not rt:
            print(RD + "  no runtime for " + rec.name + RSTC); return
        try:
            if not rt.can_run(rec):
                print(RD + "  runtime " + rt.id + " cannot run " + rec.name + RSTC)
                return
        except Exception:
            pass

        _SERVE["rec"] = rec
        port = 8686
        try:
            _ensure_srv(port, rec.name)
        except Exception as e:
            print(RD + "  ! could not start server: " + str(e) + RSTC)
            return

        exe = _resolve_bin(a.check_bin)
        if not exe:
            print(RD + "  ! could not resolve " + a.check_bin + RSTC)
            print(DIM + "    run: cs locate " + agent_id + RSTC)
            return

        env = os.environ.copy()
        for k, v in a.env.items():
            env[k] = v.replace("{port}", str(port)).replace("{model}", rec.name)

        args = [c.replace("{python}", sys.executable) for c in a.launch_cmd]
        args = [c.replace("{port}", str(port)).replace("{model}", rec.name)
                for c in args]
        args[0] = exe

        print(GR + "  launching " + a.name + " against " + rec.name +
              " at 127.0.0.1:" + str(port) + RSTC)
        print(DIM + "  (close the app when done)" + RSTC)

        suffix = pathlib.Path(exe).suffix.lower()
        try:
            if os.name == "nt" and suffix in (".cmd", ".bat"):
                subprocess.call(["cmd", "/c"] + args, env=env)
            elif os.name == "nt" and suffix == ".ps1":
                subprocess.call(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-File"]
                    + args, env=env)
            else:
                subprocess.call(args, env=env)
        except FileNotFoundError as e:
            print(RD + "  ! exec failed: " + str(e) + RSTC)
            print(DIM + "    resolved to: " + exe + RSTC)
            print(DIM + "    run: cs locate " + agent_id + RSTC)
        except KeyboardInterrupt:
            print(YL + "\n  stopped" + RSTC)
        return


def install_target(t):
    print(CY + "▸ install " + RSTC + t)
    if t in PIP_TARGETS:
        rc = subprocess.call([sys.executable,"-m","pip","install","--upgrade",*PIP_TARGETS[t]])
        print((GR if rc == 0 else RD) + f"  {'v' if rc == 0 else 'x'} pip {t}" + RSTC); return
    if t == "all":
        for k in ("llama-cpp","transformers","torch","sentencepiece","einops","tiktoken","hub"):
            try: install_target(k)
            except Exception as e: print(RD + f"  x {k}: {e}" + RSTC)
        return
    if t in ("llamacpp-bin","llama.cpp"):
        install_llamacpp_binaries(); return
    if t == "prism-fork":
        install_prism_fork(); return
    if t == "ollama":
        install_ollama(); return
    if t in PLATFORM_DEFS:
        d = dict(PLATFORM_DEFS[t])
        if not d.get("no_key"):
            d["key"] = getpass.getpass(f"  API key for {t} (hidden, Enter to skip): ") or ""
        CFG.setdefault("platforms", {})[t] = d; save_cfg()
        print(GR + f"  v platform {t} connected" + RSTC); return
    print(RD + "  unknown target: " + t + RSTC)
    print(DIM + "  targets: " + ", ".join(sorted(list(PIP_TARGETS) + ["all","llamacpp-bin","prism-fork","ollama"] + list(PLATFORM_DEFS))) + RSTC)


def install_llamacpp_binaries():
    print(CY + "▸ fetching llama.cpp release" + RSTC)
    try:
        rel = fetch_json("https://api.github.com/repos/ggml-org/llama.cpp/releases/latest", timeout=30)
    except Exception as e:
        print(RD + f"  x {e}" + RSTC); return
    machine = platform.machine().lower()
    if os.name == "nt": prefer = ["win-avx2-x64","win-x64","win-cpu-x64"]
    elif sys.platform == "darwin": prefer = ["macos-arm64"] if machine == "arm64" else ["macos-x64"]
    else: prefer = ["ubuntu-x64","linux-x64"]
    chosen = None
    for tag in prefer:
        for a in rel.get("assets", []):
            n = a.get("name","").lower()
            if tag in n and (n.endswith(".zip") or n.endswith(".tar.gz")):
                chosen = a; break
        if chosen: break
    if not chosen: print(RD + "  x no matching asset" + RSTC); return
    print(CY + f"▸ downloading {chosen['name']}" + RSTC)
    tmp = TOOLS_D / chosen["name"]
    try: download_file(chosen["browser_download_url"], tmp)
    except Exception as e: print(RD + f"  x {e}" + RSTC); return
    dest = TOOLS_D / "llamacpp"; dest.mkdir(parents=True, exist_ok=True)
    try:
        if tmp.suffix == ".zip":
            with zipfile.ZipFile(tmp) as z: z.extractall(dest)
        else:
            with tarfile.open(tmp) as t: t.extractall(dest)
        tmp.unlink(missing_ok=True)
    except Exception as e: print(RD + f"  x extract: {e}" + RSTC); return
    if os.name != "nt":
        for f in list(dest.rglob("llama-*")) + list(dest.rglob("*.dylib")):
            try: os.chmod(f, 0o755)
            except Exception: pass
    print(GR + f"  v binaries in {dest}" + RSTC)


def install_prism_fork():
    """Download prebuilt PrismML fork (ternary kernels for Bonsai 2)."""
    tag = "prism-b10660-e311ed3"
    base = f"https://github.com/PrismML-Eng/llama.cpp/releases/download/{tag}"
    has_cuda = bool(shutil.which("nvidia-smi"))
    ctag = "12.4"
    if has_cuda:
        rc, out = run_cmd(["nvidia-smi"], timeout=10)
        m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out)
        if m:
            maj, minr = int(m.group(1)), int(m.group(2))
            if maj > 13 or (maj == 13 and minr >= 3): ctag = "13.3"
            elif maj == 13 or (maj == 12 and minr >= 8): ctag = "12.8"
    machine = platform.machine().lower()
    if os.name == "nt":
        asset = f"llama-{tag}-bin-win-cuda-{ctag}-x64.zip" if has_cuda else f"llama-{tag}-bin-win-cpu-x64.zip"
    elif sys.platform == "darwin":
        asset = f"llama-{tag}-bin-macos-arm64.zip" if machine == "arm64" else f"llama-{tag}-bin-macos-x64.zip"
    else:
        asset = f"llama-{tag}-bin-ubuntu-x64.zip"
    url = f"{base}/{asset}"
    print(CY + f"▸ downloading {asset}" + RSTC)
    dest_dir = TOOLS_D / "llamacpp-prism"; dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = TOOLS_D / asset
    try: download_file(url, tmp)
    except Exception as e:
        print(RD + f"  x {e}" + RSTC)
        print(DIM + f"  manual: {url}" + RSTC); return
    try:
        with zipfile.ZipFile(tmp) as z: z.extractall(dest_dir)
        tmp.unlink(missing_ok=True)
    except Exception as e: print(RD + f"  x extract: {e}" + RSTC); return
    if os.name != "nt":
        for f in list(dest_dir.rglob("llama-*")) + list(dest_dir.rglob("*.dylib")):
            try: os.chmod(f, 0o755)
            except Exception: pass
    print(GR + f"  v PrismML fork in {dest_dir}" + RSTC)


def install_ollama():
    if shutil.which("ollama"):
        print(GR + "  v ollama already installed" + RSTC); return
    if os.name == "nt":
        print(YL + "  download: https://ollama.com/download/windows" + RSTC); return
    if sys.platform == "darwin":
        rc = subprocess.call(["brew","install","ollama"])
        print((GR if rc == 0 else RD) + f"  {'v' if rc == 0 else 'x'} brew ollama" + RSTC); return
    if ask_yn("  run official ollama install script?"):
        subprocess.call("curl -fsSL https://ollama.com/install.sh | sh", shell=True)


def install_self():
    """Install the `cs` global command pointing at this cs.py."""
    script = Path(__file__).resolve()
    py = sys.executable
    if os.name == "nt":
        BIN_D.mkdir(parents=True, exist_ok=True)
        (BIN_D / "cs.cmd").write_text(f'@echo off\r\n"{py}" "{script}" %*\r\n', encoding="utf-8")
        (BIN_D / "cs.ps1").write_text(f'& "{py}" "{script}" @args\r\n', encoding="utf-8")
        print(GR + f"  v {BIN_D / 'cs.cmd'}" + RSTC)
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                                 winreg.KEY_READ | winreg.KEY_WRITE)
            try: cur, _ = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError: cur = ""
            parts = [p for p in cur.split(";") if p]
            if str(BIN_D) not in parts:
                parts.append(str(BIN_D))
                winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, ";".join(parts))
                print(GR + f"  v added {BIN_D} to user PATH" + RSTC)
            else:
                print(DIM + f"  = {BIN_D} already on PATH" + RSTC)
            winreg.CloseKey(key)
        except Exception as e:
            print(YL + f"  ! could not update PATH: {e}" + RSTC)
            print(DIM + f"    add manually: {BIN_D}" + RSTC)
        print(DIM + "  open a new terminal for `cs` to appear." + RSTC)
        return
    BIN_D.mkdir(parents=True, exist_ok=True)
    launcher = BIN_D / "cs"
    launcher.write_text(f'#!/usr/bin/env bash\nexec "{py}" "{script}" "$@"\n', encoding="utf-8")
    try: os.chmod(launcher, 0o755)
    except Exception: pass
    print(GR + f"  v {launcher}" + RSTC)
    if str(BIN_D) in os.environ.get("PATH","").split(os.pathsep):
        print(DIM + f"  = {BIN_D} already on PATH" + RSTC); return
    rc_file = None
    for name, path in (("zsh", Path.home()/".zshrc"),
                       ("bash", Path.home()/".bashrc"),
                       ("bash_profile", Path.home()/".bash_profile")):
        if name in os.environ.get("SHELL","") and path.exists():
            rc_file = path; break
    if not rc_file and (Path.home()/".profile").exists():
        rc_file = Path.home()/".profile"
    if rc_file:
        try:
            txt = rc_file.read_text(encoding="utf-8")
            if str(BIN_D) not in txt:
                with open(rc_file, "a", encoding="utf-8") as fh:
                    fh.write(f'\n# CS Framework\nexport PATH="{BIN_D}:$PATH"\n')
                print(GR + f"  v appended PATH export to {rc_file}" + RSTC)
        except Exception: pass
    print(DIM + f"  add {BIN_D} to PATH if `cs` is not found" + RSTC)

# ─── setup wizard ──────────────────────────────────────────────────────────
def setup(full=False, quiet=False):
    if not quiet: show_logo("first-time setup")
    print(YL + "┌─ SETUP — hardware" + RSTC)
    info = probe()
    for k, v in info.items():
        time.sleep(0.04); print(GR + "  [ OK ]" + RSTC, f"{k:8}", v)
    log(f"setup probe: {info}")
    print()
    print(CY + "▸ data location: " + RSTC + str(DATA_HOME))
    print(DIM + "  (copy this folder with cs.py to move everything)" + RSTC)
    print()
    want = full or ask_yn("  install recommended runtimes?", default=True)
    if want:
        targets = (["all","llamacpp-bin","prism-fork"] if full
                   else ["llama-cpp","llamacpp-bin","transformers","sentencepiece","hub"])
        for t in targets:
            try: install_target(t)
            except Exception as e: print(RD + f"  x {t}: {e}" + RSTC)
    print()
    print(CY + "▸ initial model scan" + RSTC)
    with Spinner("scanning"):
        recs = scan_models()
    print(GR + f"  v {len(recs)} artifact(s) indexed" + RSTC)
    print()
    print(CY + "▸ global command" + RSTC)
    if ask_yn("  install `cs` command?", default=True):
        install_self()
    CFG["setup_done"] = True; CFG["first_run_ts"] = time.time(); save_cfg()
    print()
    print(MG + "  setup complete — run `cs` to launch the chooser" + RSTC)

# ─── chooser ───────────────────────────────────────────────────────────────
def _model_line(i, r, vc):
    st = vc.get(str(r.path), {})
    mark = GR + "v" + RSTC if st.get("ok") else (RD + "x" + RSTC if st else DIM + "·" + RSTC)
    rt = pick_runtime(r)
    tag = f"{DIM}{rt.id}{RSTC}" if rt else f"{RD}no-runtime{RSTC}"
    return (f"  {grad(min(1, i/15))}◆{RSTC} [{i:2}] {mark} "
            f"{trunc(r.name, 44):44} {r.kind:9} "
            f"{trunc(arch_disp(r.arch), 22):22} {human(r.size):>8}  {tag}")

def _old_chooser():
    """Simple picker. Number -> chat. No mode menu."""
    recs = load_scan()
    if not recs:
        print(YL + "  no models found" + RSTC)
        print(DIM + "  cs pull <name>   download from HuggingFace" + RSTC)
        print(DIM + "  cs setup         full setup wizard" + RSTC)
        print(DIM + "  cs scan          rescan local folders" + RSTC)
        return
    if len(recs) == 1:
        rec = recs[0]
    else:
        show_logo("pick a model")
        for i, r in enumerate(recs[:30]):
            rt = pick_runtime(r)
            tag = (DIM + rt.id + RSTC) if rt else (RD + "no runtime" + RSTC)
            print("  [%2d] %-44s %9s  %s" % (i, trunc(r.name, 44),
                                              human(r.size), tag))
        print()
        print(DIM + "  enter a number, or 'q' to quit" + RSTC)
        sel = ask(CY + "  > " + RSTC).strip().lower()
        if sel in ("q", ""):
            return
        try:
            rec = recs[int(sel)]
        except Exception:
            return
    rt = pick_runtime(rec)
    if not rt:
        print(RD + "  no runtime for " + rec.name + RSTC); return
    chat_loop(rec, rt, get_context(rec))




def chooser():
    return menu_main()

def _serve_bg(port):
    srv = _QuietHTTPServer(("127.0.0.1", port), _ServeHandler)
    try: srv.serve_forever()
    except Exception: pass
    finally: srv.server_close()


class _QuietHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that logs nothing and reuses the port."""
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        try:
            import sys as _sys
            exc = _sys.exc_info()[1]
            if isinstance(exc, (ConnectionResetError, BrokenPipeError,
                                ConnectionAbortedError, TimeoutError)):
                return
            if exc is not None:
                try:
                    log(f"serve error {client_address}: {exc}", "warn")
                except Exception:
                    pass
        except Exception:
            pass


# --- agent connectors (chatgpt / claude / opencode) ---
_AGENT_SRV = {"proc": None, "port": 0, "model": None}


def _backup_file(p):
    try:
        if p.exists():
            return True, p.read_bytes()
    except Exception:
        pass
    return False, None


def _restore_file(p, existed, data):
    try:
        if existed and data is not None:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            print(GR + "  ^ restored " + str(p) + RSTC)
        elif p.exists():
            p.unlink()
            print(GR + "  ^ removed " + str(p) + RSTC)
    except Exception as e:
        print(RD + "  ! restore failed " + str(p) + ": " + str(e) + RSTC)


def _wait_process_exit(name, timeout=43200.0):
    time.sleep(3)
    deadline = time.time() + timeout
    is_win = os.name == "nt"
    query = name
    if is_win and not query.lower().endswith(".exe"):
        query = query + ".exe"
    while time.time() < deadline:
        try:
            if is_win:
                r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + query, "/NH"],
                                   capture_output=True, text=True, timeout=10)
                if query.lower() not in (r.stdout or "").lower():
                    return True
            else:
                r = subprocess.run(["pgrep", "-x", name],
                                   capture_output=True, text=True, timeout=10)
                if r.returncode != 0:
                    return True
        except Exception:
            pass
        time.sleep(2.0)
    return False


def _wire_chatgpt(model, port):
    d = pathlib.Path.home() / ".codex"
    d.mkdir(parents=True, exist_ok=True)
    cfg = d / "config.toml"
    existed, original = _backup_file(cfg)
    cfg.write_text(
        "# CS Framework -> ChatGPT / Codex\n"
        "model_provider = \"cs-framework\"\n"
        "model = \"%s\"\n\n"
        "[model_providers.cs-framework]\n"
        "name = \"CS Framework\"\n"
        "base_url = \"http://127.0.0.1:%d/v1\"\n"
        "wire_api = \"chat\"\n"
        "env_key = \"CS_API_KEY\"\n" % (model, port),
        encoding="utf-8")
    os.environ["CS_API_KEY"] = "cs-local"
    if os.name == "nt":
        subprocess.call(["setx", "CS_API_KEY", "cs-local"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return cfg, existed, original

def _wire_claude(model, port):
    d = pathlib.Path.home() / ".claude"
    d.mkdir(parents=True, exist_ok=True)
    sp = d / "settings.json"
    existed, original = _backup_file(sp)
    ex = {}
    if sp.exists():
        try:
            ex = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            ex = {}
    env = ex.setdefault("env", {})
    base = "http://127.0.0.1:%d" % port
    env.update({"ANTHROPIC_BASE_URL": base, "ANTHROPIC_API_KEY": "cs-local",
                "ANTHROPIC_AUTH_TOKEN": "cs-local",
                "ANTHROPIC_MODEL": model, "ANTHROPIC_SMALL_FAST_MODEL": model})
    sp.write_text(json.dumps(ex, indent=2), encoding="utf-8")
    return sp, existed, original

def _wire_opencode(model, port):
    tgt = pathlib.Path.home() / ".config" / "opencode" / "opencode.json"
    tgt.parent.mkdir(parents=True, exist_ok=True)
    existed, original = _backup_file(tgt)
    tgt.write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "provider": {"cs-framework": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "CS Framework",
            "options": {"baseURL": "http://127.0.0.1:%d/v1" % port,
                        "apiKey": "cs-local"},
            "models": {model: {"name": model}},
        }},
        "model": "cs-framework/%s" % model,
    }, indent=2), encoding="utf-8")
    return tgt, existed, original

def _launch_agent(binary, env_extra=None):
    exe = find_tool(binary) or shutil.which(binary)
    if not exe:
        print(RD + "  ! " + binary + " not installed" + RSTC); return
    env = os.environ.copy()
    if env_extra: env.update(env_extra)
    try: subprocess.call([exe], env=env)
    except KeyboardInterrupt: print(YL + "\n  stopped" + RSTC)


def cmd_chatgpt(model=None, port=8686, no_launch=False):
    rec = match_model(model) if model else None
    if not rec:
        print(RD + "  no model match" + RSTC); return
    print(CY + "> ChatGPT / Codex -> " + rec.name + RSTC)
    p = _ensure_srv(port, rec.name)
    cfg, existed, original = _wire_chatgpt(rec.name, p)
    print(GR + "  v wrote " + str(cfg) + RSTC)
    print(GR + "  v http://127.0.0.1:" + str(p) + "/v1" + RSTC)
    exe_path = None
    for c in [pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "ChatGPT" / "ChatGPT.exe",
              pathlib.Path(os.environ.get("ProgramFiles", "")) / "ChatGPT" / "ChatGPT.exe",
              pathlib.Path(os.environ.get("ProgramFiles(x86)", "")) / "ChatGPT" / "ChatGPT.exe"]:
        if c.exists():
            exe_path = c
            break
    if no_launch or not exe_path:
        print(YL + "  ChatGPT not found -- config stays; run `cs unconnect chatgpt` to restore" + RSTC)
        return
    print(GR + "  launching " + str(exe_path) + RSTC)
    try:
        subprocess.Popen([str(exe_path)])
    except Exception as e:
        print(RD + "  ! " + str(e) + RSTC)
        return
    print(DIM + "  waiting for ChatGPT to close (Ctrl-C to skip restore)" + RSTC)
    try:
        _wait_process_exit("ChatGPT.exe")
    except KeyboardInterrupt:
        print(YL + "\n  stopping wait" + RSTC)
    finally:
        _restore_file(cfg, existed, original)

def cmd_claude(model=None, port=8687, no_launch=False):
    rec = match_model(model) if model else None
    if not rec:
        print(RD + "  no model match" + RSTC); return
    print(CY + "> Claude Code -> " + rec.name + RSTC)
    p = _ensure_srv(port, rec.name)
    sp, existed, original = _wire_claude(rec.name, p)
    print(GR + "  v wrote " + str(sp) + RSTC)
    print(GR + "  v http://127.0.0.1:" + str(p) + RSTC)
    if no_launch:
        return
    env = {
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:%d" % p,
        "ANTHROPIC_API_KEY": "cs-local",
        "ANTHROPIC_AUTH_TOKEN": "cs-local",
        "ANTHROPIC_MODEL": rec.name,
        "ANTHROPIC_SMALL_FAST_MODEL": rec.name,
    }
    try:
        _launch_agent("claude", env_extra=env)
    finally:
        _restore_file(sp, existed, original)

def cmd_opencode(model=None, port=8688, no_launch=False):
    rec = match_model(model) if model else None
    if not rec:
        print(RD + "  no model match" + RSTC); return
    print(CY + "> OpenCode -> " + rec.name + RSTC)
    p = _ensure_srv(port, rec.name)
    cfg, existed, original = _wire_opencode(rec.name, p)
    print(GR + "  v wrote " + str(cfg) + RSTC)
    print(GR + "  v http://127.0.0.1:" + str(p) + "/v1" + RSTC)
    if no_launch:
        return
    env = {"OPENAI_BASE_URL": "http://127.0.0.1:%d/v1" % p, "OPENAI_API_KEY": "cs-local"}
    try:
        _launch_agent("opencode", env_extra=env)
    finally:
        _restore_file(cfg, existed, original)

def cmd_unconnect(target="all"):
    home = pathlib.Path.home()
    targets = []
    if target in ("all", "chatgpt"):
        targets.append(home / ".codex" / "config.toml")
    if target in ("all", "claude"):
        targets.append(home / ".claude" / "settings.json")
    if target in ("all", "opencode"):
        targets.append(home / ".config" / "opencode" / "opencode.json")
    for path in targets:
        if path.exists():
            try:
                path.unlink()
                print(GR + "  ^ removed " + str(path) + RSTC)
            except Exception as e:
                print(RD + "  ! " + str(e) + RSTC)
        else:
            print(DIM + "  = " + str(path) + " (already gone)" + RSTC)


def _fmt_ago(ts):
    try:
        d = time.time() - float(ts)
    except Exception:
        return "?"
    if d < 60: return str(int(d)) + "s ago"
    if d < 3600: return str(int(d/60)) + "m ago"
    if d < 86400: return str(int(d/3600)) + "h ago"
    if d < 86400*30: return str(int(d/86400)) + "d ago"
    if d < 86400*365: return str(int(d/86400/30)) + "mo ago"
    return str(int(d/86400/365)) + "y ago"


def cmd_pull(name, only=None):
    """Download a model from HuggingFace by repo name or search term."""
    if not name:
        print(RD + "  usage: cs pull <owner/repo>  or  cs pull <search>" + RSTC)
        return
    if "/" in name:
        print(CY + "> downloading " + name + RSTC)
        try:
            hf_download_repo(name, only)
            print(GR + "  v done - try: cs run " + name.split("/")[-1] + RSTC)
        except Exception as e:
            print(RD + "  ! " + str(e) + RSTC)
        return
    print(CY + "> searching HuggingFace for: " + name + RSTC)
    try:
        hits = hf_search(name, limit=15)
    except Exception as e:
        print(RD + "  ! search failed: " + str(e) + RSTC); return
    if not hits:
        print(RD + "  no results" + RSTC); return
    rows = []
    for i, mm in enumerate(hits[:15]):
        rows.append([str(i), mm["id"], "{:,}".format(mm.get("downloads", 0))])
    print(table(rows, ["#", "REPO", "DOWNLOADS"]))
    choice = ask(CY + "  pick a number (Enter to cancel): " + RSTC)
    if not choice:
        return
    try:
        repo = hits[int(choice)]["id"]
    except Exception:
        return
    try:
        hf_download_repo(repo, only)
        print(GR + "  v done - try: cs run " + repo.split("/")[-1] + RSTC)
    except Exception as e:
        print(RD + "  ! " + str(e) + RSTC)


def _find_serve_procs():
    """Return list of dicts describing running cs serve processes."""
    procs = []
    try:
        import subprocess as _sp
        if os.name == "nt":
            r = _sp.run(["wmic", "process", "where", "name='python.exe'",
                         "get", "ProcessId,CommandLine"],
                        capture_output=True, text=True, timeout=10)
            out = r.stdout or ""
        else:
            r = _sp.run(["ps", "-eo", "pid,args"], capture_output=True, text=True)
            out = r.stdout or ""
        for line in out.splitlines():
            if "cs.py" not in line or " serve" not in line:
                continue
            pm = re.search(r"--port\s+(\d+)", line)
            mm = re.search(r"--model\s+(\S+)", line)
            idm = re.search(r"(\d+)\s*$", line.strip())
            if os.name != "nt":
                idm = re.match(r"\s*(\d+)", line)
            procs.append({
                "pid": idm.group(1) if idm else "?",
                "port": pm.group(1) if pm else "?",
                "model": mm.group(1) if mm else "(auto)",
            })
    except Exception:
        pass
    return procs


def cmd_ps():
    """List running cs serve processes (like `ollama ps`)."""
    procs = _find_serve_procs()
    if not procs:
        print(DIM + "  no running servers" + RSTC); return
    rows = [[p["pid"], p["port"], trunc(p["model"], 50)] for p in procs]
    print(table(rows, ["PID", "PORT", "MODEL"]))


def cmd_stop(target=None):
    """Stop running cs serve processes."""
    procs = _find_serve_procs()
    if not procs:
        print(DIM + "  no running servers" + RSTC); return
    if target:
        procs = [p for p in procs if target in p["model"] or target == p["port"]]
        if not procs:
            print(RD + "  no matching server for: " + target + RSTC); return
    import subprocess as _sp
    killed = 0
    for p in procs:
        try:
            if os.name == "nt":
                _sp.run(["taskkill", "/PID", p["pid"], "/F"],
                        capture_output=True, timeout=5)
            else:
                os.kill(int(p["pid"]), 15)
            killed += 1
        except Exception:
            pass
    print(GR + "  v stopped " + str(killed) + " server(s)" + RSTC)


def cmd_rm(model):
    """Delete a model file from disk."""
    rec = match_model(model)
    if not rec:
        print(RD + "  no model matches: " + model + RSTC); return
    p = Path(rec.path)
    if not p.exists():
        print(RD + "  file already gone: " + str(p) + RSTC); return
    try:
        sz = human(p.stat().st_size)
    except Exception:
        sz = "?"
    if not ask_yn("  delete " + str(p) + " (" + sz + ")?", default=False):
        print(DIM + "  cancelled" + RSTC); return
    try:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        print(GR + "  v removed " + rec.name + RSTC)
        scan_models()
    except Exception as e:
        print(RD + "  ! " + str(e) + RSTC)


def _handle_anthropic_messages(handler):
    try:
        ln = int(handler.headers.get("Content-Length", 0))
        body = json.loads(handler.rfile.read(ln) or b"{}")
    except Exception as e:
        handler._json(400, {"type":"error","error":{"type":"invalid_request_error","message":str(e)}}); return
    model = body.get("model", "")
    rec = _SERVE.get("rec")
    if not rec or (model and rec.name != model): rec = match_model(model) or rec
    if not rec: handler._json(404, {"type":"error","error":{"type":"not_found_error","message":"model not found"}}); return
    rt = pick_runtime(rec)
    if not rt: handler._json(503, {"type":"error","error":{"type":"overloaded_error","message":"no runtime"}}); return
    ctx = get_context(rec)
    sys_msg = body.get("system")
    if isinstance(sys_msg, list): sys_msg = " ".join(b.get("text","") for b in sys_msg if isinstance(b, dict))
    if sys_msg: ctx["system"] = sys_msg
    hist = []
    for m in body.get("messages", []):
        role = m.get("role", "user"); c = m.get("content", "")
        if isinstance(c, list): c = " ".join(b.get("text","") for b in c if isinstance(b, dict))
        hist.append({"role": role, "content": c})
    prompt = build_prompt(hist, ctx)
    ctx["max_new_tokens"] = int(body.get("max_tokens", ctx.get("max_new_tokens", 512)))
    stream = bool(body.get("stream", False))
    mid = "msg_" + uuid.uuid4().hex[:20]
    if not stream:
        out = []
        try:
            for c in rt.stream(rec, prompt, hist, ctx): out.append(c)
        except Exception as e:
            handler._json(500, {"type":"error","error":{"type":"api_error","message":str(e)}}); return
        txt = "".join(out)
        handler._json(200, {"id": mid, "type":"message", "role":"assistant",
            "model": rec.name, "content":[{"type":"text","text":txt}],
            "stop_reason":"end_turn", "stop_sequence": None,
            "usage": {"input_tokens":0, "output_tokens": max(1, len(txt)//4)}}); return
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.end_headers()
    def sse(ev, data):
        handler.wfile.write(("event: " + ev + "\n").encode())
        handler.wfile.write(b"data: " + json.dumps(data).encode() + b"\n\n")
        handler.wfile.flush()
    try:
        sse("message_start", {"type":"message_start","message":{"id":mid,"type":"message",
            "role":"assistant","model":rec.name,"content":[],"stop_reason":None,
            "stop_sequence":None,"usage":{"input_tokens":0,"output_tokens":0}}})
        sse("content_block_start", {"type":"content_block_start","index":0,
            "content_block":{"type":"text","text":""}})
        total = 0
        for c in rt.stream(rec, prompt, hist, ctx):
            if not c: continue
            total += len(c)
            sse("content_block_delta", {"type":"content_block_delta","index":0,
                "delta":{"type":"text_delta","text":c}})
        sse("content_block_stop", {"type":"content_block_stop","index":0})
        sse("message_delta", {"type":"message_delta",
            "delta":{"stop_reason":"end_turn","stop_sequence":None},
            "usage":{"output_tokens":max(1,total//4)}})
        sse("message_stop", {"type":"message_stop"})
    except Exception as e:
        try: sse("error", {"type":"error","error":{"type":"api_error","message":str(e)}})
        except Exception: pass


class _ServeHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError,
                BrokenPipeError, TimeoutError):
            self.close_connection = True
        except Exception as e:
            try:
                log(f"serve handle_one_request: {e}", "warn")
            except Exception:
                pass
            self.close_connection = True

    def log_error(self, fmt, *args):
        pass

    def log_message(self, *a):
        pass


    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            recs = load_scan() + platform_records()
            self._json(200, {"object":"list",
                             "data":[{"id":r.name,"object":"model"} for r in recs]})
        elif self.path == "/health":
            self._json(200, {"ok":True,"version":VERSION})
        else:
            self._json(404, {"error":"not found"})

    def do_POST(self):
        if self.path.startswith("/v1/messages"):
            return _handle_anthropic_messages(self)
        if not self.path.startswith(("/v1/chat/completions","/v1/completions")):
            self._json(404, {"error":"not found"}); return
        try:
            ln = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(ln) or b"{}")
        except Exception as e: self._json(400, {"error":str(e)}); return
        model = body.get("model", "")
        rec = _SERVE["rec"]
        if not rec or rec.name != model: rec = match_model(model) or rec
        if not rec: self._json(404, {"error": f"model {model} not found"}); return
        rt = pick_runtime(rec)
        if not rt: self._json(503, {"error": "no runtime"}); return
        ctx = get_context(rec)
        if self.path.startswith("/v1/chat"):
            hist = list(body.get("messages", []))
            if hist and hist[0].get("role") == "system":
                ctx["system"] = hist[0]["content"]; hist = hist[1:]
            prompt = build_prompt(hist, ctx)
        else:
            prompt = body.get("prompt", "")
            hist = [{"role":"user","content":prompt}]
        stream = bool(body.get("stream", False))
        if not stream:
            chunks = []
            try:
                for c in rt.stream(rec, prompt, hist, ctx): chunks.append(c)
            except Exception as e: self._json(500, {"error":str(e)}); return
            self._json(200, {"object":"chat.completion",
                             "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                             "model": rec.name,
                             "choices":[{"index":0,"finish_reason":"stop",
                                         "message":{"role":"assistant","content":"".join(chunks)}}]})
            return
        self._sse()
        try:
            self.wfile.write(b'data: {"choices":[{"delta":{"role":"assistant"},"index":0}]}\n\n')
            for c in rt.stream(rec, prompt, hist, ctx):
                self.wfile.write(b"data: " + json.dumps({"choices":[{"delta":{"content":c},"index":0}]}).encode() + b"\n\n")
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()
        except Exception: pass

def cmd_serve(host, port, model=None):
    if model:
        rec = match_model(model)
        if rec: _SERVE["rec"] = rec
    print(MG + f"  serving OpenAI-compatible API on http://{host}:{port}/v1" + RSTC)
    srv = _QuietHTTPServer((host, port), _ServeHandler)
    try: srv.serve_forever()
    except KeyboardInterrupt: print(YL + "  ⌁ stopped" + RSTC)
    finally: srv.server_close()

# ─── commands ──────────────────────────────────────────────────────────────
def match_model(q):
    if not q: return None
    recs = load_scan() + platform_records()
    hits = [r for r in recs if fuzzy(q, r.name) or fuzzy(q, str(r.path))]
    return hits[0] if hits else None

def cmd_scan():
    print(CY + "▸ scan" + RSTC)
    with Spinner("scanning"):
        recs = scan_models()
    rows = [[trunc(r.name,44), r.kind, trunc(arch_disp(r.arch),26), human(r.size), r.source] for r in recs]
    if rows: print(table(rows, ["NAME","KIND","ARCH","SIZE","SOURCE"]))
    print(GR + f"  v {len(recs)}" + RSTC); return recs

def cmd_list():
    recs = load_scan(); vc = jload(VER_P, {})
    print(YL + "  MODELS" + RSTC)
    rows = []
    for r in recs:
        st = vc.get(str(r.path), {})
        mark = "v" if st.get("ok") else ("x" if st else "·")
        rt = pick_runtime(r)
        rows.append([mark, trunc(r.name,38), r.kind, trunc(arch_disp(r.arch),22),
                     human(r.size), r.source, rt.id if rt else "-"])
    if rows: print(table(rows, ["OK","NAME","KIND","ARCH","SIZE","SOURCE","RUNTIME"]))
    else: print(DIM + "  (none — run cs scan)" + RSTC)
    print(YL + "  PLATFORMS" + RSTC)
    plats = list(CFG.get("platforms", {}).keys())
    print("  " + (", ".join(plats) if plats else DIM + "(none)" + RSTC))
    print(YL + "  RUNTIMES" + RSTC)
    list_runtimes()

def list_runtimes():
    for rt in all_runtimes():
        try:
            ok, h = rt.available()
        except Exception as e:
            ok, h = False, str(e)
        if rt.id == "llama-server" and not ok and _prism_server():
            ok, h = True, "(prism fork)"
        if rt.id == "llama-cli" and not ok and _prism_cli():
            ok, h = True, "(prism fork)"
        mark = GR + "v" + RSTC if ok else DIM + "." + RSTC
        print(f"  {mark} {rt.id:18} {DIM}{h or 'ready'}{RSTC}")


def cmd_verify(q=None, deep=False, online=False):
    recs = [r for r in load_scan() if not q or fuzzy(q, r.name) or fuzzy(q, str(r.path))]
    if not recs: print(RD + "  nothing" + RSTC); return
    allok = True
    for r in recs:
        print(CY + "┄ " + r.name + RSTC)
        res, ok = verify_rec(r, deep, online); allok = allok and ok
        for l, o, info in res:
            tag = GR + "v" + RSTC if o else RD + "x" + RSTC
            print(f"   {tag} {l:32} {DIM}{info}{RSTC}")
    print((GR + "  integrity: clean" if allok else RD + "  integrity: faults") + RSTC)

def cmd_run(q, prompt=None):
    """Chat with a model. If -p given, one-shot prompt instead."""
    if not q:
        return chooser()
    rec = match_model(q)
    if not rec:
        print(RD + "  no model matches: " + q + RSTC); return
    rt = pick_runtime(rec)
    if not rt:
        print(RD + "  no runtime for " + rec.name + RSTC); return
    ctx = get_context(rec)
    if prompt:
        stream_session(rec, rt, [{"role": "user", "content": prompt}], ctx)
        append_history(rec, "user", prompt)
    else:
        chat_loop(rec, rt, ctx)


def cmd_chat(q=None, incognito=False):
    if not q:
        recs = load_scan() + platform_records()
        if not recs: return chooser()
        for i, r in enumerate(recs[:30]): print(f"  [{i:2}] {r.name}")
        try: rec = recs[int(ask("  select › "))]
        except Exception: return
    else:
        rec = match_model(q)
    if not rec: print(RD + "no match" + RSTC); return
    rt = pick_runtime(rec)
    if not rt: print(RD + "no runtime" + RSTC); return
    chat_loop(rec, rt, get_context(rec), incognito=incognito)

def cmd_incognito(q=None):
    """Incognito: nothing saved to disk."""
    clearscr()
    print(YL + "  INCOGNITO — nothing will be saved" + RSTC)
    cmd_chat(q, incognito=True)

def cmd_code(q=None, cwd=None):
    if not q: return chooser()
    rec = match_model(q)
    if not rec: print(RD + "no match: " + q + RSTC); return
    rt = pick_runtime(rec)
    if not rt: print(RD + "no runtime" + RSTC); return
    code_loop(rec, rt, get_context(rec), cwd=cwd)

def cmd_bench(q, tokens=128):
    rec = match_model(q)
    if not rec: print(RD + "no match: " + q + RSTC); return
    rt = pick_runtime(rec)
    if not rt: print(RD + "no runtime" + RSTC); return
    ctx = get_context(rec); ctx["max_new_tokens"] = tokens
    prompt = "Benchmark: count upwards and explain briefly."
    print(CY + f"▸ bench {rec.name} via {rt.id}" + RSTC)
    t0 = time.time(); chars = 0
    try:
        for c in rt.stream(rec, prompt, [{"role":"user","content":prompt}], ctx):
            chars += len(c)
            if chars/4 >= tokens: break
    except Exception as e: print(RD + f"  x {e}" + RSTC); return
    dt = max(time.time()-t0, 1e-6)
    print(GR + f"  v ~{chars/4:.0f} tok in {dt:.1f}s = {chars/4/dt:.2f} tok/s" + RSTC)

def _find_serve_procs():
    procs = []
    try:
        if os.name == "nt":
            r = subprocess.run(["wmic", "process", "where", "name='python.exe'",
                                "get", "ProcessId,CommandLine"],
                               capture_output=True, text=True, timeout=10)
            out = r.stdout or ""
        else:
            r = subprocess.run(["ps", "-eo", "pid,args"],
                               capture_output=True, text=True, timeout=10)
            out = r.stdout or ""
        for line in out.splitlines():
            if "cs.py" not in line or " serve" not in line:
                continue
            pm = re.search(r"--port\s+(\d+)", line)
            mm = re.search(r"--model\s+(\S+)", line)
            idm = re.search(r"(\d+)\s*$", line.strip())
            if os.name != "nt":
                idm = re.match(r"\s*(\d+)", line)
            procs.append({
                "pid": idm.group(1) if idm else "?",
                "port": pm.group(1) if pm else "?",
                "model": mm.group(1) if mm else "(auto)",
            })
    except Exception:
        pass
    return procs


def _hr():
    print(DIM + "  " + "-" * 62 + RSTC)




def show_logo_compact():
    """One-line brand header."""
    print()
    print("  " + grad(0.2) + "\u25c6\u25c6\u25c6" + RSTC + "  " +
          col(201) + "C S   F R A M E W O R K" + RSTC + "  " +
          DIM + "v" + VERSION + RSTC)
    print()



def _vis(s):
    """Strip ANSI escapes for visible width."""
    return re.sub(r"\x1b\[[0-9;]*m", "", str(s))


def _pad(s, w):
    s = str(s)
    return s + " " * max(0, w - len(_vis(s)))


def _hex_start_with(rec):
    """Jump straight into Hex Agent for a given model."""
    rt = pick_runtime(rec)
    if not rt:
        print(RD + "  no runtime for " + rec.name + RSTC)
        print(DIM + "    try: cs install llamacpp-bin  or  cs install llama-cpp" + RSTC)
        return
    cwd = os.getcwd()
    ctx = get_context(rec)
    try:
        _hex_agent(rec, rt, cwd, ctx)
    except Exception as e:
        import traceback as _tb
        print(RD + "  agent error: " + str(e) + RSTC)
        log("hex start: " + _tb.format_exc(), "error")


def _clear_line():
    try:
        sys.stdout.write("\r" + " " * 100 + "\r")
        sys.stdout.flush()
    except Exception:
        pass



def _draw_panels(recs, procs, info, sel, dm, aa):
    """Draw the main dashboard: logo + two-column panels + key bar."""
    clearscr()
    # --- logo ---
    try:
        rows = render_logo(10)
        pad = max(0, (76 - len(rows[0])) // 2) if rows else 0
        for i, rw in enumerate(rows):
            print(" " * pad + grad(i / max(len(rows), 1)) + rw + RSTC)
    except Exception:
        pass
    print()
    brand = ("  " + col(201) + "C S   F R A M E W O R K" + RSTC +
             "   " + DIM + "v" + VERSION + "  \u00b7  " + CODENAME + RSTC)
    print(brand)

    # --- status ---
    gpu = str(info.get("gpu", "cpu-only"))
    if "CUDA:" in gpu:
        gpu = gpu.split("CUDA:", 1)[1].strip().split(",")[0].strip()
    gpu = trunc(gpu, 26)
    print("  " + DIM + "models " + RSTC + GR + str(len(recs)) + RSTC +
          "  " + DIM + "servers " + RSTC + GR + str(len(procs)) + RSTC +
          "  " + DIM + "gpu " + RSTC + gpu +
          "  " + DIM + "tools " + RSTC +
          (GR + "auto" + RSTC if aa else YL + "ask" + RSTC))
    print()

    # --- panels ---
    lw = 28
    rw = 40
    top = ("  " + col(51) + "\u256d" + "\u2500" * lw + "\u252c" +
           "\u2500" * rw + "\u256e" + RSTC)

    # header row with titles
    lh = _pad(" " + col(201) + "M O D E L S" + RSTC, lw)
    rh = _pad(" " + col(201) + "A G E N T" + RSTC, rw)
    print(top.replace("\u252c", "\u252c", 1))
    # actually we need a proper header separator; do it directly
    print("  " + col(51) + "\u2502" + RSTC + " " + lh + " " +
          col(51) + "\u2502" + RSTC + " " + rh + " " +
          col(51) + "\u2502" + RSTC)
    print("  " + col(51) + "\u251c" + "\u2500" * lw + "\u253c" +
          "\u2500" * rw + "\u2524" + RSTC)

    # model list (window of 10 centered on selection)
    page = 10
    half = page // 2
    start = max(0, sel - half)
    end = min(len(recs), start + page)
    if end - start < page:
        start = max(0, end - page)

    # right panel content
    if recs:
        cur = recs[sel]
        rt = pick_runtime(cur)
        rt_tag = rt.id if rt else "no runtime"
        right_rows = [
            (" " + col(47) + trunc(cur.name, rw - 4) + RSTC, ""),
            (" " + DIM + "kind  " + RSTC + cur.kind, ""),
            (" " + DIM + "arch  " + RSTC + trunc(arch_disp(cur.arch), 30), ""),
            (" " + DIM + "size  " + RSTC + human(cur.size), ""),
            (" " + DIM + "rt    " + RSTC + rt_tag, ""),
            ("", ""),
            (" " + GR + "\u23ce Enter" + RSTC + DIM + "  hex agent" + RSTC, ""),
            (" " + GR + "C" + RSTC + DIM + "  plain chat" + RSTC, ""),
            (" " + GR + "S" + RSTC + DIM + "  serve openai" + RSTC, ""),
            (" " + GR + "V" + RSTC + DIM + "  verify" + RSTC, ""),
            ("", ""),
            (" " + DIM + str(len(recs)) + " models  \u00b7  " +
             str(len(procs)) + " servers" + RSTC, ""),
        ]
    else:
        right_rows = [
            (" " + YL + "no models installed" + RSTC, ""),
            (" " + DIM + "press E to explore huggingface" + RSTC, ""),
        ]

    # pad right_rows to page rows
    while len(right_rows) < page:
        right_rows.append(("", ""))

    # draw rows
    for row in range(page):
        i = start + row
        if i < len(recs):
            r = recs[i]
            vc = jload(VER_P, {})
            st = vc.get(str(r.path), {})
            if st.get("ok"):
                mk = GR + "\u2713" + RSTC
            elif st:
                mk = RD + "\u2717" + RSTC
            else:
                mk = DIM + "\u00b7" + RSTC
            is_sel = (i == sel)
            arrow = ">" if is_sel else " "
            name = trunc(r.name, lw - 9)
            line = " " + arrow + mk + " [" + str(i).rjust(2) + "] " + name
            if is_sel:
                line = col(238) + line + RSTC
            else:
                line = DIM + line + RSTC
        else:
            line = ""
        lcell = _pad(line, lw)

        rtxt = right_rows[row][0] if row < len(right_rows) else ""
        rcell = _pad(rtxt, rw)

        print("  " + col(51) + "\u2502" + RSTC + " " + lcell + " " +
              col(51) + "\u2502" + RSTC + " " + rcell + " " +
              col(51) + "\u2502" + RSTC)

    print("  " + col(51) + "\u2570" + "\u2500" * lw + "\u2534" +
          "\u2500" * rw + "\u256f" + RSTC)
    print()

    # key bar
    def key(k, v, color=None):
        return (col(51) + "[" + RSTC + col(238) + k + RSTC +
                col(51) + "]" + RSTC + " " +
                (color or GR) + v + RSTC)
    print("  " + "  ".join([
        key("\u2191\u2193", "navigate"),
        key("Enter", "hex agent"),
        key("C", "chat"),
        key("E", "explore"),
        key("M", "models"),
    ]))
    print("  " + "  ".join([
        key("A", "agents"),
        key("H", "health"),
        key("R", "computer"),
        key("G", "rig"),
        key("K", "settings"),
        key("Q", "quit", RD),
    ]))
    print()


def _render_main_menu(recs, procs, info, dm, aa):
    """Compact, properly-aligned main menu."""
    # --- header: small hexagon + wordmark on one line ---
    print()
    print("  " + grad(0.15) + "\u25c6" + RSTC + " " +
          grad(0.35) + "\u25c6" + RSTC + " " +
          grad(0.55) + "\u25c6" + RSTC + "  " +
          col(201) + "C S   F R A M E W O R K" + RSTC + "  " +
          DIM + "v" + VERSION + "  \u00b7  " + CODENAME + RSTC)
    print()

    # --- status line ---
    gpu = str(info.get("gpu", "cpu-only"))
    if "CUDA:" in gpu:
        gpu = gpu.split("CUDA:", 1)[1].strip().split(",")[0].strip()
    gpu = trunc(gpu, 30)
    stats = (
        "  " + DIM + "models " + RSTC + GR + str(len(recs)) + RSTC +
        "  " + DIM + "servers " + RSTC + GR + str(len(procs)) + RSTC +
        "  " + DIM + "gpu " + RSTC + gpu +
        "  " + DIM + "tools " + RSTC +
        (GR + "auto" + RSTC if aa else YL + "ask" + RSTC)
    )
    print(stats)
    if dm:
        print("  " + DIM + "default " + RSTC + col(47) +
              trunc(dm, 66) + RSTC)
    print()

    # --- models (compact, aligned) ---
    try:
        vc = jload(VER_P, {})
        for i, r in enumerate(recs[:6]):
            st = vc.get(str(r.path), {})
            if st.get("ok"):
                mk = GR + "\u2713" + RSTC
            elif st:
                mk = RD + "\u2717" + RSTC
            else:
                mk = DIM + "\u00b7" + RSTC
            rt = pick_runtime(r)
            rt_tag = rt.id if rt else "no runtime"
            name = trunc(r.name, 44).ljust(44)
            size = human(r.size).rjust(9)
            print("  " + mk + " " + DIM + "[" + str(i).rjust(2) + "]" +
                  RSTC + " " + name + "  " + DIM + size + RSTC + "  " +
                  DIM + rt_tag + RSTC)
        if len(recs) > 6:
            print("  " + DIM + "     ... " + str(len(recs) - 6) +
                  " more (press M)" + RSTC)
    except Exception as e:
        print("  " + RD + "model list error: " + str(e) + RSTC)
    print()

    # --- key bar (fixed width, no wrap) ---
    def key(k, v, color=None):
        return (col(51) + "[" + RSTC + col(238) + k + RSTC +
                col(51) + "]" + RSTC + " " +
                (color or GR) + v + RSTC)

    print("  " + "  ".join([
        key("C", "chat"),
        key("E", "explore"),
        key("M", "models"),
        key("H", "health"),
        key("S", "servers"),
    ]))
    print("  " + "  ".join([
        key("A", "agents"),
        key("X", "hex", MG),
        key("R", "computer", MG),
        key("G", "rig"),
        key("K", "settings"),
        key("F", "fix", YL),
        key("Q", "quit", RD),
    ]))
    print()


def menu_chat():
    recs = load_scan()
    if not recs:
        print(YL + "  no models installed -- try option 2" + RSTC)
        return
    for i, r in enumerate(recs[:30]):
        rt = pick_runtime(r)
        tag = (DIM + rt.id + RSTC) if rt else (RD + "no runtime" + RSTC)
        print("  [%2d] %-46s %9s  %s" % (i, trunc(r.name, 46), human(r.size), tag))
    sel = ask(CY + "  pick a number (Enter cancels): " + RSTC).strip()
    if not sel:
        return
    try:
        rec = recs[int(sel)]
    except Exception:
        return
    rt = pick_runtime(rec)
    if not rt:
        print(RD + "  no runtime for " + rec.name + RSTC)
        return
    chat_loop(rec, rt, get_context(rec))


def cmd_explore():
    print()
    print(YL + "  EXPLORE HuggingFace" + RSTC)
    q = ask("  search (blank = trending): ").strip()
    try:
        hits = hf_search(q or "", limit=20)
    except Exception as e:
        print(RD + "  ! " + str(e) + RSTC)
        return
    if not hits:
        print(DIM + "  no results" + RSTC)
        return
    rows = []
    for i, mm in enumerate(hits[:20]):
        rows.append([str(i), mm["id"], "{:,}".format(mm.get("downloads", 0))])
    print(table(rows, ["#", "REPO", "DOWNLOADS"]))
    sel = ask(CY + "  download # (Enter cancels): " + RSTC).strip()
    if not sel:
        return
    try:
        repo = hits[int(sel)]["id"]
    except Exception:
        return
    print(CY + "  downloading " + repo + RSTC)
    try:
        hf_download_repo(repo)
    except Exception as e:
        print(RD + "  ! " + str(e) + RSTC)
        return
    print(CY + "  scanning..." + RSTC)
    scan_models()
    print(GR + "  v done" + RSTC)


def cmd_health():
    print()
    print(YL + "  HEALTH" + RSTC)
    recs = load_scan()
    vc = jload(VER_P, {})
    good = bad = unknown = 0
    for r in recs:
        st = vc.get(str(r.path), {})
        if st.get("ok"):
            good += 1
        elif st:
            bad += 1
        else:
            unknown += 1
    procs = _find_serve_procs()
    info = probe()
    print("  models   : " + str(len(recs)) + "  (ok " + str(good) +
          ", bad " + str(bad) + ", unverified " + str(unknown) + ")")
    print("  servers  : " + str(len(procs)))
    print("  gpu      : " + str(info.get("gpu", "?")))
    print("  ram      : " + str(info.get("ram", "?")))
    for rt in all_runtimes():
        try:
            ok, h = rt.available()
        except Exception as e:
            ok, h = False, str(e)
        if rt.id == "llama-server" and not ok and _prism_server():
            ok, h = True, "(prism fork)"
        if rt.id == "llama-cli" and not ok and _prism_cli():
            ok, h = True, "(prism fork)"
        mark = GR + "v" + RSTC if ok else DIM + "." + RSTC
        print("    " + mark + " " + rt.id.ljust(18) + DIM + (h or "ready") + RSTC)
    if procs:
        print()
        rows = [[p["pid"], p["port"], trunc(p["model"], 50)] for p in procs]
        print(table(rows, ["PID", "PORT", "MODEL"]))
    print()
    print(DIM + "  [v] verify all   [Enter] back" + RSTC)
    c = ask(CY + "  > " + RSTC).strip().lower()
    if c == "v":
        cmd_verify(None, deep=True)


def menu_servers():
    while True:
        procs = _find_serve_procs()
        print()
        print(YL + "  SERVERS" + RSTC)
        if procs:
            rows = [[p["pid"], p["port"], trunc(p["model"], 50)] for p in procs]
            print(table(rows, ["PID", "PORT", "MODEL"]))
        else:
            print(DIM + "  (none running)" + RSTC)
        print()
        print("  " + GR + "k" + RSTC + " stop all   " + GR + "b" + RSTC + " back")
        c = ask(CY + "  > " + RSTC).strip().lower()
        if c in ("b", ""):
            return
        if c == "k":
            cmd_stop()


def cmd_stop():
    procs = _find_serve_procs()
    if not procs:
        print(DIM + "  no running servers" + RSTC)
        return
    killed = 0
    for p in procs:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", p["pid"], "/F"],
                               capture_output=True, timeout=5)
            else:
                os.kill(int(p["pid"]), 15)
            killed += 1
        except Exception:
            pass
    print(GR + "  v stopped " + str(killed) + " server(s)" + RSTC)


_DEFINE_RX = re.compile(r"<define_tool>\s*(\{.*?\})\s*</define_tool>", re.S)
_MEM_RX = re.compile(r"<memory>\s*(\{.*?\})\s*</memory>", re.S)




def _handle_define_tools(text):
    calls = _DEFINE_RX.findall(text)
    results = []
    for raw in calls:
        try:
            spec = json.loads(raw)
            name = spec.get("name", "").strip()
            desc = spec.get("desc", "").strip()
            code = spec.get("code", "")
        except Exception as e:
            results.append("[define_tool parse error: " + str(e) + "]")
            continue
        if not name or not code:
            results.append("[define_tool: name and code required]")
            continue
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,40}$", name):
            results.append("[define_tool: invalid name]")
            continue
        if "def run(" not in code:
            results.append("[define_tool: code must define run(args, cwd=None)]")
            continue
        try:
            path = PLUGIN_TOOLS_D / (name + ".py")
            path.write_text("# CS agent tool: " + name + "\n# " + desc + "\n" + code, encoding="utf-8")
            ns = {}
            exec(compile(code, str(path), "exec"), ns)
            fn = ns.get("run")
            if not callable(fn):
                results.append("[define_tool: no run() in " + name + "]")
                continue
            TOOLS_IMPL[name] = fn
            TOOLS_SPEC.append({"name": name, "desc": desc or "custom tool"})
            _agent_mem_add("tool", name)
            results.append("[defined tool: " + name + "]")
        except Exception as e:
            results.append("[define_tool error: " + str(e) + "]")
    return results, bool(calls)


def _handle_memories(text):
    calls = _MEM_RX.findall(text)
    saved = 0
    for raw in calls:
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        note = obj.get("note") or obj.get("fact") or ""
        if note:
            _agent_mem_add("note", note)
            saved += 1
    return saved


def _load_plugin_tools():
    if not PLUGIN_TOOLS_D.exists():
        return
    for pf in sorted(PLUGIN_TOOLS_D.glob("*.py")):
        name = pf.stem
        try:
            ns = {}
            exec(compile(pf.read_text(encoding="utf-8"), str(pf), "exec"), ns)
            fn = ns.get("run")
            if callable(fn) and name not in TOOLS_IMPL:
                TOOLS_IMPL[name] = fn
                TOOLS_SPEC.append({"name": name, "desc": "custom tool"})
        except Exception as e:
            log("custom tool " + name + " failed: " + str(e), "warn")


def _hex_logo_lines(h=11):
    rows = render_logo(h)
    out = []
    for i, rw in enumerate(rows):
        out.append(grad(i / max(len(rows), 1)) + rw + RSTC)
    return out




def _hex_clear():
    if CIN:
        try:
            os.system("cls" if os.name == "nt" else "clear")
        except Exception:
            pass


def _hex_prompt():
    return col(201) + "  ❯ " + RSTC




def cmd_cs_agent():
    """Hex Agent launcher — model picker + working dir + start."""
    _load_plugin_tools()
    recs = load_scan()
    if not recs:
        print(YL + "  no models installed" + RSTC)
        print(DIM + "  use the menu → explore to download one" + RSTC)
        return

    _hex_clear()
    print("\n".join(_hex_logo_lines(11)))
    print("  " + col(201) + AGENT_NAME + RSTC +
          "   " + DIM + "pick a model to begin" + RSTC)
    print()

    # show only chat-capable models
    chat_models = []
    for r in recs:
        if r.kind in ("gguf", "tf-dir", "safetensors") and pick_runtime(r):
            chat_models.append(r)
    if not chat_models:
        chat_models = recs

    for i, r in enumerate(chat_models[:20]):
        rt = pick_runtime(r)
        print("  [" + GR + str(i).rjust(2) + RSTC + "] " +
              trunc(r.name, 48).ljust(48) + "  " +
              DIM + human(r.size).rjust(9) + RSTC + "  " +
              (DIM + rt.id + RSTC if rt else RD + "no runtime" + RSTC))
    print()
    sel = ask("  " + CY + "pick › " + RSTC).strip()
    if not sel:
        return
    try:
        rec = chat_models[int(sel)]
    except Exception:
        print(RD + "  invalid choice" + RSTC)
        return

    rt = pick_runtime(rec)
    if not rt:
        print(RD + "  no runtime available for " + rec.name + RSTC)
        return

    cwd = ask("  " + CY + "cwd › " + RSTC + DIM + "[" + os.getcwd() + "]" +
              RSTC + " ").strip() or os.getcwd()
    if not Path(cwd).exists():
        print(RD + "  no such directory: " + cwd + RSTC)
        return

    ctx = get_context(rec)
    _hex_agent(rec, rt, cwd, ctx)


# --- computer use CLI commands ---
def menu_settings():
    while True:
        print()
        print("  " + col(51) + "\u2500" * 60 + RSTC)
        print("  " + col(201) + "S E T T I N G S" + RSTC)
        print("  " + col(51) + "\u2500" * 60 + RSTC)
        dm = CFG["prefs"].get("default_model") or "(none)"
        aa = CFG["prefs"].get("auto_approve", True)
        print("  data     " + DIM + str(DATA_HOME) + RSTC)
        print("  default  " + col(47) + dm + RSTC)
        print("  tools    " +
              (GR + "auto-approved" + RSTC if aa else YL + "prompt-per-call" + RSTC))
        print()
        print("  " + GR + "1" + RSTC + "  set default model")
        print("  " + GR + "2" + RSTC + "  edit context for a model")
        print("  " + GR + "3" + RSTC + "  toggle auto-approve tools")
        print("  " + GR + "4" + RSTC + "  add model search path")
        print("  " + GR + "5" + RSTC + "  show config as JSON")
        print("  " + GR + "6" + RSTC + "  reinstall `hex` command")
        print("  " + GR + "7" + RSTC + "  clear caches")
        print("  " + GR + "b" + RSTC + "  back")
        c = ask("  " + CY + "\u203a " + RSTC).strip().lower()
        if c in ("b", ""):
            return
        try:
            if c == "1":
                recs = load_scan()
                for i, r in enumerate(recs[:20]):
                    print("  [" + str(i) + "] " + r.name)
                n = ask("  # (or - to clear): ").strip()
                if n == "-":
                    CFG["prefs"]["default_model"] = ""
                    save_cfg()
                    print(GR + "  cleared" + RSTC)
                else:
                    CFG["prefs"]["default_model"] = recs[int(n)].name
                    save_cfg()
                    print(GR + "  default: " + recs[int(n)].name + RSTC)
            elif c == "2":
                recs = load_scan()
                for i, r in enumerate(recs[:20]):
                    print("  [" + str(i) + "] " + r.name)
                n = int(ask("  #: ").strip())
                edit_context(recs[n])
            elif c == "3":
                CFG["prefs"]["auto_approve"] = not aa
                save_cfg()
                print(GR + "  auto-approve: " +
                      ("ON" if not aa else "OFF") + RSTC)
            elif c == "4":
                p = ask("  path: ").strip()
                if p:
                    CFG.setdefault("paths", [])
                    if p not in CFG["paths"]:
                        CFG["paths"].append(p)
                        save_cfg()
                        print(GR + "  added" + RSTC)
            elif c == "5":
                print(json.dumps(CFG, indent=2, default=str))
            elif c == "6":
                install_self()
            elif c == "7":
                cmd_clean(downloads=False)
        except Exception as e:
            print(RD + "  ! " + str(e) + RSTC)


def menu_models():
    while True:
        recs = load_scan()
        vc = jload(VER_P, {})
        print()
        for i, r in enumerate(recs[:30]):
            st = vc.get(str(r.path), {})
            mk = GR + "*" + RSTC if st.get("ok") else DIM + "." + RSTC
            rt = pick_runtime(r)
            tag = rt.id if rt else "no runtime"
            print("  " + mk + " [" + str(i).rjust(2) + "] " +
                  trunc(r.name, 44).ljust(46) + "  " + DIM +
                  human(r.size).rjust(9) + RSTC + "  " + DIM + tag + RSTC)
        print()
        print("  " + DIM + "[v]erify all   [d]elete #   [s]can   [b]ack" + RSTC)
        c = ask("  " + CY + "\u203a " + RSTC).strip().lower()
        if c in ("b", ""):
            return
        if c == "v":
            cmd_verify(None, deep=False)
        elif c == "s":
            cmd_scan()
        elif c == "d":
            n = ask("  number to delete: ").strip()
            try:
                cmd_rm(recs[int(n)].name)
            except Exception:
                pass
        else:
            try:
                rec = recs[int(c)]
                rt = pick_runtime(rec)
                if rt:
                    chat_loop(rec, rt, get_context(rec))
                return
            except Exception:
                pass


def cmd_rig():
    recs = load_scan()
    procs = _find_serve_procs()
    info = probe()
    print()
    print("  " + col(51) + "\u2500" * 60 + RSTC)
    print("  " + col(201) + "A I   C O N T R O L   R I G" + RSTC)
    print("  " + col(51) + "\u2500" * 60 + RSTC)
    print("  runtime   " + DIM + "llama.cpp (server/cli/py)  transformers  ollama" + RSTC)
    print("  hw        " + DIM + str(info.get("gpu", "cpu-only"))[:50] + RSTC)
    print("  tools     " + DIM + str(len(TOOLS_IMPL)) + " callable" + RSTC)
    print("  screens   " + DIM + "screen  mouse  keyboard  apps" + RSTC)
    print("  safety    " + DIM + "auto-approve  checkpoints  /undo" + RSTC)
    if procs:
        for p in procs:
            print("  " + GR + "\u25cf" + RSTC + " port " + p["port"] +
                  "  " + DIM + p["model"] + RSTC)
    print()






def cmd_venvs():
    print()
    print("  " + col(201) + "RUNTIME VENVS" + RSTC + "  " + DIM +
          "(throwaway caches under cs_data/venvs/)" + RSTC)
    print()
    if not VENVS_D.exists():
        print(DIM + "  (none — first use of a backend creates them)" + RSTC)
        return
    rows = []
    for vd in sorted(VENVS_D.iterdir()):
        if not vd.is_dir(): continue
        py = _venv_python(vd.name)
        stamp = _venv_stamp(vd.name)
        try:
            sz = sum(f.stat().st_size for f in vd.rglob("*") if f.is_file())
        except Exception:
            sz = 0
        specs = ""
        if stamp.exists():
            try:
                specs = stamp.read_text(encoding="utf-8")
            except Exception:
                pass
        rows.append([
            vd.name,
            "ok" if py.exists() else "missing",
            human(sz),
            trunc(specs.replace("|", "  "), 55),
        ])
    if rows:
        print(table(rows, ["name", "python", "size", "specs"]))
    else:
        print(DIM + "  (empty)" + RSTC)
    print()
    print("  " + DIM + "[w]ipe one   [W]ipe all   [r]ebuild all   "
                "[b]ack" + RSTC)
    c = ask("  " + CY + "> " + RSTC).strip().lower()
    if c == "b" or not c:
        return
    if c == "w":
        which = ask("  venv name: ").strip()
        if which in _VENV_SPECS:
            _venv_wipe(which)
            print(GR + "  wiped " + which + RSTC)
    elif c == "W":
        if ask_yn("  wipe ALL venvs?", default=False):
            for name in _VENV_SPECS:
                _venv_wipe(name)
            print(GR + "  wiped all" + RSTC)
    elif c == "r":
        for name in _VENV_SPECS:
            try:
                _venv_ensure(name, force=True)
            except Exception as e:
                print(RD + "  ! " + name + ": " + str(e) + RSTC)


def cmd_venv_repair(name=None):
    """Wipe and rebuild one or all venvs."""
    targets = [name] if name in _VENV_SPECS else list(_VENV_SPECS)
    print()
    print("  " + col(201) + "REPAIR VENVS" + RSTC)
    for v in targets:
        try:
            _venv_ensure(v, force=True)
        except Exception as e:
            print(RD + "  x " + v + ": " + str(e) + RSTC)


def cmd_doctor(deep=False):
    """Exercise every subsystem. Never crashes; every check is isolated."""
    import importlib, inspect

    results = []
    def rec(name, status, detail=""):
        results.append((name, status, str(detail)))
    def safe(name, fn, required=False):
        try:
            detail = fn()
            rec(name, "ok", str(detail) if detail else "")
        except Exception as e:
            rec(name, "fail" if required else "warn",
                type(e).__name__ + ": " + str(e))
    def hr(t):
        print()
        print("  " + col(51) + t + RSTC)

    print()
    print("  " + col(201) + "DOCTOR" + RSTC + "   " + DIM +
          "(exercises every subsystem)" + RSTC)

    # environment
    hr("environment")
    def _env():
        i = probe()
        for k in ("os", "arch", "python", "cpu", "ram", "gpu", "disk"):
            rec("env." + k, "ok", str(i.get(k, "?")))
        return None
    safe("environment", _env)

    # paths
    hr("paths")
    for name in ("DATA_HOME","MODELS_D","CHATS_D","CTX_D","CACHE_D",
                 "TOOLS_D","PLUGINS_D","LOGS_D","BIN_D","DL_D"):
        p = globals().get(name)
        if p is None:
            rec("path." + name, "warn", "not defined")
            continue
        def _mk(p=p):
            p.mkdir(parents=True, exist_ok=True)
            f = p / ".doctor_test"
            f.write_text("x"); f.unlink()
            return str(p)
        safe("path." + name, _mk)
    for name in ("AGENT_D","AGENT_CHECKPOINT","AGENT_SCREENS","PLUGIN_TOOLS_D"):
        p = globals().get(name)
        if p is None:
            rec("path." + name, "warn", "not defined")
            continue
        def _mk(p=p):
            p.mkdir(parents=True, exist_ok=True)
            f = p / ".doctor_test"
            f.write_text("x"); f.unlink()
            return str(p)
        safe("path." + name, _mk)

    # python deps
    hr("python deps")
    for mod in ("llama_cpp","transformers","torch","onnxruntime",
                "optimum","pyautogui","mss","PIL","pygetwindow",
                "pytesseract","huggingface_hub"):
        def _imp(mod=mod):
            importlib.import_module(mod); return "installed"
        safe("dep." + mod, _imp)

    # parsers
    hr("parsers")
    import tempfile
    tmp = tempfile.mkdtemp(prefix="cs-doctor-")
    try:
        td = pathlib.Path(tmp)
        # gguf
        def _gguf():
            kv = (len(b"general.architecture").to_bytes(8,"little") +
                  b"general.architecture" + (8).to_bytes(4,"little") +
                  len(b"llama").to_bytes(8,"little") + b"llama")
            gg = td / "t.gguf"
            gg.write_bytes(b"GGUF" + (3).to_bytes(4,"little") +
                           (0).to_bytes(8,"little") +
                           (1).to_bytes(8,"little") + kv)
            g = parse_gguf(gg)
            if not (g and g["meta"].get("general.architecture") == "llama"):
                raise RuntimeError("parse mismatch")
            return None
        safe("parse.gguf", _gguf)
        # safetensors
        def _st():
            hdr = json.dumps({"w": {"dtype":"F32","shape":[2,2],
                                    "data_offsets":[0,16]}}).encode()
            st = td / "t.safetensors"
            st.write_bytes(len(hdr).to_bytes(8,"little") + hdr + b"\x00"*16)
            r = parse_safetensors(st)
            if not (r and r["ok"]):
                raise RuntimeError("parse failed")
            return None
        safe("parse.safetensors", _st)
    finally:
        try:
            import shutil as _sh
            _sh.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass

    # arch resolver
    hr("arch resolver")
    pairs = [("qwen35","Qwen3ForCausalLM"),("qwen2","Qwen2ForCausalLM"),
             ("bonsai","Qwen2ForCausalLM"),
             ("BonsaiForCausalLM","Qwen2ForCausalLM"),
             ("llama3","LlamaForCausalLM")]
    for inp, want in pairs:
        def _a(inp=inp, want=want):
            got = normalize_arch(inp)
            if got != want:
                raise RuntimeError("got " + got + " want " + want)
            return "-> " + got
        safe("arch." + inp, _a)

    # runtimes
    hr("runtimes")
    def _rts():
        for rt in all_runtimes():
            try:
                ok, h = rt.available()
                if rt.id == "llama-server" and not ok and _prism_server():
                    ok, h = True, "(prism fork)"
                if rt.id == "llama-cli" and not ok and _prism_cli():
                    ok, h = True, "(prism fork)"
                rec("runtime." + rt.id, "ok" if ok else "warn", h or "")
            except Exception as e:
                rec("runtime." + rt.id, "fail", str(e))
        return None
    safe("runtimes", _rts)

    # tools
    hr("agent tools")
    rec("tools.count", "ok", str(len(TOOLS_IMPL)) + " registered")
    for name, fn in sorted(TOOLS_IMPL.items()):
        def _sig(fn=fn):
            sig = inspect.signature(fn)
            if "args" not in sig.parameters:
                raise RuntimeError("missing args parameter")
            return None
        safe("tool." + name, _sig)

    # agent memory
    hr("agent memory")
    def _mem():
        m = _agent_mem_load()
        _agent_mem_add("note", "__doctor_test__")
        m2 = _agent_mem_load()
        if "__doctor_test__" not in m2.get("notes", []):
            raise RuntimeError("note not persisted")
        m2["notes"] = [n for n in m2["notes"] if n != "__doctor_test__"]
        _agent_mem_save(m2)
        return "notes=" + str(len(m.get("notes", [])))
    safe("mem.roundtrip", _mem)

    # checkpoints
    hr("checkpoints")
    def _ck():
        p = globals().get("AGENT_CHECKPOINT")
        if p is None: raise RuntimeError("AGENT_CHECKPOINT not defined")
        p.mkdir(parents=True, exist_ok=True)
        f = p / ("doctor_" + str(int(time.time())) + ".tmp")
        f.write_text("x")
        if not f.exists(): raise RuntimeError("write failed")
        f.unlink()
        return None
    safe("checkpoint.write", _ck)

    # network
    hr("network")
    for name, url in (("huggingface","https://huggingface.co"),
                      ("github","https://api.github.com")):
        def _net(url=url):
            with urllib.request.urlopen(url, timeout=6) as r:
                return "http " + str(r.status)
        safe("net." + name, _net)

    # hf_search
    hr("huggingface search")
    def _hfs():
        r = hf_search("llama", limit=2)
        return str(len(r)) + " results"
    safe("hf.search", _hfs)

    # models
    hr("local models")
    def _mods():
        recs = load_scan()
        by = {}
        for r in recs:
            by[r.kind] = by.get(r.kind, 0) + 1
        for k, v in by.items():
            rec("models." + k, "ok", str(v))
        return str(len(recs)) + " indexed"
    safe("models.scan", _mods)

    # serve
    hr("serve")
    def _srv():
        procs = _find_serve_procs()
        return str(len(procs)) + " process(es)"
    safe("serve.processes", _srv)
    rec("serve.handler", "ok" if "_ServeHandler" in globals() else "warn", "")

    # cli
    hr("cli")
    def _cli():
        ap = build_cli()
        sub = list(ap._subparsers._group_actions[0].choices.keys())
        return str(len(sub)) + " commands"
    safe("cli.subcommands", _cli)

    # coding agents
    hr("coding agents")
    for aid, a in AGENTS.items():
        def _ag(a=a):
            inst = agent_installed(a)
            if not inst:
                raise RuntimeError("not found")
            return "installed"
        safe("agent." + aid, _ag)

    # plugins
    hr("plugins")
    def _plugs():
        _load_plugin_tools()
        p = globals().get("PLUGIN_TOOLS_D")
        if p is None: raise RuntimeError("PLUGIN_TOOLS_D not defined")
        return str(len(list(p.glob("*.py")))) + " custom tool(s)"
    safe("plugins.load", _plugs)

    # ---- summary ----
    hr("summary")
    ok_n = sum(1 for _, st, _ in results if st == "ok")
    warn_n = sum(1 for _, st, _ in results if st == "warn")
    fail_n = sum(1 for _, st, _ in results if st == "fail")

    for name, status, detail in results:
        if status == "ok": icon = GR + "v" + RSTC
        elif status == "warn": icon = YL + "!" + RSTC
        else: icon = RD + "x" + RSTC
        line = "  " + icon + " " + name.ljust(30)
        if detail:
            line += " " + DIM + trunc(detail, 60) + RSTC
        print(line)

    print()
    print("  " + GR + str(ok_n) + " ok" + RSTC +
          "   " + YL + str(warn_n) + " warn" + RSTC +
          "   " + RD + str(fail_n) + " fail" + RSTC)
    if fail_n:
        print()
        print("  " + RD + "failing:" + RSTC)
        for name, status, detail in results:
            if status == "fail":
                print("    " + RD + "x" + RSTC + " " + name + "  " +
                      DIM + detail + RSTC)
    else:
        print("  " + GR + "  all checks passed" + RSTC)


def cmd_clean(downloads=False):
    for p in (SCAN_P, HASH_P, VER_P): p.unlink(missing_ok=True)
    if downloads and (DATA_HOME/"downloads").exists(): shutil.rmtree(DATA_HOME/"downloads", ignore_errors=True)
    print(GR + "  v caches cleared" + RSTC)

def cmd_plugin_init(name):
    PLUGINS_D.mkdir(parents=True, exist_ok=True)
    tpl = (
        "import cs_api\n\n"
        f"class {name.capitalize()}RT(cs_api.BaseRuntime):\n"
        f'    id = "{name}"\n'
        '    kinds = ("tf-dir","gguf")\n\n'
        '    def available(self): return True, ""\n\n'
        "    def can_run(self, rec):\n"
        '        return rec.arch == "MyArchForCausalLM" or rec.kind in self.kinds\n\n'
        "    def stream(self, rec, prompt, hist, ctx):\n"
        '        yield f"[{self.id}] {rec.name}"\n\n'
        f"cs_api.register({name.capitalize()}RT)\n"
    )
    (PLUGINS_D / f"{name}.py").write_text(tpl, encoding="utf-8")
    print(GR + f"  v {PLUGINS_D / (name + '.py')}" + RSTC)

def cmd_bonsai_setup():
    print(YL + "  BONSAI / PRISM" + RSTC)
    print(f"  server : {_prism_server() or 'NOT FOUND'}")
    print(f"  cli    : {_prism_cli() or 'NOT FOUND'}")
    recs = [r for r in load_scan() if needs_prism_fork(r)]
    print(YL + f"  TERNARY ({len(recs)})" + RSTC)
    for r in recs:
        rt = pick_runtime(r)
        print(f"  {GR}◆{RSTC} {trunc(r.name, 52):52} {DIM}{rt.id if rt else 'no runtime'}{RSTC}")

def cmd_ll_log(lines=80):
    logs = sorted(LOGS_D.glob("llama-server-*.log"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs: print(DIM + "  no logs" + RSTC); return
    p = logs[0]; print(YL + "  " + str(p) + RSTC)
    try:
        for l in p.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]:
            print("  " + l)
    except Exception as e: print(RD + "  " + str(e) + RSTC)

def cmd_export(archive=None):
    """Package cs.py + cs_data into a portable zip."""
    here = Path(__file__).resolve().parent
    if archive is None:
        archive = here / f"cs-portable-{_dt.date.today().isoformat()}.zip"
    archive = Path(archive)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(Path(__file__).resolve(), "cs.py")
        for f in DATA_HOME.rglob("*"):
            if f.is_file() and not any(x in f.parts for x in ("tools","downloads","cache")):
                try: z.write(f, str(Path("cs_data") / f.relative_to(DATA_HOME)))
                except Exception: pass
    print(GR + f"  v wrote {archive}" + RSTC)
    print(DIM + "  extract anywhere, run: python cs.py" + RSTC)

# ─── selftest ──────────────────────────────────────────────────────────────
def selftest():
    passed = failed = 0
    def t(name, cond):
        nonlocal passed, failed
        if cond: passed += 1; print(GR + f"  v {name}" + RSTC)
        else: failed += 1; print(RD + f"  x {name}" + RSTC)
    tmp = Path(tempfile.mkdtemp(prefix="cs-test-"))
    t("qwen35→Qwen3", normalize_arch("qwen35") == "Qwen3ForCausalLM")
    t("bonsai→Qwen2", normalize_arch("bonsai") == "Qwen2ForCausalLM")
    t("BonsaiForCausalLM→Qwen2", normalize_arch("BonsaiForCausalLM") == "Qwen2ForCausalLM")
    t("empty→?", normalize_arch("") == "?")
    t("chain has Auto", "AutoModelForCausalLM" in arch_chain("bonsai"))
    def kv(k, v):
        return len(k).to_bytes(8,"little") + k + (8).to_bytes(4,"little") + len(v).to_bytes(8,"little") + v
    gg = tmp/"t.gguf"
    gg.write_bytes(b"GGUF" + (3).to_bytes(4,"little") + (0).to_bytes(8,"little") + (2).to_bytes(8,"little") + kv(b"general.architecture", b"qwen35") + kv(b"general.name", b"bonsai-2"))
    g = parse_gguf(gg)
    t("gguf parse", bool(g) and g["meta"].get("general.architecture") == "qwen35")
    t("gguf arch", _arch_from_gguf(g) == "Qwen3ForCausalLM")
    hdr = json.dumps({"w":{"dtype":"F32","shape":[2,2],"data_offsets":[0,16]},"__metadata__":{"format":"pt"}}).encode()
    st = tmp/"t.safetensors"; st.write_bytes(len(hdr).to_bytes(8,"little") + hdr + b"\x00"*16)
    s = parse_safetensors(st)
    t("safetensors", bool(s) and s["tensors"] == 1 and s["ok"])
    abc = tmp/"abc"; abc.write_bytes(b"abc")
    t("sha256 vector", sha256_file(abc).startswith("ba7816bf"))
    rows = render_logo(15)
    t("logo rows", len(rows) == 15 and all(len(r) == len(rows[0]) for r in rows))
    t("table", "NAME" in table([["x"]],["NAME"]))
    t("human", human(2**30) == "1.00GB")
    t("fuzzy", fuzzy("bns2","bonsai-2"))
    rec = ModelRec("t.gguf", gg, "gguf", gg.stat().st_size, "Qwen3ForCausalLM")
    _, ok = verify_rec(rec, deep=True)
    t("verify gguf", ok)
    cp = tmp/"c.json"; jsave(cp, {"a":1})
    t("config roundtrip", jload(cp, {}) == {"a":1})
    t("context default", "n_ctx" in DEFAULT_CONTEXT)
    calls = _TOOL_RX.findall('x <tool>{"name":"bash","args":{"cmd":"ls"}}</tool> y')
    t("tool regex", len(calls) == 1)
    shutil.rmtree(tmp, ignore_errors=True)
    print(GR + f"  {passed} passed" + RSTC + (RD + f", {failed} failed" + RSTC if failed else ""))
    return 1 if failed else 0

# ─── CLI ───────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(prog=APP, description=f"{APP_LONG} — portable model runner")
    sub = ap.add_subparsers(dest="cmd")
    sp = sub.add_parser("setup"); sp.add_argument("--full", action="store_true"); sp.add_argument("--quiet", action="store_true")
    sub.add_parser("install-self")
    fx = sub.add_parser("fix")
    fx.add_argument("--apply", action="store_true")
    sub.add_parser("scan"); sub.add_parser("list"); dp = sub.add_parser("doctor"); dp.add_argument("--deep", action="store_true")
    sub.add_parser("selftest"); sub.add_parser("logo")
    sub.add_parser("bonsai-setup"); sub.add_parser("ll-log")
    v = sub.add_parser("verify"); v.add_argument("query", nargs="?"); v.add_argument("--deep", action="store_true"); v.add_argument("--online", action="store_true")
    r = sub.add_parser("run"); r.add_argument("model", nargs="?"); r.add_argument("-p","--prompt", default=None)
    c = sub.add_parser("chat"); c.add_argument("model", nargs="?"); c.add_argument("--incognito", action="store_true")
    sub.add_parser("incognito").add_argument("model", nargs="?")
    cd = sub.add_parser("code"); cd.add_argument("model", nargs="?"); cd.add_argument("--cwd", default=None)
    b = sub.add_parser("bench"); b.add_argument("model"); b.add_argument("-n","--tokens", type=int, default=128)
    i = sub.add_parser("install"); i.add_argument("target")
    ct = sub.add_parser("ctx"); ct.add_argument("model")
    sv = sub.add_parser("serve"); sv.add_argument("--host", default="127.0.0.1"); sv.add_argument("--port", type=int, default=8686); sv.add_argument("--model", default=None)
    ag = sub.add_parser("agents"); ag.add_argument("action", nargs="?", default="list", choices=["list","install","launch"]); ag.add_argument("agent", nargs="?"); ag.add_argument("--model", default=None)
    pi = sub.add_parser("plugin-init"); pi.add_argument("name")
    cl = sub.add_parser("clean"); cl.add_argument("--downloads", action="store_true")
    ex = sub.add_parser("export")
    sub.add_parser("chatgpt").add_argument("model", nargs="?")
    sub.add_parser("claude").add_argument("model", nargs="?")
    sub.add_parser("opencode").add_argument("model", nargs="?"); ex.add_argument("archive", nargs="?")
    a = ap.parse_args()

    if a.cmd == "install-self": install_self(); return
    if a.cmd == "logo": show_logo(); return
    if a.cmd == "selftest": sys.exit(selftest())
    if a.cmd != "setup" and not CFG.get("setup_done"):
        print(YL + "first launch — running setup" + RSTC); setup(); print()
    if a.cmd is None: chooser(); return

    if a.cmd == "setup": setup(a.full, a.quiet)
    elif a.cmd == "scan": cmd_scan()
    elif a.cmd == "list": cmd_list()
    elif a.cmd == "chatgpt":
        cmd_chatgpt(a.model)
    elif a.cmd == "claude":
        cmd_claude(a.model)
    elif a.cmd == "opencode":
        cmd_opencode(a.model)
    elif a.cmd == "unconnect":
        cmd_unconnect(a.target)
    elif a.cmd == "menu":
        menu_main()
    elif a.cmd == "explore":
        cmd_explore()
    elif a.cmd == "health":
        cmd_health()
    elif a.cmd == "hex":
        cmd_cs_agent()
    elif a.cmd == "model":
        cmd_model(getattr(a, "name", None))
    elif a.cmd == "config":
        cmd_config()
    elif a.cmd == "perms":
        cmd_perms()
    elif a.cmd == "settings":
        menu_settings()
    elif a.cmd == "agent":
        cmd_cs_agent()
    elif a.cmd == "stop":
        cmd_stop()
    elif a.cmd == "screen":
        cmd_screen()
    elif a.cmd == "click":
        cmd_click(a.x, a.y, getattr(a,"button","left"), getattr(a,"clicks",1))
    elif a.cmd == "move":
        cmd_move(a.x, a.y)
    elif a.cmd == "drag":
        cmd_drag(a.x1, a.y1, a.x2, a.y2)
    elif a.cmd == "type":
        cmd_type(a.text)
    elif a.cmd == "key":
        cmd_key(a.keys)
    elif a.cmd == "scroll":
        cmd_scroll(a.amount)
    elif a.cmd == "windows":
        cmd_windows()
    elif a.cmd == "focus":
        cmd_focus(a.title)
    elif a.cmd == "app":
        cmd_app(a.name, a.args)
    elif a.cmd == "ocr":
        cmd_ocr(getattr(a,"path",None))
    elif a.cmd == "size":
        cmd_size()
    elif a.cmd == "fix":
        cmd_fix(getattr(a, "apply", False))
    elif a.cmd == "venvs":
        cmd_venvs()
    elif a.cmd == "venv-repair":
        cmd_venv_repair(getattr(a, "name", None))
    elif a.cmd == "locate":
        cmd_locate(getattr(a, "agent", None))
    elif a.cmd == "run-agent":
        cmd_run_agent(getattr(a, "agent", None), getattr(a, "model", None))
    elif a.cmd == "auto-ctx":
        cmd_auto_ctx(getattr(a, "value", None))
    elif a.cmd == "doctor": cmd_doctor()
    elif a.cmd == "bonsai-setup": cmd_bonsai_setup()
    elif a.cmd == "ll-log": cmd_ll_log()
    elif a.cmd == "verify": cmd_verify(a.query, a.deep, a.online)
    elif a.cmd == "run": cmd_run(a.model, a.prompt)
    elif a.cmd == "chat": cmd_chat(a.model, a.incognito)
    elif a.cmd == "incognito": cmd_incognito(a.model)
    elif a.cmd == "code": cmd_code(a.model, a.cwd)
    elif a.cmd == "bench": cmd_bench(a.model, a.tokens)
    elif a.cmd == "install": install_target(a.target)
    elif a.cmd == "ctx":
        rec = match_model(a.model)
        if rec: edit_context(rec)
        else: print(RD + f"no match: {a.model}" + RSTC)
    elif a.cmd == "serve": cmd_serve(a.host, a.port, a.model)
    elif a.cmd == "agents": cmd_agents(a.action, a.agent, a.model)
    elif a.cmd == "plugin-init": cmd_plugin_init(a.name)
    elif a.cmd == "clean": cmd_clean(a.downloads)
    elif a.cmd == "export": cmd_export(a.archive)
    else: ap.print_help()


# === CS-CANONICAL-BEGIN ===
# Managed by repair scripts. Everything between the markers is regenerated.
# Do not edit inside the markers; edits will be lost on the next repair.

# ---------- TUI helpers ----------
def _vlen(s):
    return len(re.sub(r"\x1b\[[0-9;]*m", "", str(s)))


def _cell(text, width):
    text = str(text)
    v = _vlen(text)
    if v == width:
        return text
    if v < width:
        return text + " " * (width - v)
    out = []
    seen = 0
    i = 0
    while i < len(text) and seen < width:
        if text[i] == "\x1b":
            j = i + 1
            while j < len(text) and text[j] != "m" and (j - i) < 12:
                j += 1
            j += 1
            out.append(text[i:j])
            i = j
            continue
        out.append(text[i])
        seen += 1
        i += 1
    out.append("\x1b[0m")
    return "".join(out)


def _read_key():
    if not sys.stdin.isatty():
        try:
            return (input().strip() or "enter")
        except (EOFError, KeyboardInterrupt):
            return "esc"
    try:
        if os.name == "nt":
            import msvcrt
            ch = msvcrt.getch()
            if ch in (b"\x00", b"\xe0"):
                ch2 = msvcrt.getch()
                return {b"H": "up", b"P": "down", b"K": "left",
                        b"M": "right"}.get(ch2, "")
            if ch in (b"\r", b"\n"):
                return "enter"
            if ch == b"\x1b":
                return "esc"
            if ch == b"\x03":
                raise KeyboardInterrupt
            if ch == b"\x08":
                return "bs"
            try:
                return ch.decode("utf-8", "replace").lower()
            except Exception:
                return ""
        else:
            import termios, tty
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                ch = sys.stdin.read(1)
                if ch == "\x1b":
                    nxt = sys.stdin.read(1)
                    if nxt == "[":
                        c3 = sys.stdin.read(1)
                        return {"A": "up", "B": "down", "C": "right",
                                "D": "left"}.get(c3, "esc")
                    return "esc"
                if ch in ("\r", "\n"):
                    return "enter"
                if ch in ("\x7f", "\b"):
                    return "bs"
                if ch == "\x03":
                    raise KeyboardInterrupt
                return ch.lower()
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except KeyboardInterrupt:
        raise
    except Exception:
        try:
            return (input().strip() or "enter")
        except (EOFError, KeyboardInterrupt):
            return "esc"


def safe_call(fn_name, *args, **kwargs):
    fn = globals().get(fn_name)
    if fn is None or not callable(fn):
        print()
        print(RD + "  x " + fn_name + " is not available" + RSTC)
        print(DIM + "    try: cs fix --apply" + RSTC)
        print()
        try: input(DIM + "  Enter to continue" + RSTC)
        except Exception: pass
        return None
    try:
        return fn(*args, **kwargs)
    except KeyboardInterrupt:
        print()
        return None
    except Exception as e:
        import traceback as _tb
        print()
        print(RD + "  x " + fn_name + ": " + type(e).__name__ +
              ": " + str(e) + RSTC)
        log(fn_name + ": " + _tb.format_exc(), "error")
        try: input(DIM + "  Enter to continue" + RSTC)
        except Exception: pass
        return None


# ---------- chat history preview ----------
def _load_chat_preview(rec, limit=10):
    try:
        fp = CHATS_D / (rec.slug() + ".jsonl")
        if not fp.exists():
            return []
        lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        out = []
        for ln in lines:
            try:
                o = json.loads(ln)
                text = re.sub(r"\s+", " ", str(o.get("content", ""))).strip()
                if text:
                    out.append((o.get("role", "?"), text))
            except Exception:
                continue
        return out
    except Exception:
        return []


# ---------- agent memory ----------
def _agent_mem_load():
    try:
        return jload(AGENT_MEM, {"facts": [], "notes": [], "tools": []})
    except Exception:
        return {"facts": [], "notes": [], "tools": []}


def _agent_mem_save(m):
    try: jsave(AGENT_MEM, m)
    except Exception: pass


def _agent_mem_add(kind, text):
    try:
        m = _agent_mem_load()
        if kind == "note":
            m.setdefault("notes", []).append(str(text)[:1000])
        elif kind == "tool":
            arr = m.setdefault("tools", [])
            if text not in arr: arr.append(str(text))
        for k in ("notes", "facts", "tools"):
            m[k] = m.get(k, [])[-200:]
        _agent_mem_save(m)
    except Exception:
        pass


def _agent_log(entry):
    try:
        AGENT_D.mkdir(parents=True, exist_ok=True)
        with open(AGENT_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass


# ---------- agent system prompt + dispatch tables ----------
CS_AGENT_SYSTEM = (
    "You are the Hex Agent inside CS Framework. You solve tasks on the user's machine.\n\n"
    "## Tools\n\n"
    "Emit one JSON object per line inside <tool>...</tool>:\n"
    "<tool>{\"name\":\"bash\",\"args\":{\"cmd\":\"ls\"}}</tool>\n\n"
    "Wait for the <tool_result>...</tool_result> before continuing.\n\n"
    "## Persistence\n\n"
    "Save a reusable tool:\n"
    "<define_tool>{\"name\":\"mytool\",\"desc\":\"what it does\",\"code\":\"def run(args, cwd=None): return ''\"}</define_tool>\n"
    "The code must define run(args, cwd=None) -> str.\n\n"
    "Save a note:\n"
    "<memory>{\"note\":\"this project uses pytest\"}</memory>\n\n"
    "Maintain a task list:\n"
    "<todo>{\"items\":[{\"task\":\"read config\",\"done\":false}]}</todo>\n\n"
    "## Computer use\n\n"
    "Tools: screen, screen_size, mouse_move, mouse_click, mouse_drag, scroll,\n"
    "key, type, window_list, window_focus, app_start, sleep, ocr.\n\n"
    "## Rules\n\n"
    "- Read before you write.\n"
    "- Small steps; test as you go.\n"
    "- Update <todo> when the plan changes.\n"
    "- When done, reply normally with no tool block."
)

_HEX_COMMANDS = {
    "/help":          "show this list",
    "/continue":      "force another model turn without a new prompt",
    "/tools":         "list all callable tools",
    "/memory":        "saved notes + custom tools",
    "/scratch":       "view removable context (auto memory)",
    "/scratch-clear": "wipe removable context",
    "/context":       "show context settings",
    "/clear":         "reset conversation history",
    "/dir <path>":    "change working directory",
    "/exit":          "quit",
}


def _hex_list_commands(prefix=None):
    print()
    print("  " + col(51) + "commands" + RSTC)
    for cmd in sorted(_HEX_COMMANDS):
        if prefix and prefix not in ("/", "") and not cmd.startswith(prefix):
            continue
        print("    " + col(51) + cmd.ljust(18) + RSTC +
              DIM + _HEX_COMMANDS[cmd] + RSTC)
    print()


def _hex_handle_slash(line, ctx, hist, cwd):
    s = line.strip()
    first = s.split()[0] if s else ""
    if first not in _HEX_COMMANDS:
        if s.startswith("/"):
            _hex_list_commands(prefix=first)
            return True, cwd
        return False, cwd
    if first in ("/exit", "/quit", "/q"):
        return "exit", cwd
    if first == "/continue":
        return "continue", cwd
    if first == "/help":
        _hex_list_commands()
        return True, cwd
    if first == "/tools":
        print()
        for n in sorted(TOOLS_IMPL):
            print("    " + col(51) + "*" + RSTC + " " + n)
        print()
        return True, cwd
    if first == "/memory":
        m = _agent_mem_load()
        print()
        if not m.get("notes") and not m.get("tools"):
            print(DIM + "  (empty)" + RSTC)
        for n in m.get("notes", [])[-30:]:
            print("    " + DIM + "|" + RSTC + " " + n)
        if m.get("tools"):
            print()
            print("    " + col(51) + "custom tools:" + RSTC + " " +
                  ", ".join(m["tools"]))
        print()
        return True, cwd
    if first == "/context":
        print()
        for k in sorted(ctx):
            if k == "system":
                continue
            print("    " + DIM + k.ljust(18) + RSTC +
                  trunc(str(ctx[k]), 60))
        print()
        return True, cwd
    if first == "/scratch":
        txt = _scratch_load(max_lines=60)
        print()
        if txt:
            for ln in txt.splitlines():
                print("    " + DIM + "|" + RSTC + " " + ln)
        else:
            print(DIM + "  (removable context empty)" + RSTC)
        print()
        return True, cwd
    if first == "/scratch-clear":
        _scratch_clear()
        print(GR + "  removable context cleared" + RSTC)
        return True, cwd
    if first == "/clear":
        hist.clear()
        print(DIM + "  history cleared" + RSTC)
        return True, cwd
    if first == "/dir":
        parts = s.split(maxsplit=1)
        if len(parts) < 2:
            print(RD + "  usage: /dir <path>" + RSTC)
            return True, cwd
        nd = parts[1].strip()
        if Path(nd).exists():
            print(GR + "  cwd -> " + nd + RSTC)
            return True, nd
        print(RD + "  no such directory" + RSTC)
        return True, cwd
    return True, cwd
def _hex_header(model_name, cwd, ctx, mem, tools_n):
    print()
    print("  " + col(51) + "\u2500" * 66 + RSTC)
    print("  " + col(201) + AGENT_NAME + RSTC + "  " +
          DIM + "self-improving coding agent" + RSTC)
    print("  " + col(51) + "\u2500" * 66 + RSTC)
    print("  " + DIM + "model" + RSTC + " " + trunc(model_name, 58))
    print("  " + DIM + "cwd  " + RSTC + " " + trunc(cwd, 58))
    print("  " + DIM + "ctx  " + RSTC + " " +
          str(ctx.get("n_ctx", "?")) + "  max " +
          str(ctx.get("max_new_tokens", "?")) +
          "  tools " + str(tools_n) +
          "  notes " + str(len(mem.get("notes", []))))
    print("  " + col(51) + "\u2500" * 66 + RSTC)
    print()


def _hex_stream_buffered(rec, rt, hist, ctx):
    prompt = build_prompt(hist, ctx)
    buf = []
    try:
        for chunk in rt.stream(rec, prompt, hist, ctx):
            buf.append(chunk)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        buf.append("\n[runtime error: " + str(e) + "]")
    return "".join(buf)


_SPECIAL_RX = re.compile(
    r"<tool>.*?</tool>|<define_tool>.*?</define_tool>|<memory>.*?</memory>",
    re.S)


def _strip_special(text):
    return _SPECIAL_RX.sub("", text).strip()


def _clean_display(text):
    return re.sub(r"[ \t]{3,}", " ", text)


def _hex_agent(rec, rt, cwd, ctx):
    hist = []
    todos = []
    m = _agent_mem_load()

    # assemble system prompt
    mem_txt = ""
    if m.get("notes"):
        mem_txt = "\nMemory:\n" + "\n".join(
            "- " + str(n)[:200] for n in m["notes"][-10:])
    scratch_txt = _scratch_load(max_lines=25)
    scratch_block = ""
    if scratch_txt:
        scratch_block = "\nRemovable context (recent work):\n" + scratch_txt + "\n"

    ctx = dict(ctx)
    ctx["system"] = CS_AGENT_SYSTEM + mem_txt + scratch_block
    ctx["max_new_tokens"] = max(2048, ctx.get("max_new_tokens", 512))

    clearscr()
    try:
        rows = render_logo(8)
        for i, rw in enumerate(rows):
            print(grad(i / max(len(rows), 1)) + rw + RSTC)
    except Exception:
        pass
    _hex_header(rec.name, cwd, ctx, m, len(TOOLS_IMPL))
    print("  " + DIM + "type / for commands   /tools  /memory  /scratch  "
                "/continue  /exit" + RSTC)
    print()

    force_more = False

    while True:
        try:
            if force_more:
                line = "/continue"
                force_more = False
            else:
                line = input(col(201) + "  " + AGENT_PROMPT + RSTC)
        except (EOFError, KeyboardInterrupt):
            print()
            break
        s = line.strip()
        if not s:
            continue

        if s.startswith("/"):
            handled, cwd = _hex_handle_slash(s, ctx, hist, cwd)
            if handled == "exit":
                break
            if handled == "continue":
                # don't append a message, just force another model turn
                if not hist:
                    print(DIM + "  (no history to continue)" + RSTC)
                    continue
                # inject a nudge that only the model sees
                hist.append({"role": "user",
                             "content": "(continue — you may still have work to do. "
                                        "Use tools as needed. If the task is "
                                        "finished, reply normally with no tool blocks.)"})
            else:
                continue
        else:
            hist.append({"role": "user", "content": s})
            _scratch_append("user", s)
            try: _agent_log({"ts": time.time(), "role": "user", "text": s})
            except Exception: pass

        # ----- one full agent turn (may loop many times) -----
        MAX_INNER = 40
        rounds_without_tool = 0
        for _round in range(MAX_INNER):
            print()
            print("  " + col(201) + "\u25c6 hex" + RSTC + DIM +
                  "  thinking..." + RSTC)
            raw = _hex_stream_buffered(rec, rt, hist, ctx)
            hist.append({"role": "assistant", "content": raw})
            try: _agent_log({"ts": time.time(), "role": "assistant", "text": raw})
            except Exception: pass

            # tasks
            for tm in re.findall(r"<todo>\s*(\{.*?\})\s*</todo>", raw, re.S):
                try:
                    obj = json.loads(tm)
                    if isinstance(obj.get("items"), list):
                        todos = obj["items"]
                except Exception:
                    pass

            # run tools
            tool_results, had_tool = run_tool_blocks(raw, cwd=cwd)
            define_results, had_def = _handle_define_tools(raw)
            try: saved = _handle_memories(raw)
            except Exception: saved = 0

            # display
            print("\r" + " " * 40 + "\r", end="")
            print("  " + col(201) + "\u25c6 hex" + RSTC)
            display = _clean_display(_strip_special(raw))
            display = re.sub(r"<todo>.*?</todo>", "", display, flags=re.S).strip()
            if display:
                for ln in display.splitlines():
                    print("    " + ln)
                # log compact to scratchpad
                _scratch_append("hex", display)
            elif not (had_tool or had_def or saved):
                print("    " + DIM + "(no output)" + RSTC)

            for r in define_results:
                if r.startswith("[defined tool:"):
                    print("  " + col(47) + "\u25c6 tool" + RSTC + "    " +
                          r[1:-1])
                    _scratch_append("tool", r[1:-1])
            if saved:
                print("  " + col(51) + "\u25c6 memory" + RSTC +
                      "  saved " + str(saved))
            if todos:
                done = sum(1 for td in todos if td.get("done"))
                print("  " + col(51) + "\u25c6 todo" + RSTC + "    " +
                      str(done) + "/" + str(len(todos)) + " done")

            if had_tool:
                names = re.findall(
                    r'<tool>\s*\{[^}]*"name"\s*:\s*"([^"]+)"', raw)
                for i, tr in enumerate(tool_results):
                    tn = names[i] if i < len(names) else "?"
                    print()
                    print("  " + col(201) + "\u2699 " + tn + RSTC)
                    body = tr if tr else "(no output)"
                    for ln in body.splitlines()[:40]:
                        print("    " + DIM + "\u2506 " + RSTC + ln[:200])
                    if len(body.splitlines()) > 40:
                        print("    " + DIM + "\u2506 (...)" + RSTC)
                    hist.append({
                        "role": "user",
                        "content": "<tool_result>\n" +
                                   tr[:MAX_TOOL_OUTPUT] + "\n</tool_result>",
                    })
                    _scratch_append("tool", tn + " \u2192 " +
                                    body.splitlines()[0][:120] if body else tn)

            # loop control
            if not (had_tool or had_def):
                rounds_without_tool += 1
                if rounds_without_tool >= 2:
                    break
            else:
                rounds_without_tool = 0

            # every ~10 rounds, snapshot to scratchpad
            if _round and _round % 10 == 0:
                _scratch_compact(220)
                _scratch_append("checkpoint",
                                "round " + str(_round) + " done")

        _scratch_compact(220)
        if len(hist) > MAX_HISTORY * 4:
            hist = hist[-MAX_HISTORY * 4:]

def _launch_hex(rec, seed=None):
    rt = pick_runtime(rec)
    if not rt:
        print(RD + "  no runtime for " + rec.name + RSTC)
        print(DIM + "    try: cs install llamacpp-bin" + RSTC)
        try: input(DIM + "  Enter" + RSTC)
        except Exception: pass
        return
    try:
        cwd = os.getcwd()
        ctx = get_context(rec)
        if seed:
            try:
                hist = [{"role": "user", "content": seed}]
                _ = _hex_stream_buffered(rec, rt, hist, ctx)  # warm
            except Exception:
                pass
        _hex_agent(rec, rt, cwd, ctx)
    except Exception as e:
        import traceback as _tb
        print()
        print(RD + "  agent error: " + type(e).__name__ + ": " + str(e) + RSTC)
        log("launch_hex: " + _tb.format_exc(), "error")
        try: input(DIM + "  Enter" + RSTC)
        except Exception: pass


# ---------- dashboard ----------
def _draw_dashboard(recs, procs, info, sel, prompt_buf):
    clearscr()
    total = 90
    try:
        import shutil as _sh
        total = max(72, min(_sh.get_terminal_size((90, 24)).columns - 1, 118))
    except Exception:
        pass

    logo = []
    try: logo = render_logo(8)
    except Exception: pass
    pad_l = max(0, (total - (len(logo[0]) if logo else 0)) // 2)
    for i, rw in enumerate(logo):
        print(" " * pad_l + grad(i / max(len(logo), 1)) + rw + RSTC)
    print()
    print("  " + col(201) + "C S   F R A M E W O R K" + RSTC +
          "   " + DIM + "v" + VERSION + "  \u00b7  " + CODENAME + RSTC)

    gpu = str(info.get("gpu", "cpu-only"))
    if "CUDA:" in gpu:
        gpu = gpu.split("CUDA:", 1)[1].strip().split(",")[0].strip()
    print("  " + DIM + "models " + RSTC + GR + str(len(recs)) + RSTC +
          "  " + DIM + "servers " + RSTC + GR + str(len(procs)) + RSTC +
          "  " + DIM + "gpu " + RSTC + trunc(gpu, 26) + RSTC)
    print()

    L = 28
    R = total - L - 5
    if R < 34:
        R = 34
        L = max(20, total - R - 5)

    print("  " + col(51) + "\u256d" + "\u2500" * L + "\u252c" +
          "\u2500" * R + "\u256e" + RSTC)
    print("  " + col(51) + "\u2502" + RSTC +
          _cell(" " + col(201) + "M O D E L S" + RSTC, L) +
          col(51) + "\u2502" + RSTC +
          _cell(" " + col(201) + "C H A T" + RSTC, R) +
          col(51) + "\u2502" + RSTC)
    print("  " + col(51) + "\u251c" + "\u2500" * L + "\u253c" +
          "\u2500" * R + "\u2524" + RSTC)

    right = []
    if recs and 0 <= sel < len(recs):
        cur = recs[sel]
        rt = pick_runtime(cur)
        rt_tag = rt.id if rt else "no runtime"
        right.append(" " + col(47) + trunc(cur.name, R - 4) + RSTC)
        right.append(" " + DIM + "kind " + RSTC + cur.kind +
                     "   " + DIM + "arch " + RSTC +
                     trunc(arch_disp(cur.arch), R - 24))
        right.append(" " + DIM + "size " + RSTC + human(cur.size) +
                     "   " + DIM + "rt " + RSTC + rt_tag)
        right.append(" " + DIM + "\u2500" * (R - 2) + RSTC)
        hist = _load_chat_preview(cur, limit=12)
        if not hist:
            right.append(" " + DIM + "(no chat history yet)" + RSTC)
            right.append(" " + DIM + "press Enter to start Hex Agent" + RSTC)
        else:
            for role, text in hist:
                prefix = "you  " if role == "user" else "hex  "
                pcol = CY if role == "user" else MG
                avail = R - 8
                right.append(" " + pcol + prefix + RSTC +
                             DIM + text[:avail] + RSTC)
                rest = text[avail:]
                while rest and len(right) < 20:
                    right.append(" " + DIM + "     " +
                                 rest[:avail - 5] + RSTC)
                    rest = rest[avail - 5:]
    else:
        right.append(" " + YL + "no models installed" + RSTC)
        right.append(" " + DIM + "press E to explore huggingface" + RSTC)

    ROWS = 18
    half = ROWS // 2
    start = max(0, sel - half)
    end = min(len(recs), start + ROWS)
    if end - start < ROWS:
        start = max(0, end - ROWS)
    vc = jload(VER_P, {})

    for row in range(ROWS):
        i = start + row
        if i < len(recs):
            r = recs[i]
            st = vc.get(str(r.path), {})
            mk = (GR + "\u2713" + RSTC if st.get("ok") else
                  RD + "\u2717" + RSTC if st else DIM + "\u00b7" + RSTC)
            arrow = ">" if i == sel else " "
            name = trunc(r.name, L - 9)
            inner = " " + arrow + mk + " [" + str(i).rjust(2) + "] " + name
            lcell = _cell(inner, L)
            if i == sel:
                lcell = col(238) + lcell + RSTC
        else:
            lcell = _cell("", L)

        rline = right[row] if row < len(right) else ""
        rcell = _cell(rline, R)

        print("  " + col(51) + "\u2502" + RSTC + lcell +
              col(51) + "\u2502" + RSTC + rcell +
              col(51) + "\u2502" + RSTC)

    print("  " + col(51) + "\u2570" + "\u2500" * L + "\u2534" +
          "\u2500" * R + "\u256f" + RSTC)
    print()

    def key(k, v, color=None):
        return (col(51) + "[" + RSTC + col(238) + k + RSTC +
                col(51) + "]" + RSTC + " " + (color or GR) + v + RSTC)
    print("  " + "  ".join([
        key("\u2191\u2193", "select"),
        key("Enter", "hex agent", MG),
        key("C", "chat"),
        key("E", "explore"),
        key("M", "models"),
        key("A", "agents"),
    ]))
    print("  " + "  ".join([
        key("H", "health"),
        key("R", "computer"),
        key("G", "rig"),
        key("K", "settings"),
        key("Q", "quit", RD),
    ]))
    print()
    if prompt_buf:
        print("  " + col(201) + AGENT_PROMPT + RSTC + prompt_buf +
              col(201) + "_\x1b[0m" + RSTC)
    else:
        print("  " + col(201) + AGENT_PROMPT + RSTC + DIM +
              "type a message + Enter, or bare Enter for Hex Agent" + RSTC)


def _menu_simple_fallback():
    while True:
        recs = load_scan()
        print()
        print("  " + col(201) + "CS Framework" + RSTC)
        if recs:
            for i, r in enumerate(recs[:20]):
                rt = pick_runtime(r)
                print("  [" + str(i).rjust(2) + "] " + trunc(r.name, 50) +
                      "  " + (rt.id if rt else "no runtime"))
        else:
            print(DIM + "  (no models)" + RSTC)
        print("  " + DIM + "[num] chat  [e]xplore  [m]odels  [a]gents  "
                    "[h]ealth  [q]uit" + RSTC)
        try: c = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt): return
        if c == "q": return
        if c == "e": safe_call("cmd_explore"); continue
        if c == "m": safe_call("menu_models"); continue
        if c == "a": safe_call("menu_agents"); continue
        if c == "h": safe_call("cmd_health"); continue
        try:
            _launch_hex(recs[int(c)])
        except Exception:
            pass




def _preflight_venvs():
    """If transformers locally is version-broken, auto-rebuild the venv."""
    try:
        import transformers  # noqa
        import tokenizers  # noqa
        # both importable — check the version pairing
        try:
            from transformers.utils import is_tokenizers_available
            is_tokenizers_available()  # raises if broken
        except Exception:
            pass
        return
    except Exception as e:
        msg = str(e)
        if "tokenizers" in msg.lower() or "version" in msg.lower():
            print(YL + "  transformers is version-broken: " + msg[:120] + RSTC)
            print(DIM + "  auto-repairing in a throwaway venv (one-time)..."
                        + RSTC)
            try:
                _venv_ensure("transformers", force=True)
            except Exception as e2:
                print(RD + "  venv repair failed: " + str(e2) + RSTC)



def _is_chat_model(rec):
    """Rough filter: exclude TTS, ASR, embedding, masked-LM models."""
    arch = getattr(rec, "arch", "") or ""
    name = (getattr(rec, "name", "") or "").lower()
    # non-chat archs by name pattern
    bad_archs = (
        "forctc", "formaskedlm", "fortexttospeech", "foraudioclassification",
        "forconditionalgeneration", "forsequenceclassification",
        "forpretraining", "forquestionanswering", "fortokenclassification",
        "forimageclassification", "forobjectdetection",
        "hifigan", "vocoder", "whisper", "wav2vec", "hubert",
        "sentence_transformer", "embedding",
    )
    a = arch.lower()
    for pat in bad_archs:
        if pat in a:
            return False
    # obvious non-chat names
    for kw in ("tts", "texttospeech", "whisper", "wav2vec", "embedding",
               "distilbert", "speecht5", "vocoder", "stable-diffusion",
               "clip-", "clip_", "controlnet", "vae", "rvc-"):
        if kw in name:
            return False
    # ? arch is suspicious — if we can't identify it, skip for tf-dir
    if rec.kind == "tf-dir" and arch in ("", "?"):
        return False
    return True


def _chat_models(recs):
    out = []
    for r in recs:
        try:
            if _is_chat_model(r):
                out.append(r)
        except Exception:
            out.append(r)
    return out

def menu_main():
    try: _auto_fix(silent=True)
    except Exception: pass
    sel = 0
    prompt_buf = ""
    while True:
        try:
            recs_all = load_scan()
            procs = _find_serve_procs()
            info = probe()
            # filter to chat-capable models for the picker
            recs = _chat_models(recs_all) if recs_all else []
            if not recs:
                recs = recs_all  # fallback: show everything if filter is empty
            if recs:
                sel = max(0, min(sel, len(recs) - 1))
            _draw_dashboard(recs, procs, info, sel, prompt_buf)
            k = _read_key()

            if k == "up":
                if recs: sel = max(0, sel - 1)
                continue
            if k == "down":
                if recs: sel = min(len(recs) - 1, sel + 1)
                continue
            if k == "bs":
                prompt_buf = prompt_buf[:-1]
                continue
            if k == "enter":
                if not recs: continue
                seed = prompt_buf.strip() or None
                prompt_buf = ""
                _launch_hex(recs[sel], seed)
                continue
            if k == "esc":
                if prompt_buf: prompt_buf = ""; continue
                return
            if prompt_buf:
                if k and len(k) == 1 and k.isprintable():
                    prompt_buf += k
                continue
            if k == "q": return
            if k == "c" and recs:
                rt = pick_runtime(recs[sel])
                if rt: chat_loop(recs[sel], rt, get_context(recs[sel]))
                continue
            if k == "e": safe_call("cmd_explore"); continue
            if k == "m": safe_call("menu_models"); continue
            if k == "h": safe_call("cmd_health"); continue
            if k == "s": safe_call("menu_servers"); continue
            if k == "a": safe_call("menu_agents"); continue
            if k == "x": safe_call("cmd_cs_agent"); continue
            if k == "r": safe_call("menu_computer"); continue
            if k == "g": safe_call("cmd_rig"); continue
            if k == "k": safe_call("menu_settings"); continue
            if k == "f": safe_call("cmd_fix", True); continue
            if k and len(k) == 1 and k.isprintable():
                prompt_buf += k
        except KeyboardInterrupt:
            print(); return
        except Exception as e:
            import traceback as _tb
            log("menu_main: " + _tb.format_exc(), "error")
            print()
            print("  " + RD + "x dashboard: " + type(e).__name__ + ": " +
                  str(e) + RSTC)
            print("  " + DIM + "  falling back to simple mode..." + RSTC)
            time.sleep(1.5)
            return _menu_simple_fallback()


# ---------- computer use tools ----------
def _pyautogui():
    try:
        import pyautogui as pg
        pg.FAILSAFE = True
        pg.PAUSE = 0.15
        return pg
    except Exception:
        return None


def _ensure_screen_dir():
    d = DATA_HOME / "agent" / "screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mss_shot():
    try:
        import mss, mss.tools
        with mss.mss() as sct:
            mon = sct.monitors[1]
            img = sct.grab(mon)
            out = _ensure_screen_dir() / ("shot_" + str(int(time.time())) + ".png")
            mss.tools.to_png(img.rgb, img.size, output=str(out))
            return str(out), img.width, img.height
    except Exception:
        pass
    pg = _pyautogui()
    if not pg: return None, 0, 0
    try:
        img = pg.screenshot()
        out = _ensure_screen_dir() / ("shot_" + str(int(time.time())) + ".png")
        img.save(str(out))
        return str(out), img.width, img.height
    except Exception:
        return None, 0, 0


def _t_screen(a, cwd=None):
    p, w, h = _mss_shot()
    if not p:
        return "[screen: install pyautogui + mss + pillow]"
    return "screenshot: " + p + "\n  " + str(w) + "x" + str(h)


def _t_screen_size(a, cwd=None):
    pg = _pyautogui()
    if not pg: return "[pyautogui not installed]"
    try:
        w, h = pg.size(); return str(w) + "x" + str(h)
    except Exception as e: return "[error: " + str(e) + "]"


def _t_mouse_move(a, cwd=None):
    pg = _pyautogui()
    if not pg: return "[pyautogui not installed]"
    try:
        pg.moveTo(int(a.get("x", 0)), int(a.get("y", 0)),
                  duration=float(a.get("duration", 0.2)))
        return "moved to (" + str(a.get("x")) + ", " + str(a.get("y")) + ")"
    except Exception as e: return "[error: " + str(e) + "]"


def _t_mouse_click(a, cwd=None):
    pg = _pyautogui()
    if not pg: return "[pyautogui not installed]"
    try:
        x, y = a.get("x"), a.get("y")
        clicks = int(a.get("clicks", 1))
        button = a.get("button", "left")
        if x is not None and y is not None:
            pg.click(int(x), int(y), clicks=clicks, button=button)
            return "clicked " + button + " x" + str(clicks) + " at (" + str(x) + "," + str(y) + ")"
        pg.click(clicks=clicks, button=button)
        return "clicked at current position"
    except Exception as e: return "[error: " + str(e) + "]"


def _t_mouse_drag(a, cwd=None):
    pg = _pyautogui()
    if not pg: return "[pyautogui not installed]"
    try:
        pg.moveTo(int(a.get("x1", 0)), int(a.get("y1", 0)))
        pg.dragTo(int(a.get("x2", 0)), int(a.get("y2", 0)),
                  duration=float(a.get("duration", 0.3)), button="left")
        return "dragged"
    except Exception as e: return "[error: " + str(e) + "]"


def _t_scroll(a, cwd=None):
    pg = _pyautogui()
    if not pg: return "[pyautogui not installed]"
    try:
        amt = int(a.get("amount", 3))
        x, y = a.get("x"), a.get("y")
        if x is not None and y is not None:
            pg.scroll(amt, x=int(x), y=int(y))
        else:
            pg.scroll(amt)
        return "scrolled " + str(amt)
    except Exception as e: return "[error: " + str(e) + "]"


def _t_key(a, cwd=None):
    pg = _pyautogui()
    if not pg: return "[pyautogui not installed]"
    try:
        keys = a.get("keys") or a.get("key") or ""
        if isinstance(keys, list):
            pg.hotkey(*keys)
            return "pressed " + "+".join(keys)
        if "+" in keys:
            parts = keys.split("+")
            pg.hotkey(*parts)
            return "pressed " + keys
        pg.press(keys)
        return "pressed " + keys
    except Exception as e: return "[error: " + str(e) + "]"


def _t_type(a, cwd=None):
    pg = _pyautogui()
    if not pg: return "[pyautogui not installed]"
    try:
        text = a.get("text", "")
        pg.write(text, interval=float(a.get("interval", 0.01)))
        return "typed " + str(len(text)) + " chars"
    except Exception as e: return "[error: " + str(e) + "]"


def _t_window_list(a, cwd=None):
    try:
        import pygetwindow as gw
    except Exception:
        return "[pygetwindow not installed: pip install pygetwindow]"
    try:
        out = []
        for w in gw.getAllWindows():
            try:
                if w.title and w.visible:
                    out.append(w.title[:80])
            except Exception:
                pass
        return "\n".join(out[:80]) or "(no visible windows)"
    except Exception as e: return "[error: " + str(e) + "]"


def _t_window_focus(a, cwd=None):
    try:
        import pygetwindow as gw
    except Exception:
        return "[pygetwindow not installed]"
    pat = a.get("title") or a.get("pattern") or ""
    if not pat: return "[title required]"
    try:
        for w in gw.getAllWindows():
            try:
                if pat.lower() in (w.title or "").lower():
                    if w.isMinimized: w.restore()
                    w.activate()
                    return "focused: " + w.title[:80]
            except Exception:
                pass
        return "[no match for '" + pat + "']"
    except Exception as e: return "[error: " + str(e) + "]"


def _t_app_start(a, cwd=None):
    name = a.get("name") or a.get("cmd") or ""
    args = a.get("args") or []
    if not name: return "[name required]"
    if isinstance(args, str): args = [args]
    try:
        subprocess.Popen([name] + [str(x) for x in args])
        return "started: " + name
    except FileNotFoundError:
        try:
            if os.name == "nt":
                subprocess.Popen(["cmd", "/c", "start", "", name] +
                                 [str(x) for x in args])
                return "started via shell: " + name
        except Exception as e:
            return "[error: " + str(e) + "]"
        return "[not found: " + name + "]"
    except Exception as e: return "[error: " + str(e) + "]"


def _t_sleep(a, cwd=None):
    try:
        secs = min(float(a.get("seconds", 1)), 60)
        time.sleep(secs)
        return "slept " + str(secs) + "s"
    except Exception as e: return "[error: " + str(e) + "]"


def _t_ocr(a, cwd=None):
    path = a.get("path")
    if not path:
        p, _, _ = _mss_shot()
        if not p: return "[no screenshot]"
        path = p
    try:
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore
        return pytesseract.image_to_string(Image.open(path))[:MAX_TOOL_OUTPUT]
    except ImportError:
        return "[install pytesseract + pillow]"
    except Exception as e:
        return "[error: " + str(e) + "]"


# register CU tools (idempotent)
_CU = {
    "screen":       ("Screenshot to file. args: {path:str=''}", _t_screen),
    "screen_size":  ("Screen resolution. args: {}", _t_screen_size),
    "mouse_move":   ("Move mouse. args: {x:int, y:int}", _t_mouse_move),
    "mouse_click":  ("Click. args: {x:int, y:int, button:str='left', clicks:int=1}",
                     _t_mouse_click),
    "mouse_drag":   ("Drag. args: {x1,y1,x2,y2}", _t_mouse_drag),
    "scroll":       ("Scroll. args: {amount:int=3}", _t_scroll),
    "key":          ("Press key/hotkey. args: {keys:str}", _t_key),
    "type":         ("Type text. args: {text:str}", _t_type),
    "window_list":  ("List windows. args: {}", _t_window_list),
    "window_focus": ("Focus window. args: {title:str}", _t_window_focus),
    "app_start":    ("Launch app. args: {name:str, args:list=[]}", _t_app_start),
    "sleep":        ("Sleep seconds. args: {seconds:float}", _t_sleep),
    "ocr":          ("OCR screenshot. args: {path:str=''}", _t_ocr),
}
try:
    for _n, (_d, _f) in _CU.items():
        if _f is not None:
            TOOLS_IMPL[_n] = _f
            if not any(s.get("name") == _n for s in TOOLS_SPEC):
                TOOLS_SPEC.append({"name": _n, "desc": _d})
except Exception:
    pass


# ---------- computer use CLI ----------
def cmd_screen(path=None):
    p, w, h = _mss_shot()
    if not p:
        print(RD + "  pyautogui + mss required: pip install pyautogui mss pillow" + RSTC)
        return
    if path:
        try:
            import shutil as _sh
            _sh.copy2(p, path); p = path
        except Exception: pass
    print(GR + "  v " + str(p) + RSTC)
    print(DIM + "    " + str(w) + "x" + str(h) + RSTC)


def cmd_click(x=None, y=None, button="left", clicks=1):
    pg = _pyautogui()
    if not pg: print(RD + "  pyautogui required" + RSTC); return
    try:
        if x is not None and y is not None:
            pg.click(int(x), int(y), clicks=int(clicks), button=button)
            print(GR + "  v clicked at (" + str(x) + "," + str(y) + ")" + RSTC)
        else:
            pg.click(clicks=int(clicks), button=button)
            print(GR + "  v clicked" + RSTC)
    except Exception as e: print(RD + "  x " + str(e) + RSTC)


def cmd_move(x, y):
    pg = _pyautogui()
    if not pg: print(RD + "  pyautogui required" + RSTC); return
    try:
        pg.moveTo(int(x), int(y), duration=0.2)
        print(GR + "  v moved" + RSTC)
    except Exception as e: print(RD + "  x " + str(e) + RSTC)


def cmd_drag(x1, y1, x2, y2):
    pg = _pyautogui()
    if not pg: print(RD + "  pyautogui required" + RSTC); return
    try:
        pg.moveTo(int(x1), int(y1))
        pg.dragTo(int(x2), int(y2), duration=0.3, button="left")
        print(GR + "  v dragged" + RSTC)
    except Exception as e: print(RD + "  x " + str(e) + RSTC)


def cmd_type(text, interval=0.01):
    pg = _pyautogui()
    if not pg: print(RD + "  pyautogui required" + RSTC); return
    try:
        pg.write(text, interval=float(interval))
        print(GR + "  v typed " + str(len(text)) + " chars" + RSTC)
    except Exception as e: print(RD + "  x " + str(e) + RSTC)


def cmd_key(keys):
    pg = _pyautogui()
    if not pg: print(RD + "  pyautogui required" + RSTC); return
    try:
        if "+" in keys:
            pg.hotkey(*keys.split("+")); print(GR + "  v " + keys + RSTC)
        else:
            pg.press(keys); print(GR + "  v pressed " + keys + RSTC)
    except Exception as e: print(RD + "  x " + str(e) + RSTC)


def cmd_scroll(amount):
    pg = _pyautogui()
    if not pg: print(RD + "  pyautogui required" + RSTC); return
    try:
        pg.scroll(int(amount)); print(GR + "  v scrolled" + RSTC)
    except Exception as e: print(RD + "  x " + str(e) + RSTC)


def cmd_windows():
    try:
        import pygetwindow as gw
    except Exception:
        print(RD + "  pygetwindow required: pip install pygetwindow" + RSTC); return
    try:
        rows = []
        for w in gw.getAllWindows():
            try:
                if w.title and w.visible:
                    rows.append([trunc(w.title, 50),
                                 str(w.left) + "," + str(w.top),
                                 str(w.width) + "x" + str(w.height)])
            except Exception:
                pass
        if rows:
            print(table(rows, ["TITLE", "POS", "SIZE"]))
        else:
            print(DIM + "  (none)" + RSTC)
    except Exception as e: print(RD + "  x " + str(e) + RSTC)


def cmd_focus(title):
    try:
        import pygetwindow as gw
    except Exception:
        print(RD + "  pygetwindow required" + RSTC); return
    try:
        for w in gw.getAllWindows():
            try:
                if title.lower() in (w.title or "").lower():
                    if w.isMinimized: w.restore()
                    w.activate()
                    print(GR + "  v focused: " + w.title[:80] + RSTC)
                    return
            except Exception:
                pass
        print(RD + "  no match" + RSTC)
    except Exception as e: print(RD + "  x " + str(e) + RSTC)


def cmd_app(name, args=None):
    try:
        subprocess.Popen([name] + [str(x) for x in (args or [])])
        print(GR + "  v started " + name + RSTC)
    except FileNotFoundError:
        if os.name == "nt":
            try:
                subprocess.Popen(["cmd", "/c", "start", "", name] +
                                 [str(x) for x in (args or [])])
                print(GR + "  v started via shell: " + name + RSTC)
            except Exception as e:
                print(RD + "  x " + str(e) + RSTC)
        else:
            print(RD + "  x not found: " + name + RSTC)
    except Exception as e: print(RD + "  x " + str(e) + RSTC)


def cmd_ocr(path=None):
    if not path:
        p, _, _ = _mss_shot()
        if not p: print(RD + "  no screenshot" + RSTC); return
        path = p
    try:
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore
        txt = pytesseract.image_to_string(Image.open(path))
        print(txt if txt.strip() else DIM + "  (empty)" + RSTC)
    except ImportError:
        print(RD + "  pip install pytesseract pillow" + RSTC)
    except Exception as e: print(RD + "  x " + str(e) + RSTC)


def cmd_size():
    pg = _pyautogui()
    if not pg: print(RD + "  pyautogui required" + RSTC); return
    try:
        w, h = pg.size(); print(str(w) + "x" + str(h))
    except Exception as e: print(RD + "  x " + str(e) + RSTC)


def menu_computer():
    while True:
        clearscr()
        print()
        print("  " + col(201) + "C O M P U T E R   U S E" + RSTC)
        print("  " + col(51) + "\u2500" * 50 + RSTC)
        print()
        opts = [
            ("1", "screenshot"),
            ("2", "click at x,y"),
            ("3", "type text"),
            ("4", "press key (ctrl+c)"),
            ("5", "list windows"),
            ("6", "focus a window"),
            ("7", "launch an app"),
            ("8", "OCR latest screenshot"),
            ("9", "screen size"),
            ("0", "mouse move"),
        ]
        for k, v in opts:
            print("  " + col(51) + "[" + RSTC + GR + k + RSTC +
                  col(51) + "]" + RSTC + "  " + DIM + v + RSTC)
        print("  " + col(51) + "[b]" + RSTC + "  " + DIM + "back" + RSTC)
        print()
        c = ask("  " + CY + "\u203a " + RSTC).strip().lower()
        if c in ("b", ""): return
        try:
            if c == "1": cmd_screen()
            elif c == "2": cmd_click(int(ask("  x: ")), int(ask("  y: ")))
            elif c == "3": cmd_type(ask("  text: "))
            elif c == "4": cmd_key(ask("  keys: "))
            elif c == "5": cmd_windows()
            elif c == "6": cmd_focus(ask("  title: "))
            elif c == "7": cmd_app(ask("  app: "))
            elif c == "8": cmd_ocr()
            elif c == "9": cmd_size()
            elif c == "0": cmd_move(int(ask("  x: ")), int(ask("  y: ")))
        except (ValueError, KeyboardInterrupt):
            print(RD + "  cancelled" + RSTC)


# ---------- agents ----------
def _find_chatgpt_exe():
    """Find the ChatGPT desktop app on Windows.
    Covers: manual install, MS Store (WindowsApps), Program Files,
    winget, scoop, and a `where.exe` fallback.
    """
    if sys.platform == "darwin":
        p = "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT"
        if os.path.exists(p):
            return p
        return None

    if os.name != "nt":
        for p in ("/usr/local/bin/chatgpt",
                  "/usr/bin/chatgpt",
                  str(Path.home() / ".local" / "bin" / "chatgpt")):
            if os.path.exists(p):
                return p
        return None

    # Windows candidates — in order of likelihood
    la   = os.environ.get("LOCALAPPDATA", "")
    pf   = os.environ.get("ProgramFiles", "")
    pfx  = os.environ.get("ProgramFiles(x86)", "")
    home = str(Path.home())

    cands = []
    # manual / winget / installed normally
    if la:
        cands += [
            Path(la) / "Programs" / "ChatGPT" / "ChatGPT.exe",
            Path(la) / "Programs" / "chatgpt" / "ChatGPT.exe",
            Path(la) / "ChatGPT" / "ChatGPT.exe",
            Path(la) / "Microsoft" / "WindowsApps" / "ChatGPT.exe",
            Path(la) / "Microsoft" / "WindowsApps" / "ChatGPTApp.exe",
        ]
    if pf:
        cands += [
            Path(pf) / "ChatGPT" / "ChatGPT.exe",
            Path(pf) / "OpenAI" / "ChatGPT" / "ChatGPT.exe",
        ]
    if pfx:
        cands += [Path(pfx) / "ChatGPT" / "ChatGPT.exe"]
    cands += [
        Path(home) / "AppData" / "Local" / "ChatGPT" / "ChatGPT.exe",
        Path("C:/Program Files/ChatGPT/ChatGPT.exe"),
    ]

    for c in cands:
        try:
            if c.exists():
                return str(c)
        except Exception:
            pass

    # MS Store packages live under Program Files\WindowsApps with a
    # hash in the folder name. Enumerate and pick ChatGPT.exe.
    for base in (Path(pf) / "WindowsApps", Path(la) / "Microsoft" / "WindowsApps"):
        try:
            if not base.exists():
                continue
            for d in base.iterdir():
                n = d.name.lower()
                if "chatgpt" not in n and "openai" not in n:
                    continue
                exe = d / "ChatGPT.exe"
                if exe.exists():
                    return str(exe)
                # some builds nest under app\
                for sub in ("app", "ChatGPT"):
                    e2 = d / sub / "ChatGPT.exe"
                    if e2.exists():
                        return str(e2)
        except Exception:
            pass

    # `where.exe` fallback (respects PATH and App Paths registry)
    try:
        r = subprocess.run(["where", "ChatGPT.exe"],
                           capture_output=True, text=True, timeout=6)
        for line in (r.stdout or "").splitlines():
            p = line.strip()
            if p and Path(p).exists():
                return p
    except Exception:
        pass

    # last resort: start-menu shortcuts → parse target
    try:
        sm = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / \
             "Start Menu" / "Programs"
        for lnk in sm.rglob("*ChatGPT*.lnk"):
            try:
                import win32com.client  # type: ignore
                sh = win32com.client.Dispatch("WScript.Shell")
                target = sh.CreateShortcut(str(lnk)).TargetPath
                if target and Path(target).exists():
                    return target
            except Exception:
                # no pywin32 — try reading the file bytes for the target path
                try:
                    raw = lnk.read_bytes()
                    m = re.search(rb"[A-Za-z]:\\\\[^\x00]+ChatGPT\.exe", raw)
                    if m:
                        p = m.group(0).decode("utf-8", "replace")
                        if Path(p).exists():
                            return p
                except Exception:
                    pass
    except Exception:
        pass

    return None


def agent_installed(a):
    if a.id == "chatgpt-desktop":
        return _find_chatgpt_exe() is not None
    if _resolve_bin(a.check_bin):
        return True
    try:
        if find_tool(a.check_bin):
            return True
    except Exception:
        pass
    return False


def _resolve_bin(name):
    """Find an executable. On Windows, prefer .cmd/.exe/.bat over
    extensionless npm shims which cannot be launched by subprocess.
    """
    if not name:
        return None
    p = pathlib.Path(name)
    if p.is_absolute() and p.exists():
        return str(p)

    if os.name == "nt":
        # explicit extension precedence
        for ext in (".cmd", ".exe", ".bat", ".ps1", ".com"):
            q = shutil.which(name + ext)
            if q:
                return q
        # maybe caller passed "claude.cmd" already
        if pathlib.Path(name).suffix.lower() in (".cmd", ".exe", ".bat", ".ps1", ".com"):
            q = shutil.which(name)
            if q:
                return q
        # fall back to plain
        q = shutil.which(name)
        if q:
            return q
        return None

    # Unix: standard which, then try common script extensions
    q = shutil.which(name)
    if q:
        return q
    for ext in (".sh", ".py", ".rb"):
        q = shutil.which(name + ext)
        if q:
            return q
    return None


def _ensure_srv(port, model=None):
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:" + str(port) + "/health", timeout=2) as r:
            if r.status == 200: return port
    except Exception:
        pass
    script = Path(__file__).resolve()
    LOGS_D.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_D / ("cs-serve-" + str(port) + ".log")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        fh = open(log_path, "w", encoding="utf-8", errors="replace")
    except Exception:
        fh = subprocess.DEVNULL
    args = [sys.executable, str(script), "serve", "--port", str(port)]
    if model: args += ["--model", model]
    proc = subprocess.Popen(args, stdout=fh, stderr=subprocess.STDOUT,
                            cwd=str(script.parent), env=env)
    for _ in range(120):
        time.sleep(0.5)
        if proc.poll() is not None:
            raise RuntimeError("serve exited; see " + str(log_path))
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:" + str(port) + "/health",
                    timeout=2) as r:
                if r.status == 200: return port
        except Exception:
            pass
    raise RuntimeError("serve did not become healthy; see " + str(log_path))


def _agents_run_flow(aid):
    a = AGENTS.get(aid)
    if not a:
        print(RD + "  unknown: " + aid + RSTC); return
    if not agent_installed(a):
        print()
        print(YL + "  " + a.name + " not installed" + RSTC)
        if ask_yn("  install now?", default=True):
            try: cmd_agents("install", aid)
            except Exception as e:
                print(RD + "  x " + str(e) + RSTC); return
            if not agent_installed(a):
                print(RD + "  still not detected" + RSTC); return
        else:
            return
    recs = load_scan()
    if not recs:
        print(RD + "  no models; use E to explore" + RSTC); return
    print()
    print("  " + col(201) + "pick a model for " + a.name + RSTC)
    for i, r in enumerate(recs[:30]):
        rt = pick_runtime(r)
        ok = GR + "v" + RSTC if rt else RD + "x" + RSTC
        print("  " + ok + " [" + str(i).rjust(2) + "] " +
              trunc(r.name, 52).ljust(52) + "  " +
              DIM + human(r.size).rjust(9) + RSTC)
    sel = ask("  " + CY + "model \u203a " + RSTC).strip()
    if sel == "b": return
    try:
        rec = recs[int(sel)] if sel else recs[0]
    except (ValueError, IndexError):
        print(RD + "  invalid" + RSTC); return
    rt = pick_runtime(rec)
    if not rt:
        print(RD + "  no runtime for " + rec.name + RSTC); return
    try:
        if not rt.can_run(rec):
            print(RD + "  runtime " + rt.id + " cannot run " + rec.name + RSTC)
            return
    except Exception:
        pass
    print()
    print(GR + "  launching " + a.name + " \u2192 " + rec.name + RSTC)
    try:
        cmd_agents("launch", aid, rec.name)
    except Exception as e:
        import traceback as _tb
        print(RD + "  launch failed: " + str(e) + RSTC)
        log("agents launch: " + _tb.format_exc(), "error")
    try: input(DIM + "  Enter to return" + RSTC)
    except Exception: pass




def cmd_locate(agent_id=None):
    """Show exactly how cs resolves an agent binary, step by step."""
    if not agent_id:
        print(DIM + "  usage: cs locate <agent>   (e.g. claude-code)")
        print(DIM + "  agents: " + ", ".join(AGENTS.keys()))
        return
    a = AGENTS.get(agent_id)
    if not a and agent_id not in (a.id for a in AGENTS.values() if a):
        print(RD + "  unknown agent: " + agent_id + RSTC); return
    print()
    print("  " + col(201) + "LOCATE: " + agent_id + RSTC)
    print("  " + DIM + a.name + RSTC)
    print()

    if a.id == "chatgpt-desktop":
        p = _find_chatgpt_exe()
        print("  desktop app")
        print("    detected: " + (GR + str(p) + RSTC if p else RD + "no" + RSTC))
        print()
        print("  searched:")
        for line in [
            "%LOCALAPPDATA%\\Programs\\ChatGPT\\ChatGPT.exe",
            "%LOCALAPPDATA%\\ChatGPT\\ChatGPT.exe",
            "%LOCALAPPDATA%\\Microsoft\\WindowsApps\\ChatGPT.exe",
            "%ProgramFiles%\\ChatGPT\\ChatGPT.exe",
            "%ProgramFiles%\\WindowsApps\\*ChatGPT*\\ChatGPT.exe",
            "where.exe ChatGPT.exe",
            "Start Menu shortcuts",
        ]:
            print("    " + DIM + line + RSTC)
        return

    print("  check_bin: " + a.check_bin)
    print()
    print("  shutil.which() with each extension:")
    for ext in ("", ".cmd", ".exe", ".bat", ".ps1", ".com"):
        try:
            w = shutil.which(a.check_bin + ext)
        except Exception:
            w = None
        mark = GR + "v" + RSTC if w else DIM + "." + RSTC
        print("    " + mark + " " + (a.check_bin + ext).ljust(30) +
              (DIM + str(w) + RSTC if w else ""))
    print()
    print("  find_tool(): " + str(find_tool(a.check_bin)))
    print("  _resolve_bin(): " + str(_resolve_bin(a.check_bin)))
    print()
    print("  PATH order (first 8):")
    for p in os.environ.get("PATH", "").split(os.pathsep)[:8]:
        print("    " + DIM + p + RSTC)




def cmd_run_agent(agent_id=None, model=None):
    """Directly launch a coding agent with full diagnostics."""
    if not agent_id:
        print(DIM + "  usage: cs run-agent <id> [model]")
        print(DIM + "  agents: " + ", ".join(AGENTS.keys()))
        return
    a = AGENTS.get(agent_id)
    if not a:
        print(RD + "  unknown agent: " + agent_id + RSTC)
        return

    print()
    print("  " + col(201) + "RUN AGENT" + RSTC + "  " + a.name)
    print()

    # 1. installed?
    inst = False
    try:
        inst = agent_installed(a)
    except Exception as e:
        print(RD + "  check failed: " + str(e) + RSTC)
    print("  installed : " + (GR + "yes" + RSTC if inst else RD + "no" + RSTC))

    # 2. resolve binary
    exe = None
    if a.id == "chatgpt-desktop":
        exe = _find_chatgpt_exe()
    else:
        exe = _resolve_bin(a.check_bin)
    print("  binary    : " + (GR + str(exe) + RSTC if exe else RD + "not found" + RSTC))

    if a.id == "chatgpt-desktop":
        if not exe:
            print()
            print(DIM + "  ChatGPT Desktop is not installed." + RSTC)
            print(DIM + "  Install from the Microsoft Store, then retry." + RSTC)
            return
        cmd_chatgpt(model)
        return

    if not exe:
        print()
        print(YL + "  binary not found on PATH" + RSTC)
        print(DIM + "  install: cs agents install " + agent_id + RSTC)
        print(DIM + "  or check: cs locate " + agent_id + RSTC)
        return

    # 3. pick model
    recs = load_scan()
    if not recs:
        print(RD + "  no models" + RSTC); return
    if model:
        rec = match_model(model)
    else:
        rec = recs[0]
    if not rec:
        print(RD + "  no match for: " + str(model) + RSTC); return
    rt = pick_runtime(rec)
    if not rt:
        print(RD + "  no runtime for " + rec.name + RSTC); return
    print("  model     : " + rec.name)
    print("  runtime   : " + rt.id)

    # 4. start server
    port = 8686
    _SERVE["rec"] = rec
    print("  starting server on :" + str(port) + " ...")
    try:
        _ensure_srv(port, rec.name)
    except Exception as e:
        print(RD + "  server failed: " + str(e) + RSTC)
        return
    print("  " + GR + "v server ready" + RSTC)

    # 5. build env + args
    env = os.environ.copy()
    for k, v in a.env.items():
        env[k] = v.replace("{port}", str(port)).replace("{model}", rec.name)

    args = [c.replace("{python}", sys.executable) for c in a.launch_cmd]
    args = [c.replace("{port}", str(port)).replace("{model}", rec.name)
            for c in args]
    args[0] = exe

    print()
    print(GR + "  launching: " + " ".join(args) + RSTC)
    print(DIM + "  (close the app when done)" + RSTC)
    print()

    suffix = pathlib.Path(exe).suffix.lower()
    rc = None
    try:
        if os.name == "nt" and suffix in (".cmd", ".bat"):
            rc = subprocess.call(["cmd", "/c"] + args, env=env)
        elif os.name == "nt" and suffix == ".ps1":
            rc = subprocess.call(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File"]
                + args, env=env)
        else:
            rc = subprocess.call(args, env=env)
    except FileNotFoundError as e:
        print(RD + "  exec failed (file not found): " + str(e) + RSTC)
        print(DIM + "  resolved to: " + exe + RSTC)
        print(DIM + "  suffix: " + suffix + RSTC)
    except Exception as e:
        print(RD + "  exec failed: " + type(e).__name__ + ": " + str(e) + RSTC)
    else:
        print()
        if rc == 0:
            print(GR + "  agent exited cleanly" + RSTC)
        else:
            print(YL + "  agent exited with code " + str(rc) + RSTC)

def menu_agents():
    ids = list(AGENTS.keys())
    while True:
        try:
            clearscr()
            print()
            print("  " + col(201) + "CODING AGENTS" + RSTC + "  " +
                  DIM + "run an agent against a local model" + RSTC)
            print()
            for i, aid in enumerate(ids):
                a = AGENTS[aid]
                try: ok = agent_installed(a)
                except Exception: ok = False
                mk = GR + "\u2713" + RSTC if ok else DIM + "\u00b7" + RSTC
                color = GR if ok else DIM
                print("  " + mk + " [" + str(i).rjust(2) + "] " +
                      color + aid.ljust(20) + RSTC + "  " +
                      DIM + a.name + RSTC)
            print()
            print("  " + DIM + "type a number to run   \u00b7   "
                        "i <num> to install   \u00b7   b to go back" + RSTC)
            print()
            c = ask("  " + CY + "\u203a " + RSTC).strip().lower()
            if c in ("b", "", "q"): return
            if c.startswith("i"):
                arg = c[1:].strip()
                if not arg: arg = ask("  install which #: ").strip()
                try:
                    cmd_agents("install", ids[int(arg)])
                except (ValueError, IndexError):
                    print(RD + "  usage: i <num>" + RSTC)
                try: input(DIM + "  Enter" + RSTC)
                except Exception: pass
                continue
            try:
                n = int(c)
                _agents_run_flow(ids[n])
            except (ValueError, IndexError):
                if c in AGENTS:
                    _agents_run_flow(c)
                else:
                    print(RD + "  unknown" + RSTC)
                    try: input(DIM + "  Enter" + RSTC)
                    except Exception: pass
        except KeyboardInterrupt:
            print(); return
        except Exception as e:
            print(RD + "  ! " + str(e) + RSTC)
            try: input(DIM + "  Enter" + RSTC)
            except Exception: pass


# ---------- fix / auto-heal ----------
def _auto_fix(silent=False):
    try:
        src = Path(__file__).read_text(encoding="utf-8")
    except Exception:
        return 0
    defined = set(re.findall(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)", src, re.M))
    critical = [
        "menu_main", "safe_call", "_read_key", "_cell", "_vlen",
        "_draw_dashboard", "_launch_hex", "_menu_simple_fallback",
        "_hex_agent", "_hex_header", "_hex_stream_buffered",
        "run_tool_blocks", "_handle_define_tools", "_handle_memories",
        "menu_agents", "_agents_run_flow", "cmd_agents",
        "agent_installed", "_resolve_bin", "_ensure_srv",
        "_find_chatgpt_exe", "menu_computer", "cmd_screen",
        "_pyautogui", "_mss_shot",
        "_agent_mem_load", "_agent_mem_save", "_agent_mem_add", "_agent_log",
    ]
    miss = [c for c in critical if c not in defined]
    if not miss:
        if not silent:
            print(GR + "  v all critical functions defined" + RSTC)
        return 0
    if not silent:
        print(YL + "  ! missing: " + ", ".join(miss) + RSTC)
        print(DIM + "    run `cs fix --apply` (repairs the canonical block)" + RSTC)
    return len(miss)


def cmd_fix(apply=False):
    print()
    print("  " + col(201) + "F I X" + RSTC + "  " + DIM +
          "self-audit and repair" + RSTC)
    n = _auto_fix(silent=False)
    if n == 0: return
    if not apply:
        print()
        print(DIM + "  run `cs fix --apply` to repair" + RSTC)
        return
    print()
    print(CY + "  attempting reload..." + RSTC)
    try:
        import importlib
        spec = importlib.util.spec_from_file_location(
            "cs_reload", str(Path(__file__).resolve()))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        print(GR + "  v module reloaded cleanly" + RSTC)
    except Exception as e:
        print(RD + "  x reload failed: " + str(e) + RSTC)
        print(DIM + "    full repair: python cs.py setup" + RSTC)


# === CS-CANONICAL-END ===


if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print(RSTC + "\n  ⌁ aborted")
    except Exception as e:
        log_exc("fatal"); print(RD + f"  x fatal: {e}" + RSTC); sys.exit(1)