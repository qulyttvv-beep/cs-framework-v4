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

# The windowed Spark X app has no console: stdin/stdout/stderr are None, and
# anything touching them (even sys.stdout.isatty() below) would crash at start.
_NO_CONSOLE = sys.stdout is None or sys.stderr is None
if sys.stdin is None or _NO_CONSOLE:
    _null = open(os.devnull, "r+", encoding="utf-8")
    sys.stdin = sys.stdin or _null
    sys.stdout = sys.stdout or _null
    sys.stderr = sys.stderr or _null
    if os.name == "nt":
        # Without a console of its own, every console program it starts (shell
        # commands, git, nvidia-smi …) would flash up a black window.
        _popen_init = subprocess.Popen.__init__

        def _popen_no_window(self, *a, **kw):
            if not kw.get("creationflags"):
                kw["creationflags"] = 0x08000000                   # CREATE_NO_WINDOW
            _popen_init(self, *a, **kw)
        subprocess.Popen.__init__ = _popen_no_window

APP       = "cs"
APP_LONG  = "CS Framework"
APP_UI    = "Spark X"          # the desktop app built on the framework
VERSION   = "4.3.0"
CODENAME  = "spark-x"


# --- forced constants (repair patch) ---
DEFAULT_TIMEOUT = 3600
DOWNLOAD_CHUNK = 1 << 16
HASH_CHUNK = 1 << 20
MAX_SAFETENSORS_HDR = 200_000_000
MAX_ARRAY_PREVIEW = 20_000
MAX_HISTORY = 40
MAX_TOOL_ROUNDS = 12
AGENT_MAX_ROUNDS = 40            # Spark X agent: computer/Blender tasks take many steps
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
        "computer":     ["mss", "pyautogui", "pillow"],
    }


# --- TOOLS_SPEC: name + description for every code-mode tool ---
# NOTE: TOOLS_SPEC must be defined BEFORE TOOLS_HEADER, which is built from it.
if "TOOLS_SPEC" not in globals():
    _TOOL_DESCS = {
        "bash":         '{"cmd":str} — run a shell command, return stdout+stderr',
        "read":         '{"path":str,"offset":int=0,"limit":int=200} — read a text file',
        "write":        '{"path":str,"content":str} — overwrite (or create) a file',
        "append":       '{"path":str,"content":str} — append to a file',
        "edit":         '{"path":str,"old":str,"new":str,"all":bool?} — replace exact text in a file',
        "browse":       '{"url":str} — open a web page and return its readable text',
        "ls":           '{"path":str="."} — list a directory',
        "glob":         '{"pattern":str,"root":str="."} — glob for matching files',
        "grep":         '{"pattern":str,"root":str=".","glob":str="**/*"} — search file contents',
        "web_fetch":    '{"url":str} — fetch a URL and return its text',
        "python":       '{"code":str} — execute a Python snippet, return its output',
        "http":         '{"url":str,"method":str="GET","headers":dict?,"body":str?} — raw HTTP request',
        "download":     '{"url":str,"dest":str} — download a file to disk',
        "extract":      '{"path":str,"dest":str?} — extract a .zip/.tar archive',
        "tree":         '{"path":str=".","depth":int=2} — print a directory tree',
        "diff":         '{"a":str,"b":str} — unified diff between two files',
        "find":         '{"name":str,"root":str="."} — find files by name pattern',
        "wc":           '{"path":str} — count lines, words and bytes of a file',
        "notify":       '{"message":str,"title":str?} — desktop notification',
        "clip_read":    '{} — read the system clipboard',
        "clip_write":   '{"text":str} — write text to the system clipboard',
        "screen":       '{"path":str?} — capture a screenshot',
        "screen_size":  '{} — return the screen dimensions',
        "mouse_move":   '{"x":int,"y":int} — move the mouse pointer',
        "mouse_click":  '{"x":int?,"y":int?,"button":str="left","clicks":int=1} — click the mouse',
        "mouse_drag":   '{"x1":int,"y1":int,"x2":int,"y2":int} — drag the mouse',
        "scroll":       '{"amount":int} — scroll the mouse wheel',
        "key":          '{"keys":str} — press a key or hotkey combo',
        "type":         '{"text":str} — type text with the keyboard',
        "window_list":  '{} — list open windows',
        "window_focus": '{"title":str} — focus a window by title',
        "app_start":    '{"name":str,"args":list?} — launch an application',
        "sleep":        '{"seconds":float} — pause for a number of seconds',
        "ocr":          '{"path":str?} — OCR text from a screenshot or image',
    }
    TOOLS_SPEC = [{"name": _n, "desc": _d} for _n, _d in _TOOL_DESCS.items()]


# --- TOOLS_HEADER: system-prompt preamble injected in code mode ---
if "TOOLS_HEADER" not in globals():
    _th_lines = ["- " + t["name"] + ": " + (t.get("desc") or "")
                 for t in TOOLS_SPEC]
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



def build_cli():
    """Return the single argparse parser used by the CLI.

    This is the ONE source of truth for subcommands — main() dispatches
    against it and cmd_doctor() audits it, so every command listed here is
    guaranteed to be reachable.
    """
    import argparse as _ap
    ap = _ap.ArgumentParser(prog=APP,
                            description=APP_LONG + " — portable LLM runner")
    ap.add_argument("-V", "--version", action="version",
                    version=f"{APP_LONG} {VERSION} ({CODENAME})")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("version", help="print version and exit")
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
    dc = sub.add_parser("doctor"); dc.add_argument("--deep", action="store_true")
    sub.add_parser("selftest"); sub.add_parser("logo")
    sub.add_parser("bonsai-setup"); sub.add_parser("ll-log"); sub.add_parser("menu")
    sub.add_parser("explore"); sub.add_parser("health"); sub.add_parser("agent")
    sub.add_parser("hex"); sub.add_parser("rig")
    sub.add_parser("screen"); sub.add_parser("windows"); sub.add_parser("size")
    sub.add_parser("platforms"); sub.add_parser("ps")

    v = sub.add_parser("verify"); v.add_argument("query", nargs="?"); v.add_argument("--deep", action="store_true"); v.add_argument("--online", action="store_true")
    r = sub.add_parser("run"); r.add_argument("model", nargs="?"); r.add_argument("-p","--prompt", default=None)
    c = sub.add_parser("chat"); c.add_argument("model", nargs="?"); c.add_argument("--incognito", action="store_true")
    sub.add_parser("incognito").add_argument("model", nargs="?")
    cd = sub.add_parser("code"); cd.add_argument("model", nargs="?"); cd.add_argument("--cwd", default=None)
    b = sub.add_parser("bench"); b.add_argument("model"); b.add_argument("-n","--tokens", type=int, default=128)
    i = sub.add_parser("install"); i.add_argument("target")
    cn = sub.add_parser("connect"); cn.add_argument("platform")
    pl = sub.add_parser("pull"); pl.add_argument("name"); pl.add_argument("--only", default=None)
    rm = sub.add_parser("rm"); rm.add_argument("model")
    ct = sub.add_parser("ctx"); ct.add_argument("model")
    sv = sub.add_parser("serve"); sv.add_argument("--host", default="127.0.0.1"); sv.add_argument("--port", type=int, default=8686); sv.add_argument("--model", default=None)
    apc = sub.add_parser("studio"); apc.add_argument("--host", default="127.0.0.1"); apc.add_argument("--port", type=int, default=8799); apc.add_argument("--model", default=None); apc.add_argument("--no-open", action="store_true"); apc.add_argument("--smoke", action="store_true", help="open the app window, check it boots, exit (CI)")
    ag = sub.add_parser("agents"); ag.add_argument("action", nargs="?", default="list", choices=["list","install","launch"]); ag.add_argument("agent", nargs="?"); ag.add_argument("--model", default=None)
    pi = sub.add_parser("plugin-init"); pi.add_argument("name")
    cl = sub.add_parser("clean"); cl.add_argument("--downloads", action="store_true")
    ex = sub.add_parser("export"); ex.add_argument("archive", nargs="?")
    md = sub.add_parser("model"); md.add_argument("name", nargs="?")
    sub.add_parser("config"); sub.add_parser("perms"); sub.add_parser("settings")
    fx = sub.add_parser("fix"); fx.add_argument("--apply", action="store_true")

    # agent-connector wiring (start local server + point agent at it)
    for _agent, _port in (("chatgpt", 8686), ("claude", 8687), ("opencode", 8688)):
        _p = sub.add_parser(_agent)
        _p.add_argument("model", nargs="?")
        _p.add_argument("--port", type=int, default=_port)
        _p.add_argument("--no-launch", action="store_true")
    un = sub.add_parser("unconnect"); un.add_argument("target", nargs="?", default="all",
                                                      choices=["all","chatgpt","claude","opencode"])

    # stop running servers
    st = sub.add_parser("stop"); st.add_argument("target", nargs="?")

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
def _app_dir() -> Path:
    """Directory the app 'lives' in — the folder holding the executable when
    frozen (PyInstaller), otherwise the folder holding cs.py.

    Using sys.executable when frozen is essential: a PyInstaller onefile build
    sets __file__ to a path inside its ephemeral extraction dir, so keying the
    portable data folder off __file__ would put cs_data somewhere that is wiped
    when the process exits.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _self_invoke(*args) -> list:
    """Argv that re-invokes this app with a cs subcommand.

    Frozen: the executable itself is the entrypoint, so just append args.
    From source: run ``python cs.py <args>``.
    """
    argv = [str(a) for a in args]
    if getattr(sys, "frozen", False):
        return [sys.executable, *argv]
    return [sys.executable, str(Path(__file__).resolve()), *argv]


def _installed_layout() -> bool:
    """True for an installed Spark X build (the Windows installer drops an
    INSTALLED marker next to the exe; a macOS .app bundle is always installed).
    Those must never write their data into the program folder."""
    if not getattr(sys, "frozen", False):
        return False
    exe = Path(sys.executable).resolve()
    return ".app/Contents/MacOS" in exe.as_posix() or (exe.parent / "INSTALLED").exists()


def _user_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Spark X"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Spark X"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "spark-x"


def _find_data_home() -> Path:
    env = os.environ.get("CS_HOME")
    if env:
        return Path(env).expanduser().resolve()
    if _installed_layout():
        d = _user_data_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d
    here = _app_dir()
    portable = here / "cs_data"
    # Portable mode if PORTABLE marker exists or cs_data/ already in use
    if (here / "PORTABLE").exists() or (portable / "config.json").exists():
        portable.mkdir(parents=True, exist_ok=True)
        return portable
    # Otherwise try to create it next to the app (running from a writable dir)
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

# -- settings defaults --
CFG.setdefault("prefs", {})
CFG["prefs"].setdefault("auto_approve", True)
CFG["prefs"].setdefault("auto_ctx", True)
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

def _interactive() -> bool:
    """True only when both stdin and stdout are real terminals.

    Used to keep setup/prompts from blocking in CI, pipes, or the packaged
    binary's smoke tests, where input() would hit EOF immediately.
    """
    try:
        return bool(sys.stdin and sys.stdin.isatty()
                    and sys.stdout and sys.stdout.isatty())
    except Exception:
        return False

def ask(prompt, default=""):
    if not _interactive():
        return default
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
    """One record per model of every connected API platform.

    Records are named ``<platform>/<model>``; platforms connected before
    model discovery existed (no ``models`` list) keep a single record named
    after the platform, using its default model.
    """
    recs = []
    for pid, pc in CFG.get("platforms", {}).items():
        models = [m for m in (pc.get("models") or []) if m]
        if not models:
            recs.append(ModelRec(pid, Path(pid), "platform", 0, "remote-api", "platform",
                                 meta={"platform": pid, "model": pc.get("model", "")}))
            continue
        for m in models:
            recs.append(ModelRec(f"{pid}/{m}", Path(pid), "platform", 0, "remote-api",
                                 "platform", meta={"platform": pid, "model": m}))
    return recs

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
    def can_run(self, r):
        return r.kind == "platform" and (r.meta or {}).get("platform", r.name) == self.pname
    def stream(self, r, prompt, hist, ctx):
        msgs = list(hist) if hist else [{"role":"user","content":prompt}]
        for kind, val in self.chat(r, msgs, ctx):
            if kind == "text":
                yield val

    def _endpoint(self, r):
        """(base_url, model, key, label) for this request."""
        model = (r.meta or {}).get("model") or self.pcfg.get("model") or "gpt-4o-mini"
        return self.pcfg["base_url"], model, self.pcfg.get("key"), self.pname

    def chat(self, r, msgs, ctx, tools=None):
        """Stream one completion. Yields ("text", str), ("think", str) and,
        at the end, ("tool_calls", [{"id", "name", "arguments"}]) when the
        model asked for tools via native function calling."""
        base, model, key, label = self._endpoint(r)
        yield from _openai_chat(base, model, key, label, msgs, ctx, tools)


class ProviderError(RuntimeError):
    """An HTTP/transport failure from a model endpoint. `retryable` marks
    failures where another endpoint may succeed (rate limit, 5xx, network)."""
    def __init__(self, msg, code=0, retryable=False):
        super().__init__(msg)
        self.code, self.retryable = code, retryable


def _is_loopback(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.startswith("127.")


_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def _urlopen(req, timeout):
    """urlopen that never routes local endpoints (Ollama, LM Studio, the
    Blender bridge…) through a system HTTP proxy."""
    url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
    if _is_loopback(url):
        return _NO_PROXY_OPENER.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def _openai_chat(base, model, key, label, msgs, ctx, tools=None):
    sys_prompt = ctx.get("system")
    if sys_prompt and not (msgs and msgs[0].get("role") == "system"):
        msgs = [{"role": "system", "content": sys_prompt}] + list(msgs)
    payload = {"model": model, "messages": msgs, "stream": True,
               "temperature": float(ctx.get("temperature", 0.7)),
               "max_tokens": int(ctx.get("max_new_tokens", 2048))}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    headers = {"Content-Type": "application/json", "User-Agent": f"{APP_UI}/{VERSION}",
               "X-Title": APP_UI, "HTTP-Referer": "https://github.com/qulyttvv-beep/cs-framework-v4"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions",
                                 data=json.dumps(payload).encode(), headers=headers)
    try:
        resp = _urlopen(req, timeout=300)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:600]
        try:
            j = json.loads(detail)
            err = j.get("error")
            detail = (err.get("message") if isinstance(err, dict) else err) or j.get("message") or detail
        except Exception:
            pass
        raise ProviderError(f"{label} returned HTTP {e.code}: {detail}", e.code,
                            retryable=e.code in (408, 425, 429) or e.code >= 500)
    except (urllib.error.URLError, OSError) as e:
        raise ProviderError(f"couldn't reach {label}: {getattr(e, 'reason', e)}", 0, retryable=True)
    calls = {}
    with resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            d = line[5:].strip()
            if d == "[DONE]":
                break
            try:
                ch = json.loads(d)
            except Exception:
                continue
            if isinstance(ch, dict) and ch.get("error"):
                e = ch["error"]
                raise ProviderError(f"{label}: " + str(e.get("message") if isinstance(e, dict) else e))
            for choice in (ch.get("choices") or [])[:1]:
                delta = choice.get("delta") or choice.get("message") or {}
                think = delta.get("reasoning_content") or delta.get("reasoning")
                if isinstance(think, str) and think:
                    yield ("think", think)
                c = delta.get("content")
                if isinstance(c, str) and c:
                    yield ("text", c)
                for tc in delta.get("tool_calls") or []:
                    slot = calls.setdefault(tc.get("index", len(calls)), {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    nm = fn.get("name")
                    if nm and nm != slot["name"]:
                        slot["name"] = nm if not slot["name"] else slot["name"] + nm
                    args = fn.get("arguments")
                    if isinstance(args, dict):          # some servers send objects
                        slot["arguments"] = json.dumps(args)
                    elif isinstance(args, str):
                        slot["arguments"] += args
    if calls:
        out = []
        for i in sorted(calls):
            c = calls[i]
            if c["name"]:
                out.append({"id": c["id"] or f"call_{uuid.uuid4().hex[:10]}",
                            "name": c["name"], "arguments": c["arguments"]})
        if out:
            yield ("tool_calls", out)


def _parse_tool_args(raw):
    """Arguments of a native tool call: tolerant of empty strings, objects and
    servers that repeat the whole JSON in every chunk."""
    if isinstance(raw, dict):
        return raw
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {"value": v}
    except Exception:
        pass
    dec, i, last = json.JSONDecoder(), 0, None
    while i < len(raw):
        j = raw.find("{", i)
        if j < 0:
            break
        try:
            v, end = dec.raw_decode(raw, j)
            if isinstance(v, dict):
                last = v
            i = end
        except Exception:
            i = j + 1
    if last is None:
        raise ValueError("tool arguments are not valid JSON")
    return last


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

_PRISM_CACHE = {}

def needs_prism_fork(rec) -> bool:
    if getattr(rec, "kind", "") != "gguf": return False
    try:
        st = Path(rec.path).stat()
        key = (str(rec.path), st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    if key in _PRISM_CACHE:
        return _PRISM_CACHE[key]
    res = _needs_prism_fork_uncached(rec)
    if key:
        _PRISM_CACHE[key] = res
    return res


def _needs_prism_fork_uncached(rec) -> bool:
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


_PLUGIN_SIG = {"sig": None}

def load_plugins():
    """Load drop-in runtime plugins. Re-executes plugin files only when the
    plugins folder changed (this is called for every runtime lookup)."""
    global _PLUGIN_RTS
    try:
        sig = tuple((f.name, f.stat().st_mtime_ns, f.stat().st_size)
                    for f in sorted(PLUGINS_D.glob("*.py"))) if PLUGINS_D.exists() else ()
    except OSError:
        sig = None
    if sig is not None and sig == _PLUGIN_SIG["sig"] and "_PLUGIN_RTS" in globals():
        return _PLUGIN_RTS
    _PLUGIN_SIG["sig"] = sig
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
        rts.append(FreeRT(pn, pc) if pc.get("free_auto") else OpenAIRT(pn, pc))
    return rts


_AVAIL_CACHE = {}

def _rt_available(rt, ttl=10.0):
    """rt.available(), memoised briefly: it probes binaries, imports and
    folders, and the model list asks it once per model on every refresh."""
    key = (getattr(rt, "id", ""), getattr(rt, "pname", ""), json.dumps(getattr(rt, "pcfg", None), sort_keys=True, default=str))
    hit = _AVAIL_CACHE.get(key)
    now = time.time()
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        ok = bool(rt.available()[0])
    except Exception:
        ok = False
    _AVAIL_CACHE[key] = (now, ok)
    return ok

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

    rts = all_runtimes()
    cached_id = _RUNTIME_PICK.get(rec.slug())
    if cached_id:
        for rt in rts:
            if rt.id == cached_id and rt.can_run(rec) and _rt_available(rt):
                return rt
    for rt in rts:
        if rt.can_run(rec) and _rt_available(rt):
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


def _python_exe():
    """Argv prefix of a real Python for the `python` tool. From source that is
    this interpreter; in the packaged app sys.executable is Spark X/cs itself,
    so use a system Python if there is one (skipping the Microsoft Store stub),
    else the bundled interpreter via the hidden --py-exec entry point."""
    if not getattr(sys, "frozen", False):
        return [sys.executable]
    for name in (["py", "-3"], ["python3"], ["python"]):
        exe = shutil.which(name[0])
        if exe and "WindowsApps" not in exe:
            return [exe] + name[1:]
    return [sys.executable, "--py-exec"]


def _py_exec(argv):
    """`cs --py-exec -c CODE` / `cs --py-exec FILE`: run Python with the
    interpreter bundled in the packaged app (standard library only)."""
    import runpy
    if argv[:1] == ["-c"] and len(argv) > 1:
        sys.argv = ["-c"] + argv[2:]
        exec(compile(argv[1], "<python>", "exec"), {"__name__": "__main__"})
    elif argv:
        sys.argv = argv
        runpy.run_path(argv[0], run_name="__main__")


def _t_python(a, cwd=None):
    code = a.get("code") or a.get("src") or ""
    if not code:
        return "[python: missing code]"
    try:
        r = subprocess.run(_python_exe() + ["-c", code],
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


def _python_for_pip():
    """Interpreter to run pip with. From source that's us; a frozen exe has no
    pip of its own, so fall back to a Python on PATH (or None)."""
    if not getattr(sys, "frozen", False):
        return sys.executable
    for name in ("python3", "python", "py"):
        p = shutil.which(name)
        if p:
            return p
    return None


def install_target(t):
    print(CY + "▸ install " + RSTC + t)
    if t in PIP_TARGETS:
        py = _python_for_pip()
        if not py:
            print(RD + "  x Python runtimes need a Python 3.9+ install (python.org); "
                  "GGUF models work without it via `cs install llamacpp-bin`." + RSTC)
            return
        rc = subprocess.call([py, "-m", "pip", "install", "--upgrade", *PIP_TARGETS[t]])
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
    """Install the `cs` global command pointing at this app (script or exe)."""
    if getattr(sys, "frozen", False):
        # Packaged binary: the launcher just calls the executable directly.
        exe = Path(sys.executable).resolve()
        win_run = f'"{exe}"'
        nix_run = f'exec "{exe}"'
    else:
        script = Path(__file__).resolve()
        py = sys.executable
        win_run = f'"{py}" "{script}"'
        nix_run = f'exec "{py}" "{script}"'
    if os.name == "nt":
        BIN_D.mkdir(parents=True, exist_ok=True)
        (BIN_D / "cs.cmd").write_text(f'@echo off\r\n{win_run} %*\r\n', encoding="utf-8")
        (BIN_D / "cs.ps1").write_text(f'& {win_run} @args\r\n', encoding="utf-8")
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
    launcher.write_text(f'#!/usr/bin/env bash\n{nix_run} "$@"\n', encoding="utf-8")
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
    interactive = _interactive()
    if not quiet: show_logo("first-time setup")
    print(YL + "┌─ SETUP — hardware" + RSTC)
    info = probe()
    for k, v in info.items():
        if interactive and not quiet: time.sleep(0.04)
        print(GR + "  [ OK ]" + RSTC, f"{k:8}", v)
    log(f"setup probe: {info}")
    print()
    print(CY + "▸ data location: " + RSTC + str(DATA_HOME))
    print(DIM + "  (copy this folder with cs.py to move everything)" + RSTC)
    print()
    # Only install runtimes when explicitly asked (--full) or an interactive
    # human confirms. A non-interactive first run (CI, pipe, packaged binary)
    # must never hang on a prompt or trigger multi-hundred-MB pip installs.
    if full:
        want = True
    elif interactive:
        want = ask_yn("  install recommended runtimes?", default=True)
    else:
        want = False
        print(DIM + "  (non-interactive — skipping runtime install; "
              "run `cs install all` later)" + RSTC)
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
    if interactive:
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

    def server_bind(self):
        # HTTPServer.server_bind() calls socket.getfqdn(host), a reverse-DNS
        # lookup that can stall for ~30 s on macOS before the port is served.
        # server_name is informational only, so skip the lookup.
        import socketserver
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

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
    """Running `cs serve` / `cs studio` processes, from source or the exe."""
    procs = []
    try:
        if os.name == "nt":
            ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
                  "' (serve|studio)' } | ForEach-Object { \"$($_.ProcessId) $($_.CommandLine)\" }")
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               capture_output=True, text=True, timeout=20)
        else:
            r = subprocess.run(["ps", "-eo", "pid,args"],
                               capture_output=True, text=True, timeout=10)
        out = r.stdout or ""
        me = os.getpid()
        for line in out.splitlines():
            low = line.lower()
            if not re.search(r"\s(serve|studio)(\s|$)", low):
                continue
            if "cs.py" not in low and not re.search(r"(^|[\\/ ])cs(\.exe)?\s", low):
                continue
            idm = re.match(r"\s*(\d+)", line)
            if not idm or int(idm.group(1)) == me:
                continue
            studio = re.search(r"\sstudio(\s|$)", low) is not None
            pm = re.search(r"--port\s+(\d+)", line)
            mm = re.search(r"--model\s+(\S+)", line)
            procs.append({
                "pid": idm.group(1),
                "port": pm.group(1) if pm else ("8799" if studio else "8686"),
                "model": mm.group(1) if mm else ("(studio)" if studio else "(auto)"),
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
    handler.close_connection = True
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "close")
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

    def _html(self, code, s):
        b = s.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def _sse(self):
        # No Content-Length is possible for a stream, so we must close the
        # connection at the end to give the client a clean EOF (browsers and
        # read-to-end clients both rely on this).
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            recs = load_scan() + platform_records()
            self._json(200, {"object":"list",
                             "data":[{"id":r.name,"object":"model"} for r in recs]})
        elif self.path == "/health":
            self._json(200, {"ok":True,"version":VERSION})
        elif self.path.split("?")[0] in ("/", "/index.html"):
            _studio_send_static(self, "index.html")
        elif self.path.startswith("/static/"):
            _studio_send_static(self, urllib.parse.unquote(self.path.split("?")[0][len("/static/"):]))
        elif self.path.startswith("/api/"):
            _app_get(self)
        else:
            self._json(404, {"error":"not found"})

    def do_POST(self):
        if self.path.startswith("/api/"):
            try:
                ln = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(ln) or b"{}") if ln else {}
            except Exception as e:
                self._json(400, {"error": str(e)}); return
            return _app_post(self, self.path.split("?")[0], body)
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


# ═══════════════════════════════════════════════════════════════════════════
#  Spark X — the desktop app, served by the framework itself
#  chat · artifacts · code workspace · browser · computer use · connectors
#  (MCP) · routines · providers.   Frontend: cs_studio/static/
# ═══════════════════════════════════════════════════════════════════════════
APP_D          = DATA_HOME / "app"
APP_CHATS_D    = APP_D / "chats"
APP_ROUTINES_P = APP_D / "routines.json"
APP_MCP_P      = APP_D / "mcp.json"
DEMO_MODEL_ID  = "cs-echo"

_STUDIO = {"token": None, "browse_token": None}
_STREAMS = {}      # stream id -> {"cancel": bool}
_APPROVALS = {}    # approval id -> {"event", "allow", "always"}
_JOBS = {}         # job id -> job dict


def _app_dirs():
    for d in (APP_D, APP_CHATS_D):
        try: d.mkdir(parents=True, exist_ok=True)
        except Exception: pass


# ── security: every /api call needs the session token, a local Host and a
#    same-origin (or absent) Origin. This server can run shell commands, read
#    and write files and drive the mouse, so a random web page must never be
#    able to reach it (CSRF / DNS rebinding).
def _studio_tokens():
    if not _STUDIO["token"]:
        import secrets
        _STUDIO["token"] = os.environ.get("CS_STUDIO_TOKEN") or secrets.token_urlsafe(24)
        _STUDIO["browse_token"] = secrets.token_urlsafe(18)
    return _STUDIO["token"], _STUDIO["browse_token"]


_LOOPBACK = ("127.0.0.1", "localhost", "::1")

def _studio_host_ok(handler):
    bound = handler.server.server_address[0]
    if bound not in ("127.0.0.1", "::1", "localhost"):
        return True                       # user explicitly exposed the server
    host = (handler.headers.get("Host") or "").strip()
    host = host[1:host.index("]")] if host.startswith("[") else host.split(":")[0]
    return host.lower() in _LOOPBACK


def _studio_origin_ok(handler):
    origin = handler.headers.get("Origin")
    if not origin:
        return True
    if origin == "null":
        return False
    try:
        o = urllib.parse.urlparse(origin)
    except Exception:
        return False
    bound = handler.server.server_address[0]
    host_ok = (o.hostname or "").lower() in _LOOPBACK or bound not in _LOOPBACK
    return host_ok and o.port == handler.server.server_port


def _studio_authorized(handler, q=None):
    import hmac
    tok, _ = _studio_tokens()
    got = handler.headers.get("X-CS-Token") or ((q or {}).get("t") or [""])[0]
    return (bool(got) and hmac.compare_digest(str(got), tok)
            and _studio_host_ok(handler) and _studio_origin_ok(handler))


# ── static frontend (cs_studio/static) ───────────────────────────────────────
_STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml",
                 ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json",
                 ".woff2": "font/woff2", ".webp": "image/webp"}

_STUDIO_MISSING_HTML = ("<!doctype html><meta charset=utf-8><title>Spark X</title>"
                        "<body style='background:#1f1e1c;color:#ecebe6;font:15px system-ui;"
                        "display:grid;place-items:center;height:100vh;margin:0'><div>"
                        "<h2>Spark X app files not found</h2><p>The <code>cs_studio/</code> folder "
                        "must sit next to <code>cs.py</code>. Use the release executable or the "
                        "full repository.</p></div>")


def _studio_static_dir():
    cands = []
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        cands.append(Path(mei) / "cs_studio" / "static")
    cands.append(_app_dir() / "cs_studio" / "static")
    try:
        spec = importlib.util.find_spec("cs_studio")
        if spec and spec.submodule_search_locations:
            cands.append(Path(list(spec.submodule_search_locations)[0]) / "static")
    except Exception:
        pass
    for c in cands:
        if (c / "index.html").is_file():
            return c
    return None


def _studio_send_static(handler, rel):
    base = _studio_static_dir()
    if not base:
        return handler._html(200, _STUDIO_MISSING_HTML)
    if not _studio_host_ok(handler):
        return handler._json(403, {"error": "forbidden host"})
    root = base.resolve()
    p = (root / rel).resolve()
    if root not in p.parents or not p.is_file():
        return handler._json(404, {"error": "not found"})
    data = p.read_bytes()
    if rel == "index.html":
        tok, btok = _studio_tokens()
        data = (data.replace(b"__CS_TOKEN__", tok.encode())
                    .replace(b"__CS_BROWSE_TOKEN__", btok.encode())
                    .replace(b"__CS_VERSION__", VERSION.encode()))
    handler.send_response(200)
    handler.send_header("Content-Type", _STATIC_TYPES.get(p.suffix.lower(), "application/octet-stream"))
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.end_headers()
    handler.wfile.write(data)


# ── models / runtimes ────────────────────────────────────────────────────────
def _model_info_list():
    out = []
    try:
        for r in load_scan():
            rt = None
            try: rt = pick_runtime(r)
            except Exception: pass
            arch = getattr(r, "arch", "") or ""
            out.append({"id": r.name, "name": r.name, "kind": r.kind, "group": "Local",
                        "arch": arch_disp(arch) if arch and arch != "?" else "",
                        "size": human(getattr(r, "size", 0) or 0),
                        "runtime": getattr(rt, "id", "") if rt else "",
                        "ready": bool(rt), "local": True})
    except Exception as e:
        log(f"model_info: {e}", "warn")
    names = {p["id"]: p["name"] for p in PROVIDERS}
    for pid, pc in CFG.get("platforms", {}).items():
        if pc.get("name"):
            names.setdefault(pid, pc["name"])
    for r in platform_records():
        meta = r.meta or {}
        pid = meta.get("platform", r.name)
        if pid == "free":
            best = next((x for x in _FREE["results"] if x.get("ok")), None)
            out.append({"id": r.name, "name": "Free model", "kind": "api", "group": "Free",
                        "provider": "free", "free": True, "auto": True, "vision": _rec_vision(r),
                        "via": (best or {}).get("name", ""), "runtime": "api", "ready": True, "local": False})
            continue
        caps = _OLLAMA["caps"].get(meta.get("model")) if pid == "ollama" else None
        out.append({"id": r.name, "name": meta.get("model") or r.name, "kind": "api",
                    "group": names.get(pid, pid), "provider": pid,
                    "free": bool((_prov(pid) or {}).get("free")) or str(meta.get("model", "")).endswith(":free"),
                    "vision": _rec_vision(r), "tools": ("tools" in caps) if caps is not None else None,
                    "runtime": "api", "ready": True, "local": pid in ("ollama", "lmstudio")})
    out.append({"id": DEMO_MODEL_ID, "name": "Spark Echo (demo)", "kind": "demo", "group": "Built-in",
                "runtime": "builtin", "ready": True, "local": True})
    return out


def _runtime_info_list():
    out = []
    for rt in all_runtimes():
        try: ok, detail = rt.available()
        except Exception as e: ok, detail = False, str(e)
        if getattr(rt, "id", "") == "openai-compat":
            continue
        out.append({"id": getattr(rt, "id", rt.__class__.__name__),
                    "ok": bool(ok), "detail": detail or ""})
    return out


_VISION_HINTS = ("gpt-4o", "gpt-4.1", "gpt-5", "o3", "o4", "gemini", "llama-4", "llama4", "vision",
                 "-vl", "vl:", "2.5vl", "pixtral", "grok", "gemma-3", "gemma3", "llava", "minicpm-v",
                 "qwen2.5-vl", "mistral-small3.1", "mistral-small3.2", "mistral-small-3.1",
                 "mistral-small-3.2", "moondream", "granite3.2-vision")

def _is_vision(model_id):
    m = str(model_id or "").lower()
    return any(h in m for h in _VISION_HINTS)


def _rec_vision(rec):
    """Can this model see images? Ollama tells us; otherwise go by name."""
    meta = rec.meta or {}
    pid, mname = meta.get("platform", ""), meta.get("model") or rec.name
    if pid == "ollama" and mname in _OLLAMA["caps"]:
        return "vision" in _OLLAMA["caps"][mname]
    if pid == "free":
        return any(x.get("ok") and x.get("vision") and x.get("id") == _FREE.get("last_good")
                   for x in _FREE["results"]) or (not _FREE.get("last_good") and any(
                   x.get("ok") and x.get("vision") for x in _FREE["results"][:1]))
    return _is_vision(mname)


# ── providers: OpenAI-compatible endpoints, many with genuine free tiers ─────
PROVIDERS = [
    {"id": "groq", "name": "Groq", "base_url": "https://api.groq.com/openai/v1",
     "key_url": "https://console.groq.com/keys", "free": True,
     "note": "Free tier. Very fast Llama, Qwen and GPT-OSS models.", "model": "llama-3.3-70b-versatile"},
    {"id": "gemini", "name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
     "key_url": "https://aistudio.google.com/apikey", "free": True,
     "note": "Free tier on AI Studio. Gemini Flash models, vision.", "model": "gemini-2.5-flash"},
    {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1",
     "key_url": "https://openrouter.ai/keys", "free": True,
     "note": "Dozens of free ':free' models from many labs.", "model": "meta-llama/llama-3.3-70b-instruct:free"},
    {"id": "cerebras", "name": "Cerebras", "base_url": "https://api.cerebras.ai/v1",
     "key_url": "https://cloud.cerebras.ai", "free": True,
     "note": "Free tier. Extremely fast inference.", "model": "llama-3.3-70b"},
    {"id": "mistral", "name": "Mistral", "base_url": "https://api.mistral.ai/v1",
     "key_url": "https://console.mistral.ai/api-keys", "free": True,
     "note": "Free 'Experiment' plan, including Codestral.", "model": "mistral-small-latest"},
    {"id": "github", "name": "GitHub Models", "base_url": "https://models.github.ai/inference",
     "key_url": "https://github.com/settings/tokens", "free": True,
     "note": "Free for prototyping with a GitHub token.", "model": "openai/gpt-4.1-mini"},
    {"id": "huggingface", "name": "Hugging Face", "base_url": "https://router.huggingface.co/v1",
     "key_url": "https://huggingface.co/settings/tokens", "free": True,
     "note": "Monthly free inference credits.", "model": "meta-llama/Llama-3.3-70B-Instruct"},
    {"id": "nvidia", "name": "NVIDIA NIM", "base_url": "https://integrate.api.nvidia.com/v1",
     "key_url": "https://build.nvidia.com", "free": True,
     "note": "Free developer credits.", "model": "meta/llama-3.3-70b-instruct"},
    {"id": "sambanova", "name": "SambaNova", "base_url": "https://api.sambanova.ai/v1",
     "key_url": "https://cloud.sambanova.ai/apis", "free": True,
     "note": "Free tier.", "model": "Meta-Llama-3.3-70B-Instruct"},
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1",
     "key_url": "https://platform.openai.com/api-keys", "free": False,
     "note": "GPT models.", "model": "gpt-4o-mini"},
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
     "key_url": "https://platform.deepseek.com/api_keys", "free": False,
     "note": "Low-cost chat and reasoning models.", "model": "deepseek-chat"},
    {"id": "together", "name": "Together AI", "base_url": "https://api.together.xyz/v1",
     "key_url": "https://api.together.ai/settings/api-keys", "free": False,
     "note": "Open models at scale.", "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo"},
    {"id": "ollama", "name": "Ollama", "base_url": "http://localhost:11434/v1",
     "key_url": "https://ollama.com/download", "free": True, "local": True, "no_key": True,
     "note": "Local. Detected automatically when running.", "model": ""},
    {"id": "lmstudio", "name": "LM Studio", "base_url": "http://localhost:1234/v1",
     "key_url": "https://lmstudio.ai", "free": True, "local": True, "no_key": True,
     "note": "Local. Detected automatically when running.", "model": ""},
]

_PROVIDER_FALLBACK_MODELS = {
    "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen3-32b", "openai/gpt-oss-120b"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"],
    "openrouter": ["meta-llama/llama-3.3-70b-instruct:free", "qwen/qwen3-coder:free",
                   "deepseek/deepseek-chat-v3-0324:free"],
    "cerebras": ["llama-3.3-70b", "qwen-3-32b", "gpt-oss-120b"],
    "mistral": ["mistral-small-latest", "codestral-latest", "mistral-large-latest"],
    "github": ["openai/gpt-4.1-mini", "openai/gpt-4.1"],
    "huggingface": ["meta-llama/Llama-3.3-70B-Instruct", "Qwen/Qwen2.5-Coder-32B-Instruct"],
    "nvidia": ["meta/llama-3.3-70b-instruct", "qwen/qwen2.5-coder-32b-instruct"],
    "sambanova": ["Meta-Llama-3.3-70B-Instruct"],
    "openai": ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "together": ["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
}

_NON_CHAT = ("embed", "whisper", "tts", "moderation", "dall-e", "image", "audio",
             "transcribe", "rerank", "guard", "speech", "sdxl", "flux")


def _prov(pid):
    return next((p for p in PROVIDERS if p["id"] == pid), None)


def _mask(k):
    if not k: return ""
    return (k[:4] + "…" + k[-4:]) if len(k) > 12 else "•" * 6


def _http_json(url, headers=None, timeout=15):
    h = {"User-Agent": f"{APP_LONG}/{VERSION}", "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:240].strip()
        raise RuntimeError(f"HTTP {e.code}" + (f": {body}" if body else f" {e.reason}"))


def _fetch_models(base_url, key=None, pid=None, timeout=12):
    h = {"Authorization": "Bearer " + key} if key else {}
    d = _http_json(base_url.rstrip("/") + "/models", h, timeout=timeout)
    items = d.get("data") if isinstance(d, dict) else d
    if items is None and isinstance(d, dict):
        items = d.get("models", [])
    ids = []
    for m in items or []:
        mid = (m.get("id") or m.get("name")) if isinstance(m, dict) else str(m)
        if not mid: continue
        mid = mid[7:] if mid.startswith("models/") else mid
        if any(b in mid.lower() for b in _NON_CHAT): continue
        ids.append(mid)
    if pid == "openrouter":
        free = sorted(i for i in ids if i.endswith(":free"))
        ids = free + sorted(i for i in ids if not i.endswith(":free"))[:60]
    return list(dict.fromkeys(ids))[:250]


def _provider_public():
    plats = CFG.get("platforms", {})
    out = []
    for p in PROVIDERS:
        pc = plats.get(p["id"]) or {}
        out.append({**p, "connected": p["id"] in plats, "key_masked": _mask(pc.get("key", "")),
                    "base_url": pc.get("base_url") or p["base_url"],
                    "models": pc.get("models", []), "model": pc.get("model") or p.get("model", ""),
                    "error": pc.get("error", "")})
    for pid, pc in plats.items():
        if not _prov(pid):
            out.append({"id": pid, "name": pc.get("name") or pid, "base_url": pc.get("base_url", ""),
                        "free": False, "custom": True, "note": "Custom OpenAI-compatible endpoint",
                        "connected": True, "key_masked": _mask(pc.get("key", "")),
                        "models": pc.get("models", []), "model": pc.get("model", ""),
                        "error": pc.get("error", "")})
    return out


def _provider_connect(pid, key="", base_url="", name=""):
    p = _prov(pid)
    if not p:
        if not base_url:
            raise ValueError("a base URL is required for a custom endpoint")
        pid = re.sub(r"[^a-z0-9-]+", "-", (name or pid or "custom").lower()).strip("-") or "custom"
    base = (base_url or (p or {}).get("base_url") or "").rstrip("/")
    old = CFG.get("platforms", {}).get(pid, {})
    pc = {"base_url": base, "provider": pid}
    if name and not p: pc["name"] = name
    key = (key or "").strip() or old.get("key", "")
    if key: pc["key"] = key
    # keyless endpoints: catalog entries that need none, and custom/local
    # servers connected without a key (vLLM, llama.cpp server, gateways)
    if (p and p.get("no_key")) or (not key and (not p or p.get("local"))):
        pc["no_key"] = True
    if not key and not pc.get("no_key") and p:
        raise ValueError("an API key is required for " + p["name"])
    try:
        models, err = _fetch_models(base, key or None, pid), ""
    except Exception as e:
        msg = str(e)
        if re.search(r"HTTP 40[13]", msg):
            raise ValueError("the key was rejected: " + msg[:160])
        models, err = list(_PROVIDER_FALLBACK_MODELS.get(pid, [])), msg[:200]
        if not p and not models:
            raise ValueError("couldn't reach that endpoint: " + msg[:160])
    default = (p or {}).get("model", "")
    if not models and default:
        models = [default]
    pc["models"] = models
    pc["model"] = default if default in models else (models[0] if models else "")
    pc["error"] = err
    CFG.setdefault("platforms", {})[pid] = pc
    save_cfg()
    return pid, pc


_LOCAL_PROBE = {"ts": 0.0}

def _autodetect_local(force=False):
    """Auto-connect Ollama / LM Studio when they are running (no setup needed)."""
    if not force and time.time() - _LOCAL_PROBE["ts"] < 20:
        return
    _LOCAL_PROBE["ts"] = time.time()
    for pid in ("ollama", "lmstudio"):
        p = _prov(pid)
        base = _ollama_base() + "/v1" if pid == "ollama" else p["base_url"]
        try:
            models = _fetch_models(base, None, pid, timeout=1.5)
        except Exception:
            continue
        plats = CFG.setdefault("platforms", {})
        pc = plats.get(pid) or {}
        if not models:                      # server up but every model deleted
            if pc.get("auto"):
                plats.pop(pid, None); save_cfg()
            continue
        if pc.get("models") != models or pc.get("base_url") != base:
            pc.update({"base_url": base, "no_key": True, "models": models,
                       "model": pc.get("model") if pc.get("model") in models else models[0],
                       "provider": pid, "auto": True})
            plats[pid] = pc
            save_cfg()


# ── chat / routine / mcp stores ──────────────────────────────────────────────
def _routines_load(): return jload(APP_ROUTINES_P, [])
def _routines_save(x): jsave(APP_ROUTINES_P, x)
def _mcp_cfg_load(): return jload(APP_MCP_P, {"servers": []})
def _mcp_cfg_save(c): jsave(APP_MCP_P, c)

def _safe_id(cid):
    return re.sub(r"[^A-Za-z0-9_-]", "", str(cid or ""))[:40]

def _chats_list():
    _app_dirs(); out = []
    for p in sorted(APP_CHATS_D.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        d = jload(p, {})
        out.append({"id": d.get("id", p.stem), "title": d.get("title", "Untitled"),
                    "model": d.get("model", ""), "updated": p.stat().st_mtime,
                    "kind": d.get("kind", "chat"), "n": len(d.get("messages", []))})
    return out

def _chat_load(cid):
    _app_dirs(); return jload(APP_CHATS_D / (_safe_id(cid) + ".json"), None)

def _chat_save(chat):
    _app_dirs(); chat["id"] = _safe_id(chat.get("id")) or uuid.uuid4().hex[:10]
    jsave(APP_CHATS_D / (chat["id"] + ".json"), chat)
    return chat["id"]

def _chat_delete(cid):
    try: (APP_CHATS_D / (_safe_id(cid) + ".json")).unlink()
    except Exception: pass


_ART_RX = re.compile(r"```([\w.+-]*)[^\n]*\n([\s\S]*?)```")

def _artifacts_list():
    out = []
    for c in _chats_list()[:200]:
        chat = _chat_load(c["id"]) or {}
        for mi, m in enumerate(chat.get("messages", [])):
            if m.get("role") != "assistant":
                continue
            for ai, mt in enumerate(_ART_RX.finditer(m.get("content") or "")):
                lang, code = (mt.group(1) or "text").lower(), mt.group(2)
                if lang not in ("html", "htm", "svg", "xml") and code.count("\n") < 14:
                    continue
                t = re.search(r"(?is)<title>(.*?)</title>", code)
                title = (t.group(1).strip() if t else "") or (
                    code.strip().splitlines()[0][:60] if code.strip() else lang)
                out.append({"chat_id": c["id"], "chat_title": c["title"], "lang": lang,
                            "title": title, "code": code[:40000], "lines": code.count("\n") + 1,
                            "updated": c["updated"], "key": f"{c['id']}:{mi}:{ai}"})
                if len(out) >= 120:
                    return out
    return out


# ── MCP: minimal stdio client (newline-delimited JSON-RPC 2.0) ───────────────
class MCPClient:
    def __init__(self, command, args=None, env=None):
        self.command = command; self.args = list(args or [])
        self.env = dict(env or {}); self.proc = None
        self._id = 0; self._lock = threading.Lock(); self.tools = []

    def start(self, timeout=25):
        e = os.environ.copy(); e.update({k: str(v) for k, v in self.env.items()})
        cmd = shutil.which(self.command) or self.command
        self.proc = subprocess.Popen(
            [cmd, *self.args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=e, text=True, bufsize=1,
            encoding="utf-8", errors="replace")
        self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                 "clientInfo": {"name": "cs-framework", "version": VERSION}},
                  timeout=timeout)
        self._notify("notifications/initialized")
        res = self._rpc("tools/list", {}, timeout=timeout) or {}
        self.tools = res.get("tools", [])
        return self.tools

    def _write(self, obj):
        self.proc.stdin.write(json.dumps(obj) + "\n"); self.proc.stdin.flush()

    def _notify(self, method, params=None):
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _rpc(self, method, params=None, timeout=30):
        with self._lock:
            self._id += 1; rid = self._id
            self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
            deadline = time.time() + timeout
            while time.time() < deadline:
                line = self.proc.stdout.readline()
                if not line:
                    if self.proc.poll() is not None:
                        raise RuntimeError("MCP server exited")
                    continue
                try: msg = json.loads(line)
                except Exception: continue
                if msg.get("id") == rid:
                    if "error" in msg: raise RuntimeError(str(msg["error"]))
                    return msg.get("result")
            raise TimeoutError("MCP timeout: " + method)

    def call_tool(self, name, arguments, timeout=180):
        res = self._rpc("tools/call", {"name": name, "arguments": arguments or {}},
                        timeout=timeout) or {}
        parts = [c.get("text", "") if c.get("type") == "text" else json.dumps(c)
                 for c in res.get("content", [])]
        return "\n".join(parts) if parts else json.dumps(res)

    def stop(self):
        try:
            if self.proc: self.proc.terminate()
        except Exception: pass


_MCP_CLIENTS = {}

def _mcp_get_client(server):
    sid = server.get("id")
    cl = _MCP_CLIENTS.get(sid)
    if cl and cl.proc and cl.proc.poll() is None:
        return cl
    cl = MCPClient(server.get("command"), server.get("args"), server.get("env"))
    cl.start(); _MCP_CLIENTS[sid] = cl
    return cl

def _mcp_all_tools(server_ids=None):
    tools = []
    for s in _mcp_cfg_load().get("servers", []):
        if server_ids is not None and s.get("id") not in server_ids: continue
        if not s.get("enabled", True): continue
        try:
            for t in _mcp_get_client(s).tools:
                tools.append({"server": s.get("id"), "name": t.get("name"),
                              "qualified": f"{s.get('id')}__{t.get('name')}",
                              "description": t.get("description", ""),
                              "schema": t.get("inputSchema", {})})
        except Exception as e:
            log(f"mcp {s.get('id')}: {e}", "warn")
    return tools

def _claude_desktop_mcp_path():
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"

def _mcp_import_claude_desktop():
    p = _claude_desktop_mcp_path()
    data = jload(p, None)
    if not data:
        raise FileNotFoundError(f"no Claude Desktop config at {p}")
    cfg = _mcp_cfg_load(); have = {s["id"] for s in cfg.get("servers", [])}
    added = []
    for name, spec in (data.get("mcpServers") or {}).items():
        sid = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or uuid.uuid4().hex[:6]
        if sid in have or not spec.get("command"):
            continue
        cfg.setdefault("servers", []).append({"id": sid, "name": name, "command": spec["command"],
                                              "args": spec.get("args", []), "env": spec.get("env", {}),
                                              "enabled": True})
        added.append(name)
    _mcp_cfg_save(cfg)
    return added

MCP_GALLERY = [
    {"id": "filesystem", "name": "Filesystem", "desc": "Read and write files in a folder you choose.",
     "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "{folder}"], "needs": "folder"},
    {"id": "memory", "name": "Memory", "desc": "A persistent knowledge graph the model can remember with.",
     "command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"]},
    {"id": "fetch", "name": "Fetch", "desc": "Fetch web pages and convert them to markdown.",
     "command": "uvx", "args": ["mcp-server-fetch"]},
    {"id": "git", "name": "Git", "desc": "Inspect and operate on a git repository.",
     "command": "uvx", "args": ["mcp-server-git", "--repository", "{folder}"], "needs": "folder"},
    {"id": "time", "name": "Time", "desc": "Current time and timezone conversion.",
     "command": "uvx", "args": ["mcp-server-time"]},
    {"id": "sequential-thinking", "name": "Sequential thinking", "desc": "Structured step-by-step reasoning.",
     "command": "npx", "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]},
]


# ── code workspace: file system API sandboxed to the chosen project root ─────
_FS_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
            ".pytest_cache", ".idea", ".next", ".DS_Store", ".tox", ".cache"}

def _fs_resolve(root, rel=""):
    r = Path(str(root or "")).expanduser()
    if not str(root or "") or not r.is_absolute():
        raise ValueError("project root must be an absolute path")
    r = r.resolve()
    p = (r / (rel or "")).resolve()
    if p != r and r not in p.parents:
        raise PermissionError("path is outside the project folder")
    return r, p

def _fs_list(root, rel=""):
    r, p = _fs_resolve(root, rel)
    if not p.is_dir():
        raise NotADirectoryError(str(p))
    out = []
    for c in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if c.name in _FS_SKIP:
            continue
        try: size = c.stat().st_size if c.is_file() else 0
        except Exception: continue
        out.append({"name": c.name, "path": c.relative_to(r).as_posix(), "dir": c.is_dir(), "size": size})
        if len(out) >= 1000:
            break
    return out

def _fs_read(root, rel):
    _, p = _fs_resolve(root, rel)
    if not p.is_file():
        raise FileNotFoundError(rel)
    size = p.stat().st_size
    if size > 2_000_000:
        return {"content": "", "size": size, "binary": True, "too_big": True}
    raw = p.read_bytes()
    if b"\x00" in raw[:8192]:
        return {"content": "", "size": size, "binary": True}
    return {"content": raw.decode("utf-8", "replace"), "size": size, "binary": False}

def _fs_write(root, rel, content):
    _, p = _fs_resolve(root, rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p.stat().st_size

def _fs_dirs(path=""):
    """Directory picker: list sub-folders of an absolute path (read-only)."""
    if not path:
        roots = [str(Path.home())]
        if os.name == "nt":
            import string
            roots += [f"{d}:\\" for d in string.ascii_uppercase if Path(f"{d}:\\").exists()]
        else:
            roots.append("/")
        return {"path": "", "parent": None, "dirs": [{"name": r, "path": r} for r in roots]}
    p = Path(path).expanduser().resolve()
    dirs = []
    try:
        for c in sorted(p.iterdir(), key=lambda x: x.name.lower()):
            if c.is_dir() and not c.name.startswith("."):
                dirs.append({"name": c.name, "path": str(c)})
    except Exception:
        pass
    parent = str(p.parent) if p.parent != p else None
    return {"path": str(p), "parent": parent, "dirs": dirs[:500]}


# ── built-in browser: fetch pages server-side and show them sandboxed ────────
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

def _web_get(url, timeout=20, limit=6_000_000):
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    req = urllib.request.Request(url, headers={
        "User-Agent": _BROWSER_UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.geturl(), r.headers.get("Content-Type", ""), r.read(limit)

def _decode_html(raw, ctype):
    m = re.search(r"charset=([\w-]+)", ctype or "", re.I)
    enc = m.group(1) if m else None
    if not enc:
        m2 = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", raw[:4096], re.I)
        enc = m2.group(1).decode("ascii", "ignore") if m2 else "utf-8"
    try: return raw.decode(enc, "replace")
    except LookupError: return raw.decode("utf-8", "replace")

def _html_to_text(html_src):
    import html as _h
    t = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_src)
    title = _h.unescape(t.group(1)).strip() if t else ""
    s = re.sub(r"(?is)<(script|style|noscript|svg|template|iframe)[^>]*>.*?</\1>", " ", html_src)
    s = re.sub(r"(?is)<(nav|footer|aside)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h[1-6]>|</li>|</tr>|</section>|</article>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n• ", s)
    s = re.sub(r"(?i)<h([1-6])[^>]*>", lambda m: "\n" + "#" * int(m.group(1)) + " ", s)
    s = _h.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n[ ]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return title, s

_BROWSE_SHIM = r"""<script>(function(){function go(u){try{parent.postMessage({cs:'nav',url:u},'*')}catch(e){}}
document.addEventListener('click',function(e){var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;if(!a)return;var h=a.getAttribute('href');if(!h||h.charAt(0)==='#'||/^(javascript|mailto|tel):/i.test(h))return;e.preventDefault();go(new URL(h,document.baseURI).href)},true);
document.addEventListener('submit',function(e){var f=e.target;if((f.method||'get').toLowerCase()!=='get')return;e.preventDefault();var u=new URL(f.getAttribute('action')||document.baseURI,document.baseURI);new FormData(f).forEach(function(v,k){u.searchParams.set(k,v)});go(u.href)},true);
function hi(){try{parent.postMessage({cs:'loaded',url:document.baseURI,title:document.title},'*')}catch(e){}}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',hi);else hi();})();</script>"""

def _browse_response(handler, url):
    from html import escape as _hesc
    try:
        final, ctype, raw = _web_get(url)
    except Exception as e:
        body = ("<!doctype html><meta charset=utf-8><body style='font:15px system-ui;padding:40px;"
                "color:#333'><h3>Couldn't open this page</h3><p>" + _hesc(str(e)[:300]) + "</p>")
        return _send_sandboxed(handler, body.encode("utf-8"), "text/html; charset=utf-8")
    if "html" in (ctype or "").lower() or not ctype:
        page = _decode_html(raw, ctype)
        page = re.sub(r"(?is)<meta[^>]+http-equiv=[\"']?content-security-policy[^>]*>", "", page)
        inject = '<base href="%s">%s' % (_hesc(final, quote=True), _BROWSE_SHIM)
        if re.search(r"(?i)<head[^>]*>", page):
            page = re.sub(r"(?i)(<head[^>]*>)", lambda m: m.group(1) + inject, page, count=1)
        else:
            page = inject + page
        return _send_sandboxed(handler, page.encode("utf-8"), "text/html; charset=utf-8")
    return _send_sandboxed(handler, raw, ctype)

def _send_sandboxed(handler, data, ctype):
    handler.send_response(200)
    handler.send_header("Content-Type", ctype or "application/octet-stream")
    handler.send_header("Content-Length", str(len(data)))
    # a sandboxed, opaque origin even if opened directly: page scripts can
    # never talk to this app's API
    handler.send_header("Content-Security-Policy", "sandbox allow-scripts allow-forms allow-popups")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


# ── extra agent tools: precise edits + readable browsing ─────────────────────
def _t_edit(a, cwd=None):
    path = a.get("path", "")
    p = Path(path) if Path(path).is_absolute() else Path(cwd or ".") / path
    old, new = a.get("old", ""), a.get("new", "")
    if not p.is_file():
        return "[edit: no such file " + str(p) + "]"
    text = p.read_text(encoding="utf-8", errors="replace")
    if not old:
        return "[edit: 'old' must be the exact text to replace]"
    n = text.count(old)
    if n == 0:
        return "[edit: 'old' text not found — read the file and copy it exactly]"
    if n > 1 and not a.get("all"):
        return f"[edit: 'old' text occurs {n} times — include more context or pass all:true]"
    p.write_text(text.replace(old, new) if a.get("all") else text.replace(old, new, 1),
                 encoding="utf-8")
    return f"edited {p} ({n if a.get('all') else 1} replacement)"

def _t_browse(a, cwd=None):
    final, ctype, raw = _web_get(a.get("url", ""))
    if "html" not in (ctype or "").lower():
        return f"{final}\n[{ctype}, {len(raw)} bytes]\n" + raw[:4000].decode("utf-8", "replace")
    title, text = _html_to_text(_decode_html(raw, ctype))
    return f"# {title}\n{final}\n\n{text[:14000]}"

TOOLS_IMPL.update({"edit": _t_edit, "browse": _t_browse})

_TOOLSETS = {
    "code": ["bash", "read", "write", "edit", "ls", "glob", "grep", "python"],
    "web": ["browse", "download"],
    "computer": ["computer", "open", "bash"],
    "blender": ["blender"],
}
# tools that change something ask first (computer/blender decide per action)
_APPROVAL_TOOLS = {"bash", "write", "append", "edit", "python", "download", "extract",
                   "clip_write", "open"}


def _computer_status():
    need = {"mss": "mss", "pyautogui": "pyautogui", "PIL": "pillow"}
    missing = [pip for mod, pip in need.items() if importlib.util.find_spec(mod) is None]
    return {"available": not missing, "missing": missing,
            "frozen": bool(getattr(sys, "frozen", False)),
            "ocr": importlib.util.find_spec("pytesseract") is not None and bool(shutil.which("tesseract"))}


# ── jobs: long-running installs / downloads, run as `cs <subcommand>` ────────
_PROGRESS_RX = re.compile(r"\d+(\.\d+)?%|[█▓▒░#]{4,}")

def _job_start(title, steps, watch_dir=None):
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "title": title, "status": "running", "log": [], "step": 0,
           "steps": len(steps), "started": time.time(),
           "watch_dir": str(watch_dir) if watch_dir else None}
    _JOBS[jid] = job

    def run():
        try:
            for i, argv in enumerate(steps):
                job["step"] = i + 1
                env = os.environ.copy()
                env.update({"CS_NO_COLOR": "1", "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
                proc = subprocess.Popen(_self_invoke(*argv), stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        text=True, encoding="utf-8", errors="replace",
                                        env=env, cwd=str(_app_dir()))
                job["pid"] = proc.pid
                for line in proc.stdout:
                    line = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", line).rstrip()
                    if not line.strip():
                        continue
                    if (_PROGRESS_RX.search(line) and job["log"]
                            and _PROGRESS_RX.search(job["log"][-1])):
                        job["log"][-1] = line[-240:]
                    else:
                        job["log"].append(line[-240:])
                    job["log"] = job["log"][-200:]
                rc = proc.wait()
                if rc != 0:
                    raise RuntimeError(f"step {i + 1} failed (exit {rc})")
            job["status"] = "done"
        except Exception as e:
            job["status"], job["error"] = "error", str(e)
        finally:
            job["ended"] = time.time()
            try: load_scan(rescan=True)
            except Exception: pass

    threading.Thread(target=run, daemon=True).start()
    return job

def _job_public(job):
    j = {k: v for k, v in job.items() if k != "watch_dir"}
    wd = job.get("watch_dir")
    if wd and Path(wd).exists():
        try: j["bytes"] = sum(f.stat().st_size for f in Path(wd).rglob("*") if f.is_file())
        except Exception: pass
    return j

CODER_PRESETS = {
    "small": {"repo": "bartowski/Qwen2.5-Coder-1.5B-Instruct-GGUF", "only": "*Q4_K_M.gguf",
              "label": "Qwen2.5-Coder 1.5B", "size": "1.1 GB", "hint": "Runs on any laptop"},
    "medium": {"repo": "bartowski/Qwen2.5-Coder-7B-Instruct-GGUF", "only": "*Q4_K_M.gguf",
               "label": "Qwen2.5-Coder 7B", "size": "4.7 GB", "hint": "8 GB+ RAM, good quality"},
    "large": {"repo": "bartowski/Qwen2.5-Coder-14B-Instruct-GGUF", "only": "*Q4_K_M.gguf",
              "label": "Qwen2.5-Coder 14B", "size": "9 GB", "hint": "16 GB+ RAM or a GPU"},
}

def _coder_setup(preset):
    p = CODER_PRESETS.get(preset)
    if not p:
        raise ValueError("unknown preset")
    steps = []
    try:
        have_server = LlamaServerRT().available()[0]
    except Exception:
        have_server = False
    if not have_server:
        steps.append(["install", "llamacpp-bin"])
    steps.append(["pull", p["repo"], "--only", p["only"]])
    steps.append(["scan"])
    CFG.setdefault("prefs", {})["code_model_hint"] = p["repo"].split("/")[-1]
    save_cfg()
    return _job_start("Set up local coder · " + p["label"], steps,
                      watch_dir=DL_D / "hf" / p["repo"].replace("/", "__"))


# ══ Spark X: free models · hardware · Ollama · model catalog ═════════════════
def _pref(key, default=None):
    return CFG.get("prefs", {}).get(key, default)


# ── free cloud models (no signup) ────────────────────────────────────────────
# Services that officially offer anonymous, keyless access to an OpenAI-
# compatible endpoint. Nothing here scrapes a website or creates accounts. The
# list can be updated without a release through the remote catalog, and a
# service that stops answering is simply skipped (requests fail over).
FREE_PROVIDERS = [
    {"id": "pollinations", "name": "Pollinations", "home": "https://pollinations.ai",
     "base_url": "https://text.pollinations.ai/openai", "probe": "https://text.pollinations.ai/models",
     "prefer": ["openai", "openai-fast", "mistral", "qwen-coder", "llama"]},
    {"id": "llm7", "name": "LLM7", "home": "https://llm7.io",
     "base_url": "https://api.llm7.io/v1", "probe": "https://api.llm7.io/v1/models",
     "prefer": ["gpt-4.1-nano", "gpt-4o-mini", "mistral-small", "qwen", "llama", "deepseek"]},
]
_FREE = {"ts": 0.0, "results": [], "lock": threading.Lock(), "last_good": None}


def _free_providers():
    env = os.environ.get("SPARKX_FREE_PROVIDERS")          # tests / power users
    if env:
        try:
            return json.loads(env)
        except Exception:
            pass
    remote = (_CATALOG.get("data") or {}).get("free_providers")
    if isinstance(remote, list) and remote and all(isinstance(x, dict) and x.get("base_url") for x in remote):
        return remote
    return FREE_PROVIDERS


def _free_models_from(payload):
    items = payload.get("data") if isinstance(payload, dict) else payload
    if items is None and isinstance(payload, dict):
        items = payload.get("models", [])
    out = []
    for m in items or []:
        if isinstance(m, dict):
            mid = m.get("id") or m.get("name")
            outs = " ".join(str(x) for x in (m.get("output_modalities") or []))
            if not mid or (outs and "text" not in outs):
                continue
            out.append({"id": str(mid), "vision": bool(m.get("vision")) or "image" in " ".join(
                str(x) for x in (m.get("input_modalities") or [])), "tools": m.get("tools")})
        elif isinstance(m, str):
            out.append({"id": m, "vision": False, "tools": None})
    return [m for m in out if not any(b in m["id"].lower() for b in _NON_CHAT)]


def _free_pick(models, prefer):
    ids = [m["id"] for m in models]
    for p in prefer or []:
        for m in models:
            if m["id"].lower() == p or m["id"].lower().startswith(p):
                return m
    return models[0] if ids else None


def _free_probe(force=False, timeout=6.0):
    """Which free services answer right now (only their public model lists
    are fetched — no prompts are sent). Cached for 10 minutes."""
    with _FREE["lock"]:
        if not force and _FREE["results"] and time.time() - _FREE["ts"] < 600:
            return _FREE["results"]

    def one(fp):
        t0 = time.time()
        try:
            models = _free_models_from(_http_json(fp["probe"], timeout=timeout))
            pick = _free_pick(models, fp.get("prefer"))
            if not pick:
                raise RuntimeError("no chat models listed")
            return {"id": fp["id"], "name": fp["name"], "home": fp.get("home", ""), "ok": True,
                    "latency_ms": int((time.time() - t0) * 1000), "model": pick["id"],
                    "vision": bool(pick.get("vision")), "models": [m["id"] for m in models][:40]}
        except Exception as e:
            return {"id": fp["id"], "name": fp["name"], "home": fp.get("home", ""), "ok": False,
                    "error": str(e)[:160]}

    import concurrent.futures as _cf
    provs = _free_providers()
    with _cf.ThreadPoolExecutor(max_workers=max(1, len(provs))) as ex:
        res = list(ex.map(one, provs))
    res.sort(key=lambda r: (not r["ok"], r.get("latency_ms", 1e9)))
    with _FREE["lock"]:
        _FREE["results"], _FREE["ts"] = res, time.time()
    return res


def _free_enabled():
    return bool((CFG.get("platforms", {}).get("free") or {}).get("free_auto"))


def _free_enable():
    res = _free_probe(force=True)
    CFG.setdefault("platforms", {})["free"] = {
        "name": "Free", "provider": "free", "free_auto": True, "no_key": True,
        "base_url": "auto", "models": ["auto"], "model": "auto"}
    prefs = CFG.setdefault("prefs", {})
    if not prefs.get("default_model") or prefs.get("default_model") == DEMO_MODEL_ID:
        prefs["default_model"] = "free/auto"
    save_cfg()
    return res


class FreeRT(OpenAIRT):
    """`free/auto`: the fastest free service that answers, failing over to
    the next one when a service is down or rate-limited."""
    def available(self):
        return True, ""

    def chat(self, r, msgs, ctx, tools=None):
        ok = [x for x in _free_probe() if x.get("ok")] or [x for x in _free_probe(force=True) if x.get("ok")]
        if not ok:
            raise ProviderError("No free AI service is reachable right now. Try again in a minute, connect a "
                                "free-tier key in Settings → Providers, or run a local model with Ollama.")
        ok.sort(key=lambda x: x["id"] != _FREE.get("last_good"))
        bases = {f["id"]: f["base_url"] for f in _free_providers()}
        errors = []
        for fp in ok:
            started = False
            try:
                for ev in _openai_chat(bases[fp["id"]], fp["model"], None, fp["name"], msgs, ctx, tools):
                    if not started:
                        started = True
                        _FREE["last_good"] = fp["id"]
                        yield ("provider", fp["name"])
                    yield ev
                return
            except ProviderError as e:
                if started or (tools and _tools_unsupported(e)):
                    raise
                errors.append(str(e))
        raise ProviderError("The free AI services didn't answer: " + " · ".join(errors[:3]))


def _tools_unsupported(e):
    code = getattr(e, "code", 0)
    return code in (400, 404, 422, 501) and bool(re.search(r"tool|function", str(e), re.I))


# ── hardware ─────────────────────────────────────────────────────────────────
_HW = {}

def _total_ram_bytes():
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, ValueError, OSError):
        pass
    if os.name == "nt":
        try:
            import ctypes
            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = _MS(); st.dwLength = ctypes.sizeof(_MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return int(st.ullTotalPhys)
        except Exception:
            return 0
    try:
        return int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True,
                                  timeout=5).stdout.strip() or 0)
    except Exception:
        return 0


def _hardware():
    if _HW:
        return _HW
    ram = _total_ram_bytes()
    vram, gpu = 0.0, ""
    if shutil.which("nvidia-smi"):
        rc, out = run_cmd(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], timeout=10)
        if rc == 0:
            for line in out.strip().splitlines():
                parts = [x.strip() for x in line.split(",")]
                if len(parts) >= 2:
                    try:
                        mib = float(parts[1])
                    except ValueError:
                        continue
                    if mib / 1024 > vram:
                        vram, gpu = mib / 1024, parts[0]
    apple = sys.platform == "darwin" and platform.machine() == "arm64"
    _HW.update({"ram_gb": round(ram / 2 ** 30, 1), "vram_gb": round(vram, 1),
                "gpu": gpu or ("Apple Silicon (unified memory)" if apple else ""),
                "apple_silicon": apple, "cpu_threads": os.cpu_count() or 0,
                "os": {"win32": "Windows", "darwin": "macOS"}.get(sys.platform, "Linux")})
    return _HW


# ── Ollama: detect, start, keep alive ("revive"), pull, delete ──────────────
_OLLAMA = {"proc": None, "started_by_us": False, "revived": 0, "fails": 0, "ever_up": False,
           "lock": threading.Lock(), "caps": {}, "last_error": ""}


def _ollama_base():
    h = (os.environ.get("OLLAMA_HOST") or "127.0.0.1:11434").strip()
    if not re.match(r"^https?://", h):
        h = "http://" + h
    h = h.replace("://0.0.0.0", "://127.0.0.1")
    if not re.search(r":\d+$", h.split("//", 1)[-1]):
        h += ":11434"
    return h.rstrip("/")


def _ollama_bin():
    w = shutil.which("ollama")
    if w:
        return w
    cands = []
    if os.name == "nt":
        la = os.environ.get("LOCALAPPDATA", "")
        if la:
            cands.append(Path(la) / "Programs" / "Ollama" / "ollama.exe")
        cands.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Ollama" / "ollama.exe")
    elif sys.platform == "darwin":
        cands += [Path("/Applications/Ollama.app/Contents/Resources/ollama"),
                  Path("/opt/homebrew/bin/ollama"), Path("/usr/local/bin/ollama")]
    else:
        cands += [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama"), Path.home() / ".local/bin/ollama"]
    for c in cands:
        if c.is_file():
            return str(c)
    return None


def _ollama_req(path, body=None, timeout=3.0, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(_ollama_base() + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with _urlopen(req, timeout) as r:
        raw = r.read()
    return json.loads(raw or b"{}")


def _ollama_version(timeout=1.5):
    try:
        v = _ollama_req("/api/version", timeout=timeout).get("version") or "?"
    except Exception:
        return None
    _OLLAMA["ever_up"] = True
    return v


def _ollama_caps(name):
    """Capabilities of an installed model (vision, tools, thinking), from /api/show."""
    if name in _OLLAMA["caps"]:
        return _OLLAMA["caps"][name]
    caps = []
    try:
        caps = _ollama_req("/api/show", {"model": name, "name": name}, timeout=4).get("capabilities") or []
    except Exception:
        pass
    _OLLAMA["caps"][name] = caps
    return caps


def _ollama_status():
    ver = _ollama_version()
    exe = _ollama_bin()
    st = {"installed": bool(exe) or ver is not None, "bin": exe or "", "running": ver is not None,
          "version": ver or "", "managed": _OLLAMA["started_by_us"], "revived": _OLLAMA["revived"],
          "keep_alive": bool(_pref("ollama_keep_alive", True)), "base_url": _ollama_base(),
          "error": _OLLAMA["last_error"], "models": []}
    if ver:
        try:
            for m in _ollama_req("/api/tags", timeout=4).get("models", []):
                d = m.get("details") or {}
                name = m.get("name") or m.get("model")
                st["models"].append({"name": name, "size": m.get("size", 0), "size_h": human(m.get("size", 0)),
                                     "params": d.get("parameter_size", ""), "quant": d.get("quantization_level", ""),
                                     "family": d.get("family", ""), "caps": _ollama_caps(name)})
        except Exception as e:
            st["error"] = str(e)[:200]
    return st


def _ollama_start(wait=30.0):
    """Start `ollama serve` in the background (or the Ollama app on macOS)
    and wait until the API answers."""
    with _OLLAMA["lock"]:
        if _ollama_version(1.0):
            return True, "running"
        exe = _ollama_bin()
        proc = None
        if exe:
            APP_D.mkdir(parents=True, exist_ok=True)
            logf = open(APP_D / "ollama.log", "ab")
            kw = dict(stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            if os.name == "nt":
                kw["creationflags"] = 0x08000000 | 0x00000200     # no window, own process group
            else:
                kw["start_new_session"] = True                    # survives Spark X closing
            proc = subprocess.Popen([exe, "serve"], **kw)
            _OLLAMA["proc"], _OLLAMA["started_by_us"] = proc, True
        elif sys.platform == "darwin" and Path("/Applications/Ollama.app").exists():
            subprocess.Popen(["open", "-ga", "Ollama"])
        else:
            _OLLAMA["last_error"] = "Ollama isn't installed"
            return False, _OLLAMA["last_error"]
        deadline = time.time() + wait
        while time.time() < deadline:
            if _ollama_version(1.0):
                _LOCAL_PROBE["ts"] = 0.0
                _OLLAMA["last_error"] = ""
                return True, "started"
            if proc is not None and proc.poll() is not None:
                try:
                    tail = (APP_D / "ollama.log").read_text(encoding="utf-8", errors="replace")[-400:]
                except Exception:
                    tail = ""
                _OLLAMA["last_error"] = "ollama serve exited: " + tail.strip().splitlines()[-1] if tail.strip() else "ollama serve exited"
                return False, _OLLAMA["last_error"]
            time.sleep(0.4)
        _OLLAMA["last_error"] = "Ollama didn't start within %d s" % wait
        return False, _OLLAMA["last_error"]


def _ollama_watchdog():
    """Start Ollama when Spark X opens and bring it back if it dies."""
    every = float(os.environ.get("SPARKX_WATCHDOG_S") or 12)
    backoff = every
    while not _APP_SCHED["stop"]:
        was_up = _OLLAMA["ever_up"]                 # seen running at any point this session
        up = _ollama_version(1.5) is not None
        if up:
            backoff, _OLLAMA["fails"] = every, 0
        elif _pref("ollama_keep_alive", True) and (_ollama_bin() or was_up) and \
                (was_up or _pref("ollama_autostart", True)):
            ok, msg = _ollama_start()
            if ok:
                if was_up:
                    _OLLAMA["revived"] += 1
                    log("ollama revived")
                _autodetect_local(force=True)
            else:
                _OLLAMA["fails"] += 1
                backoff = min(300, every * (2 ** min(_OLLAMA["fails"], 5)))
                log(f"ollama start failed: {msg}", "warn")
        end = time.time() + backoff
        while time.time() < end:
            if _APP_SCHED["stop"]:
                return
            time.sleep(min(1.0, backoff))


def _ollama_pull(name):
    name = str(name or "").strip()
    if not re.match(r"^[\w./:@-]+$", name):
        raise ValueError("not a valid model name")
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "title": "Download " + name, "status": "running", "log": [], "step": 1, "steps": 1,
           "started": time.time(), "progress": 0.0, "kind": "ollama-pull", "model": name, "cancel": False}
    _JOBS[jid] = job

    def run():
        try:
            if not _ollama_version(1.5):
                ok, msg = _ollama_start()
                if not ok:
                    raise RuntimeError(msg)
            req = urllib.request.Request(_ollama_base() + "/api/pull",
                                         data=json.dumps({"model": name, "name": name, "stream": True}).encode(),
                                         headers={"Content-Type": "application/json"})
            with _urlopen(req, 300) as r:
                for raw in r:
                    if job["cancel"]:
                        raise RuntimeError("cancelled")
                    try:
                        d = json.loads(raw)
                    except Exception:
                        continue
                    if d.get("error"):
                        raise RuntimeError(d["error"])
                    status = d.get("status", "")
                    if d.get("total"):
                        job["progress"] = round(d.get("completed", 0) / d["total"], 4)
                        status += f" · {human(d.get('completed', 0))} / {human(d['total'])}"
                    if job["log"] and job["log"][-1].split(" · ")[0] == status.split(" · ")[0]:
                        job["log"][-1] = status
                    else:
                        job["log"].append(status)
                    job["log"] = job["log"][-60:]
            job["status"], job["progress"] = "done", 1.0
            _OLLAMA["caps"].pop(name, None)
            _autodetect_local(force=True)
        except Exception as e:
            job["status"], job["error"] = "error", str(e)[:300]
        finally:
            job["ended"] = time.time()

    threading.Thread(target=run, daemon=True).start()
    return job


def _ollama_delete(name):
    _ollama_req("/api/delete", {"model": name, "name": name}, timeout=20, method="DELETE")
    _OLLAMA["caps"].pop(name, None)
    _autodetect_local(force=True)


# ── model catalog: curated picks + live trending ─────────────────────────────
CATALOG_URL = "https://raw.githubusercontent.com/qulyttvv-beep/cs-framework-v4/main/cs_studio/static/catalog.json"
_CATALOG = {"data": None, "source": "", "ts": 0.0, "fetching": False}
_TRENDING = {"ts": 0.0, "data": []}


def _catalog_newer(a, b):
    """True when catalog a is newer than b (by its `updated` date)."""
    return str((a or {}).get("updated", "")) > str((b or {}).get("updated", ""))


def _catalog():
    if _CATALOG["data"] is None:
        base = _studio_static_dir()
        bundled = jload(base / "catalog.json", None) if base else None
        cached = jload(APP_D / "catalog.json", None)
        if cached and cached.get("models") and _catalog_newer(cached, bundled):
            _CATALOG.update(data=cached, source="updated")
        else:
            _CATALOG.update(data=bundled or {"models": []}, source="bundled")
    stale = time.time() - (_CATALOG["ts"] or 0) > 86400
    if stale and not _CATALOG["fetching"] and not os.environ.get("SPARKX_OFFLINE"):
        _CATALOG["fetching"] = True
        threading.Thread(target=_catalog_refresh, daemon=True).start()
    return _CATALOG["data"]


def _catalog_refresh():
    try:
        d = _http_json(os.environ.get("SPARKX_CATALOG_URL") or CATALOG_URL, timeout=8)
        if isinstance(d, dict) and isinstance(d.get("models"), list) and d["models"]:
            if _catalog_newer(d, _CATALOG["data"]):
                _CATALOG.update(data=d, source="updated")
            jsave(APP_D / "catalog.json", d)
    except Exception as e:
        log(f"catalog refresh: {e}", "warn")
    finally:
        _CATALOG["ts"] = time.time()
        _CATALOG["fetching"] = False


def _catalog_view():
    data = _catalog()
    hw = _hardware()
    ram, vram, apple = hw["ram_gb"] or 8, hw["vram_gb"], hw["apple_silicon"]
    installed = set()
    ost = None
    if _ollama_version(1.0):
        try:
            ost = _ollama_req("/api/tags", timeout=4).get("models", [])
            for m in ost:
                n = m.get("name", "")
                installed |= {n, n[:-7] if n.endswith(":latest") else n + ":latest"}
        except Exception:
            pass
    models = []
    for m in data.get("models", []):
        m = dict(m)
        need = float(m.get("min_ram", 8))
        m["fits"] = need <= max(ram, vram) + 0.5
        m["fast"] = (vram >= float(m.get("size_gb", 99)) * 1.2) or (apple and float(m.get("size_gb", 99)) <= ram * 0.55)
        m["installed"] = m.get("id") in installed
        models.append(m)
    best = {}
    for m in models:
        if not m["fits"]:
            continue
        for tag in ("general", "coding", "vision", "reasoning", "computer"):
            if tag in (m.get("tags") or []) or (tag == "general" and "general" not in m.get("tags", [])
                                                  and "chat" in m.get("tags", [])):
                cur = best.get(tag)
                if cur is None or m.get("score", 0) > cur.get("score", 0):
                    best[tag] = m
    for tag, m in best.items():
        m.setdefault("best_for", []).append(tag)
    return {"hardware": hw, "updated": data.get("updated", ""), "source": _CATALOG["source"],
            "models": models, "ollama": bool(ost is not None)}


def _hf_trending(limit=24):
    """Trending GGUF models on Hugging Face (official public API), cached 1 h.
    Each one can be pulled into Ollama as hf.co/<repo>."""
    if _TRENDING["data"] and time.time() - _TRENDING["ts"] < 3600:
        return _TRENDING["data"]
    base = os.environ.get("SPARKX_HF_API") or "https://huggingface.co/api/models"
    items = None
    for sort in ("trendingScore", "downloads"):
        try:
            items = _http_json(f"{base}?filter=gguf&sort={sort}&direction=-1&limit=60", timeout=8)
            break
        except Exception as e:
            err = e
    if items is None:
        raise RuntimeError(f"Hugging Face didn't answer: {err}")
    out = []
    for m in items if isinstance(items, list) else []:
        rid = m.get("id") or m.get("modelId")
        pt = m.get("pipeline_tag") or ""
        if not rid or (pt and pt not in ("text-generation", "image-text-to-text")):
            continue
        out.append({"id": rid, "pull": "hf.co/" + rid, "likes": m.get("likes", 0),
                    "downloads": m.get("downloads", 0), "created": str(m.get("createdAt", ""))[:10],
                    "vision": pt == "image-text-to-text"})
        if len(out) >= limit:
            break
    _TRENDING.update(ts=time.time(), data=out)
    return out


# ══ Spark X: using the computer ══════════════════════════════════════════════
_CU_STATE = {"geom": None, "lock": threading.Lock()}
_WEBVIEW = {"window": None}


def _cu_capture(max_w=None):
    """Screenshot of the primary screen, scaled for the model. Returns
    (path, shot_w, shot_h). The cursor is drawn on the image so the model
    can see where the mouse is; coordinates the model gives back are in this
    image's pixel space and mapped to real screen coordinates."""
    import mss
    from PIL import Image, ImageDraw
    pg = _pyautogui()
    with (getattr(mss, "MSS", None) or mss.mss)() as sct:
        mon = sct.monitors[1]
        raw = sct.grab(mon)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    lw, lh = (pg.size() if pg else (mon["width"], mon["height"]))
    mw = int(max_w or _pref("computer_shot_width", 1280) or 1280)
    tw = max(320, min(mw, lw))
    th = max(200, round(lh * tw / lw))
    img = img.resize((tw, th), Image.LANCZOS)
    if pg:
        try:
            cx, cy = pg.position()
            x, y = cx * tw / lw, cy * th / lh
            d = ImageDraw.Draw(img)
            d.ellipse((x - 9, y - 9, x + 9, y + 9), outline=(0, 0, 0), width=4)
            d.ellipse((x - 9, y - 9, x + 9, y + 9), outline=(255, 255, 255), width=2)
            d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(230, 60, 40))
        except Exception:
            pass
    d = _ensure_screen_dir()
    path = d / f"screen_{int(time.time() * 1000)}.jpg"
    img.save(path, "JPEG", quality=72, optimize=True)
    try:
        shots = sorted(d.glob("screen_*.jpg"))
        for old in shots[:-80]:
            old.unlink()
    except Exception:
        pass
    _CU_STATE["geom"] = (tw, th, lw, lh)
    return str(path), tw, th


def _cu_point(a, kx="x", ky="y"):
    if _CU_STATE["geom"] is None:
        _cu_capture()
    tw, th, lw, lh = _CU_STATE["geom"]
    try:
        x, y = float(a[kx]), float(a[ky])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"'{kx}' and '{ky}' (pixels in the last screenshot) are required")
    x, y = min(max(x, 0), tw - 1), min(max(y, 0), th - 1)
    return round(x * lw / tw), round(y * lh / th)


_KEY_ALIASES = {"cmd": "command", "super": "win", "meta": "win", "windows": "win", "control": "ctrl",
                "return": "enter", "esc": "escape", "del": "delete", "pgup": "pageup", "pgdn": "pagedown",
                "arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right",
                "option": "alt", "opt": "alt", "spacebar": "space", "bksp": "backspace", "ins": "insert"}


def _norm_keys(keys):
    if isinstance(keys, (list, tuple)):
        parts = [str(k) for k in keys]
    else:
        parts = re.split(r"\s*\+\s*", str(keys or "").strip())
    out = []
    for p in parts:
        k = p.strip().lower()
        if not k:
            continue
        k = _KEY_ALIASES.get(k, k)
        if k == "win" and sys.platform == "darwin":
            k = "command"
        elif k == "command" and sys.platform != "darwin":
            k = "ctrl"                     # "cmd+c" means ctrl+c off a Mac
        out.append(k)
    return out


def _cu_type(pg, text):
    if not text:
        return
    if all(32 <= ord(c) < 127 or c in "\n\t" for c in text) and len(text) <= 400:
        pg.write(text, interval=0.006)
        return
    try:                                   # unicode / long text: paste it
        import pyperclip
        prev = None
        try:
            prev = pyperclip.paste()
        except Exception:
            pass
        pyperclip.copy(text)
        pg.hotkey("command" if sys.platform == "darwin" else "ctrl", "v")
        time.sleep(0.25)
        if prev is not None:
            pyperclip.copy(prev)
    except Exception:
        pg.write(text, interval=0.006)


def _self_window(action):
    """Minimize / restore the Spark X window so it isn't in the way while
    the model uses the computer."""
    w = _WEBVIEW.get("window")
    try:
        if w is not None:
            getattr(w, action)()
            return True
        if os.name == "nt":
            import pygetwindow as gw
            wins = [x for x in gw.getWindowsWithTitle(APP_UI) if x.title.strip() == APP_UI]
            for x in wins:
                x.minimize() if action == "minimize" else x.restore()
            return bool(wins)
    except Exception:
        pass
    return False


_CU_READONLY = ("screenshot", "cursor_position", "wait")


def _t_computer(a, cwd=None):
    act = str(a.get("action") or "screenshot").strip().lower().replace(" ", "_").replace("-", "_")
    act = {"left_click": "click", "screen": "screenshot", "mouse_move": "move", "press": "key",
           "hotkey": "key", "write": "type", "sleep": "wait"}.get(act, act)
    if act == "screenshot":
        path, tw, th = _cu_capture()
        return {"text": f"Screenshot {tw}×{th}. Use coordinates in this image.", "image": path}
    pg = _pyautogui()
    if pg is None:
        return {"text": "[computer use needs pyautogui, mss and pillow: Settings → Computer use]"}
    with _CU_STATE["lock"]:
        if act in ("click", "double_click", "right_click", "middle_click", "triple_click"):
            x, y = _cu_point(a)
            button = {"right_click": "right", "middle_click": "middle"}.get(act, a.get("button", "left"))
            clicks = {"double_click": 2, "triple_click": 3}.get(act, int(a.get("clicks", 1) or 1))
            pg.click(x, y, clicks=clicks, interval=0.08, button=button)
            did = f"{act.replace('_', ' ')} at ({a.get('x')}, {a.get('y')})"
        elif act == "move":
            x, y = _cu_point(a)
            pg.moveTo(x, y, duration=0.15)
            did = f"moved to ({a.get('x')}, {a.get('y')})"
        elif act == "drag":
            x, y = _cu_point(a)
            x2, y2 = _cu_point(a, "to_x", "to_y")
            pg.moveTo(x, y, duration=0.1)
            pg.dragTo(x2, y2, duration=0.45, button=a.get("button", "left"))
            did = f"dragged to ({a.get('to_x')}, {a.get('to_y')})"
        elif act == "scroll":
            if a.get("x") is not None and a.get("y") is not None:
                pg.moveTo(*_cu_point(a), duration=0.1)
            n = int(a.get("amount", 5) or 5)
            direction = str(a.get("direction", "down")).lower()
            if direction in ("left", "right"):
                pg.hscroll(n * (1 if direction == "right" else -1) * (1 if sys.platform == "darwin" else 60))
            else:
                pg.scroll(n * (1 if direction == "up" else -1) * (1 if sys.platform == "darwin" else 60))
            did = f"scrolled {direction} {n}"
        elif act == "type":
            text = str(a.get("text", ""))
            _cu_type(pg, text)
            did = f"typed {len(text)} characters"
        elif act == "key":
            keys = _norm_keys(a.get("keys") or a.get("key") or a.get("text"))
            if not keys:
                return {"text": "[key: give keys, e.g. 'enter' or 'ctrl+s']"}
            pg.hotkey(*keys) if len(keys) > 1 else pg.press(keys[0])
            did = "pressed " + "+".join(keys)
        elif act == "wait":
            secs = min(max(float(a.get("seconds", 1) or 1), 0.1), 30)
            time.sleep(secs)
            did = f"waited {secs:g}s"
        elif act == "cursor_position":
            if _CU_STATE["geom"] is None:
                _cu_capture()
            tw, th, lw, lh = _CU_STATE["geom"]
            cx, cy = pg.position()
            return {"text": f"mouse at ({round(cx * tw / lw)}, {round(cy * th / lh)}) in screenshot pixels"}
        else:
            return {"text": f"[unknown action '{act}'. Use screenshot, click, double_click, right_click, "
                            "move, drag, scroll, type, key, wait]"}
    if a.get("screenshot", True) is False:
        return {"text": did}
    time.sleep(float(_pref("computer_settle", 0.6) or 0.6))
    path, tw, th = _cu_capture()
    return {"text": did + f". New screenshot {tw}×{th} attached.", "image": path}


def _t_open(a, cwd=None):
    """Open a file, folder, URL or app with the system's default handler."""
    target = str(a.get("target") or a.get("path") or a.get("url") or a.get("app") or "").strip()
    if not target:
        return "[open: give a file, folder, URL or app name]"
    if target.lower() in ("blender", "blender.exe") and _blender_bin():
        subprocess.Popen([_blender_bin()], **_detached())
        return "opened Blender"
    p = Path(target).expanduser()
    if cwd and not p.is_absolute() and (Path(cwd) / p).exists():
        p = Path(cwd) / p
    is_url = bool(re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I)) and not re.match(r"^[a-z]:[\\/]", target, re.I)
    try:
        if os.name == "nt":
            if p.exists() or is_url:
                os.startfile(str(p) if p.exists() else target)
            else:
                subprocess.Popen(["cmd", "/c", "start", "", target], **_detached())
        elif sys.platform == "darwin":
            if p.exists() or is_url:
                subprocess.Popen(["open", str(p) if p.exists() else target])
            else:
                subprocess.Popen(["open", "-a", target])
        else:
            if p.exists() or is_url:
                subprocess.Popen(["xdg-open", str(p) if p.exists() else target], **_detached())
            else:
                exe = shutil.which(target)
                if not exe:
                    return f"[open: no app called '{target}' on PATH]"
                subprocess.Popen([exe], **_detached())
        return f"opened {target}"
    except Exception as e:
        return f"[open failed: {e}]"


def _detached():
    if os.name == "nt":
        return {"creationflags": 0x00000008 | 0x00000200, "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    return {"start_new_session": True, "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


# ══ Spark X: Blender ═════════════════════════════════════════════════════════
BLENDER_PRELUDE = r'''
import bpy, bmesh, math, os, sys
import mathutils
from mathutils import Vector, Euler, Matrix
OUT = os.environ.get("SPARKX_OUT") or os.getcwd()
os.makedirs(OUT, exist_ok=True)
_SPARKX = {"saved": None, "images": []}

def clear_scene():
    """Delete every object (and orphaned meshes, materials, lights, cameras)."""
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras, bpy.data.curves):
        for block in list(coll):
            if block.users == 0:
                coll.remove(block)

def material(name, color=(0.8, 0.8, 0.8), metallic=0.0, roughness=0.5, emission=None, strength=1.0):
    """A Principled BSDF material (reused if the name exists)."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if getattr(m, "node_tree", None) is None:        # Blender 5 materials have nodes already
        m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    color = tuple(color) + ((1.0,) if len(color) == 3 else ())
    if b:
        b.inputs["Base Color"].default_value = color
        b.inputs["Metallic"].default_value = metallic
        b.inputs["Roughness"].default_value = roughness
        if emission is not None:
            e = tuple(emission) + ((1.0,) if len(emission) == 3 else ())
            b.inputs["Emission Color" if "Emission Color" in b.inputs else "Emission"].default_value = e
            if "Emission Strength" in b.inputs:
                b.inputs["Emission Strength"].default_value = strength
    m.diffuse_color = color
    return m

def assign(obj, mat):
    """Give obj the material mat (replacing its first slot)."""
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
    return obj

def look_at(obj, target=(0, 0, 0)):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()

def _link(obj):
    bpy.context.scene.collection.objects.link(obj)
    return obj

def add_camera(location=(7.5, -7.5, 5.5), target=(0, 0, 0.5), lens=50):
    cam = _link(bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera")))
    cam.data.lens = lens
    cam.location = location
    look_at(cam, target)
    bpy.context.scene.camera = cam
    return cam

def add_sun(strength=3.0, rotation=(math.radians(50), 0, math.radians(30))):
    sun = _link(bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN")))
    sun.data.energy = strength
    sun.rotation_euler = rotation
    return sun

def add_area_light(location=(4, -4, 6), size=5.0, power=800.0, target=(0, 0, 0)):
    lamp = _link(bpy.data.objects.new("Area", bpy.data.lights.new("Area", "AREA")))
    lamp.data.size, lamp.data.energy = size, power
    lamp.location = location
    look_at(lamp, target)
    return lamp

def _engine_id(name):
    items = bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items.keys()
    name = (name or "EEVEE").upper()
    if name.startswith("EEVEE"):
        for cand in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            if cand in items:
                return cand
    if name.startswith("WORK"):
        return "BLENDER_WORKBENCH"
    return "CYCLES"

def render(path=None, engine="EEVEE", samples=64, size=(1280, 720)):
    """Render the scene camera to a PNG (Spark X switches to Cycles on
    machines where EEVEE can't run headless). Spark X shows the image and the
    model can look at it."""
    engine = os.environ.get("SPARKX_ENGINE") or engine
    sc = bpy.context.scene
    if sc.camera is None:
        add_camera()
    sc.render.resolution_x, sc.render.resolution_y = int(size[0]), int(size[1])
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    path = os.path.abspath(path or os.path.join(OUT, "render_%d.png" % (len(_SPARKX["images"]) + 1)))
    sc.render.filepath = path
    engines = [_engine_id(engine)] + (["CYCLES"] if _engine_id(engine) != "CYCLES" else [])
    for eng in engines:
        try:
            sc.render.engine = eng
            if eng == "CYCLES":
                sc.cycles.samples = int(samples)
                sc.cycles.use_denoising = True
            elif "EEVEE" in eng:
                try:
                    sc.eevee.taa_render_samples = int(samples)
                except Exception:
                    pass
            bpy.ops.render.render(write_still=True)
            break
        except Exception as e:
            print("SPARKX_WARN: %s render failed: %s" % (eng, e))
            if eng == engines[-1]:
                raise
    _SPARKX["images"].append(path)
    print("SPARKX_IMAGE:" + path)
    return path

def save(path=None):
    """Save the scene as a .blend file."""
    path = os.path.abspath(path or os.environ.get("SPARKX_SAVE") or os.path.join(OUT, "scene.blend"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=path)
    _SPARKX["saved"] = path
    print("SPARKX_SAVED:" + path)
    return path
'''

BLENDER_EPILOGUE = r'''
if os.environ.get("SPARKX_SAVE") and not _SPARKX["saved"]:
    save()
'''

BLENDER_TOOL_DESC = (
    "Make and edit 3D scenes in Blender with Python (bpy). action 'run' executes code in a "
    "background Blender and returns its output plus any rendered image; action 'live' runs code "
    "inside the Blender window the user has open (needs the Spark X bridge add-on — see 'status'); "
    "'open' opens a .blend in Blender; 'install_bridge' installs the bridge add-on. Helpers "
    "available in 'run': clear_scene(), material(name, color, metallic, roughness, emission, "
    "strength), assign(obj, mat), add_camera(location, target, lens), add_sun(strength, rotation), "
    "add_area_light(location, size, power, target), look_at(obj, target), render(path=None, "
    "engine='EEVEE', samples=64, size=(1280, 720)) and save(path=None); OUT is an output folder. "
    "Build scenes with bpy.ops/bpy.data, call render() to check your work, look at the render and "
    "iterate, then save().")


def _blender_bin():
    cfg = os.environ.get("BLENDER_PATH") or _pref("blender_path")
    if cfg and Path(cfg).is_file():
        return str(cfg)
    w = shutil.which("blender")
    if w:
        return w
    cands = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
            if base:
                cands += sorted(Path(base, "Blender Foundation").glob("Blender*/blender.exe"),
                                key=lambda p: [int(x) if x.isdigit() else 0 for x in re.findall(r"\d+", p.parent.name)],
                                reverse=True)
        cands.append(Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                          "Steam", "steamapps", "common", "Blender", "blender.exe"))
    elif sys.platform == "darwin":
        cands += [Path("/Applications/Blender.app/Contents/MacOS/Blender"),
                  Path.home() / "Applications/Blender.app/Contents/MacOS/Blender"]
    else:
        cands += [Path("/snap/bin/blender"), Path("/usr/bin/blender"), Path("/usr/local/bin/blender")]
        cands += sorted(Path.home().glob("blender*/blender"), reverse=True)
        cands += sorted(Path("/opt").glob("blender*/blender"), reverse=True)
    for c in cands:
        if c.is_file():
            return str(c)
    return None


_BLENDER_VER = {}

def _blender_version(exe):
    if exe in _BLENDER_VER:
        return _BLENDER_VER[exe]
    ver = ""
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30,
                             errors="replace").stdout
        m = re.search(r"Blender\s+([\d.]+[^\n]*)", out)
        ver = m.group(1).strip() if m else ""
    except Exception:
        pass
    _BLENDER_VER[exe] = ver
    return ver


def _bridge_file():
    return Path.home() / ".sparkx" / "blender-bridge.json"


def _bridge_info():
    info = jload(_bridge_file(), None)
    if not info or not info.get("port") or not info.get("token"):
        return None
    return info


def _bridge_call(code, screenshot=False, timeout=180):
    info = _bridge_info()
    if not info:
        raise RuntimeError("Blender isn't connected. Open Blender with the Spark X bridge add-on enabled "
                           "(blender action 'install_bridge'), then try again.")
    import socket as _sock
    try:
        s = _sock.create_connection(("127.0.0.1", int(info["port"])), timeout=4)
    except OSError:
        raise RuntimeError("Blender isn't running (or the Spark X bridge add-on is disabled).")
    with s:
        s.settimeout(timeout)
        s.sendall((json.dumps({"token": info["token"], "code": code, "screenshot": bool(screenshot),
                               "timeout": timeout}) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf.decode("utf-8", "replace") or "{}")


def _bridge_up():
    info = _bridge_info()
    if not info:
        return False
    try:
        import socket as _sock
        with _sock.create_connection(("127.0.0.1", int(info["port"])), timeout=0.6):
            return True
    except OSError:
        return False


def _bridge_addon_path():
    base = _studio_static_dir()
    p = (base.parent / "blender" / "spark_x_bridge.py") if base else None
    return p if p and p.is_file() else None


def _blender_status():
    exe = _blender_bin()
    info = _bridge_info() or {}
    return {"found": bool(exe), "path": exe or "", "version": _blender_version(exe) if exe else "",
            "bridge": {"connected": _bridge_up(), "blender": info.get("blender", ""), "port": info.get("port")},
            "addon": str(_bridge_addon_path() or "")}


def _blender_run(code, blend_file=None, save_as=None, timeout=600):
    exe = _blender_bin()
    if not exe:
        return {"text": "[Blender isn't installed (or not found). Install it from blender.org, or set its "
                        "path in Settings → Computer use.]"}
    job = APP_D / "blender" / time.strftime("%Y%m%d-%H%M%S")
    job.mkdir(parents=True, exist_ok=True)
    script = job / "script.py"
    script.write_text(BLENDER_PRELUDE + "\n# ── model code ──\n" + str(code) + "\n" + BLENDER_EPILOGUE,
                      encoding="utf-8")
    argv = [exe, "--background"]
    if blend_file:
        bf = Path(blend_file).expanduser()
        if not bf.is_file():
            return {"text": f"[no such .blend file: {bf}]"}
        argv.append(str(bf))
    else:
        argv.append("--factory-startup")
    argv += ["-noaudio", "--python-exit-code", "1", "--python", str(script)]
    env = dict(os.environ, SPARKX_OUT=str(job), SPARKX_SAVE=str(save_as or ""), PYTHONIOENCODING="utf-8")
    headless_linux = sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if headless_linux:
        env["SPARKX_ENGINE"] = "CYCLES"          # EEVEE needs a GPU context
    note = ""
    for attempt in (1, 2):
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env,
                               cwd=str(job), errors="replace")
        except subprocess.TimeoutExpired:
            return {"text": f"[Blender didn't finish within {timeout}s]"}
        out = (r.stdout or "") + (r.stderr or "")
        # EEVEE without a usable GPU context aborts Blender outright (no Python
        # error to catch), so run the script again rendering with Cycles.
        if (attempt == 1 and r.returncode != 0 and "SPARKX_IMAGE:" not in out and "render(" in str(code)
                and env.get("SPARKX_ENGINE") != "CYCLES"
                and re.search(r"EGL|OpenGL|GLX|GPU|gpu backend|Vulkan|Metal", out, re.I)):
            env["SPARKX_ENGINE"] = "CYCLES"
            note = "EEVEE isn't available here, so this was rendered with Cycles."
            continue
        break
    images = re.findall(r"^SPARKX_IMAGE:(.+)$", out, re.M)
    saved = re.findall(r"^SPARKX_SAVED:(.+)$", out, re.M)
    noise = re.compile(r"^(Fra:\d+|Blender \d|Read prefs|Warning: .*(fontconfig|egl)|Color management|"
                       r"SPARKX_(IMAGE|SAVED):|\s*$|Saved \"|Time: \d|Blender quit)")
    lines = [ln for ln in out.splitlines() if not noise.match(ln)]
    parts = [f"Blender exited with code {r.returncode}."] + ([note] if note else [])
    if saved:
        parts.append("Saved: " + saved[-1].strip())
    if images:
        parts.append("Rendered: " + ", ".join(i.strip() for i in images))
    parts.append("Output folder: " + str(job))
    if lines:
        parts.append("Log:\n" + "\n".join(lines[-40:]))
    return {"text": "\n".join(parts)[:MAX_TOOL_OUTPUT],
            "image": images[-1].strip() if images and Path(images[-1].strip()).is_file() else None}


def _blender_install_bridge():
    exe = _blender_bin()
    src = _bridge_addon_path()
    if not exe:
        raise RuntimeError("Blender wasn't found")
    if not src:
        raise RuntimeError("the bridge add-on file is missing from this build")
    expr = ("import bpy\n"
            "try:\n"
            f"    bpy.ops.preferences.addon_install(filepath={str(src)!r}, overwrite=True)\n"
            "    bpy.ops.preferences.addon_enable(module='spark_x_bridge')\n"
            "    bpy.ops.wm.save_userpref()\n"
            "    print('SPARKX_OK')\n"
            "except Exception as e:\n"
            "    print('SPARKX_FAIL', e)\n")
    r = subprocess.run([exe, "--background", "-noaudio", "--python-expr", expr], capture_output=True,
                       text=True, timeout=180, errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    if "SPARKX_OK" not in out:
        m = re.search(r"SPARKX_FAIL (.+)", out)
        raise RuntimeError(m.group(1) if m else (out.strip().splitlines() or ["install failed"])[-1])
    return "Installed and enabled the Spark X bridge. Restart Blender (or open it) and it connects automatically."


def _t_blender(a, cwd=None):
    act = str(a.get("action") or "run").lower()
    if act == "status":
        st = _blender_status()
        if not st["found"]:
            return "Blender isn't installed or wasn't found. Get it from https://www.blender.org/download/"
        b = st["bridge"]
        return (f"Blender {st['version'] or ''} at {st['path']}. Live bridge: "
                + ("connected" + (f" (Blender {b['blender']})" if b.get("blender") else "")
                   if b["connected"] else "not connected — open Blender with the Spark X bridge add-on "
                                         "(action 'install_bridge' installs it)."))
    if act == "run":
        code = a.get("code") or ""
        if not code.strip():
            return "[blender run: give Python code]"
        return _blender_run(code, a.get("blend_file"), a.get("save_as"),
                            timeout=int(a.get("timeout", 600) or 600))
    if act == "live":
        res = _bridge_call(a.get("code") or "", screenshot=bool(a.get("screenshot", True)))
        txt = ("ok" if res.get("ok") else "error") + "\n" + (res.get("output") or "")
        if res.get("result"):
            txt += "\nresult: " + str(res["result"])
        if res.get("error"):
            txt += "\n" + str(res["error"])
        img = res.get("image")
        return {"text": txt[:MAX_TOOL_OUTPUT], "image": img if img and Path(img).is_file() else None}
    if act == "open":
        exe = _blender_bin()
        if not exe:
            return "[Blender wasn't found]"
        target = a.get("path") or a.get("blend_file") or ""
        subprocess.Popen([exe] + ([str(Path(target).expanduser())] if target else []), **_detached())
        return "opened Blender" + (f" with {target}" if target else "")
    if act == "install_bridge":
        return _blender_install_bridge()
    return f"[unknown blender action '{act}': use run, live, status, open or install_bridge]"


TOOLS_IMPL.update({"computer": _t_computer, "open": _t_open, "blender": _t_blender})


# ── tool schemas for native function calling ─────────────────────────────────
def _obj(props, required=()):
    return {"type": "object", "properties": props, "required": list(required)}

def _s(desc):
    return {"type": "string", "description": desc}

def _i(desc):
    return {"type": "integer", "description": desc}


_SHELL_NAME = "cmd.exe" if os.name == "nt" else ("zsh/bash" if sys.platform == "darwin" else "bash")

STUDIO_TOOLS = {
    "bash": (f"Run a shell command ({_SHELL_NAME}) in the working folder; returns output and exit code.",
             _obj({"cmd": _s("The command to run")}, ["cmd"])),
    "read": ("Read a text file (numbered chunk).",
             _obj({"path": _s("File path"), "offset": _i("First line, 0-based"), "limit": _i("Max lines (default 200)")}, ["path"])),
    "write": ("Create or overwrite a file with the given content.",
              _obj({"path": _s("File path"), "content": _s("Full file content")}, ["path", "content"])),
    "edit": ("Replace exact text in a file (read it first).",
             _obj({"path": _s("File path"), "old": _s("Exact text to replace"), "new": _s("Replacement text"),
                   "all": {"type": "boolean", "description": "Replace every occurrence"}}, ["path", "old", "new"])),
    "ls": ("List a directory.", _obj({"path": _s("Directory (default: working folder)")})),
    "glob": ("Find files matching a glob pattern.", _obj({"pattern": _s("e.g. **/*.py"), "root": _s("Folder to search")}, ["pattern"])),
    "grep": ("Search file contents with a regular expression.",
             _obj({"pattern": _s("Regex"), "root": _s("Folder"), "glob": _s("File glob, e.g. **/*.js")}, ["pattern"])),
    "python": ("Run a Python snippet and return what it prints.", _obj({"code": _s("Python code")}, ["code"])),
    "browse": ("Open a web page and return its readable text.", _obj({"url": _s("URL")}, ["url"])),
    "download": ("Download a URL to a file.", _obj({"url": _s("URL"), "path": _s("Where to save it")}, ["url", "path"])),
    "computer": (
        "Use the computer like a person: see the screen and control the mouse and keyboard. Start with "
        "action 'screenshot'. x/y are pixels in the most recent screenshot. After each action you get a "
        "fresh screenshot to check the result.",
        _obj({"action": {"type": "string", "enum": ["screenshot", "click", "double_click", "right_click",
                                                    "middle_click", "move", "drag", "scroll", "type", "key",
                                                    "wait", "cursor_position"]},
              "x": _i("x in screenshot pixels"), "y": _i("y in screenshot pixels"),
              "to_x": _i("drag end x"), "to_y": _i("drag end y"),
              "text": _s("text to type"), "keys": _s("key or combination, e.g. 'enter', 'ctrl+s', 'cmd+space'"),
              "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
              "amount": _i("scroll steps (default 5)"), "seconds": {"type": "number", "description": "seconds to wait"}},
             ["action"])),
    "open": ("Open a file, folder, URL or application (e.g. 'blender', 'notepad', 'Safari', 'https://…').",
             _obj({"target": _s("Path, URL or app name")}, ["target"])),
    "blender": (BLENDER_TOOL_DESC,
                _obj({"action": {"type": "string", "enum": ["run", "live", "status", "open", "install_bridge"]},
                      "code": _s("Python (bpy) code for 'run' or 'live'"),
                      "blend_file": _s("Optional .blend to open before 'run'"),
                      "save_as": _s("Optional .blend path to save to after 'run'"),
                      "path": _s(".blend file for 'open'"),
                      "screenshot": {"type": "boolean", "description": "'live': also return a viewport screenshot"}},
                     ["action"])),
}


def _tool_schemas(names, mcp_tools):
    """OpenAI `tools` for the enabled tools, plus a name map back to ours."""
    tools, name_map = [], {}
    for n in names:
        if n in STUDIO_TOOLS:
            desc, params = STUDIO_TOOLS[n]
            tools.append({"type": "function", "function": {"name": n, "description": desc, "parameters": params}})
            name_map[n] = n
    for t in mcp_tools:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", t["qualified"])[:64]
        schema = t.get("schema") or {"type": "object", "properties": {}}
        if schema.get("type") != "object":
            schema = {"type": "object", "properties": {}}
        tools.append({"type": "function", "function": {"name": safe,
                                                       "description": (t.get("description") or t["name"])[:1000],
                                                       "parameters": schema}})
        name_map[safe] = t["qualified"]
    return tools, name_map


def _data_url(path):
    p = Path(path)
    mime = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


_SHOT_MARK = "Current screen (after your last action):"


def _drop_old_images(msgs, keep=1):
    """Keep only the newest `keep` screenshots in the conversation sent to the
    model: they are large and older ones are no longer useful. Images the
    user attached are never touched."""
    seen = 0
    for m in reversed(msgs):
        c = m.get("content")
        if m.get("role") != "user" or not isinstance(c, list) or not c:
            continue
        first = c[0]
        if not (first.get("type") == "text" and str(first.get("text", "")).startswith(_SHOT_MARK)):
            continue
        parts = []
        for part in c:
            if part.get("type") == "image_url":
                seen += 1
                if seen > keep:
                    part = {"type": "text", "text": "[earlier screenshot omitted]"}
            parts.append(part)
        m["content"] = parts


# ── the agentic chat stream ──────────────────────────────────────────────────
def _demo_reply(messages):
    last = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last = str(m.get("content", "")); break
    low = last.lower()
    if re.search(r"\b(html|page|website|landing|artifact|ui)\b", low):
        return ("Here's a small page to show how **artifacts** work. It opens in the panel on "
                "the right, where you can switch between the live preview and the code.\n\n"
                "```html\n<!doctype html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
                "<title>Hello from Spark X</title>\n<style>\n  body { margin: 0; min-height: 100vh; "
                "display: grid; place-items: center;\n         background: #1f1e1c; color: #ecebe6; "
                "font: 16px Georgia, serif; }\n  .card { padding: 40px 48px; border: 1px solid "
                "#3a3833; border-radius: 16px; text-align: center; }\n  h1 { font-weight: 400; "
                "margin: 0 0 8px; }\n  button { margin-top: 20px; padding: 10px 18px; border: 0; "
                "border-radius: 10px;\n           background: #c9794f; color: #fff; font: 600 14px "
                "system-ui; cursor: pointer; }\n</style>\n</head>\n<body>\n  <div class=\"card\">\n"
                "    <h1>Hello from Spark X</h1>\n    <p>Built by the demo model.</p>\n"
                "    <button onclick=\"this.textContent='Clicked'\">Click me</button>\n  </div>\n"
                "</body>\n</html>\n```\n\nThis is the built-in demo, so it can't really reason. "
                "Connect a free provider in **Settings → Providers** or set up a local model to "
                "get real answers.")
    if re.search(r"\b(python|code|function|script)\b", low):
        return ("A tiny example from the demo model:\n\n```python\ndef fib(n: int) -> list[int]:\n"
                "    a, b, out = 0, 1, []\n    for _ in range(n):\n        out.append(a)\n"
                "        a, b = b, a + b\n    return out\n\nprint(fib(10))\n```\n\n"
                "For real coding help, open **Code** in the sidebar and set up a local coding "
                "model, or connect a free cloud provider.")
    return ("I'm **Spark Echo**, the built-in demo model — I don't run a neural network, so I can "
            "only echo. You said:\n\n> " + (last.replace("\n", "\n> ") or "…") + "\n\n"
            "To get real answers:\n\n"
            "- **Free model, no signup** — pick *Free model* in the model menu (or Settings → "
            "Providers). Groq, Google Gemini and OpenRouter also have free tiers with a key.\n"
            "- **Local models** — Settings → Models suggests models for your computer and "
            "installs them with Ollama.\n"
            "- **Ollama / LM Studio** — detected automatically when running.")

def _demo_stream(messages):
    for tok in re.findall(r"\s+|\S+", _demo_reply(messages)):
        yield tok


def _text_only(hist):
    out = []
    for m in hist:
        c = m.get("content")
        if isinstance(c, list):
            c = "\n".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
        out.append({"role": m.get("role"), "content": c or ""})
    return out


def _prep_history(msgs, vision):
    hist = []
    for m in msgs:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = str(m.get("content") or "")
        images = []
        for a in (m.get("attachments") or [])[:10]:
            if a.get("type") == "image" and a.get("data_url"):
                if vision:
                    images.append(a["data_url"])
                else:
                    content += f"\n\n[image attached: {a.get('name', 'image')} — this model can't see images]"
            elif a.get("type") == "text":
                content += (f"\n\n<file name=\"{a.get('name', 'file')}\">\n"
                            f"{str(a.get('content', ''))[:80000]}\n</file>")
        if images and role == "user":
            hist.append({"role": "user", "content": [{"type": "text", "text": content}]
                         + [{"type": "image_url", "image_url": {"url": u}} for u in images]})
        else:
            hist.append({"role": role, "content": content})
    return hist


def _tool_args_hint(params):
    out = []
    for k, v in (params.get("properties") or {}).items():
        t = "|".join(v["enum"]) if v.get("enum") else {"integer": "int", "number": "num", "boolean": "bool"}.get(v.get("type"), "str")
        out.append(f"{k}:{t}")
    return "{" + ", ".join(out) + "}"


def _studio_system(ctx, tools, mcp_tools, cwd, mode, native=False, vision=False):
    now = _dt.datetime.now().strftime("%A, %d %B %Y")
    os_name = {"win32": "Windows", "darwin": "macOS"}.get(sys.platform, "Linux")
    base = (ctx.get("system") or "").strip()
    parts = [f"You are {APP_UI}, a capable, precise assistant running on {CS_USER}'s {os_name} "
             f"computer. Today is {now}."]
    if base and base != DEFAULT_CONTEXT.get("system"):
        parts.append(base)
    if CFG.get("prefs", {}).get("artifacts", True):
        parts.append("When you write a complete web page, SVG, or a substantial standalone "
                     "program, put it in one fenced code block tagged with its language "
                     "(```html, ```svg, ```python …). Web pages must be complete HTML documents.")
    if mode == "code":
        parts.append(f"You are working in the project folder {cwd}. Explore with ls/glob/grep "
                     "and read files before changing them. Prefer 'edit' for small changes. "
                     "Keep explanations short.")
    if "computer" in tools:
        parts.append("You can operate this computer. The `computer` tool shows you the screen and "
                     "controls the mouse and keyboard, `open` launches apps, files and URLs, and "
                     "`bash` runs commands. Take a screenshot first, work one step at a time and check "
                     "each new screenshot before the next step. Prefer keyboard shortcuts, `open` and "
                     "`bash` over hunting for buttons. Ask the user before anything destructive or "
                     "irreversible (deleting files, sending messages, payments).")
        if not vision:
            parts.append("This model can't see images, so screenshots won't help: rely on `open`, "
                         "`bash` and keyboard shortcuts.")
    if "blender" in tools:
        parts.append("For 3D work use the `blender` tool with Python (bpy) rather than clicking "
                     "through Blender's interface: build the scene in code, call render() and look at "
                     "the image, refine it, then save() a .blend. If the user has Blender open with "
                     "the Spark X bridge, use action 'live' to build directly in their scene. Target "
                     "Blender 4.x/5.x APIs.")
    if (tools or mcp_tools) and not native:
        lines = [f"- {n}: {STUDIO_TOOLS[n][0]} args={_tool_args_hint(STUDIO_TOOLS[n][1])}"
                 for n in tools if n in STUDIO_TOOLS]
        for t in mcp_tools:
            props = json.dumps((t.get("schema") or {}).get("properties", {}))[:400]
            lines.append(f"- {t['qualified']}: {t.get('description', '')[:300]} args={props}")
        parts.append(
            "You can use tools. To call one, reply with a single JSON object wrapped in "
            "<tool>...</tool>, for example:\n<tool>{\"name\":\"read\",\"args\":{\"path\":\"README.md\"}}</tool>\n"
            "Then stop and wait for the <tool_result>. Make one tool call at a time. When you "
            "have what you need, answer normally without a <tool> block.\nTools:\n" + "\n".join(lines))
    return "\n\n".join(parts)


class _Cancelled(Exception):
    pass


def _needs_approval(name, args, is_mcp):
    if is_mcp:
        return True
    if name == "computer":
        return str(args.get("action", "screenshot")).lower() not in _CU_READONLY
    if name == "blender":
        return str(args.get("action", "run")).lower() != "status"
    return name in _APPROVAL_TOOLS


def _studio_run_tool(name, args, cwd, enabled, mcp_tools, allowed_always, send, state):
    mcp = next((t for t in mcp_tools if t["qualified"] == name or t["name"] == name), None)
    if not mcp and name not in enabled:
        return f"[tool '{name}' is not enabled]", None
    ask = CFG.get("prefs", {}).get("tool_approval", "ask") == "ask"
    needs = ask and _needs_approval(name, args, mcp is not None) and name not in allowed_always
    if needs:
        aid = uuid.uuid4().hex[:10]
        ev = threading.Event()
        _APPROVALS[aid] = {"event": ev, "allow": False, "always": False}
        send({"type": "approval", "id": aid, "name": name, "args": args})
        waited = 0.0
        while not ev.wait(0.5):
            waited += 0.5
            if state["cancel"] or waited > 900:
                break
        info = _APPROVALS.pop(aid, {})
        if state["cancel"]:
            raise _Cancelled()
        if not info.get("allow"):
            return "[the user declined this tool call]", None
        if info.get("always"):
            allowed_always.add(name)
    # get Spark X out of the way once the model may act freely on the screen
    if (name == "computer" and _pref("computer_minimize", True) and not state.get("minimized")
            and (not ask or name in allowed_always)):
        state["minimized"] = _self_window("minimize")
        if state["minimized"]:
            time.sleep(0.45)
    try:
        if mcp:
            srv = next((s for s in _mcp_cfg_load().get("servers", []) if s.get("id") == mcp["server"]), None)
            if not srv:
                return "[MCP server no longer configured]", None
            return _mcp_get_client(srv).call_tool(mcp["name"], args), None
        out = TOOLS_IMPL[name](args, cwd=cwd)
    except Exception as e:
        if type(e).__name__ == "FailSafeException":        # mouse slammed into a screen corner
            state["cancel"] = True
            send({"type": "token", "text": "\n\nStopped: you moved the mouse into a corner of the screen."})
            raise _Cancelled() from e
        return f"[tool error: {e}]", None
    if isinstance(out, dict):
        img = out.get("image")
        return str(out.get("text", "")), (img if img and Path(img).is_file() else None)
    out = str(out)
    image = None
    if name == "screen":
        m = re.search(r"screenshot:\s*(\S+\.(?:png|jpg))", out)
        if m and Path(m.group(1)).is_file():
            image = m.group(1)
    return out, image


def _file_token_url(path):
    tok, _ = _studio_tokens()
    return "/api/file?path=" + urllib.parse.quote(str(path)) + "&t=" + tok


_NO_NATIVE = set()

def _rec_key(rec):
    return rec.name


def _native_tools_ok(rec):
    meta = rec.meta or {}
    if _rec_key(rec) in _NO_NATIVE or (CFG.get("platforms", {}).get(meta.get("platform"), {}) or {}).get("no_tools"):
        return False
    if meta.get("platform") == "ollama":
        caps = _OLLAMA["caps"].get(meta.get("model"))
        if caps is not None and caps and "tools" not in caps:
            return False
    return True


def _forward(kind, val, send, state, buf):
    if kind == "text":
        buf.append(val); state["output"] = True
        send({"type": "token", "text": val})
    elif kind == "think":
        send({"type": "think", "text": val})
    elif kind == "provider":
        send({"type": "provider", "name": val})


def _run_calls(calls, run, results_to):
    """Execute tool calls, stream their events; return screenshot paths."""
    images = []
    for c in calls:
        cid = uuid.uuid4().hex[:8]
        name = c["name"]
        try:
            args = _parse_tool_args(c.get("arguments", {}))
        except ValueError as e:
            args, result, image = {}, f"[invalid tool arguments: {e}]", None
            run["send"]({"type": "tool_call", "id": cid, "name": name, "args": {}})
        else:
            run["send"]({"type": "tool_call", "id": cid, "name": name, "args": args})
            result, image = _studio_run_tool(name, args, run["cwd"], run["enabled"], run["mcp_tools"],
                                             run["allowed"], run["send"], run["state"])
        result = str(result)[:MAX_TOOL_OUTPUT]
        run["send"]({"type": "tool_result", "id": cid, "name": name, "result": result,
                     "image": _file_token_url(image) if image else None})
        results_to(c, name, result)
        if image:
            images.append(image)
        if run["state"]["cancel"]:
            break
    return images


def _agent_native(msgs, run):
    """Agent loop with the provider's native function calling."""
    tools_param, name_map = _tool_schemas(run["enabled"], run["mcp_tools"])
    rec, rt, ctx, state, send = run["rec"], run["rt"], run["ctx"], run["state"], run["send"]
    for _ in range(run["rounds"]):
        buf, calls = [], []
        for kind, val in rt.chat(rec, msgs, ctx, tools_param):
            if state["cancel"]:
                break
            if kind == "tool_calls":
                calls = val
            else:
                _forward(kind, val, send, state, buf)
        text = "".join(buf)
        if state["cancel"]:
            return
        if not calls:                       # some models still print a <tool> block
            for raw in _TOOL_RX.findall(text)[:3]:
                try:
                    j = json.loads(raw)
                    calls.append({"id": "call_" + uuid.uuid4().hex[:10], "name": str(j.get("name", "")),
                                  "arguments": json.dumps(j.get("args") or j.get("arguments") or {})})
                except Exception:
                    pass
            if not calls:
                return
        msgs.append({"role": "assistant", "content": text,
                     "tool_calls": [{"id": c["id"], "type": "function",
                                     "function": {"name": c["name"], "arguments": c.get("arguments") or "{}"}}
                                    for c in calls]})
        for c in calls:
            c["name"] = name_map.get(c["name"], c["name"])

        def add(c, name, result):
            msgs.append({"role": "tool", "tool_call_id": c["id"], "name": name, "content": result or "(no output)"})

        images = _run_calls(calls[:8], run, add)
        if images and run["vision"]:
            _drop_old_images(msgs, keep=0)
            msgs.append({"role": "user", "content": [{"type": "text", "text": _SHOT_MARK},
                                                     {"type": "image_url", "image_url": {"url": _data_url(images[-1])}}]})
    send({"type": "token", "text": "\n\n*Reached the step limit for one message — say “continue” to keep going.*"})


def _agent_text(hist, run):
    """Agent loop with the <tool>{json}</tool> text protocol (local models and
    endpoints without function calling)."""
    rec, rt, ctx, state, send = run["rec"], run["rt"], run["ctx"], run["state"], run["send"]
    for _ in range(run["rounds"]):
        buf = []
        if run["is_api"]:
            for kind, val in rt.chat(rec, hist, ctx):
                if state["cancel"]:
                    break
                _forward(kind, val, send, state, buf)
        else:
            for c in rt.stream(rec, build_prompt(_text_only(hist), ctx), _text_only(hist), ctx):
                if state["cancel"]:
                    break
                _forward("text", c, send, state, buf)
        text = "".join(buf)
        hist.append({"role": "assistant", "content": text})
        if state["cancel"] or not (run["enabled"] or run["mcp_tools"]):
            return
        calls = []
        for raw in _TOOL_RX.findall(text)[:3]:
            try:
                j = json.loads(raw)
                calls.append({"name": str(j.get("name", "")), "arguments": j.get("args") or j.get("arguments") or {}})
            except Exception as e:
                calls.append({"name": "invalid", "arguments": f"not JSON: {e}"})
        if not calls:
            return
        results = []
        images = _run_calls(calls, run, lambda c, name, result: results.append(
            f"<tool_result name=\"{name}\">{result}</tool_result>"))
        body = "\n".join(results)
        if images and run["vision"] and run["is_api"]:
            _drop_old_images(hist, keep=0)
            hist.append({"role": "user", "content": [{"type": "text", "text": _SHOT_MARK + "\n" + body},
                                                     {"type": "image_url", "image_url": {"url": _data_url(images[-1])}}]})
        else:
            hist.append({"role": "user", "content": body})
    send({"type": "token", "text": "\n\n*Reached the step limit for one message — say “continue” to keep going.*"})


def _app_chat_stream(handler, body):
    model = body.get("model") or DEMO_MODEL_ID
    raw_msgs = list(body.get("messages", []))
    tools_cfg = body.get("tools") or {}
    if isinstance(tools_cfg, bool):
        tools_cfg = {"code": tools_cfg}
    mode = body.get("mode") or "chat"
    cwd = body.get("cwd") or str(Path.home())
    sid = _safe_id(body.get("stream_id")) or uuid.uuid4().hex[:10]
    state = _STREAMS[sid] = {"cancel": False, "minimized": False, "output": False}
    handler._sse()

    def send(ev):
        handler.wfile.write(b"data: " + json.dumps(ev).encode() + b"\n\n")
        handler.wfile.flush()

    try:
        send({"type": "start", "stream_id": sid})
        if model == DEMO_MODEL_ID:
            for tok in _demo_stream(raw_msgs):
                if state["cancel"]: break
                send({"type": "token", "text": tok}); time.sleep(0.006)
            send({"type": "done", "stopped": state["cancel"]}); return

        rec = match_model(model)
        if not rec:
            send({"type": "error", "error": f"Model not found: {model}"}); send({"type": "done"}); return
        rt = pick_runtime(rec)
        if not rt:
            send({"type": "error", "error": f"No runtime can run {rec.name}. Open Settings → Models to install one."})
            send({"type": "done"}); return
        is_api = rec.kind == "platform"
        meta = rec.meta or {}
        if meta.get("platform") == "ollama" and meta.get("model"):
            _ollama_caps(meta["model"])
        vision = is_api and _rec_vision(rec)
        enabled = []
        for key in ("code", "web", "computer", "blender"):
            if tools_cfg.get(key):
                enabled += [t for t in _TOOLSETS[key] if t in TOOLS_IMPL and t not in enabled]
        mcp_ids = tools_cfg.get("mcp") or []
        mcp_tools = _mcp_all_tools(mcp_ids) if mcp_ids else []
        ctx = dict(get_context(rec))
        if is_api and int(ctx.get("max_new_tokens", 512)) == int(DEFAULT_CONTEXT["max_new_tokens"]):
            ctx["max_new_tokens"] = 4096
        allowed = {t for t in (body.get("allowed") or []) if isinstance(t, str)}
        heavy = tools_cfg.get("computer") or tools_cfg.get("blender") or mcp_tools
        run = {"rec": rec, "rt": rt, "ctx": ctx, "enabled": enabled, "mcp_tools": mcp_tools, "cwd": cwd,
               "send": send, "state": state, "allowed": allowed, "vision": vision, "is_api": is_api,
               "rounds": AGENT_MAX_ROUNDS if heavy else MAX_TOOL_ROUNDS}
        hist = _prep_history(raw_msgs, vision)
        native = is_api and bool(enabled or mcp_tools) and _native_tools_ok(rec)
        ctx["system"] = _studio_system(ctx, enabled, mcp_tools, cwd, mode, native=native, vision=vision)
        if native:
            try:
                _agent_native(list(hist), run)
            except ProviderError as e:
                if not (_tools_unsupported(e) and not state["output"]):
                    raise
                _NO_NATIVE.add(_rec_key(rec))            # endpoint has no function calling
                ctx["system"] = _studio_system(ctx, enabled, mcp_tools, cwd, mode, native=False, vision=vision)
                _agent_text(hist, run)
        else:
            _agent_text(hist, run)
        if run["allowed"]:
            send({"type": "allowed", "tools": sorted(run["allowed"])})
        send({"type": "done", "stopped": state["cancel"]})
    except _Cancelled:
        try: send({"type": "done", "stopped": True})
        except Exception: pass
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        pass
    except ProviderError as e:
        try:
            send({"type": "error", "error": str(e)[:600]}); send({"type": "done"})
        except Exception:
            pass
    except Exception as e:
        log_exc("studio chat")
        try:
            send({"type": "error", "error": str(e)[:600]}); send({"type": "done"})
        except Exception:
            pass
    finally:
        if state.get("minimized"):
            _self_window("restore")
        _STREAMS.pop(sid, None)


# ── routines scheduler ───────────────────────────────────────────────────────
_APP_SCHED = {"stop": False, "thread": None}

def _routine_due(r, now):
    if not r.get("enabled", True): return False
    last = r.get("last_run") or 0
    every = r.get("every_minutes")
    if every:
        try: return (now - last) >= float(every) * 60
        except Exception: return False
    at = r.get("at_time")
    if at and ":" in at:
        lt = _dt.datetime.fromtimestamp(now)
        try: hh, mm = [int(x) for x in at.split(":")[:2]]
        except Exception: return False
        return lt.hour == hh and lt.minute == mm and (now - last) > 55
    return False

def _routine_run(r):
    model = r.get("model") or DEMO_MODEL_ID
    prompt = r.get("prompt", "")
    out = []
    try:
        if model == DEMO_MODEL_ID:
            out = list(_demo_stream([{"role": "user", "content": prompt}]))
        else:
            rec = match_model(model); rt = pick_runtime(rec) if rec else None
            if rec and rt:
                ctx = get_context(rec)
                hist = [{"role": "user", "content": prompt}]
                for c in rt.stream(rec, build_prompt(hist, ctx), hist, ctx):
                    out.append(c)
            else:
                out = ["[model unavailable]"]
    except Exception as e:
        out = ["[error: " + str(e) + "]"]
    r["last_run"] = time.time(); r["last_output"] = "".join(out)[:6000]
    r.setdefault("history", []).insert(0, {"ts": r["last_run"], "output": r["last_output"][:1500]})
    r["history"] = r["history"][:10]
    return r["last_output"]

def _sched_loop():
    while not _APP_SCHED["stop"]:
        try:
            items = _routines_load(); now = time.time(); changed = False
            for r in items:
                if _routine_due(r, now):
                    log(f"routine run: {r.get('name')}"); _routine_run(r); changed = True
            if changed: _routines_save(items)
        except Exception as e:
            log(f"sched: {e}", "warn")
        for _ in range(30):
            if _APP_SCHED["stop"]: break
            time.sleep(1)

def _start_scheduler():
    if _APP_SCHED["thread"]: return
    _APP_SCHED["stop"] = False
    t = threading.Thread(target=_sched_loop, daemon=True); t.start()
    _APP_SCHED["thread"] = t


# ── JSON API ─────────────────────────────────────────────────────────────────
def _local_server_ok():
    try:
        return bool(LlamaServerRT().available()[0])
    except Exception:
        return False


def _q1(q, k, d=""):
    return (q.get(k) or [d])[0]


def _app_get(handler):
    u = urllib.parse.urlparse(handler.path); path = u.path
    q = urllib.parse.parse_qs(u.query)
    if path == "/api/browse":
        _, btok = _studio_tokens()
        import hmac
        if not (_studio_host_ok(handler) and hmac.compare_digest(_q1(q, "bt"), btok)):
            return handler._json(403, {"error": "forbidden"})
        return _browse_response(handler, _q1(q, "url", "about:blank"))
    if not _studio_authorized(handler, q):
        return handler._json(403, {"error": "forbidden"})
    try:
        return _app_get_routes(handler, path, q)
    except (PermissionError, ValueError, FileNotFoundError, NotADirectoryError) as e:
        return handler._json(400, {"error": str(e)})


def _app_get_routes(handler, path, q):
    if path == "/api/state":
        _autodetect_local()
        prefs = CFG.get("prefs", {})
        return handler._json(200, {
            "version": VERSION, "codename": CODENAME, "user": CS_USER,
            "platform": sys.platform, "frozen": bool(getattr(sys, "frozen", False)),
            "models": _model_info_list(), "runtimes": _runtime_info_list(),
            "providers": _provider_public(), "prefs": prefs, "home": str(Path.home()),
            "cwd": str(Path.cwd()), "demo_model": DEMO_MODEL_ID,
            "computer": _computer_status(), "coder_presets": CODER_PRESETS,
            "recent_projects": prefs.get("recent_projects", [])[:8],
            "mcp_gallery": MCP_GALLERY, "claude_desktop_config": str(_claude_desktop_mcp_path()),
            "local_server": _local_server_ok(), "app": APP_UI, "free_enabled": _free_enabled(),
            "ollama": {"installed": bool(_ollama_bin()), "running": _ollama_version(0.8) is not None},
            "blender_found": bool(_blender_bin()), "native_window": _WEBVIEW.get("window") is not None,
            "hardware": _hardware()})
    if path == "/api/ollama":
        return handler._json(200, _ollama_status())
    if path == "/api/catalog":
        return handler._json(200, _catalog_view())
    if path == "/api/catalog/trending":
        try:
            return handler._json(200, {"models": _hf_trending()})
        except Exception as e:
            return handler._json(200, {"models": [], "error": str(e)[:200]})
    if path == "/api/free":
        return handler._json(200, {"enabled": _free_enabled(),
                                   "providers": _free_probe(force=_q1(q, "force") == "1")})
    if path == "/api/blender":
        return handler._json(200, _blender_status())
    if path == "/api/models":
        return handler._json(200, {"models": _model_info_list()})
    if path == "/api/providers":
        return handler._json(200, {"providers": _provider_public()})
    if path == "/api/context":
        rec = match_model(_q1(q, "model"))
        if not rec: return handler._json(404, {"error": "model not found"})
        return handler._json(200, {"model": rec.name, "context": get_context(rec)})
    if path == "/api/routines":
        return handler._json(200, {"routines": _routines_load()})
    if path == "/api/mcp":
        return handler._json(200, _mcp_cfg_load())
    if path == "/api/chats":
        return handler._json(200, {"chats": _chats_list()})
    if path.startswith("/api/chats/"):
        c = _chat_load(path.rsplit("/", 1)[-1])
        return handler._json(200 if c else 404, c or {"error": "not found"})
    if path == "/api/artifacts":
        return handler._json(200, {"artifacts": _artifacts_list()})
    if path == "/api/fs/list":
        return handler._json(200, {"entries": _fs_list(_q1(q, "root"), _q1(q, "path"))})
    if path == "/api/fs/read":
        return handler._json(200, _fs_read(_q1(q, "root"), _q1(q, "path")))
    if path == "/api/fs/dirs":
        return handler._json(200, _fs_dirs(_q1(q, "path")))
    if path == "/api/reader":
        final, ctype, raw = _web_get(_q1(q, "url"))
        title, text = _html_to_text(_decode_html(raw, ctype)) if "html" in ctype.lower() else ("", "")
        return handler._json(200, {"url": final, "title": title, "text": text[:60000]})
    if path.startswith("/api/jobs/"):
        job = _JOBS.get(path.rsplit("/", 1)[-1])
        return handler._json(200 if job else 404, _job_public(job) if job else {"error": "not found"})
    if path == "/api/jobs":
        return handler._json(200, {"jobs": [_job_public(j) for j in _JOBS.values()]})
    if path == "/api/file":
        p = Path(_q1(q, "path")).resolve()
        allowed = [_ensure_screen_dir().resolve(), APP_D.resolve()]
        if not any(a in p.parents for a in allowed) or not p.is_file():
            return handler._json(404, {"error": "not found"})
        data = p.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", _STATIC_TYPES.get(p.suffix.lower(), "application/octet-stream"))
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers(); handler.wfile.write(data)
        return
    return handler._json(404, {"error": "not found"})


def _app_post(handler, path, body):
    if not _studio_authorized(handler):
        return handler._json(403, {"error": "forbidden"})
    try:
        return _app_post_routes(handler, path, body)
    except (PermissionError, ValueError, FileNotFoundError, NotADirectoryError,
            RuntimeError, TimeoutError) as e:
        return handler._json(400, {"error": str(e)})


def _app_post_routes(handler, path, body):
    if path == "/api/chat":
        return _app_chat_stream(handler, body)
    if path == "/api/chat/stop":
        st = _STREAMS.get(_safe_id(body.get("stream_id")))
        if st: st["cancel"] = True
        return handler._json(200, {"ok": True})
    if path == "/api/approve":
        info = _APPROVALS.get(str(body.get("id")))
        if not info:
            return handler._json(404, {"error": "no such approval"})
        info["allow"] = bool(body.get("allow")); info["always"] = bool(body.get("always"))
        info["event"].set()
        return handler._json(200, {"ok": True})
    if path == "/api/context":
        rec = match_model(body.get("model"))
        if not rec: return handler._json(404, {"error": "model not found"})
        ctx = get_context(rec); ctx.update(body.get("context", {})); set_context(rec, ctx)
        return handler._json(200, {"ok": True, "context": ctx})
    if path == "/api/prefs":
        CFG.setdefault("prefs", {}).update(body.get("prefs", {})); save_cfg()
        return handler._json(200, {"ok": True, "prefs": CFG["prefs"]})
    if path == "/api/providers/connect":
        pid, pc = _provider_connect(body.get("id", ""), body.get("key", ""),
                                    body.get("base_url", ""), body.get("name", ""))
        return handler._json(200, {"ok": True, "id": pid, "models": pc.get("models", []),
                                   "warning": pc.get("error", "")})
    if path == "/api/providers/disconnect":
        CFG.get("platforms", {}).pop(str(body.get("id")), None); save_cfg()
        return handler._json(200, {"ok": True})
    if path == "/api/providers/refresh":
        pid = str(body.get("id")); pc = CFG.get("platforms", {}).get(pid)
        if not pc: return handler._json(404, {"error": "not connected"})
        pc["models"] = _fetch_models(pc["base_url"], pc.get("key"), pid); pc["error"] = ""; save_cfg()
        return handler._json(200, {"ok": True, "models": pc["models"]})
    if path == "/api/scan":
        load_scan(rescan=True)
        return handler._json(200, {"ok": True, "models": _model_info_list()})
    if path == "/api/routines":
        items = _routines_load(); r = body.get("routine", {})
        r["id"] = _safe_id(r.get("id")) or uuid.uuid4().hex[:8]
        items = [x for x in items if x.get("id") != r["id"]] + [r]
        _routines_save(items); return handler._json(200, {"ok": True, "routines": items})
    if path == "/api/routines/run":
        items = _routines_load()
        for r in items:
            if r.get("id") == body.get("id"):
                out = _routine_run(r); _routines_save(items)
                return handler._json(200, {"ok": True, "output": out, "routine": r})
        return handler._json(404, {"error": "not found"})
    if path == "/api/routines/delete":
        items = [x for x in _routines_load() if x.get("id") != body.get("id")]
        _routines_save(items); return handler._json(200, {"ok": True, "routines": items})
    if path == "/api/mcp":
        cfg = _mcp_cfg_load(); s = dict(body.get("server", {}))
        if not s.get("command"): raise ValueError("command is required")
        s["id"] = (_safe_id(s.get("id")) or
                   re.sub(r"[^a-z0-9-]+", "-", (s.get("name") or "server").lower()).strip("-")
                   or uuid.uuid4().hex[:6])
        s.setdefault("enabled", True)
        cfg["servers"] = [x for x in cfg.get("servers", []) if x.get("id") != s["id"]] + [s]
        old = _MCP_CLIENTS.pop(s["id"], None)
        if old: old.stop()
        _mcp_cfg_save(cfg); return handler._json(200, {"ok": True, **cfg})
    if path == "/api/mcp/delete":
        cfg = _mcp_cfg_load(); sid = body.get("id")
        cfg["servers"] = [x for x in cfg.get("servers", []) if x.get("id") != sid]
        old = _MCP_CLIENTS.pop(sid, None)
        if old: old.stop()
        _mcp_cfg_save(cfg); return handler._json(200, {"ok": True, **cfg})
    if path == "/api/mcp/tools":
        try: return handler._json(200, {"tools": _mcp_all_tools(body.get("ids"))})
        except Exception as e: return handler._json(200, {"tools": [], "error": str(e)})
    if path == "/api/mcp/import":
        return handler._json(200, {"ok": True, "added": _mcp_import_claude_desktop(), **_mcp_cfg_load()})
    if path == "/api/chats":
        cid = _chat_save(dict(body.get("chat", {})))
        return handler._json(200, {"ok": True, "id": cid})
    if path == "/api/chats/delete":
        _chat_delete(body.get("id")); return handler._json(200, {"ok": True})
    if path == "/api/fs/write":
        size = _fs_write(body.get("root"), body.get("path"), str(body.get("content", "")))
        return handler._json(200, {"ok": True, "size": size})
    if path == "/api/project/open":
        root = Path(str(body.get("root", ""))).expanduser()
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("not a folder: " + str(root))
        prefs = CFG.setdefault("prefs", {})
        rec = [str(root.resolve())] + [p for p in prefs.get("recent_projects", []) if p != str(root.resolve())]
        prefs["recent_projects"] = rec[:10]; save_cfg()
        return handler._json(200, {"ok": True, "root": str(root.resolve()), "entries": _fs_list(str(root.resolve()))})
    if path == "/api/setup/coder":
        return handler._json(200, _job_public(_coder_setup(body.get("preset", "small"))))
    if path == "/api/install":
        target = str(body.get("target", ""))
        if not re.match(r"^[\w.-]+$", target): raise ValueError("bad target")
        return handler._json(200, _job_public(_job_start("Install " + target, [["install", target]])))
    if path == "/api/pull":
        repo = str(body.get("repo", "")).strip()
        if not re.match(r"^[\w.-]+/[\w.-]+$", repo): raise ValueError("use the form owner/repo")
        steps = [["pull", repo] + (["--only", str(body["only"])] if body.get("only") else []), ["scan"]]
        return handler._json(200, _job_public(_job_start("Download " + repo, steps,
                                                         watch_dir=DL_D / "hf" / repo.replace("/", "__"))))
    if path == "/api/computer/screenshot":
        try:
            shot, w, h = _cu_capture()
        except Exception as e:
            return handler._json(400, {"error": f"couldn't take a screenshot: {e}"})
        return handler._json(200, {"ok": True, "url": _file_token_url(shot), "path": shot, "width": w, "height": h})
    if path == "/api/ollama/start":
        ok, msg = _ollama_start()
        return handler._json(200 if ok else 400, {"ok": ok, "message": msg, **({} if ok else {"error": msg})})
    if path == "/api/ollama/pull":
        return handler._json(200, _job_public(_ollama_pull(body.get("model", ""))))
    if path == "/api/ollama/delete":
        _ollama_delete(str(body.get("model", "")))
        return handler._json(200, {"ok": True})
    if path == "/api/free/enable":
        res = _free_enable()
        return handler._json(200, {"ok": True, "providers": res, "working": any(x.get("ok") for x in res)})
    if path == "/api/free/disable":
        CFG.get("platforms", {}).pop("free", None)
        if _pref("default_model") == "free/auto":
            CFG["prefs"].pop("default_model", None)
        save_cfg()
        return handler._json(200, {"ok": True})
    if path == "/api/blender/install_bridge":
        return handler._json(200, {"ok": True, "message": _blender_install_bridge()})
    if path == "/api/blender/open":
        return handler._json(200, {"ok": True, "message": _t_blender({"action": "open", "path": body.get("path", "")})})
    if path == "/api/jobs/cancel":
        job = _JOBS.get(str(body.get("id")))
        if job:
            job["cancel"] = True
        return handler._json(200, {"ok": bool(job)})
    return handler._json(404, {"error": "not found"})


# ── desktop launch: a chromeless app window when possible ────────────────────
def _find_app_browser():
    names = []
    if os.name == "nt":
        pf = [os.environ.get(k, "") for k in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
        for base in pf:
            if not base: continue
            names += [Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                      Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe",
                      Path(base) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"]
    elif sys.platform == "darwin":
        names += [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                  Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                  Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
                  Path("/Applications/Chromium.app/Contents/MacOS/Chromium")]
    for n in names:
        if n.is_file():
            return str(n)
    for n in ("microsoft-edge", "google-chrome", "google-chrome-stable", "chromium",
              "chromium-browser", "brave-browser", "msedge", "chrome"):
        p = shutil.which(n)
        if p:
            return p
    return None


def _open_app_window(url):
    """Returns a Popen for a dedicated app window, or None."""
    exe = _find_app_browser()
    if not exe:
        return None
    profile = APP_D / "window-profile"
    profile.mkdir(parents=True, exist_ok=True)
    args = [exe, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1280,860",
            "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"]
    try:
        return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return None


def _launched_from_desktop():
    """True when the packaged app was double-clicked rather than run from a
    terminal, so it should open the graphical app instead of the TUI."""
    if not getattr(sys, "frozen", False):
        return False
    if os.name == "nt":
        try:
            import ctypes
            ids = (ctypes.c_uint * 8)()
            n = ctypes.windll.kernel32.GetConsoleProcessList(ids, 8)
            # onefile = bootloader + app; a shell would make it 3 or more
            return 0 < n <= 2
        except Exception:
            return False
    return not _interactive()


def _hide_console():
    if os.name != "nt":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def _studio_healthy(url):
    try:
        with _urlopen(urllib.request.Request(url.rstrip("/") + "/health"), 1.5) as r:
            return bool(json.loads(r.read() or b"{}").get("ok"))
    except Exception:
        return False


def _studio_background():
    """Keep Ollama alive, find which free models answer, refresh the catalog —
    all in the background so the window opens immediately."""
    threading.Thread(target=_ollama_watchdog, daemon=True, name="ollama-watchdog").start()

    def warm():
        if os.environ.get("SPARKX_OFFLINE"):
            return
        try:
            real = [m for m in _model_info_list() if m.get("kind") != "demo" and m.get("ready")
                    and m.get("provider") != "free"]
            if _free_enabled() or not real:
                _free_probe()
        except Exception as e:
            log(f"warm-up: {e}", "warn")
        try:
            _catalog()
        except Exception:
            pass
    threading.Thread(target=warm, daemon=True, name="warm-up").start()


def _webview_start(webview, func=None):
    store = APP_D / "webview"
    store.mkdir(parents=True, exist_ok=True)
    kw = {"private_mode": False, "storage_path": str(store)}   # keep settings between launches
    if os.name == "nt":
        kw["gui"] = "edgechromium"                            # never fall back to old IE
    webview.start(func, **kw) if func else webview.start(**kw)


def _native_window(url):
    """Open Spark X in a real app window (pywebview: WebView2 on Windows,
    WebKit on macOS). Blocks until it's closed; False when unavailable."""
    if os.environ.get("SPARKX_NO_NATIVE"):
        return False
    if sys.platform.startswith("linux") and not any(importlib.util.find_spec(m) for m in ("gi", "qtpy")):
        return False                    # pywebview needs GTK or Qt bindings on Linux
    try:
        import webview
    except Exception:
        return False
    try:
        win = webview.create_window(APP_UI, url, width=1280, height=860, min_size=(960, 620),
                                    background_color="#1f1e1d", text_select=True)
        _WEBVIEW["window"] = win
        _webview_start(webview)
        return True
    except Exception as e:
        log(f"native window unavailable: {e}", "warn")
        return False
    finally:
        _WEBVIEW["window"] = None


def _smoke_run(url):
    """Boot the real window, wait for the app to report ready, then close.
    Used by CI to prove the packaged app works end to end."""
    res = {"url": url, "native": False, "ready": False}
    try:
        import webview
        win = webview.create_window(APP_UI, url, width=1100, height=760, background_color="#1f1e1d")
        _WEBVIEW["window"] = win

        def check():
            try:
                res["loaded"] = bool(win.events.loaded.wait(90))
                for _ in range(120):
                    if win.evaluate_js("!!(window.__spark && window.__spark.ready)"):
                        res["ready"] = True
                        break
                    time.sleep(0.5)
                res["title"] = win.evaluate_js("document.title")
                res["models"] = win.evaluate_js("window.__spark ? window.__spark.models : -1")
                res["native"] = True
            except Exception as e:
                res["error"] = f"{type(e).__name__}: {e}"
            finally:
                try:
                    win.destroy()
                except Exception:
                    pass
        _webview_start(webview, check)
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {e}"
    txt = json.dumps(res)
    out = os.environ.get("SPARKX_SMOKE_OUT")
    if out:
        Path(out).write_text(txt, encoding="utf-8")
    print(txt)
    return 0 if res.get("ready") else 1


def cmd_studio(host="127.0.0.1", port=8799, open_ui=True, model=None, hide_console=False, smoke=False):
    _app_dirs(); _start_scheduler(); _studio_tokens()
    if model:
        rec = match_model(model)
        if rec: _SERVE["rec"] = rec
    url_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    try:
        srv = _QuietHTTPServer((host, port), _ServeHandler)
    except OSError:
        existing = f"http://{url_host}:{port}/"
        if not smoke and _studio_healthy(existing):
            print(YL + f"  {APP_UI} is already running at {existing}" + RSTC)
            if open_ui and not _native_window(existing) and not _open_app_window(existing):
                import webbrowser; webbrowser.open(existing)
            return
        srv = _QuietHTTPServer((host, 0), _ServeHandler)      # port taken by something else
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _studio_background()
    url = f"http://{url_host}:{port}/"
    print(MG + f"  {APP_UI}  " + RSTC + url)
    print(DIM + "  chat · code · computer · blender · browser · artifacts — Ctrl-C to quit" + RSTC)
    if smoke:
        code = _smoke_run(url)
        _APP_SCHED["stop"] = True; srv.shutdown()
        sys.exit(code)
    window = None
    if open_ui:
        if hide_console:
            _hide_console()
        if _native_window(url):                                # blocks until closed
            _APP_SCHED["stop"] = True; srv.shutdown(); return
        window = _open_app_window(url)
        if not window:
            try:
                import webbrowser; webbrowser.open(url)
            except Exception:
                pass
    started = time.time()
    try:
        while True:
            time.sleep(1)
            if window is not None and window.poll() is not None:
                # A browser that exits within seconds handed the window to an
                # already-running instance; keep serving. Otherwise the user
                # closed the app window, so quit.
                if time.time() - started > 8:
                    break
                window = None
    except KeyboardInterrupt:
        print(YL + "  ⌁ stopped" + RSTC)
    finally:
        _APP_SCHED["stop"] = True; srv.shutdown()


def _is_gui_exe():
    """The packaged 'Spark X' app executable (as opposed to the `cs` CLI)."""
    if not getattr(sys, "frozen", False):
        return False
    return re.sub(r"[\s_-]", "", Path(sys.executable).stem.lower()) == "sparkx"


def gui_main():
    """Start Spark X in its own window: the packaged `Spark X` app and the
    `spark-x` command (pip install) both land here."""
    try:
        no_terminal = getattr(sys, "frozen", False) and not sys.stdout.isatty()
    except Exception:
        no_terminal = True
    if _NO_CONSOLE or no_terminal:            # started from Finder / Start menu: log to a file
        LOGS_D.mkdir(parents=True, exist_ok=True)
        f = open(LOGS_D / "spark-x.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = f
    args = sys.argv[1:]
    port = 8799
    if "--port" in args:
        try:
            port = int(args[args.index("--port") + 1])
        except (IndexError, ValueError):
            pass
    cmd_studio(port=port, open_ui=True, smoke="--smoke" in args)


# ─── commands ──────────────────────────────────────────────────────────────
def match_model(q):
    if not q: return None
    recs = load_scan() + platform_records()
    for r in recs:                      # exact id wins over fuzzy matching
        if r.name == q:
            return r
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
    """Package cs.py (when running from source) + cs_data into a portable zip."""
    here = _app_dir()
    frozen = getattr(sys, "frozen", False)
    if archive is None:
        archive = here / f"cs-portable-{_dt.date.today().isoformat()}.zip"
    archive = Path(archive)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        if not frozen:
            z.write(Path(__file__).resolve(), "cs.py")
        for f in DATA_HOME.rglob("*"):
            if f.is_file() and not any(x in f.parts for x in ("tools","downloads","cache")):
                try: z.write(f, str(Path("cs_data") / f.relative_to(DATA_HOME)))
                except Exception: pass
    print(GR + f"  v wrote {archive}" + RSTC)
    if frozen:
        print(DIM + "  data only (running from a binary); ship the cs executable "
              "alongside it." + RSTC)
    else:
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

def cmd_platforms():
    """List the remote API platforms you can connect and their status."""
    print()
    print("  " + BOLD + "connectable platforms" + RSTC)
    connected = CFG.get("platforms", {})
    for name in sorted(PLATFORM_DEFS):
        d = PLATFORM_DEFS[name]
        mark = (GR + "connected" + RSTC) if name in connected else (DIM + "—" + RSTC)
        nokey = DIM + " (no key needed)" + RSTC if d.get("no_key") else ""
        print(f"    {name:11} {DIM}{d.get('base_url',''):34}{RSTC} {mark}{nokey}")
    print()
    print(DIM + "  connect with:  cs connect <platform>" + RSTC)


# ─── CLI ───────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--py-exec":
        _py_exec(sys.argv[2:]); return
    if _is_gui_exe():
        gui_main(); return
    ap = build_cli()
    a = ap.parse_args()

    # commands that must work with zero prior setup and no TTY
    if a.cmd == "version":
        print(f"{APP_LONG} {VERSION} ({CODENAME})"); return
    if a.cmd == "install-self": install_self(); return
    if a.cmd == "logo": show_logo(); return
    if a.cmd == "selftest": sys.exit(selftest())

    # First-launch setup. Skipped for read-only commands that need no runtimes,
    # and never blocks a non-interactive shell (CI / pipe / packaged binary).
    _NO_SETUP = {"list", "scan", "doctor", "verify", "ll-log", "bonsai-setup",
                 "config", "perms", "fix", "platforms", "ps", "clean",
                 "plugin-init", "export", "install", "connect", "rm",
                 "serve", "stop", "studio"}
    if a.cmd not in (None, "setup") and a.cmd not in _NO_SETUP \
            and not CFG.get("setup_done"):
        if _interactive():
            print(YL + "first launch — running setup" + RSTC); setup(); print()
        else:
            setup(quiet=True)
    if a.cmd is None:
        if _launched_from_desktop():
            cmd_studio(hide_console=True); return
        if not CFG.get("setup_done") and _interactive():
            print(YL + "first launch — running setup" + RSTC); setup(); print()
        chooser(); return

    if a.cmd == "setup": setup(a.full, a.quiet)
    elif a.cmd == "scan": cmd_scan()
    elif a.cmd == "list": cmd_list()
    elif a.cmd == "chatgpt":
        cmd_chatgpt(a.model, getattr(a, "port", 8686), getattr(a, "no_launch", False))
    elif a.cmd == "claude":
        cmd_claude(a.model, getattr(a, "port", 8687), getattr(a, "no_launch", False))
    elif a.cmd == "opencode":
        cmd_opencode(a.model, getattr(a, "port", 8688), getattr(a, "no_launch", False))
    elif a.cmd == "unconnect":
        cmd_unconnect(a.target)
    elif a.cmd == "connect":
        install_target(a.platform)
    elif a.cmd == "pull":
        cmd_pull(a.name, getattr(a, "only", None))
    elif a.cmd == "rm":
        cmd_rm(a.model)
    elif a.cmd == "ps":
        cmd_ps()
    elif a.cmd == "rig":
        cmd_rig()
    elif a.cmd == "platforms":
        cmd_platforms()
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
        cmd_stop(getattr(a, "target", None))
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
    elif a.cmd == "doctor": cmd_doctor(getattr(a, "deep", False))
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
    elif a.cmd == "studio": cmd_studio(a.host, a.port, not getattr(a, "no_open", False), a.model, smoke=getattr(a, "smoke", False))
    elif a.cmd == "agents": cmd_agents(a.action, a.agent, a.model)
    elif a.cmd == "plugin-init": cmd_plugin_init(a.name)
    elif a.cmd == "clean": cmd_clean(a.downloads)
    elif a.cmd == "export": cmd_export(a.archive)
    else: ap.print_help()


# === CS-CANONICAL-BEGIN ===
# TUI, computer-use, and coding-agent helpers.
# (These markers are retained for reference; the file is now maintained by
#  hand and covered by the test suite — edit freely.)

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
    # pyautogui imports mouseinfo, which calls sys.exit() on Linux when tkinter
    # is missing (the packaged app ships without tkinter). mouseinfo is only
    # an interactive helper, so give it a stand-in instead of dying.
    if "mouseinfo" not in sys.modules and importlib.util.find_spec("tkinter") is None:
        stub = types.ModuleType("mouseinfo")
        stub.MouseInfoWindow = lambda *a, **k: None
        sys.modules["mouseinfo"] = stub
    # python-xlib refuses to connect when there is no Xauthority file at all
    # (some Linux sessions don't create one); an empty one means "no auth".
    if sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
        xa = os.environ.get("XAUTHORITY") or str(Path.home() / ".Xauthority")
        if not Path(xa).exists():
            empty = Path(tempfile.gettempdir()) / "sparkx-empty-xauthority"
            try:
                empty.touch(exist_ok=True)
                os.environ["XAUTHORITY"] = str(empty)
            except OSError:
                pass
    try:
        import pyautogui as pg
        pg.FAILSAFE = True
        pg.PAUSE = 0.05
        return pg
    except (Exception, SystemExit):
        return None


def _ensure_screen_dir():
    d = DATA_HOME / "agent" / "screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mss_shot():
    try:
        import mss, mss.tools
        with (getattr(mss, "MSS", None) or mss.mss)() as sct:
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
    LOGS_D.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_D / ("cs-serve-" + str(port) + ".log")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        fh = open(log_path, "w", encoding="utf-8", errors="replace")
    except Exception:
        fh = subprocess.DEVNULL
    args = _self_invoke("serve", "--port", str(port))
    if model: args += ["--model", model]
    proc = subprocess.Popen(args, stdout=fh, stderr=subprocess.STDOUT,
                            cwd=str(_app_dir()), env=env)
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